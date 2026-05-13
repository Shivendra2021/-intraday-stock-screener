# MarketMind Pro — Research Only

"""
main.py — MarketMind Pro v2.0 Dual-Session System

SESSION 1 (Morning Pipeline):
  08:00-08:40 → Universe scan → 20 stocks
  08:40-08:55 → Deep research → 5 draft  
  08:55-09:10 → Dual-brain debate → lock picks
  09:10 → Send to Telegram

SESSION 2 (Continuous Learning - ALWAYS RUNNING):
  - Continuous NSE universe scan
  - News analysis
  - FII/DII flow tracking
  - Pattern discovery
  - Data insights

ONE COMMAND SYSTEM controls everything.
"""

import logging
import datetime
import json
import os
import sys

from dotenv import load_dotenv

from modules.time_utils import now_ist, today_ist, today_ist_str

load_dotenv()

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logger = logging.getLogger("main")

_daily_picks: list[dict] = []
_runtime_lock = None


def _is_trading_day() -> bool:
    try:
        from modules.scanner import is_market_holiday, is_weekend
        today = today_ist()
        return not (is_weekend(today) or is_market_holiday(today))
    except Exception:
        return today_ist().weekday() < 5


def _append_decision_log(stage: str, payload: dict) -> None:
    """Append structured morning-pipeline decisions for audit/debugging."""
    import json

    os.makedirs("data", exist_ok=True)
    record = {
        "timestamp": now_ist().isoformat(timespec="seconds"),
        "stage": stage,
        **payload,
    }
    try:
        with open("data/morning_decisions.jsonl", "a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        logger.warning("Failed to write decision log for %s: %s", stage, exc)


def _today_pick_count() -> int:
    """Return today's stored pick count from SQLite, if the DB is available."""
    try:
        import sqlite3
        from config import DB_PATH
        from modules.db_migrations import ensure_research_tables

        ensure_research_tables()
        today = today_ist_str()
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute("SELECT COUNT(*) FROM picks WHERE date=?", (today,)).fetchone()
        finally:
            conn.close()
        return int(row[0] or 0) if row else 0
    except Exception as exc:
        logger.debug("Could not read today's pick count: %s", exc)
        return 0


def _morning_decision_logged_today() -> bool:
    """Return True if today's morning pipeline already logged final picks."""
    import json

    today = today_ist_str()
    path = os.path.join("data", "morning_decisions.jsonl")
    if not os.path.exists(path):
        return False

    try:
        with open(path, "r", encoding="utf-8") as fp:
            for line in fp:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    str(record.get("timestamp", "")).startswith(today)
                    and record.get("stage") == "final_picks"
                    and int(record.get("final_count") or 0) > 0
                ):
                    return True
    except Exception as exc:
        logger.debug("Could not inspect morning decision log: %s", exc)

    return False


def _morning_already_done_today() -> bool:
    """Check both durable places used by the morning flow."""
    return _today_pick_count() > 0 or _morning_decision_logged_today()


def _telegram_event_success_today(event_type: str) -> bool:
    today = today_ist_str()
    path = os.path.join("data", "telegram_delivery.jsonl")
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fp:
            for line in fp:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    record.get("date") == today
                    and record.get("event_type") == event_type
                    and bool(record.get("ok"))
                ):
                    return True
    except Exception as exc:
        logger.debug("Could not inspect Telegram delivery log: %s", exc)
    return False


def _load_todays_picks() -> list[dict]:
    try:
        from modules.picker import get_todays_picks

        return get_todays_picks()
    except Exception as exc:
        logger.debug("Could not load today's picks: %s", exc)
        return []


