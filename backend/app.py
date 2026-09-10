from flask import Flask, jsonify, request
from flask_cors import CORS
from yahooquery import Ticker
from datetime import datetime
import json
import pandas as pd
import os
import threading
import time
from pathlib import Path

app = Flask(__name__)

# Only the dev frontends may call the API. A wide-open CORS policy would let any
# page the user visits drive these endpoints, including the Excel path setter.
_allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001"
    ).split(",")
    if origin.strip()
]
CORS(app, resources={r"/api/*": {"origins": _allowed_origins}})

# Your complete stock tickers dictionary
stock_name_to_scrip = {
    "ASIAN PAINTS": "ASIANPAINT.NS",
    "BRITANNIA INDUSTRIES": "BRITANNIA.NS",
    "HAPPIEST MINDS TECH": "HAPPSTMNDS.NS",
    "HCL TECHNOLOGIES": "HCLTECH.NS",
    "ITC": "ITC.NS",
    "ITC HOTELS": "ITCHOTELS.NS",
    "MAHINDRA & MAHINDRA": "M&M.NS",
    "PTC INDIA": "PTC.NS",
    "TATA CHEMICALS": "TATACHEM.NS",
    "TATA ELXSI": "TATAELXSI.NS",
    "TATA POWER": "TATAPOWER.NS",
    "TATA STEEL": "TATASTEEL.NS",
    "INFOSYS": "INFY.NS",
    "WIPRO": "WIPRO.NS",
    "ADANI PORTS": "ADANIPORTS.NS",
    "DRREDDY": "DRREDDY.NS",
    "GRASIM": "GRASIM.NS",
    "CAMS" : "CAMS.NS",
    "HAVELLS": "HAVELLS.NS",
    "INDIAN HOTELS": "INDHOTEL.NS",
    "SIEMENS": "SIEMENS.NS",
    "ENRIN": "ENRIN.NS",
    "IRCTC": "IRCTC.NS",
    "STATE BANK OF INDIA": "SBIN.NS",
    "TRENT": "TRENT.NS",
    "BAJAJ FINANCE": "BAJFINANCE.NS",
    "INDUSIND BANK": "INDUSINDBK.NS",
    "ABFRL": "ABFRL.NS",
    "ABLBL": "ABLBL.NS",
    "TEJASNET": "TEJASNET.NS",
    "HYUNDAI": "HYUNDAI.NS",
    "LIC INDIA": "LICI.NS",
    "TCS": "TCS.NS",
}

class PriceFetchError(Exception):
    """Raised when Yahoo Finance cannot be reached (rate limit, network error)."""


# /api/prices and /api/portfolio-with-live-prices request the same symbol set,
# and the dashboard calls both every 90 seconds. Without a shared cache that is
# two full 33-symbol sweeps per refresh, which Yahoo answers with 429s.
PRICE_CACHE_TTL_SECONDS = int(os.environ.get("PRICE_CACHE_TTL", "60"))
_price_cache = {}
_price_cache_lock = threading.Lock()


def fetch_price_data(symbols):
    """Fetch quote payloads from Yahoo Finance, keyed by symbol.

    Results are cached per symbol set for PRICE_CACHE_TTL_SECONDS. Raises
    PriceFetchError rather than letting the upstream exception escape, so
    callers can choose between failing and falling back to stored values.
    """
    cache_key = tuple(sorted(symbols))
    now = time.monotonic()

    with _price_cache_lock:
        entry = _price_cache.get(cache_key)
        if entry and (now - entry["fetched_at"]) < PRICE_CACHE_TTL_SECONDS:
            return entry["data"]

    try:
        data = Ticker(symbols).price
    except Exception as exc:
        raise PriceFetchError(str(exc)) from exc

    if not isinstance(data, dict):
        raise PriceFetchError(f"unexpected response from Yahoo Finance: {data!r}")

    with _price_cache_lock:
        _price_cache[cache_key] = {"data": data, "fetched_at": time.monotonic()}

    return data


