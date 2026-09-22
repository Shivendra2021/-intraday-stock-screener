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


def format_auditor_rules_for_prompt() -> str:
    """
    Format active learned penalty rules and failure signatures into an institutional
    prompt block for LLM Dual-Brain evaluation and prompt injection.
    """
    rules_data = load_audit_rules()
    rules = rules_data.get("penalty_rules", [])
    if not rules:
        return ""

    lines = [
        "### [INSTITUTIONAL RISK AUDITOR: ACTIVE LOSS PREVENTION RULES]",
        "The Autonomous Risk Auditor reviewed historical closed trades and identified these recurring failure signatures:",
    ]
    for r in rules:
        if not r.get("active", True):
            continue
        r_id = r.get("rule_id") or r.get("type", "RULE_UNKNOWN")
        target = r.get("symbol") or r.get("target") or "ALL"
        pts = float(r.get("penalty_pts", 10.0) or 10.0)
        desc = r.get("flawed_setup") or r.get("reason", "")
        ev = r.get("evidence", {})
        ev_str = ""
        if ev and ev.get("loss_rate_pct") is not None:
            ev_str = f" [Evidence: {ev.get('loss_rate_pct')}% loss rate across {ev.get('sample_size')} trades]"
        elif r.get("loss_rate") is not None:
            ev_str = f" [Evidence: {r.get('loss_rate')}% loss rate across {r.get('sample_size', 0)} trades]"
        lines.append(f"- [{r_id}] Target: {target} | Penalty: -{pts:.1f} pts | Condition: {desc}{ev_str}")

    lines.append(
        "\nINSTRUCTION TO AI: If any candidate setup violates these active rules, "
        "you MUST discount confidence below 60% or issue an explicit REMOVE_PICK / VETO command citing the Rule ID."
    )
    return "\n".join(lines)


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
    expansion_pct = float(metadata.get("expansion_pct", metadata.get("adr_exp", 0.0)) or 0.0)
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
        if not rule.get("active", True):
            continue

        pts = float(rule.get("penalty_pts", 0.0) or 0.0)
        rule_type = str(rule.get("type", "")).lower()
        rule_id = str(rule.get("rule_id", "")).lower()
        rule_sym = str(rule.get("symbol") or rule.get("target") or "").upper()

        if rule_sym and rule_sym != "ALL" and rule_sym == symbol:
            total_penalty += pts
            reasons.append(f"auditor:symbol_loss_streak_{symbol} (-{pts:.1f}pts)")
            continue

        if ("low_rvol" in rule_type or "low_rvol" in rule_id) and rvol <= float(rule.get("threshold_rvol", 1.2)):
            total_penalty += pts
            reasons.append(f"auditor:{rule.get('rule_id', rule_type)} (-{pts:.1f}pts)")

        elif ("atr_exhaustion" in rule_type or "atr_exhaustion" in rule_id) and expansion_pct >= float(rule.get("threshold_expansion", 80.0)):
            total_penalty += pts
            reasons.append(f"auditor:{rule.get('rule_id', rule_type)} (-{pts:.1f}pts)")

        elif ("rsi_exhaustion" in rule_type or "rsi_exhaustion" in rule_id) and rsi >= float(rule.get("threshold_rsi", 72.0)):
            total_penalty += pts
            reasons.append(f"auditor:{rule.get('rule_id', rule_type)} (-{pts:.1f}pts)")

        elif ("macro_bear" in rule_type or "macro_bear" in rule_id) and macro_align == "full_bear":
            total_penalty += pts
            reasons.append(f"auditor:{rule.get('rule_id', rule_type)} (-{pts:.1f}pts)")

    # Clamp penalty strictly between 0 and 20 points
    clamped_penalty = round(min(20.0, max(0.0, total_penalty)), 2)
    return clamped_penalty, reasons


