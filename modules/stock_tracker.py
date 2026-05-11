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


# ─────────────────────────────────────────────────────────────────────────────
# Market hours helper
# ─────────────────────────────────────────────────────────────────────────────

def _is_market_open() -> bool:
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def _market_time_str() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S IST")


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
    today = datetime.date.today().isoformat()
    tracking: dict[str, dict] = {}

    for pick in picks:
        sym    = pick.get("symbol", "")
        entry  = float(pick.get("entry_price") or pick.get("price") or 0)
        sl     = float(pick.get("sl_price") or entry * 0.98)
        tp     = float(pick.get("target_price") or entry * 1.065)

        tracking[sym] = {
            "symbol":       sym,
            "date":         today,
            "rank":         pick.get("rank", 0),
            "sector":       pick.get("sector", ""),
            "entry_price":  entry,
            "sl_price":     sl,
            "tp_price":     tp,
            "upside_pct":   pick.get("upside_pct", 6.5),
            "risk_reward":  pick.get("risk_reward", "N/A"),
            "score":        pick.get("score", 0),
            "rsi":          pick.get("rsi"),
            "adx":          pick.get("adx"),
            "patterns":     pick.get("patterns", []),
            "signal_reasons": pick.get("signal_reasons", ""),
            # Live tracking state
            "status":       "ACTIVE",
            "current_price": entry,
            "pnl_pct":      0.0,
            "hit_sl":       None,
            "hit_tp":       None,
            "exit_price":   None,
            "exit_time":    None,
            "init_time":    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "price_history": [],
        }

    _save(tracking)
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
            "time":  datetime.datetime.now().strftime("%H:%M"),
            "price": round(price, 2),
        })

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if price <= sl and not data.get("hit_sl"):
            data["hit_sl"]     = now_str
            data["status"]     = "SL_HIT"
            data["exit_price"] = round(price, 2)
            data["exit_time"]  = now_str
            logger.warning("SL HIT: %s at %.2f (entry %.2f, loss %.2f%%)", sym, price, entry, pnl)
            _alert_sl_hit(data)

        elif price >= tp and not data.get("hit_tp"):
            data["hit_tp"]     = now_str
            data["status"]     = "TP_HIT"
            data["exit_price"] = round(price, 2)
            data["exit_time"]  = now_str
            logger.info("TP HIT: %s at %.2f (entry %.2f, gain %.2f%%)", sym, price, entry, pnl)
            _alert_tp_hit(data)

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

    hour = datetime.datetime.now().strftime("%H:%M")
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

    _send_telegram("\n".join(lines))


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
                pnl   = round((price - entry) / entry * 100, 2)
                data["exit_price"] = round(price, 2)
                data["exit_time"]  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                data["status"]     = "EOD_CLOSED"
                data["pnl_pct"]    = pnl
                data["current_price"] = round(price, 2)
            else:
                data["status"] = "EOD_CLOSED"

    _save(tracking)
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
    time_s = datetime.datetime.now().strftime("%H:%M IST")
    msg = (
        f"🛑 <b>STOP LOSS HIT — {sym}</b>\n\n"
        f"⏰ Time: {time_s}\n"
        f"💰 Exit: ₹{price:.2f} | Entry: ₹{entry:.2f}\n"
        f"📉 Loss: {pnl:.2f}%\n\n"
        f"<i>Stock removed from active tracking</i>"
    )
    _send_telegram(msg)


def _alert_tp_hit(data: dict) -> None:
    sym    = data["symbol"]
    price  = data.get("exit_price", 0)
    entry  = data.get("entry_price", 0)
    pnl    = data.get("pnl_pct", 0)
    time_s = datetime.datetime.now().strftime("%H:%M IST")
    msg = (
        f"✅ <b>TARGET HIT — {sym}</b>\n\n"
        f"⏰ Time: {time_s}\n"
        f"💰 Exit: ₹{price:.2f} | Entry: ₹{entry:.2f}\n"
        f"📈 Gain: +{pnl:.2f}%\n\n"
        f"<i>Book profits! Stock removed from active tracking</i>"
    )
    _send_telegram(msg)


def _send_eod_report(tracking: dict) -> None:
    """Build and send the EOD report to Telegram."""
    today = datetime.date.today().strftime("%d %b %Y")
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

    _send_telegram("\n".join(lines))


def _send_telegram(text: str) -> None:
    """Send message via the alerts module."""
    try:
        from modules.alerts import _send
        _send(text)
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
        "as_of":    datetime.datetime.now().strftime("%H:%M:%S"),
    }