def _fallback_intraday_candidates(limit: int = 20) -> list[dict]:
    """Use the intraday agent's full-universe scan when the morning scanner returns zero."""
    try:
        from modules.ollama_intraday_agent import scan_full_universe

        result = scan_full_universe()
    except Exception as exc:
        logger.warning("Fallback intraday scan failed: %s", exc)
        return []

    raw_candidates = result.get("top_candidates", []) or []
    if not raw_candidates:
        logger.warning("Fallback intraday scan returned zero candidates: %s", result)
        return []

    candidates: list[dict] = []
    for row in raw_candidates[:limit]:
        price = row.get("close_price") or row.get("open_price") or 0
        try:
            price = float(price)
        except Exception:
            price = 0.0
        if price <= 0:
            continue

        volume_ratio = row.get("volume_ratio", row.get("first_15m_volume_ratio", 1.0))
        candidate = {
            "symbol": str(row.get("symbol", "")).replace(".NS", "").upper(),
            "price": price,
            "score": row.get("score", 0),
            "price_change_pct": row.get("return_pct", 0),
            "daily_change": row.get("return_pct", 0),
            "volume_ratio": volume_ratio,
            "vol_ratio": volume_ratio,
            "gap_up": row.get("gap_pct", 0),
            "rsi": 50,
            "adx": 20,
            "sector": row.get("sector", "UNKNOWN"),
            "fallback_source": "ollama_intraday_agent",
            "signal_reasons": "fallback_intraday_scan",
            "open_to_high_pct": row.get("open_to_high_pct", 0),
            "first_15m_return_pct": row.get("first_15m_return_pct", 0),
            "first_15m_volume_ratio": row.get("first_15m_volume_ratio", 0),
        }
        if candidate["symbol"]:
            candidates.append(candidate)

    logger.info(
        "Fallback intraday scan produced %s candidates from %s scanned symbols",
        len(candidates),
        result.get("symbols_scanned", 0),
    )
    return candidates


# ============================================================================
# Morning Pipeline (Session 1)
# ============================================================================

def run_morning_session():
    """Run morning session (08:00-09:10)."""
    global _daily_picks
    
    if not _is_trading_day():
        logger.info("Not a trading day, skipping")
        return
    
    logger.info("=== MORNING SESSION STARTED ===")
    
    # Get learned context from continuous learning
    from modules.continuous_learning import get_morning_context
    context = get_morning_context()
    
    logger.info(f"Morning context: {context.get('insights_summary', {})}")
    
    # Stage 1: Universe scan (08:00-08:40)
    from modules.universe_scanner import get_last_scan_diagnostics, scan_universe_parallel
    candidates = scan_universe_parallel(top_n=20)
    
    if not candidates:
        logger.warning("Universe scan empty")
        diagnostics = get_last_scan_diagnostics()
        _append_decision_log("universe_scan_empty", {
            "diagnostics": diagnostics,
        })
        candidates = _fallback_intraday_candidates(limit=20)

    if not candidates:
        logger.warning("Fallback scan empty")
        try:
            from modules.alerts import send_no_picks
            send_no_picks(
                "Morning scanner and fallback intraday scanner returned zero candidates",
                diagnostics=get_last_scan_diagnostics(),
            )
        except Exception:
            pass
        return
    try:
        from modules.market_terminal import rank_candidates
        candidates = rank_candidates(candidates, limit=20)
    except Exception as exc:
        logger.debug("Terminal ranking skipped for candidates: %s", exc)
    
    logger.info(f"Universe scan: {len(candidates)} candidates")
    _append_decision_log("universe_scan", {
        "candidate_count": len(candidates),
        "candidates": candidates,
    })
    
    # Stage 2: Deep research (08:40-08:55)
    from modules.stock_selector import deep_research_stocks
    draft = deep_research_stocks(candidates, n=5)
    
    if not draft:
        draft = candidates[:5]
    try:
        from modules.market_terminal import rank_candidates
        draft = rank_candidates(draft, limit=5)
    except Exception as exc:
        logger.debug("Terminal ranking skipped for draft picks: %s", exc)
    
    logger.info(f"Deep research: {len(draft)} draft picks")
    _append_decision_log("deep_research", {
        "draft_count": len(draft),
        "draft_picks": draft,
    })
    
    # Stage 3: Dual-brain debate (08:55-09:10)
    from modules.dual_brain import debate_picks
    ctx_str = f"Sectors: {set(s.get('sector') for s in draft)}, learned: {context}"
    final, agreed = debate_picks(draft, ctx_str)
    if not final:
        final = draft[:5]
    elif len(final) < 5:
        existing = {p.get("symbol") for p in final}
        final.extend([p for p in draft if p.get("symbol") not in existing][: 5 - len(final)])
    try:
        from modules.market_terminal import rank_candidates
        final = rank_candidates(final, limit=5)
        for i, pick in enumerate(final, start=1):
            pick["rank"] = i
            pick["score"] = pick.get("terminal_score", pick.get("score", 0))
    except Exception as exc:
        logger.debug("Terminal ranking skipped for final picks: %s", exc)
    
    _daily_picks = final
    
    logger.info(f"Dual-brain debate: {len(final)} picks, both_agreed={agreed}")
    _append_decision_log("final_picks", {
        "final_count": len(final),
        "both_agreed": agreed,
        "final_picks": final,
    })

    try:
        from modules.picker import _write_picks_to_db

        _write_picks_to_db(final)
    except Exception as exc:
        logger.error("Failed to persist final picks before Telegram send: %s", exc)
    
    # Send to Telegram (09:10)
    sent = _send_telegram(final, agreed)
    if not sent:
        logger.error("Morning final picks were generated but Telegram delivery failed")
    
    # Initialize tracking
    try:
        from modules.stock_tracker import init_tracking
        init_tracking(final)
    except Exception as e:
        logger.debug(f"Tracking init: {e}")
    
    logger.info("=== MORNING SESSION COMPLETE ===")


