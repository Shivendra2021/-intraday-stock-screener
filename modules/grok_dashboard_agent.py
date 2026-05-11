"""Grok-led dashboard state agent."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

STATE_FILE = "data/grok_dashboard_state.json"
_agent_thread: threading.Thread | None = None
_agent_running = False


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return dt.date.today().isoformat()


def _connect() -> sqlite3.Connection:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    except Exception as exc:
        logger.debug("Dashboard agent query failed: %s | %s", exc, sql)
        return []


def _one(conn: sqlite3.Connection, sql: str, params: tuple = (), default: Any = None) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else default
    except Exception as exc:
        logger.debug("Dashboard agent scalar failed: %s | %s", exc, sql)
        return default


def _market_status() -> str:
    try:
        from modules.scanner import is_market_holiday, is_market_open

        today = dt.date.today()
        if today.weekday() >= 5:
            return "Weekend"
        if is_market_holiday(today):
            return "Holiday"
        return "Open" if is_market_open() else "Closed"
    except Exception:
        return "Unknown"


def _latest_picks(conn: sqlite3.Connection) -> tuple[str | None, list[dict[str, Any]]]:
    today = _today()
    fields = (
        "date, rank, symbol, entry_price, sl_price, target_price, confidence, "
        "signal_reasons, status, result_return, validated_price, "
        "price_validation_status, edge_status, grok_review"
    )
    rows = _q(conn, f"SELECT {fields} FROM picks WHERE date=? ORDER BY rank", (today,))
    if rows:
        return today, rows

    latest_date = _one(conn, "SELECT MAX(date) FROM picks", default=None)
    if not latest_date:
        return None, []
    return latest_date, _q(conn, f"SELECT {fields} FROM picks WHERE date=? ORDER BY rank", (latest_date,))


def _accuracy(conn: sqlite3.Connection) -> dict[str, Any]:
    totals = _q(
        conn,
        """SELECT COALESCE(SUM(tp_count), 0) AS tp,
                  COALESCE(SUM(sl_count), 0) AS sl,
                  COALESCE(AVG(accuracy), 0) AS avg_accuracy,
                  COALESCE(AVG(avg_return), 0) AS avg_return,
                  COUNT(*) AS trading_days
             FROM daily_accuracy""",
    )
    daily = _q(
        conn,
        """SELECT date, tp_count, sl_count, total, accuracy, avg_return
             FROM daily_accuracy
            ORDER BY date DESC
            LIMIT 7""",
    )
    overall = totals[0] if totals else {}
    tp = int(overall.get("tp") or 0)
    sl = int(overall.get("sl") or 0)
    closed = tp + sl
    return {
        "tp": tp,
        "sl": sl,
        "closed": closed,
        "hit_rate": round(tp / closed * 100, 1) if closed else 0.0,
        "avg_accuracy": round(float(overall.get("avg_accuracy") or 0), 2),
        "avg_return": round(float(overall.get("avg_return") or 0), 2),
        "trading_days": int(overall.get("trading_days") or 0),
        "daily": daily,
    }


def _sector_snapshot(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    latest_date = _one(conn, "SELECT MAX(date) FROM intraday_sector_heatmap", default=None)
    if latest_date:
        rows = _q(
            conn,
            """SELECT sector, sector_avg_change_pct, sector_advance_count,
                      sector_decline_count, sector_7plus_count,
                      sector_momentum_score, is_hot, timestamp
                 FROM intraday_sector_heatmap
                WHERE date=?
                ORDER BY sector_momentum_score DESC, sector_avg_change_pct DESC
                LIMIT 8""",
            (latest_date,),
        )
        if rows:
            return rows
    return []


def _top_intraday_stocks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    latest_date = _one(conn, "SELECT MAX(date) FROM after_market_winner_features", default=None)
    if latest_date:
        rows = _q(
            conn,
            """SELECT symbol, return_pct, open_to_high_pct, open_to_close_pct,
                      volume_ratio, gap_pct, sector, pattern_key
                 FROM after_market_winner_features
                WHERE date=?
                ORDER BY return_pct DESC
                LIMIT 12""",
            (latest_date,),
        )
        if rows:
            return rows

    latest_date = _one(conn, "SELECT MAX(date) FROM intraday_winners", default=None)
    if latest_date:
        return _q(
            conn,
            """SELECT symbol, return_pct, volume_ratio, sector, notes
                 FROM intraday_winners
                WHERE date=?
                ORDER BY return_pct DESC
                LIMIT 12""",
            (latest_date,),
        )
    return []


def _pattern_snapshot(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    latest_date = _one(conn, "SELECT MAX(date) FROM after_market_learned_patterns", default=None)
    if latest_date:
        rows = _q(
            conn,
            """SELECT pattern_key, confidence, support_count, avg_return_pct, rules_json
                 FROM after_market_learned_patterns
                WHERE date=?
                ORDER BY confidence DESC, support_count DESC
                LIMIT 8""",
            (latest_date,),
        )
        if rows:
            return rows
    return _q(
        conn,
        """SELECT pattern_key, success_rate AS confidence, sample_count AS support_count,
                  last_market_update
             FROM patterns
            ORDER BY success_rate DESC, sample_count DESC
            LIMIT 8""",
    )


def _tracking_snapshot() -> dict[str, Any]:
    try:
        from modules.stock_tracker import get_tracking_status

        return get_tracking_status()
    except Exception as exc:
        logger.debug("Tracking snapshot unavailable: %s", exc)
        return {}


def _tracked_picks_as_rows(tracking: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    picks = tracking.get("picks") or {}
    if not isinstance(picks, dict):
        return None, []

    rows: list[dict[str, Any]] = []
    for item in picks.values():
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "date": item.get("date"),
                "rank": item.get("rank"),
                "symbol": item.get("symbol"),
                "entry_price": item.get("entry_price"),
                "sl_price": item.get("sl_price"),
                "target_price": item.get("tp_price") or item.get("target_price"),
                "confidence": item.get("score"),
                "signal_reasons": item.get("signal_reasons"),
                "status": item.get("status"),
                "result_return": item.get("pnl_pct"),
                "sector": item.get("sector"),
                "rsi": item.get("rsi"),
                "adx": item.get("adx"),
                "patterns": item.get("patterns", []),
            }
        )
    rows.sort(key=lambda row: int(row.get("rank") or 999))
    dates = [row.get("date") for row in rows if row.get("date")]
    return (max(dates) if dates else None), rows


def _load_existing() -> dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {}


def _save_state(payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False, default=str)


def _ai_due(existing: dict[str, Any]) -> bool:
    from config import GROK_DASHBOARD_AGENT_AI_INTERVAL_MINUTES

    last = existing.get("ai", {}).get("updated_epoch")
    if not last:
        return True
    return (time.time() - float(last)) >= max(60, GROK_DASHBOARD_AGENT_AI_INTERVAL_MINUTES * 60)


def _fallback_brief(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    sectors = [row.get("sector") for row in payload.get("trending_sectors", [])[:3] if row.get("sector")]
    winners = [row.get("symbol") for row in payload.get("top_intraday_stocks", [])[:5] if row.get("symbol")]
    pick_count = len(payload.get("next_session_picks", []))
    return {
        "ok": False,
        "skipped": True,
        "reason": reason,
        "model": None,
        "market_note": f"Market is {payload.get('market_status', 'Unknown')}. Dashboard state updated from local data.",
        "dashboard_summary": f"{pick_count} picks in latest set. Top sectors: {', '.join(sectors) or 'not available'}.",
        "pick_view": "Use latest stored picks and SL/TP levels until the next morning run refreshes them.",
        "sector_view": f"Leading sectors: {', '.join(sectors) or 'not available'}.",
        "risk_flags": [],
        "action_items": [f"Monitor {', '.join(winners[:3])}" if winners else "Wait for the next market data refresh."],
        "updated_at": _now(),
        "updated_epoch": time.time(),
    }


def _ask_grok_for_brief(payload: dict[str, Any]) -> dict[str, Any]:
    from modules.grok_brain import _allow_call, _call_brain, _parse_json_object

    allowed, reason = _allow_call()
    if not allowed:
        return _fallback_brief(payload, reason)

    compact = {
        "market_status": payload.get("market_status"),
        "latest_picks_date": payload.get("latest_picks_date"),
        "next_session_picks": payload.get("next_session_picks", [])[:8],
        "accuracy": payload.get("accuracy"),
        "tracking": payload.get("tracking"),
        "trending_sectors": payload.get("trending_sectors", [])[:8],
        "top_intraday_stocks": payload.get("top_intraday_stocks", [])[:12],
        "learned_patterns": payload.get("learned_patterns", [])[:8],
    }
    system_prompt = (
        "You are Grok, the main dashboard brain for MarketMind Pro, an Indian intraday "
        "stock research system. Use only the provided data. Do not invent prices, picks, "
        "targets, news, or live market status. Return compact JSON only with keys: "
        "market_note, dashboard_summary, pick_view, sector_view, risk_flags, action_items. "
        "risk_flags and action_items must be arrays of max 4 short strings."
    )
    result = _call_brain(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(compact, ensure_ascii=True, default=str)},
        ],
        max_tokens=420,
    )
    if not result.get("ok"):
        return _fallback_brief(payload, result.get("error", "AI unavailable"))

    parsed = _parse_json_object(result.get("content", ""))
    if not parsed:
        return _fallback_brief(payload, "AI returned non-JSON")
    parsed.update({"ok": True, "model": result.get("model"), "updated_at": _now(), "updated_epoch": time.time()})
    return parsed


def _persist_snapshot(payload: dict[str, Any]) -> None:
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO grok_dashboard_snapshots
                   (date, market_status, payload_json, ai_model, ai_status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    _today(),
                    payload.get("market_status"),
                    json.dumps(payload, ensure_ascii=False, default=str),
                    payload.get("ai", {}).get("model"),
                    "ok" if payload.get("ai", {}).get("ok") else payload.get("ai", {}).get("reason", "skipped"),
                    _now(),
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.debug("Could not persist Grok dashboard snapshot: %s", exc)


def build_dashboard_payload() -> dict[str, Any]:
    with _connect() as conn:
        latest_picks_date, picks = _latest_picks(conn)
        tracking = _tracking_snapshot()
        if not picks:
            latest_picks_date, picks = _tracked_picks_as_rows(tracking)
        return {
            "updated_at": _now(),
            "updated_epoch": time.time(),
            "market_status": _market_status(),
            "latest_picks_date": latest_picks_date,
            "next_session_picks": picks,
            "accuracy": _accuracy(conn),
            "tracking": tracking,
            "trending_sectors": _sector_snapshot(conn),
            "top_intraday_stocks": _top_intraday_stocks(conn),
            "learned_patterns": _pattern_snapshot(conn),
        }


def refresh_dashboard_state(use_ai: bool = True, force_ai: bool = False) -> dict[str, Any]:
    existing = _load_existing()
    payload = build_dashboard_payload()
    if use_ai and (force_ai or _ai_due(existing)):
        payload["ai"] = _ask_grok_for_brief(payload)
    else:
        payload["ai"] = existing.get("ai") or _fallback_brief(payload, "AI refresh not due")
    _save_state(payload)
    _persist_snapshot(payload)
    logger.info(
        "Grok dashboard agent updated: picks=%s sectors=%s winners=%s ai=%s",
        len(payload.get("next_session_picks", [])),
        len(payload.get("trending_sectors", [])),
        len(payload.get("top_intraday_stocks", [])),
        "ok" if payload.get("ai", {}).get("ok") else payload.get("ai", {}).get("reason", "skipped"),
    )
    return payload


def get_dashboard_state(max_age_seconds: int = 900) -> dict[str, Any]:
    state = _load_existing()
    if not state or (time.time() - float(state.get("updated_epoch", 0) or 0)) > max_age_seconds:
        return refresh_dashboard_state(use_ai=False)
    return state


def start_grok_dashboard_agent(interval_minutes: int | None = None) -> dict[str, Any]:
    global _agent_running, _agent_thread

    if _agent_running:
        return {"ok": False, "error": "Grok dashboard agent already running"}

    from config import GROK_DASHBOARD_AGENT_INTERVAL_MINUTES

    interval_minutes = interval_minutes or GROK_DASHBOARD_AGENT_INTERVAL_MINUTES
    _agent_running = True

    def _loop() -> None:
        while _agent_running:
            try:
                refresh_dashboard_state(use_ai=True)
            except Exception as exc:
                logger.error("Grok dashboard agent cycle failed: %s", exc)
            time.sleep(max(60, interval_minutes * 60))

    _agent_thread = threading.Thread(target=_loop, name="grok-dashboard-agent", daemon=True)
    _agent_thread.start()
    logger.info("Grok dashboard agent started (every %s min)", interval_minutes)
    return {"ok": True, "interval_minutes": interval_minutes}


def stop_grok_dashboard_agent() -> dict[str, Any]:
    global _agent_running
    _agent_running = False
    return {"ok": True}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = refresh_dashboard_state(use_ai=True, force_ai=True)
    print(json.dumps({"ok": True, "updated_at": result.get("updated_at"), "ai": result.get("ai", {})}, indent=2, default=str))
