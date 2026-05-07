"""
三大法人買賣超資料擷取
來源：TWSE (上市) + TPEX (上櫃)
"""
import logging
import sqlite3
import time
from datetime import date, timedelta, datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DB_PATH: Optional[str] = None

TWSE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date}&selectType=ALLBUT0999"
TPEX_URL = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=AL&t=D&d={date}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


def set_db_path(path: str):
    global _DB_PATH
    _DB_PATH = path


def get_conn() -> sqlite3.Connection:
    import data as _data
    _data.set_db_path(_DB_PATH)
    return _data.get_conn()


def init_tables():
    """建立三大法人與60m相關資料表"""
    conn = get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS institutional (
            symbol      TEXT NOT NULL,
            trade_date  TEXT NOT NULL,
            foreign_net INTEGER DEFAULT 0,
            trust_net   INTEGER DEFAULT 0,
            dealer_net  INTEGER DEFAULT 0,
            total_net   INTEGER DEFAULT 0,
            PRIMARY KEY (symbol, trade_date)
        );

        CREATE TABLE IF NOT EXISTS price_history_60m (
            symbol    TEXT NOT NULL,
            dt        TEXT NOT NULL,   -- 'YYYY-MM-DD HH:MM'
            open      REAL,
            high      REAL,
            low       REAL,
            close     REAL,
            volume    INTEGER,
            PRIMARY KEY (symbol, dt)
        );

        CREATE TABLE IF NOT EXISTS indicators_60m (
            symbol         TEXT NOT NULL,
            calc_dt        TEXT NOT NULL,
            ma60           REAL,
            price_vs_ma60  TEXT,        -- 'above' | 'below'
            PRIMARY KEY (symbol, calc_dt)
        );

        CREATE INDEX IF NOT EXISTS idx_inst_sym_date ON institutional(symbol, trade_date DESC);
        CREATE INDEX IF NOT EXISTS idx_60m_sym_dt    ON price_history_60m(symbol, dt DESC);
        CREATE INDEX IF NOT EXISTS idx_60mind_sym_dt ON indicators_60m(symbol, calc_dt DESC);
        """)
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────
# 日期工具
# ─────────────────────────────────────────────

def _to_roc_date(d: date) -> str:
    """轉換為民國年格式 YYY/MM/DD"""
    roc_year = d.year - 1911
    return f"{roc_year}/{d.month:02d}/{d.day:02d}"


def _trading_dates(n: int = 10) -> list[str]:
    """取最近 n 個可能的交易日（YYYYMMDD），排除週末"""
    result = []
    d = date.today()
    while len(result) < n:
        if d.weekday() < 5:  # 週一到週五
            result.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return result


def _parse_int(s: str) -> int:
    """解析帶逗號的數字字串，含負號"""
    if not s:
        return 0
    s = str(s).replace(",", "").strip()
    if s in ("", "--", "---", "─"):
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


# ─────────────────────────────────────────────
# TWSE 上市資料
# ─────────────────────────────────────────────

def _fetch_twse(date_str: str) -> list[dict]:
    """擷取 TWSE 三大法人單日資料，回傳 list of dict"""
    url = TWSE_URL.format(date=date_str)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        data = resp.json()
        if data.get("stat") != "OK":
            return []
        rows = []
        for row in data.get("data", []):
            if len(row) < 19:
                continue
            symbol = row[0].strip() + ".TW"
            rows.append({
                "symbol": symbol,
                "trade_date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
                "foreign_net": _parse_int(row[4]),   # 外陸資買賣超（不含外資自營商）
                "trust_net":   _parse_int(row[10]),  # 投信買賣超
                "dealer_net":  _parse_int(row[11]),  # 自營商買賣超合計
                "total_net":   _parse_int(row[18]),  # 三大法人合計
            })
        return rows
    except Exception as e:
        logger.warning(f"TWSE {date_str} 擷取失敗: {e}")
        return []


def _fetch_tpex(date_str: str) -> list[dict]:
    """擷取 TPEX 上櫃三大法人單日資料"""
    d = datetime.strptime(date_str, "%Y%m%d").date()
    roc = _to_roc_date(d)
    url = TPEX_URL.format(date=roc)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        data = resp.json()
        raw = data.get("iTotalRecords")
        # TPEX 回傳格式：aaData 陣列，每列 25 欄
        aa = data.get("aaData", [])
        rows = []
        trade_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        for row in aa:
            if len(row) < 20:
                continue
            code = str(row[0]).strip()
            if not code or len(code) < 4:
                continue
            symbol = code + ".TW"
            # TPEX 欄位：[0]代號 [1]名稱
            # 外資: [2]買 [3]賣 [4]超
            # 外資自營商: [5][6][7]
            # 投信: [8][9][10]
            # 自營商自行: [11][12][13]
            # 自營商避險: [14][15][16]
            # 自營商合計淨: [17]
            # 合計: [18] or [-1]
            try:
                foreign_net = _parse_int(row[4])
                trust_net   = _parse_int(row[10])
                dealer_net  = _parse_int(row[17]) if len(row) > 17 else 0
                total_net   = _parse_int(row[18]) if len(row) > 18 else foreign_net + trust_net + dealer_net
            except Exception:
                continue
            rows.append({
                "symbol": symbol,
                "trade_date": trade_date,
                "foreign_net": foreign_net,
                "trust_net":   trust_net,
                "dealer_net":  dealer_net,
                "total_net":   total_net,
            })
        return rows
    except Exception as e:
        logger.warning(f"TPEX {date_str} 擷取失敗: {e}")
        return []


# ─────────────────────────────────────────────
# 主要擷取函式
# ─────────────────────────────────────────────

def fetch_institutional(days: int = 5) -> int:
    """
    擷取最近 days 個交易日的三大法人資料（TWSE + TPEX）
    回傳：成功儲存的記錄筆數
    """
    dates = _trading_dates(days + 5)[:days + 2]  # 多取幾天以防假日
    conn = get_conn()
    total = 0
    try:
        for date_str in dates:
            # 檢查是否已有資料
            trade_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            existing = conn.execute(
                "SELECT COUNT(*) FROM institutional WHERE trade_date=?",
                (trade_date,)
            ).fetchone()[0]
            if existing > 0:
                continue  # 已有則跳過

            logger.info(f"擷取三大法人 {date_str}…")
            rows = _fetch_twse(date_str)
            rows += _fetch_tpex(date_str)

            if not rows:
                continue

            conn.executemany(
                """INSERT OR REPLACE INTO institutional
                   (symbol, trade_date, foreign_net, trust_net, dealer_net, total_net)
                   VALUES (:symbol, :trade_date, :foreign_net, :trust_net, :dealer_net, :total_net)""",
                rows
            )
            conn.commit()
            total += len(rows)
            logger.info(f"  {date_str}: {len(rows)} 筆")
            time.sleep(0.5)  # 避免太頻繁請求
    finally:
        conn.close()
    return total


# ─────────────────────────────────────────────
# 查詢：連續買超
# ─────────────────────────────────────────────

def get_consecutive_buyers(conn: sqlite3.Connection,
                            institution: str,
                            days: int = 3) -> set[str]:
    """
    回傳指定法人連續買超 days 天的股票代碼集合
    institution: 'foreign' | 'trust' | 'dealer' | 'total'
    """
    col_map = {
        "foreign": "foreign_net",
        "trust":   "trust_net",
        "dealer":  "dealer_net",
        "total":   "total_net",
    }
    col = col_map.get(institution, "total_net")

    # 取最近 days 個有資料的交易日
    dates = conn.execute(
        "SELECT DISTINCT trade_date FROM institutional ORDER BY trade_date DESC LIMIT ?",
        (days,)
    ).fetchall()

    if len(dates) < days:
        return set()

    date_list = [r[0] for r in dates]
    # 找在所有這些日期都買超（>0）的股票
    placeholders = ",".join("?" * len(date_list))
    rows = conn.execute(f"""
        SELECT symbol
        FROM institutional
        WHERE trade_date IN ({placeholders})
          AND {col} > 0
        GROUP BY symbol
        HAVING COUNT(DISTINCT trade_date) >= ?
    """, date_list + [days]).fetchall()

    return {r[0] for r in rows}


# ─────────────────────────────────────────────
# 60分K資料擷取與MA60計算
# ─────────────────────────────────────────────

def fetch_60m_data(symbols: list) -> dict:
    """
    下載60分K資料，計算MA60，存入DB
    回傳 {symbol: 'ok'|'error'}
    """
    import yfinance as yf
    results = {}
    if not symbols:
        return results

    logger.info(f"擷取60分K資料：{len(symbols)} 支…")
    try:
        raw = yf.download(
            tickers=" ".join(symbols),
            period="60d",
            interval="60m",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.error(f"60m 下載失敗: {e}")
        return {s: f"error: {e}" for s in symbols}

    conn = get_conn()
    try:
        for symbol in symbols:
            try:
                if len(symbols) == 1:
                    df = raw
                else:
                    if symbol not in raw.columns.get_level_values(0):
                        results[symbol] = "error: 無資料"
                        continue
                    df = raw[symbol]

                df = df.dropna(subset=["Close"])
                if df.empty:
                    results[symbol] = "error: 空資料"
                    continue

                # 儲存60m資料
                rows_60m = []
                for idx, row in df.iterrows():
                    import math
                    dt_str = idx.strftime("%Y-%m-%d %H:%M") if hasattr(idx, "strftime") else str(idx)[:16]
                    close = float(row["Close"])
                    if math.isnan(close):
                        continue
                    rows_60m.append((
                        symbol, dt_str,
                        round(float(row["Open"]), 2) if not math.isnan(float(row["Open"])) else None,
                        round(float(row["High"]), 2) if not math.isnan(float(row["High"])) else None,
                        round(float(row["Low"]),  2) if not math.isnan(float(row["Low"])) else None,
                        round(close, 2),
                        int(row["Volume"]) if not math.isnan(float(row["Volume"])) else None,
                    ))

                conn.executemany(
                    "INSERT OR REPLACE INTO price_history_60m (symbol,dt,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
                    rows_60m
                )

                # 計算MA60（60根60分K）
                all_rows = conn.execute(
                    "SELECT close FROM price_history_60m WHERE symbol=? ORDER BY dt ASC",
                    (symbol,)
                ).fetchall()
                closes = [r[0] for r in all_rows if r[0] is not None]

                if len(closes) >= 60:
                    ma60 = round(sum(closes[-60:]) / 60, 2)
                    price = closes[-1]
                    pos = "above" if price > ma60 else "below"
                    latest_dt = rows_60m[-1][1] if rows_60m else None
                    if latest_dt:
                        conn.execute(
                            "INSERT OR REPLACE INTO indicators_60m (symbol, calc_dt, ma60, price_vs_ma60) VALUES (?,?,?,?)",
                            (symbol, latest_dt, ma60, pos)
                        )

                results[symbol] = "ok"
            except Exception as e:
                logger.warning(f"{symbol} 60m 處理失敗: {e}")
                results[symbol] = f"error: {e}"

        conn.commit()
    finally:
        conn.close()

    ok_count = sum(1 for v in results.values() if v == "ok")
    logger.info(f"60m 完成：{ok_count} 成功，{len(symbols)-ok_count} 失敗")
    return results
