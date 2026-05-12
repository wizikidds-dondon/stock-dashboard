"""
台股監控儀表板 - 靜態資料產生器
每次執行會：
1. 從 yfinance 抓觀察名單股票資料
2. 從台灣證券交易所抓三大法人資料
3. 產生 docs/data.json
4. 複製前端靜態檔到 docs/
"""

import json
import os
import shutil
import logging
from datetime import datetime, date
from pathlib import Path

import yfinance as yf
import requests
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TW = pytz.timezone("Asia/Taipei")

DEFAULT_STOCKS = [
    "2330.TW", "2317.TW", "2454.TW", "2382.TW", "2308.TW",
    "2303.TW", "2881.TW", "2882.TW", "2886.TW", "2891.TW",
    "3008.TW", "2412.TW", "2002.TW", "1301.TW", "1303.TW",
]

def get_stock_list():
    env_list = os.environ.get("STOCK_LIST", "")
    if env_list:
        return [s.strip() for s in env_list.split(",") if s.strip()]
    return DEFAULT_STOCKS

def fetch_stock_data(symbols):
    logger.info(f"抓取 {len(symbols)} 檔股票資料...")
    result = []
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            hist = ticker.history(period="60d")
            if hist.empty:
                logger.warning(f"{symbol}: 無歷史資料，跳過")
                continue
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
            close = float(latest["Close"])
            prev_close = float(prev["Close"])
            change = close - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            closes = hist["Close"].values.tolist()
            def ma(n):
                if len(closes) >= n:
                    return round(sum(closes[-n:]) / n, 2)
                return None
            history = []
            for idx, row in hist.iterrows():
                history.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                })
            result.append({
                "symbol": symbol,
                "name": info.get("longName") or info.get("shortName") or symbol,
                "close": round(close, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "volume": int(latest.get("Volume", 0)),
                "ma5": ma(5), "ma10": ma(10), "ma20": ma(20), "ma60": ma(60),
                "high_52w": info.get("fiftyTwoWeekHigh"),
                "low_52w": info.get("fiftyTwoWeekLow"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "history": history,
            })
            logger.info(f"  ✓ {symbol} {close:,.2f} ({change_pct:+.2f}%)")
        except Exception as e:
            logger.error(f"  ✗ {symbol}: {e}")
    return result

def fetch_institutional(trade_date=None):
    logger.info("抓取三大法人資料...")
    today = trade_date or date.today().strftime("%Y%m%d")
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    params = {"response": "json", "date": today, "selectType": "ALL"}
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("stat") != "OK":
            return []
        fields = data.get("fields", [])
        rows = data.get("data", [])
        result = []
        for row in rows:
            record = dict(zip(fields, row))
            def parse_num(s):
                try: return int(str(s).replace(",", "").replace("+", ""))
                except: return 0
            result.append({
                "symbol": record.get("證券代號", ""),
                "name": record.get("證券名稱", ""),
                "foreign_net": parse_num(record.get("外陸資買賣超股數(不含外資自營商)", 0)),
                "trust_net": parse_num(record.get("投信買賣超股數", 0)),
                "dealer_net": parse_num(record.get("自營商買賣超股數", 0)),
                "total_net": parse_num(record.get("三大法人買賣超股數", 0)),
            })
        logger.info(f"  ✓ 三大法人 {len(result)} 筆")
        return result
    except Exception as e:
        logger.error(f"  ✗ {e}")
        return []

SECTORS = {
    "半導體": ["2330.TW", "2454.TW", "2303.TW", "3711.TW", "2379.TW"],
    "電子零組件": ["2317.TW", "2382.TW", "2308.TW", "3034.TW", "2301.TW"],
    "金融": ["2881.TW", "2882.TW", "2886.TW", "2891.TW", "2884.TW"],
    "傳產/鋼鐵": ["2002.TW", "2006.TW", "9910.TW"],
    "石化": ["1301.TW", "1303.TW", "1326.TW"],
    "電信": ["2412.TW", "3045.TW", "4904.TW"],
}

def fetch_sectors():
    logger.info("抓取類股資料...")
    result = {}
    for sector_name, symbols in SECTORS.items():
        sector_stocks = []
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d")
                if len(hist) >= 2:
                    close = float(hist.iloc[-1]["Close"])
                    prev = float(hist.iloc[-2]["Close"])
                    chg_pct = (close - prev) / prev * 100
                    sector_stocks.append({"symbol": symbol, "close": round(close, 2), "change_pct": round(chg_pct, 2)})
            except: pass
        if sector_stocks:
            avg_chg = sum(s["change_pct"] for s in sector_stocks) / len(sector_stocks)
            result[sector_name] = {"avg_change_pct": round(avg_chg, 2), "stocks": sector_stocks}
    return result

def main():
    now_tw = datetime.now(TW)
    logger.info(f"=== 開始產生資料 {now_tw.strftime('%Y-%m-%d %H:%M')} TW ===")
    symbols = get_stock_list()
    stocks = fetch_stock_data(symbols)
    institutional = fetch_institutional()
    sectors = fetch_sectors()
    output = {
        "updated_at": now_tw.strftime("%Y-%m-%d %H:%M"),
        "updated_timestamp": int(now_tw.timestamp()),
        "stocks": stocks, "institutional": institutional, "sectors": sectors,
    }
    docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)
    with open(docs_dir / "data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    public_dir = Path("public")
    if public_dir.exists():
        for item in public_dir.iterdir():
            dest = docs_dir / item.name
            if item.is_dir():
                if dest.exists(): shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
    logger.info(f"=== 完成 === 股票: {len(stocks)} | 三大法人: {len(institutional)} | 類股: {len(sectors)}")

if __name__ == "__main__":
    main()
    
