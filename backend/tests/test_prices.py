"""Tests for the price refresh policy (point 6)."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from portfolio.prices import (
    IST,
    MarketStatus,
    PriceFetchError,
    decide_refresh,
    fetch_quotes,
    is_trading_day,
    last_settled_session,
    market_status,
    previous_trading_day,
)

# 2026-09-09 is a Wednesday.
WED = date(2026, 9, 9)
SAT = date(2026, 9, 12)
MON = date(2026, 9, 14)


def ist(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


class TestMarketCalendar:
    def test_weekend_is_not_a_trading_day(self):
        assert is_trading_day(WED)
        assert not is_trading_day(SAT)

    def test_declared_holiday_is_not_a_trading_day(self):
        assert not is_trading_day(WED, frozenset({WED}))

    def test_status_during_session(self):
        assert market_status(ist(WED, 10)) is MarketStatus.OPEN

    def test_status_before_open_excludes_preopen_auction(self):
        # 09:00-09:15 is the auction; indicative prices are not tradable.
        assert market_status(ist(WED, 9, 5)) is MarketStatus.CLOSED
        assert market_status(ist(WED, 9, 15)) is MarketStatus.OPEN

    def test_status_at_and_after_the_bell(self):
        assert market_status(ist(WED, 15, 29)) is MarketStatus.OPEN
        assert market_status(ist(WED, 15, 30)) is MarketStatus.CLOSED

    def test_weekend_reports_holiday(self):
        assert market_status(ist(SAT, 10)) is MarketStatus.HOLIDAY

    def test_previous_trading_day_skips_the_weekend(self):
        assert previous_trading_day(MON) == date(2026, 9, 11)  # Friday

    def test_previous_trading_day_skips_contiguous_holidays(self):
        holidays = frozenset({date(2026, 9, 11), date(2026, 9, 10)})
        assert previous_trading_day(MON, holidays) == date(2026, 9, 9)

    def test_naive_datetime_is_treated_as_ist(self):
        naive = datetime(2026, 9, 9, 10, 0)
        assert market_status(naive) is MarketStatus.OPEN


class TestLastSettledSession:
    def test_mid_session_uses_the_previous_day(self):
        # Today's close does not exist yet at 10:00.
        assert last_settled_session(ist(WED, 10)) == date(2026, 9, 8)

    def test_just_after_the_bell_still_uses_previous_day(self):
        assert last_settled_session(ist(WED, 15, 35)) == date(2026, 9, 8)

    def test_once_settled_uses_today(self):
        assert last_settled_session(ist(WED, 16)) == WED

    def test_weekend_falls_back_to_friday(self):
        assert last_settled_session(ist(SAT, 12)) == date(2026, 9, 11)


class TestRefreshDecision:
    def test_no_fetch_when_stored_close_is_current(self):
        d = decide_refresh(
            last_fetch_at=None, stored_close_date=WED, moment=ist(WED, 20)
        )
        assert not d.should_fetch
        assert d.reason == "stored close is current"

    def test_fetch_when_stored_close_is_stale(self):
        d = decide_refresh(
            last_fetch_at=None,
            stored_close_date=date(2026, 9, 4),
            moment=ist(WED, 20),
        )
        assert d.should_fetch
        assert "want 2026-09-09" in d.reason

    def test_fetch_when_nothing_stored(self):
        d = decide_refresh(
            last_fetch_at=None, stored_close_date=None, moment=ist(WED, 20)
        )
        assert d.should_fetch
        assert d.reason == "no stored price"

    def test_fetch_while_market_is_open(self):
        d = decide_refresh(
            last_fetch_at=None,
            stored_close_date=date(2026, 9, 8),
            moment=ist(WED, 11),
        )
        assert d.should_fetch
        assert d.reason == "market is open"

    def test_weekend_does_not_fetch(self):
        # The whole point of an after-market dashboard: no idle polling.
        d = decide_refresh(
            last_fetch_at=None,
            stored_close_date=date(2026, 9, 11),
            moment=ist(SAT, 12),
        )
        assert not d.should_fetch
        assert d.status is MarketStatus.HOLIDAY

    def test_throttle_beats_market_open(self):
        d = decide_refresh(
            last_fetch_at=ist(WED, 11, 0),
            stored_close_date=date(2026, 9, 8),
            moment=ist(WED, 11, 0) + timedelta(seconds=30),
        )
        assert not d.should_fetch
        assert "throttled" in d.reason

    def test_throttle_also_beats_force(self):
        # Yahoo's rate limiter does not care that a human clicked refresh.
        d = decide_refresh(
            last_fetch_at=ist(WED, 20, 0),
            stored_close_date=WED,
            force=True,
            moment=ist(WED, 20, 0) + timedelta(seconds=10),
        )
        assert not d.should_fetch

    def test_force_fetches_once_past_the_throttle(self):
        d = decide_refresh(
            last_fetch_at=ist(WED, 20, 0),
            stored_close_date=WED,
            force=True,
            moment=ist(WED, 20, 5),
        )
        assert d.should_fetch
        assert d.reason == "manual refresh"


class TestFetchQuotes:
    def test_parses_regular_market_price(self):
        factory = lambda syms: type("T", (), {"price": {
            "ITC.NS": {"regularMarketPrice": 416.85},
        }})()
        assert fetch_quotes(["ITC.NS"], factory) == {"ITC.NS": Decimal("416.85")}

    def test_falls_back_to_previous_close(self):
        factory = lambda syms: type("T", (), {"price": {
            "ITC.NS": {"regularMarketPreviousClose": 410.0},
        }})()
        assert fetch_quotes(["ITC.NS"], factory) == {"ITC.NS": Decimal("410.0")}

    def test_skips_symbols_returned_as_error_strings(self):
        factory = lambda syms: type("T", (), {"price": {
            "ITC.NS": {"regularMarketPrice": 416.85},
            "BAD.NS": "Quote not found",
        }})()
        result = fetch_quotes(["ITC.NS", "BAD.NS"], factory)
        assert result == {"ITC.NS": Decimal("416.85")}

    def test_zero_price_is_kept_not_dropped(self):
        # The old code used a falsy check here and turned 0 into "N/A".
        factory = lambda syms: type("T", (), {"price": {
            "X.NS": {"regularMarketPrice": 0},
        }})()
        assert fetch_quotes(["X.NS"], factory) == {"X.NS": Decimal("0")}

    def test_rate_limit_becomes_price_fetch_error(self):
        def factory(syms):
            raise RuntimeError("too many 429 error responses")

        with pytest.raises(PriceFetchError, match="429"):
            fetch_quotes(["ITC.NS"], factory)

    def test_empty_symbol_list_makes_no_call(self):
        def factory(syms):  # pragma: no cover - must not run
            raise AssertionError("should not have called Yahoo")

        assert fetch_quotes([], factory) == {}

    def test_all_symbols_unusable_raises(self):
        factory = lambda syms: type("T", (), {"price": {"BAD.NS": "err"}})()
        with pytest.raises(PriceFetchError, match="no usable quotes"):
            fetch_quotes(["BAD.NS"], factory)
