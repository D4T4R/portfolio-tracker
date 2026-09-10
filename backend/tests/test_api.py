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


class TestCorporateActionsOverHttp:
    """The demerger route: the one corporate action with no feed behind it."""

    def _pair(self, client):
        parent = add_itc(client)
        trade(client, parent, "BUY", "2021-12-15", "2500", "370.52")

        resp = client.post(
            "/api/v2/instruments",
            json={"symbol": "ITCHOTELS.NS", "name": "ITC Hotels"},
        )
        child = resp.get_json()["id"]
        trade(client, child, "BUY", "2021-12-15", "250", "574.80")
        return parent, child

    def demerge(self, client, parent, child, retained="0.8966"):
        return client.post(
            "/api/v2/corporate-actions/demerger",
            json={
                "parentId": parent,
                "childId": child,
                "exDate": "2025-01-06",
                "costRetained": retained,
            },
        )

    def test_the_two_costs_still_add_up_to_the_parents(self, client):
        parent, child = self._pair(client)
        body = self.demerge(client, parent, child).get_json()

        # A demerger deploys no new money, so the response has to show the
        # parent's cost merely divided. Half a paisa of slack: the carved cost
        # per share is stored at four decimals and 95,779.42 over 250 shares
        # does not land on that grid.
        combined = Decimal(body["parentCostAfter"]) + Decimal(body["childCost"])
        assert abs(combined - Decimal(body["parentCostBefore"])) < Decimal("0.05")

    def test_the_portfolio_stops_counting_invented_capital(self, client):
        parent, child = self._pair(client)
        before = client.get("/api/v2/portfolio").get_json()["summary"]["costBasis"]
        self.demerge(client, parent, child)
        after = client.get("/api/v2/portfolio").get_json()["summary"]["costBasis"]

        # The child was booked as an ordinary purchase, which is what a
        # spreadsheet does and what inflates the denominator of every return.
        assert Decimal(after) < Decimal(before)

    def test_a_preview_reports_the_figures_without_storing_them(self, client):
        parent, child = self._pair(client)
        before = client.get("/api/v2/portfolio").get_json()["summary"]["costBasis"]

        body = client.post(
            "/api/v2/corporate-actions/demerger",
            json={
                "parentId": parent,
                "childId": child,
                "exDate": "2025-01-06",
                "costRetained": "0.8966",
                "preview": True,
            },
        ).get_json()
        assert body["preview"] is True
        assert Decimal(body["childCost"]) > 0

        after = client.get("/api/v2/portfolio").get_json()["summary"]["costBasis"]
        assert after == before

    def test_a_preview_matches_what_applying_stores(self, client):
        # The dialog previews, the user approves, then it applies. If those two
        # disagreed, the figure approved would not be the figure on the books -
        # which is the whole reason the preview is computed here rather than in
        # the browser.
        parent, child = self._pair(client)
        payload = {
            "parentId": parent,
            "childId": child,
            "exDate": "2025-01-06",
            "costRetained": "0.8966",
        }
        previewed = client.post(
            "/api/v2/corporate-actions/demerger", json={**payload, "preview": True}
        ).get_json()
        applied = client.post(
            "/api/v2/corporate-actions/demerger", json=payload
        ).get_json()

        assert previewed["parentCostAfter"] == applied["parentCostAfter"]
        assert previewed["childCost"] == applied["childCost"]
        assert previewed["childPerShare"] == applied["childPerShare"]

    def test_an_out_of_range_ratio_is_rejected(self, client):
        parent, child = self._pair(client)
        resp = self.demerge(client, parent, child, retained="1.2")
        assert resp.status_code == 400
        assert "between 0 and 1" in resp.get_json()["error"]

    def test_a_missing_parent_is_rejected(self, client):
        _, child = self._pair(client)
        resp = client.post(
            "/api/v2/corporate-actions/demerger",
            json={"childId": child, "exDate": "2025-01-06", "costRetained": "0.9"},
        )
        assert resp.status_code == 400
        assert "parentId is required" in resp.get_json()["error"]

    def test_a_parent_from_another_portfolio_is_not_reachable(self, client):
        parent, child = self._pair(client)
        other = client.post(
            "/api/v2/portfolios", json={"name": "Trading"}
        ).get_json()["id"]

        resp = client.post(
            f"/api/v2/corporate-actions/demerger?portfolioId={other}",
            json={
                "parentId": parent,
                "childId": child,
                "exDate": "2025-01-06",
                "costRetained": "0.8966",
            },
        )
        assert resp.status_code == 404

    def test_suspects_name_the_unexplained_falls(self, client, monkeypatch):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        import portfolio.service as service_module

        # A 75% fall against cost: the shape a missed 4:1 action leaves behind.
        monkeypatch.setattr(
            service_module, "fetch_quotes", lambda syms: {"ITC.NS": Decimal("100")}
        )
        client.post("/api/v2/prices/refresh", json={"force": True})

        body = client.get("/api/v2/corporate-actions/suspects").get_json()
        assert [s["symbol"] for s in body["suspects"]] == ["ITC.NS"]
        assert body["suspects"][0]["impliedRatio"] == "4.00"
        assert body["suspects"][0]["instrumentId"] == iid

    def test_a_steady_price_raises_no_suspects(self, client, monkeypatch):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        import portfolio.service as service_module

        monkeypatch.setattr(
            service_module, "fetch_quotes", lambda syms: {"ITC.NS": Decimal("390")}
        )
        client.post("/api/v2/prices/refresh", json={"force": True})

        body = client.get("/api/v2/corporate-actions/suspects").get_json()
        assert body["suspects"] == []


