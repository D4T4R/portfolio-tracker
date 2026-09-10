"""Tests for bulk trade upload: parsing, resolution, and atomic apply."""

import io
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from portfolio.imports import (
    ImportError_,
    coerce_date,
    coerce_decimal,
    coerce_type,
    map_columns,
    parse,
)
from portfolio.models import Base
from portfolio.service import PortfolioService

D = Decimal

HEADERS = ["Ticker", "Type", "Quantity", "Date", "Price"]


def sheet(rows, headers=HEADERS):
    """Build an in-memory xlsx upload."""
    buffer = io.BytesIO()
    pd.DataFrame(rows, columns=headers).to_excel(buffer, index=False)
    buffer.seek(0)
    buffer.name = "trades.xlsx"
    return buffer


class TestColumnMapping:
    def test_accepts_common_synonyms(self):
        mapping, missing = map_columns(
            ["Symbol", "Action", "Qty", "Trade Date", "Rate"]
        )
        assert missing == []
        assert mapping["quantity"] == "Qty"
        assert mapping["price"] == "Rate"

    def test_is_case_and_punctuation_insensitive(self):
        mapping, missing = map_columns(
            ["  TICKER ", "type", "QUANTITY", "date", "Price Per Share"]
        )
        assert missing == []
        assert mapping["price"] == "Price Per Share"

    def test_reports_missing_required_columns(self):
        _, missing = map_columns(["Ticker", "Type", "Quantity", "Date"])
        assert missing == ["price"]

    def test_optional_columns_are_not_required(self):
        mapping, missing = map_columns(HEADERS)
        assert missing == []
        assert "fees" not in mapping and "note" not in mapping


class TestCoercion:
    def test_reads_iso_and_named_month_dates(self):
        assert coerce_date("2025-09-15") == date(2025, 9, 15)
        assert coerce_date("15-Sep-2025") == date(2025, 9, 15)
        assert coerce_date(pd.Timestamp("2025-09-15")) == date(2025, 9, 15)

    def test_rejects_ambiguous_slash_dates(self):
        # 03/04/2025 is two different days depending on locale, so it is not
        # guessed at.
        assert coerce_date("03/04/2025") is None

    def test_decimal_avoids_float_artifacts(self):
        assert coerce_decimal("1014.44") == D("1014.44")
        assert coerce_decimal("1,00,430.50") == D("100430.50")
        assert coerce_decimal("₹945.50") == D("945.50")

    def test_type_words(self):
        assert coerce_type("Buy") == "BUY"
        assert coerce_type("SOLD") == "SELL"
        assert coerce_type("b") == "BUY"
        assert coerce_type("transfer") is None


class TestParsing:
    def test_reads_a_clean_sheet(self):
        rows = parse(sheet([["ITC.NS", "BUY", 100, "2024-01-10", 400]]))
        assert len(rows) == 1
        row = rows[0]
        assert row.ok
        assert row.raw_symbol == "ITC.NS"
        assert row.quantity == D("100")
        assert row.price == D("400")
        assert row.trade_date == date(2024, 1, 10)

    def test_row_numbers_match_the_spreadsheet(self):
        rows = parse(
            sheet([
                ["ITC.NS", "BUY", 100, "2024-01-10", 400],
                ["TCS.NS", "BUY", 10, "2024-02-10", 3800],
            ])
        )
        # Row 1 is the header, so the first trade is row 2.
        assert [r.row_number for r in rows] == [2, 3]

    def test_missing_price_is_reported_not_guessed(self):
        rows = parse(sheet([["ITC.NS", "BUY", 100, "2024-01-10", None]]))
        assert not rows[0].ok
        assert any("price is required" in e for e in rows[0].errors)

    def test_missing_price_column_rejects_the_file(self):
        with pytest.raises(ImportError_, match="price"):
            parse(
                sheet(
                    [["ITC.NS", "BUY", 100, "2024-01-10"]],
                    headers=["Ticker", "Type", "Quantity", "Date"],
                )
            )

    def test_blank_padding_rows_are_skipped(self):
        rows = parse(
            sheet([
                ["ITC.NS", "BUY", 100, "2024-01-10", 400],
                [None, None, None, None, None],
            ])
        )
        assert len(rows) == 1

    def test_future_date_is_rejected(self):
        rows = parse(sheet([["ITC.NS", "BUY", 100, "2099-01-10", 400]]))
        assert any("future" in e for e in rows[0].errors)

    def test_negative_quantity_is_rejected(self):
        rows = parse(sheet([["ITC.NS", "BUY", -5, "2024-01-10", 400]]))
        assert any("greater than zero" in e for e in rows[0].errors)

    def test_empty_sheet_raises(self):
        with pytest.raises(ImportError_):
            parse(sheet([], headers=HEADERS))


