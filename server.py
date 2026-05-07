"""
台股監控儀表板 Flask 伺服器
預設 PORT=5001，可透過環境變數調整
"""
import os
import threading
import logging
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory, g, session, redirect, render_template_string
from flask_cors import CORS

import data
import telegram_bot
import institutional
from sectors import SECTORS

# ─────────────────────────────────────────────
# App 初始化
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", 5001))
DB_PATH = os.getenv("STOCK_DB_PATH", os.path.join(os.path.dirname(__file__), "stock.db"))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "")   # 若空字串則不需要登入
SECRET_KEY      = os.getenv("SECRET_KEY", "dev-secret-please-change-in-production")

app = Flask(__name__, static_folder="public", static_url_path="")
app.secret_key = SECRET_KEY
CORS(app)

data.set_db_path(DB_PATH)

# ─────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = data.get_conn()
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def ok(payload):
    return jsonify(payload)


def err(msg, code=400):
    return jsonify({"error": msg}), code


# ─────────────────────────────────────────────
# 登入驗證
# ─────────────────────────────────────────────

_LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>台股監控儀表板 — 登入</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh}
  .card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:40px;width:320px}
  .logo{font-size:22px;font-weight:700;margin-bottom:6px}
  .sub{color:#8b949e;font-size:13px;margin-bottom:28px}
  label{display:block;font-size:12px;color:#8b949e;margin-bottom:6px}
  input{width:100%;padding:10px 12px;background:#0d1117;border:1px solid #30363d;
        border-radius:6px;color:#e6edf3;font-size:14px;outline:none}
  input:focus{border-color:#58a6ff}
  button{width:100%;margin-top:16px;padding:10px;background:#238636;border:none;
         border-radius:6px;color:#fff;font-size:14px;font-weight:600;cursor:pointer}
  button:hover{background:#2ea043}
  .err{color:#f85149;font-size:12px;margin-top:10px;text-align:center}
</style>
</head>
<body>
<div class="card">
  <div class="logo">📈 台股監控儀表板</div>
  <div class="sub">請輸入存取密碼以繼續</div>
  <form method="post">
    <label>密碼</label>
    <input type="password" name="password" autofocus placeholder="••••••••">
    <button type="submit">登入</button>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
  </form>
</div>
</body>
</html>"""


@app.before_request
def check_auth():
    """所有請求先檢查登入狀態（未設定密碼則略過）"""
    if not ACCESS_PASSWORD:
        return
    if request.endpoint in ("login", "logout"):
        return
    if not session.get("authed"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "未登入"}), 401
        return redirect(f"/login?next={request.path}")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ACCESS_PASSWORD:
            session["authed"] = True
            return redirect(request.args.get("next") or "/")
        return render_template_string(_LOGIN_HTML, error="密碼錯誤，請再試一次")
    return render_template_string(_LOGIN_HTML, error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ─────────────────────────────────────────────
# 靜態頁面
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ─────────────────────────────────────────────
# 觀察名單 API
# ─────────────────────────────────────────────

@app.route("/api/watchlist", methods=["GET"])
def api_watchlist_get():
    db = get_db()
    stocks = data.get_watchlist(db)
    return ok(stocks)


@app.route("/api/watchlist", methods=["POST"])
def api_watchlist_add():
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").upper().strip()
    if not symbol:
        return err("缺少 symbol")
    # 自動加上 .TW 後綴
    if not symbol.endswith(".TW") and not symbol.startswith("^"):
        symbol += ".TW"

    name = body.get("name", "").strip()
    sector_key = body.get("sector_key", "").strip()
    note = body.get("note", "").strip()

    db = get_db()
    existing = db.execute("SELECT symbol FROM stocks WHERE symbol=?", (symbol,)).fetchone()
    if existing:
        db.execute("UPDATE stocks SET in_watchlist=1, note=? WHERE symbol=?", (note, symbol))
    else:
        # 嘗試從 yfinance 取得名稱
        if not name:
            try:
                import yfinance as yf
                info = yf.Ticker(symbol).fast_info
                name = symbol
            except Exception:
                name = symbol
        from sectors import SECTORS
        if not sector_key:
            sector_key = "other"
        sector_name = SECTORS.get(sector_key, {}).get("name", "其他")
        db.execute(
            """INSERT INTO stocks (symbol, name, sector_key, sector_name, in_watchlist, note)
               VALUES (?,?,?,?,1,?)""",
            (symbol, name or symbol, sector_key, sector_name, note)
        )
    db.commit()

    # 背景擷取資料
    threading.Thread(target=data.fetch_and_store, args=([symbol],), daemon=True).start()
    return ok({"status": "added", "symbol": symbol})


@app.route("/api/watchlist/<path:symbol>", methods=["DELETE"])
def api_watchlist_remove(symbol):
    db = get_db()
    db.execute("UPDATE stocks SET in_watchlist=0 WHERE symbol=?", (symbol,))
    db.commit()
    return ok({"status": "removed"})


@app.route("/api/watchlist/<path:symbol>/note", methods=["PUT"])
def api_watchlist_note(symbol):
    body = request.get_json(silent=True) or {}
    note = body.get("note", "")
    db = get_db()
    db.execute("UPDATE stocks SET note=? WHERE symbol=?", (note, symbol))
    db.commit()
    return ok({"status": "updated"})


# ─────────────────────────────────────────────
# 個股歷史 & 報價
# ─────────────────────────────────────────────

@app.route("/api/stock/<path:symbol>/history")
def api_stock_history(symbol):
    days = int(request.args.get("days", 90))
    db = get_db()
    history = data.get_price_history(db, symbol, days)
    return ok(history)


@app.route("/api/stock/<path:symbol>/quote")
def api_stock_quote(symbol):
    quote = data.get_quick_quote(symbol)
    if not quote:
        return err("無法取得報價", 404)
    return ok(quote)


# ─────────────────────────────────────────────
# 類股 API
# ─────────────────────────────────────────────

@app.route("/api/sectors")
def api_sectors():
    db = get_db()
    result = []
    for sector_key, sector_data in SECTORS.items():
        sector_name = sector_data["name"]
        stocks = data.get_sector_stocks(db, sector_key)
        advancing = sum(1 for s in stocks if (s.get("change_pct") or 0) > 0)
        declining = sum(1 for s in stocks if (s.get("change_pct") or 0) < 0)
        avg_chg = None
        chgs = [s["change_pct"] for s in stocks if s.get("change_pct") is not None]
        if chgs:
            avg_chg = round(sum(chgs) / len(chgs), 2)
        result.append({
            "key": sector_key,
            "name": sector_name,
            "stock_count": len(stocks),
            "avg_change_pct": avg_chg,
            "advancing": advancing,
            "declining": declining,
        })
    return ok(result)


@app.route("/api/sectors/<sector_key>")
def api_sector_stocks(sector_key):
    db = get_db()
    stocks = data.get_sector_stocks(db, sector_key)
    sector_name = SECTORS.get(sector_key, {}).get("name", sector_key)
    return ok({"sector_key": sector_key, "sector_name": sector_name, "stocks": stocks})


@app.route("/api/sectors/catalog")
def api_sectors_catalog():
    catalog = [
        {"key": k, "name": v["name"]}
        for k, v in SECTORS.items()
    ]
    return ok(catalog)


# ─────────────────────────────────────────────
# 篩選器 API
# ─────────────────────────────────────────────

@app.route("/api/screen")
def api_screen():
    filters = {
        "ma_position":   request.args.get("ma_position"),
        "cross":         request.args.get("cross"),
        "volume_surge":  request.args.get("volume_surge"),
        "alignment":     request.args.get("alignment"),
        "ma_return":     request.args.get("ma_return"),
        "ma60_60m":      request.args.get("ma60_60m"),
        "institutional": request.args.get("institutional"),
        "sector":        request.args.get("sector"),
    }
    # 移除 None 值
    filters = {k: v for k, v in filters.items() if v is not None}
    db = get_db()
    stocks = data.screen_stocks(db, filters)
    return ok(stocks)


# ─────────────────────────────────────────────
# 資料刷新 API
# ─────────────────────────────────────────────

_refresh_lock = threading.Lock()
_refresh_status = {"running": False, "last": None, "errors": []}


def _do_refresh(symbols):
    global _refresh_status
    _refresh_status["running"] = True
    try:
        results = data.fetch_and_store(symbols)
        errors = [f"{k}: {v}" for k, v in results.items() if v != "ok"]
        # 同時更新60分K
        institutional.fetch_60m_data(symbols)
        # 更新三大法人
        institutional.fetch_institutional(days=5)
        _refresh_status["last"] = datetime.now().isoformat()
        _refresh_status["errors"] = errors
    except Exception as e:
        _refresh_status["errors"] = [str(e)]
    finally:
        _refresh_status["running"] = False


@app.route("/api/refresh", methods=["POST"])
def api_refresh_all():
    if _refresh_status["running"]:
        return ok({"status": "already_running"})
    db = get_db()
    symbols = [r["symbol"] for r in db.execute("SELECT symbol FROM stocks").fetchall()]
    t = threading.Thread(target=_do_refresh, args=(symbols,), daemon=True)
    t.start()
    return ok({"status": "started", "count": len(symbols)})


@app.route("/api/refresh/<path:symbol>", methods=["POST"])
def api_refresh_symbol(symbol):
    threading.Thread(target=data.fetch_and_store, args=([symbol],), daemon=True).start()
    return ok({"status": "started", "symbol": symbol})


@app.route("/api/refresh/status")
def api_refresh_status():
    db = get_db()
    last_log = db.execute(
        "SELECT * FROM refresh_log ORDER BY refreshed_at DESC LIMIT 1"
    ).fetchone()
    return ok({
        "running": _refresh_status["running"],
        "last_run": _refresh_status.get("last"),
        "errors": _refresh_status.get("errors", []),
        "last_db_refresh": dict(last_log) if last_log else None,
    })


# ─────────────────────────────────────────────
# 三大法人 API
# ─────────────────────────────────────────────

@app.route("/api/institutional/refresh", methods=["POST"])
def api_institutional_refresh():
    def _job():
        institutional.fetch_institutional(days=5)
        db = get_db()
        symbols = [r["symbol"] for r in db.execute("SELECT symbol FROM stocks").fetchall()]
        institutional.fetch_60m_data(symbols)
    threading.Thread(target=_job, daemon=True).start()
    return ok({"status": "started"})


@app.route("/api/institutional/summary")
def api_institutional_summary():
    db = get_db()
    # 取最新日期的三大法人資料
    latest_date = db.execute(
        "SELECT MAX(trade_date) FROM institutional"
    ).fetchone()[0]
    if not latest_date:
        return ok({"date": None, "data": []})

    rows = db.execute("""
        SELECT i.symbol, s.name, s.sector_name,
               i.foreign_net, i.trust_net, i.dealer_net, i.total_net
        FROM institutional i
        JOIN stocks s ON s.symbol = i.symbol
        WHERE i.trade_date = ?
        ORDER BY i.total_net DESC
        LIMIT 50
    """, (latest_date,)).fetchall()
    return ok({"date": latest_date, "data": [dict(r) for r in rows]})


@app.route("/api/institutional/consecutive")
def api_institutional_consecutive():
    """連續買超 N 日的股票"""
    days = int(request.args.get("days", 3))
    inst = request.args.get("institution", "total")  # foreign/trust/dealer/total
    db = get_db()
    symbols = institutional.get_consecutive_buyers(db, inst, days)
    if not symbols:
        return ok([])

    placeholders = ",".join("?" * len(symbols))
    rows = db.execute(f"""
        WITH lp AS (
            SELECT ph.symbol, ph.close, ph.trade_date,
                   LAG(ph.close) OVER (PARTITION BY ph.symbol ORDER BY ph.trade_date) AS prev_close
            FROM price_history ph
        ),
        latest AS (
            SELECT lp2.* FROM lp lp2
            INNER JOIN (SELECT symbol, MAX(trade_date) d FROM price_history GROUP BY symbol) m
            ON lp2.symbol = m.symbol AND lp2.trade_date = m.d
        )
        SELECT s.symbol, s.name, s.sector_name,
               la.close, la.prev_close,
               inst.foreign_net, inst.trust_net, inst.dealer_net, inst.total_net,
               i.price_vs_ma5, i.price_vs_ma20, i.price_vs_ma60,
               i.bullish_align, i.vol_ratio_5d
        FROM stocks s
        LEFT JOIN latest la ON la.symbol = s.symbol
        LEFT JOIN indicators i ON i.symbol = s.symbol AND i.calc_date = la.trade_date
        LEFT JOIN institutional inst
          ON inst.symbol = s.symbol
          AND inst.trade_date = (SELECT MAX(trade_date) FROM institutional WHERE symbol = s.symbol)
        WHERE s.symbol IN ({placeholders})
        ORDER BY inst.total_net DESC
    """, list(symbols)).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        c, p = d.get("close"), d.get("prev_close")
        d["change_pct"] = round((c - p) / p * 100, 2) if c and p and p != 0 else None
        result.append(d)
    return ok(result)


# ─────────────────────────────────────────────
# 資金流向 API
# ─────────────────────────────────────────────

_INST_COL = {
    "foreign": '"foreign_net"',
    "trust":   "trust_net",
    "dealer":  "dealer_net",
    "total":   "total_net",
}

_LATEST_PRICE_SQL = """
    (SELECT ph2.symbol, ph2.close
     FROM price_history ph2
     INNER JOIN (
         SELECT symbol, MAX(trade_date) AS max_d
         FROM price_history GROUP BY symbol
     ) m ON ph2.symbol = m.symbol AND ph2.trade_date = m.max_d)
"""


@app.route("/api/flow/sectors")
def api_flow_sectors():
    days = min(int(request.args.get("days", 5)), 20)
    inst = request.args.get("institution", "total")
    col  = _INST_COL.get(inst, "total_net")
    db   = get_db()

    dates = db.execute(
        "SELECT DISTINCT trade_date FROM institutional ORDER BY trade_date DESC LIMIT ?",
        (days,)
    ).fetchall()
    if not dates:
        return ok({"days": days, "institution": inst, "date_range": [], "sectors": []})

    date_list = [r[0] for r in dates]
    cutoff = date_list[-1]

    rows = db.execute(f"""
        SELECT s.sector_key, s.sector_name,
               COUNT(DISTINCT i.symbol)            AS stock_count,
               SUM(i.{col})                        AS net_shares,
               SUM(i.{col} * COALESCE(ph.close,0)) AS net_value
        FROM institutional i
        JOIN stocks s ON s.symbol = i.symbol
        LEFT JOIN {_LATEST_PRICE_SQL} ph ON ph.symbol = i.symbol
        WHERE i.trade_date >= ?
        GROUP BY s.sector_key, s.sector_name
        ORDER BY net_shares DESC
    """, (cutoff,)).fetchall()

    return ok({
        "days": days,
        "institution": inst,
        "date_range": [date_list[-1], date_list[0]],
        "sectors": [dict(r) for r in rows],
    })


@app.route("/api/flow/stocks")
def api_flow_stocks():
    days  = min(int(request.args.get("days", 5)), 20)
    inst  = request.args.get("institution", "total")
    limit = min(int(request.args.get("limit", 20)), 50)
    col   = _INST_COL.get(inst, "total_net")
    db    = get_db()

    dates = db.execute(
        "SELECT DISTINCT trade_date FROM institutional ORDER BY trade_date DESC LIMIT ?",
        (days,)
    ).fetchall()
    if not dates:
        return ok({"days": days, "institution": inst, "buy": [], "sell": []})

    cutoff = dates[-1][0]

    rows = db.execute(f"""
        SELECT i.symbol, s.name, s.sector_name,
               SUM(i.{col})                        AS net_shares,
               SUM(i.{col} * COALESCE(ph.close,0)) AS net_value
        FROM institutional i
        JOIN stocks s ON s.symbol = i.symbol
        LEFT JOIN {_LATEST_PRICE_SQL} ph ON ph.symbol = i.symbol
        WHERE i.trade_date >= ?
        GROUP BY i.symbol, s.name, s.sector_name
    """, (cutoff,)).fetchall()

    all_rows = [dict(r) for r in rows]
    buy_list  = sorted(
        [r for r in all_rows if (r["net_shares"] or 0) > 0],
        key=lambda x: x["net_shares"], reverse=True
    )[:limit]
    sell_list = sorted(
        [r for r in all_rows if (r["net_shares"] or 0) < 0],
        key=lambda x: x["net_shares"]
    )[:limit]

    return ok({"days": days, "institution": inst, "buy": buy_list, "sell": sell_list})


@app.route("/api/flow/matrix")
def api_flow_matrix():
    db = get_db()
    dates = db.execute(
        "SELECT DISTINCT trade_date FROM institutional ORDER BY trade_date DESC LIMIT 5"
    ).fetchall()
    if not dates:
        return ok({"sectors": [], "data": {}, "max_abs": 0})

    cutoff = dates[-1][0]

    rows = db.execute("""
        SELECT s.sector_name,
               SUM(i."foreign_net") AS foreign_sum,
               SUM(i.trust_net)     AS trust_sum,
               SUM(i.dealer_net)    AS dealer_sum
        FROM institutional i
        JOIN stocks s ON s.symbol = i.symbol
        WHERE i.trade_date >= ?
        GROUP BY s.sector_name
        ORDER BY (ABS(SUM(i."foreign_net")) + ABS(SUM(i.trust_net)) + ABS(SUM(i.dealer_net))) DESC
    """, (cutoff,)).fetchall()

    data_map = {}
    max_abs  = 0
    sector_names = []
    for r in rows:
        name = r["sector_name"]
        sector_names.append(name)
        f = r["foreign_sum"] or 0
        t = r["trust_sum"]   or 0
        d = r["dealer_sum"]  or 0
        data_map[name] = {"foreign": f, "trust": t, "dealer": d}
        for v in (f, t, d):
            if abs(v) > max_abs:
                max_abs = abs(v)

    return ok({"sectors": sector_names, "data": data_map, "max_abs": max_abs})


# ─────────────────────────────────────────────
# 設定 API
# ─────────────────────────────────────────────

SETTING_KEYS = {"telegram_token", "telegram_chat_id", "report_enabled", "report_time"}


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    settings = {r["key"]: r["value"] for r in rows}
    # 遮蔽 token
    if "telegram_token" in settings and settings["telegram_token"]:
        t = settings["telegram_token"]
        settings["telegram_token_masked"] = t[:6] + "***" + t[-4:] if len(t) > 10 else "***"
        del settings["telegram_token"]
    return ok(settings)


@app.route("/api/settings", methods=["PUT"])
def api_settings_put():
    body = request.get_json(silent=True) or {}
    db = get_db()
    for key, value in body.items():
        if key in SETTING_KEYS:
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                (key, str(value))
            )
    db.commit()
    return ok({"status": "saved"})


# ─────────────────────────────────────────────
# Telegram API
# ─────────────────────────────────────────────

@app.route("/api/telegram/test", methods=["POST"])
def api_telegram_test():
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    settings = {r["key"]: r["value"] for r in rows}
    token = settings.get("telegram_token", "").strip()
    chat_id = settings.get("telegram_chat_id", "").strip()
    if not token or not chat_id:
        return err("Telegram 設定不完整")
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    ok_flag, msg = telegram_bot.send_message(
        token, chat_id, f"✅ 台股監控測試訊息\n時間: {now}"
    )
    if ok_flag:
        return ok({"status": "sent"})
    return err(f"發送失敗: {msg}")


@app.route("/api/telegram/report", methods=["POST"])
def api_telegram_report():
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    settings = {r["key"]: r["value"] for r in rows}
    token = settings.get("telegram_token", "").strip()
    chat_id = settings.get("telegram_chat_id", "").strip()
    if not token or not chat_id:
        return err("Telegram 設定不完整")
    report = telegram_bot.build_daily_report(db)
    ok_flag, msg = telegram_bot.send_message(token, chat_id, report)
    db.execute(
        "INSERT INTO report_log (status, message, report_text) VALUES (?,?,?)",
        ("ok" if ok_flag else "error", msg, report)
    )
    db.commit()
    if ok_flag:
        return ok({"status": "sent", "length": len(report)})
    return err(f"發送失敗: {msg}")


@app.route("/api/telegram/preview", methods=["GET"])
def api_telegram_preview():
    db = get_db()
    report = telegram_bot.build_daily_report(db)
    return ok({"report": report})


@app.route("/api/report/log")
def api_report_log():
    db = get_db()
    rows = db.execute(
        "SELECT id, sent_at, status, message FROM report_log ORDER BY sent_at DESC LIMIT 20"
    ).fetchall()
    return ok([dict(r) for r in rows])


# ─────────────────────────────────────────────
# 股票搜尋
# ─────────────────────────────────────────────

@app.route("/api/stocks/search")
def api_stocks_search():
    q = request.args.get("q", "").strip()
    if not q or len(q) < 1:
        return ok([])
    db = get_db()
    rows = db.execute(
        """SELECT symbol, name, sector_name, in_watchlist
           FROM stocks
           WHERE symbol LIKE ? OR name LIKE ?
           LIMIT 20""",
        (f"%{q}%", f"%{q}%")
    ).fetchall()
    return ok([dict(r) for r in rows])


# ─────────────────────────────────────────────
# 排程器（APScheduler）
# ─────────────────────────────────────────────

def _init_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz
        TW_TZ = pytz.timezone("Asia/Taipei")
        scheduler = BackgroundScheduler(timezone=TW_TZ)

        # 每個交易日 14:30 台灣時間更新資料
        def refresh_job():
            with app.app_context():
                conn = data.get_conn()
                try:
                    symbols = [r[0] for r in conn.execute("SELECT symbol FROM stocks").fetchall()]
                finally:
                    conn.close()
                if symbols:
                    data.fetch_and_store(symbols)
                    logger.info(f"排程刷新完成，共 {len(symbols)} 支")

        # 每個交易日 15:00 更新三大法人（收盤後約1小時TWSE才更新）
        def institutional_job():
            institutional.set_db_path(DB_PATH)
            count = institutional.fetch_institutional(days=3)
            conn2 = data.get_conn()
            try:
                symbols = [r[0] for r in conn2.execute("SELECT symbol FROM stocks").fetchall()]
            finally:
                conn2.close()
            institutional.fetch_60m_data(symbols)
            logger.info(f"三大法人更新完成 {count} 筆")

        scheduler.add_job(
            institutional_job,
            CronTrigger(day_of_week="mon-fri", hour=15, minute=0, timezone=TW_TZ),
            id="institutional_refresh",
            replace_existing=True,
            misfire_grace_time=600,
        )

        # 每個交易日 14:35 台灣時間發送日報
        def report_job():
            with app.app_context():
                ok_flag, msg = telegram_bot.send_daily_report(DB_PATH)
                logger.info(f"排程日報: {'成功' if ok_flag else '失敗'} — {msg}")

        scheduler.add_job(
            refresh_job,
            CronTrigger(day_of_week="mon-fri", hour=14, minute=30, timezone=TW_TZ),
            id="market_refresh",
            replace_existing=True,
            misfire_grace_time=600,
        )
        scheduler.add_job(
            report_job,
            CronTrigger(day_of_week="mon-fri", hour=14, minute=35, timezone=TW_TZ),
            id="telegram_report",
            replace_existing=True,
            misfire_grace_time=600,
        )
        scheduler.start()
        logger.info("排程器啟動：每個交易日 14:30 更新資料，14:35 發送日報")
        return scheduler
    except ImportError:
        logger.warning("APScheduler 未安裝，排程功能停用")
        return None


# ─────────────────────────────────────────────
# 啟動
# ─────────────────────────────────────────────

def _startup():
    """初始化 DB 並啟動排程（gunicorn 與直接執行都會呼叫）"""
    data.init_db()
    data.seed_sectors()
    institutional.set_db_path(DB_PATH)
    institutional.init_tables()
    logger.info(f"DB 初始化完成: {DB_PATH}")
    _init_scheduler()

    def _initial_refresh():
        import time
        time.sleep(3)
        conn = data.get_conn()
        try:
            symbols = [r[0] for r in conn.execute("SELECT symbol FROM stocks").fetchall()]
        finally:
            conn.close()
        if symbols:
            logger.info(f"啟動時背景擷取 {len(symbols)} 支股票資料…")
            data.fetch_and_store(symbols)

    threading.Thread(target=_initial_refresh, daemon=True).start()


# 讓 gunicorn import 時也能正確初始化
_startup()

if __name__ == "__main__":
    logger.info(f"台股監控儀表板啟動，Port: {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