def extract_quote(info):
    """Pull (price, change, change_percent) out of one Yahoo quote payload.

    Yahoo reports regularMarketChangePercent as a fraction (0.0123 == 1.23%),
    so it is scaled here to the percentage the UI expects. Any field may be
    None when the symbol is unknown or the payload is an error string.
    """
    if not isinstance(info, dict):
        return None, None, None

    price = info.get("regularMarketPrice")
    if price is None:
        price = info.get("regularMarketPreviousClose")

    change = info.get("regularMarketChange")

    change_percent = info.get("regularMarketChangePercent")
    if change_percent is not None:
        change_percent = change_percent * 100

    return price, change, change_percent


@app.route('/api/prices')
def get_prices():
    """Get current market prices for all stocks"""
    symbols = list(stock_name_to_scrip.values())

    try:
        price_data = fetch_price_data(symbols)
    except PriceFetchError as exc:
        # Yahoo rate-limits aggressively. Report it as a temporary upstream
        # failure rather than letting it surface as an opaque 500.
        return jsonify({
            "error": "Live price data is temporarily unavailable.",
            "detail": str(exc),
            "pricesLive": False,
        }), 503

    prices = {}
    for name, symbol in stock_name_to_scrip.items():
        price, change, change_percent = extract_quote(price_data.get(symbol))

        prices[name] = {
            # "N/A" is the sentinel StockCard.js checks for; a price of 0 is a
            # real price and must not collapse into it.
            "price": round(price, 2) if price is not None else "N/A",
            "change": round(change, 2) if change is not None else 0,
            "changePercent": round(change_percent, 2) if change_percent is not None else 0,
            "symbol": symbol
        }

    return jsonify({
        "prices": prices,
        "pricesLive": True,
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%B %d, %Y")
    })

@app.route('/api/stocks')
def get_stocks():
    """Get list of all tracked stocks"""
    return jsonify({
        "stocks": stock_name_to_scrip,
        "count": len(stock_name_to_scrip)
    })

@app.route('/api/detailed/<stock_name>')
def get_stock_details(stock_name):
    """Get detailed information for a specific stock"""
    if stock_name not in stock_name_to_scrip:
        return jsonify({"error": "Stock not found"}), 404
    
    symbol = stock_name_to_scrip[stock_name]
    ticker = Ticker(symbol)

    try:
        price_data = ticker.price[symbol]
        summary_data = ticker.summary_detail[symbol]
    except Exception as exc:
        app.logger.warning("detail lookup failed for %s: %s", symbol, exc)
        return jsonify({
            "error": "Live data for this stock is temporarily unavailable.",
        }), 503

    if not isinstance(price_data, dict) or not isinstance(summary_data, dict):
        return jsonify({"error": "Live data for this stock is temporarily unavailable."}), 503

    _, _, change_percent = extract_quote(price_data)

    return jsonify({
        "name": stock_name,
        "symbol": symbol,
        "currentPrice": price_data.get("regularMarketPrice"),
        "previousClose": price_data.get("regularMarketPreviousClose"),
        "change": price_data.get("regularMarketChange"),
        "changePercent": change_percent,
        "dayHigh": price_data.get("regularMarketDayHigh"),
        "dayLow": price_data.get("regularMarketDayLow"),
        "volume": price_data.get("regularMarketVolume"),
        "marketCap": summary_data.get("marketCap"),
        "pe": summary_data.get("trailingPE"),
        "timestamp": datetime.now().isoformat()
    })

# Workbook location. Prefer PORTFOLIO_EXCEL_PATH at startup; /api/set-excel-path
# can override it at runtime but only within PORTFOLIO_DATA_DIR.
ALLOWED_DATA_DIR = Path(
    os.environ.get("PORTFOLIO_DATA_DIR", Path.home())
).expanduser().resolve()
ALLOWED_WORKBOOK_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
EXCEL_FILE_PATH = os.environ.get("PORTFOLIO_EXCEL_PATH")


# Header and summary rows that appear in the sheet but are not holdings. The
# workbook ends with a TOTAL row whose QTY is a column sum, so a plain
# "quantity > 0" filter is not enough to exclude it.
NON_POSITION_ROW_LABELS = {
    'STOCK NAME', 'STOCK', 'NAME', 'TOTAL', 'TOTALS', 'GRAND TOTAL', 'SUM', 'NAN',
}


