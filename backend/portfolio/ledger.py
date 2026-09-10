"""Position accounting from a transaction ledger.

Every figure the dashboard shows is derived here from an ordered list of
transactions; nothing about a position is stored. Two cost conventions run side
by side:

* weighted average - the headline numbers, and what the original workbook used.
* FIFO             - oldest lots consumed first, which is what Indian tax law
                     requires for listed equity. Kept alongside so a capital
                     gains report can be exported without recomputing history.

Quantities and money are Decimal throughout. Binary floats silently drift once
you accumulate hundreds of trades, and these numbers get filed with a tax
return.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Iterable, Sequence

# India: listed equity held beyond one year is long term.
LONG_TERM_DAYS = 365

ZERO = Decimal("0")
ONE = Decimal("1")


class TxnType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class LedgerError(ValueError):
    """Raised when a ledger cannot be reduced to a coherent position."""


@dataclass(frozen=True)
class Transaction:
    """One executed trade.

    ``fees`` is the all-in cost of the trade (brokerage, STT, stamp duty). It
    increases the cost of a buy and reduces the proceeds of a sell.
    """

    trade_date: date
    txn_type: TxnType
    quantity: Decimal
    price: Decimal
    fees: Decimal = ZERO
    txn_id: str | None = None

    def __post_init__(self):
        if self.quantity <= ZERO:
            raise LedgerError(f"quantity must be positive, got {self.quantity}")
        if self.price < ZERO:
            raise LedgerError(f"price cannot be negative, got {self.price}")
        if self.fees < ZERO:
            raise LedgerError(f"fees cannot be negative, got {self.fees}")


SPLIT = "SPLIT"
DEMERGER = "DEMERGER"


@dataclass(frozen=True)
class CorporateAction:
    """Something the company did that restates a holding.

    Two kinds, and they are not variations of each other:

    SPLIT (and bonus) changes the share count and nothing else. ``ratio`` is
    shares after per share before - 10 for a 10-for-1 - so quantity multiplies
    and price divides, leaving the money committed untouched.

    DEMERGER spins a division out as a separately listed company. The share
    count of the parent does not change; what changes is that part of its cost
    now belongs to the new company. ``ratio`` is the fraction of cost the
    parent *keeps* (0.8966 for an 89.66/10.34 apportionment), applied to price
    alone. The carved-off remainder becomes the child's opening cost, which is
    recorded against the child instrument rather than here.

    Getting these two confused would be expensive: treating a demerger as a
    split would multiply the share count of a holding that never gained a
    share.
    """

    ex_date: date
    ratio: Decimal
    action_type: str = SPLIT

    def __post_init__(self):
        if self.ratio <= ZERO:
            raise LedgerError(f"ratio must be positive, got {self.ratio}")
        if self.action_type == DEMERGER and self.ratio > ONE:
            raise LedgerError(
                f"a demerger cannot retain more than all of its cost, "
                f"got {self.ratio}"
            )


def restate(
    txns: Iterable[Transaction], actions: Sequence[CorporateAction]
) -> list[Transaction]:
    """Put every trade onto the current share basis.

    A split multiplies the share count and divides the price, leaving the money
    committed unchanged. Doing this at read time keeps the stored ledger a
    faithful record of what was actually executed - 27 shares really were
    bought at 6,000 - while every derived figure comes out in today's units, so
    quantities line up with the market price and with a split-adjusted
    dividend feed.

    Fees are left alone: brokerage paid is an amount of money, not a per-share
    quantity, and a split does not revise it.
    """
    txns = list(txns)
    if not actions:
        return txns

    out = []
    for txn in txns:
        shares = ONE   # split factor: multiplies quantity, divides price
        cost = ONE     # demerger factor: reduces price, quantity untouched
        for action in actions:
            # Only trades predating the action are restated; anything executed
            # on or after it was already quoted in the new units.
            if action.ex_date <= txn.trade_date:
                continue
            if action.action_type == DEMERGER:
                cost *= action.ratio
            else:
                shares *= action.ratio

        if shares == ONE and cost == ONE:
            out.append(txn)
        else:
            out.append(
                replace(
                    txn,
                    quantity=txn.quantity * shares,
                    price=txn.price * cost / shares,
                )
            )
    return out


@dataclass
class Lot:
    """An open parcel of shares, used for FIFO matching."""

    acquired_on: date
    quantity: Decimal
    unit_cost: Decimal


@dataclass(frozen=True)
class RealizedSale:
    """One sell matched against one lot. The unit of a capital gains report."""

    sold_on: date
    acquired_on: date
    quantity: Decimal
    proceeds: Decimal
    cost: Decimal

    @property
    def gain(self) -> Decimal:
        return self.proceeds - self.cost

    @property
    def holding_days(self) -> int:
        return (self.sold_on - self.acquired_on).days

    @property
    def is_long_term(self) -> bool:
        return self.holding_days > LONG_TERM_DAYS

    @property
    def term(self) -> str:
        return "LTCG" if self.is_long_term else "STCG"


@dataclass
class Position:
    """Derived state of a single instrument."""

    quantity: Decimal = ZERO
    # Cost of the shares still held. Excludes anything already sold, which is
    # the distinction the source workbook collapsed.
    cost_basis: Decimal = ZERO
    realized_gain: Decimal = ZERO
    # Capital deployed across the whole life of the position, for return-on-
    # capital reporting.
    total_invested: Decimal = ZERO
    fees_paid: Decimal = ZERO

    @property
    def average_cost(self) -> Decimal:
        if self.quantity <= ZERO:
            return ZERO
        return self.cost_basis / self.quantity

    @property
    def is_open(self) -> bool:
        return self.quantity > ZERO


def _ordered(transactions: Iterable[Transaction]) -> list[Transaction]:
    """Sort by trade date, settling same-day ties by putting buys first.

    A same-day buy-then-sell is otherwise unmatchable under FIFO, and brokers
    do not always preserve intra-day ordering in exports.
    """
    return sorted(
        transactions,
        key=lambda t: (t.trade_date, 0 if t.txn_type is TxnType.BUY else 1),
    )


def weighted_average(transactions: Iterable[Transaction]) -> Position:
    """Reduce a ledger to a position using a running average cost.

    A sale is costed at the average price at the moment of sale, so realized
    gain is ``proceeds - average_cost * quantity``.
    """
    pos = Position()

    for txn in _ordered(transactions):
        if txn.txn_type is TxnType.BUY:
            cost = txn.quantity * txn.price + txn.fees
            pos.quantity += txn.quantity
            pos.cost_basis += cost
            pos.total_invested += cost
            pos.fees_paid += txn.fees
            continue

        if txn.quantity > pos.quantity:
            raise LedgerError(
                f"sell of {txn.quantity} on {txn.trade_date} exceeds "
                f"holding of {pos.quantity}"
            )

        # Capture the average before mutating, so the sale is costed at the
        # rate that applied when it happened.
        unit_cost = pos.average_cost
        cost_removed = unit_cost * txn.quantity
        proceeds = txn.quantity * txn.price - txn.fees

        pos.quantity -= txn.quantity
        pos.cost_basis -= cost_removed
        pos.realized_gain += proceeds - cost_removed
        pos.fees_paid += txn.fees

        # Guard against Decimal residue leaving a dust cost on a closed lot.
        if pos.quantity == ZERO:
            pos.cost_basis = ZERO

    return pos


def fifo(transactions: Iterable[Transaction]) -> tuple[Position, list[RealizedSale]]:
    """Reduce a ledger to a position by consuming the oldest lots first.

    Returns the resulting position and every matched sale, which together form
    the capital gains record.
    """
    pos = Position()
    lots: list[Lot] = []
    sales: list[RealizedSale] = []

    for txn in _ordered(transactions):
        if txn.txn_type is TxnType.BUY:
            unit_cost = txn.price + (txn.fees / txn.quantity)
            lots.append(Lot(txn.trade_date, txn.quantity, unit_cost))
            pos.quantity += txn.quantity
            pos.cost_basis += txn.quantity * unit_cost
            pos.total_invested += txn.quantity * unit_cost
            pos.fees_paid += txn.fees
            continue

        if txn.quantity > pos.quantity:
            raise LedgerError(
                f"sell of {txn.quantity} on {txn.trade_date} exceeds "
                f"holding of {pos.quantity}"
            )

        # Spread sell-side fees across the disposed shares so each matched
        # parcel carries its share of the cost.
        unit_proceeds = txn.price - (txn.fees / txn.quantity)
        remaining = txn.quantity

        while remaining > ZERO:
            lot = lots[0]
            take = min(lot.quantity, remaining)

            sales.append(
                RealizedSale(
                    sold_on=txn.trade_date,
                    acquired_on=lot.acquired_on,
                    quantity=take,
                    proceeds=take * unit_proceeds,
                    cost=take * lot.unit_cost,
                )
            )

            lot.quantity -= take
            remaining -= take
            pos.quantity -= take
            pos.cost_basis -= take * lot.unit_cost

            if lot.quantity <= ZERO:
                lots.pop(0)

        pos.fees_paid += txn.fees

        if pos.quantity == ZERO:
            pos.cost_basis = ZERO
            lots.clear()

    pos.realized_gain = sum((s.gain for s in sales), ZERO)
    return pos, sales


def quantity_on(transactions: Sequence[Transaction], on: date) -> Decimal:
    """Shares held at the close of ``on``.

    Used to value a dividend: entitlement follows whoever held the shares on
    the ex-date, so the ledger has to be replayed to that point rather than
    using the current holding.
    """
    total = ZERO
    for txn in _ordered(transactions):
        if txn.trade_date > on:
            break
        if txn.txn_type is TxnType.BUY:
            total += txn.quantity
        else:
            total -= txn.quantity
    return total


def build_quantity_timeline(
    transactions: Sequence[Transaction],
) -> tuple[list[date], list[Decimal]]:
    """Precompute cumulative holdings so many ex-dates can be valued cheaply.

    Returns parallel lists of dates and the running quantity from that date
    onward. Pairs with :func:`quantity_on_timeline` for O(log n) lookups
    instead of replaying the ledger per dividend.
    """
    dates: list[date] = []
    quantities: list[Decimal] = []
    running = ZERO

    for txn in _ordered(transactions):
        running += txn.quantity if txn.txn_type is TxnType.BUY else -txn.quantity
        if dates and dates[-1] == txn.trade_date:
            quantities[-1] = running
        else:
            dates.append(txn.trade_date)
            quantities.append(running)

    return dates, quantities


def quantity_on_timeline(
    dates: Sequence[date], quantities: Sequence[Decimal], on: date
) -> Decimal:
    """Look up the holding on ``on`` from a prebuilt timeline."""
    idx = bisect_right(dates, on)
    if idx == 0:
        return ZERO
    return quantities[idx - 1]
