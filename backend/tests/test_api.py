"""End-to-end tests for the ledger HTTP API."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from portfolio.api import create_api
from portfolio.models import Base
from portfolio.prices import IST, PriceFetchError


@pytest.fixture
def client():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_api(factory))
    with app.test_client() as c:
        c.engine = engine
        yield c


def add_itc(client):
    resp = client.post("/api/v2/instruments", json={"symbol": "ITC.NS", "name": "ITC"})
    assert resp.status_code == 201
    return resp.get_json()["id"]


def trade(client, iid, type_, day, qty, price, fees="0"):
    return client.post(
        f"/api/v2/instruments/{iid}/transactions",
        json={
            "type": type_,
            "tradeDate": day,
            "quantity": qty,
            "price": price,
            "fees": fees,
        },
    )


class TestInstruments:
    def test_add_and_list(self, client):
        add_itc(client)
        body = client.get("/api/v2/instruments").get_json()
        assert [i["symbol"] for i in body["instruments"]] == ["ITC.NS"]

    def test_duplicate_returns_400(self, client):
        add_itc(client)
        resp = client.post(
            "/api/v2/instruments", json={"symbol": "ITC.NS", "name": "ITC"}
        )
        assert resp.status_code == 400
        assert "already tracked" in resp.get_json()["error"]

    def test_archive_open_position_returns_400(self, client):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        resp = client.post(f"/api/v2/instruments/{iid}/archive")
        assert resp.status_code == 400
        assert "still holds" in resp.get_json()["error"]

    def test_archive_then_hidden_from_default_list(self, client):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")
        trade(client, iid, "SELL", "2024-06-10", "100", "450")

        assert client.post(f"/api/v2/instruments/{iid}/archive").status_code == 200
        assert client.get("/api/v2/instruments").get_json()["instruments"] == []

        body = client.get("/api/v2/instruments?includeArchived=true").get_json()
        assert body["instruments"][0]["status"] == "archived"

    def test_unknown_instrument_returns_404(self, client):
        assert client.post("/api/v2/instruments/nope/archive").status_code == 404


class TestTransactions:
    def test_record_and_list(self, client):
        iid = add_itc(client)
        assert trade(client, iid, "BUY", "2024-01-10", "100", "400").status_code == 201

        body = client.get(f"/api/v2/instruments/{iid}/transactions").get_json()
        assert len(body["transactions"]) == 1
        assert body["transactions"][0]["type"] == "BUY"

    def test_oversell_returns_400(self, client):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        resp = trade(client, iid, "SELL", "2024-06-10", "101", "450")
        assert resp.status_code == 400
        assert "exceeds" in resp.get_json()["error"]

    def test_bad_date_returns_400(self, client):
        iid = add_itc(client)
        resp = trade(client, iid, "BUY", "10-01-2024", "100", "400")
        assert resp.status_code == 400
        assert "YYYY-MM-DD" in resp.get_json()["error"]

    def test_non_numeric_quantity_returns_400(self, client):
        iid = add_itc(client)
        resp = trade(client, iid, "BUY", "2024-01-10", "many", "400")
        assert resp.status_code == 400
        assert "must be a number" in resp.get_json()["error"]

    def test_delete_transaction(self, client):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")
        extra = trade(client, iid, "BUY", "2024-03-10", "50", "500").get_json()

        assert client.delete(f"/api/v2/transactions/{extra['id']}").status_code == 204
        body = client.get(f"/api/v2/instruments/{iid}/transactions").get_json()
        assert len(body["transactions"]) == 1

    def test_money_is_serialised_as_string(self, client):
        # Floats would reintroduce the drift Decimal exists to prevent.
        iid = add_itc(client)
        body = trade(client, iid, "BUY", "2024-01-10", "100", "400.1234").get_json()
        assert isinstance(body["price"], str)
        assert body["price"] == "400.1234"


class TestLedgerHistory:
    def test_lists_trades_across_instruments_newest_first(self, client):
        itc = add_itc(client)
        trade(client, itc, "BUY", "2024-01-10", "100", "400")

        tcs = client.post(
            "/api/v2/instruments", json={"symbol": "TCS.NS", "name": "TCS"}
        ).get_json()["id"]
        trade(client, tcs, "BUY", "2024-06-10", "10", "3800")

        rows = client.get("/api/v2/transactions").get_json()["transactions"]
        assert [(r["symbol"], r["tradeDate"]) for r in rows] == [
            ("TCS.NS", "2024-06-10"),
            ("ITC.NS", "2024-01-10"),
        ]

    def test_cash_effect_puts_fees_on_the_right_side(self, client):
        # Fees add to what a buy costs and subtract from what a sell returns.
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400", fees="150")
        trade(client, iid, "SELL", "2024-06-10", "40", "500", fees="80")

        rows = client.get("/api/v2/transactions").get_json()["transactions"]
        sell, buy = rows

        assert buy["grossValue"] == "40000.00"
        assert buy["netValue"] == "40150.00"
        assert sell["grossValue"] == "20000.00"
        assert sell["netValue"] == "19920.00"

    def test_archived_names_still_appear(self, client):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")
        trade(client, iid, "SELL", "2024-06-10", "100", "450")
        client.post(f"/api/v2/instruments/{iid}/archive")

        rows = client.get("/api/v2/transactions").get_json()["transactions"]
        assert len(rows) == 2
        assert {r["status"] for r in rows} == {"archived"}

    def test_empty_ledger_is_not_an_error(self, client):
        assert client.get("/api/v2/transactions").get_json() == {"transactions": []}


class TestPortfolio:
    def test_summary_counts_each_component_once(self, client):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")
        trade(client, iid, "SELL", "2024-06-10", "40", "500")

        body = client.get("/api/v2/portfolio").get_json()
        summary = body["summary"]

        assert summary["positions"] == 1
        assert Decimal(summary["realized"]) == Decimal("4000")
        assert Decimal(summary["costBasis"]) == Decimal("24000")  # 60 * 400
        # No price stored yet, so market value stays zero rather than invented.
        assert Decimal(summary["marketValue"]) == Decimal("0")
        assert body["pricesAsOf"] is None

    def test_archived_losses_still_count_toward_totals(self, client):
        # A booked loss on an exited position must not disappear from the
        # summary just because the name is hidden from the holdings list.
        open_id = add_itc(client)
        trade(client, open_id, "BUY", "2024-01-10", "100", "400")

        exited = client.post(
            "/api/v2/instruments", json={"symbol": "DELTACORP.NS", "name": "Deltacorp"}
        ).get_json()["id"]
        trade(client, exited, "BUY", "2024-01-10", "100", "300")
        trade(client, exited, "SELL", "2024-06-10", "100", "200")   # -10,000
        client.post(f"/api/v2/instruments/{exited}/archive")

        body = client.get("/api/v2/portfolio").get_json()
        # Hidden from the list...
        assert len(body["holdings"]) == 1
        # ...but its loss is still in the total.
        assert Decimal(body["summary"]["realized"]) == Decimal("-10000")

    def test_displayed_parts_add_up_exactly(self, client):
        # Quantities chosen so each component rounds, which is where a total
        # computed from raw Decimals drifts a paisa from the printed figures.
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "3", "333.335")
        trade(client, iid, "SELL", "2024-06-10", "1", "466.665")

        s = client.get("/api/v2/portfolio").get_json()["summary"]
        assert Decimal(s["unrealized"]) + Decimal(s["realized"]) + Decimal(
            s["dividends"]
        ) == Decimal(s["totalProfit"])

    def test_total_profit_is_the_sum_of_its_parts(self, client):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")
        trade(client, iid, "SELL", "2024-06-10", "40", "500")

        s = client.get("/api/v2/portfolio").get_json()["summary"]
        assert Decimal(s["totalProfit"]) == (
            Decimal(s["unrealized"]) + Decimal(s["realized"]) + Decimal(s["dividends"])
        )


class TestPriceRefresh:
    def test_refresh_stores_and_reports_live(self, client, monkeypatch):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        import portfolio.service as service_module

        monkeypatch.setattr(
            service_module, "fetch_quotes", lambda syms: {"ITC.NS": Decimal("416.85")}
        )

        body = client.post("/api/v2/prices/refresh", json={"force": True}).get_json()
        assert body["live"] is True
        # Per-share prices serialise at the column's 4-place scale.
        assert body["prices"]["ITC.NS"] == "416.8500"

        portfolio = client.get("/api/v2/portfolio").get_json()
        assert Decimal(portfolio["summary"]["marketValue"]) == Decimal("41685")

    def test_rate_limit_keeps_stored_prices_and_flags_not_live(
        self, client, monkeypatch
    ):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        import portfolio.service as service_module

        monkeypatch.setattr(
            service_module, "fetch_quotes", lambda syms: {"ITC.NS": Decimal("400")}
        )
        client.post("/api/v2/prices/refresh", json={"force": True})

        def boom(syms):
            raise PriceFetchError("too many 429 error responses")

        monkeypatch.setattr(service_module, "fetch_quotes", boom)

        # Clear the throttle so the failure path is what is exercised.
        client.application.config["LAST_PRICE_FETCH_AT"] = datetime.now(
            IST
        ) - timedelta(minutes=5)

        body = client.post("/api/v2/prices/refresh", json={"force": True}).get_json()
        assert body["live"] is False
        assert "429" in body["error"]
        # The previously stored close survives rather than vanishing.
        assert body["prices"]["ITC.NS"] == "400.0000"


class TestDividends:
    def test_sync_then_listed_with_holding_context(self, client, monkeypatch):
        from datetime import date as _date

        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")
        trade(client, iid, "SELL", "2024-05-01", "40", "450")

        import portfolio.service as service_module

        monkeypatch.setattr(
            service_module,
            "fetch_dividend_history",
            lambda syms, start: {
                "ITC.NS": [
                    (_date(2024, 2, 8), Decimal("6.25")),   # 100 held
                    (_date(2024, 6, 4), Decimal("7.50")),   # 60 held
                ]
            },
        )

        result = client.post("/api/v2/dividends/sync").get_json()
        assert result["added"] == 2 and result["error"] is None

        body = client.get(f"/api/v2/instruments/{iid}/dividends").get_json()
        rows = body["dividends"]
        # Each payment is valued against the holding on its own ex-date.
        assert rows[0]["quantityHeld"] == "100.000000"
        assert rows[0]["amount"] == "625.00"
        assert rows[1]["quantityHeld"] == "60.000000"
        assert rows[1]["amount"] == "450.00"
        assert body["total"] == "1075.00"

    def test_nothing_to_sync_when_no_trades_recorded(self, client, monkeypatch):
        # No trades means no start date, so there is no window to fetch and
        # the upstream should not be called at all.
        add_itc(client)
        import portfolio.service as service_module

        def must_not_run(syms, start):  # pragma: no cover
            raise AssertionError("should not have called the dividend feed")

        monkeypatch.setattr(service_module, "fetch_dividend_history", must_not_run)
        body = client.post("/api/v2/dividends/sync").get_json()
        assert body == {"added": 0, "updated": 0, "symbols": 0, "error": None}

    def test_sync_failure_is_reported_not_raised(self, client, monkeypatch):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")
        import portfolio.service as service_module
        from portfolio.dividends import DividendFetchError

        def boom(syms, start):
            raise DividendFetchError("too many 429 error responses")

        monkeypatch.setattr(service_module, "fetch_dividend_history", boom)

        body = client.post("/api/v2/dividends/sync").get_json()
        assert body["added"] == 0
        assert "429" in body["error"]


class TestImportEndpoints:
    def upload(self, client, rows, headers=None):
        import io

        import pandas as pd

        headers = headers or ["Ticker", "Type", "Quantity", "Date", "Price"]
        buffer = io.BytesIO()
        pd.DataFrame(rows, columns=headers).to_excel(buffer, index=False)
        buffer.seek(0)
        return client.post(
            "/api/v2/imports/preview",
            data={"file": (buffer, "trades.xlsx")},
            content_type="multipart/form-data",
        )

    def test_preview_writes_nothing(self, client):
        add_itc(client)
        body = self.upload(
            client, [["ITC.NS", "BUY", 100, "2024-01-10", 400]]
        ).get_json()

        assert body["counts"]["ok"] == 1
        # Preview is read-only; the ledger is untouched until apply.
        assert client.get("/api/v2/transactions").get_json()["transactions"] == []

    def test_missing_price_column_is_a_400(self, client):
        resp = self.upload(
            client,
            [["ITC.NS", "BUY", 100, "2024-01-10"]],
            headers=["Ticker", "Type", "Quantity", "Date"],
        )
        assert resp.status_code == 400
        assert "price" in resp.get_json()["error"]

    def test_no_file_is_a_400(self, client):
        resp = client.post("/api/v2/imports/apply", json={"rows": []})
        assert resp.status_code == 400

    def test_preview_then_apply(self, client):
        add_itc(client)
        plan = self.upload(
            client,
            [
                ["ITC.NS", "BUY", 100, "2024-01-10", 400],
                ["TCS.NS", "BUY", 10, "2024-01-10", 3800],
            ],
        ).get_json()

        rows = [r for r in plan["rows"] if r["status"] in ("ok", "new")]
        result = client.post("/api/v2/imports/apply", json={"rows": rows}).get_json()

        assert result["applied"] == 2
        assert result["instrumentsCreated"] == 1

        ledger = client.get("/api/v2/transactions").get_json()["transactions"]
        assert len(ledger) == 2
        assert all(r["reference"].startswith("TXN-") for r in ledger)

    def test_apply_revalidates_against_the_live_ledger(self, client):
        # A sell that was valid at preview time must not be applied if the
        # position has since been sold off in another tab.
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        plan = self.upload(
            client, [["ITC.NS", "SELL", 100, "2024-06-10", 500]]
        ).get_json()
        assert plan["counts"]["ok"] == 1

        trade(client, iid, "SELL", "2024-05-01", "100", "480")

        resp = client.post("/api/v2/imports/apply", json={"rows": plan["rows"]})
        assert resp.status_code == 400
        assert "nothing in this file" in resp.get_json()["error"]


class TestCapitalGains:
    def test_fifo_export_classifies_terms(self, client):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2021-12-15", "100", "400")
        trade(client, iid, "BUY", "2024-01-10", "50", "450")
        trade(client, iid, "SELL", "2024-03-01", "120", "500")

        sales = client.get("/api/v2/capital-gains").get_json()["sales"]
        assert len(sales) == 2
        assert sales[0]["term"] == "LTCG"
        assert sales[0]["quantity"] == "100.000000"
        assert sales[1]["term"] == "STCG"
        assert sales[1]["quantity"] == "20.000000"
