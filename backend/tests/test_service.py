"""Tests for ledger mutations: trade entry (point 2) and lifecycle (point 4)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from portfolio.models import Base
from portfolio.service import NotFound, PortfolioService, ServiceError

D = Decimal


@pytest.fixture
def service():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield PortfolioService(session)


@pytest.fixture
def itc(service):
    return service.add_instrument("ITC.NS", "ITC")


def buy(service, inst, day, qty, price, fees="0"):
    return service.record_transaction(
        inst.id, "BUY", day, D(qty), D(price), D(fees)
    )


def sell(service, inst, day, qty, price, fees="0"):
    return service.record_transaction(
        inst.id, "SELL", day, D(qty), D(price), D(fees)
    )


class TestInstrumentLifecycle:
    def test_add_normalises_symbol_case(self, service):
        inst = service.add_instrument(" itc.ns ", " ITC ")
        assert inst.symbol == "ITC.NS"
        assert inst.name == "ITC"
        assert inst.status == "active"

    def test_duplicate_symbol_is_rejected(self, service, itc):
        with pytest.raises(ServiceError, match="already tracked"):
            service.add_instrument("ITC.NS", "ITC Ltd")

    def test_blank_fields_rejected(self, service):
        with pytest.raises(ServiceError, match="symbol is required"):
            service.add_instrument("  ", "ITC")
        with pytest.raises(ServiceError, match="name is required"):
            service.add_instrument("ITC.NS", "  ")

    def test_unknown_instrument_raises_not_found(self, service):
        with pytest.raises(NotFound):
            service.get_instrument("does-not-exist")

    def test_archive_requires_a_closed_position(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        with pytest.raises(ServiceError, match="still holds"):
            service.archive_instrument(itc.id)

    def test_archive_after_full_exit(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        sell(service, itc, date(2024, 6, 10), "100", "450")
        assert service.archive_instrument(itc.id).status == "archived"

    def test_archived_names_are_hidden_by_default(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        sell(service, itc, date(2024, 6, 10), "100", "450")
        service.archive_instrument(itc.id)

        assert service.list_instruments() == []
        assert len(service.list_instruments(include_archived=True)) == 1

    def test_rebuying_an_archived_name_reactivates_it(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        sell(service, itc, date(2024, 6, 10), "100", "450")
        service.archive_instrument(itc.id)

        buy(service, itc, date(2024, 9, 10), "50", "420")
        assert service.get_instrument(itc.id).status == "active"


class TestTradeEntry:
    def test_buy_then_partial_sell(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        buy(service, itc, date(2024, 3, 10), "100", "500")
        sell(service, itc, date(2024, 6, 10), "50", "600")

        pos = service.position_for(service.get_instrument(itc.id))
        assert pos.quantity == D("150")
        assert pos.average_cost == D("450")
        assert pos.realized_gain == D("7500")

    def test_fees_are_captured(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400", fees="120")
        pos = service.position_for(service.get_instrument(itc.id))
        assert pos.cost_basis == D("40120")
        assert pos.fees_paid == D("120")

    def test_overselling_is_rejected(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        with pytest.raises(ServiceError, match="exceeds"):
            sell(service, itc, date(2024, 6, 10), "101", "450")

    def test_backdated_sell_that_breaks_a_later_trade_is_rejected(self, service, itc):
        # 50 held from January; a sell of 40 in June is fine on its own. But
        # inserting a 30-share sell dated *before* it would leave the June sale
        # unmatched, so the whole timeline has to be revalidated.
        buy(service, itc, date(2024, 1, 10), "50", "400")
        sell(service, itc, date(2024, 6, 10), "40", "450")

        with pytest.raises(ServiceError, match="exceeds"):
            sell(service, itc, date(2024, 3, 10), "30", "430")

    def test_backdated_sell_that_fits_is_accepted(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "50", "400")
        sell(service, itc, date(2024, 6, 10), "40", "450")
        sell(service, itc, date(2024, 3, 10), "10", "430")

        pos = service.position_for(service.get_instrument(itc.id))
        assert pos.quantity == D("0")

    def test_future_dated_trade_is_rejected(self, service, itc):
        with pytest.raises(ServiceError, match="future"):
            buy(service, itc, date(2099, 1, 1), "10", "400")

    def test_non_positive_quantity_rejected(self, service, itc):
        with pytest.raises(ServiceError, match="greater than zero"):
            buy(service, itc, date(2024, 1, 10), "0", "400")

    def test_negative_price_rejected(self, service, itc):
        with pytest.raises(ServiceError, match="price cannot be negative"):
            buy(service, itc, date(2024, 1, 10), "10", "-5")


class TestTransactionDeletion:
    def test_delete_reverts_the_position(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        extra = buy(service, itc, date(2024, 3, 10), "50", "500")

        service.delete_transaction(extra.id)
        pos = service.position_for(service.get_instrument(itc.id))
        assert pos.quantity == D("100")

    def test_cannot_delete_a_buy_a_later_sell_depends_on(self, service, itc):
        opening = buy(service, itc, date(2024, 1, 10), "100", "400")
        sell(service, itc, date(2024, 6, 10), "80", "450")

        with pytest.raises(ServiceError, match="exceeds"):
            service.delete_transaction(opening.id)

    def test_deleting_a_missing_transaction_raises(self, service):
        with pytest.raises(NotFound):
            service.delete_transaction("nope")


class TestDividendIncome:
    def test_valued_against_holding_on_the_ex_date(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        sell(service, itc, date(2024, 5, 1), "40", "450")

        # Before the sale: 100 shares. After: 60.
        service.record_dividend(itc.id, date(2024, 2, 8), D("6.25"))
        service.record_dividend(itc.id, date(2024, 6, 4), D("7.50"))

        inst = service.get_instrument(itc.id)
        assert service.dividend_income(inst) == D("625") + D("450")

    def test_uses_historical_not_current_holding(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        service.record_dividend(itc.id, date(2024, 2, 8), D("10"))
        sell(service, itc, date(2024, 5, 1), "100", "450")

        # Fully exited now, but the dividend was still earned on 100 shares.
        inst = service.get_instrument(itc.id)
        assert service.dividend_income(inst) == D("1000")

    def test_dividend_before_holding_earns_nothing(self, service, itc):
        buy(service, itc, date(2024, 3, 1), "100", "400")
        service.record_dividend(itc.id, date(2024, 1, 1), D("10"))

        inst = service.get_instrument(itc.id)
        assert service.dividend_income(inst) == D("0")

    def test_opening_balance_is_included(self, service, itc):
        inst = service.get_instrument(itc.id)
        inst.opening_dividends = D("18750")
        buy(service, itc, date(2024, 1, 10), "100", "400")

        assert service.dividend_income(service.get_instrument(itc.id)) == D("18750")

    def test_payments_before_the_migration_cutoff_are_not_recounted(
        self, service, itc
    ):
        # This is the double-count guard: the opening balance already covers
        # everything before dividend_start_date.
        inst = service.get_instrument(itc.id)
        inst.opening_dividends = D("5000")
        inst.dividend_start_date = date(2025, 8, 4)

        buy(service, itc, date(2024, 1, 10), "100", "400")
        service.record_dividend(itc.id, date(2025, 2, 12), D("6.50"))   # before
        service.record_dividend(itc.id, date(2026, 2, 4), D("6.50"))    # after

        assert service.dividend_income(service.get_instrument(itc.id)) == D("5650")

    def test_recording_the_same_ex_date_twice_updates(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        service.record_dividend(itc.id, date(2024, 2, 8), D("6.25"))
        service.record_dividend(itc.id, date(2024, 2, 8), D("7.00"))

        inst = service.get_instrument(itc.id)
        assert len(inst.dividends) == 1
        assert service.dividend_income(inst) == D("700")


class TestHoldingMath:
    def test_total_profit_counts_each_component_once(self, service, itc):
        inst = service.get_instrument(itc.id)
        inst.opening_dividends = D("1000")

        buy(service, itc, date(2024, 1, 10), "100", "400")
        sell(service, itc, date(2024, 6, 10), "40", "500")

        holding = service.holding_for(service.get_instrument(itc.id), D("450"))

        assert holding.position.quantity == D("60")
        assert holding.market_value == D("27000")
        assert holding.unrealized == D("3000")       # 60 * (450 - 400)
        assert holding.position.realized_gain == D("4000")  # 40 * (500 - 400)
        assert holding.dividend_income == D("1000")
        assert holding.total_profit == D("8000")

    def test_return_is_measured_against_capital_deployed(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        sell(service, itc, date(2024, 6, 10), "100", "500")

        holding = service.holding_for(service.get_instrument(itc.id), D("450"))
        # Closed position: 10,000 profit on 40,000 deployed.
        assert holding.position.total_invested == D("40000")
        assert holding.total_return_pct == D("25")

    def test_missing_price_does_not_fabricate_value(self, service, itc):
        buy(service, itc, date(2024, 1, 10), "100", "400")
        holding = service.holding_for(service.get_instrument(itc.id), None)
        assert holding.market_value == D("0")
        assert holding.unrealized == D("0")
