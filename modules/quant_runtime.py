"""Single scheduler for Quant v3, with restart catch-up and bounded jobs."""
from __future__ import annotations

import datetime as dt
import logging

from modules.quant_store import Store
from modules.quant_time import now_ist

LOG = logging.getLogger(__name__)


def run_once(notify=False, now=None):
    # Covers manual/cloud catch-up as well as the local scheduler.
    store = Store()
    with store.lease("runtime", 1800) as acquired:
        if not acquired:
            return {"status": "busy"}
        return _run_once(store, notify=notify, now=now)


def _run_once(store, notify=False, now=None):
    from config import QUANT_WATCHLIST_TIME, QUANT_EXIT_TIME
    from modules.quant_engine import prepare, cycle, learn, reconcile
    from modules.scanner import is_market_holiday
    now = now or now_ist()
    if now.weekday() >= 5 or is_market_holiday(now.date()):
        store.put("runtime", {"status": "non_trading_day", "date": str(now.date()), "updated_at": now.isoformat()})
        return {"status": "non_trading_day"}
    watch_time = dt.time.fromisoformat(QUANT_WATCHLIST_TIME)
    if now.time() < watch_time:
        result = {"status": "waiting_for_watchlist", "at": QUANT_WATCHLIST_TIME,
                  "date": str(now.date()), "updated_at": now.isoformat()}
        store.put("runtime", result)
        return result
    watch = store.get("watchlist", {})
    if watch.get("date") != str(now.date()):
        prepare(store, now=now)
    if now.time() <= dt.time(15, 30):
        return cycle(store, now=now, notify=notify)
    if store.get("last_learning_date") != str(now.date()):
        # Get the day's closing bars before resolving outcomes and retraining.
        from modules.quant_data import DataService
        symbols = list(dict.fromkeys([r["symbol"] for r in store.get("watchlist", {}).get("candidates", [])]
                                    + [r["symbol"] for r in store.signals(str(now.date()))]))
        service = DataService(store)
        # Backfill is resumable and bounded. With no Angel credentials it records
        # not_configured immediately and Yahoo continuity remains available.
        service.backfill(symbols, budget=300)
        service.refresh(symbols, budget=90, force=True)
        reconcile(store, now)
        try:
            from modules.winner_discovery import analyze_session_winners
            analyze_session_winners(store, date=str(now.date()))
        except Exception as exc:
            LOG.warning("Post-market winner discovery error: %s", exc)
        result = learn(store)
        # Qualitative review is post-market only. It cannot influence the current
        # session, candidate selection, or parameter values.
        try:
            from modules.quant_daily_review import run_daily_review
            result["qualitative_review"] = run_daily_review(store, result.get("learning"), now=now)
        except Exception as exc:
            result["qualitative_review"] = {"ok": False, "reason": type(exc).__name__}
        if notify:
            send_daily_report(store)
        return result
    if notify:
        send_daily_report(store)
    result = {"status": "post_market_complete", "date": str(now.date()), "updated_at": now.isoformat()}
    store.put("runtime", result)
    return result


def send_daily_report(store):
    import json
    from modules.alerts import send_raw_alert
    from config import DRY_RUN
    date = str(now_ist().date())
    if DRY_RUN or store.get("daily_report_sent") == date:
        return
    with store.connect() as c:
        rows = c.execute("SELECT t.value FROM signals s LEFT JOIN outcomes t ON s.id=t.observation_id WHERE s.date=?", (date,)).fetchall()
    outcomes = [json.loads(r[0]) if r[0] else {} for r in rows]
    filled = [r for r in outcomes if r.get("resolved") and r.get("return_pct") is not None]
    unresolved = sum(not r.get("resolved") for r in outcomes)
    text = (f"<b>Quant V3 — Daily paper results</b>\n{date}\n"
            f"Signals: {len(rows)} | Closed fills: {len(filled)} | Unresolved: {unresolved}\n"
            f"Reached +7%: {sum(r['hit7'] for r in filled)} | +10%: {sum(r['hit10'] for r in filled)}\n")
    if filled:
        text += f"Mean modeled net return: {sum(r['return_pct'] for r in filled)/len(filled):+.2f}%\n"
    else:
        text += "No measured return today.\n"
    text += "<i>Simulated fills and costs. No trades placed.</i>"
    if send_raw_alert(text, review_with_grok=False, event_type="quant_daily_report"):
        store.put("daily_report_sent", date)


def run():
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.events import EVENT_JOB_ERROR
    scheduler = BlockingScheduler(timezone="Asia/Kolkata", job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120})
    def tick():
        result = run_once(notify=True)
        LOG.info("Quant cycle: %s", result.get("status"))
    def failed(event):
        LOG.error("Quant job failed: %s", type(event.exception).__name__)
        Store().put("runtime", {"status": "job_failed", "error_type": type(event.exception).__name__,
                                "updated_at": now_ist().isoformat()})
    scheduler.add_listener(failed, EVENT_JOB_ERROR)
    scheduler.add_job(tick, "interval", seconds=60, id="quant_v3", next_run_time=now_ist())
    LOG.info("Quant v3 ready: watchlist 08:45; paper signals 09:30–11:00; free/existing data only")
    scheduler.start()
