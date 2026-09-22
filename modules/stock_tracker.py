"""
stock_tracker.py — 24x7 tracking of the 5 selected stocks.

Responsibilities:
  - Initialize tracking when picks are selected
  - Update prices every 5 minutes during market hours (09:15-15:30)
  - Detect SL hit / TP hit immediately
  - Send Telegram alert on hit
  - Send hourly status at 10:00, 11:00, 12:00, 13:00, 14:00
  - EOD close at 15:30 with final P&L
  - Persist state to data/pick_tracking.json (survives restarts)
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

TRACKING_FILE = "data/pick_tracking.json"
_IS_MARKET_HOURS_CACHE: Optional[bool] = None


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────

def _load() -> dict:
    if os.path.exists(TRACKING_FILE):
        try:
            with open(TRACKING_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(TRACKING_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _today_str() -> str:
    try:
        from modules.time_utils import today_ist_str
        return today_ist_str()
    except Exception:
        return datetime.date.today().isoformat()


def _now_str() -> str:
    try:
        from modules.time_utils import now_ist
        return now_ist().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now_time_str() -> str:
    try:
        from modules.time_utils import now_ist

        return now_ist().strftime("%H:%M")
    except Exception:
        return datetime.datetime.now().strftime("%H:%M")


def _now_clock_str() -> str:
    try:
        from modules.time_utils import now_ist

        return now_ist().strftime("%H:%M:%S")
    except Exception:
        return datetime.datetime.now().strftime("%H:%M:%S")


def _display_date_str() -> str:
    try:
        from modules.time_utils import now_ist

        return now_ist().strftime("%d %b %Y")
    except Exception:
        return datetime.date.today().strftime("%d %b %Y")


def _refresh_daily_accuracy(date_s: str) -> dict:
    """Rebuild daily TP/SL accuracy from stored picks for one date."""
    try:
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status='tp_hit' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status='sl_hit' THEN 1 ELSE 0 END),
                    COUNT(*),
                    AVG(CASE WHEN result_return IS NOT NULL THEN result_return END)
                FROM picks
                WHERE date=?
                  AND COALESCE(session_type, 'morning_final')='morning_final'
                  AND COALESCE(is_official_morning, 1)=1
                """,
                (date_s,),
            ).fetchone()
            tp_count = int(row[0] or 0)
            sl_count = int(row[1] or 0)
            total = int(row[2] or 0)
            avg_return = round(float(row[3] or 0.0), 2)
            closed = tp_count + sl_count
            accuracy = round(tp_count / closed * 100, 2) if closed else 0.0
            conn.execute(
                """
                INSERT INTO daily_accuracy(date, tp_count, sl_count, total, accuracy, avg_return)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    tp_count=excluded.tp_count,
                    sl_count=excluded.sl_count,
                    total=excluded.total,
                    accuracy=excluded.accuracy,
                    avg_return=excluded.avg_return
                """,
                (date_s, tp_count, sl_count, total, accuracy, avg_return),
            )
            conn.commit()
            return {
                "date": date_s,
                "tp_count": tp_count,
                "sl_count": sl_count,
                "total": total,
                "accuracy": accuracy,
                "avg_return": avg_return,
            }
        finally:
            conn.close()
    except Exception as exc:
        logger.error("Daily accuracy refresh failed for %s: %s", date_s, exc)
        return {}


