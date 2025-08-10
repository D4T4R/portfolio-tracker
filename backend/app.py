from flask import Flask, jsonify, request
from flask_cors import CORS
from yahooquery import Ticker
from datetime import datetime
import json
import pandas as pd
import os
from pathlib import Path

app = Flask(__name__)
CORS(app)  # Enable CORS for all domains on all routes

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

@app.route('/api/prices')
def get_prices():
    """Get current market prices for all stocks"""
    symbols = list(stock_name_to_scrip.values())
    tickers = Ticker(symbols)
    price_data = tickers.price

    prices = {}
    for name, symbol in stock_name_to_scrip.items():
        info = price_data.get(symbol)
        price = None
        change = None
        change_percent = None
        
        if info and isinstance(info, dict):
            price = info.get("regularMarketPrice")
            if price is None:
                price = info.get("regularMarketPreviousClose")
            
            change = info.get("regularMarketChange")
            change_percent = info.get("regularMarketChangePercent")
        
        prices[name] = {
            "price": round(price, 2) if price else "N/A",
            "change": round(change, 2) if change else 0,
            "changePercent": round(change_percent, 2) if change_percent else 0,
            "symbol": symbol
        }
    
    return jsonify({
        "prices": prices,
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
        
        return jsonify({
            "name": stock_name,
            "symbol": symbol,
            "currentPrice": price_data.get("regularMarketPrice"),
            "previousClose": price_data.get("regularMarketPreviousClose"),
            "change": price_data.get("regularMarketChange"),
            "changePercent": price_data.get("regularMarketChangePercent"),
            "dayHigh": price_data.get("regularMarketDayHigh"),
            "dayLow": price_data.get("regularMarketDayLow"),
            "volume": price_data.get("regularMarketVolume"),
            "marketCap": summary_data.get("marketCap"),
            "pe": summary_data.get("trailingPE"),
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Global variable to store excel file path
EXCEL_FILE_PATH = None

@app.route('/api/set-excel-path', methods=['POST'])
def set_excel_path():
    """Set the Excel file path"""
    global EXCEL_FILE_PATH
    data = request.get_json()
    file_path = data.get('path')
    
    if not file_path:
        return jsonify({"error": "File path is required"}), 400
    
    if not os.path.exists(file_path):
        return jsonify({"error": "File does not exist"}), 404
    
    EXCEL_FILE_PATH = file_path
    return jsonify({"message": "Excel file path set successfully", "path": file_path})

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
            
            # Skip empty rows or headers
            if not stock_name or stock_name.upper() in ['STOCK NAME', 'STOCK', 'NAME']:
                continue
            
            # Extract data from different columns (adjust indices based on your Excel structure)
            portfolio_item = {
                "stockName": stock_name,
                "quantity": float(row.iloc[1]) if pd.notna(row.iloc[1]) and str(row.iloc[1]).replace('.', '').replace('-', '').isdigit() else 0,
                "avgBuyPrice": float(row.iloc[2]) if pd.notna(row.iloc[2]) and str(row.iloc[2]).replace('.', '').replace('-', '').isdigit() else 0,
                "currentPrice": float(row.iloc[5]) if len(row) > 5 and pd.notna(row.iloc[5]) and str(row.iloc[5]).replace('.', '').replace('-', '').isdigit() else 0,
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
        return jsonify({"error": f"Error reading Excel file: {str(e)}"}), 500

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
        
        # Get live prices (with error handling for rate limiting)
        symbols = list(stock_name_to_scrip.values())
        price_data = {}
        
        try:
            tickers = Ticker(symbols)
            price_data = tickers.price
        except Exception as price_error:
            print(f"Warning: Could not fetch live prices - {str(price_error)}")
            # Continue without live prices - will use Excel prices
        
        portfolio_data = []
        
        for index, row in df.iterrows():
            stock_name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            
            # Skip empty rows or headers
            if not stock_name or stock_name.upper() in ['STOCK NAME', 'STOCK', 'NAME']:
                continue
            
            # Get live price
            symbol = stock_name_to_scrip.get(stock_name.upper(), "")
            live_price = 0
            change = 0
            change_percent = 0
            
            if symbol and symbol in price_data:
                info = price_data[symbol]
                if info and isinstance(info, dict):
                    live_price = info.get("regularMarketPrice") or info.get("regularMarketPreviousClose") or 0
                    change = info.get("regularMarketChange", 0)
                    change_percent = info.get("regularMarketChangePercent", 0)
            
            # Excel column mapping based on your headers:
            # A: Stock Name, B: AVG PRICE, C: INITIAL QTY, D: QTY, E: AVG INVESTED, 
            # F: CMP ON Aug 01 2025, G: NET VALUE, H: UNREALIZED PROFIT, I: DIVIDEND TILL NOW,
            # J: TOTAL PROFIT, K: PROFIT %, L: REALIZED, M: BOOKED QTY, N: REMARKS
            
            def safe_float(value, default=0):
                try:
                    if pd.notna(value) and str(value).strip() != '':
                        return float(str(value).replace(',', ''))
                    return default
                except (ValueError, TypeError):
                    return default
            
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
        
        # Calculate summary totals according to Excel formulas
        
        # Filter only stocks with quantities > 0 for accurate count
        active_stocks = [item for item in portfolio_data if item["quantity"] > 0]
        
        total_invested = sum(item["investedValue"] for item in active_stocks)
        total_current = sum(item["currentValue"] for item in active_stocks)
        total_unrealized = sum(item["unrealizedProfit"] for item in active_stocks)
        
        # Total Profit calculation as per Excel: =SUM(J2:Jn)+SUM(L2:Ln)
        # Where J = totalProfit column, L = realized column
        total_profit_from_j = sum(item["totalProfit"] for item in active_stocks)
        total_realized_from_l = sum(item["realized"] for item in active_stocks)
        total_profit_sum = round(total_profit_from_j + total_realized_from_l, 2)
        
        # Profit % calculation as per Excel: (Total Profit * 100) / Sum of Avg Invested
        total_profit_percent = (total_profit_sum * 100 / total_invested) if total_invested > 0 else 0
        
        return jsonify({
            "portfolioData": portfolio_data,
            "summary": {
                "totalStocks": len(active_stocks),  # Count only active stocks
                "totalInvestedValue": round(total_invested, 2),
                "totalCurrentValue": round(total_current, 2),
                "totalPnL": round(total_unrealized, 2),  # Unrealized profit for table display
                "totalProfitSum": total_profit_sum,  # Total profit including realized
                "totalPnLPercent": round(total_profit_percent, 2),  # Correct profit %
                "gainers": len([item for item in active_stocks if item["totalProfit"] > 0]),
                "losers": len([item for item in active_stocks if item["totalProfit"] < 0])
            },
            "timestamp": datetime.now().isoformat(),
            "date": datetime.now().strftime("%B %d, %Y")
        })
        
    except Exception as e:
        return jsonify({"error": f"Error processing portfolio data: {str(e)}"}), 500

@app.route('/api/historical/<symbol>')
def get_historical_data(symbol):
    """Get historical price data for a stock"""
    try:
        # Default to 30 days of data
        period = request.args.get('period', '1mo')  # Options: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
        interval = request.args.get('interval', '1d')  # Options: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
        
        ticker = Ticker(symbol)
        history = ticker.history(period=period, interval=interval)
        
        if history is None or history.empty:
            return jsonify({"error": "No historical data found"}), 404
        
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
        
    except Exception as e:
        return jsonify({"error": f"Error fetching historical data: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True)

