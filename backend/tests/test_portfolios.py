"""Multiple portfolios, and the isolation between them."""

from datetime import date
from decimal import Decimal as D

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from portfolio.api import create_api
from portfolio.models import Base
from portfolio.service import NotFound, PortfolioService, ServiceError


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def client():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(create_api(factory))
    with app.test_client() as c:
        yield c


def stocked(session, portfolio_id, symbol="ITC.NS", qty="100", price="400"):
    svc = PortfolioService(session, portfolio_id)
    inst = svc.add_instrument(symbol, symbol.split(".")[0])
    svc.record_transaction(inst.id, "BUY", date(2024, 1, 10), D(qty), D(price))
    return svc, inst


class TestDefaults:
    def test_a_default_is_created_on_first_use(self, session):
        svc = PortfolioService(session)
        assert svc.portfolio_id is not None
        assert svc.default_portfolio().is_default is True

    def test_callers_naming_no_portfolio_share_the_default(self, session):
        a = PortfolioService(session)
        a.add_instrument("ITC.NS", "ITC")
        b = PortfolioService(session)
        assert [i.symbol for i in b.list_instruments()] == ["ITC.NS"]

    def test_first_created_portfolio_becomes_the_default(self, session):
        svc = PortfolioService(session)
        first = svc.create_portfolio("Long term")
        second = svc.create_portfolio("Trading")
        assert first.is_default is True
        assert second.is_default is False


class TestIsolation:
    def test_holdings_do_not_leak_between_portfolios(self, session):
        svc = PortfolioService(session)
        a = svc.create_portfolio("Long term")
        b = svc.create_portfolio("Trading")

        stocked(session, a.id, "ITC.NS")
        stocked(session, b.id, "TCS.NS")

        assert [i.symbol for i in PortfolioService(session, a.id).list_instruments()] == ["ITC.NS"]
        assert [i.symbol for i in PortfolioService(session, b.id).list_instruments()] == ["TCS.NS"]

    def test_the_same_stock_can_sit_in_both_with_different_cost(self, session):
        svc = PortfolioService(session)
        a = svc.create_portfolio("Long term")
        b = svc.create_portfolio("Trading")

        stocked(session, a.id, "ITC.NS", "100", "400")
        stocked(session, b.id, "ITC.NS", "50", "250")

        assert PortfolioService(session, a.id).position_for(
            PortfolioService(session, a.id).find_by_symbol("ITC.NS")
        ).average_cost == D("400")
        assert PortfolioService(session, b.id).position_for(
            PortfolioService(session, b.id).find_by_symbol("ITC.NS")
        ).average_cost == D("250")

    def test_an_id_from_another_portfolio_is_not_readable(self, session):
        svc = PortfolioService(session)
        a = svc.create_portfolio("Long term")
        b = svc.create_portfolio("Trading")
        _, mine = stocked(session, a.id)

        # Knowing the id must not be enough; the scope has to match.
        with pytest.raises(NotFound):
            PortfolioService(session, b.id).get_instrument(mine.id)

    def test_an_id_from_another_portfolio_is_not_writable(self, session):
        svc = PortfolioService(session)
        a = svc.create_portfolio("Long term")
        b = svc.create_portfolio("Trading")
        _, mine = stocked(session, a.id)

        with pytest.raises(NotFound):
            PortfolioService(session, b.id).record_transaction(
                mine.id, "BUY", date(2024, 2, 1), D("10"), D("400")
            )

    def test_a_trade_cannot_be_deleted_through_another_portfolio(self, session):
        svc = PortfolioService(session)
        a = svc.create_portfolio("Long term")
        b = svc.create_portfolio("Trading")
        svc_a, inst = stocked(session, a.id)
        txn = svc_a.record_transaction(
            inst.id, "BUY", date(2024, 3, 1), D("10"), D("410")
        )

        with pytest.raises(NotFound):
            PortfolioService(session, b.id).delete_transaction(txn.id)
        assert len(PortfolioService(session, a.id).get_instrument(inst.id).transactions) == 2

    def test_the_ledger_listing_is_scoped(self, session):
        svc = PortfolioService(session)
        a = svc.create_portfolio("Long term")
        b = svc.create_portfolio("Trading")
        stocked(session, a.id, "ITC.NS")
        stocked(session, b.id, "TCS.NS")

        rows = PortfolioService(session, a.id).all_transactions()
        assert {r.instrument.symbol for r in rows} == {"ITC.NS"}

    def test_totals_are_computed_per_portfolio(self, session):
        svc = PortfolioService(session)
        a = svc.create_portfolio("Long term")
        b = svc.create_portfolio("Trading")
        stocked(session, a.id, "ITC.NS", "100", "400")   # 40,000
        stocked(session, b.id, "TCS.NS", "10", "3800")   # 38,000

        cost_a = sum(
            (h.position.cost_basis for h in PortfolioService(session, a.id).holdings()),
            D(0),
        )
        assert cost_a == D("40000")