def _send_telegram(picks: list[dict], agreed: bool) -> bool:
    """Send final picks to Telegram."""
    try:
        from modules.alerts import send_morning_final_picks, send_raw_alert
        from modules.grok_brain import get_brain_status
        
        brain_status = get_brain_status()
        
        header = (
            f"📈 <b>MARKETMIND PRO v2.0 — FINAL PICKS</b>\n"
            f"📅 {now_ist().strftime('%d %b %Y, %H:%M IST')}\n\n"
            f"🤖 <b>Dual-Brain:</b> {'✅ Both Agreed' if agreed else '⚠️ Modified'}\n"
            f"🧠 Model: {brain_status.get('grok_model', 'N/A')}"
        )
        
        header_ok = send_raw_alert(header, review_with_grok=False)
        picks_ok = send_morning_final_picks(picks, None, review_with_grok=False)
        
        ok = bool(header_ok and picks_ok)
        if not ok and picks:
            compact = ["<b>MARKETMIND PRO - FINAL TOP 5 PICKS</b>"]
            for pick in picks[:5]:
                compact.append(
                    f"{pick.get('rank', '')}. <b>{pick.get('symbol')}</b> "
                    f"Entry {float(pick.get('entry_price') or pick.get('price') or 0):.2f} | "
                    f"SL {float(pick.get('sl_price') or 0):.2f} | "
                    f"TP {float(pick.get('target_price') or 0):.2f}"
                )
            compact.append("<i>Research only. Not a trade recommendation.</i>")
            ok = send_raw_alert("\n".join(compact), review_with_grok=False)

        logger.info("Sent %s picks to Telegram: %s", len(picks), ok)
        return ok
    except Exception as e:
        logger.error(f"Telegram send: {e}")
        return False


# ============================================================================
# Intraday Jobs
# ============================================================================

def job_find_winners():
    """Find 7%+ intraday winners."""
    if not _is_trading_day():
        return
    
    logger.info("=== JOB: Find Winners ===")
    
    try:
        from modules.winner_finder import find_winners
        from modules.alerts import send_raw_alert
        
        winners = find_winners(7.0)
        
        if winners:
            lines = [f"📈 <b>INTRADAY WINNERS ({len(winners)})</b>\n"]
            for w in winners[:10]:
                lines.append(f"• {w['symbol']}: +{w['return_pct']:.1f}% Vol:{w['volume_ratio']:.1f}x")
            
            send_raw_alert("\n".join(lines))
            
            # Run pattern learning
            from modules.pattern_learner import run_self_learning
            run_self_learning()
    except Exception as e:
        logger.error(f"Winner finder: {e}")


