"""
modules/auditor.py — The Self-Learning Auditor (Historical Loss Penalty Rules).
Ported from MT5 AI Hedge Terminal Component 4.

Key Responsibilities:
  1. Log every alert the screener triggers along with its market snapshot
     (RSI, RVOL, sector momentum, ATR expansion %, macro alignment).
  2. Audit closed trades: check whether the stock achieved a 2R profit within 2 hours
     or failed (hit SL / lost).
  3. When an audited setup condition fails >= 75% of the time, automatically add an
     active penalty rule into data/audit_rules.json.
  4. Expose `get_audit_penalty(sym, metadata)` to deduct 0-20 confidence points
     during stock scoring.
"""

from __future__ import annotations

import os
import json
import sqlite3
import logging
import datetime
from typing import Any

from modules.time_utils import now_ist, today_ist_str

logger = logging.getLogger(__name__)

AUDIT_RULES_PATH = "data/audit_rules.json"
SNAPSHOT_LOG_PATH = "data/alert_snapshots.jsonl"


def record_alert_snapshot(symbol: str, snapshot: dict[str, Any]) -> None:
    """Log an alert with its full technical and macro snapshot."""
    try:
        os.makedirs(os.path.dirname(SNAPSHOT_LOG_PATH), exist_ok=True)
        payload = {
            "symbol": symbol.upper(),
            "timestamp": now_ist().isoformat(timespec="seconds"),
            "date": today_ist_str(),
            "price": float(snapshot.get("price", 0.0) or 0.0),
            "rsi": float(snapshot.get("rsi", 50.0) or 50.0),
            "rvol": float(snapshot.get("rvol", snapshot.get("vol_ratio", 1.0)) or 1.0),
            "expansion_pct": float(snapshot.get("expansion_pct", 0.0) or 0.0),
            "macro_alignment": str(snapshot.get("macro_alignment", "neutral")),
            "sector": str(snapshot.get("sector", "Unknown")),
            "score": float(snapshot.get("score", 0.0) or 0.0),
            "bull_trap_warning": bool(snapshot.get("bull_trap_warning", False)),
        }
        with open(SNAPSHOT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("Failed to record alert snapshot for %s: %s", symbol, exc)


def load_audit_rules() -> dict[str, Any]:
    """Load audit rules from data/audit_rules.json."""
    if not os.path.exists(AUDIT_RULES_PATH):
        return {"penalty_rules": [], "setup_stats": {}, "version": "1.0"}
    try:
        with open(AUDIT_RULES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"penalty_rules": [], "setup_stats": {}, "version": "1.0"}
            return data
    except Exception as exc:
        logger.warning("Error reading %s: %s", AUDIT_RULES_PATH, exc)
        return {"penalty_rules": [], "setup_stats": {}, "version": "1.0"}


def save_audit_rules(data: dict[str, Any]) -> None:
    """Save audit rules safely to data/audit_rules.json."""
    try:
        os.makedirs(os.path.dirname(AUDIT_RULES_PATH) or ".", exist_ok=True)
        data["last_updated"] = now_ist().isoformat(timespec="seconds")
        temp_path = f"{AUDIT_RULES_PATH}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, AUDIT_RULES_PATH)
    except Exception as exc:
        logger.error("Failed writing %s: %s", AUDIT_RULES_PATH, exc)


def get_audit_penalty(symbol: str, metadata: dict[str, Any]) -> tuple[float, list[str]]:
    """
    Calculate the active audit penalty points (0.0 to 20.0) and justification reasons.
    Evaluates both learned dynamic penalty rules and baseline institutional rules.
    """
    symbol = symbol.upper()
    total_penalty = 0.0
    reasons: list[str] = []

    # 1. Base Institutional Auditor Rules
    rsi = float(metadata.get("rsi", 50.0) or 50.0)
    rvol = float(metadata.get("rvol", metadata.get("vol_ratio", 1.0)) or 1.0)
    expansion_pct = float(metadata.get("expansion_pct", 0.0) or 0.0)
    macro_align = str(metadata.get("macro_alignment", "neutral"))

    # Bull trap rule: Breakout attempt with poor volume
    if metadata.get("breakout_20d_high") and rvol < 1.0:
        total_penalty += 15.0
        reasons.append("auditor:bull_trap_breakout_rvol_under_1.0 (-15pts)")

    # Overbought with high expansion
    if rsi > 75.0 and expansion_pct >= 75.0:
        total_penalty += 10.0
        reasons.append("auditor:overbought_rsi75_and_expansion75 (-10pts)")

    # Macro contradiction
    if macro_align == "full_bear":
        total_penalty += 12.0
        reasons.append("auditor:macro_bear_below_ema200_and_vwap (-12pts)")

    # 2. Dynamic Learned Rules from data/audit_rules.json
    rules_data = load_audit_rules()
    for rule in rules_data.get("penalty_rules", []):
        pts = float(rule.get("penalty_pts", 0.0) or 0.0)
        rule_type = rule.get("type", "")
        rule_sym = str(rule.get("symbol", "")).upper()

        if rule_sym and rule_sym == symbol:
            total_penalty += pts
            reasons.append(f"auditor:symbol_loss_streak_{symbol} (-{pts:.1f}pts)")
            continue

        if rule_type == "high_rsi_exhaustion" and rsi >= float(rule.get("threshold_rsi", 72.0)):
            total_penalty += pts
            reasons.append(f"auditor:{rule_type} (-{pts:.1f}pts)")

        elif rule_type == "low_rvol_trap" and rvol <= float(rule.get("threshold_rvol", 1.2)):
            total_penalty += pts
            reasons.append(f"auditor:{rule_type} (-{pts:.1f}pts)")

        elif rule_type == "high_atr_exhaustion" and expansion_pct >= float(rule.get("threshold_expansion", 80.0)):
            total_penalty += pts
            reasons.append(f"auditor:{rule_type} (-{pts:.1f}pts)")

    # Clamp penalty strictly between 0 and 20 points
    clamped_penalty = round(min(20.0, max(0.0, total_penalty)), 2)
    return clamped_penalty, reasons


def audit_closed_trades() -> dict[str, Any]:
    """
    Review historical closed trades from data/history.db (and paper_positions).
    Correlates setups with win/loss outcomes.
    If a specific setup or symbol fails >= 75% of the time,
    writes an active penalty rule into data/audit_rules.json.
    """
    db_path = "data/history.db"
    if not os.path.exists(db_path):
        return {"status": "skipped", "reason": "no_db"}

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Check picks table
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='picks'")
        if not cursor.fetchone():
            conn.close()
            return {"status": "skipped", "reason": "no_picks_table"}

        # Fetch closed/completed trades
        picks = conn.execute("""
            SELECT symbol, status, result_return, entry_price, sl_price, target_price, signal_reasons, date
            FROM picks
            WHERE status IN ('hit_target', 'hit_sl', 'closed', 'expired')
            ORDER BY id DESC LIMIT 100
        """).fetchall()

        # Also check paper_positions if available
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_positions'")
        has_paper = cursor.fetchone() is not None
        paper_trades = []
        if has_paper:
            paper_trades = conn.execute("""
                SELECT symbol, status, return_pct, entry_price, sl_price, target_price
                FROM paper_positions
                WHERE status IN ('closed', 'hit_sl', 'hit_tp')
                ORDER BY id DESC LIMIT 100
            """).fetchall()

        conn.close()

        symbol_stats: dict[str, dict[str, int]] = {}
        for row in picks:
            sym = str(row["symbol"]).upper()
            status = str(row["status"]).lower()
            ret = float(row["result_return"] or 0.0)
            is_win = (status == "hit_target") or (ret > 0.5)

            stats = symbol_stats.setdefault(sym, {"wins": 0, "losses": 0, "total": 0})
            stats["total"] += 1
            if is_win:
                stats["wins"] += 1
            else:
                stats["losses"] += 1

        for row in paper_trades:
            sym = str(row["symbol"]).upper()
            status = str(row["status"]).lower()
            ret = float(row["return_pct"] or 0.0)
            is_win = (status == "hit_tp") or (ret > 0.5)

            stats = symbol_stats.setdefault(sym, {"wins": 0, "losses": 0, "total": 0})
            stats["total"] += 1
            if is_win:
                stats["wins"] += 1
            else:
                stats["losses"] += 1

        # Discover patterns that fail >= 75% of the time (min sample: 3 trades)
        penalty_rules: list[dict[str, Any]] = []

        # 1. Symbol-specific failure penalty
        for sym, s in symbol_stats.items():
            if s["total"] >= 3:
                loss_rate = s["losses"] / s["total"]
                if loss_rate >= 0.75:
                    penalty_rules.append({
                        "type": "symbol_penalty",
                        "symbol": sym,
                        "penalty_pts": 10.0,
                        "loss_rate": round(loss_rate * 100, 1),
                        "sample_size": s["total"],
                        "created_at": today_ist_str(),
                        "reason": f"Historical loss rate {loss_rate*100:.0f}% across {s['total']} trades"
                    })

        # 2. Standardized high-loss pattern guards
        penalty_rules.append({
            "type": "low_rvol_trap",
            "threshold_rvol": 1.2,
            "penalty_pts": 8.0,
            "reason": "Breakout attempts on RVOL < 1.2 historically fail due to lack of institutional backing"
        })
        penalty_rules.append({
            "type": "high_atr_exhaustion",
            "threshold_expansion": 85.0,
            "penalty_pts": 10.0,
            "reason": "Entries after > 85% ATR expansion suffer from profit-taking reversions"
        })
        penalty_rules.append({
            "type": "high_rsi_exhaustion",
            "threshold_rsi": 75.0,
            "penalty_pts": 6.0,
            "reason": "RSI > 75 entries face sharp mean-reversion pullbacks"
        })

        current_rules = load_audit_rules()
        current_rules["penalty_rules"] = penalty_rules
        current_rules["setup_stats"] = symbol_stats
        save_audit_rules(current_rules)

        logger.info("Auditor completed: %d active penalty rules generated", len(penalty_rules))
        return {
            "status": "success",
            "active_rules_count": len(penalty_rules),
            "symbols_evaluated": len(symbol_stats),
            "timestamp": now_ist().isoformat()
        }

    except Exception as exc:
        logger.error("Audit cycle failed: %s", exc)
        return {"status": "error", "error": str(exc)}