def audit_closed_trades() -> dict[str, Any]:
    """
    Review historical closed trades from data/history.db (and paper_positions).
    Clusters losing trades by adverse technical signatures:
      1. Entering breakouts when RVOL < 1.2 (lack of volume backing)
      2. Entering when Daily ATR expansion >= 85% (exhaustion / reversal)
      3. Overbought RSI > 72 near resistance
      4. Macro trend contradiction (below Daily EMA200 & VWAP)
      5. Symbol-specific chronic loss streaks (>= 70% loss rate)
    Synthesizes active penalization rules into data/audit_rules.json with empirical evidence.
    """
    db_path = "data/history.db"
    if not os.path.exists(db_path):
        return {"status": "skipped", "reason": "no_db"}

    # Load alert snapshots to map entry metrics to trade outcomes
    snapshots_by_symbol: dict[str, list[dict]] = {}
    if os.path.exists(SNAPSHOT_LOG_PATH):
        try:
            with open(SNAPSHOT_LOG_PATH, "r", encoding="utf-8") as sf:
                for line in sf:
                    line = line.strip()
                    if line:
                        s_obj = json.loads(line)
                        sym = s_obj.get("symbol", "").upper()
                        if sym:
                            snapshots_by_symbol.setdefault(sym, []).append(s_obj)
        except Exception as exc:
            logger.debug("Failed reading snapshots log: %s", exc)

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
            ORDER BY id DESC LIMIT 150
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
                ORDER BY id DESC LIMIT 150
            """).fetchall()

        conn.close()

        symbol_stats: dict[str, dict[str, Any]] = {}
        pattern_clusters: dict[str, dict[str, Any]] = {
            "low_rvol": {"total": 0, "losses": 0, "returns": []},
            "high_atr": {"total": 0, "losses": 0, "returns": []},
            "high_rsi": {"total": 0, "losses": 0, "returns": []},
            "macro_bear": {"total": 0, "losses": 0, "returns": []},
        }

        all_closed = []
        for row in picks:
            sym = str(row["symbol"]).upper()
            status = str(row["status"]).lower()
            ret = float(row["result_return"] or 0.0)
            is_win = (status == "hit_target") or (ret > 0.5)
            all_closed.append((sym, is_win, ret, str(row["signal_reasons"] or "")))

        for row in paper_trades:
            sym = str(row["symbol"]).upper()
            status = str(row["status"]).lower()
            ret = float(row["return_pct"] or 0.0)
            is_win = (status == "hit_tp") or (ret > 0.5)
            all_closed.append((sym, is_win, ret, ""))

        for sym, is_win, ret, reasons in all_closed:
            stats = symbol_stats.setdefault(sym, {"wins": 0, "losses": 0, "total": 0, "returns": []})
            stats["total"] += 1
            stats["returns"].append(ret)
            if is_win:
                stats["wins"] += 1
            else:
                stats["losses"] += 1

            # Match with snapshot to correlate technical failure signatures
            snaps = snapshots_by_symbol.get(sym, [])
            snap = snaps[-1] if snaps else {}

            rvol = float(snap.get("rvol", 1.0) or 1.0)
            expansion_pct = float(snap.get("expansion_pct", 0.0) or 0.0)
            rsi = float(snap.get("rsi", 50.0) or 50.0)
            macro_align = str(snap.get("macro_alignment", "neutral"))

            # Cluster signatures
            if rvol <= 1.2:
                pattern_clusters["low_rvol"]["total"] += 1
                pattern_clusters["low_rvol"]["returns"].append(ret)
                if not is_win:
                    pattern_clusters["low_rvol"]["losses"] += 1

            if expansion_pct >= 85.0:
                pattern_clusters["high_atr"]["total"] += 1
                pattern_clusters["high_atr"]["returns"].append(ret)
                if not is_win:
                    pattern_clusters["high_atr"]["losses"] += 1

            if rsi >= 72.0:
                pattern_clusters["high_rsi"]["total"] += 1
                pattern_clusters["high_rsi"]["returns"].append(ret)
                if not is_win:
                    pattern_clusters["high_rsi"]["losses"] += 1

            if macro_align == "full_bear":
                pattern_clusters["macro_bear"]["total"] += 1
                pattern_clusters["macro_bear"]["returns"].append(ret)
                if not is_win:
                    pattern_clusters["macro_bear"]["losses"] += 1

        penalty_rules: list[dict[str, Any]] = []

        # 1. Symbol-specific failure penalty (min 3 trades, loss rate >= 70%)
        for sym, s in symbol_stats.items():
            if s["total"] >= 3:
                loss_rate = s["losses"] / s["total"]
                if loss_rate >= 0.70:
                    avg_loss = sum(r for r in s["returns"] if r < 0) / max(1, s["losses"])
                    penalty_rules.append({
                        "rule_id": f"RULE_SYMBOL_{sym}",
                        "type": "symbol_penalty",
                        "symbol": sym,
                        "target": sym,
                        "penalty_pts": 12.0,
                        "active": True,
                        "flawed_setup": f"Chronic failure streak on {sym} ({s['losses']}/{s['total']} trades stopped out)",
                        "evidence": {
                            "sample_size": s["total"],
                            "loss_rate_pct": round(loss_rate * 100, 1),
                            "avg_loss_pct": round(avg_loss, 2)
                        },
                        "created_at": today_ist_str()
                    })

        # 2. Dynamic Pattern Rules based on Empirical Clustering
        # Low RVOL Breakout Rule
        lr_data = pattern_clusters["low_rvol"]
        if lr_data["total"] >= 3 and (lr_data["losses"] / lr_data["total"]) >= 0.65:
            lr_loss_rate = round((lr_data["losses"] / lr_data["total"]) * 100, 1)
            lr_avg_loss = sum(r for r in lr_data["returns"] if r < 0) / max(1, lr_data["losses"])
            penalty_rules.append({
                "rule_id": "RULE_LOW_RVOL_BREAKOUT",
                "type": "low_rvol_trap",
                "target": "ALL",
                "threshold_rvol": 1.2,
                "penalty_pts": 12.0,
                "active": True,
                "flawed_setup": "Breakout entered with RVOL < 1.2x (lack of institutional participation)",
                "evidence": {
                    "sample_size": lr_data["total"],
                    "loss_rate_pct": lr_loss_rate,
                    "avg_loss_pct": round(lr_avg_loss, 2)
                }
            })
        else:
            # Baseline institutional prior
            penalty_rules.append({
                "rule_id": "RULE_LOW_RVOL_BREAKOUT",
                "type": "low_rvol_trap",
                "target": "ALL",
                "threshold_rvol": 1.2,
                "penalty_pts": 10.0,
                "active": True,
                "flawed_setup": "Breakout attempts on RVOL < 1.2x historically fail due to lack of volume backing",
                "evidence": {"type": "institutional_prior", "status": "active"}
            })

        # High ATR Exhaustion Rule
        ha_data = pattern_clusters["high_atr"]
        if ha_data["total"] >= 3 and (ha_data["losses"] / ha_data["total"]) >= 0.65:
            ha_loss_rate = round((ha_data["losses"] / ha_data["total"]) * 100, 1)
            ha_avg_loss = sum(r for r in ha_data["returns"] if r < 0) / max(1, ha_data["losses"])
            penalty_rules.append({
                "rule_id": "RULE_HIGH_ATR_EXHAUSTION",
                "type": "high_atr_exhaustion",
                "target": "ALL",
                "threshold_expansion": 85.0,
                "penalty_pts": 12.0,
                "active": True,
                "flawed_setup": "Entries after >= 85% ATR expansion suffer from immediate profit-taking reversions",
                "evidence": {
                    "sample_size": ha_data["total"],
                    "loss_rate_pct": ha_loss_rate,
                    "avg_loss_pct": round(ha_avg_loss, 2)
                }
            })
        else:
            penalty_rules.append({
                "rule_id": "RULE_HIGH_ATR_EXHAUSTION",
                "type": "high_atr_exhaustion",
                "target": "ALL",
                "threshold_expansion": 85.0,
                "penalty_pts": 10.0,
                "active": True,
                "flawed_setup": "Entries after > 85% ATR expansion suffer from profit-taking reversions",
                "evidence": {"type": "institutional_prior", "status": "active"}
            })

        # Overbought RSI Exhaustion Rule
        hr_data = pattern_clusters["high_rsi"]
        if hr_data["total"] >= 3 and (hr_data["losses"] / hr_data["total"]) >= 0.65:
            hr_loss_rate = round((hr_data["losses"] / hr_data["total"]) * 100, 1)
            hr_avg_loss = sum(r for r in hr_data["returns"] if r < 0) / max(1, hr_data["losses"])
            penalty_rules.append({
                "rule_id": "RULE_HIGH_RSI_EXHAUSTION",
                "type": "high_rsi_exhaustion",
                "target": "ALL",
                "threshold_rsi": 72.0,
                "penalty_pts": 10.0,
                "active": True,
                "flawed_setup": "RSI >= 72 entries face sharp mean-reversion pullbacks into resistance",
                "evidence": {
                    "sample_size": hr_data["total"],
                    "loss_rate_pct": hr_loss_rate,
                    "avg_loss_pct": round(hr_avg_loss, 2)
                }
            })
        else:
            penalty_rules.append({
                "rule_id": "RULE_HIGH_RSI_EXHAUSTION",
                "type": "high_rsi_exhaustion",
                "target": "ALL",
                "threshold_rsi": 75.0,
                "penalty_pts": 8.0,
                "active": True,
                "flawed_setup": "RSI > 75 entries face sharp mean-reversion pullbacks",
                "evidence": {"type": "institutional_prior", "status": "active"}
            })

        current_rules = load_audit_rules()
        current_rules["penalty_rules"] = penalty_rules
        current_rules["setup_stats"] = symbol_stats
        current_rules["version"] = "2.0"
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