@pytest.fixture
def service():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield PortfolioService(session)


def itc(service):
    inst = service.add_instrument("ITC.NS", "ITC")
    service.record_transaction(inst.id, "BUY", date(2021, 12, 15), D("100"), D("200"))
    return inst


class TestReferences:
    def test_are_allocated_in_order(self, service):
        inst = itc(service)
        second = service.record_transaction(
            inst.id, "BUY", date(2024, 1, 10), D("50"), D("400")
        )
        assert second.reference == "TXN-000002"

    def test_survive_a_deletion_without_reuse(self, service):
        inst = itc(service)
        extra = service.record_transaction(
            inst.id, "BUY", date(2024, 1, 10), D("50"), D("400")
        )
        service.delete_transaction(extra.id)
        third = service.record_transaction(
            inst.id, "BUY", date(2024, 2, 10), D("10"), D("400")
        )
        # TXN-000002 was freed but must not be handed out again: a reference
        # that once meant one trade cannot later mean a different one, or a
        # re-uploaded sheet quoting it would skip a legitimate row.
        assert third.reference == "TXN-000003"


class TestPlanning:
    def test_resolves_exact_and_suffixless_tickers(self, service):
        itc(service)
        plan = service.plan_import(
            parse(sheet([
                ["ITC.NS", "BUY", 10, "2024-01-10", 400],
                ["ITC", "BUY", 10, "2024-02-10", 410],
            ]))
        )
        assert [r.status for r in plan.rows] == ["ok", "ok"]
        assert {r.symbol for r in plan.rows} == {"ITC.NS"}

    def test_unknown_ticker_becomes_a_new_instrument(self, service):
        itc(service)
        plan = service.plan_import(
            parse(sheet([["TCS.NS", "BUY", 10, "2024-01-10", 3800]]))
        )
        assert plan.rows[0].status == "new"
        assert plan.new_symbols == ["TCS.NS"]

    def test_near_miss_is_suggested_not_applied(self, service):
        service.add_instrument("BAJFINANCE.NS", "BAJAJ FINANCE")
        plan = service.plan_import(
            parse(sheet([["BAJFINANCEE", "BUY", 10, "2024-01-10", 900]]))
        )
        row = plan.rows[0]
        # Never silently resolved: a wrong guess files a trade against the
        # wrong company.
        assert row.instrument_id is None
        assert any("BAJFINANCE.NS" in w for w in row.warnings)

    def test_oversell_across_the_file_is_caught_before_writing(self, service):
        itc(service)
        plan = service.plan_import(
            parse(sheet([
                ["ITC.NS", "SELL", 60, "2024-01-10", 400],
                ["ITC.NS", "SELL", 60, "2024-02-10", 410],
            ]))
        )
        # 100 held, 120 sold: neither row applies.
        assert [r.status for r in plan.rows] == ["error", "error"]
        assert plan.counts["error"] == 2

    def test_sell_valid_only_with_a_buy_in_the_same_file(self, service):
        plan = service.plan_import(
            parse(sheet([
                ["TCS.NS", "BUY", 10, "2024-01-10", 3800],
                ["TCS.NS", "SELL", 4, "2024-06-10", 4200],
            ]))
        )
        assert [r.status for r in plan.rows] == ["new", "new"]

    def test_known_reference_is_marked_duplicate(self, service):
        inst = itc(service)
        existing = service.record_transaction(
            inst.id, "BUY", date(2024, 1, 10), D("10"), D("400")
        )
        rows = parse(
            sheet(
                [["ITC.NS", "BUY", 10, "2024-01-10", 400, existing.reference]],
                headers=HEADERS + ["Reference"],
            )
        )
        plan = service.plan_import(rows)
        assert plan.rows[0].status == "duplicate"


