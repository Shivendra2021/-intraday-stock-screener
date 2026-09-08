"""Live terminal updater backed by the dashboard database.

This does not create picks or place trades. It mirrors the current DB/dashboard
state into a small JSON file that a visible terminal can refresh from.
"""

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

STATE_FILE = os.path.join("data", "live_terminal_state.json")
_thread: threading.Thread | None = None
_running = False


def _now() -> str:
    try:
        from modules.time_utils import now_ist

        return now_ist().isoformat(timespec="seconds")
    except Exception:
        return dt.datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    try:
        from modules.time_utils import today_ist_str

        return today_ist_str()
    except Exception:
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
        logger.debug("Terminal updater query failed: %s | %s", exc, sql)
        return []


def _one(conn: sqlite3.Connection, sql: str, params: tuple = (), default: Any = None) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else default
    except Exception as exc:
        logger.debug("Terminal updater scalar failed: %s | %s", exc, sql)
        return default


def _load_json(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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


def build_terminal_state() -> dict[str, Any]:
    """Build a compact state from DB and existing AI agent output files."""
    today = _today()
    with _connect() as conn:
        today_picks = _q(
            conn,
            """SELECT rank, symbol, entry_price, sl_price, target_price,
                      confidence, status, result_return, created_at, session_type, source_label
                 FROM picks
                WHERE date=?
                  AND COALESCE(session_type, 'morning_final')='morning_final'
                  AND COALESCE(is_official_morning, 1)=1
                ORDER BY rank""",
            (today,),
        )
        if not today_picks:
            today_picks = _q(
                conn,
                """SELECT rank, symbol, entry_price, sl_price, target_price,
                          confidence, status, result_return, created_at, session_type, source_label
                     FROM picks
                    WHERE date=?
                      AND COALESCE(session_type, '')='late_intraday_recovery'
                    ORDER BY rank""",
                (today,),
            )
        latest_pick_date = _one(
            conn,
            "SELECT MAX(date) FROM picks WHERE COALESCE(session_type, 'morning_final')='morning_final' "
            "AND COALESCE(is_official_morning, 1)=1",
            default=None,
        )
        recent_history = _q(
            conn,
            """SELECT date, rank, symbol, status, result_return
                 FROM picks
                WHERE COALESCE(session_type, 'morning_final')='morning_final'
                  AND COALESCE(is_official_morning, 1)=1
                ORDER BY date DESC, rank ASC, id DESC
                LIMIT 12""",
        )
        accuracy = _q(
            conn,
            """SELECT date, tp_count, sl_count, total, accuracy, avg_return
                 FROM daily_accuracy
                ORDER BY date DESC
                LIMIT 7""",
        )
        universe_count = _one(conn, "SELECT COUNT(*) FROM stock_universe WHERE is_active=1", default=0) or 0

    terminal = {}
    try:
        from modules.market_terminal import terminal_snapshot

        terminal = terminal_snapshot(limit=10)
    except Exception as exc:
        terminal = {"error": str(exc)}

    grok_state = _load_json(os.path.join("data", "grok_dashboard_state.json"))
    ollama_state = _load_json(os.path.join("data", "ollama_intraday_agent_state.json"))
    ai = grok_state.get("ai") or {}
    ollama_scan = ollama_state.get("scan") or {}
    ollama_study = ollama_state.get("study") or {}

    state = {
        "updated_at": _now(),
        "date": today,
        "market_status": _market_status(),
        "universe_count": universe_count,
        "today_picks": today_picks,
        "today_pick_count": len(today_picks),
        "latest_pick_date": latest_pick_date,
        "recent_history": recent_history,
        "accuracy": accuracy,
        "terminal": terminal,
        "ai_brief": {
            "model": ai.get("model"),
            "market_note": ai.get("market_note"),
            "dashboard_summary": ai.get("dashboard_summary"),
            "pick_view": ai.get("pick_view"),
            "risk_flags": ai.get("risk_flags") or [],
            "action_items": ai.get("action_items") or [],
            "updated_at": ai.get("updated_at"),
            "ok": bool(ai.get("ok")),
        },
        "ollama": {
            "scanned": ollama_scan.get("symbols_scanned", 0),
            "winners": ollama_scan.get("winner_count", 0),
            "top_symbols": ollama_study.get("top_symbols", [])[:8],
            "summary": ollama_study.get("summary") or ollama_study.get("winner_profile"),
        },
    }
    return state


def refresh_terminal_state() -> dict[str, Any]:
    state = build_terminal_state()
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fp:
        json.dump(state, fp, indent=2, ensure_ascii=False, default=str)
    logger.info(
        "Live terminal state updated: date=%s today_picks=%s market=%s",
        state.get("date"),
        state.get("today_pick_count"),
        state.get("market_status"),
    )
    return state


def get_terminal_state(max_age_seconds: int = 120) -> dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            age = time.time() - os.path.getmtime(STATE_FILE)
            if age <= max_age_seconds:
                return _load_json(STATE_FILE)
        except Exception:
            pass
    return refresh_terminal_state()


def start_terminal_updater(interval_seconds: int | None = None) -> dict[str, Any]:
    global _running, _thread

    if _running:
        return {"ok": False, "error": "Terminal updater already running"}

    from config import TERMINAL_UPDATER_INTERVAL_SECONDS

    interval_seconds = int(interval_seconds or TERMINAL_UPDATER_INTERVAL_SECONDS)
    _running = True

    def _loop() -> None:
        while _running:
            try:
                refresh_terminal_state()
            except Exception as exc:
                logger.error("Live terminal updater cycle failed: %s", exc)
            time.sleep(max(10, interval_seconds))

    _thread = threading.Thread(target=_loop, name="live-terminal-updater", daemon=True)
    _thread.start()
    logger.info("Live terminal updater started (every %s sec)", interval_seconds)
    return {"ok": True, "interval_seconds": interval_seconds}


def stop_terminal_updater() -> dict[str, Any]:
    global _running
    _running = False
    return {"ok": True}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(refresh_terminal_state(), indent=2, ensure_ascii=False, default=str))