def job_after_market_learning():
    """Post-close loop: learn similarities from 7%+ intraday winners."""
    if not _is_trading_day():
        return

    logger.info("=== JOB: After-Market 7% Winner Learning ===")
    try:
        from config import INTRADAY_MIN_RETURN_PCT
        from modules.after_market_learning import run_after_market_learning
        from modules.alerts import send_raw_alert

        result = run_after_market_learning(min_return_pct=INTRADAY_MIN_RETURN_PCT)
        lines = [
            "🧠 <b>AFTER-MARKET LEARNING COMPLETE</b>",
            f"Winners ≥{INTRADAY_MIN_RETURN_PCT:.1f}%: {result.get('winner_count', 0)}",
            f"Patterns learned: {result.get('pattern_count', 0)}",
        ]
        for p in result.get("patterns", [])[:5]:
            lines.append(f"• {p.get('pattern_key')}: conf {p.get('confidence', 0):.0%}, avg {p.get('avg_return_pct', 0):.1f}%")
        lines.append("\n<i>Research only. Learned similarities feed the next scan.</i>")
        send_raw_alert("\n".join(lines))
    except Exception as e:
        logger.error("After-market learning failed: %s", e)


def job_pattern_learning():
    """Pattern learning."""
    if not _is_trading_day():
        return
    
    logger.info("=== JOB: Pattern Learning ===")
    
    try:
        from modules.pattern_learner import run_self_learning
        run_self_learning()
    except Exception as e:
        logger.debug(f"Pattern learning: {e}")


def job_health_check():
    """Health check."""
    if not _is_trading_day():
        return
    
    logger.info("=== JOB: Health Check ===")
    
    try:
        from modules.morning_analysis import get_system_health
        from modules.alerts import send_morning_health_check
        
        health = get_system_health()
        send_morning_health_check(health)
    except Exception as e:
        logger.debug(f"Health check: {e}")


def job_morning_delivery_guard():
    """Guarantee that generated morning top-5 picks reach Telegram."""
    if not _is_trading_day():
        return

    logger.info("=== JOB: Morning Delivery Guard ===")
    try:
        if _telegram_event_success_today("morning_final_picks"):
            logger.info("Morning delivery guard: Telegram already delivered")
            return

        picks = _load_todays_picks()
        if picks:
            logger.warning("Morning delivery guard: resending %s stored picks", len(picks))
            _send_telegram(picks, agreed=False)
            return

        now = datetime.datetime.now().time()
        from config import MORNING_CATCHUP_END

        catchup_end = datetime.time(*[int(x) for x in MORNING_CATCHUP_END.split(":", 1)])
        if now <= catchup_end:
            logger.warning("Morning delivery guard: no picks found; running catch-up morning session")
            run_morning_session()
        else:
            from modules.alerts import send_raw_alert

            send_raw_alert(
                "<b>MORNING PICKS DELIVERY WARNING</b>\n"
                "No stored top-5 picks found after the catch-up window. Check scanner/provider logs.",
                review_with_grok=False,
            )
    except Exception as e:
        logger.error("Morning delivery guard failed: %s", e)


def job_preclose():
    """Preclose scan."""
    if not _is_trading_day():
        return
    
    try:
        from modules.preclose_watchlist import run_preclose_scan
        from modules.alerts import send_preclose_alert
        
        results = run_preclose_scan()
        if results:
            send_preclose_alert(results)
    except Exception as e:
        logger.debug(f"Preclose: {e}")


def job_tracking_update():
    """Update active pick tracking and send TP/SL alerts."""
    if not _is_trading_day():
        return
    try:
        from modules.stock_tracker import update_tracking

        update_tracking()
    except Exception as e:
        logger.debug("Tracking update: %s", e)


