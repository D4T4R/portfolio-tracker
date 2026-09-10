"""Tests for the position accounting engine."""

from datetime import date
from decimal import Decimal

import pytest

from portfolio.ledger import (
    LedgerError,
    Transaction,
    TxnType,
    build_quantity_timeline,
    fifo,
    quantity_on,
    quantity_on_timeline,
    weighted_average,
)

D = Decimal


def buy(day, qty, price, fees="0"):
    return Transaction(date(2021, 12, day), TxnType.BUY, D(qty), D(price), D(fees))


def sell(day, qty, price, fees="0"):
    return Transaction(date(2021, 12, day), TxnType.SELL, D(qty), D(price), D(fees))


class TestWeightedAverage:
    def test_single_buy(self):
        pos = weighted_average([buy(1, "10", "100")])
        assert pos.quantity == D("10")
        assert pos.cost_basis == D("1000")
        assert pos.average_cost == D("100")
        assert pos.realized_gain == D("0")

    def test_average_blends_two_buys(self):
        pos = weighted_average([buy(1, "10", "100"), buy(2, "10", "200")])
        assert pos.quantity == D("20")
        assert pos.average_cost == D("150")

    def test_partial_sale_costed_at_average(self):
        pos = weighted_average(
            [buy(1, "10", "100"), buy(2, "10", "200"), sell(3, "5", "250")]
        )
        # Sold 5 at 250 against an average cost of 150.
        assert pos.realized_gain == D("500")
        assert pos.quantity == D("15")
        assert pos.average_cost == D("150")

    def test_full_exit_zeroes_cost_basis(self):
        pos = weighted_average([buy(1, "10", "100"), sell(2, "10", "150")])
        assert pos.quantity == D("0")
        assert pos.cost_basis == D("0")
        assert pos.average_cost == D("0")
        assert pos.realized_gain == D("500")
        assert not pos.is_open

    def test_fees_raise_cost_and_cut_proceeds(self):
        pos = weighted_average([buy(1, "10", "100", fees="50")])
        assert pos.cost_basis == D("1050")

        pos = weighted_average([buy(1, "10", "100"), sell(2, "10", "150", fees="50")])
        assert pos.realized_gain == D("450")
        assert pos.fees_paid == D("50")

    def test_total_invested_survives_a_full_exit(self):
        # cost_basis goes to zero on exit, but capital deployed must not, or
        # return-on-capital for closed positions is unmeasurable.
        pos = weighted_average([buy(1, "10", "100"), sell(2, "10", "150")])
        assert pos.total_invested == D("1000")

    def test_overselling_is_rejected(self):
        with pytest.raises(LedgerError, match="exceeds"):
            weighted_average([buy(1, "10", "100"), sell(2, "11", "150")])


class TestFifo:
    def test_oldest_lot_is_consumed_first(self):
        _, sales = fifo([buy(1, "10", "100"), buy(2, "10", "200"), sell(3, "5", "250")])
        assert len(sales) == 1
        assert sales[0].cost == D("500")  # 5 @ 100, the older lot
        assert sales[0].gain == D("750")

    def test_sale_spanning_two_lots_splits(self):
        _, sales = fifo(
            [buy(1, "10", "100"), buy(2, "10", "200"), sell(3, "15", "250")]
        )
        assert len(sales) == 2
        assert sales[0].quantity == D("10")
        assert sales[0].cost == D("1000")
        assert sales[1].quantity == D("5")
        assert sales[1].cost == D("1000")  # 5 @ 200
        assert sum(s.gain for s in sales) == D("1750")

    def test_fifo_and_average_diverge_on_partial_sales(self):
        txns = [buy(1, "10", "100"), buy(2, "10", "200"), sell(3, "5", "250")]
        assert fifo(txns)[0].realized_gain == D("750")
        assert weighted_average(txns).realized_gain == D("500")

    def test_fifo_and_average_agree_once_fully_exited(self):
        # Total profit over a closed position cannot depend on lot convention.
        txns = [buy(1, "10", "100"), buy(2, "10", "200"), sell(3, "20", "250")]
        assert fifo(txns)[0].realized_gain == weighted_average(txns).realized_gain

    def test_a_sale_spanning_lots_splits_across_terms(self):
        txns = [
            Transaction(date(2021, 1, 1), TxnType.BUY, D("10"), D("100")),
            Transaction(date(2023, 1, 2), TxnType.BUY, D("5"), D("140")),
            # Consumes the remaining old lot and part of the recent one, so the
            # single disposal has to be reported as two gains of different term.
            Transaction(date(2023, 3, 1), TxnType.SELL, D("12"), D("160")),
        ]
        _, sales = fifo(txns)
        assert [s.term for s in sales] == ["LTCG", "STCG"]
        assert sales[0].quantity == D("10")
        assert sales[1].quantity == D("2")

    def test_exactly_one_year_is_short_term(self):
        txns = [
            Transaction(date(2023, 1, 1), TxnType.BUY, D("1"), D("100")),
            Transaction(date(2024, 1, 1), TxnType.SELL, D("1"), D("120")),
        ]
        _, sales = fifo(txns)
        assert sales[0].holding_days == 365
        assert sales[0].term == "STCG"

    def test_same_day_buy_then_sell_matches(self):
        txns = [
            Transaction(date(2023, 1, 1), TxnType.SELL, D("5"), D("120")),
            Transaction(date(2023, 1, 1), TxnType.BUY, D("5"), D("100")),
        ]
        pos, sales = fifo(txns)
        assert pos.quantity == D("0")
        assert sales[0].gain == D("100")


