"""HTTP surface over the ledger.

Mounted at /api/v2 alongside the legacy Excel endpoints so the old dashboard
keeps working while the new one is built.

Money crosses the wire as a JSON string, not a float. Serialising Decimal via
float would reintroduce exactly the drift the ledger uses Decimal to avoid, and
the frontend formats these for display rather than computing with them.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.orm import Session

from portfolio.ledger import (
    Transaction as LedgerTxn,
    TxnType,
    build_quantity_timeline,
    quantity_on_timeline,
)
from portfolio.imports import ImportError_, ParsedRow, parse
from portfolio.service import NotFound, PortfolioService, ServiceError

bp = Blueprint("ledger", __name__, url_prefix="/api/v2")

# Set by create_api(); a sessionmaker bound to the configured database.
_session_factory = None


def create_api(session_factory):
    """Bind the blueprint to a SQLAlchemy sessionmaker."""
    global _session_factory
    _session_factory = session_factory
    return bp


def _session() -> Session:
    if _session_factory is None:
        raise RuntimeError("ledger API not initialised; call create_api() first")
    return _session_factory()


def _requested_portfolio() -> str | None:
    """Which portfolio the caller is addressing, if it says.

    Accepted as a query parameter on every route and in the body of writes, so
    a request never depends on server-side "current portfolio" state - two
    browser tabs on different books would otherwise fight over it.
    """
    from_query = request.args.get("portfolioId")
    if from_query:
        return from_query
    if request.is_json:
        body = request.get_json(silent=True)
        if isinstance(body, dict) and body.get("portfolioId"):
            return body["portfolioId"]
    return None


def _service(session) -> PortfolioService:
    """A service scoped to the requested portfolio, or the default one."""
    return PortfolioService(session, _requested_portfolio())


# Division (average cost, percentages) yields full Decimal precision, which is
# right to compute with and wrong to publish. Quantize at the boundary only.
MONEY_SCALE = Decimal("0.01")
# Per-share prices keep the 4 places the numeric(18,4) column stores, so a
# value survives a round trip through the API unchanged.
PRICE_SCALE = Decimal("0.0001")
QUANTITY_SCALE = Decimal("0.000001")


def money(value, scale: Decimal = MONEY_SCALE) -> str:
    """Serialise a Decimal without going through binary floating point."""
    return f"{Decimal(value).quantize(scale, rounding=ROUND_HALF_UP):f}"


def quantity(value) -> str:
    """Quantities keep six places; fractional units exist in some instruments."""
    return f"{Decimal(value).quantize(QUANTITY_SCALE, rounding=ROUND_HALF_UP):f}"


def _decimal(payload: dict, field: str, default=None) -> Decimal:
    raw = payload.get(field, default)
    if raw is None:
        raise ServiceError(f"{field} is required")
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise ServiceError(f"{field} must be a number, got {raw!r}")


def _date(payload: dict, field: str) -> date:
    raw = payload.get(field)
    if not raw:
        raise ServiceError(f"{field} is required")
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").date()
    except ValueError:
        raise ServiceError(f"{field} must be YYYY-MM-DD, got {raw!r}")


def instrument_json(instrument) -> dict:
    return {
        "id": instrument.id,
        "symbol": instrument.symbol,
        "name": instrument.name,
        "status": instrument.status,
        "openingDividends": money(instrument.opening_dividends or 0),
        "dividendStartDate": (
            instrument.dividend_start_date.isoformat()
            if instrument.dividend_start_date
            else None
        ),
    }


def transaction_json(txn) -> dict:
    return {
        "id": txn.id,
        "reference": txn.reference,
        "instrumentId": txn.instrument_id,
        "type": txn.txn_type,
        "tradeDate": txn.trade_date.isoformat(),
        "quantity": quantity(txn.quantity),
        "price": money(txn.price, PRICE_SCALE),
        "fees": money(txn.fees or 0),
        "note": txn.note,
    }


def ledger_entry_json(txn) -> dict:
    """A trade with its instrument and cash effect, for the history view."""
    gross = Decimal(txn.quantity) * Decimal(txn.price)
    fees = Decimal(txn.fees or 0)
    # A buy takes cash out including costs; a sell brings it in net of them.
    net = gross + fees if txn.txn_type == "BUY" else gross - fees
    return {
        **transaction_json(txn),
        "symbol": txn.instrument.symbol,
        "name": txn.instrument.name,
        "status": txn.instrument.status,
        "grossValue": money(gross),
        "netValue": money(net),
    }


def holding_json(holding) -> dict:
    pos = holding.position
    return {
        "instrument": instrument_json(holding.instrument),
        "quantity": quantity(pos.quantity),
        "averageCost": money(pos.average_cost, PRICE_SCALE),
        "costBasis": money(pos.cost_basis),
        "totalInvested": money(pos.total_invested),
        "marketPrice": (money(holding.market_price, PRICE_SCALE)
                        if holding.market_price is not None else None),
        "marketValue": money(holding.market_value),
        "unrealized": money(holding.unrealized),
        "realized": money(pos.realized_gain),
        "dividendIncome": money(holding.dividend_income),
        "totalProfit": money(holding.total_profit),
        "totalReturnPct": money(holding.total_return_pct),
    }


@bp.errorhandler(NotFound)
def _handle_not_found(exc):
    return jsonify({"error": str(exc)}), 404


@bp.errorhandler(ServiceError)
def _handle_service_error(exc):
    return jsonify({"error": str(exc)}), 400


# -------------------------------------------------------------- portfolios


def portfolio_json(portfolio) -> dict:
    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "isDefault": portfolio.is_default,
    }


@bp.get("/portfolios")
def list_portfolios():
    with _session() as session:
        service = _service(session)
        portfolios = service.list_portfolios()
        session.commit()   # a default may have been created on first use
        return jsonify({
            "portfolios": [portfolio_json(p) for p in portfolios],
            "activeId": service.portfolio_id,
        })


@bp.post("/portfolios")
def create_portfolio():
    payload = request.get_json(silent=True) or {}
    with _session() as session:
        service = _service(session)
        portfolio = service.create_portfolio(payload.get("name", ""))
        session.commit()
        return jsonify(portfolio_json(portfolio)), 201


@bp.patch("/portfolios/<portfolio_id>")
def rename_portfolio(portfolio_id):
    payload = request.get_json(silent=True) or {}
    with _session() as session:
        service = _service(session)
        portfolio = service.rename_portfolio(portfolio_id, payload.get("name", ""))
        session.commit()
        return jsonify(portfolio_json(portfolio))


@bp.delete("/portfolios/<portfolio_id>")
def delete_portfolio(portfolio_id):
    with _session() as session:
        service = _service(session)
        service.delete_portfolio(portfolio_id)
        session.commit()
        return "", 204


# ------------------------------------------------------------- instruments


@bp.get("/instruments")
def list_instruments():
    include_archived = request.args.get("includeArchived") == "true"
    with _session() as session:
        service = _service(session)
        return jsonify({
            "instruments": [
                instrument_json(i)
                for i in service.list_instruments(include_archived)
            ]
        })


@bp.post("/instruments")
def add_instrument():
    payload = request.get_json(silent=True) or {}
    with _session() as session:
        service = _service(session)
        instrument = service.add_instrument(
            payload.get("symbol", ""), payload.get("name", "")
        )
        session.commit()
        return jsonify(instrument_json(instrument)), 201


@bp.post("/instruments/<instrument_id>/archive")
def archive_instrument(instrument_id):
    with _session() as session:
        service = _service(session)
        instrument = service.archive_instrument(instrument_id)
        session.commit()
        return jsonify(instrument_json(instrument))


@bp.post("/instruments/<instrument_id>/unarchive")
def unarchive_instrument(instrument_id):
    with _session() as session:
        service = _service(session)
        instrument = service.unarchive_instrument(instrument_id)
        session.commit()
        return jsonify(instrument_json(instrument))


# ------------------------------------------------------------ transactions


@bp.get("/instruments/<instrument_id>/transactions")
def list_transactions(instrument_id):
    with _session() as session:
        service = _service(session)
        instrument = service.get_instrument(instrument_id)
        return jsonify({
            "transactions": [transaction_json(t) for t in instrument.transactions]
        })


@bp.post("/instruments/<instrument_id>/transactions")
def record_transaction(instrument_id):
    payload = request.get_json(silent=True) or {}
    with _session() as session:
        service = _service(session)
        txn = service.record_transaction(
            instrument_id=instrument_id,
            txn_type=payload.get("type", ""),
            trade_date=_date(payload, "tradeDate"),
            quantity=_decimal(payload, "quantity"),
            price=_decimal(payload, "price"),
            fees=_decimal(payload, "fees", "0"),
            note=payload.get("note"),
        )
        session.commit()
        return jsonify(transaction_json(txn)), 201


@bp.get("/transactions")
def list_all_transactions():
    """The whole ledger across every instrument, newest first."""
    with _session() as session:
        service = _service(session)
        return jsonify({
            "transactions": [
                ledger_entry_json(t) for t in service.all_transactions()
            ]
        })


@bp.delete("/transactions/<txn_id>")
def delete_transaction(txn_id):
    with _session() as session:
        service = _service(session)
        service.delete_transaction(txn_id)
        session.commit()
        return "", 204


# --------------------------------------------------------------- portfolio


@bp.get("/portfolio")
def portfolio():
    include_archived = request.args.get("includeArchived") == "true"
    with _session() as session:
        service = _service(session)
        prices, as_of = service.stored_prices()
        holdings = service.holdings(prices, include_archived)

        # Totals always span archived names too. A closed position's realized
        # gain and dividends are permanently part of the portfolio's result,
        # and dropping them silently overstates profit by every booked loss.
        everything = service.holdings(prices, include_archived=True)

        invested = sum((h.position.cost_basis for h in everything), Decimal("0"))
        market = sum((h.market_value for h in everything), Decimal("0"))
        unrealized = sum((h.unrealized for h in everything), Decimal("0"))
        realized = sum((h.position.realized_gain for h in everything), Decimal("0"))
        dividends = sum((h.dividend_income for h in everything), Decimal("0"))
        deployed = sum((h.position.total_invested for h in everything), Decimal("0"))

        # Totalled from the rounded components rather than the raw ones. The
        # dashboard prints "unrealized + realized + dividends = total", and
        # rounding each part separately can leave that a paisa short - which
        # reads as a broken sum however small it is.
        unrealized_s = money(unrealized)
        realized_s = money(realized)
        dividends_s = money(dividends)
        total_profit = (
            Decimal(unrealized_s) + Decimal(realized_s) + Decimal(dividends_s)
        )
        return_pct = (
            total_profit * 100 / deployed if deployed > 0 else Decimal("0")
        )

        return jsonify({
            "holdings": [holding_json(h) for h in holdings],
            "summary": {
                "positions": len([h for h in everything if h.position.is_open]),
                "costBasis": money(invested),
                "marketValue": money(market),
                "unrealized": unrealized_s,
                "realized": realized_s,
                "dividends": dividends_s,
                "capitalDeployed": money(deployed),
                "totalProfit": money(total_profit),
                "totalReturnPct": money(return_pct),
            },
            "pricesAsOf": as_of.isoformat() if as_of else None,
        })


@bp.post("/prices/refresh")
def refresh_prices():
    payload = request.get_json(silent=True) or {}
    force = bool(payload.get("force"))

    with _session() as session:
        service = _service(session)
        last_fetch = current_app.config.get("LAST_PRICE_FETCH_AT")
        result = service.refresh_prices(force=force, last_fetch_at=last_fetch)

        if result.live:
            current_app.config["LAST_PRICE_FETCH_AT"] = datetime.now()
        session.commit()

        return jsonify({
            "live": result.live,
            "reason": result.reason,
            "marketStatus": result.status.value,
            "asOf": result.as_of.isoformat() if result.as_of else None,
            "error": result.error,
            "prices": {s: money(p, PRICE_SCALE) for s, p in result.prices.items()},
        })


@bp.post("/dividends/sync")
def sync_dividends():
    """Pull dividend history from the feed for every tracked instrument."""
    with _session() as session:
        service = _service(session)
        result = service.sync_dividends()
        session.commit()
        return jsonify({
            "added": result.added,
            "updated": result.updated,
            "symbols": result.symbols,
            "error": result.error,
        })


@bp.get("/instruments/<instrument_id>/dividends")
def list_dividends(instrument_id):
    with _session() as session:
        service = _service(session)
        instrument = service.get_instrument(instrument_id)
        ledger = [
            LedgerTxn(
                trade_date=t.trade_date,
                txn_type=TxnType(t.txn_type),
                quantity=Decimal(t.quantity),
                price=Decimal(t.price),
                fees=Decimal(t.fees or 0),
            )
            for t in instrument.transactions
        ]
        dates, quantities = build_quantity_timeline(ledger)

        rows = []
        for dividend in instrument.dividends:
            held = quantity_on_timeline(dates, quantities, dividend.ex_date)
            rows.append({
                "id": dividend.id,
                "exDate": dividend.ex_date.isoformat(),
                "perShare": money(dividend.per_share, PRICE_SCALE),
                "quantityHeld": quantity(held),
                "amount": money(Decimal(dividend.per_share) * held),
                "source": dividend.source,
            })

        return jsonify({
            "dividends": rows,
            "openingDividends": money(instrument.opening_dividends or 0),
            "total": money(service.dividend_income(instrument)),
        })


def planned_trade_json(entry) -> dict:
    return {
        "rowNumber": entry.row_number,
        "rawSymbol": entry.raw_symbol,
        "status": entry.status,
        "symbol": entry.symbol,
        "instrumentId": entry.instrument_id,
        "instrumentName": entry.instrument_name,
        "type": entry.txn_type,
        "tradeDate": entry.trade_date.isoformat() if entry.trade_date else None,
        "quantity": quantity(entry.quantity) if entry.quantity is not None else None,
        "price": (money(entry.price, PRICE_SCALE)
                  if entry.price is not None else None),
        "fees": money(entry.fees or 0),
        "note": entry.note,
        "reference": entry.reference,
        "errors": entry.errors,
        "warnings": entry.warnings,
        "suggestions": entry.suggestions,
        "needsReview": entry.needs_review,
    }


def plan_json(plan) -> dict:
    return {
        "rows": [planned_trade_json(r) for r in plan.rows],
        "counts": plan.counts,
        "newSymbols": plan.new_symbols,
    }


def _rows_from_payload(payload: list) -> list[ParsedRow]:
    """Rebuild parser output from a confirmed plan.

    Deliberately goes back through the same normalisation the file did, so a
    posted row cannot smuggle in a value the parser would have rejected.
    """
    rows = []
    for item in payload:
        row = ParsedRow(
            row_number=int(item.get("rowNumber") or 0),
            raw_symbol=str(item.get("symbol") or item.get("rawSymbol") or ""),
            txn_type=item.get("type"),
            reference=item.get("reference"),
            note=item.get("note"),
        )
        try:
            row.trade_date = datetime.strptime(
                str(item.get("tradeDate")), "%Y-%m-%d"
            ).date()
        except (ValueError, TypeError):
            row.errors.append("trade date missing or malformed")
        for attr, key in (("quantity", "quantity"), ("price", "price")):
            try:
                setattr(row, attr, Decimal(str(item.get(key))))
            except (InvalidOperation, TypeError):
                row.errors.append(f"{key} missing or malformed")
        try:
            row.fees = Decimal(str(item.get("fees") or "0"))
        except (InvalidOperation, TypeError):
            row.fees = Decimal("0")
        if row.txn_type not in ("BUY", "SELL"):
            row.errors.append("type must be BUY or SELL")
        rows.append(row)
    return rows


@bp.post("/imports/preview")
def preview_import():
    """Parse and validate an uploaded sheet. Writes nothing."""
    upload = request.files.get("file")
    if upload is None:
        return jsonify({"error": "no file uploaded"}), 400

    try:
        rows = parse(upload)
    except ImportError_ as exc:
        return jsonify({"error": str(exc)}), 400

    with _session() as session:
        service = _service(session)
        # Read-only: the session is discarded without a commit.
        return jsonify(plan_json(service.plan_import(rows)))


@bp.post("/imports/apply")
def apply_import():
    """Apply a confirmed plan, all rows or none."""
    payload = request.get_json(silent=True) or {}
    submitted = payload.get("rows")
    if not isinstance(submitted, list) or not submitted:
        raise ServiceError("no rows to apply")

    with _session() as session:
        service = _service(session)
        # Re-planned against the live database rather than trusting what came
        # back: trades may have been recorded between preview and confirm.
        plan = service.plan_import(_rows_from_payload(submitted))
        result = service.apply_import(plan)
        session.commit()
        return jsonify({**result, "plan": plan_json(plan)})


@bp.post("/corporate-actions/sync")
def sync_corporate_actions():
    """Pull splits and bonuses, then report anything still looking unexplained."""
    with _session() as session:
        service = _service(session)
        result = service.sync_corporate_actions()
        session.commit()
        return jsonify({
            "added": result.added,
            "updated": result.updated,
            "symbols": result.symbols,
            "error": result.error,
            "suspects": [
                {
                    "symbol": s["instrument"].symbol,
                    "name": s["instrument"].name,
                    "averageCost": money(s["averageCost"], PRICE_SCALE),
                    "price": money(s["price"], PRICE_SCALE),
                    "dropPct": money(s["drop"] * 100),
                    "impliedRatio": money(s["impliedRatio"]),
                }
                for s in service.suspected_corporate_actions()
            ],
        })


@bp.get("/price-anomalies")
def price_anomalies():
    """Recorded trades whose price looks like a data-entry error.

    A stock added by import has no reference price at the time, so a price of
    1 cannot be questioned then. Once a close exists this catches it.
    """
    with _session() as session:
        service = _service(session)
        return jsonify({
            "anomalies": [
                {
                    "reference": a["transaction"].reference,
                    "transactionId": a["transaction"].id,
                    "symbol": a["instrument"].symbol,
                    "name": a["instrument"].name,
                    "type": a["transaction"].txn_type,
                    "tradeDate": a["transaction"].trade_date.isoformat(),
                    "quantity": quantity(a["transaction"].quantity),
                    "price": money(a["transaction"].price, PRICE_SCALE),
                    "referencePrice": money(a["reference"], PRICE_SCALE),
                    "deviation": money(a["deviation"]),
                }
                for a in service.price_anomalies()
            ]
        })


@bp.get("/capital-gains")
def capital_gains():
    """FIFO-matched disposals, for the tax export."""
    with _session() as session:
        service = _service(session)
        rows = []
        for instrument in service.list_instruments(include_archived=True):
            for sale in service.realized_sales(instrument):
                rows.append({
                    "symbol": instrument.symbol,
                    "name": instrument.name,
                    "acquiredOn": sale.acquired_on.isoformat(),
                    "soldOn": sale.sold_on.isoformat(),
                    "quantity": quantity(sale.quantity),
                    "cost": money(sale.cost),
                    "proceeds": money(sale.proceeds),
                    "gain": money(sale.gain),
                    "holdingDays": sale.holding_days,
                    "term": sale.term,
                })
        rows.sort(key=lambda r: r["soldOn"])
        return jsonify({"sales": rows})
