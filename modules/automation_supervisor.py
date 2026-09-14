"""Time-aware automation supervisor for missed bot work.

The APScheduler jobs still define the normal daily timetable. This module adds
durable catch-up logic for Windows sleep/restart cases where scheduled run
times were missed while the laptop was unavailable.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from modules.time_utils import now_ist, today_ist_str

logger = logging.getLogger(__name__)

LEDGER_FILE = Path("data") / "automation_ledger.json"
_thread: threading.Thread | None = None
_running = False
_cycle_lock = threading.Lock()


def _parse_hhmm(value: str) -> dt.time:
    hour, minute = str(value).split(":", 1)
    return dt.time(int(hour), int(minute))


def _load_ledger() -> dict[str, Any]:
    today = today_ist_str()
    if LEDGER_FILE.exists():
        try:
            with LEDGER_FILE.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("date") == today:
                data.setdefault("jobs", {})
                return data
        except Exception:
            pass
    return {"date": today, "updated_at": now_ist().isoformat(timespec="seconds"), "jobs": {}}


def _save_ledger(ledger: dict[str, Any]) -> None:
    LEDGER_FILE.parent.mkdir(exist_ok=True)
    ledger["updated_at"] = now_ist().isoformat(timespec="seconds")
    with LEDGER_FILE.open("w", encoding="utf-8") as fp:
        json.dump(ledger, fp, indent=2, ensure_ascii=False, default=str)


def _mark(job_id: str, status: str, detail: str = "", extra: dict[str, Any] | None = None) -> None:
    ledger = _load_ledger()
    ledger.setdefault("jobs", {})[job_id] = {
        "status": status,
        "detail": detail,
        "updated_at": now_ist().isoformat(timespec="seconds"),
        "extra": extra or {},
    }
    _save_ledger(ledger)


def _job_status(job_id: str) -> str:
    return str((_load_ledger().get("jobs") or {}).get(job_id, {}).get("status") or "")


def _done(job_id: str) -> bool:
    return _job_status(job_id) in {"done", "skipped", "timeout"}


def _connect() -> sqlite3.Connection:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _scalar(sql: str, params: tuple[Any, ...] = (), default: Any = 0) -> Any:
    try:
        with _connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return row[0] if row else default
    except Exception as exc:
        logger.debug("Automation scalar check failed: %s", exc)
        return default


def _count_picks(session_type: str | None = None, official: bool | None = None) -> int:
    today = today_ist_str()
    clauses = ["date=?"]
    params: list[Any] = [today]
    if session_type is not None:
        clauses.append("COALESCE(session_type, 'morning_final')=?")
        params.append(session_type)
    if official is not None:
        clauses.append("COALESCE(is_official_morning, 1)=?")
        params.append(1 if official else 0)
    return int(_scalar(f"SELECT COUNT(*) FROM picks WHERE {' AND '.join(clauses)}", tuple(params), 0) or 0)


def _late_recovery_picks() -> list[dict[str, Any]]:
    today = today_ist_str()
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM picks
                WHERE date=? AND COALESCE(session_type, '')='late_intraday_recovery'
                ORDER BY rank, id
                """,
                (today,),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.debug("Late recovery pick load failed: %s", exc)
        return []


def _tracking_active_count() -> int:
    path = Path("data") / "pick_tracking.json"
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return sum(1 for row in data.values() if str(row.get("status", "")).upper() == "ACTIVE")


def _today_after_market_rows() -> int:
    today = today_ist_str()
    return int(
        _scalar(
            "SELECT COUNT(*) FROM after_market_winner_features WHERE date=?",
            (today,),
            0,
        )
        or 0
    )


def _eod_outcome_done_today() -> bool:
    path = Path("data") / "eod_outcome_brain_state.json"
    if not path.exists():
        return False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return state.get("last_alert_date") == today_ist_str()


def _deep_learning_done_today() -> bool:
    path = Path("data") / "daily_winner_learning.json"
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("date") == today_ist_str() and int(state.get("winner_count") or 0) > 0:
                return True
        except Exception:
            pass
    return int(
        _scalar(
            "SELECT COUNT(*) FROM ollama_winner_studies WHERE date=?",
            (today_ist_str(),),
            0,
        )
        or 0
    ) > 0


