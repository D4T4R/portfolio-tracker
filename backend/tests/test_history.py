"""Parsing of the price history that feeds the chart."""

from datetime import date
from decimal import Decimal as D

import pandas as pd
import pytest

from portfolio.history import (
    DEFAULT_RANGE,
    HistoryFetchError,
    RANGES,
    fetch_history,
    parse_history,
)


def frame(rows, symbol="TRENT.NS"):
    """A yahooquery-shaped frame: (symbol, date) index, lowercase columns."""
    index = pd.MultiIndex.from_tuples(
        [(symbol, pd.Timestamp(day)) for day, *_ in rows]
    )
    return pd.DataFrame(
        {
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [r[5] for r in rows],
        },
        index=index,
    )


class TestParseHistory:
    def test_reads_candles_in_date_order(self):
        candles = parse_history(
            frame([
                ("2026-01-02", 5300, 5400, 5250, 5380, 120000),
                ("2026-01-01", 5200, 5310, 5180, 5300, 90000),
            ])
        )
        assert [c.day for c in candles] == [date(2026, 1, 1), date(2026, 1, 2)]
        assert candles[0].close == D("5300")
        assert candles[1].volume == 120000

    def test_prices_survive_as_decimals(self):
        # Through str, so a close of 5380.35 is not stored as 5380.349999...
        candles = parse_history(frame([("2026-01-02", 5300.1, 5400, 5250, 5380.35, 1)]))
        assert candles[0].close == D("5380.35")

    def test_a_row_missing_a_price_is_dropped_not_zeroed(self):
        # A zero would draw the candle to the floor of the chart, which reads
        # as a crash that never happened.
        candles = parse_history(
            frame([
                ("2026-01-01", 5200, 5310, 5180, 5300, 90000),
                ("2026-01-02", float("nan"), 5400, 5250, 5380, 120000),
            ])
        )
        assert [c.day for c in candles] == [date(2026, 1, 1)]

    def test_a_single_symbol_index_is_read_too(self):
        rows = [("2026-01-01", 5200, 5310, 5180, 5300, 90000)]
        flat = frame(rows)
        flat.index = [pd.Timestamp("2026-01-01")]
        assert parse_history(flat)[0].close == D("5300")

    def test_an_empty_window_is_not_an_error(self):
        assert parse_history(pd.DataFrame({"open": []})) == []

    def test_a_string_payload_is_rejected(self):
        # yahooquery hands back a plain string for an unknown symbol rather
        # than raising, and a string has no columns to misread.
        with pytest.raises(HistoryFetchError, match="unexpected history"):
            parse_history("No data found for this symbol")

    def test_nothing_at_all_is_empty(self):
        assert parse_history(None) == []


class TestFetchHistory:
    def test_an_unknown_range_falls_back_rather_than_reaching_upstream(self):
        seen = {}

        class FakeTicker:
            def history(self, period, interval, adj_ohlc):
                seen.update(period=period, adj_ohlc=adj_ohlc)
                return frame([("2026-01-01", 1, 2, 0.5, 1.5, 10)])

        # The range lands in a URL the browser controls, so it is checked here
        # rather than passed through to the feed.
        fetch_history("TRENT.NS", "'; DROP TABLE", lambda s: FakeTicker())
        assert seen["period"] == RANGES[DEFAULT_RANGE]

    def test_prices_are_requested_unadjusted_for_dividends(self):
        # Dividend-adjusted prices slide the series away from what was paid,
        # and the average-cost line would then sit at a price the chart never
        # shows.
        seen = {}

        class FakeTicker:
            def history(self, period, interval, adj_ohlc):
                seen["adj_ohlc"] = adj_ohlc
                return frame([("2026-01-01", 1, 2, 0.5, 1.5, 10)])

        fetch_history("TRENT.NS", "1y", lambda s: FakeTicker())
        assert seen["adj_ohlc"] is False

    def test_an_upstream_failure_becomes_a_history_error(self):
        class Boom:
            def history(self, **kwargs):
                raise RuntimeError("too many 429 error responses")

        with pytest.raises(HistoryFetchError, match="429"):
            fetch_history("TRENT.NS", "1y", lambda s: Boom())
