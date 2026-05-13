"""
台股監控儀表板 - 靜態資料產生器
修正：1.股票名稱改用中文 2.三大法人自動機制
"""
import json, os, shutil, logging, requests, re
from datetime import datetime, date, timedelta
from pathlib import Path
import yfinance as yf
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
TW = pytz.timezone("Asia/Taipei")

DEFAULT_STOCKS = [
    "2330.TW","2317.TW","2454.TW","2382.TW","2308.TW",
    "2303.TW","2881.TW","2882.TW","2886.TW","2891.TW",
    "3008.TW","2412.TW","2002.TW","1301.TW","1303.TW",
]
_TW_NAMES = {}

def fetch_tw_names():
    global _TW_NAMES
    try:
        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        resp = requests.get(url, timeout=15, headers={"User-Agent":"Mozilla/5.0"})
        resp.encoding = "big5"
        for line in resp.text.split("\n"):
            if "<td>" in line:
                cells = re.findall(r"<td[^>]*>(.*?)</td>", line)
                if len(cells) >= 2:
                    code_name = cells[0].strip()
                    if "\u3000" in code_name:
                        parts = code_name.split("\u3000")
                        code = parts[0].strip()
                        name = parts[1].strip() if len(parts) > 1 else ""
                        if code and name and len(code) <= 6:
                            _TW_NAMES[code] = name
        logger.info(f"✓ 中文名稱 {len(_TW_NAMES)} 筆")
    except Exception as e:
        logger.warning(f"中文名稱失敗: {e}")

def get_stock_list():
    env = os.environ.get("STOCK_LIST","")
    return [s.strip() for s in env.split(",") if s.strip()] if env else DEFAULT_STOCKS

def get_tw_name(symbol, fallback=""):
    code = symbol.replace(".TW","").replace(".TWO","")
    return _TW_NAMES.get(code, fallback)

def fetch_stock_data(symbols):
    logger.info(f"抓取 {len(symbols)} 檔股票...")
    result = []
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            hist = ticker.history(period="60d")
            if hist.empty: continue
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
            close = float(latest["Close"])
            prev_close = float(prev["Close"])
            change = close - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            closes = hist["Close"].values.tolist()
            def ma(n): return round(sum(closes[-n:])/n,2) if len(closes)>=n else None
            history = [{"date":idx.strftime("%Y-%m-%d"),"open":round(float(r["Open"]),2),
                "high":round(float(r["High"]),2),"low":round(float(r["Low"]),2),
                "close":round(float(r["Close"]),2),"volume":int(r["Volume"])}
                for idx,r in hist.iterrows()]
            en_name = info.get("longName") or info.get("shortName") or symbol
            tw_name = get_tw_name(symbol, en_name)
            result.append({"symbol":symbol,"name":tw_name,
                "close":round(close,2),"change":round(change,2),"change_pct":round(change_pct,2),
                "volume":int(latest.get("Volume",0)),
                "ma5":ma(5),"ma10":ma(10),"ma20":ma(20),"ma60":ma(60),
                "high_52w":info.get("fiftyTwoWeekHigh"),"low_52w":info.get("fiftyTwoWeekLow"),
                "market_cap":info.get("marketCap"),"pe_ratio":info.get("trailingPE"),
                "sector":info.get("sector",""),"industry":info.get("industry",""),
                "history":history})
            logger.info(f"  ✓ {symbol} {tw_name} {close:,.2f} ({change_pct:+.2f}%)")
        except Exception as e:
            logger.error(f"  ✗ {symbol}: {e}")
    return result

def fetch_institutional():
    logger.info("抓取三大法人...")
    for days_back in range(0, 8):
        target = date.today() - timedelta(days=days_back)
        if target.weekday() >= 5: continue
        date_str = target.strftime("%Y%m%d")
        try:
            resp = requests.get("https://www.twse.com.tw/rwd/zh/fund/T86",
                params={"response":"json","date":date_str,"selectType":"ALL"}, timeout=15)
            data = resp.json()
            if data.get("stat") != "OK" or not data.get("data"):
                logger.info(f"  {date_str} 無資料，往前找...")
                continue
            fields = data.get("fields",[])
            rows = data.get("data",[])
            def pn(s):
                try: return int(str(s).replace(",","").replace("+",""))
                except: return 0
            result = []
            for r in rows:
                rec = dict(zip(fields,r))
                result.append({"symbol":rec.get("證券代號",""),
                    "name":rec.get("證券名稱",""),
                    "foreign_net":pn(rec.get("外陸資買賣超股數(不含外資自營商)",0)),
                    "trust_net":pn(rec.get("投信買賣超股數",0)),
                    "dealer_net":pn(rec.get("自營商買賣超股數",0)),
                    "total_net":pn(rec.get("三大法人買賣超股數",0))})
            logger.info(f"  ✓ 三大法人 {len(result)} 筆 ({date_str})")
            return result
        except Exception as e:
            logger.error(f"  ✗ {date_str}: {e}")
    return []

SECTORS = {
    "半導體":["2330.TW","2454.TW","2303.TW","3711.TW","2379.TW"],
    "電子零組件":["2317.TW","2382.TW","2308.TW","3034.TW","2301.TW"],
    "金融":["2881.TW","2882.TW","2886.TW","2891.TW","2884.TW"],
    "傳產/鋼鐵":["2002.TW","2006.TW","9910.TW"],
    "石化":["1301.TW","1303.TW","1326.TW"],
    "電信":["2412.TW","3045.TW","4904.TW"],
}

def fetch_sectors():
    result = {}
    for name, symbols in SECTORS.items():
        stocks = []
        for s in symbols:
            try:
                hist = yf.Ticker(s).history(period="5d")
                if len(hist) >= 2:
                    c = float(hist.iloc[-1]["Close"])
                    p = float(hist.iloc[-2]["Close"])
                    stocks.append({"symbol":s,"name":get_tw_name(s,s),"close":round(c,2),"change_pct":round((c-p)/p*100,2)})
            except: pass
        if stocks:
            result[name] = {"avg_change_pct":round(sum(x["change_pct"] for x in stocks)/len(stocks),2),"stocks":stocks}
    return result

def main():
    now_tw = datetime.now(TW)
    logger.info(f"=== 開始 {now_tw.strftime('%Y-%m-%d %H:%M')} ===")
    fetch_tw_names()
    stocks = fetch_stock_data(get_stock_list())
    institutional = fetch_institutional()
    sectors = fetch_sectors()
    output = {"updated_at":now_tw.strftime("%Y-%m-%d %H:%M"),
        "updated_timestamp":int(now_tw.timestamp()),
        "stocks":stocks,"institutional":institutional,"sectors":sectors}
    docs = Path("docs")
    docs.mkdir(exist_ok=True)
    with open(docs/"data.json","w",encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    pub = Path("public")
    if pub.exists():
        for item in pub.iterdir():
            dest = docs/item.name
            if item.is_dir():
                if dest.exists(): shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else: shutil.copy2(item, dest)
    logger.info(f"=== 完成 股票:{len(stocks)} 三大法人:{len(institutional)} 類股:{len(sectors)} ===")

if __name__ == "__main__":
    main()
