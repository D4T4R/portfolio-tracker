"""Tests for dividend retrieval and sync (point 3)."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from portfolio.dividends import (
    DividendFetchError,
    fetch_dividend_history,
    parse_dividend_history,
)
from portfolio.models import Base
from portfolio.service import PortfolioService

D = Decimal


def frame(rows):
    """Build a Yahoo-shaped MultiIndex dividend frame."""
    if not rows:
        return pd.DataFrame({"dividends": []})
    index = pd.MultiIndex.from_tuples(
        [(sym, d) for sym, d, _ in rows], names=["symbol", "date"]
    )
    return pd.DataFrame({"dividends": [amt for _, _, amt in rows]}, index=index)


class TestParsing:
    def test_groups_payments_by_symbol(self):
        result = parse_dividend_history(
            frame([
                ("ITC.NS", date(2025, 2, 12), 6.50),
                ("ITC.NS", date(2025, 5, 28), 7.85),
                ("TCS.NS", date(2025, 1, 17), 76.0),
            ])
        )
        assert set(result) == {"ITC.NS", "TCS.NS"}
        assert result["ITC.NS"] == [
            (date(2025, 2, 12), D("6.5")),
            (date(2025, 5, 28), D("7.85")),
        ]

    def test_payments_are_sorted(self):
        result = parse_dividend_history(
            frame([
                ("ITC.NS", date(2025, 5, 28), 7.85),
                ("ITC.NS", date(2025, 2, 12), 6.50),
            ])
        )
        assert [d for d, _ in result["ITC.NS"]] == [
            date(2025, 2, 12),
            date(2025, 5, 28),
        ]

    def test_accepts_timestamp_and_string_dates(self):
        result = parse_dividend_history(
            frame([
                ("ITC.NS", pd.Timestamp("2025-02-12"), 6.50),
                ("TCS.NS", "2025-01-17", 76.0),
            ])
        )
        assert result["ITC.NS"][0][0] == date(2025, 2, 12)
        assert result["TCS.NS"][0][0] == date(2025, 1, 17)

    def test_zero_and_negative_amounts_dropped(self):
        # Yahoo emits placeholder rows that carry no income.
        result = parse_dividend_history(
            frame([
                ("ITC.NS", date(2025, 2, 12), 0.0),
                ("ITC.NS", date(2025, 5, 28), 7.85),
            ])
        )
        assert result["ITC.NS"] == [(date(2025, 5, 28), D("7.85"))]

    def test_empty_frame_is_not_an_error(self):
        assert parse_dividend_history(frame([])) == {}
        assert parse_dividend_history(None) == {}

    def test_unexpected_payload_raises(self):
        with pytest.raises(DividendFetchError):
            parse_dividend_history(pd.DataFrame({"nope": [1]}))

    def test_amounts_avoid_float_artifacts(self):
        result = parse_dividend_history(frame([("X.NS", date(2025, 1, 1), 6.50)]))
        assert result["X.NS"][0][1] == D("6.5")


class TestFetch:
    def test_filters_rows_before_start(self):
        factory = lambda syms: type("T", (), {
            "dividend_history": lambda self, start: frame([
                ("ITC.NS", date(2024, 6, 1), 7.5),   # before start
                ("ITC.NS", date(2025, 5, 28), 7.85),
            ])
        })()
        result = fetch_dividend_history(["ITC.NS"], date(2025, 1, 1), factory)
        assert result["ITC.NS"] == [(date(2025, 5, 28), D("7.85"))]

    def test_no_symbols_makes_no_call(self):
        def factory(syms):  # pragma: no cover - must not run
            raise AssertionError("should not have called Yahoo")

        assert fetch_dividend_history([], date(2025, 1, 1), factory) == {}

    def test_upstream_failure_wrapped(self):
        def factory(syms):
            raise RuntimeError("too many 429 error responses")

        with pytest.raises(DividendFetchError, match="429"):
            fetch_dividend_history(["ITC.NS"], date(2025, 1, 1), factory)


@pytest.fixture
def service():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield PortfolioService(session)


class TestSync:
    def _itc(self, service, start=None, opening=D("0")):
        inst = service.add_instrument("ITC.NS", "ITC")
        inst.dividend_start_date = start
        inst.opening_dividends = opening
        service.record_transaction(
            inst.id, "BUY", date(2021, 12, 15), D("100"), D("200")
        )
        return service.get_instrument(inst.id)

    def test_sync_stores_payments(self, service):
        self._itc(service, start=date(2025, 1, 1))
        fetcher = lambda syms, start: {
            "ITC.NS": [(date(2025, 2, 12), D("6.5")), (date(2025, 5, 28), D("7.85"))]
        }
        result = service.sync_dividends(fetcher=fetcher)

        assert result.added == 2
        inst = service.find_by_symbol("ITC.NS")
        assert service.dividend_income(inst) == D("1435")  # 100 * (6.5 + 7.85)

    def test_sync_is_idempotent(self, service):
        self._itc(service, start=date(2025, 1, 1))
        fetcher = lambda syms, start: {"ITC.NS": [(date(2025, 2, 12), D("6.5"))]}

        assert service.sync_dividends(fetcher=fetcher).added == 1
        second = service.sync_dividends(fetcher=fetcher)
        assert second.added == 0 and second.updated == 0

    def test_corrected_amount_updates(self, service):
        self._itc(service, start=date(2025, 1, 1))
        service.sync_dividends(
            fetcher=lambda s, st: {"ITC.NS": [(date(2025, 2, 12), D("6.5"))]}
        )
        result = service.sync_dividends(
            fetcher=lambda s, st: {"ITC.NS": [(date(2025, 2, 12), D("7.0"))]}
        )
        assert result.updated == 1
        assert service.dividend_income(service.find_by_symbol("ITC.NS")) == D("700")

    def test_payments_before_cutoff_are_not_imported(self, service):
        # The double-count guard: everything before dividend_start_date is
        # already inside opening_dividends.
        self._itc(service, start=date(2025, 8, 4), opening=D("18750"))
        fetcher = lambda syms, start: {
            "ITC.NS": [
                (date(2025, 2, 12), D("6.5")),   # pre-migration, must be skipped
                (date(2026, 2, 4), D("6.5")),
            ]
        }
        result = service.sync_dividends(fetcher=fetcher)

        assert result.added == 1
        inst = service.find_by_symbol("ITC.NS")
        assert service.dividend_income(inst) == D("18750") + D("650")

    def test_sync_values_against_holding_on_ex_date(self, service):
        inst = self._itc(service, start=date(2022, 1, 1))
        service.record_transaction(
            inst.id, "SELL", date(2025, 3, 1), D("60"), D("400")
        )
        fetcher = lambda syms, start: {
            "ITC.NS": [
                (date(2025, 2, 12), D("10")),   # 100 held
                (date(2025, 5, 28), D("10")),   # 40 held
            ]
        }
        service.sync_dividends(fetcher=fetcher)

        assert service.dividend_income(service.find_by_symbol("ITC.NS")) == D("1400")

    def test_upstream_failure_reported_not_raised(self, service):
        self._itc(service, start=date(2025, 1, 1))

        def boom(syms, start):
            raise DividendFetchError("too many 429 error responses")

        result = service.sync_dividends(fetcher=boom)
        assert result.added == 0
        assert "429" in result.error

    def test_falls_back_to_earliest_trade_when_no_start_set(self, service):
        self._itc(service, start=None)
        seen = {}

        def fetcher(syms, start):
            seen["start"] = start
            return {}

        service.sync_dividends(fetcher=fetcher)
        assert seen["start"] == date(2021, 12, 15)

    def test_unknown_symbols_in_response_ignored(self, service):
        self._itc(service, start=date(2025, 1, 1))
        fetcher = lambda syms, start: {
            "ITC.NS": [(date(2025, 2, 12), D("6.5"))],
            "GHOST.NS": [(date(2025, 2, 12), D("9"))],
        }
        assert service.sync_dividends(fetcher=fetcher).added == 1