class TestPricePlausibility:
    def _priced(self, service, close):
        """A tracked stock with a known market price."""
        inst = service.add_instrument("BAJFINANCE.NS", "BAJAJ FINANCE")
        service.record_transaction(
            inst.id, "BUY", date(2021, 12, 15), D("270"), D("945.50")
        )
        service.refresh_prices(
            force=True, fetcher=lambda syms: {"BAJFINANCE.NS": D(close)}
        )
        return inst

    def test_price_of_one_is_held_back(self, service):
        self._priced(service, "1040")
        plan = service.plan_import(
            parse(sheet([["BAJFINANCE.NS", "BUY", 10, "2026-02-10", 1]]))
        )
        row = plan.rows[0]
        assert row.needs_review
        assert any("check for a typo" in w for w in row.warnings)

    def test_a_real_multi_year_move_is_not_flagged(self, service):
        # ITC bought at 370, trading at 262: ordinary history, must pass.
        inst = service.add_instrument("ITC.NS", "ITC")
        service.record_transaction(
            inst.id, "BUY", date(2021, 12, 15), D("2500"), D("370.52")
        )
        service.refresh_prices(
            force=True, fetcher=lambda syms: {"ITC.NS": D("262.80")}
        )
        plan = service.plan_import(
            parse(sheet([["ITC.NS", "BUY", 10, "2026-02-10", 265.40]]))
        )
        assert not plan.rows[0].needs_review
        assert plan.rows[0].warnings == []

    def test_lost_decimal_point_is_caught(self, service):
        self._priced(service, "1040")
        plan = service.plan_import(
            parse(sheet([["BAJFINANCE.NS", "BUY", 10, "2026-02-10", 104000]]))
        )
        assert plan.rows[0].needs_review

    def test_held_back_rows_are_still_applicable_if_confirmed(self, service):
        # Suspicious, not forbidden: a genuine outlier must remain enterable.
        self._priced(service, "1040")
        plan = service.plan_import(
            parse(sheet([["BAJFINANCE.NS", "BUY", 10, "2026-02-10", 1]]))
        )
        assert plan.rows[0].applies
        assert service.apply_import(plan)["applied"] == 1

    def test_new_stock_price_is_accepted_and_flagged_later(self, service):
        # No reference exists at import time, so it goes in as given...
        plan = service.plan_import(
            parse(sheet([["ZOMATO.NS", "BUY", 300, "2026-02-10", 1]]))
        )
        assert plan.rows[0].status == "new"
        assert not plan.rows[0].needs_review
        service.apply_import(plan)
        assert service.price_anomalies() == []

        # ...and is questioned once a real close is known.
        service.refresh_prices(
            force=True, fetcher=lambda syms: {"ZOMATO.NS": D("210.75")}
        )
        anomalies = service.price_anomalies()
        assert len(anomalies) == 1
        assert anomalies[0]["instrument"].symbol == "ZOMATO.NS"
        assert anomalies[0]["deviation"] > D("20")

    def test_sound_prices_produce_no_anomalies(self, service):
        self._priced(service, "1040")
        assert service.price_anomalies() == []


class TestApply:
    def test_applies_and_creates_instruments(self, service):
        itc(service)
        plan = service.plan_import(
            parse(sheet([
                ["ITC.NS", "BUY", 10, "2024-01-10", 400],
                ["TCS.NS", "BUY", 5, "2024-01-10", 3800],
            ]))
        )
        result = service.apply_import(plan)

        assert result == {"applied": 2, "instrumentsCreated": 1, "skipped": 0}
        assert service.position_for(service.find_by_symbol("ITC.NS")).quantity == D("110")
        assert service.find_by_symbol("TCS.NS") is not None

    def test_nothing_is_written_when_every_row_fails(self, service):
        itc(service)
        plan = service.plan_import(
            parse(sheet([["ITC.NS", "SELL", 500, "2024-01-10", 400]]))
        )
        with pytest.raises(Exception, match="nothing in this file"):
            service.apply_import(plan)
        assert service.position_for(service.find_by_symbol("ITC.NS")).quantity == D("100")

    def test_duplicate_rows_are_skipped_not_reapplied(self, service):
        inst = itc(service)
        existing = service.record_transaction(
            inst.id, "BUY", date(2024, 1, 10), D("10"), D("400")
        )
        before = service.position_for(service.get_instrument(inst.id)).quantity

        rows = parse(
            sheet(
                [["ITC.NS", "BUY", 10, "2024-01-10", 400, existing.reference]],
                headers=HEADERS + ["Reference"],
            )
        )
        with pytest.raises(Exception, match="nothing in this file"):
            service.apply_import(service.plan_import(rows))

        assert service.position_for(service.get_instrument(inst.id)).quantity == before

    def test_sheet_reference_is_preserved_so_reimport_is_idempotent(self, service):
        itc(service)
        rows = parse(
            sheet(
                [["ITC.NS", "BUY", 10, "2024-01-10", 400, "EXT-42"]],
                headers=HEADERS + ["Reference"],
            )
        )
        service.apply_import(service.plan_import(rows))

        second = service.plan_import(rows)
        assert second.rows[0].status == "duplicate"
