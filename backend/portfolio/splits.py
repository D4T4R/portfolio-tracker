"""Retrieval of splits and bonus issues from the price feed.

A split changes the share count without changing what the holding is worth. If
it goes unrecorded the ledger keeps the old count while the market quotes the
new price, and the position silently reads as a catastrophic loss - a 5-for-1
looks like an 80% fall.

Parsing is pure and separated from fetching so the shapes the feed returns can
be tested without a network call.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pandas as pd

# A ratio far from 1 that is not a real action is more likely bad data, and a
# ratio very close to 1 is noise rather than a corporate action.
MIN_RATIO = Decimal("0.01")
MAX_RATIO = Decimal("1000")


class SplitFetchError(Exception):
    """The feed could not be reached or returned something unusable."""


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().date()
    try:
        return pd.Timestamp(value).to_pydatetime().date()
    except Exception:
        return None


def parse_split_history(frame) -> dict[str, list[tuple[date, Decimal]]]:
    """Pull (ex_date, ratio) pairs per symbol out of a price history frame."""
    if frame is None:
        return {}
    if not hasattr(frame, "columns"):
        raise SplitFetchError(f"unexpected split payload: {type(frame).__name__}")
    if "splits" not in frame.columns:
        # A window with no action in it has no column; that is not a failure.
        return {}

    rows = frame[frame["splits"] != 0]["splits"]
    out: dict[str, list[tuple[date, Decimal]]] = {}
    for key, raw in rows.items():
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        symbol, stamp = key
        when = _as_date(stamp)
        if when is None:
            continue
        # Via str: a float ratio would carry binary artefacts into a factor
        # that multiplies every historical quantity.
        ratio = Decimal(str(raw))
        if ratio <= MIN_RATIO or ratio > MAX_RATIO or ratio == Decimal("1"):
            continue
        out.setdefault(str(symbol), []).append((when, ratio))

    for symbol in out:
        out[symbol].sort(key=lambda pair: pair[0])
    return out


def fetch_split_history(
    symbols: list[str], start: date, ticker_factory=None
) -> dict[str, list[tuple[date, Decimal]]]:
    """Splits per symbol from ``start`` onward."""
    if not symbols:
        return {}

    if ticker_factory is None:
        from yahooquery import Ticker

        def ticker_factory(syms):
            return Ticker(syms, asynchronous=True)

    try:
        ticker = ticker_factory(list(symbols))
        # adj_ohlc off: adjusted prices already fold the split in, and the raw
        # series is what makes the action visible.
        frame = ticker.history(start=start.isoformat(), adj_ohlc=False)
    except Exception as exc:
        raise SplitFetchError(str(exc)) from exc

    history = parse_split_history(frame)
    return {
        symbol: [(d, r) for d, r in events if d >= start]
        for symbol, events in history.items()
        if any(d >= start for d, _ in events)
    }