def _is_trading_day() -> bool:
    try:
        from modules.scanner import is_market_holiday, is_weekend
        from modules.time_utils import today_ist

        today = today_ist()
        return not (is_weekend(today) or is_market_holiday(today))
    except Exception:
        return now_ist().weekday() < 5


def _telegram_ok(event_type: str) -> bool:
    today = today_ist_str()
    path = Path("data") / "telegram_delivery.jsonl"
    if not path.exists():
        return False
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("date") == today and row.get("event_type") == event_type and bool(row.get("ok")):
                return True
    except Exception:
        return False
    return False


def _safe_run(job_id: str, action: Callable[[], Any]) -> Any:
    if _done(job_id):
        return {"skipped": True, "reason": "already_done"}
    _mark(job_id, "running")
    try:
        result = action()
        if isinstance(result, dict) and result.get("timeout"):
            _mark(job_id, "timeout", "Timed out; will not block system startup", result)
            return result
        _mark(job_id, "done", extra={"result": result if isinstance(result, dict) else str(result)[:500]})
        return result
    except Exception as exc:
        logger.exception("Automation catch-up job failed: %s", job_id)
        _mark(job_id, "failed", str(exc)[:500])
        return {"ok": False, "error": str(exc)}


def _refresh_dashboard_state() -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        from modules.paper_portfolio import portfolio_summary

        result["paper"] = portfolio_summary()
    except Exception as exc:
        result["paper_error"] = str(exc)[:200]
    try:
        from modules.terminal_updater import refresh_terminal_state

        state = refresh_terminal_state()
        result["terminal"] = {
            "today_pick_count": state.get("today_pick_count"),
            "market_status": state.get("market_status"),
        }
    except Exception as exc:
        result["terminal_error"] = str(exc)[:200]
    try:
        from modules.grok_dashboard_agent import refresh_dashboard_state

        state = refresh_dashboard_state(use_ai=False)
        result["dashboard"] = {"latest_picks_date": state.get("latest_picks_date")}
    except Exception as exc:
        result["dashboard_error"] = str(exc)[:200]
    return result


def _run_morning_or_late_recovery() -> dict[str, Any]:
    import main

    before_official = _count_picks("morning_final", True)
    before_late = _count_picks("late_intraday_recovery", False)
    main.run_morning_session()
    after_official = _count_picks("morning_final", True)
    after_late = _count_picks("late_intraday_recovery", False)

    if after_late > before_late:
        picks = _late_recovery_picks()
        if picks:
            try:
                from modules.stock_tracker import init_tracking

                init_tracking(picks)
            except Exception as exc:
                logger.warning("Late recovery tracking init failed: %s", exc)
    return {
        "official_before": before_official,
        "official_after": after_official,
        "late_before": before_late,
        "late_after": after_late,
    }


def _run_tracking_update() -> dict[str, Any]:
    from modules.stock_tracker import update_tracking

    tracking = update_tracking()
    return {"tracked": len(tracking), "active": _tracking_active_count()}


def _run_tracking_eod() -> dict[str, Any]:
    from modules.stock_tracker import close_and_report_eod

    tracking = close_and_report_eod()
    try:
        from modules.paper_portfolio import settle_closed_positions

        paper = settle_closed_positions(today_ist_str())
    except Exception as exc:
        paper = {"error": str(exc)[:200]}
    return {"tracked": len(tracking), "active": _tracking_active_count(), "paper": paper}


def _run_eod_outcome() -> dict[str, Any]:
    from modules.eod_outcome_brain import reconcile_daily_outcomes

    return reconcile_daily_outcomes(send_telegram=True, review_with_brain=True)


def _run_light_after_market_learning() -> dict[str, Any]:
    from config import INTRADAY_MIN_RETURN_PCT, POSTMARKET_LIGHT_MAX_SYMBOLS
    from modules.after_market_learning import run_after_market_learning

    return run_after_market_learning(
        min_return_pct=INTRADAY_MIN_RETURN_PCT,
        max_symbols=max(50, int(POSTMARKET_LIGHT_MAX_SYMBOLS)),
    )


