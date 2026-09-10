"""Dividend history retrieval.

Yahoo is used rather than screener.in: it exposes a clean per-symbol payment
history, while screener would need scraping and has known gaps in exactly the
fields that matter here.

The dates Yahoo reports are ex-dates. That is the correct cutoff for
entitlement - whoever holds the shares before the ex-date receives the payment -
so these pair directly with a ledger replay to that date. This module only
retrieves and normalises; valuing a payment against a holding is the ledger's
job.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


class DividendFetchError(Exception):
    """Upstream dividend data could not be retrieved."""


def _coerce_date(value) -> date | None:
    """Yahoo's index level arrives as date, Timestamp or string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _coerce_amount(value) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    # Yahoo occasionally emits 0.0 placeholder rows; they carry no income and
    # would otherwise create meaningless dividend records.
    if amount <= 0:
        return None
    return amount


def parse_dividend_history(frame) -> dict[str, list[tuple[date, Decimal]]]:
    """Normalise Yahoo's MultiIndex frame into {symbol: [(ex_date, amount)]}.

    Symbols with no payments in the window are simply absent from the frame,
    so callers must not assume every requested symbol appears.
    """
    if frame is None or not hasattr(frame, "empty") or frame.empty:
        return {}

    if "dividends" not in getattr(frame, "columns", []):
        raise DividendFetchError(f"unexpected dividend payload: {frame!r}"[:200])

    history: dict[str, list[tuple[date, Decimal]]] = {}

    for index, row in frame.iterrows():
        # Single-symbol requests can come back without the symbol level.
        if isinstance(index, tuple) and len(index) == 2:
            symbol, raw_date = index
        else:
            continue

        ex_date = _coerce_date(raw_date)
        amount = _coerce_amount(row["dividends"])
        if ex_date is None or amount is None:
            continue

        history.setdefault(str(symbol), []).append((ex_date, amount))

    for payments in history.values():
        payments.sort()

    return history


def fetch_dividend_history(
    symbols: list[str], start: date, ticker_factory=None
) -> dict[str, list[tuple[date, Decimal]]]:
    """Fetch payments on or after ``start`` for every symbol, in one call."""
    if not symbols:
        return {}

    if ticker_factory is None:  # pragma: no cover - exercised via integration
        from yahooquery import Ticker

        ticker_factory = Ticker

    try:
        frame = ticker_factory(symbols).dividend_history(start=start.isoformat())
    except Exception as exc:
        raise DividendFetchError(str(exc)) from exc

    history = parse_dividend_history(frame)

    # dividend_history's start is inclusive but has been observed to bleed
    # earlier rows in; filter defensively so opening balances stay untouched.
    return {
        symbol: [(d, amount) for d, amount in payments if d >= start]
        for symbol, payments in history.items()
    }