class TestDividendTiming:
    def test_quantity_on_tracks_history_not_current(self):
        txns = [buy(1, "100", "10"), sell(10, "40", "20")]
        assert quantity_on(txns, date(2021, 12, 5)) == D("100")
        assert quantity_on(txns, date(2021, 12, 15)) == D("60")

    def test_quantity_before_first_purchase_is_zero(self):
        assert quantity_on([buy(10, "100", "10")], date(2021, 12, 1)) == D("0")

    def test_ex_date_on_trade_date_counts_the_trade(self):
        txns = [buy(1, "100", "10"), sell(10, "40", "20")]
        assert quantity_on(txns, date(2021, 12, 10)) == D("60")

    def test_timeline_matches_replay(self):
        txns = [buy(1, "100", "10"), buy(5, "50", "12"), sell(10, "40", "20")]
        dates, qtys = build_quantity_timeline(txns)
        for day in range(1, 20):
            probe = date(2021, 12, day)
            assert quantity_on_timeline(dates, qtys, probe) == quantity_on(txns, probe)

    def test_timeline_collapses_same_day_trades(self):
        txns = [buy(1, "100", "10"), buy(1, "50", "12")]
        dates, qtys = build_quantity_timeline(txns)
        assert dates == [date(2021, 12, 1)]
        assert qtys == [D("150")]


class TestWorkbookReconciliation:
    """Mahindra & Mahindra as it stands in Final_P&L_auto.xlsx."""

    AVG_PRICE = D("773.6146")
    INITIAL_QTY = D("100")
    BOOKED_QTY = D("33")
    REALIZED = D("58284.12")
    CMP = D("3200.20")

    def _ledger(self):
        # Seed exactly as the migration will: one opening buy, and a sell
        # priced so it reproduces the workbook's realized figure.
        sell_price = self.AVG_PRICE + (self.REALIZED / self.BOOKED_QTY)
        return [
            Transaction(date(2021, 12, 15), TxnType.BUY, self.INITIAL_QTY, self.AVG_PRICE),
            Transaction(date(2024, 6, 1), TxnType.SELL, self.BOOKED_QTY, sell_price),
        ]

    def test_seeded_sell_reproduces_workbook_realized(self):
        pos = weighted_average(self._ledger())
        assert pos.realized_gain == pytest.approx(self.REALIZED, abs=D("0.01"))

    def test_remaining_quantity_matches_sheet(self):
        pos = weighted_average(self._ledger())
        assert pos.quantity == D("67")

    def test_cost_basis_excludes_sold_shares(self):
        pos = weighted_average(self._ledger())
        # The sheet's column E charges all 100 shares against the open
        # position; only the 67 still held belong in cost basis.
        assert pos.cost_basis == pytest.approx(self.AVG_PRICE * D("67"), abs=D("0.01"))
        assert pos.cost_basis < self.AVG_PRICE * self.INITIAL_QTY

    DIVIDENDS = D("28413")
    WORKBOOK_TOTAL_PROFIT = D("223749.06")  # sheet column J

    def test_total_profit_counts_realized_exactly_once(self):
        pos = weighted_average(self._ledger())
        unrealized = self.CMP * pos.quantity - pos.cost_basis
        total = unrealized + pos.realized_gain + self.DIVIDENDS

        assert total == pytest.approx(D("249278.34"), abs=D("1"))

    def test_engine_beats_the_workbook_by_the_cost_of_sold_shares(self):
        pos = weighted_average(self._ledger())
        unrealized = self.CMP * pos.quantity - pos.cost_basis
        total = unrealized + pos.realized_gain + self.DIVIDENDS

        # Column J is I + (G - E) + L, and E charges the sold shares against
        # the open position even though realized already accounts for them.
        # The shortfall is exactly the cost of those 33 shares.
        cost_of_sold = self.AVG_PRICE * self.BOOKED_QTY
        assert total - self.WORKBOOK_TOTAL_PROFIT == pytest.approx(
            cost_of_sold, abs=D("1")
        )
