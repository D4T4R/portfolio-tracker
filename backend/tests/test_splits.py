"""Splits and bonus issues: restatement, retrieval, and detection."""

from datetime import date
from decimal import Decimal as D

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from portfolio.ledger import (
    CorporateAction,
    LedgerError,
    Transaction,
    TxnType,
    restate,
    weighted_average,
)
from portfolio.models import Base
from portfolio.service import PortfolioService
from portfolio.splits import SplitFetchError, parse_split_history


def buy(day, qty, price):
    return Transaction(day, TxnType.BUY, D(qty), D(price))


def sell(day, qty, price):
    return Transaction(day, TxnType.SELL, D(qty), D(price))


class TestRestate:
    def test_split_multiplies_shares_and_divides_price(self):
        out = restate(
            [buy(date(2021, 12, 15), "27", "6000")],
            [CorporateAction(date(2025, 6, 17), D("10"))],
        )
        assert out[0].quantity == D("270")
        assert out[0].price == D("600")

    def test_money_committed_is_unchanged(self):
        original = buy(date(2021, 12, 15), "27", "6000")
        adjusted = restate(
            [original], [CorporateAction(date(2025, 6, 17), D("10"))]
        )[0]
        assert adjusted.quantity * adjusted.price == original.quantity * original.price

    def test_trades_after_the_action_are_untouched(self):
        # Bought post-split, so already quoted in the new units.
        out = restate(
            [buy(date(2025, 7, 1), "100", "600")],
            [CorporateAction(date(2025, 6, 17), D("10"))],
        )
        assert out[0].quantity == D("100")
        assert out[0].price == D("600")

    def test_a_trade_on_the_ex_date_is_untouched(self):
        out = restate(
            [buy(date(2025, 6, 17), "100", "600")],
            [CorporateAction(date(2025, 6, 17), D("10"))],
        )
        assert out[0].quantity == D("100")

    def test_successive_actions_compound(self):
        # A 1:2 split then a 4:1 bonus is a tenfold increase overall.
        out = restate(
            [buy(date(2021, 1, 1), "10", "10000")],
            [
                CorporateAction(date(2025, 6, 1), D("2")),
                CorporateAction(date(2025, 6, 15), D("5")),
            ],
        )
        assert out[0].quantity == D("100")
        assert out[0].price == D("1000")

    def test_fees_are_not_restated(self):
        # Brokerage paid is an amount of money, not a per-share quantity.
        out = restate(
            [Transaction(date(2021, 1, 1), TxnType.BUY, D("10"), D("100"), D("25"))],
            [CorporateAction(date(2024, 1, 1), D("5"))],
        )
        assert out[0].fees == D("25")

    def test_no_actions_returns_the_ledger_unchanged(self):
        txns = [buy(date(2021, 12, 15), "100", "400")]
        assert restate(txns, []) == txns

    def test_position_after_a_split_holds_its_value(self):
        ledger = [buy(date(2021, 12, 15), "100", "1000")]
        actions = [CorporateAction(date(2022, 7, 28), D("10"))]

        before = weighted_average(ledger)
        after = weighted_average(restate(ledger, actions))

        assert after.quantity == before.quantity * 10
        assert after.average_cost == before.average_cost / 10
        # The money committed is the same either way.
        assert after.cost_basis == before.cost_basis

    def test_a_sell_priced_after_the_split_still_reconciles(self):
        # 100 shares become 1,000; selling 400 of them must be valid.
        ledger = [buy(date(2021, 12, 15), "100", "1000"), sell(date(2023, 1, 1), "400", "120")]
        position = weighted_average(
            restate(ledger, [CorporateAction(date(2022, 7, 28), D("10"))])
        )
        assert position.quantity == D("600")

    def test_zero_ratio_is_rejected(self):
        with pytest.raises(LedgerError):
            CorporateAction(date(2024, 1, 1), D("0"))