class TestManagement:
    def test_duplicate_name_is_rejected(self, session):
        svc = PortfolioService(session)
        svc.create_portfolio("Long term")
        with pytest.raises(ServiceError, match="already exists"):
            svc.create_portfolio("long term")

    def test_deleting_a_portfolio_with_trades_is_refused(self, session):
        svc = PortfolioService(session)
        a = svc.create_portfolio("Long term")
        svc.create_portfolio("Trading")
        stocked(session, a.id)

        with pytest.raises(ServiceError, match="still holds"):
            svc.delete_portfolio(a.id)

    def test_cannot_delete_the_only_portfolio(self, session):
        svc = PortfolioService(session)
        only = svc.create_portfolio("Long term")
        with pytest.raises(ServiceError, match="only portfolio"):
            svc.delete_portfolio(only.id)

    def test_deleting_the_default_promotes_another(self, session):
        svc = PortfolioService(session)
        first = svc.create_portfolio("Long term")
        second = svc.create_portfolio("Trading")
        assert first.is_default

        svc.delete_portfolio(first.id)
        # Something must still answer a request that names no portfolio.
        assert svc.default_portfolio().id == second.id


class TestApi:
    @staticmethod
    def second(client, name="Trading"):
        """Add a portfolio alongside the default.

        The listing call is what materialises the default, exactly as the app
        does on load. Without it the new portfolio would be the only one, and
        so become the default itself.
        """
        client.get("/api/v2/portfolios")
        return client.post("/api/v2/portfolios", json={"name": name}).get_json()

    def test_default_portfolio_is_listed(self, client):
        body = client.get("/api/v2/portfolios").get_json()
        assert len(body["portfolios"]) == 1
        assert body["activeId"] == body["portfolios"][0]["id"]

    def test_first_portfolio_on_an_empty_database_is_the_default(self, client):
        only = client.post("/api/v2/portfolios", json={"name": "Trading"}).get_json()
        assert only["isDefault"] is True

    def test_create_then_scope_by_query_parameter(self, client):
        b = self.second(client)

        client.post("/api/v2/instruments", json={"symbol": "ITC.NS", "name": "ITC"})
        client.post(
            f"/api/v2/instruments?portfolioId={b['id']}",
            json={"symbol": "TCS.NS", "name": "TCS"},
        )

        default = client.get("/api/v2/instruments").get_json()["instruments"]
        trading = client.get(
            f"/api/v2/instruments?portfolioId={b['id']}"
        ).get_json()["instruments"]

        assert [i["symbol"] for i in default] == ["ITC.NS"]
        assert [i["symbol"] for i in trading] == ["TCS.NS"]

    def test_cross_portfolio_access_is_a_404(self, client):
        b = self.second(client)
        mine = client.post(
            "/api/v2/instruments", json={"symbol": "ITC.NS", "name": "ITC"}
        ).get_json()

        resp = client.get(
            f"/api/v2/instruments/{mine['id']}/transactions?portfolioId={b['id']}"
        )
        assert resp.status_code == 404

    def test_summary_is_scoped(self, client):
        b = self.second(client)
        itc = client.post(
            "/api/v2/instruments", json={"symbol": "ITC.NS", "name": "ITC"}
        ).get_json()
        client.post(
            f"/api/v2/instruments/{itc['id']}/transactions",
            json={"type": "BUY", "tradeDate": "2024-01-10",
                  "quantity": "100", "price": "400", "fees": "0"},
        )

        empty = client.get(f"/api/v2/portfolio?portfolioId={b['id']}").get_json()
        assert empty["holdings"] == []
        assert D(empty["summary"]["costBasis"]) == D("0")

        mine = client.get("/api/v2/portfolio").get_json()
        assert D(mine["summary"]["costBasis"]) == D("40000")

    def test_duplicate_name_returns_400(self, client):
        self.second(client)
        resp = client.post("/api/v2/portfolios", json={"name": "Trading"})
        assert resp.status_code == 400

    def test_rename(self, client):
        p = self.second(client)
        body = client.patch(
            f"/api/v2/portfolios/{p['id']}", json={"name": "Short term"}
        ).get_json()
        assert body["name"] == "Short term"