class TestStockDetail:
    """The per-stock page: local figures, then the chart, fetched separately."""

    def test_detail_carries_the_holding_and_its_weight(self, client, monkeypatch):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        other = client.post(
            "/api/v2/instruments", json={"symbol": "TRENT.NS", "name": "Trent"}
        ).get_json()["id"]
        trade(client, other, "BUY", "2024-01-10", "100", "1200")

        import portfolio.service as service_module

        quotes = {"ITC.NS": Decimal("400"), "TRENT.NS": Decimal("1200")}
        monkeypatch.setattr(service_module, "fetch_quotes", lambda syms: quotes)
        client.post("/api/v2/prices/refresh", json={"force": True})

        body = client.get(f"/api/v2/instruments/{iid}/detail").get_json()
        assert body["instrument"]["symbol"] == "ITC.NS"
        assert body["tradeCount"] == 1
        assert body["firstTradeDate"] == "2024-01-10"
        # 40,000 of a 1,60,000 book.
        assert body["weightPct"] == "25.00"

    def test_detail_is_scoped_to_its_portfolio(self, client):
        iid = add_itc(client)
        other = client.post(
            "/api/v2/portfolios", json={"name": "Trading"}
        ).get_json()["id"]

        resp = client.get(
            f"/api/v2/instruments/{iid}/detail?portfolioId={other}"
        )
        assert resp.status_code == 404

    def test_history_marks_this_books_trades_on_the_candles(self, client, monkeypatch):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")
        trade(client, iid, "SELL", "2024-03-01", "40", "480")

        self.stub_candles(monkeypatch, [("2024-01-10", 400), ("2024-03-01", 480)])

        body = client.get(f"/api/v2/instruments/{iid}/history").get_json()
        assert [m["type"] for m in body["markers"]] == ["BUY", "SELL"]
        assert body["markers"][0]["price"] == "400.0000"
        assert body["averageCost"] == "400.0000"

    def test_markers_are_restated_for_splits_like_the_candles_are(
        self, client, monkeypatch
    ):
        # Markers carry the same basis as the average-cost line drawn beside
        # them. Left at the price paid, a pre-split buy would label the chart
        # at five times the cost the rest of the page reports.
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        import portfolio.service as service_module

        monkeypatch.setattr(
            service_module,
            "fetch_split_history",
            lambda syms, start: {"ITC.NS": [(date(2024, 6, 1), Decimal("5"))]},
        )
        client.post("/api/v2/corporate-actions/sync")

        self.stub_candles(monkeypatch, [("2024-01-10", 80)])
        body = client.get(f"/api/v2/instruments/{iid}/history").get_json()
        assert body["markers"][0]["price"] == "80.0000"
        assert body["markers"][0]["quantity"] == "500.000000"

    def test_a_trade_before_the_window_is_left_off(self, client, monkeypatch):
        # Charting libraries clamp an out-of-range marker to the edge, which
        # reads as a trade on a day it did not happen.
        iid = add_itc(client)
        trade(client, iid, "BUY", "2020-01-10", "100", "400")
        trade(client, iid, "BUY", "2024-02-10", "10", "450")

        self.stub_candles(monkeypatch, [("2024-01-01", 420), ("2024-02-10", 450)])
        body = client.get(f"/api/v2/instruments/{iid}/history?range=1mo").get_json()
        assert [m["date"] for m in body["markers"]] == ["2024-02-10"]

    def test_a_rate_limited_feed_returns_an_empty_chart_not_an_error(
        self, client, monkeypatch
    ):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        import portfolio.api as api_module

        def boom(symbol, period):
            raise api_module.HistoryFetchError("too many 429 error responses")

        monkeypatch.setattr(api_module, "fetch_history", boom)
        api_module._HISTORY_CACHE.clear()

        resp = client.get(f"/api/v2/instruments/{iid}/history")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["candles"] == []
        assert "429" in body["error"]

    def test_a_second_view_inside_the_window_does_not_refetch(
        self, client, monkeypatch
    ):
        iid = add_itc(client)
        trade(client, iid, "BUY", "2024-01-10", "100", "400")

        calls = []
        import portfolio.api as api_module
        from portfolio.history import Candle

        def counted(symbol, period):
            calls.append(symbol)
            return [Candle(date(2024, 1, 10), *[Decimal("400")] * 4, volume=1)]

        monkeypatch.setattr(api_module, "fetch_history", counted)
        api_module._HISTORY_CACHE.clear()

        client.get(f"/api/v2/instruments/{iid}/history")
        client.get(f"/api/v2/instruments/{iid}/history")
        assert len(calls) == 1

    @staticmethod
    def stub_candles(monkeypatch, rows):
        import portfolio.api as api_module
        from portfolio.history import Candle

        candles = [
            Candle(
                date.fromisoformat(day),
                Decimal(str(close)),
                Decimal(str(close)),
                Decimal(str(close)),
                Decimal(str(close)),
                volume=1000,
            )
            for day, close in rows
        ]
        monkeypatch.setattr(api_module, "fetch_history", lambda symbol, period: candles)
        api_module._HISTORY_CACHE.clear()
