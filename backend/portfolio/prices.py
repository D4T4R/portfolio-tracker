"""Price retrieval with a refresh policy built around NSE trading hours.

This is an after-market dashboard, so the default posture is: serve the stored
close and do not call Yahoo at all. A fetch only happens when there is a reason
for the number to have changed.

  * market closed, and the last session's close is stored -> no fetch
  * market open                                           -> fetch, throttled
  * stale or missing close                                -> fetch

Yahoo rate-limits aggressively and answers a 33-symbol sweep with 429s within a
couple of minutes of repeated polling, which is why the old dashboard silently
fell back to year-old spreadsheet prices. Here a failed refresh leaves the
stored close in place and says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# NSE continuous trading. The pre-open auction (09:00-09:15) is deliberately
# excluded: prices during it are indicative, not tradable.
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# Prices settle shortly after the bell; before this the "close" may still move.
CLOSE_SETTLED_AT = time(15, 45)

# Floor between live fetches while the market is open, so a user leaning on the
# refresh button cannot trip the rate limiter.
MIN_REFRESH_INTERVAL = timedelta(seconds=90)


class MarketStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    HOLIDAY = "holiday"


@dataclass(frozen=True)
class RefreshDecision:
    should_fetch: bool
    reason: str
    status: MarketStatus


def _as_ist(moment: datetime | None = None) -> datetime:
    if moment is None:
        return datetime.now(IST)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=IST)
    return moment.astimezone(IST)


def is_trading_day(day: date, holidays: frozenset[date] = frozenset()) -> bool:
    """Weekday and not an exchange holiday.

    The holiday list is supplied by the caller rather than hardcoded, because
    NSE publishes it annually and a stale built-in list fails silently.
    """
    return day.weekday() < 5 and day not in holidays


def market_status(
    moment: datetime | None = None, holidays: frozenset[date] = frozenset()
) -> MarketStatus:
    now = _as_ist(moment)
    if not is_trading_day(now.date(), holidays):
        return MarketStatus.HOLIDAY
    if MARKET_OPEN <= now.time() < MARKET_CLOSE:
        return MarketStatus.OPEN
    return MarketStatus.CLOSED


def previous_trading_day(
    day: date, holidays: frozenset[date] = frozenset()
) -> date:
    probe = day - timedelta(days=1)
    # A run of weekend plus contiguous holidays; 10 is comfortably beyond the
    # longest NSE closure.
    for _ in range(10):
        if is_trading_day(probe, holidays):
            return probe
        probe -= timedelta(days=1)
    return probe


def last_settled_session(
    moment: datetime | None = None, holidays: frozenset[date] = frozenset()
) -> date:
    """The most recent session whose close is final.

    During a session, and briefly after the bell, that is the *previous* day:
    today's close does not exist yet.
    """
    now = _as_ist(moment)
    today = now.date()

    if is_trading_day(today, holidays) and now.time() >= CLOSE_SETTLED_AT:
        return today
    return previous_trading_day(today, holidays)


def decide_refresh(
    *,
    last_fetch_at: datetime | None,
    stored_close_date: date | None,
    force: bool = False,
    moment: datetime | None = None,
    holidays: frozenset[date] = frozenset(),
) -> RefreshDecision:
    """Decide whether to call Yahoo.

    ``force`` is the manual refresh button. It still respects the throttle,
    since the rate limiter does not care that a human asked.
    """
    now = _as_ist(moment)
    status = market_status(now, holidays)

    throttled = (
        last_fetch_at is not None
        and now - _as_ist(last_fetch_at) < MIN_REFRESH_INTERVAL
    )
    if throttled:
        return RefreshDecision(False, "throttled: fetched moments ago", status)

    if force:
        return RefreshDecision(True, "manual refresh", status)

    if stored_close_date is None:
        return RefreshDecision(True, "no stored price", status)

    if status is MarketStatus.OPEN:
        return RefreshDecision(True, "market is open", status)

    wanted = last_settled_session(now, holidays)
    if stored_close_date < wanted:
        return RefreshDecision(
            True, f"stored close is from {stored_close_date}, want {wanted}", status
        )

    return RefreshDecision(False, "stored close is current", status)


@dataclass
class PriceResult:
    """Prices plus the provenance the UI needs to label them honestly."""

    prices: dict[str, Decimal]
    as_of: date | None
    live: bool
    reason: str
    status: MarketStatus
    error: str | None = None


class PriceFetchError(Exception):
    """Upstream price data could not be retrieved."""


def fetch_quotes(symbols: list[str], ticker_factory=None) -> dict[str, Decimal]:
    """One batched call to Yahoo for every symbol.

    Batching matters: the previous design swept all symbols twice per refresh
    from two separate endpoints, which is what triggered the rate limiting.
    """
    if not symbols:
        return {}

    if ticker_factory is None:  # pragma: no cover - exercised via integration
        from yahooquery import Ticker

        ticker_factory = Ticker

    try:
        payload = ticker_factory(symbols).price
    except Exception as exc:
        raise PriceFetchError(str(exc)) from exc

    if not isinstance(payload, dict):
        raise PriceFetchError(f"unexpected response from Yahoo: {payload!r}")

    quotes: dict[str, Decimal] = {}
    for symbol in symbols:
        info = payload.get(symbol)
        if not isinstance(info, dict):
            continue
        price = info.get("regularMarketPrice")
        if price is None:
            price = info.get("regularMarketPreviousClose")
        if price is not None:
            quotes[symbol] = Decimal(str(price))

    if not quotes:
        raise PriceFetchError("no usable quotes in response")

    return quotes
