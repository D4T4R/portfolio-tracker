"""Domain operations over the ledger.

Everything that mutates the portfolio goes through here so the invariants live
in one place:

* a ledger may never imply a negative holding at any point in time, not merely
  at the end - a back-dated sell can invalidate trades that already exist
* only a fully exited position can be archived
* dividends are valued against the holding on the ex-date, and only from
  dividend_start_date onward so migrated balances are not double counted
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from portfolio.ledger import (
    CorporateAction as LedgerAction,
    LedgerError,
    Position,
    RealizedSale,
    Transaction as LedgerTxn,
    TxnType,
    build_quantity_timeline,
    fifo,
    quantity_on_timeline,
    restate,
    weighted_average,
)
from portfolio.dividends import DividendFetchError, fetch_dividend_history
from portfolio.imports import ParsedRow
from portfolio.models import (
    CorporateAction,
    Counter,
    Dividend,
    Instrument,
    Portfolio,
    PriceSnapshot,
    Transaction,
)
from portfolio.splits import SplitFetchError, fetch_split_history
from portfolio.prices import (
    IST,
    MarketStatus,
    PriceFetchError,
    PriceResult,
    decide_refresh,
    fetch_quotes,
    last_settled_session,
)

ZERO = Decimal("0")

REFERENCE_COUNTER = "transaction_reference"

# How far a trade price may sit from a reference before it is treated as a
# data-entry error rather than history.
#
# Deliberately wide. A stock genuinely moves several-fold over years - ITC was
# bought at 370 and trades at 262, Tata Steel at 87 against 188 - so a tight
# band would reject real trades, which is worse than missing a typo. What this
# catches is the order-of-magnitude slip: a price typed as 1, or a decimal
# point lost, which lands 100x or more away from anything plausible.
IMPLAUSIBLE_PRICE_FACTOR = Decimal("20")


class ServiceError(Exception):
    """A request that cannot be satisfied. Safe to show the caller."""


class NotFound(ServiceError):
    pass


@dataclass
class DividendSyncResult:
    added: int
    updated: int
    symbols: int
    error: str | None = None


@dataclass
class PlannedTrade:
    """One import row after resolution, ready to show before anything is written."""

    row_number: int
    raw_symbol: str
    status: str                       # ok | new | duplicate | error
    txn_type: str | None = None
    trade_date: date | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    fees: Decimal = ZERO
    note: str | None = None
    reference: str | None = None
    symbol: str | None = None         # resolved Yahoo symbol
    instrument_id: str | None = None  # None when the row would create one
    instrument_name: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Tracked names this ticker nearly matches. Their presence means the row
    # is more likely a typo than a genuinely new holding, so the UI can make
    # creating the instrument an explicit choice rather than the default.
    suggestions: list[str] = field(default_factory=list)
    # Applicable, but suspicious enough that it should not be applied unless
    # the user deliberately says so.
    needs_review: bool = False

    @property
    def applies(self) -> bool:
        return self.status in ("ok", "new")


@dataclass
class ImportPlan:
    rows: list[PlannedTrade]

    def _count(self, status: str) -> int:
        return sum(1 for r in self.rows if r.status == status)

    @property
    def applicable(self) -> list[PlannedTrade]:
        return [r for r in self.rows if r.applies]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "total": len(self.rows),
            "ok": self._count("ok"),
            "new": self._count("new"),
            "duplicate": self._count("duplicate"),
            "error": self._count("error"),
        }

    @property
    def new_symbols(self) -> list[str]:
        seen = {r.symbol for r in self.rows if r.status == "new" and r.symbol}
        return sorted(seen)


@dataclass
class Holding:
    """An instrument together with everything derived from its ledger."""

    instrument: Instrument
    position: Position
    dividend_income: Decimal
    market_price: Decimal | None = None

    @property
    def market_value(self) -> Decimal:
        if self.market_price is None:
            return ZERO
        return self.position.quantity * self.market_price

    @property
    def unrealized(self) -> Decimal:
        if self.market_price is None:
            return ZERO
        return self.market_value - self.position.cost_basis

    @property
    def total_profit(self) -> Decimal:
        """Unrealized + realized + dividends, each counted exactly once."""
        return self.unrealized + self.position.realized_gain + self.dividend_income

    @property
    def total_return_pct(self) -> Decimal:
        # Measured against all capital ever deployed, so realized gains sit
        # over the basis that produced them.
        if self.position.total_invested <= ZERO:
            return ZERO
        return self.total_profit * 100 / self.position.total_invested


def _to_ledger(txns: list[Transaction], instrument=None) -> list[LedgerTxn]:
    """Ledger rows on the current share basis.

    Passing the instrument applies its splits and bonuses. Without it the rows
    come back exactly as stored, which is what validation of a newly submitted
    trade wants - the user typed today's share count, not a historical one.
    """
    rows = [
        LedgerTxn(
            trade_date=t.trade_date,
            txn_type=TxnType(t.txn_type),
            quantity=Decimal(t.quantity),
            price=Decimal(t.price),
            fees=Decimal(t.fees or 0),
            txn_id=t.id,
        )
        for t in txns
    ]
    if instrument is None:
        return rows
    return restate(rows, _actions_for(instrument))


def _actions_for(instrument) -> list[LedgerAction]:
    """Actions that still need applying to this instrument's stored figures.

    Anything auto-synced from the feed on or before basis_date is already
    reflected in what was stored, and replaying it would double-count.

    Manually recorded actions are exempt, because recording one by hand is an
    explicit statement that it has *not* been applied. That distinction is
    load-bearing for demergers: the migrated workbook listed the demerged
    company as a separate holding with its own invented cost, so the shares
    were captured but the parent's cost was never reduced. Judging that by
    date alone would skip the correction entirely.
    """
    basis = getattr(instrument, "basis_date", None)
    return [
        LedgerAction(
            ex_date=a.ex_date,
            ratio=Decimal(a.ratio),
            action_type=a.action_type,
        )
        for a in getattr(instrument, "corporate_actions", [])
        if basis is None or a.ex_date > basis or a.source == "manual"
    ]


class PortfolioService:
    """Operations against one portfolio.

    The scope lives here rather than at each call site: every query filters on
    ``portfolio_id``, so a route cannot forget to and accidentally serve one
    book's holdings to another.
    """

    def __init__(self, session: Session, portfolio_id: str | None = None):
        self.session = session
        self._portfolio_id = portfolio_id

    # ----------------------------------------------------------- portfolios

    @property
    def portfolio_id(self) -> str:
        """The portfolio in scope, falling back to the default one."""
        if self._portfolio_id is None:
            self._portfolio_id = self.default_portfolio().id
        return self._portfolio_id

    def default_portfolio(self) -> Portfolio:
        """The portfolio used when a request names none.

        Created on demand so a fresh database is usable without a setup step.
        """
        portfolio = self.session.scalar(
            select(Portfolio).where(Portfolio.is_default.is_(True))
        )
        if portfolio is None:
            portfolio = self.session.scalar(
                select(Portfolio).order_by(Portfolio.created_at)
            )
        if portfolio is None:
            portfolio = Portfolio(name="My portfolio", is_default=True)
            self.session.add(portfolio)
            self.session.flush()
        return portfolio

    def list_portfolios(self) -> list[Portfolio]:
        self.default_portfolio()   # ensure at least one exists
        return list(
            self.session.scalars(select(Portfolio).order_by(Portfolio.created_at))
        )

    def get_portfolio(self, portfolio_id: str) -> Portfolio:
        portfolio = self.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise NotFound(f"no portfolio {portfolio_id}")
        return portfolio

    def create_portfolio(self, name: str) -> Portfolio:
        name = (name or "").strip()
        if not name:
            raise ServiceError("portfolio name is required")
        existing = self.session.scalar(
            select(Portfolio).where(func.lower(Portfolio.name) == name.lower())
        )
        if existing is not None:
            raise ServiceError(f"a portfolio called {name!r} already exists")

        first = self.session.scalar(select(Portfolio).limit(1)) is None
        portfolio = Portfolio(name=name, is_default=first)
        self.session.add(portfolio)
        self.session.flush()
        return portfolio

    def rename_portfolio(self, portfolio_id: str, name: str) -> Portfolio:
        portfolio = self.get_portfolio(portfolio_id)
        name = (name or "").strip()
        if not name:
            raise ServiceError("portfolio name is required")
        clash = self.session.scalar(
            select(Portfolio).where(
                func.lower(Portfolio.name) == name.lower(),
                Portfolio.id != portfolio_id,
            )
        )
        if clash is not None:
            raise ServiceError(f"a portfolio called {name!r} already exists")
        portfolio.name = name
        self.session.flush()
        return portfolio

    def delete_portfolio(self, portfolio_id: str) -> None:
        """Remove a portfolio and everything in it.

        Refuses while it still holds trades: deleting cascades to instruments
        and their whole history, which is not something to do by mis-click.
        """
        portfolio = self.get_portfolio(portfolio_id)
        if len(self.list_portfolios()) == 1:
            raise ServiceError("cannot delete the only portfolio")

        trades = self.session.scalar(
            select(func.count())
            .select_from(Transaction)
            .join(Instrument, Instrument.id == Transaction.instrument_id)
            .where(Instrument.portfolio_id == portfolio_id)
        )
        if trades:
            raise ServiceError(
                f"{portfolio.name} still holds {trades} trades; "
                "empty it before deleting"
            )

        was_default = portfolio.is_default
        self.session.delete(portfolio)
        self.session.flush()
        if was_default:
            # Something must answer a request that names no portfolio.
            remaining = self.session.scalar(
                select(Portfolio).order_by(Portfolio.created_at)
            )
            if remaining is not None:
                remaining.is_default = True
                self.session.flush()

    # ---------------------------------------------------------- instruments

    def get_instrument(self, instrument_id: str) -> Instrument:
        instrument = self.session.get(Instrument, instrument_id)
        # Checked against the scope, not merely fetched: without this, an id
        # from one portfolio would be readable and editable through another.
        if instrument is None or instrument.portfolio_id != self.portfolio_id:
            raise NotFound(f"no instrument {instrument_id}")
        return instrument

    def find_by_symbol(self, symbol: str) -> Instrument | None:
        return self.session.scalar(
            select(Instrument).where(
                Instrument.symbol == symbol.upper(),
                Instrument.portfolio_id == self.portfolio_id,
            )
        )

    def list_instruments(self, include_archived: bool = False) -> list[Instrument]:
        stmt = (
            select(Instrument)
            .where(Instrument.portfolio_id == self.portfolio_id)
            .options(
                selectinload(Instrument.transactions),
                selectinload(Instrument.dividends),
                selectinload(Instrument.corporate_actions),
            )
        )
        if not include_archived:
            stmt = stmt.where(Instrument.status == "active")
        return list(self.session.scalars(stmt.order_by(Instrument.name)))

    def add_instrument(self, symbol: str, name: str) -> Instrument:
        """Register a stock so trades can be recorded against it (point 4)."""
        symbol = symbol.strip().upper()
        name = name.strip()
        if not symbol:
            raise ServiceError("symbol is required")
        if not name:
            raise ServiceError("name is required")

        if self.find_by_symbol(symbol) is not None:
            raise ServiceError(f"{symbol} is already tracked")

        instrument = Instrument(
            portfolio_id=self.portfolio_id,
            symbol=symbol,
            name=name,
            status="active",
        )
        self.session.add(instrument)
        self.session.flush()
        return instrument

    def archive_instrument(self, instrument_id: str) -> Instrument:
        """Retire a fully exited position.

        Refuses while shares are still held: archiving an open position would
        drop it out of the portfolio totals while its capital is still at risk.
        """
        instrument = self.get_instrument(instrument_id)
        position = self.position_for(instrument)

        if position.quantity > ZERO:
            raise ServiceError(
                f"{instrument.symbol} still holds {position.quantity} shares; "
                "record the closing sale before archiving"
            )

        instrument.status = "archived"
        self.session.flush()
        return instrument

    def unarchive_instrument(self, instrument_id: str) -> Instrument:
        instrument = self.get_instrument(instrument_id)
        instrument.status = "active"
        self.session.flush()
        return instrument

    # --------------------------------------------------------- transactions

    def record_transaction(
        self,
        instrument_id: str,
        txn_type: str | TxnType,
        trade_date: date,
        quantity: Decimal,
        price: Decimal,
        fees: Decimal = ZERO,
        note: str | None = None,
    ) -> Transaction:
        """Register a purchase or sale (point 2).

        The trade is validated against the *whole* ledger, not just the current
        holding, because a back-dated sell can leave a later trade unmatched.
        """
        instrument = self.get_instrument(instrument_id)
        txn_type = TxnType(txn_type)

        quantity = Decimal(quantity)
        price = Decimal(price)
        fees = Decimal(fees or 0)

        if quantity <= ZERO:
            raise ServiceError("quantity must be greater than zero")
        if price < ZERO:
            raise ServiceError("price cannot be negative")
        if fees < ZERO:
            raise ServiceError("fees cannot be negative")
        if trade_date > date.today():
            raise ServiceError("trade date cannot be in the future")

        candidate = LedgerTxn(trade_date, txn_type, quantity, price, fees)
        self._assert_ledger_valid(
            # Restated: the quantity just typed is in today's shares, so the
            # history it is checked against has to be too.
            _to_ledger(instrument.transactions, instrument) + [candidate],
            instrument.symbol,
        )

        txn = Transaction(
            reference=self.next_references(1)[0],
            instrument_id=instrument.id,
            txn_type=txn_type.value,
            trade_date=trade_date,
            quantity=quantity,
            price=price,
            fees=fees,
            note=note,
        )
        self.session.add(txn)

        # A buy on an archived name means it has been re-entered.
        if instrument.is_archived and txn_type is TxnType.BUY:
            instrument.status = "active"

        self.session.flush()
        self.session.refresh(instrument)
        return txn

    def next_references(self, count: int) -> list[str]:
        """Allocate the next N trade references, never reusing a retired one.

        Held in a counter rather than derived from MAX(reference), which would
        rewind when the newest trade is deleted and hand the same number to a
        different trade. See Counter in models.py.
        """
        counter = self.session.get(Counter, REFERENCE_COUNTER)
        if counter is None:
            # A ledger written before the counter existed: start above whatever
            # is already there so a backfilled reference is never issued twice.
            highest = self.session.scalar(select(func.max(Transaction.reference)))
            start = 0
            if highest:
                try:
                    start = int(str(highest).rsplit("-", 1)[-1])
                except ValueError:
                    start = 0
            counter = Counter(name=REFERENCE_COUNTER, value=start)
            self.session.add(counter)

        first = counter.value + 1
        counter.value += count
        self.session.flush()
        return [f"TXN-{n:06d}" for n in range(first, first + count)]

    def all_transactions(self) -> list[Transaction]:
        """Every trade ever recorded, newest first, for the history view.

        Archived names are included: retiring a position hides it from the
        holdings table but does not unmake the trades that closed it.
        """
        stmt = (
            select(Transaction)
            .join(Instrument, Instrument.id == Transaction.instrument_id)
            .where(Instrument.portfolio_id == self.portfolio_id)
            .options(joinedload(Transaction.instrument))
            .order_by(
                Transaction.trade_date.desc(),
                # Two trades on one day still have an order they were entered
                # in; without this tiebreak the list reshuffles between loads.
                Transaction.created_at.desc(),
            )
        )
        return list(self.session.scalars(stmt))

    def delete_transaction(self, txn_id: str) -> None:
        """Remove a mistaken entry, provided the rest still reconciles."""
        txn = self.session.get(Transaction, txn_id)
        if txn is None:
            raise NotFound(f"no transaction {txn_id}")

        # get_instrument enforces the portfolio scope, so a transaction id
        # belonging to another book resolves to a 404 rather than a deletion.
        instrument = self.get_instrument(txn.instrument_id)
        remaining = [t for t in instrument.transactions if t.id != txn_id]
        self._assert_ledger_valid(
            _to_ledger(remaining, instrument), instrument.symbol
        )

        self.session.delete(txn)
        self.session.flush()
        # The relationship collection is cached on the identity map, so without
        # this the deleted trade still counts toward the position.
        self.session.refresh(instrument)

    @staticmethod
    def _assert_ledger_valid(ledger: list[LedgerTxn], symbol: str) -> None:
        try:
            weighted_average(ledger)
        except LedgerError as exc:
            raise ServiceError(f"{symbol}: {exc}") from exc

    # ---------------------------------------------------------- bulk import

    def _resolve_symbol(
        self, raw: str, known: dict[str, Instrument]
    ) -> tuple[Instrument | None, str, list[str]]:
        """Map a spreadsheet ticker onto a tracked instrument.

        Returns the instrument (or None), the symbol to use, and any close
        matches worth showing. Fuzzy matches are never applied automatically:
        picking BAJFINANCE.NS for "bajfin" is a guess, and a wrong guess files
        a trade against the wrong company where it is unlikely to be noticed.
        """
        candidate = raw.strip().upper()

        if candidate in known:
            return known[candidate], candidate, []

        # NSE tickers carry a suffix that people leave off when typing.
        suffixed = f"{candidate}.NS"
        if suffixed in known:
            return known[suffixed], suffixed, []

        by_name = {i.name.strip().upper(): i for i in known.values()}
        if candidate in by_name:
            instrument = by_name[candidate]
            return instrument, instrument.symbol, []

        pool = list(known) + list(by_name)
        close = difflib.get_close_matches(candidate, pool, n=3, cutoff=0.6)
        suggestions = []
        for match in close:
            instrument = known.get(match) or by_name.get(match)
            if instrument and instrument.symbol not in suggestions:
                suggestions.append(instrument.symbol)

        return None, suffixed if "." not in candidate else candidate, suggestions

    def reference_price(
        self, instrument: Instrument, prices: dict[str, Decimal] | None = None
    ) -> Decimal | None:
        """A price to sanity-check an entry against, or None if there is none.

        Prefers the last stored close; falls back to what the position already
        cost. A brand new stock has neither, which is why its prices cannot be
        checked at import and are revisited once a close has been fetched.
        """
        prices = prices if prices is not None else self.stored_prices()[0]
        stored = prices.get(instrument.symbol)
        if stored is not None and Decimal(stored) > ZERO:
            return Decimal(stored)

        position = self.position_for(instrument)
        if position.average_cost > ZERO:
            return position.average_cost
        return None

    @staticmethod
    def price_deviation(price: Decimal, reference: Decimal) -> Decimal | None:
        """How many times apart two prices are, larger over smaller."""
        if price <= ZERO or reference <= ZERO:
            return None
        return price / reference if price > reference else reference / price

    def price_anomalies(self) -> list[dict]:
        """Recorded trades whose price no longer looks plausible.

        Run after a price refresh: a stock added by import has no reference
        price at the time, so an entry of 1 cannot be questioned until a real
        close exists. This is where that catches up.
        """
        prices, _ = self.stored_prices()
        found = []
        for instrument in self.list_instruments(include_archived=True):
            reference = prices.get(instrument.symbol)
            if reference is None or Decimal(reference) <= ZERO:
                continue
            reference = Decimal(reference)

            for txn in instrument.transactions:
                deviation = self.price_deviation(Decimal(txn.price), reference)
                if deviation is None or deviation <= IMPLAUSIBLE_PRICE_FACTOR:
                    continue
                found.append({
                    "transaction": txn,
                    "instrument": instrument,
                    "reference": reference,
                    "deviation": deviation,
                })
        found.sort(key=lambda a: a["deviation"], reverse=True)
        return found

    def plan_import(self, rows: list[ParsedRow]) -> ImportPlan:
        """Resolve, validate and classify upload rows without writing anything.

        The whole file is judged against the ledger it would produce, so a sell
        that overdraws a position is caught here rather than half way through
        applying, which would leave the portfolio in a state nobody asked for.
        """
        known = {
            i.symbol: i for i in self.list_instruments(include_archived=True)
        }
        seen_references = set(
            self.session.scalars(select(Transaction.reference)).all()
        )
        prices, _ = self.stored_prices()

        planned: list[PlannedTrade] = []
        for row in rows:
            entry = PlannedTrade(
                row_number=row.row_number,
                raw_symbol=row.raw_symbol,
                status="error" if row.errors else "ok",
                txn_type=row.txn_type,
                trade_date=row.trade_date,
                quantity=row.quantity,
                price=row.price,
                fees=row.fees,
                note=row.note,
                reference=row.reference,
                errors=list(row.errors),
            )

            if row.reference and row.reference in seen_references:
                # Already applied by an earlier upload of the same sheet.
                entry.status = "duplicate"
                entry.warnings.append(
                    f"{row.reference} is already recorded; row will be skipped"
                )

            if entry.status not in ("error", "duplicate") and row.raw_symbol:
                instrument, symbol, suggestions = self._resolve_symbol(
                    row.raw_symbol, known
                )
                entry.symbol = symbol
                if instrument is not None:
                    entry.instrument_id = instrument.id
                    entry.instrument_name = instrument.name
                    self._flag_implausible_price(entry, instrument, prices)
                else:
                    entry.status = "new"
                    entry.instrument_name = row.raw_symbol.strip()
                    entry.suggestions = suggestions
                    if suggestions:
                        entry.needs_review = True
                        entry.warnings.append(
                            f"not tracked - did you mean {', '.join(suggestions)}?"
                        )
                    else:
                        # Nothing to compare against yet. Recorded as given and
                        # re-checked once a real close has been fetched.
                        entry.warnings.append(
                            "new stock - price cannot be checked until a market "
                            "price is fetched; it will be flagged afterwards if "
                            "it looks wrong"
                        )

            planned.append(entry)

        self._validate_planned_timelines(planned, known)
        return ImportPlan(rows=planned)

    def _flag_implausible_price(
        self,
        entry: PlannedTrade,
        instrument: Instrument,
        prices: dict[str, Decimal],
    ) -> None:
        """Question a price that is orders of magnitude from the known one.

        Held back rather than rejected: a genuine outlier must still be
        enterable, so this un-ticks the row and says why instead of refusing.
        """
        if entry.price is None or entry.price <= ZERO:
            return
        reference = self.reference_price(instrument, prices)
        if reference is None:
            return

        deviation = self.price_deviation(entry.price, reference)
        if deviation is None or deviation <= IMPLAUSIBLE_PRICE_FACTOR:
            return

        entry.needs_review = True
        entry.warnings.append(
            f"price {entry.price} is {deviation.quantize(Decimal('0.1'))}x away "
            f"from {instrument.symbol}'s known price of "
            f"{reference.quantize(Decimal('0.01'))} - check for a typo"
        )

    def _validate_planned_timelines(
        self, planned: list[PlannedTrade], known: dict[str, Instrument]
    ) -> None:
        """Replay each affected instrument with its imported rows merged in."""
        by_symbol: dict[str, list[PlannedTrade]] = {}
        for entry in planned:
            if entry.applies and entry.symbol:
                by_symbol.setdefault(entry.symbol, []).append(entry)

        for symbol, entries in by_symbol.items():
            instrument = known.get(symbol)
            existing = (
                _to_ledger(instrument.transactions, instrument) if instrument else []
            )
            candidates = [
                LedgerTxn(
                    trade_date=e.trade_date,
                    txn_type=TxnType(e.txn_type),
                    quantity=Decimal(e.quantity),
                    price=Decimal(e.price),
                    fees=Decimal(e.fees or 0),
                )
                for e in entries
            ]

            try:
                weighted_average(existing + candidates)
            except LedgerError as exc:
                # The ledger is only invalid as a whole; there is no single
                # guilty row, so every imported row for this name is held back
                # rather than applying an arbitrary subset.
                for entry in entries:
                    entry.status = "error"
                    entry.errors.append(f"{symbol}: {exc}")

    def apply_import(self, plan: ImportPlan) -> dict[str, int]:
        """Write an already-planned import. Caller commits.

        Re-plans nothing and trusts nothing: rows carrying errors are not
        applied even if a caller hands them back.
        """
        applicable = [r for r in plan.applicable if not r.errors]
        if not applicable:
            raise ServiceError("nothing in this file can be applied")

        created: dict[str, Instrument] = {}
        for entry in applicable:
            if entry.instrument_id or not entry.symbol:
                continue
            if entry.symbol not in created:
                created[entry.symbol] = self.add_instrument(
                    entry.symbol, entry.instrument_name or entry.symbol
                )

        references = self.next_references(len(applicable))
        for entry, reference in zip(applicable, references):
            instrument_id = entry.instrument_id
            if instrument_id is None:
                instrument_id = created[entry.symbol].id

            self.session.add(
                Transaction(
                    # A reference from the sheet is kept so re-uploading the
                    # same file is recognised as already applied.
                    reference=entry.reference or reference,
                    instrument_id=instrument_id,
                    txn_type=entry.txn_type,
                    trade_date=entry.trade_date,
                    quantity=entry.quantity,
                    price=entry.price,
                    fees=entry.fees or ZERO,
                    note=entry.note,
                )
            )

        self.session.flush()

        # A buy on an archived name means it has been re-entered.
        for entry in applicable:
            if entry.instrument_id and entry.txn_type == "BUY":
                instrument = self.session.get(Instrument, entry.instrument_id)
                if instrument is not None and instrument.is_archived:
                    instrument.status = "active"

        self.session.flush()
        return {
            "applied": len(applicable),
            "instrumentsCreated": len(created),
            "skipped": len(plan.rows) - len(applicable),
        }

    # ------------------------------------------------------------ positions

    def position_for(self, instrument: Instrument) -> Position:
        return weighted_average(_to_ledger(instrument.transactions, instrument))

    def realized_sales(self, instrument: Instrument) -> list[RealizedSale]:
        """FIFO-matched disposals, for the capital gains export."""
        _, sales = fifo(_to_ledger(instrument.transactions, instrument))
        return sales

    def dividend_income(self, instrument: Instrument) -> Decimal:
        """Opening balance plus every payment valued on its ex-date.

        Payments before dividend_start_date are skipped because they are
        already inside opening_dividends.
        """
        total = Decimal(instrument.opening_dividends or 0)
        if not instrument.dividends:
            return total

        # Restated, because the feed quotes dividends per current share.
        ledger = _to_ledger(instrument.transactions, instrument)
        dates, quantities = build_quantity_timeline(ledger)
        start = instrument.dividend_start_date

        for dividend in instrument.dividends:
            if start is not None and dividend.ex_date < start:
                continue
            held = quantity_on_timeline(dates, quantities, dividend.ex_date)
            if held > ZERO:
                total += Decimal(dividend.per_share) * held

        return total

    def holding_for(
        self, instrument: Instrument, price: Decimal | None = None
    ) -> Holding:
        return Holding(
            instrument=instrument,
            position=self.position_for(instrument),
            dividend_income=self.dividend_income(instrument),
            market_price=price,
        )

    def holdings(
        self,
        prices: dict[str, Decimal] | None = None,
        include_archived: bool = False,
    ) -> list[Holding]:
        prices = prices or {}
        return [
            self.holding_for(instrument, prices.get(instrument.symbol))
            for instrument in self.list_instruments(include_archived)
        ]

    # --------------------------------------------------------------- prices

    def stored_prices(self) -> tuple[dict[str, Decimal], date | None]:
        """Latest stored close per symbol, and the newest snapshot date."""
        rows = self.session.execute(
            select(Instrument.symbol, PriceSnapshot.close, PriceSnapshot.as_of)
            .join(PriceSnapshot, PriceSnapshot.instrument_id == Instrument.id)
            .where(Instrument.portfolio_id == self.portfolio_id)
            .order_by(PriceSnapshot.as_of)
        ).all()

        prices: dict[str, Decimal] = {}
        newest: date | None = None
        for symbol, close, as_of in rows:
            # Ordered ascending, so the last write per symbol wins.
            prices[symbol] = Decimal(close)
            newest = as_of if newest is None else max(newest, as_of)
        return prices, newest

    def refresh_prices(
        self,
        *,
        force: bool = False,
        last_fetch_at=None,
        now=None,
        holidays: frozenset[date] = frozenset(),
        fetcher=None,
    ) -> PriceResult:
        """Refresh stored closes, subject to the market-hours policy (point 6).

        A failed fetch is not fatal: the previously stored closes are returned
        with ``live=False`` and the reason attached, so the UI can label them
        rather than silently presenting stale numbers as current.
        """
        # Resolved at call time rather than as a default argument, so the
        # upstream can be substituted in tests without reaching the network.
        fetcher = fetcher or fetch_quotes

        stored, stored_as_of = self.stored_prices()
        decision = decide_refresh(
            last_fetch_at=last_fetch_at,
            stored_close_date=stored_as_of,
            force=force,
            moment=now,
            holidays=holidays,
        )

        if not decision.should_fetch:
            return PriceResult(
                prices=stored,
                as_of=stored_as_of,
                live=False,
                reason=decision.reason,
                status=decision.status,
            )

        # Across every portfolio, not just the one in scope. A closing price is
        # market data, identical whoever holds it, and Yahoo rate-limits hard
        # enough that fetching the same symbol once per portfolio is how the
        # 429s start.
        instruments = list(
            self.session.scalars(
                select(Instrument).where(Instrument.status == "active")
            )
        )
        symbols = sorted({i.symbol for i in instruments})

        try:
            quotes = fetcher(symbols)
        except PriceFetchError as exc:
            return PriceResult(
                prices=stored,
                as_of=stored_as_of,
                live=False,
                reason="upstream unavailable, showing stored close",
                status=decision.status,
                error=str(exc),
            )

        # An intraday quote belongs to today; once the session has settled it
        # belongs to the last completed session.
        if decision.status is MarketStatus.OPEN:
            as_of = (now.astimezone(IST) if now else datetime.now(IST)).date()
        else:
            as_of = last_settled_session(now, holidays)

        by_symbol = {i.symbol: i for i in instruments}
        for symbol, close in quotes.items():
            instrument = by_symbol.get(symbol)
            if instrument is None:
                continue
            snapshot = self.session.get(PriceSnapshot, (instrument.id, as_of))
            if snapshot is None:
                self.session.add(
                    PriceSnapshot(
                        instrument_id=instrument.id, as_of=as_of, close=close
                    )
                )
            else:
                snapshot.close = close
        self.session.flush()

        merged = {**stored, **quotes}
        return PriceResult(
            prices=merged,
            as_of=as_of,
            live=True,
            reason=decision.reason,
            status=decision.status,
        )

    def sync_dividends(
        self,
        *,
        instruments: list[Instrument] | None = None,
        fetcher=None,
        default_start: date | None = None,
    ) -> DividendSyncResult:
        """Pull dividend history from the feed and store it (point 3).

        Each instrument is only synced from its own dividend_start_date, so
        payments already summed into opening_dividends are never re-imported.
        Nothing is fetched before the earliest such date.
        """
        fetcher = fetcher or fetch_dividend_history
        instruments = (
            instruments
            if instruments is not None
            else self.list_instruments(include_archived=True)
        )
        if not instruments:
            return DividendSyncResult(added=0, updated=0, symbols=0)

        # A position bought but never held through an ex-date still needs a
        # floor; fall back to the earliest trade.
        starts = {}
        for instrument in instruments:
            start = instrument.dividend_start_date or default_start
            if start is None:
                trades = instrument.transactions
                start = min((t.trade_date for t in trades), default=None)
            if start is not None:
                starts[instrument.symbol] = start

        if not starts:
            return DividendSyncResult(added=0, updated=0, symbols=0)

        earliest = min(starts.values())
        symbols = sorted(starts)

        try:
            history = fetcher(symbols, earliest)
        except DividendFetchError as exc:
            return DividendSyncResult(
                added=0, updated=0, symbols=0, error=str(exc)
            )

        by_symbol = {i.symbol: i for i in instruments}
        added = updated = 0

        for symbol, payments in history.items():
            instrument = by_symbol.get(symbol)
            if instrument is None:
                continue
            cutoff = starts[symbol]

            for ex_date, per_share in payments:
                # Per-instrument cutoff, not the batch-wide one.
                if ex_date < cutoff:
                    continue

                existing = self.session.scalar(
                    select(Dividend).where(
                        Dividend.instrument_id == instrument.id,
                        Dividend.ex_date == ex_date,
                    )
                )
                if existing is None:
                    # Appended through the relationship, not added by id: that
                    # keeps the already-loaded collection in step, so a
                    # dividend_income() call right after a sync sees the new
                    # rows instead of a stale cache.
                    instrument.dividends.append(
                        Dividend(
                            ex_date=ex_date,
                            per_share=per_share,
                            source="yahoo",
                        )
                    )
                    added += 1
                elif Decimal(existing.per_share) != per_share:
                    existing.per_share = per_share
                    existing.source = "yahoo"
                    updated += 1

        self.session.flush()
        return DividendSyncResult(
            added=added, updated=updated, symbols=len(history)
        )

    def sync_corporate_actions(
        self,
        *,
        instruments: list[Instrument] | None = None,
        fetcher=None,
        default_start: date | None = None,
    ) -> DividendSyncResult:
        """Pull splits and bonuses from the feed and store them.

        Each instrument is scanned only from its basis date onward. Actions
        already reflected in the stored figures must not be imported: applying
        a 10-for-1 that is baked into an 87.08 average would restate it to
        8.708 and multiply the holding tenfold.
        """
        fetcher = fetcher or fetch_split_history
        instruments = (
            instruments
            if instruments is not None
            else self.list_instruments(include_archived=True)
        )
        if not instruments:
            return DividendSyncResult(added=0, updated=0, symbols=0)

        starts: dict[str, date] = {}
        for instrument in instruments:
            start = instrument.basis_date or default_start
            if start is None:
                start = min(
                    (t.trade_date for t in instrument.transactions), default=None
                )
            if start is not None:
                starts[instrument.symbol] = start

        if not starts:
            return DividendSyncResult(added=0, updated=0, symbols=0)

        try:
            history = fetcher(sorted(starts), min(starts.values()))
        except SplitFetchError as exc:
            return DividendSyncResult(added=0, updated=0, symbols=0, error=str(exc))

        by_symbol = {i.symbol: i for i in instruments}
        added = updated = 0

        for symbol, events in history.items():
            instrument = by_symbol.get(symbol)
            if instrument is None:
                continue
            cutoff = starts[symbol]

            for ex_date, ratio in events:
                if ex_date <= cutoff:
                    continue
                existing = self.session.scalar(
                    select(CorporateAction).where(
                        CorporateAction.instrument_id == instrument.id,
                        CorporateAction.ex_date == ex_date,
                    )
                )
                if existing is None:
                    # Through the relationship so a position computed straight
                    # after a sync sees the action rather than a stale cache.
                    instrument.corporate_actions.append(
                        CorporateAction(
                            ex_date=ex_date, ratio=ratio, source="yahoo"
                        )
                    )
                    added += 1
                elif Decimal(existing.ratio) != ratio:
                    existing.ratio = ratio
                    updated += 1

        self.session.flush()
        return DividendSyncResult(
            added=added, updated=updated, symbols=len(history)
        )

    def record_demerger(
        self,
        parent_id: str,
        child_id: str,
        ex_date: date,
        cost_retained: Decimal,
    ) -> dict:
        """Split a parent's cost basis with the company demerged out of it.

        A demerger gives you shares in a new company without taking more money,
        so the two cost bases must together equal what the parent alone cost
        beforehand. Recording the child as an ordinary purchase - which is what
        a spreadsheet naturally does - invents capital that was never deployed
        and inflates the denominator of every return figure.

        ``cost_retained`` is the fraction staying with the parent, as published
        by the company. It is not derivable from prices, which is why it is a
        parameter rather than something guessed here.

        The child's shares keep the parent's acquisition dates, so the holding
        period for long-term gains carries over as the tax treatment requires.
        """
        cost_retained = Decimal(cost_retained)
        if not (ZERO < cost_retained < Decimal("1")):
            raise ServiceError(
                f"cost retained must be between 0 and 1, got {cost_retained}"
            )

        parent = self.get_instrument(parent_id)
        child = self.get_instrument(child_id)
        if parent.id == child.id:
            raise ServiceError("a company cannot demerge from itself")

        existing = self.session.scalar(
            select(CorporateAction).where(
                CorporateAction.instrument_id == parent.id,
                CorporateAction.ex_date == ex_date,
            )
        )
        if existing is not None:
            # Dropped before the parent is measured, not edited afterwards.
            # position_for already applies this action, so carving out of what
            # it left would take a second slice off a basis that has been
            # reduced once - the child silently loses a tenth of its cost each
            # time the same demerger is recorded. Recording one twice has to
            # correct it, not compound it.
            self.session.delete(existing)
            self.session.flush()
            self.session.refresh(parent)

        parent_before = self.position_for(parent)
        if parent_before.cost_basis <= ZERO:
            raise ServiceError(f"{parent.symbol} has no cost to apportion")

        carved = parent_before.cost_basis * (Decimal("1") - cost_retained)

        parent.corporate_actions.append(
            CorporateAction(
                ex_date=ex_date,
                ratio=cost_retained,
                action_type="DEMERGER",
                source="manual",
            )
        )

        # Reprice the child's opening holding so it carries exactly the cost
        # carved out of the parent, no more.
        opening = [t for t in child.transactions if t.txn_type == "BUY"]
        if not opening:
            raise ServiceError(
                f"{child.symbol} has no opening holding to attach the "
                "demerged cost to"
            )
        received = sum((Decimal(t.quantity) for t in opening), ZERO)
        if received <= ZERO:
            raise ServiceError(f"{child.symbol} holds no shares")

        per_share = carved / received
        for txn in opening:
            txn.price = per_share
            txn.note = (
                f"cost apportioned from {parent.symbol} demerger on "
                f"{ex_date.isoformat()}"
            )

        self.session.flush()
        self.session.refresh(parent)
        self.session.refresh(child)

        return {
            "parentCostBefore": parent_before.cost_basis,
            "parentCostAfter": self.position_for(parent).cost_basis,
            "childCost": carved,
            "childPerShare": per_share,
            "sharesReceived": received,
        }

    def suspected_corporate_actions(
        self, *, threshold: Decimal = Decimal("0.35")
    ) -> list[dict]:
        """Holdings whose price has moved enough to suggest an unrecorded split.

        A 5-for-1 shows up as an 80% fall that no news explains. This is the
        cheap trigger: rather than polling every symbol constantly, a suspicious
        move is what prompts a scan.
        """
        prices, _ = self.stored_prices()
        suspects = []
        for instrument in self.list_instruments():
            price = prices.get(instrument.symbol)
            if price is None or Decimal(price) <= ZERO:
                continue
            position = self.position_for(instrument)
            if position.quantity <= ZERO or position.average_cost <= ZERO:
                continue

            drop = (position.average_cost - Decimal(price)) / position.average_cost
            if drop < threshold:
                continue
            ratio = position.average_cost / Decimal(price)
            suspects.append({
                "instrument": instrument,
                "averageCost": position.average_cost,
                "price": Decimal(price),
                "drop": drop,
                "impliedRatio": ratio,
            })
        suspects.sort(key=lambda s: s["drop"], reverse=True)
        return suspects

    def record_dividend(
        self,
        instrument_id: str,
        ex_date: date,
        per_share: Decimal,
        source: str = "manual",
    ) -> Dividend:
        """Insert or update one dividend payment."""
        instrument = self.get_instrument(instrument_id)
        per_share = Decimal(per_share)
        if per_share < ZERO:
            raise ServiceError("dividend per share cannot be negative")

        existing = self.session.scalar(
            select(Dividend).where(
                Dividend.instrument_id == instrument.id,
                Dividend.ex_date == ex_date,
            )
        )
        if existing is not None:
            existing.per_share = per_share
            existing.source = source
            self.session.flush()
            return existing

        dividend = Dividend(ex_date=ex_date, per_share=per_share, source=source)
        instrument.dividends.append(dividend)
        self.session.flush()
        return dividend
