"""
Telegram 日報產生與發送
直接使用 Telegram Bot API（requests），不依賴第三方 bot 函式庫
"""
import logging
import sqlite3
from datetime import datetime

import requests

import data

logger = logging.getLogger(__name__)


def get_settings(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def send_message(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """發送 HTML 格式訊息。回傳 (成功, 訊息)"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=15)
        if resp.ok:
            return True, "OK"
        return False, resp.json().get("description", "未知錯誤")
    except Exception as e:
        return False, str(e)


def _ma_arrow(pos) -> str:
    if pos == "above":
        return "▲"
    if pos == "below":
        return "▼"
    return "─"


def _pct_str(pct) -> str:
    if pct is None:
        return "  N/A "
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.2f}%"


def _signals(row: dict) -> list[str]:
    sigs = []
    if row.get("bullish_align"):
        sigs.append("多頭排列")
    if row.get("bearish_align"):
        sigs.append("空頭排列")
    if row.get("golden_cross_520"):
        sigs.append("5/20黃金交叉")
    if row.get("death_cross_520"):
        sigs.append("5/20死亡交叉")
    if row.get("golden_cross_2060"):
        sigs.append("20/60黃金交叉")
    if row.get("death_cross_2060"):
        sigs.append("20/60死亡交叉")
    vol = row.get("vol_ratio_5d")
    if vol and vol >= 2.0:
        sigs.append(f"爆量{vol:.1f}x")
    elif vol and vol >= 1.5:
        sigs.append(f"放量{vol:.1f}x")
    return sigs


def build_daily_report(db_conn: sqlite3.Connection) -> str:
    today = datetime.now().strftime("%Y/%m/%d")
    lines = [f"📊 <b>台股日報 — {today}</b>\n"]

    # 大盤
    try:
        import yfinance as yf
        twii = yf.Ticker("^TWII")
        h = twii.history(period="2d")
        if not h.empty and len(h) >= 1:
            latest = h.iloc[-1]
            prev_close = h.iloc[-2]["Close"] if len(h) >= 2 else latest["Close"]
            close = latest["Close"]
            chg = (close - prev_close) / prev_close * 100 if prev_close else 0
            sign = "▲" if chg >= 0 else "▼"
            vol_b = latest["Volume"] / 1e8  # 億
            lines.append(
                f"<b>大盤概況</b>\n"
                f"加權指數: <b>{close:,.0f}</b> {sign} {abs(chg):.2f}%\n"
                f"成交量: 約 {vol_b:.0f} 億\n"
            )
    except Exception as e:
        logger.warning(f"大盤資料擷取失敗: {e}")
        lines.append("<b>大盤概況</b>\n（資料暫時無法取得）\n")

    # 觀察名單
    watchlist = data.get_watchlist(db_conn)
    if watchlist:
        lines.append("<b>📋 觀察名單</b>")
        lines.append("<code>")
        lines.append(f"{'股票':<8} {'現價':>7} {'漲跌':>7}  均線位置")
        lines.append("─" * 38)
        for s in watchlist:
            name = s.get("name", "")[:5]
            price = f"{s['close']:.1f}" if s.get("close") else "  N/A"
            pct = _pct_str(s.get("change_pct"))
            ma_pos = (
                f"5{_ma_arrow(s.get('price_vs_ma5'))}"
                f"20{_ma_arrow(s.get('price_vs_ma20'))}"
                f"60{_ma_arrow(s.get('price_vs_ma60'))}"
            )
            lines.append(f"{name:<8} {price:>7} {pct:>7}  {ma_pos}")
        lines.append("</code>\n")
    else:
        lines.append("（觀察名單為空）\n")

    # 技術訊號彙整
    alert_lines = []
    for s in watchlist:
        sigs = _signals(s)
        if sigs:
            sym = s.get("symbol", "").replace(".TW", "")
            name = s.get("name", "")
            alert_lines.append(f"• {name}（{sym}）: {', '.join(sigs)}")

    if alert_lines:
        lines.append("<b>🔔 今日訊號</b>")
        lines.extend(alert_lines)
        lines.append("")

    # 多頭排列股
    bullish = [s for s in watchlist if s.get("bullish_align")]
    if bullish:
        names = "、".join([s["name"] for s in bullish])
        lines.append(f"<b>💪 多頭排列股</b>\n{names}\n")

    # 爆量股
    vol_stocks = [(s, s["vol_ratio_5d"]) for s in watchlist if (s.get("vol_ratio_5d") or 0) >= 1.5]
    vol_stocks.sort(key=lambda x: x[1], reverse=True)
    if vol_stocks:
        lines.append("<b>📈 量能異常 (≥1.5x 5日均量)</b>")
        for s, ratio in vol_stocks:
            sym = s["symbol"].replace(".TW", "")
            lines.append(f"• {s['name']}（{sym}）: {ratio:.1f} 倍均量")
        lines.append("")

    now_str = datetime.now().strftime("%H:%M")
    lines.append(f"<i>更新時間: {now_str} | 資料來源: Yahoo Finance</i>")

    report = "\n".join(lines)

    # Telegram 訊息上限 4096 字元
    if len(report) > 4000:
        report = report[:4000] + "\n<i>（訊息已截斷）</i>"

    return report


def send_daily_report(db_path: str) -> tuple[bool, str]:
    """主入口：從 DB 讀取設定，產生並發送報告"""
    import data as _data
    _data.set_db_path(db_path)
    conn = _data.get_conn()
    try:
        settings = get_settings(conn)
        token = settings.get("telegram_token", "").strip()
        chat_id = settings.get("telegram_chat_id", "").strip()

        if not token or not chat_id:
            return False, "Telegram 設定不完整"

        report = build_daily_report(conn)
        ok, msg = send_message(token, chat_id, report)

        conn.execute(
            "INSERT INTO report_log (status, message, report_text) VALUES (?,?,?)",
            ("ok" if ok else "error", msg, report)
        )
        conn.commit()
        return ok, msg
    finally:
        conn.close()