def _run_deep_after_market_learning() -> dict[str, Any]:
    from config import POSTMARKET_DEEP_LEARNING_ENABLED, POSTMARKET_DEEP_TIMEOUT_MINUTES
    from modules.heavy_job_coordinator import acquire_heavy_job

    if not POSTMARKET_DEEP_LEARNING_ENABLED:
        return {"skipped": True, "reason": "disabled"}

    timeout = max(300, int(POSTMARKET_DEEP_TIMEOUT_MINUTES) * 60)
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    with acquire_heavy_job(
        "postmarket_deep_learning",
        priority=3,
        stale_after_seconds=timeout + 300,
        wait=True,
        wait_timeout_seconds=120,
    ) as lease:
        if not lease.acquired:
            return {"skipped": True, "reason": lease.reason}
        try:
            proc = subprocess.run(
                [sys.executable, "tools/run_cloud_after_market.py"],
                cwd=os.getcwd(),
                text=True,
                capture_output=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            _mark("postmarket_deep_learning", "timeout", f"Timed out after {timeout}s")
            return {
                "ok": False,
                "timeout": True,
                "stdout": (exc.stdout or "")[-1000:],
                "stderr": (exc.stderr or "")[-1000:],
            }
        ok = proc.returncode == 0
        if not ok:
            raise RuntimeError((proc.stderr or proc.stdout or f"exit={proc.returncode}")[-800:])
        return {"ok": ok, "stdout": proc.stdout[-1500:], "stderr": proc.stderr[-800:]}


def _send_catchup_summary(result: dict[str, Any]) -> None:
    if _telegram_ok("automation_catchup_summary"):
        return
    try:
        from modules.alerts import send_raw_alert

        jobs = result.get("jobs", {})
        lines = [
            "<b>Stock Analyser V2 - Automation Catch-up</b>",
            f"Date: {today_ist_str()}",
            f"Phase: {result.get('phase')}",
            "",
        ]
        for job_id, payload in jobs.items():
            if isinstance(payload, dict):
                status = payload.get("status") or ("ok" if not payload.get("error") else "error")
            else:
                status = "done"
            lines.append(f"- {job_id}: {status}")
        lines.append("")
        lines.append("<i>Research only. Missed scheduled work has been reconciled.</i>")
        send_raw_alert("\n".join(lines), review_with_grok=False, event_type="automation_catchup_summary")
    except Exception as exc:
        logger.debug("Automation summary Telegram failed: %s", exc)


def current_phase() -> str:
    from config import (
        AUTO_LATE_RECOVERY_END,
        MARKET_CLOSE,
        MARKET_OPEN,
        MORNING_CATCHUP_END,
        MORNING_UNIVERSE_SCAN_START,
        POSTMARKET_CATCHUP_END,
    )

    now = now_ist().time()
    if now < _parse_hhmm(MORNING_UNIVERSE_SCAN_START):
        return "pre_morning_wait"
    if now <= _parse_hhmm(MORNING_CATCHUP_END):
        return "official_morning"
    if now < _parse_hhmm(MARKET_OPEN):
        return "pre_market_late"
    if now <= _parse_hhmm(AUTO_LATE_RECOVERY_END):
        return "intraday_late_recovery"
    if now <= _parse_hhmm(MARKET_CLOSE):
        return "intraday_tracking"
    if now <= _parse_hhmm(POSTMARKET_CATCHUP_END):
        return "post_market_catchup"
    return "off_hours"


def run_once(dry_run: bool = False, skip_deep: bool = False) -> dict[str, Any]:
    """Run one catch-up pass. Idempotent through DB checks and ledger entries."""
    from config import QUANT_ENABLED
    if QUANT_ENABLED:
        if dry_run:
            return {"status": "quant_v3", "dry_run": True, "jobs": {}}
        from modules.quant_runtime import run_once as run_quant_once
        return run_quant_once(notify=True)
    if not _cycle_lock.acquire(blocking=False):
        return {"ok": False, "reason": "cycle_already_running"}
    try:
        phase = current_phase()
        result: dict[str, Any] = {
            "ok": True,
            "date": today_ist_str(),
            "time": now_ist().strftime("%H:%M:%S"),
            "phase": phase,
            "dry_run": dry_run,
            "skip_deep": skip_deep,
            "jobs": {},
        }

        if not _is_trading_day():
            result["jobs"]["refresh"] = "non_trading_day"
            if not dry_run:
                result["jobs"]["refresh"] = _safe_run("daily_refresh", _refresh_dashboard_state)
            return result

        official_count = _count_picks("morning_final", True)
        late_count = _count_picks("late_intraday_recovery", False)
        active_count = _tracking_active_count()

        if phase == "official_morning" and official_count == 0:
            result["jobs"]["official_morning"] = "would_run" if dry_run else _safe_run("official_morning_pipeline", _run_morning_or_late_recovery)

        if phase == "intraday_late_recovery":
            from config import AUTO_LATE_RECOVERY_ENABLED

            if AUTO_LATE_RECOVERY_ENABLED and official_count == 0 and late_count == 0:
                result["jobs"]["late_recovery"] = "would_run" if dry_run else _safe_run("late_recovery_pipeline", _run_morning_or_late_recovery)

        if phase in {"intraday_late_recovery", "intraday_tracking"} and active_count > 0:
            result["jobs"]["tracking_update"] = "would_run" if dry_run else _safe_run(f"tracking_update_{now_ist().strftime('%H%M')}", _run_tracking_update)

        if phase == "post_market_catchup":
            if active_count > 0:
                result["jobs"]["tracking_eod"] = "would_run" if dry_run else _safe_run("tracking_eod", _run_tracking_eod)

            if not _eod_outcome_done_today() and not _done("eod_outcome_brain") and (_count_picks("morning_final", True) + _count_picks("late_intraday_recovery", False)) > 0:
                result["jobs"]["eod_outcome_brain"] = "would_run" if dry_run else _safe_run("eod_outcome_brain", _run_eod_outcome)

            if _today_after_market_rows() <= 0 and not _done("postmarket_light_learning"):
                result["jobs"]["postmarket_light_learning"] = "would_run" if dry_run else _safe_run("postmarket_light_learning", _run_light_after_market_learning)

            if skip_deep and not _deep_learning_done_today() and not _done("postmarket_deep_learning"):
                result["jobs"]["postmarket_deep_learning"] = "skipped_quick_pass"
            elif not _deep_learning_done_today() and not _done("postmarket_deep_learning"):
                result["jobs"]["postmarket_deep_learning"] = "would_run" if dry_run else _safe_run("postmarket_deep_learning", _run_deep_after_market_learning)

            result["jobs"]["refresh"] = "would_run" if dry_run else _safe_run(f"refresh_{now_ist().strftime('%H%M')}", _refresh_dashboard_state)
            if not dry_run:
                _send_catchup_summary(result)

        if not result["jobs"]:
            result["jobs"]["refresh"] = "would_run" if dry_run else _safe_run(f"refresh_{now_ist().strftime('%H%M')}", _refresh_dashboard_state)

        return result
    finally:
        _cycle_lock.release()


def start_automation_supervisor(interval_seconds: int | None = None) -> dict[str, Any]:
    global _running, _thread
    if _running:
        return {"ok": False, "error": "Automation supervisor already running"}

    from config import AUTOMATION_SUPERVISOR_INTERVAL_SECONDS

    interval_seconds = int(interval_seconds or AUTOMATION_SUPERVISOR_INTERVAL_SECONDS)
    _running = True

    def _loop() -> None:
        while _running:
            try:
                result = run_once(dry_run=False)
                logger.info("Automation supervisor cycle: phase=%s jobs=%s", result.get("phase"), list((result.get("jobs") or {}).keys()))
            except Exception as exc:
                logger.error("Automation supervisor cycle failed: %s", exc)
            time.sleep(max(30, interval_seconds))

    _thread = threading.Thread(target=_loop, name="automation-supervisor", daemon=True)
    _thread.start()
    logger.info("Automation supervisor started (every %s sec)", interval_seconds)
    return {"ok": True, "interval_seconds": interval_seconds}


def stop_automation_supervisor() -> dict[str, Any]:
    global _running
    _running = False
    return {"ok": True}
