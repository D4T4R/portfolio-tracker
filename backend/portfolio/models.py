"""SQLAlchemy mapping for the ledger schema.

Mirrors migrations/001_initial.sql. The models deliberately hold no derived
state - no cached quantity, no stored average cost - because every such field
is a chance for the stored number to drift from the ledger, which is exactly
how the source workbook's totals went wrong.

Runs against Supabase Postgres in production and SQLite in tests; UUID primary
keys are generated in Python so both behave identically.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Scales must match 001_initial.sql, otherwise values round differently
# depending on which backend is in use.
QUANTITY = Numeric(18, 6)
MONEY = Numeric(18, 4)
PER_SHARE = Numeric(18, 6)


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Portfolio(Base):
    """A separately tracked book of holdings.

    Everything else hangs off an instrument, and an instrument belongs to
    exactly one portfolio, so this one foreign key scopes the whole model.
    """

    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # Exactly one portfolio answers a request that names none, so existing
    # callers and bookmarks keep working.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    instruments: Mapped[list["Instrument"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        order_by="Instrument.name",
    )

    def __repr__(self) -> str:
        return f"<Portfolio {self.name}>"


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    portfolio_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    # Not globally unique any more: the same stock can sit in two portfolios
    # with different cost bases. Uniqueness is per portfolio, below.
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    # Dividends paid before dividend_start_date are already summed into
    # opening_dividends; the feed is only consulted from that date onward so
    # the migrated history is not counted twice.
    opening_dividends: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0")
    )
    dividend_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # The date the stored quantities and prices are stated as of. Figures
    # migrated from the workbook were already restated for every split up to
    # the snapshot, so replaying those would double-count: a 10-for-1 that is
    # baked into an 87.08 average must not turn it into 8.708. Only actions
    # after this date are applied. NULL means the ledger is as-traded and
    # every action counts.
    basis_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="instrument",
        cascade="all, delete-orphan",
        order_by="Transaction.trade_date",
    )
    dividends: Mapped[list["Dividend"]] = relationship(
        back_populates="instrument",
        cascade="all, delete-orphan",
        order_by="Dividend.ex_date",
    )
    corporate_actions: Mapped[list["CorporateAction"]] = relationship(
        back_populates="instrument",
        cascade="all, delete-orphan",
        order_by="CorporateAction.ex_date",
    )

    portfolio: Mapped[Portfolio] = relationship(back_populates="instruments")

    __table_args__ = (
        CheckConstraint("status in ('active', 'archived')", name="instruments_status"),
        UniqueConstraint("portfolio_id", "symbol", name="instruments_unique_symbol"),
    )

    @property
    def is_archived(self) -> bool:
        return self.status == "archived"

    def __repr__(self) -> str:
        return f"<Instrument {self.symbol} {self.status}>"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # A short, ordered handle for humans: the UUID above is the key the database
    # joins on, but it is not something you can read off a screen or type into a
    # spreadsheet. Imports use this to recognise rows already applied.
    reference: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    instrument_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    txn_type: Mapped[str] = mapped_column(String(8), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fees: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    instrument: Mapped[Instrument] = relationship(back_populates="transactions")

    __table_args__ = (
        CheckConstraint("txn_type in ('BUY', 'SELL')", name="transactions_type"),
        CheckConstraint("quantity > 0", name="transactions_quantity_positive"),
        CheckConstraint("price >= 0", name="transactions_price_non_negative"),
        CheckConstraint("fees >= 0", name="transactions_fees_non_negative"),
        Index("transactions_instrument_date_idx", "instrument_id", "trade_date"),
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.txn_type} {self.quantity}@{self.price}>"


class Counter(Base):
    """Monotonic sequences that must not rewind when rows are deleted.

    Deriving the next trade reference from MAX(reference) looks equivalent and
    is not: deleting the newest trade frees its number, and the next trade
    recorded would claim it. A reference that once identified one trade would
    then identify a different one, so a re-uploaded import sheet quoting the
    old number would skip a legitimate row as "already applied".
    """

    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class Dividend(Base):
    __tablename__ = "dividends"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    instrument_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    # Entitlement follows the holder on the ex-date, so this is the date the
    # ledger is replayed to when valuing the payment.
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    per_share: Mapped[Decimal] = mapped_column(PER_SHARE, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="yahoo")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    instrument: Mapped[Instrument] = relationship(back_populates="dividends")

    __table_args__ = (
        UniqueConstraint("instrument_id", "ex_date", name="dividends_unique_ex_date"),
        CheckConstraint("per_share >= 0", name="dividends_per_share_non_negative"),
    )


class CorporateAction(Base):
    """A split or bonus, which changes the share count without changing value.

    Stored rather than applied destructively: rewriting historical trades would
    lose what was actually executed, and a ratio corrected upstream could then
    never be undone.
    """

    __tablename__ = "corporate_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    instrument_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Shares after per share before: 10 for a 10-for-1 split.
    ratio: Mapped[Decimal] = mapped_column(PER_SHARE, nullable=False)
    action_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="SPLIT"
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="yahoo")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    instrument: Mapped[Instrument] = relationship(back_populates="corporate_actions")

    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "ex_date", name="corporate_actions_unique_ex_date"
        ),
        CheckConstraint("ratio > 0", name="corporate_actions_ratio_positive"),
    )


class PriceSnapshot(Base):
    """A daily close, so the dashboard renders without hitting Yahoo."""

    __tablename__ = "price_snapshots"

    instrument_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