def job_tracking_status():
    """Send periodic active-pick status during market hours."""
    if not _is_trading_day():
        return
    try:
        from modules.stock_tracker import send_hourly_status

        send_hourly_status()
    except Exception as e:
        logger.debug("Tracking status: %s", e)


def job_tracking_eod():
    """Close pick tracking at EOD and send report."""
    if not _is_trading_day():
        return
    try:
        from modules.stock_tracker import close_and_report_eod

        close_and_report_eod()
    except Exception as e:
        logger.debug("Tracking EOD: %s", e)


def job_heartbeat():
    """Daily heartbeat."""
    logger.info("=== JOB: Heartbeat ===")
    
    try:
        from modules.alerts import send_raw_alert
        
        send_raw_alert(
            f"💓 <b>MarketMind Pro v2.0</b>\n"
            f"⏰ {now_ist().strftime('%d %b %Y, %H:%M IST')}\n"
            f"✅ System Active"
        )
    except Exception as e:
        logger.error(f"Heartbeat: {e}")


# ============================================================================
# Main
# ============================================================================

def main():
    global _runtime_lock
    from modules.runtime_guard import acquire_single_instance

    _runtime_lock = acquire_single_instance("marketmind-main")
    if _runtime_lock is None:
        logger.error("Another MarketMind main.py process is already running; exiting duplicate instance")
        return

    logger.info("Startup path: executable=%s cwd=%s", sys.executable, os.getcwd())

    # Start continuous learning (Session 2) in background
    from modules.continuous_learning import start_continuous_learning
    
    logger.info("Starting continuous learning...")
    start_continuous_learning(interval_minutes=30, run_immediate=False)

    try:
        from config import INTRADAY_PATTERN_AGENT_ENABLED, INTRADAY_PATTERN_SCAN_INTERVAL_MINUTES
        if INTRADAY_PATTERN_AGENT_ENABLED:
            from modules.intraday_pattern_agent import start_intraday_pattern_agent

            start_intraday_pattern_agent(interval_minutes=INTRADAY_PATTERN_SCAN_INTERVAL_MINUTES)
    except Exception as exc:
        logger.error("Intraday pattern agent failed to start: %s", exc)

    try:
        from config import GROK_DASHBOARD_AGENT_ENABLED, GROK_DASHBOARD_AGENT_INTERVAL_MINUTES
        if GROK_DASHBOARD_AGENT_ENABLED:
            from modules.grok_dashboard_agent import start_grok_dashboard_agent

            start_grok_dashboard_agent(interval_minutes=GROK_DASHBOARD_AGENT_INTERVAL_MINUTES)
    except Exception as exc:
        logger.error("Grok dashboard agent failed to start: %s", exc)

    try:
        from config import OLLAMA_AGENT_ENABLED, OLLAMA_AGENT_INTERVAL_MINUTES
        if OLLAMA_AGENT_ENABLED:
            from modules.ollama_intraday_agent import start_ollama_intraday_agent

            start_ollama_intraday_agent(interval_minutes=OLLAMA_AGENT_INTERVAL_MINUTES)
    except Exception as exc:
        logger.error("Ollama intraday agent failed to start: %s", exc)
    
    # Create scheduler for timed jobs
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
    
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")
    
    def _job_listener(event) -> None:
        if event.exception:
            logger.error("JOB FAILED [%s]: %s", event.job_id, event.exception)
            try:
                import traceback
                from modules.self_healing import diagnose_and_heal
                tb_str = "".join(traceback.format_exception(type(event.exception), event.exception, event.exception.__traceback__))
                diagnose_and_heal(tb_str, job_name=event.job_id)
            except Exception as e:
                logger.error("Failed to trigger self-healing: %s", e)
    
    scheduler.add_listener(_job_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
    
    from config import (
        AFTER_MARKET_LEARNING_TIME, LEARNER_START, MARKET_LEARNER_START, MORNING_CATCHUP_END,
        MORNING_FINAL_PICKS, MORNING_UNIVERSE_SCAN_START, PRECLOSE_SCAN_TIME,
        STARTUP_ANALYSIS_ON_LAUNCH,
    )

    def _parse_hhmm(value: str) -> tuple[int, int]:
        hour, minute = value.split(":", 1)
        return int(hour), int(minute)

    def _add_cron(job, time_value: str, job_id: str, misfire_grace_time: int | None = None) -> None:
        hour, minute = _parse_hhmm(time_value)
        kwargs = {"hour": hour, "minute": minute, "id": job_id}
        if misfire_grace_time is not None:
            kwargs["misfire_grace_time"] = misfire_grace_time
        scheduler.add_job(job, "cron", **kwargs)

    # Morning session
    _add_cron(run_morning_session, MORNING_FINAL_PICKS, "morning", misfire_grace_time=5400)
    _add_cron(job_morning_delivery_guard, "09:25", "morning_delivery_guard_0925", misfire_grace_time=3600)
    _add_cron(job_morning_delivery_guard, "10:00", "morning_delivery_guard_1000", misfire_grace_time=3600)
    
    # Intraday
    _add_cron(job_health_check, "08:00", "health")
    _add_cron(job_preclose, PRECLOSE_SCAN_TIME, "preclose")
    _add_cron(job_find_winners, MARKET_LEARNER_START, "winners")
    _add_cron(job_after_market_learning, AFTER_MARKET_LEARNING_TIME, "after_market_learning")
    _add_cron(job_pattern_learning, LEARNER_START, "learning")
    scheduler.add_job(job_tracking_update, "cron", hour="9-15", minute="*/5", id="tracking_update")
    scheduler.add_job(job_tracking_status, "cron", hour="10-14", minute=0, id="tracking_status")
    scheduler.add_job(job_tracking_eod, "cron", hour=15, minute=31, id="tracking_eod")
    
    # Daily
    _add_cron(job_heartbeat, "18:00", "heartbeat")
    
    # Banner
    print("\n" + "#" * 60)
    print("  MarketMind Pro v2.0 — Dual-Session System")
    print("  Session 1: Morning Pipeline (08:00-09:10)")
    print("  Session 2: Continuous Learning (ALWAYS RUNNING)")
    print("#" * 60 + "\n")
    
    # Run or catch up the morning session on startup. This covers Windows booting
    # after the 09:10 scheduled job, while avoiding stale afternoon picks.
    if STARTUP_ANALYSIS_ON_LAUNCH:
        if not _is_trading_day():
            logger.info("Startup morning check: not a trading day, skipping")
        else:
            now = datetime.datetime.now().time()
            start = datetime.time(*_parse_hhmm(MORNING_UNIVERSE_SCAN_START))
            scheduled = datetime.time(*_parse_hhmm(MORNING_FINAL_PICKS))
            catchup_end = datetime.time(*_parse_hhmm(MORNING_CATCHUP_END))
            already_done = _morning_already_done_today()

            if already_done:
                logger.info("Startup morning check: today's picks already exist, skipping")
                if not _telegram_event_success_today("morning_final_picks"):
                    picks = _load_todays_picks() or _daily_picks
                    if picks:
                        logger.warning("Startup morning check: picks exist but Telegram delivery is not audited; resending")
                        _send_telegram(picks, agreed=False)
            elif start <= now <= catchup_end:
                if now > scheduled:
                    logger.warning(
                        "Morning job was missed; running startup catch-up now (scheduled %s, catch-up until %s)",
                        MORNING_FINAL_PICKS,
                        MORNING_CATCHUP_END,
                    )
                else:
                    logger.info("Running morning session on startup...")
                run_morning_session()
            elif now < start:
                logger.info("Startup morning check: before morning window; scheduler will run at %s", MORNING_FINAL_PICKS)
            else:
                logger.warning(
                    "Startup morning check: missed catch-up window (%s-%s) and no picks found; "
                    "not sending stale morning picks",
                    MORNING_UNIVERSE_SCAN_START,
                    MORNING_CATCHUP_END,
                )
    
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped")
        print("\n  MarketMind Pro stopped.\n")


if __name__ == "__main__":
    main()
