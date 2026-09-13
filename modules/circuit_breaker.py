# MarketMind Pro — Risk & Capital Preservation Engine
# Daily Loss Circuit Breaker (Tilt Protection)

"""
circuit_breaker.py — Protects capital by halting new intraday trade signals
if the maximum allowed stop-loss hits (default: 2 SLs / -2.0% risk) are reached on any single day.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional

from modules.time_utils import now_ist, today_ist_str

logger = logging.getLogger(__name__)

STATE_FILE = "data/circuit_breaker_state.json"


def _load_state() -> dict:
    today = today_ist_str()
    default_state = {
        "date": today,
        "sl_count": 0,
        "sl_hits": [],
        "active": False,
        "triggered_at": None,
        "reason": None,
    }

    if not os.path.exists(STATE_FILE):
        return default_state

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        # Reset automatically if state is from a previous calendar day
        if state.get("date") != today:
            return default_state
        return state
    except Exception as exc:
        logger.warning("Could not read circuit breaker state: %s", exc)
        return default_state


def _save_state(state: dict) -> None:
    os.makedirs("data", exist_ok=True)
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as exc:
        logger.error("Could not save circuit breaker state: %s", exc)


def is_circuit_breaker_active() -> bool:
    """Returns True if the daily circuit breaker is currently active for today."""
    state = _load_state()
    return bool(state.get("active", False))


def get_circuit_breaker_status() -> dict:
    """Returns current telemetry status of the circuit breaker for dashboard/APIs."""
    from config import MAX_DAILY_SL_HITS, MAX_DAILY_PORTFOLIO_LOSS_PCT

    state = _load_state()
    return {
        "active": bool(state.get("active", False)),
        "sl_count": int(state.get("sl_count", 0)),
        "max_allowed_sl": int(MAX_DAILY_SL_HITS),
        "max_portfolio_loss_pct": float(MAX_DAILY_PORTFOLIO_LOSS_PCT),
        "triggered_at": state.get("triggered_at"),
        "reason": state.get("reason"),
        "sl_hits": state.get("sl_hits", []),
        "date": state.get("date", today_ist_str()),
    }


def record_sl_hit(symbol: str, loss_pct: float) -> dict:
    """
    Record an SL hit. If today's SL hits reach or exceed MAX_DAILY_SL_HITS,
    activates the daily circuit breaker and fires an emergency Telegram alert.
    """
    from config import MAX_DAILY_SL_HITS, MAX_DAILY_PORTFOLIO_LOSS_PCT

    state = _load_state()
    today = today_ist_str()

    hit_record = {
        "symbol": symbol,
        "loss_pct": round(float(loss_pct), 2),
        "time": now_ist().strftime("%H:%M:%S"),
    }
    state["sl_hits"].append(hit_record)
    state["sl_count"] = len(state["sl_hits"])

    logger.warning(
        "SL Hit recorded for %s (%.2f%%). Today's SL count: %d/%d",
        symbol,
        loss_pct,
        state["sl_count"],
        MAX_DAILY_SL_HITS,
    )

    if state["sl_count"] >= MAX_DAILY_SL_HITS and not state.get("active"):
        state["active"] = True
        state["triggered_at"] = now_ist().strftime("%H:%M:%S")
        state["reason"] = (
            f"Daily loss limit reached: {state['sl_count']} stop-loss hits today "
            f"(max allowed: {MAX_DAILY_SL_HITS}). All intraday scans halted."
        )
        logger.critical("🚨 DAILY CIRCUIT BREAKER ENGAGED: %s", state["reason"])
        _save_state(state)

        # Broadcast emergency Telegram shield alert
        try:
            from modules.alerts import send_circuit_breaker_alert
            send_circuit_breaker_alert(
                sl_count=state["sl_count"],
                max_sl=MAX_DAILY_SL_HITS,
                loss_pct=sum(h["loss_pct"] for h in state["sl_hits"]),
            )
        except Exception as exc:
            logger.error("Failed to broadcast circuit breaker alert: %s", exc)
    else:
        _save_state(state)

    return state


def reset_daily_circuit_breaker() -> None:
    """Explicit daily reset (called during pre-market 08:30 IST)."""
    today = today_ist_str()
    state = {
        "date": today,
        "sl_count": 0,
        "sl_hits": [],
        "active": False,
        "triggered_at": None,
        "reason": None,
    }
    _save_state(state)
    logger.info("Daily circuit breaker reset for %s", today)