def _persist_pick_outcome(data: dict, status: str) -> None:
    """Persist one tracked pick outcome into the dashboard DB."""
    symbol = data.get("symbol")
    if not symbol:
        return

    date_s = data.get("date") or _today_str()
    pnl = data.get("pnl_pct")
    try:
        pnl_value = round(float(pnl), 2) if pnl is not None else None
    except Exception:
        pnl_value = None

    try:
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                """
                UPDATE picks
                SET status=?, result_return=?
                WHERE date=? AND symbol=?
                  AND (
                    (COALESCE(session_type, 'morning_final')='morning_final' AND COALESCE(is_official_morning, 1)=1)
                    OR COALESCE(session_type, '')='late_intraday_recovery'
                  )
                """,
                (status, pnl_value, date_s, symbol),
            )
            conn.commit()
        finally:
            conn.close()
        stats = _refresh_daily_accuracy(date_s)
        try:
            from modules.paper_portfolio import settle_closed_positions
            settle_closed_positions(date_s)
        except Exception as exc:
            logger.debug("Paper portfolio settle skipped for %s: %s", symbol, exc)
        line = (
            f"[TRACKER] {status.upper()} {symbol} "
            f"pnl={pnl_value if pnl_value is not None else 0:.2f}% "
            f"accuracy={stats.get('accuracy', 0):.1f}% "
            f"TP={stats.get('tp_count', 0)} SL={stats.get('sl_count', 0)}"
        )
        logger.info(line)
        print(line, flush=True)
    except Exception as exc:
        logger.error("Pick outcome persist failed for %s: %s", symbol, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Market hours helper
# ─────────────────────────────────────────────────────────────────────────────

def _is_market_open() -> bool:
    try:
        from modules.scanner import is_market_holiday, is_weekend
        from modules.time_utils import now_ist, today_ist

        today = today_ist()
        if is_weekend(today) or is_market_holiday(today):
            return False
        now = now_ist().replace(tzinfo=None)
    except Exception:
        now = datetime.datetime.now()
        if now.weekday() >= 5:
            return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def _market_time_str() -> str:
    return f"{_now_clock_str()} IST"


# ─────────────────────────────────────────────────────────────────────────────
# Price fetch (robust)
# ─────────────────────────────────────────────────────────────────────────────

def _get_live_price(sym: str) -> Optional[float]:
    """Get live/last price using modules.fetch (with jugaad fallback)."""
    try:
        from modules.fetch import fetch_price
        return fetch_price(sym)
    except Exception as e:
        logger.debug("Live price error for %s: %s", sym, e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Initialize tracking
# ─────────────────────────────────────────────────────────────────────────────

def init_tracking(picks: list[dict]) -> None:
    """
    Initialize tracking for today's picks.
    Called once after morning picks are selected.
    Overwrites any existing tracking for today.
    """
    today = _today_str()
    tracking: dict[str, dict] = {}

    for pick in picks:
        from config import RUNNER_BREAKEVEN_PCT, RUNNER_TP1_PCT, RUNNER_TP2_PCT
        sym    = pick.get("symbol", "")
        entry  = float(pick.get("entry_trigger") or pick.get("entry_price") or pick.get("price") or 0)
        sl_pct = float(pick.get("ai_sl_pct") or 1.8)
        sl     = float(pick.get("sl_price") or entry * (1 - sl_pct / 100))
        tp1_pct = float(pick.get("ai_tp1_pct") or RUNNER_TP1_PCT)
        tp2_pct = float(pick.get("ai_tp2_pct") or RUNNER_TP2_PCT)
        tp1    = float(pick.get("tp1_price") or entry * (1 + tp1_pct / 100))
        tp2    = float(pick.get("tp2_price") or pick.get("target_price") or entry * (1 + tp2_pct / 100))
        be_p   = round(entry * (1 + RUNNER_BREAKEVEN_PCT / 100), 2)

        tracking[sym] = {
            "symbol":       sym,
            "date":         today,
            "rank":         pick.get("rank", 0),
            "sector":       pick.get("sector", ""),
            "entry_price":  entry,
            "sl_price":     sl,
            "tp_price":     tp2,
            "tp1_price":    tp1,
            "tp2_price":    tp2,
            "be_price":     be_p,
            "sl_pct":       sl_pct,
            "tp1_pct":      tp1_pct,
            "tp2_pct":      tp2_pct,
            "upside_pct":   pick.get("upside_pct", tp2_pct),
            "risk_reward":  pick.get("risk_reward", "N/A"),
            "score":        pick.get("composite_score") or pick.get("score", 0),
            "air_ratio":    pick.get("air_ratio"),
            "vcp_score":    pick.get("vcp_score"),
            "delivery_score": pick.get("delivery_score") or pick.get("delivery_pct"),
            "catalyst":     pick.get("catalyst"),
            "patterns":     pick.get("patterns", []),
            "signal_reasons": pick.get("signal_reasons", ""),
            # Live tracking state
            "status":       "ACTIVE",
            "stage":        "STAGE_1",
            "current_price": entry,
            "pnl_pct":      0.0,
            "hit_sl":       None,
            "hit_be":       None,
            "hit_tp":       None,
            "hit_tp1":      None,
            "hit_tp2":      None,
            "exit_price":   None,
            "exit_time":    None,
            "init_time":    _now_str(),
            "price_history": [],
        }

    _save(tracking)
    _refresh_daily_accuracy(today)
    logger.info("Tracking initialized: %s", list(tracking.keys()))


# ─────────────────────────────────────────────────────────────────────────────
# Update (called every 5 minutes during market)
# ─────────────────────────────────────────────────────────────────────────────

def update_tracking() -> dict:
    """
    Update prices for all active tracked stocks.
    Detects SL/TP hits and fires Telegram alerts immediately.
    Returns the full tracking dict.
    """
    tracking = _load()
    if not tracking:
        return {}

    for sym, data in tracking.items():
        if data.get("status") != "ACTIVE":
            continue

        price = _get_live_price(sym)
        if price is None or price <= 0:
            logger.debug("No price for %s, skipping", sym)
            continue

        entry = data.get("entry_price", price)
        sl    = data.get("sl_price", 0)
        tp    = data.get("tp_price", 999999)
        pnl   = round((price - entry) / entry * 100, 2) if entry > 0 else 0.0

        data["current_price"] = round(price, 2)
        data["pnl_pct"]       = pnl
        data["price_history"].append({
            "time":  _now_time_str(),
            "price": round(price, 2),
        })

        now_str = _now_str()

        # Intraday RL Trailing Stop & Early Exit Manager
        try:
            from modules.rl_intraday_manager import process_tick_with_rl
            rl_eval = process_tick_with_rl(data)
            if rl_eval.get("sl_modified"):
                old_sl = data.get("sl_price")
                data["sl_price"] = rl_eval["new_sl"]
                data["rl_trailing_action"] = rl_eval["action_name"]
                logger.info("RL trailing stop updated for %s: %.2f -> %.2f (%s)", sym, old_sl, data["sl_price"], rl_eval["reason"])
            if rl_eval.get("trigger_early_exit") and not data.get("hit_tp") and not data.get("hit_sl"):
                data["hit_tp"] = now_str
                data["status"] = "TP_HIT"
                data["exit_price"] = round(price, 2)
                data["exit_time"] = now_str
                data["rl_exit_reason"] = rl_eval["reason"]
                logger.info("RL early exit executed for %s: %s", sym, rl_eval["reason"])
                _alert_tp_hit(data)
                _persist_pick_outcome(data, "tp_hit")
                continue
        except Exception as exc:
            logger.debug("RL intraday evaluation skipped for %s: %s", sym, exc)

        from config import RUNNER_BREAKEVEN_PCT, RUNNER_TP1_PCT, RUNNER_TP2_PCT, RUNNER_TRAIL_LOCKED_PCT

        # ── Stage 1: Breakeven Lock (+3.5% Gain Achieved) ────────────────────
        be_trigger = float(data.get("be_price") or entry * (1 + RUNNER_BREAKEVEN_PCT / 100))
        if price >= be_trigger and not data.get("hit_be") and not data.get("hit_tp1"):
            data["hit_be"] = now_str
            data["stage"] = "BREAKEVEN_LOCKED"
            # Shift stop loss to cover entry + buffer
            be_sl = round(entry * 1.002, 2)
            if be_sl > data.get("sl_price", 0):
                old_sl = data.get("sl_price")
                data["sl_price"] = be_sl
                logger.info("Breakeven triggered for %s: Trailed SL %.2f -> %.2f (Risk eliminated)", sym, old_sl, be_sl)
            try:
                from modules.alerts import send_breakeven_hit
                send_breakeven_hit(sym, pnl, be_sl)
            except Exception as exc:
                logger.debug("Breakeven alert error: %s", exc)

        # ── Stage 2: Target 1 Hit (+7.0%): Book 50%, lock trailing SL to +3.5% ─
        tp1 = float(data.get("tp1_price") or entry * (1 + RUNNER_TP1_PCT / 100))
        if price >= tp1 and not data.get("hit_tp1"):
            data["hit_tp1"] = now_str
            data["stage"] = "RUNNER_ACTIVE"
            locked_sl = round(entry * (1 + RUNNER_TRAIL_LOCKED_PCT / 100), 2)
            if locked_sl > data.get("sl_price", 0):
                old_sl = data.get("sl_price")
                data["sl_price"] = locked_sl
                logger.info("TP1 reached for %s: Trailed SL %.2f -> %.2f (+%.2f%% locked)", sym, old_sl, locked_sl, RUNNER_TRAIL_LOCKED_PCT)
            try:
                from modules.alerts import send_tp1_hit
                send_tp1_hit(sym, pnl, data["sl_price"])
            except Exception as exc:
                logger.debug("TP1 alert error: %s", exc)

        # ── Stop Loss Hit Check ──────────────────────────────────────────────
        if price <= sl and not data.get("hit_sl"):
            data["hit_sl"]     = now_str
            data["status"]     = "SL_HIT"
            data["exit_price"] = round(price, 2)
            data["exit_time"]  = now_str
            logger.warning("SL HIT: %s at %.2f (entry %.2f, loss %.2f%%)", sym, price, entry, pnl)
            _alert_sl_hit(data)
            _persist_pick_outcome(data, "sl_hit")

            # Check and record in Daily Loss Circuit Breaker
            try:
                from modules.circuit_breaker import record_sl_hit
                record_sl_hit(sym, pnl)
            except Exception as cb_exc:
                logger.error("Failed to record SL in circuit breaker: %s", cb_exc)

        # ── Stage 3: Target 2 Super-Runner Hit (+10.2%) ──────────────────────
        tp2 = float(data.get("tp2_price") or data.get("tp_price") or entry * (1 + RUNNER_TP2_PCT / 100))
        if price >= tp2 and not data.get("hit_tp"):
            data["hit_tp"]     = now_str
            data["hit_tp2"]    = now_str
            data["status"]     = "TP_HIT"
            data["exit_price"] = round(price, 2)
            data["exit_time"]  = now_str
            data["stage"]      = "CLOSED_PROFIT"
            logger.info("TP2 RUNNER HIT: %s at %.2f (entry %.2f, gain %.2f%%)", sym, price, entry, pnl)
            try:
                from modules.alerts import send_tp2_hit
                send_tp2_hit(sym, pnl)
            except Exception:
                _alert_tp_hit(data)
            _persist_pick_outcome(data, "tp_hit")

    _save(tracking)
    return tracking


# ─────────────────────────────────────────────────────────────────────────────
# Hourly status update
# ─────────────────────────────────────────────────────────────────────────────

def send_hourly_status() -> None:
    """Send compact status of all tracked stocks to Telegram."""
    tracking = _load()
    if not tracking:
        logger.info("No tracking data for hourly status")
        return

    hour = _now_time_str()
    lines = [
        f"📊 <b>TRACKING STATUS — {hour} IST</b>",
        "",
    ]

    total_pnl = 0.0
    active_count = 0

    for sym, data in tracking.items():
        price  = data.get("current_price") or data.get("entry_price", 0)
        entry  = data.get("entry_price", 0)
        pnl    = data.get("pnl_pct", 0.0)
        status = data.get("status", "ACTIVE")
        sl     = data.get("sl_price", 0)
        tp     = data.get("tp_price", 0)

        # Status emoji
        if status == "TP_HIT":
            emoji = "✅"
        elif status == "SL_HIT":
            emoji = "🛑"
        else:
            emoji = "🟢" if pnl >= 0 else "🔴"
            active_count += 1

        pnl_str = f"+{pnl:.2f}%" if pnl >= 0 else f"{pnl:.2f}%"
        total_pnl += pnl

        lines.append(
            f"{emoji} <b>{sym}</b> ₹{price:.2f} | {pnl_str} | {status}"
        )
        if status == "ACTIVE":
            sl_dist  = round((price - sl) / price * 100, 1) if price > 0 else 0
            tp_dist  = round((tp - price) / price * 100, 1) if price > 0 else 0
            lines.append(f"   ↓SL {sl_dist:.1f}% away | ↑TP {tp_dist:.1f}% away")

    lines.append("")
    avg_pnl = total_pnl / len(tracking) if tracking else 0
    lines.append(f"📈 Avg P&L: {'+' if avg_pnl >= 0 else ''}{avg_pnl:.2f}% | Active: {active_count}/{len(tracking)}")

    _send_telegram("\n".join(lines), event_type="tracking_hourly_status")


# ─────────────────────────────────────────────────────────────────────────────
# EOD close
# ─────────────────────────────────────────────────────────────────────────────

def close_and_report_eod() -> dict:
    """
    Close all active positions at 15:30 EOD.
    Build and send EOD report with top performers.
    Returns the final tracking dict.
    """
    tracking = _load()
    if not tracking:
        return {}

    # Close any still-active positions
    for sym, data in tracking.items():
        if data.get("status") == "ACTIVE":
            price = _get_live_price(sym)
            if price and price > 0:
                entry = data.get("entry_price", price)
                pnl   = round((price - entry) / entry * 100, 2) if entry and entry > 0 else 0.0
                data["exit_price"] = round(price, 2)
                data["exit_time"]  = _now_str()
                data["status"]     = "EOD_CLOSED"
                data["pnl_pct"]    = pnl
                data["current_price"] = round(price, 2)
                _persist_pick_outcome(data, "eod_closed")
            else:
                data["data_status"] = "unresolved_missing_exit_price"
        elif data.get("status") == "TP_HIT":
            _persist_pick_outcome(data, "tp_hit")
        elif data.get("status") == "SL_HIT":
            _persist_pick_outcome(data, "sl_hit")

    _save(tracking)
    _refresh_daily_accuracy(_today_str())
    _send_eod_report(tracking)
    return tracking


# ─────────────────────────────────────────────────────────────────────────────
# Alert helpers
# ─────────────────────────────────────────────────────────────────────────────

def _alert_sl_hit(data: dict) -> None:
    sym    = data["symbol"]
    price  = data.get("exit_price", 0)
    entry  = data.get("entry_price", 0)
    pnl    = data.get("pnl_pct", 0)
    time_s = f"{_now_time_str()} IST"
    msg = (
        f"🛑 <b>STOP LOSS HIT — {sym}</b>\n\n"
        f"⏰ Time: {time_s}\n"
        f"💰 Exit: ₹{price:.2f} | Entry: ₹{entry:.2f}\n"
        f"📉 Loss: {pnl:.2f}%\n\n"
        f"<i>Stock removed from active tracking</i>"
    )
    _send_telegram(msg, event_type="sl_hit")


def _alert_tp_hit(data: dict) -> None:
    sym    = data["symbol"]
    price  = data.get("exit_price", 0)
    entry  = data.get("entry_price", 0)
    pnl    = data.get("pnl_pct", 0)
    time_s = f"{_now_time_str()} IST"
    msg = (
        f"✅ <b>TARGET HIT — {sym}</b>\n\n"
        f"⏰ Time: {time_s}\n"
        f"💰 Exit: ₹{price:.2f} | Entry: ₹{entry:.2f}\n"
        f"📈 Gain: +{pnl:.2f}%\n\n"
        f"<i>Book profits! Stock removed from active tracking</i>"
    )
    _send_telegram(msg, event_type="tp_hit")


def _send_eod_report(tracking: dict) -> None:
    """Build and send the EOD report to Telegram."""
    today = _display_date_str()
    lines = [
        f"📋 <b>EOD REPORT — {today}</b>",
        "=" * 40,
        "",
    ]

    results = []
    for sym, data in tracking.items():
        pnl    = data.get("pnl_pct", 0.0)
        exit_p = data.get("exit_price") or data.get("current_price", 0)
        entry  = data.get("entry_price", 0)
        status = data.get("status", "")
        results.append((sym, pnl, entry, exit_p, status))

    # Sort by P&L descending
    results.sort(key=lambda x: x[1], reverse=True)

    tp_hits = sum(1 for _, _, _, _, s in results if s == "TP_HIT")
    sl_hits = sum(1 for _, _, _, _, s in results if s == "SL_HIT")
    total   = len(results)
    avg_pnl = sum(p for _, p, _, _, _ in results) / total if total else 0

    lines.append(f"🎯 Results: ✅TP={tp_hits} | 🛑SL={sl_hits} | Total={total}")
    lines.append(f"📊 Avg Return: {'+' if avg_pnl >= 0 else ''}{avg_pnl:.2f}%")
    lines.append("")

    for sym, pnl, entry, exit_p, status in results:
        if status == "TP_HIT":
            icon = "✅"
        elif status == "SL_HIT":
            icon = "🛑"
        else:
            icon = "🟡"
        pnl_str = f"+{pnl:.2f}%" if pnl >= 0 else f"{pnl:.2f}%"
        lines.append(f"{icon} <b>{sym}</b>: {pnl_str} | ₹{entry:.0f}→₹{exit_p:.0f}")

    lines.append("")
    lines.append("=" * 40)
    lines.append(f"⏰ Market closed at 15:30 IST")
    lines.append("<i>Research only. Not a trade recommendation.</i>")

    _send_telegram("\n".join(lines), event_type="tracking_eod_report")


def _send_telegram(text: str, event_type: str = "tracking_update") -> None:
    """Send message via the alerts module."""
    try:
        from modules.alerts import _send
        _send(text, review_with_grok=False, event_type=event_type)
    except Exception as e:
        logger.error("Telegram send failed: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# Status query (for dashboard)
# ─────────────────────────────────────────────────────────────────────────────

def get_tracking_status() -> dict:
    """Return current tracking state for dashboard API."""
    tracking = _load()
    active    = sum(1 for d in tracking.values() if d.get("status") == "ACTIVE")
    tp_hit    = sum(1 for d in tracking.values() if d.get("status") == "TP_HIT")
    sl_hit    = sum(1 for d in tracking.values() if d.get("status") == "SL_HIT")
    avg_pnl   = 0.0
    if tracking:
        avg_pnl = sum(d.get("pnl_pct", 0.0) for d in tracking.values()) / len(tracking)
    return {
        "total":    len(tracking),
        "active":   active,
        "tp_hit":   tp_hit,
        "sl_hit":   sl_hit,
        "avg_pnl":  round(avg_pnl, 2),
        "picks":    tracking,
        "as_of":    _now_clock_str(),
    }
