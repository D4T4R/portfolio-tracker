"""Daily OHLC history for the price chart.

Fetched unadjusted (adj_ohlc=False), which keeps the right-hand edge of the
series on the same basis as the position it is drawn against: the average-cost
line and today's close have to mean the same thing, or the line sits at a price
the chart never shows. Dividend-adjusted prices would slide the whole series
down away from what was actually paid.

Yahoo's back-adjustment of older candles is not always complete - TRENT's series
carries a clean 1.5x step at the turn of the year with no real price move behind
it - so the shape of a long window can contain a discontinuity we did not cause
and cannot fix from here. Trade markers are anchored to their bar rather than to
a price, so they stay on the right day regardless.

Parsing is pure and separated from fetching so the shapes the feed returns can
be tested without a network call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

# What the UI offers. Anything else is rejected rather than passed upstream,
# since the value lands in a URL the browser controls.
RANGES = {
    "1mo": "1mo",
    "3mo": "3mo",
    "6mo": "6mo",
    "1y": "1y",
    "2y": "2y",
    "5y": "5y",
    "max": "max",
}

DEFAULT_RANGE = "1y"


class HistoryFetchError(Exception):
    """The feed could not be reached or returned something unusable."""


@dataclass(frozen=True)
class Candle:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).to_pydatetime().date()
    except Exception:
        return None


def _decimal(value) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        # Via str: a float close carries binary artefacts into a price the
        # chart draws and the tooltip prints.
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_history(frame) -> list[Candle]:
    """Turn a yahooquery history frame into candles, newest last.

    Rows missing any of the four prices are dropped rather than zero-filled: a
    zero would draw a candle to the floor of the chart, which reads as a crash
    that never happened.
    """
    if frame is None:
        return []
    if not hasattr(frame, "columns"):
        raise HistoryFetchError(f"unexpected history payload: {type(frame).__name__}")

    needed = ("open", "high", "low", "close")
    if any(column not in frame.columns for column in needed):
        return []

    candles: list[Candle] = []
    for key, row in frame.iterrows():
        # Single- and multi-symbol requests index differently: (symbol, date)
        # against a bare date.
        stamp = key[1] if isinstance(key, tuple) and len(key) == 2 else key
        day = _as_date(stamp)
        if day is None:
            continue

        prices = [_decimal(row[column]) for column in needed]
        if any(p is None or p <= 0 for p in prices):
            continue

        raw_volume = row["volume"] if "volume" in frame.columns else 0
        try:
            volume = int(raw_volume) if not pd.isna(raw_volume) else 0
        except (TypeError, ValueError):
            volume = 0

        candles.append(Candle(day, *prices, volume=volume))

    candles.sort(key=lambda c: c.day)
    return candles


def fetch_history(
    symbol: str, period: str = DEFAULT_RANGE, ticker_factory=None
) -> list[Candle]:
    """Daily candles for one symbol over ``period``."""
    period = RANGES.get(period, DEFAULT_RANGE)

    if ticker_factory is None:
        from yahooquery import Ticker

        def ticker_factory(sym):
            return Ticker(sym)

    try:
        ticker = ticker_factory(symbol)
        frame = ticker.history(period=period, interval="1d", adj_ohlc=False)
    except Exception as exc:
        raise HistoryFetchError(str(exc)) from exc

    # yahooquery hands back a plain string for an unknown symbol rather than
    # raising, so the type check in parse_history is what catches it.
    return parse_history(frame)
