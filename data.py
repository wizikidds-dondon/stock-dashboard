"""
台股資料擷取、快取與技術指標計算
使用 yfinance 抓取歷史 OHLCV，計算 MA5/10/20/60/120/240 及相關訊號
"""
import sqlite3
import logging
from datetime import date, datetime
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

_DB_PATH: Optional[str] = None


def set_db_path(path: str):
    global _DB_PATH
    _DB_PATH = path


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─────────────────────────────────────────────
# 資料庫初始化
# ─────────────────────────────────────────────

def init_db():
    conn = get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS stocks (
            symbol       TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            sector_key   TEXT NOT NULL DEFAULT '',
            sector_name  TEXT NOT NULL DEFAULT '',
            in_watchlist INTEGER NOT NULL DEFAULT 0,
            note         TEXT NOT NULL DEFAULT '',
            added_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS price_history (
            symbol     TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open       REAL,
            high       REAL,
            low        REAL,
            close      REAL,
            volume     INTEGER,
            PRIMARY KEY (symbol, trade_date),
            FOREIGN KEY (symbol) REFERENCES stocks(symbol) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS indicators (
            symbol            TEXT NOT NULL,
            calc_date         TEXT NOT NULL,
            ma5               REAL,
            ma10              REAL,
            ma20              REAL,
            ma60              REAL,
            ma120             REAL,
            ma240             REAL,
            price_vs_ma5      TEXT,
            price_vs_ma20     TEXT,
            price_vs_ma60     TEXT,
            golden_cross_520  INTEGER DEFAULT 0,
            death_cross_520   INTEGER DEFAULT 0,
            golden_cross_2060 INTEGER DEFAULT 0,
            death_cross_2060  INTEGER DEFAULT 0,
            vol_ratio_5d      REAL,
            bullish_align     INTEGER DEFAULT 0,
            bearish_align     INTEGER DEFAULT 0,
            PRIMARY KEY (symbol, calc_date),
            FOREIGN KEY (symbol) REFERENCES stocks(symbol) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS report_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at     TEXT NOT NULL DEFAULT (datetime('now')),
            status      TEXT NOT NULL,
            message     TEXT,
            report_text TEXT
        );

        CREATE TABLE IF NOT EXISTS refresh_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            refreshed_at    TEXT NOT NULL DEFAULT (datetime('now')),
            symbols_updated INTEGER DEFAULT 0,
            errors          TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_price_sym_date ON price_history(symbol, trade_date DESC);
        CREATE INDEX IF NOT EXISTS idx_ind_sym_date   ON indicators(symbol, calc_date DESC);
        CREATE INDEX IF NOT EXISTS idx_stocks_wl      ON stocks(in_watchlist);
        CREATE INDEX IF NOT EXISTS idx_stocks_sector  ON stocks(sector_key);
        """)
        # 欄位遷移：新增回到上升月線指標欄位（若已存在則忽略）
        for col_sql in [
            "ALTER TABLE indicators ADD COLUMN ma20_rising       INTEGER DEFAULT 0",
            "ALTER TABLE indicators ADD COLUMN touch_rising_ma20 INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(col_sql)
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────
# 種子資料：從 sectors.py 填充股票清單
# ─────────────────────────────────────────────

def seed_sectors():
    from sectors import SECTORS
    conn = get_conn()
    try:
        for sector_key, sector_data in SECTORS.items():
            sector_name = sector_data["name"]
            for symbol, name in sector_data["default_stocks"]:
                conn.execute(
                    """INSERT OR IGNORE INTO stocks
                       (symbol, name, sector_key, sector_name)
                       VALUES (?,?,?,?)""",
                    (symbol, name, sector_key, sector_name)
                )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────
# MA 計算工具
# ─────────────────────────────────────────────

def _calc_ma(prices: list, period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    return round(sum(prices[-period:]) / period, 2)


def _detect_cross(fast_today, slow_today, fast_prev, slow_prev):
    """回傳 'golden' / 'death' / None"""
    if any(v is None for v in [fast_today, slow_today, fast_prev, slow_prev]):
        return None
    if fast_prev < slow_prev and fast_today >= slow_today:
        return "golden"
    if fast_prev > slow_prev and fast_today <= slow_today:
        return "death"
    return None


# ─────────────────────────────────────────────
# 核心：批次擷取並更新資料
# ─────────────────────────────────────────────

def fetch_and_store(symbols: list[str]) -> dict[str, str]:
    """
    下載多支股票歷史資料，儲存至 price_history，
    重新計算技術指標存至 indicators。
    回傳 {symbol: 'ok' | 'error: ...'} 結果字典。
    """
    results = {}
    if not symbols:
        return results

    logger.info(f"開始擷取 {len(symbols)} 支股票資料…")

    # yfinance 批次下載（一次 HTTP 請求）
    try:
        raw = yf.download(
            tickers=" ".join(symbols),
            period="1y",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.error(f"yfinance 下載失敗: {e}")
        return {s: f"error: {e}" for s in symbols}

    conn = get_conn()
    try:
        for symbol in symbols:
            try:
                # 取出單支股票 DataFrame
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

                # 儲存 price_history
                rows = []
                for idx, row in df.iterrows():
                    trade_date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                    rows.append((
                        symbol, trade_date,
                        round(float(row["Open"]), 2) if not _is_nan(row["Open"]) else None,
                        round(float(row["High"]), 2) if not _is_nan(row["High"]) else None,
                        round(float(row["Low"]), 2) if not _is_nan(row["Low"]) else None,
                        round(float(row["Close"]), 2) if not _is_nan(row["Close"]) else None,
                        int(row["Volume"]) if not _is_nan(row["Volume"]) else None,
                    ))

                conn.executemany(
                    """INSERT OR REPLACE INTO price_history
                       (symbol, trade_date, open, high, low, close, volume)
                       VALUES (?,?,?,?,?,?,?)""",
                    rows
                )

                # 重新計算指標
                _recalc_indicators(conn, symbol)

                results[symbol] = "ok"
            except Exception as e:
                logger.warning(f"{symbol} 處理失敗: {e}")
                results[symbol] = f"error: {e}"

        conn.commit()
    finally:
        conn.close()

    ok_count = sum(1 for v in results.values() if v == "ok")
    errors = [f"{k}: {v}" for k, v in results.items() if v != "ok"]
    logger.info(f"完成擷取：{ok_count} 成功，{len(errors)} 失敗")

    # 記錄到 refresh_log
    _log_refresh(ok_count, "; ".join(errors) if errors else None)
    return results


def _is_nan(val) -> bool:
    try:
        import math
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return True


def _recalc_indicators(conn: sqlite3.Connection, symbol: str):
    """從 price_history 重新計算並寫入 indicators"""
    rows = conn.execute(
        """SELECT trade_date, close, volume FROM price_history
           WHERE symbol = ? ORDER BY trade_date ASC""",
        (symbol,)
    ).fetchall()

    if len(rows) < 2:
        return

    closes = [r["close"] for r in rows if r["close"] is not None]
    volumes = [r["volume"] for r in rows if r["volume"] is not None]

    # 只計算最近 3 天的指標（節省計算量，實際上只需最新一天）
    # 但需要前一天資料來偵測交叉，所以取最後兩行
    for i in [-1]:  # 只計算最新一天
        trade_date = rows[i]["trade_date"]
        price = closes[i] if i < 0 and len(closes) >= abs(i) else None
        if price is None:
            continue

        idx = len(closes) + i  # 正索引

        ma5   = _calc_ma(closes[:idx+1], 5)
        ma10  = _calc_ma(closes[:idx+1], 10)
        ma20  = _calc_ma(closes[:idx+1], 20)
        ma60  = _calc_ma(closes[:idx+1], 60)
        ma120 = _calc_ma(closes[:idx+1], 120)
        ma240 = _calc_ma(closes[:idx+1], 240)

        price_vs_ma5  = _vs(price, ma5)
        price_vs_ma20 = _vs(price, ma20)
        price_vs_ma60 = _vs(price, ma60)

        bullish = int(
            ma5 and ma20 and ma60 and
            price > ma5 > ma20 > ma60
        )
        bearish = int(
            ma5 and ma20 and ma60 and
            price < ma5 < ma20 < ma60
        )

        # 回到上升月線指標
        # ma20_rising: 今日MA20 > 5日前MA20（月線向上）
        ma20_5ago = _calc_ma(closes[:max(0, idx-4)], 20) if idx >= 5 else None
        ma20_rising = int(ma20 is not None and ma20_5ago is not None and ma20 > ma20_5ago)

        # touch_rising_ma20: 月線向上 + 目前站上月線 + 近5日曾觸碰月線（最低收盤 ≤ MA20×1.02）
        touch_rising_ma20 = 0
        if ma20_rising and ma20 and price_vs_ma20 == 'above':
            recent5 = closes[max(0, idx-4):idx+1]
            if min(recent5) <= ma20 * 1.02:
                touch_rising_ma20 = 1

        # 交叉偵測（需要前一天）
        gc_520 = dc_520 = gc_2060 = dc_2060 = 0
        if idx >= 1:
            prev_closes = closes[:idx]
            prev_ma5  = _calc_ma(prev_closes, 5)
            prev_ma20 = _calc_ma(prev_closes, 20)
            prev_ma60 = _calc_ma(prev_closes, 60)
            cross_520 = _detect_cross(ma5, ma20, prev_ma5, prev_ma20)
            if cross_520 == "golden":
                gc_520 = 1
            elif cross_520 == "death":
                dc_520 = 1

            cross_2060 = _detect_cross(ma20, ma60, prev_ma20, prev_ma60)
            if cross_2060 == "golden":
                gc_2060 = 1
            elif cross_2060 == "death":
                dc_2060 = 1

        # 成交量比率（與5日平均量比較）
        vol_ratio = None
        if len(volumes) >= 2 and volumes[i] is not None:
            past5 = [v for v in volumes[max(0, len(volumes)+i-5):len(volumes)+i] if v]
            if past5:
                avg5 = sum(past5) / len(past5)
                if avg5 > 0:
                    vol_ratio = round(volumes[i] / avg5, 2)

        conn.execute(
            """INSERT OR REPLACE INTO indicators
               (symbol, calc_date, ma5, ma10, ma20, ma60, ma120, ma240,
                price_vs_ma5, price_vs_ma20, price_vs_ma60,
                golden_cross_520, death_cross_520,
                golden_cross_2060, death_cross_2060,
                vol_ratio_5d, bullish_align, bearish_align,
                ma20_rising, touch_rising_ma20)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (symbol, trade_date, ma5, ma10, ma20, ma60, ma120, ma240,
             price_vs_ma5, price_vs_ma20, price_vs_ma60,
             gc_520, dc_520, gc_2060, dc_2060,
             vol_ratio, bullish, bearish,
             ma20_rising, touch_rising_ma20)
        )


def _vs(price, ma) -> Optional[str]:
    if price is None or ma is None:
        return None
    return "above" if price > ma else "below"


def _log_refresh(ok_count: int, errors: Optional[str]):
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO refresh_log (symbols_updated, errors) VALUES (?,?)",
            (ok_count, errors)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─────────────────────────────────────────────
# 單支快速報價（即時）
# ─────────────────────────────────────────────

def get_quick_quote(symbol: str) -> Optional[dict]:
    """使用 fast_info 快速取得即時報價（不更新歷史資料）"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        return {
            "symbol": symbol,
            "price": round(float(info.last_price), 2) if info.last_price else None,
            "prev_close": round(float(info.previous_close), 2) if info.previous_close else None,
            "volume": int(info.last_volume) if info.last_volume else None,
        }
    except Exception as e:
        logger.warning(f"快速報價失敗 {symbol}: {e}")
        return None


# ─────────────────────────────────────────────
# 查詢觀察名單
# ─────────────────────────────────────────────

def get_watchlist(conn: sqlite3.Connection) -> list[dict]:
    """取得觀察名單（含最新指標與漲跌幅）"""
    rows = conn.execute("""
        WITH latest_price AS (
            SELECT ph.symbol,
                   ph.close,
                   ph.volume,
                   ph.trade_date,
                   LAG(ph.close) OVER (PARTITION BY ph.symbol ORDER BY ph.trade_date) AS prev_close
            FROM price_history ph
        ),
        last_price AS (
            SELECT lp.*
            FROM latest_price lp
            INNER JOIN (
                SELECT symbol, MAX(trade_date) as max_date
                FROM price_history GROUP BY symbol
            ) m ON lp.symbol = m.symbol AND lp.trade_date = m.max_date
        )
        SELECT s.symbol, s.name, s.sector_name, s.note,
               lp.close, lp.prev_close, lp.volume, lp.trade_date,
               i.ma5, i.ma10, i.ma20, i.ma60, i.ma120, i.ma240,
               i.price_vs_ma5, i.price_vs_ma20, i.price_vs_ma60,
               i.golden_cross_520, i.death_cross_520,
               i.golden_cross_2060, i.death_cross_2060,
               i.vol_ratio_5d, i.bullish_align, i.bearish_align
        FROM stocks s
        LEFT JOIN last_price lp ON lp.symbol = s.symbol
        LEFT JOIN indicators i ON i.symbol = s.symbol AND i.calc_date = lp.trade_date
        WHERE s.in_watchlist = 1
        ORDER BY s.added_at ASC
    """).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_sector_stocks(conn: sqlite3.Connection, sector_key: str) -> list[dict]:
    """取得指定類股所有股票（含指標）"""
    rows = conn.execute("""
        WITH last_price AS (
            SELECT ph.symbol, ph.close, ph.volume, ph.trade_date,
                   LAG(ph.close) OVER (PARTITION BY ph.symbol ORDER BY ph.trade_date) AS prev_close
            FROM price_history ph
        ),
        lp AS (
            SELECT lp2.*
            FROM last_price lp2
            INNER JOIN (
                SELECT symbol, MAX(trade_date) as max_date
                FROM price_history GROUP BY symbol
            ) m ON lp2.symbol = m.symbol AND lp2.trade_date = m.max_date
        )
        SELECT s.symbol, s.name, s.sector_name, s.note,
               lp.close, lp.prev_close, lp.volume, lp.trade_date,
               i.ma5, i.ma20, i.ma60,
               i.price_vs_ma5, i.price_vs_ma20, i.price_vs_ma60,
               i.golden_cross_520, i.death_cross_520,
               i.vol_ratio_5d, i.bullish_align, i.bearish_align
        FROM stocks s
        LEFT JOIN lp ON lp.symbol = s.symbol
        LEFT JOIN indicators i ON i.symbol = s.symbol AND i.calc_date = lp.trade_date
        WHERE s.sector_key = ?
        ORDER BY s.name
    """, (sector_key,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def screen_stocks(conn: sqlite3.Connection, filters: dict) -> list[dict]:
    """篩選股票，回傳符合條件的清單"""
    where_clauses = ["1=1"]
    params = []
    joins = []

    ma_pos = filters.get("ma_position")
    if ma_pos == "above_ma5":
        where_clauses.append("i.price_vs_ma5 = 'above'")
    elif ma_pos == "above_ma20":
        where_clauses.append("i.price_vs_ma20 = 'above'")
    elif ma_pos == "above_ma60":
        where_clauses.append("i.price_vs_ma60 = 'above'")
    elif ma_pos == "below_ma20":
        where_clauses.append("i.price_vs_ma20 = 'below'")
    elif ma_pos == "below_ma60":
        where_clauses.append("i.price_vs_ma60 = 'below'")

    cross = filters.get("cross")
    if cross == "golden_520":
        where_clauses.append("i.golden_cross_520 = 1")
    elif cross == "death_520":
        where_clauses.append("i.death_cross_520 = 1")
    elif cross == "golden_2060":
        where_clauses.append("i.golden_cross_2060 = 1")
    elif cross == "death_2060":
        where_clauses.append("i.death_cross_2060 = 1")

    vol_surge = filters.get("volume_surge")
    if vol_surge == "1":
        where_clauses.append("i.vol_ratio_5d >= 1.5")
    elif vol_surge == "2":
        where_clauses.append("i.vol_ratio_5d >= 2.0")

    alignment = filters.get("alignment")
    if alignment == "bullish":
        where_clauses.append("i.bullish_align = 1")
    elif alignment == "bearish":
        where_clauses.append("i.bearish_align = 1")

    # ── 回到上升月線 ──────────────────────────
    ma_return = filters.get("ma_return")
    if ma_return == "rising_ma20":
        where_clauses.append("i.touch_rising_ma20 = 1")

    # ── 60分K MA60 位置 ──────────────────────
    ma60_60m = filters.get("ma60_60m")
    if ma60_60m == "above":
        joins.append("""
            LEFT JOIN indicators_60m i60
              ON i60.symbol = s.symbol
              AND i60.calc_dt = (SELECT MAX(calc_dt) FROM indicators_60m WHERE symbol = s.symbol)
        """)
        where_clauses.append("i60.price_vs_ma60 = 'above'")
    elif ma60_60m == "below":
        joins.append("""
            LEFT JOIN indicators_60m i60
              ON i60.symbol = s.symbol
              AND i60.calc_dt = (SELECT MAX(calc_dt) FROM indicators_60m WHERE symbol = s.symbol)
        """)
        where_clauses.append("i60.price_vs_ma60 = 'below'")

    # ── 三大法人連續買超 ──────────────────────
    inst_days = 3  # 連續 N 天
    inst_filter = filters.get("institutional")
    if inst_filter:
        # 取最近 inst_days 個有資料的交易日
        dates = conn.execute(
            "SELECT DISTINCT trade_date FROM institutional ORDER BY trade_date DESC LIMIT ?",
            (inst_days,)
        ).fetchall()
        if len(dates) >= inst_days:
            date_list = [r[0] for r in dates]
            col_map = {
                "foreign": "foreign_net",
                "trust":   "trust_net",
                "dealer":  "dealer_net",
                "total":   "total_net",
            }
            col = col_map.get(inst_filter, "total_net")
            placeholders = ",".join("?" * len(date_list))
            # 子查詢：在所有 date_list 日期都買超的股票
            sub = f"""
                (SELECT symbol FROM institutional
                 WHERE trade_date IN ({placeholders})
                   AND {col} > 0
                 GROUP BY symbol
                 HAVING COUNT(DISTINCT trade_date) >= ?)
            """
            where_clauses.append(f"s.symbol IN {sub}")
            params = date_list + [inst_days] + params

    sector = filters.get("sector")
    if sector:
        where_clauses.append("s.sector_key = ?")
        params.append(sector)

    where_sql = " AND ".join(where_clauses)
    joins_sql = "\n".join(joins)

    rows = conn.execute(f"""
        WITH last_price AS (
            SELECT ph.symbol, ph.close, ph.volume, ph.trade_date,
                   LAG(ph.close) OVER (PARTITION BY ph.symbol ORDER BY ph.trade_date) AS prev_close
            FROM price_history ph
        ),
        lp AS (
            SELECT lp2.*
            FROM last_price lp2
            INNER JOIN (
                SELECT symbol, MAX(trade_date) as max_date
                FROM price_history GROUP BY symbol
            ) m ON lp2.symbol = m.symbol AND lp2.trade_date = m.max_date
        )
        SELECT s.symbol, s.name, s.sector_name, s.note,
               lp.close, lp.prev_close, lp.volume, lp.trade_date,
               i.ma5, i.ma20, i.ma60,
               i.price_vs_ma5, i.price_vs_ma20, i.price_vs_ma60,
               i.golden_cross_520, i.death_cross_520,
               i.golden_cross_2060, i.death_cross_2060,
               i.vol_ratio_5d, i.bullish_align, i.bearish_align,
               inst_latest.foreign_net, inst_latest.trust_net,
               inst_latest.dealer_net, inst_latest.total_net,
               i60latest.ma60 AS ma60_60m,
               i60latest.price_vs_ma60 AS price_vs_ma60_60m
        FROM stocks s
        LEFT JOIN lp ON lp.symbol = s.symbol
        LEFT JOIN indicators i ON i.symbol = s.symbol AND i.calc_date = lp.trade_date
        LEFT JOIN institutional inst_latest
          ON inst_latest.symbol = s.symbol
          AND inst_latest.trade_date = (SELECT MAX(trade_date) FROM institutional WHERE symbol = s.symbol)
        LEFT JOIN indicators_60m i60latest
          ON i60latest.symbol = s.symbol
          AND i60latest.calc_dt = (SELECT MAX(calc_dt) FROM indicators_60m WHERE symbol = s.symbol)
        {joins_sql}
        WHERE {where_sql}
        ORDER BY s.sector_key, s.name
    """, params).fetchall()

    return [_row_to_dict(r) for r in rows]


def get_price_history(conn: sqlite3.Connection, symbol: str, days: int = 90) -> list[dict]:
    rows = conn.execute(
        """SELECT trade_date, open, high, low, close, volume
           FROM price_history WHERE symbol = ?
           ORDER BY trade_date DESC LIMIT ?""",
        (symbol, days)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def _row_to_dict(row) -> dict:
    d = dict(row)
    # 計算漲跌幅
    close = d.get("close")
    prev_close = d.get("prev_close")
    if close and prev_close and prev_close != 0:
        d["change_pct"] = round((close - prev_close) / prev_close * 100, 2)
        d["change"] = round(close - prev_close, 2)
    else:
        d["change_pct"] = None
        d["change"] = None
    return d