class TestDemerger:
    def test_cost_is_reduced_but_share_count_is_not(self):
        # A demerger hands over shares in a new company; it does not change
        # how many of the parent you hold.
        out = restate(
            [buy(date(2021, 12, 15), "2500", "370.52")],
            [CorporateAction(date(2025, 1, 6), D("0.8966"), "DEMERGER")],
        )
        assert out[0].quantity == D("2500")
        assert out[0].price == D("370.52") * D("0.8966")

    def test_a_demerger_is_not_a_split(self):
        ledger = [buy(date(2021, 12, 15), "2500", "370.52")]
        as_demerger = weighted_average(
            restate(ledger, [CorporateAction(date(2025, 1, 6), D("0.9"), "DEMERGER")])
        )
        as_split = weighted_average(
            restate(ledger, [CorporateAction(date(2025, 1, 6), D("0.9"), "SPLIT")])
        )
        # The split would restate the share count of a holding that never
        # gained or lost a share.
        assert as_demerger.quantity == D("2500")
        assert as_split.quantity != as_demerger.quantity

    def test_retaining_more_than_all_cost_is_rejected(self):
        with pytest.raises(LedgerError, match="more than all"):
            CorporateAction(date(2025, 1, 6), D("1.5"), "DEMERGER")

    def test_a_split_and_a_demerger_compose(self):
        out = restate(
            [buy(date(2021, 1, 1), "100", "1000")],
            [
                CorporateAction(date(2023, 1, 1), D("2"), "SPLIT"),
                CorporateAction(date(2024, 1, 1), D("0.9"), "DEMERGER"),
            ],
        )
        assert out[0].quantity == D("200")          # split only
        assert out[0].price == D("450")             # 1000 * 0.9 / 2
        assert out[0].quantity * out[0].price == D("90000")


@pytest.fixture
def demerger_service():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield PortfolioService(session)


class TestRecordDemerger:
    def _pair(self, service):
        parent = service.add_instrument("ITC.NS", "ITC")
        service.record_transaction(
            parent.id, "BUY", date(2021, 12, 15), D("2500"), D("370.52")
        )
        child = service.add_instrument("ITCHOTELS.NS", "ITC HOTELS")
        service.record_transaction(
            child.id, "BUY", date(2021, 12, 15), D("250"), D("574.80")
        )
        return service.get_instrument(parent.id), service.get_instrument(child.id)

    def test_combined_cost_is_conserved(self, demerger_service):
        svc = demerger_service
        parent, child = self._pair(svc)
        before = svc.position_for(parent).cost_basis

        svc.record_demerger(parent.id, child.id, date(2025, 1, 6), D("0.8966"))

        after_parent = svc.position_for(svc.find_by_symbol("ITC.NS")).cost_basis
        after_child = svc.position_for(svc.find_by_symbol("ITCHOTELS.NS")).cost_basis

        # No new money was deployed, so the two together are what the parent
        # cost on its own beforehand. Not exact to the last digit: the carved
        # cost per share is held at the price column's four decimals, and
        # 95,779.42 spread over 250 shares does not land on that grid. Half a
        # paisa of rounding, bounded by the share count, not capital appearing
        # from nowhere.
        assert abs((after_parent + after_child) - before) < D("0.05")

    def test_parent_share_count_is_untouched(self, demerger_service):
        svc = demerger_service
        parent, child = self._pair(svc)
        svc.record_demerger(parent.id, child.id, date(2025, 1, 6), D("0.8966"))
        assert svc.position_for(svc.find_by_symbol("ITC.NS")).quantity == D("2500")

    def test_child_keeps_the_parents_acquisition_date(self, demerger_service):
        # The holding period carries over, which is what makes the gain long
        # term rather than short.
        svc = demerger_service
        parent, child = self._pair(svc)
        svc.record_demerger(parent.id, child.id, date(2025, 1, 6), D("0.8966"))

        child = svc.find_by_symbol("ITCHOTELS.NS")
        svc.record_transaction(child.id, "SELL", date(2026, 1, 6), D("250"), D("200"))
        sale = svc.realized_sales(svc.find_by_symbol("ITCHOTELS.NS"))[0]
        assert sale.acquired_on == date(2021, 12, 15)
        assert sale.term == "LTCG"

    def test_reapplying_updates_rather_than_stacking(self, demerger_service):
        svc = demerger_service
        parent, child = self._pair(svc)
        svc.record_demerger(parent.id, child.id, date(2025, 1, 6), D("0.8966"))
        first = svc.position_for(svc.find_by_symbol("ITC.NS")).cost_basis
        svc.record_demerger(parent.id, child.id, date(2025, 1, 6), D("0.8966"))
        assert svc.position_for(svc.find_by_symbol("ITC.NS")).cost_basis == first

    def test_out_of_range_fraction_is_rejected(self, demerger_service):
        svc = demerger_service
        parent, child = self._pair(svc)
        for bad in (D("0"), D("1"), D("1.2"), D("-0.5")):
            with pytest.raises(Exception, match="between 0 and 1"):
                svc.record_demerger(parent.id, child.id, date(2025, 1, 6), bad)


def frame(rows):
    if not rows:
        return pd.DataFrame({"splits": []})
    index = pd.MultiIndex.from_tuples(
        [(s, d) for s, d, _ in rows], names=["symbol", "date"]
    )
    return pd.DataFrame({"splits": [r for _, _, r in rows]}, index=index)