def is_position_row(stock_name):
    """True when a sheet row represents an actual holding rather than a header/total."""
    return bool(stock_name) and stock_name.strip().upper() not in NON_POSITION_ROW_LABELS


def safe_float(value, default=0):
    """Coerce a spreadsheet cell to float, tolerating thousands separators."""
    try:
        if pd.notna(value) and str(value).strip() != '':
            return float(str(value).replace(',', ''))
        return default
    except (ValueError, TypeError):
        return default


def resolve_workbook_path(raw_path):
    """Validate a caller-supplied workbook path.

    Returns the resolved Path, or raises ValueError with a message safe to show
    the caller. Symlinks are resolved before the containment check so they
    cannot be used to step outside ALLOWED_DATA_DIR.
    """
    if not raw_path or not isinstance(raw_path, str):
        raise ValueError("File path is required")

    try:
        resolved = Path(raw_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise ValueError("File does not exist")

    if not resolved.is_file():
        raise ValueError("Path is not a file")

    if resolved.suffix.lower() not in ALLOWED_WORKBOOK_SUFFIXES:
        raise ValueError("File must be an Excel workbook (.xlsx, .xls or .xlsm)")

    if ALLOWED_DATA_DIR != resolved and ALLOWED_DATA_DIR not in resolved.parents:
        raise ValueError("File is outside the permitted data directory")

    return resolved


@app.route('/api/set-excel-path', methods=['POST'])
def set_excel_path():
    """Set the Excel file path"""
    global EXCEL_FILE_PATH

    data = request.get_json(silent=True) or {}

    try:
        resolved = resolve_workbook_path(data.get('path'))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    EXCEL_FILE_PATH = str(resolved)
    return jsonify({"message": "Excel file path set successfully", "path": EXCEL_FILE_PATH})

@app.route('/api/portfolio-data')
def get_portfolio_data():
    """Extract portfolio data from Excel file"""
    if not EXCEL_FILE_PATH:
        return jsonify({"error": "Excel file path not set. Use /api/set-excel-path first."}), 400
    
    try:
        # Read Excel file
        df = pd.read_excel(EXCEL_FILE_PATH)
        
        # Convert DataFrame to list of dictionaries
        portfolio_data = []
        
        for index, row in df.iterrows():
            stock_name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            
            # Skip empty rows, headers and the trailing TOTAL row
            if not is_position_row(stock_name):
                continue
            
            # Extract data from different columns (adjust indices based on your Excel structure)
            portfolio_item = {
                "stockName": stock_name,
                "quantity": safe_float(row.iloc[1]),
                "avgBuyPrice": safe_float(row.iloc[2]),
                "currentPrice": safe_float(row.iloc[5]) if len(row) > 5 else 0,
                "investedValue": 0,
                "currentValue": 0,
                "pnl": 0,
                "pnlPercent": 0,
                "symbol": stock_name_to_scrip.get(stock_name.upper(), "")
            }
            
            # Calculate values
            portfolio_item["investedValue"] = portfolio_item["quantity"] * portfolio_item["avgBuyPrice"]
            portfolio_item["currentValue"] = portfolio_item["quantity"] * portfolio_item["currentPrice"]
            portfolio_item["pnl"] = portfolio_item["currentValue"] - portfolio_item["investedValue"]
            
            if portfolio_item["investedValue"] > 0:
                portfolio_item["pnlPercent"] = (portfolio_item["pnl"] / portfolio_item["investedValue"]) * 100
            
            portfolio_data.append(portfolio_item)
        
        return jsonify({
            "portfolioData": portfolio_data,
            "totalStocks": len(portfolio_data),
            "totalInvestedValue": sum(item["investedValue"] for item in portfolio_data),
            "totalCurrentValue": sum(item["currentValue"] for item in portfolio_data),
            "totalPnL": sum(item["pnl"] for item in portfolio_data),
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        app.logger.exception("failed to read workbook")
        return jsonify({"error": "Could not read the Excel file."}), 500

@app.route('/api/portfolio-with-live-prices')
def get_portfolio_with_live_prices():
    """Get portfolio data with live prices from Yahoo Finance"""
    if not EXCEL_FILE_PATH:
        return jsonify({"error": "Excel file path not set. Use /api/set-excel-path first."}), 400
    
    try:
        # Get portfolio data from Excel with formulas
        import openpyxl
        from openpyxl import load_workbook
        
        # Load workbook to access formulas
        wb = load_workbook(EXCEL_FILE_PATH, data_only=False)
        ws = wb.active
        
        # Also load data values
        df = pd.read_excel(EXCEL_FILE_PATH)
        
        # Get live prices. If Yahoo is unavailable we fall back to the CMP column
        # stored in the workbook, but that fact is reported in the response so the
        # UI can avoid labelling stale figures as live.
        symbols = list(stock_name_to_scrip.values())
        price_data = {}
        prices_live = True
        price_error = None

        try:
            price_data = fetch_price_data(symbols)
        except PriceFetchError as exc:
            prices_live = False
            price_error = str(exc)
            app.logger.warning("falling back to workbook prices: %s", exc)
        
        portfolio_data = []
        
        for index, row in df.iterrows():
            stock_name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            
            # Skip empty rows, headers and the trailing TOTAL row
            if not is_position_row(stock_name):
                continue
            
            # Get live price
            symbol = stock_name_to_scrip.get(stock_name.upper(), "")
            live_price = 0
            change = 0
            change_percent = 0
            
            if symbol:
                quote_price, quote_change, quote_change_percent = extract_quote(
                    price_data.get(symbol)
                )
                if quote_price is not None:
                    live_price = quote_price
                change = quote_change or 0
                change_percent = quote_change_percent or 0
            
            # Excel column mapping based on your headers:
            # A: Stock Name, B: AVG PRICE, C: INITIAL QTY, D: QTY, E: AVG INVESTED, 
            # F: CMP ON Aug 01 2025, G: NET VALUE, H: UNREALIZED PROFIT, I: DIVIDEND TILL NOW,
            # J: TOTAL PROFIT, K: PROFIT %, L: REALIZED, M: BOOKED QTY, N: REMARKS
            
            portfolio_item = {
                "stockName": stock_name,
                "symbol": symbol,
                "avgPrice": safe_float(row.iloc[1]),  # Column B: AVG PRICE
                "initialQty": safe_float(row.iloc[2]),  # Column C: INITIAL QTY
                "quantity": safe_float(row.iloc[3]),  # Column D: QTY
                "avgInvested": safe_float(row.iloc[4]),  # Column E: AVG INVESTED
                "currentPrice": round(live_price, 2) if live_price > 0 else safe_float(row.iloc[5]),  # Column F: CMP
                "netValue": safe_float(row.iloc[6]),  # Column G: NET VALUE
                "unrealizedProfit": safe_float(row.iloc[7]),  # Column H: UNREALIZED PROFIT
                "dividendTillNow": safe_float(row.iloc[8]),  # Column I: DIVIDEND TILL NOW
                "totalProfit": safe_float(row.iloc[9]),  # Column J: TOTAL PROFIT
                "profitPercent": safe_float(row.iloc[10]),  # Column K: PROFIT %
                "realized": safe_float(row.iloc[11]),  # Column L: REALIZED
                "bookedQty": safe_float(row.iloc[12]),  # Column M: BOOKED QTY
                "remarks": str(row.iloc[13]).strip() if len(row) > 13 and pd.notna(row.iloc[13]) else "",  # Column N: REMARKS
                "change": round(change, 2),
                "changePercent": round(change_percent, 2)
            }
            
            # Apply comprehensive formula calculations
            
            # 1. Calculate Avg Invested = Quantity × Avg Price
            calculated_avg_invested = round(portfolio_item["quantity"] * portfolio_item["avgPrice"], 2)
            portfolio_item["avgInvested"] = calculated_avg_invested
            portfolio_item["investedValue"] = calculated_avg_invested

            # Capital deployed over the whole life of the position. Realized profit
            # was earned on the booked shares, so the return denominator has to
            # include them; INITIAL QTY == QTY + BOOKED QTY in the workbook.
            portfolio_item["costBasis"] = round(
                portfolio_item["avgPrice"] * portfolio_item["initialQty"], 2
            )
            
            # 2. Calculate Net Value = Quantity × Current Price
            calculated_net_value = round(portfolio_item["quantity"] * portfolio_item["currentPrice"], 2)
            # Use calculated value, but keep Excel value if it exists and seems reasonable
            if portfolio_item["netValue"] > 0 and abs(portfolio_item["netValue"] - calculated_net_value) < (calculated_net_value * 0.05):  # 5% tolerance
                portfolio_item["currentValue"] = portfolio_item["netValue"]
            else:
                portfolio_item["netValue"] = calculated_net_value
                portfolio_item["currentValue"] = calculated_net_value
            
            # 3. Calculate Unrealized Profit = Net Value - Avg Invested
            calculated_unrealized_profit = round(portfolio_item["currentValue"] - portfolio_item["investedValue"], 2)
            # Use calculated value, prioritizing accuracy
            portfolio_item["unrealizedProfit"] = calculated_unrealized_profit
            portfolio_item["pnl"] = calculated_unrealized_profit
            
            # 4. Calculate Total Profit = SUM(Dividend, Unrealized Profit, Realized)
            # Formula: Total Profit = I + H + L (where exists)
            calculated_total_profit = round(
                portfolio_item["dividendTillNow"] +  # Column I
                portfolio_item["unrealizedProfit"] +  # Column H
                portfolio_item["realized"], 2          # Column L
            )
            # Use calculated value for accuracy
            portfolio_item["totalProfit"] = calculated_total_profit
            
            # 5. Calculate Profit % = (Total Profit / Avg Invested) × 100
            if portfolio_item["investedValue"] > 0:
                calculated_profit_percent = round(
                    (portfolio_item["totalProfit"] / portfolio_item["investedValue"]) * 100, 2
                )
                portfolio_item["profitPercent"] = calculated_profit_percent
                portfolio_item["pnlPercent"] = calculated_profit_percent
            else:
                portfolio_item["profitPercent"] = 0
                portfolio_item["pnlPercent"] = 0
            
            # 6. Additional calculated fields for completeness
            # Calculate unrealized profit percentage (separate from total profit %)
            if portfolio_item["investedValue"] > 0:
                portfolio_item["unrealizedProfitPercent"] = round(
                    (portfolio_item["unrealizedProfit"] / portfolio_item["investedValue"]) * 100, 2
                )
            else:
                portfolio_item["unrealizedProfitPercent"] = 0
            
            # Calculate dividend yield (if meaningful)
            if portfolio_item["investedValue"] > 0 and portfolio_item["dividendTillNow"] > 0:
                portfolio_item["dividendYield"] = round(
                    (portfolio_item["dividendTillNow"] / portfolio_item["investedValue"]) * 100, 2
                )
            else:
                portfolio_item["dividendYield"] = 0
            
            portfolio_data.append(portfolio_item)
        
        # Currently held positions drive the market-value figures.
        held_stocks = [item for item in portfolio_data if item["quantity"] > 0]

        # Profit figures must also include fully exited positions, whose realized
        # gains and dividends are still part of the portfolio's result.
        touched_stocks = [
            item for item in portfolio_data
            if item["initialQty"] > 0 or item["realized"] or item["dividendTillNow"]
        ]

        total_invested = sum(item["investedValue"] for item in held_stocks)
        total_current = sum(item["currentValue"] for item in held_stocks)
        total_unrealized = sum(item["unrealizedProfit"] for item in held_stocks)

        total_realized = sum(item["realized"] for item in touched_stocks)
        total_dividends = sum(item["dividendTillNow"] for item in touched_stocks)

        # Each component is counted exactly once. The workbook's own total row
        # (=SUM(J2:J35)+SUM(L2:L35)) adds realized twice, because every Jn is
        # already SUM(In, Hn, Ln); this does not reproduce that.
        total_profit_sum = round(total_unrealized + total_realized + total_dividends, 2)

        # Return is measured against all capital deployed, not just the capital
        # still in the market, so realized gains sit over the basis that produced
        # them rather than inflating the percentage.
        total_cost_basis = sum(item["costBasis"] for item in touched_stocks)
        total_profit_percent = (
            (total_profit_sum * 100 / total_cost_basis) if total_cost_basis > 0 else 0
        )
        unrealized_percent = (
            (total_unrealized * 100 / total_invested) if total_invested > 0 else 0
        )

        return jsonify({
            "portfolioData": portfolio_data,
            "summary": {
                "totalStocks": len(held_stocks),
                "totalInvestedValue": round(total_invested, 2),
                "totalCurrentValue": round(total_current, 2),
                "totalPnL": round(total_unrealized, 2),  # Unrealized, for the table
                "totalPnLPercent": round(unrealized_percent, 2),  # Pairs with totalPnL
                "totalRealized": round(total_realized, 2),
                "totalDividends": round(total_dividends, 2),
                "totalCostBasis": round(total_cost_basis, 2),
                "totalProfitSum": total_profit_sum,  # Unrealized + realized + dividends
                "totalProfitPercent": round(total_profit_percent, 2),
                "gainers": len([item for item in held_stocks if item["unrealizedProfit"] > 0]),
                "losers": len([item for item in held_stocks if item["unrealizedProfit"] < 0])
            },
            "pricesLive": prices_live,
            "priceError": price_error,
            "timestamp": datetime.now().isoformat(),
            "date": datetime.now().strftime("%B %d, %Y")
        })
        
    except Exception as e:
        app.logger.exception("failed to process portfolio data")
        return jsonify({"error": "Could not process the portfolio data."}), 500

@app.route('/api/historical/<symbol>')
def get_historical_data(symbol):
    """Get historical price data for a stock"""
    # Default to 30 days of data
    period = request.args.get('period', '1mo')  # Options: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
    interval = request.args.get('interval', '1d')  # Options: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo

    try:
        history = Ticker(symbol).history(period=period, interval=interval)
    except Exception as exc:
        # Same rate-limit story as the quote endpoints: upstream unavailability
        # is a 503, not an internal error, and the raw exception is not echoed.
        app.logger.warning("history lookup failed for %s: %s", symbol, exc)
        return jsonify({"error": "Historical data is temporarily unavailable."}), 503

    # yahooquery returns a plain string instead of a frame for bad symbols.
    if not isinstance(history, pd.DataFrame) or history.empty:
        return jsonify({"error": "No historical data found"}), 404

    try:
        # Reset index to get date as a column
        history = history.reset_index()

        # Convert to list of dictionaries for JSON response
        chart_data = []
        for _, row in history.iterrows():
            chart_data.append({
                "date": row['date'].strftime('%Y-%m-%d') if pd.notna(row['date']) else "",
                "open": round(float(row['open']), 2) if pd.notna(row['open']) else 0,
                "high": round(float(row['high']), 2) if pd.notna(row['high']) else 0,
                "low": round(float(row['low']), 2) if pd.notna(row['low']) else 0,
                "close": round(float(row['close']), 2) if pd.notna(row['close']) else 0,
                "volume": int(row['volume']) if pd.notna(row['volume']) else 0,
                "price": round(float(row['close']), 2) if pd.notna(row['close']) else 0  # For chart compatibility
            })
        
        return jsonify({
            "symbol": symbol,
            "period": period,
            "interval": interval,
            "data": chart_data,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as exc:
        app.logger.exception("failed to serialise history for %s", symbol)
        return jsonify({"error": "Could not read the historical data."}), 500

# ------------------------------------------------------------- ledger API v2
# The transaction-ledger endpoints that replace the Excel dependency. Mounted
# only when a database is configured, so the legacy endpoints above keep
# working during the migration.
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from portfolio.api import create_api

    _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    app.register_blueprint(create_api(_session_factory))
    app.logger.info("ledger API mounted at /api/v2")


if __name__ == "__main__":
    # The Werkzeug debugger allows arbitrary code execution, so it stays off
    # unless explicitly requested via FLASK_DEBUG=1.
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", 5000)),
            debug=debug)