class TestParsing:
    def test_reads_events_per_symbol(self):
        out = parse_split_history(
            frame([
                ("TATASTEEL.NS", date(2022, 7, 28), 10.0),
                ("WIPRO.NS", date(2024, 12, 4), 2.0),
            ])
        )
        assert out["TATASTEEL.NS"] == [(date(2022, 7, 28), D("10"))]
        assert out["WIPRO.NS"] == [(date(2024, 12, 4), D("2"))]

    def test_ratio_of_one_is_not_an_action(self):
        assert parse_split_history(frame([("X.NS", date(2024, 1, 1), 1.0)])) == {}

    def test_absent_column_is_not_an_error(self):
        assert parse_split_history(pd.DataFrame({"close": [1]})) == {}
        assert parse_split_history(None) == {}

    def test_unusable_payload_raises(self):
        with pytest.raises(SplitFetchError):
            parse_split_history("nonsense")


@pytest.fixture
def service():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield PortfolioService(session)


class TestSyncAndBasisDate:
    def _cams(self, service, basis=None):
        inst = service.add_instrument("CAMS.NS", "CAMS")
        inst.basis_date = basis
        service.record_transaction(
            inst.id, "BUY", date(2021, 12, 15), D("19"), D("2741.41")
        )
        return service.get_instrument(inst.id)

    def test_split_after_basis_date_is_applied(self, service):
        inst = self._cams(service, basis=date(2025, 8, 4))
        service.sync_corporate_actions(
            fetcher=lambda syms, start: {"CAMS.NS": [(date(2025, 12, 8), D("5"))]}
        )
        position = service.position_for(service.find_by_symbol("CAMS.NS"))
        assert position.quantity == D("95")
        assert position.average_cost == D("2741.41") / 5

    def test_split_already_baked_in_is_not_reapplied(self, service):
        # Stored figures are stated as of 2025-08-04, so a 2024 split is
        # already inside them and must be ignored.
        self._cams(service, basis=date(2025, 8, 4))
        result = service.sync_corporate_actions(
            fetcher=lambda syms, start: {"CAMS.NS": [(date(2024, 10, 29), D("5"))]}
        )
        assert result.added == 0
        assert service.position_for(service.find_by_symbol("CAMS.NS")).quantity == D("19")

    def test_sync_is_idempotent(self, service):
        self._cams(service, basis=date(2025, 8, 4))
        f = lambda syms, start: {"CAMS.NS": [(date(2025, 12, 8), D("5"))]}
        assert service.sync_corporate_actions(fetcher=f).added == 1
        second = service.sync_corporate_actions(fetcher=f)
        assert second.added == 0 and second.updated == 0

    def test_upstream_failure_is_reported_not_raised(self, service):
        self._cams(service, basis=date(2025, 8, 4))

        def boom(syms, start):
            raise SplitFetchError("too many 429 error responses")

        result = service.sync_corporate_actions(fetcher=boom)
        assert result.added == 0 and "429" in result.error

    def test_market_value_reflects_the_split(self, service):
        inst = self._cams(service, basis=date(2025, 8, 4))
        service.refresh_prices(
            force=True, fetcher=lambda syms: {"CAMS.NS": D("713.95")}
        )
        service.sync_corporate_actions(
            fetcher=lambda syms, start: {"CAMS.NS": [(date(2025, 12, 8), D("5"))]}
        )
        prices, _ = service.stored_prices()
        holding = service.holding_for(service.find_by_symbol("CAMS.NS"), prices["CAMS.NS"])
        # 95 shares, not 19: the value roughly holds instead of showing an
        # 80% loss that never happened.
        assert holding.market_value == D("95") * D("713.95")


class TestDetection:
    def test_flags_a_holding_that_fell_like_a_split(self, service):
        inst = service.add_instrument("CAMS.NS", "CAMS")
        service.record_transaction(
            inst.id, "BUY", date(2021, 12, 15), D("19"), D("2741.41")
        )
        service.refresh_prices(
            force=True, fetcher=lambda syms: {"CAMS.NS": D("713.95")}
        )
        suspects = service.suspected_corporate_actions()
        assert len(suspects) == 1
        assert suspects[0]["instrument"].symbol == "CAMS.NS"
        assert suspects[0]["impliedRatio"] > D("3.5")

    def test_an_ordinary_loss_is_not_flagged(self, service):
        inst = service.add_instrument("ITC.NS", "ITC")
        service.record_transaction(
            inst.id, "BUY", date(2021, 12, 15), D("2500"), D("370.52")
        )
        service.refresh_prices(
            force=True, fetcher=lambda syms: {"ITC.NS": D("262.80")}
        )
        # Down 29%: painful, but not a corporate action.
        assert service.suspected_corporate_actions() == []
