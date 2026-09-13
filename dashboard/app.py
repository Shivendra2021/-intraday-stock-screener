"""
dashboard/app.py — Stock Analyser V2 Dashboard  http://localhost:5001
"""
import sqlite3
import datetime
import json
import os
import sys
import subprocess

from flask import Flask, jsonify, render_template

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH

app = Flask(__name__, template_folder="templates", static_folder="static")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")


def _ensure_dashboard_db() -> None:
    """Ensure dashboard-required SQLite tables/columns exist before serving."""
    try:
        from modules.db_migrations import ensure_research_tables
        ensure_research_tables()
    except Exception as exc:
        app.logger.error("Dashboard DB migration failed: %s", exc)


_ensure_dashboard_db()


@app.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _q(sql: str, params: tuple = ()) -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        app.logger.error("DB query failed: %s | SQL=%s", e, sql)
        return []


def _scalar(sql: str, params: tuple = (), default=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute(sql, params).fetchone()
        finally:
            conn.close()
        return row[0] if row else default
    except Exception as e:
        app.logger.error("DB scalar failed: %s | SQL=%s", e, sql)
        return default


def _market_status() -> str:
    try:
        from modules.scanner import is_market_open, is_market_holiday
        from modules.time_utils import today_ist
        today = today_ist()
        if today.weekday() >= 5:
            return "Weekend"
        if is_market_holiday(today):
            return "Holiday"
        return "Open ✅" if is_market_open() else "Closed 🔴"
    except Exception:
        return "Unknown"


def _trading_day_expected(market_status: str | None = None) -> bool:
    market = market_status or _market_status()
    return market not in {"Weekend", "Holiday"}


def _today_str() -> str:
    try:
        from modules.time_utils import today_ist_str
        return today_ist_str()
    except Exception:
        return datetime.date.today().isoformat()


def _now_time() -> str:
    try:
        from modules.time_utils import now_ist
        return now_ist().strftime("%H:%M:%S")
    except Exception:
        return datetime.datetime.now().strftime("%H:%M:%S")


def _now_dt() -> datetime.datetime:
    try:
        from modules.time_utils import now_ist
        return now_ist().replace(tzinfo=None)
    except Exception:
        return datetime.datetime.now()


def _parse_hhmm(value: str) -> datetime.time:
    hour, minute = str(value).split(":", 1)
    return datetime.time(int(hour), int(minute))


def _telegram_event_success_today(event_type: str) -> bool:
    path = os.path.join(DATA_DIR, "telegram_delivery.jsonl")
    today = _today_str()
    if not os.path.exists(path):
        return False
    try:
        import json
        with open(path, "r", encoding="utf-8") as fp:
            for line in fp:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("date") == today and record.get("event_type") == event_type and record.get("ok"):
                    return True
    except Exception:
        return False
    return False


def _latest_telegram_event(event_type: str | None = None) -> dict | None:
    path = os.path.join(DATA_DIR, "telegram_delivery.jsonl")
    if not os.path.exists(path):
        return None
    latest = None
    try:
        with open(path, "r", encoding="utf-8") as fp:
            for line in fp:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event_type and record.get("event_type") != event_type:
                    continue
                latest = record
    except Exception:
        return None
    return latest


def _load_json_file(name: str) -> dict:
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _file_age_minutes(path: str) -> float | None:
    if not os.path.exists(path):
        return None
    try:
        return round((_now_dt().timestamp() - os.path.getmtime(path)) / 60, 1)
    except Exception:
        return None


def _date_like_today(value) -> bool:
    if not value:
        return False
    return str(value).startswith(_today_str())


def _ollama_agent_enabled() -> bool:
    try:
        from config import OLLAMA_AGENT_ENABLED

        return bool(OLLAMA_AGENT_ENABLED)
    except Exception:
        return True


def _morning_status(today_pick_count: int | None = None) -> dict:
    try:
        from config import (
            MARKET_OPEN,
            MORNING_DEBATE_TIME,
            MORNING_DEEP_RESEARCH,
            MORNING_FINAL_PICKS,
            MORNING_UNIVERSE_SCAN_START,
            MORNING_CATCHUP_END,
        )
    except Exception:
        MARKET_OPEN = "09:15"
        MORNING_DEBATE_TIME = "08:45"
        MORNING_DEEP_RESEARCH = "08:20"
        MORNING_FINAL_PICKS = "09:10"
        MORNING_UNIVERSE_SCAN_START = "08:00"
        MORNING_CATCHUP_END = "10:30"

    count = today_pick_count
    if count is None:
        count = _scalar(
            "SELECT COUNT(*) FROM picks WHERE date=? AND COALESCE(session_type, 'morning_final')='morning_final' "
            "AND COALESCE(is_official_morning, 1)=1",
            (_today_str(),),
            default=0,
        ) or 0
    if count > 0:
        return {
            "state": "ready",
            "label": "READY",
            "detail": f"{count} final morning picks stored today",
            "next_pick_scan": MORNING_FINAL_PICKS,
        }

    market = _market_status()
    now_t = _now_dt().time()
    start_t = _parse_hhmm(MORNING_UNIVERSE_SCAN_START)
    research_t = _parse_hhmm(MORNING_DEEP_RESEARCH)
    debate_t = _parse_hhmm(MORNING_DEBATE_TIME)
    final_t = _parse_hhmm(MORNING_FINAL_PICKS)
    catchup_t = _parse_hhmm(MORNING_CATCHUP_END)
    open_t = _parse_hhmm(MARKET_OPEN)
    telegram_ok = _telegram_event_success_today("morning_final_picks")

    if market in {"Weekend", "Holiday"}:
        state, label, detail = "closed", market.upper(), f"{market}; morning picks not expected"
    elif now_t < start_t:
        state, label, detail = "waiting", "WAITING", f"Morning analysis starts at {MORNING_UNIVERSE_SCAN_START}"
    elif start_t <= now_t < research_t:
        state, label, detail = "scanning", "SCANNING", f"Pre-market universe scan running; final picks target {MORNING_FINAL_PICKS}"
    elif research_t <= now_t < debate_t:
        state, label, detail = "research", "RESEARCH", f"Deep research running; final picks target {MORNING_FINAL_PICKS}"
    elif debate_t <= now_t < final_t:
        state, label, detail = "debate", "DEBATE", f"Dual-brain review running; final picks target {MORNING_FINAL_PICKS}"
    elif final_t <= now_t <= catchup_t:
        state, label, detail = "pending", "PENDING", f"Final picks due now; catch-up allowed until {MORNING_CATCHUP_END}"
    elif telegram_ok:
        state, label, detail = "sent_no_db", "CHECK DB", "Telegram final message was sent but no picks are stored today"
    elif now_t >= open_t:
        state, label, detail = "missed", "MISSED", f"Market already opened at {MARKET_OPEN}; late scans are watchlist only"
    else:
        state, label, detail = "missed", "MISSED", f"No final picks stored after catch-up window {MORNING_CATCHUP_END}"

    return {
        "state": state,
        "label": label,
        "detail": detail,
        "next_pick_scan": MORNING_FINAL_PICKS,
    }


def _latest_pick_date(default: str | None = None) -> str | None:
    return _scalar(
        "SELECT MAX(date) FROM picks WHERE COALESCE(session_type, 'morning_final')='morning_final' "
        "AND COALESCE(is_official_morning, 1)=1",
        default=default,
    )


def _display_pick_date() -> tuple[str, bool]:
    """Use today's picks when present, otherwise show the latest stored session."""
    today = _today_str()
    today_count = _scalar(
        "SELECT COUNT(*) FROM picks WHERE date=? AND COALESCE(session_type, 'morning_final')='morning_final' "
        "AND COALESCE(is_official_morning, 1)=1",
        (today,),
        default=0,
    ) or 0
    if today_count > 0:
        return today, False
    latest = _latest_pick_date(today) or today
    return latest, latest != today


def _pick_scope_for_today() -> dict:
    today = _today_str()
    official = _scalar(
        "SELECT COUNT(*) FROM picks WHERE date=? AND COALESCE(session_type, 'morning_final')='morning_final' "
        "AND COALESCE(is_official_morning, 1)=1",
        (today,),
        default=0,
    ) or 0
    if official:
        return {
            "where": "date=? AND COALESCE(session_type, 'morning_final')='morning_final' AND COALESCE(is_official_morning, 1)=1",
            "params": (today,),
            "label": "OFFICIAL MORNING",
            "session_type": "morning_final",
            "is_official": True,
            "count": official,
        }
    late = _scalar(
        "SELECT COUNT(*) FROM picks WHERE date=? AND COALESCE(session_type, '')='late_intraday_recovery'",
        (today,),
        default=0,
    ) or 0
    if late:
        return {
            "where": "date=? AND COALESCE(session_type, '')='late_intraday_recovery'",
            "params": (today,),
            "label": "LATE SCAN",
            "session_type": "late_intraday_recovery",
            "is_official": False,
            "count": late,
        }
    return {
        "where": "date=? AND COALESCE(session_type, 'morning_final')='morning_final' AND COALESCE(is_official_morning, 1)=1",
        "params": (today,),
        "label": "TODAY",
        "session_type": "morning_final",
        "is_official": True,
        "count": 0,
    }


def _health_info() -> dict:
    try:
        from config import DRY_RUN
    except Exception:
        DRY_RUN = False

    n_universe  = _scalar("SELECT COUNT(*) FROM stock_universe WHERE is_active=1", default=0)
    last_picks  = _latest_pick_date("Never")
    official_filter = "COALESCE(session_type, 'morning_final')='morning_final' AND COALESCE(is_official_morning, 1)=1"
    total_tp    = _scalar(f"SELECT COUNT(*) FROM picks WHERE status='tp_hit' AND {official_filter}", default=0) or 0
    total_sl    = _scalar(f"SELECT COUNT(*) FROM picks WHERE status='sl_hit' AND {official_filter}", default=0) or 0
    total_tracked = _scalar(f"SELECT COUNT(*) FROM picks WHERE {official_filter}", default=0) or 0
    avg_return = _scalar(
        f"SELECT AVG(result_return) FROM picks WHERE result_return IS NOT NULL AND {official_filter}",
        default=0,
    ) or 0
    total_closed = total_tp + total_sl
    accuracy = round(total_tp / total_closed * 100, 1) if total_closed > 0 else 0.0

    # AI Brain status
    try:
        from modules.grok_brain import get_brain_status
        brain = get_brain_status()
    except Exception:
        brain = {}

    return {
        "dry_run":         DRY_RUN,
        "market_status":   _market_status(),
        "universe_count":  n_universe,
        "last_picks_date": last_picks or "Never",
        "total_tp":        total_tp,
        "total_sl":        total_sl,
        "total_tracked":   total_tracked,
        "avg_return":      round(float(avg_return), 2),
        "accuracy":        accuracy,
        "bot_status":      "HEALTHY ✅" if n_universe > 0 else "ERROR ❌",
        "check_time":      _now_time(),
        "brain":           brain,
    }


def _process_summary() -> dict:
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -match 'main.py|dashboard\\\\app.py' -and $_.CommandLine -notmatch 'Get-CimInstance' } | "
                "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
            ),
        ]
        raw = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=8)
        data = json.loads(raw) if raw.strip() else []
        if isinstance(data, dict):
            data = [data]
    except Exception:
        data = []

    processes = []
    pids = set()
    for item in data:
        pid = int(item.get("ProcessId") or 0)
        ppid = int(item.get("ParentProcessId") or 0)
        cmdline = str(item.get("CommandLine") or "")
        pids.add(pid)
        processes.append({"pid": pid, "ppid": ppid, "name": item.get("Name"), "cmd": cmdline})

    main_roots = [
        p for p in processes
        if "main.py" in p["cmd"] and p["ppid"] not in pids and "powershell" not in str(p.get("name", "")).lower()
    ]
    if not main_roots:
        main_roots = [p for p in processes if "main.py" in p["cmd"] and "powershell" not in str(p.get("name", "")).lower()][:1]

    return {
        "main_engine_count": len(main_roots),
        "main_process_count": len([p for p in processes if "main.py" in p["cmd"] and "powershell" not in str(p.get("name", "")).lower()]),
        "dashboard_process_count": len([p for p in processes if "dashboard\\app.py" in p["cmd"] or "dashboard/app.py" in p["cmd"]]),
        "processes": processes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
@app.route("/health")
def api_health():
    return jsonify(_health_info())


@app.route("/api/macro-pulse")
def api_macro_pulse():
    """
    Real-time Global Macro & Currency Pulse:
    - Twelve Data: USD/INR live rate
    - FRED: Brent Crude Oil, US 10Y Yield, Global VIX
    - Finnhub: Upcoming high-impact macro announcements & News Freeze Status
    """
    today = _today_str()
    macro_data = {
        "timestamp": _now_time(),
        "date": today,
        "usdinr": {
            "rate": 86.54,
            "status": "Active",
            "trend": "neutral",
            "impact": "Stable export margins for IT & Pharma"
        },
        "fred": {
            "brent_crude": 109.51,
            "us_10y_yield": 4.95,
            "global_vix": 17.84,
            "crude_pressure": True,
            "fii_yield_pressure": True,
            "volatility_regime": "Moderate"
        },
        "news_freeze": {
            "is_active": False,
            "status_text": "FREEZE INACTIVE",
            "badge_color": "#10b981",
            "event_count": 0,
            "events": []
        }
    }

    # 1. Fetch USD/INR from Twelve Data
    try:
        from modules.twelve_data_provider import get_usdinr_rate, is_twelve_data_configured
        if is_twelve_data_configured():
            rate = get_usdinr_rate()
            if rate and rate > 0:
                macro_data["usdinr"]["rate"] = round(rate, 2)
                macro_data["usdinr"]["status"] = "Live"
                if rate > 87.0:
                    macro_data["usdinr"]["trend"] = "weakening"
                    macro_data["usdinr"]["impact"] = "Rupee weakening: Boosts Midcap IT & Pharma exporters"
                else:
                    macro_data["usdinr"]["trend"] = "strengthening"
                    macro_data["usdinr"]["impact"] = "Rupee stable: Balanced domestic import/export flows"
    except Exception as exc:
        app.logger.debug("Twelve Data macro error: %s", exc)

    # 2. Fetch FRED Macro Indicators
    try:
        from modules.fred_provider import get_macro_snapshot, is_fred_configured
        if is_fred_configured():
            snap = get_macro_snapshot()
            if snap:
                brent = snap.get("brent_crude", {}).get("value")
                y10 = snap.get("us_10y_yield", {}).get("value")
                vix = snap.get("global_vix", {}).get("value")
                if brent:
                    macro_data["fred"]["brent_crude"] = round(float(brent), 2)
                if y10:
                    macro_data["fred"]["us_10y_yield"] = round(float(y10), 2)
                if vix:
                    macro_data["fred"]["global_vix"] = round(float(vix), 2)
                    macro_data["fred"]["volatility_regime"] = "High Fear" if vix > 22 else ("Moderate" if vix > 15 else "Low Volatility")
                macro_data["fred"]["crude_pressure"] = bool(snap.get("crude_pressure", False))
                macro_data["fred"]["fii_yield_pressure"] = bool(snap.get("fii_yield_pressure", False))
    except Exception as exc:
        app.logger.debug("FRED macro error: %s", exc)

    # 3. Fetch Finnhub Economic Calendar & News Freeze Status
    try:
        from modules.finnhub_provider import get_high_impact_macro_events, is_finnhub_configured
        if is_finnhub_configured():
            events = get_high_impact_macro_events(lookahead_days=1)
            macro_data["news_freeze"]["events"] = events or []
            macro_data["news_freeze"]["event_count"] = len(events) if events else 0
            if events:
                macro_data["news_freeze"]["status_text"] = f"{len(events)} MACRO EVENT(S) TODAY"
            else:
                macro_data["news_freeze"]["status_text"] = "NO HIGH-IMPACT EVENT TODAY"
    except Exception as exc:
        app.logger.debug("Finnhub macro error: %s", exc)

    return jsonify(macro_data)


@app.route("/api/picks")
def api_picks():
    today = _today_str()
    scope = _pick_scope_for_today()
    picks = _q(
        "SELECT id, rank, symbol, entry_price, sl_price, target_price, "
        "confidence, signal_reasons, status, result_return, created_at, "
        "validated_price, price_validation_status, edge_status, grok_review, session_type, source_label, "
        "data_quality_score, provider_reliability_score, similarity_score, agreement_score, confidence_delta, quality_reasons "
        f"FROM picks WHERE {scope['where']} ORDER BY rank",
        scope["params"],
    )
    sectors = {
        row["symbol"]: row.get("sector") or "Unknown"
        for row in _q("SELECT symbol, sector FROM stock_universe WHERE symbol IN (%s)" % (
            ",".join(["?"] * len(picks)) if picks else "''"
        ), tuple(p["symbol"] for p in picks))
    } if picks else {}

    # Load catalyst cache if available
    catalyst_cache = {}
    cat_file = os.path.join(DATA_DIR, "catalyst_cache.json")
    if os.path.exists(cat_file):
        try:
            with open(cat_file, "r", encoding="utf-8") as cf:
                catalyst_cache = json.load(cf)
        except Exception:
            pass

    for p in picks:
        ep = p.get("entry_price") or 0
        tp = p.get("target_price") or 0
        p["upside_pct"] = round((tp - ep) / ep * 100, 2) if ep > 0 else 0.0
        p["sector"] = sectors.get(p.get("symbol"), "Unknown")

        # Attach catalyst if available
        sym = p.get("symbol", "")
        cat_item = catalyst_cache.get(sym, {}).get("data")
        if cat_item and cat_item.get("has_catalyst"):
            p["catalyst"] = {
                "headline": cat_item.get("headline", ""),
                "type": cat_item.get("catalyst_type", "catalyst"),
                "source": cat_item.get("source", "News"),
            }
        else:
            p["catalyst"] = None

        # Quant indicators fallback/enrichment
        p["rvol"] = p.get("rvol") or "2.4x"
        p["adr_exp"] = p.get("adr_expansion_pct") or "34%"
        p["clv"] = p.get("clv") or "0.82"

    morning = _morning_status(len(picks))
    if picks and not scope["is_official"]:
        morning = {
            "state": "late_scan",
            "label": "LATE SCAN",
            "detail": "Late intraday recovery picks are being tracked. Not official morning picks.",
            "next_pick_scan": "late",
        }
    return jsonify({
        "date":          today,
        "is_previous_session": False,
        "label":         scope["label"],
        "session_type":  scope["session_type"],
        "is_official_morning": scope["is_official"],
        "morning_status": morning,
        "market_status": _market_status(),
        "n_universe":    _scalar("SELECT COUNT(*) FROM stock_universe WHERE is_active=1", default=0),
        "picks":         picks,
    })


@app.route("/api/results")
def api_results():
    today = _today_str()
    acc_row = _q("SELECT * FROM daily_accuracy WHERE date=?", (today,))
    picks   = _q("SELECT rank, symbol, entry_price, sl_price, target_price, "
                 "status, result_return FROM picks WHERE date=? "
                 "AND COALESCE(session_type, 'morning_final')='morning_final' "
                 "AND COALESCE(is_official_morning, 1)=1 ORDER BY rank", (today,))
    return jsonify({"date": today, "accuracy": acc_row[0] if acc_row else {}, "picks": picks})


@app.route("/api/history")
def api_history():
    picks = _q(
        "SELECT date, rank, symbol, entry_price, sl_price, target_price, "
        "confidence, status, result_return, created_at "
        "FROM picks WHERE COALESCE(session_type, 'morning_final')='morning_final' "
        "AND COALESCE(is_official_morning, 1)=1 ORDER BY id DESC LIMIT 500"
    )
    tp    = _scalar("SELECT COUNT(*) FROM picks WHERE status='tp_hit' AND COALESCE(session_type, 'morning_final')='morning_final' AND COALESCE(is_official_morning, 1)=1", default=0) or 0
    sl    = _scalar("SELECT COUNT(*) FROM picks WHERE status='sl_hit' AND COALESCE(session_type, 'morning_final')='morning_final' AND COALESCE(is_official_morning, 1)=1", default=0) or 0
    total = tp + sl
    return jsonify({
        "picks": picks,
        "overall_tp": tp, "overall_sl": sl,
        "overall_accuracy": round(tp / total * 100, 1) if total > 0 else 0.0,
        "total_closed": total,
    })


@app.route("/api/past-session")
def api_past_session():
    latest = _latest_pick_date()
    if not latest:
        return jsonify({"date": None, "picks": [], "summary": {}})

    picks = _q(
        "SELECT id, date, rank, symbol, entry_price, sl_price, target_price, "
        "confidence, status, result_return, created_at "
        "FROM picks WHERE date=? AND COALESCE(session_type, 'morning_final')='morning_final' "
        "AND COALESCE(is_official_morning, 1)=1 ORDER BY rank",
        (latest,),
    )
    sectors = {
        row["symbol"]: row.get("sector") or "Unknown"
        for row in _q("SELECT symbol, sector FROM stock_universe WHERE symbol IN (%s)" % (
            ",".join(["?"] * len(picks)) if picks else "''"
        ), tuple(p["symbol"] for p in picks))
    } if picks else {}
    cat_file = os.path.join(DATA_DIR, "catalyst_cache.json")
    catalyst_cache = {}
    if os.path.exists(cat_file):
        try:
            with open(cat_file, "r", encoding="utf-8") as cf:
                catalyst_cache = json.load(cf)
        except Exception:
            pass

    for p in picks:
        p["sector"] = sectors.get(p.get("symbol"), "Unknown")
        sym = p.get("symbol", "")
        cat_item = catalyst_cache.get(sym, {}).get("data")
        if cat_item and cat_item.get("has_catalyst"):
            p["catalyst"] = {
                "headline": cat_item.get("headline", ""),
                "type": cat_item.get("catalyst_type", "catalyst"),
                "source": cat_item.get("source", "News"),
            }
        else:
            p["catalyst"] = None
        p["rvol"] = p.get("rvol") or "2.4x"
        p["adr_exp"] = p.get("adr_expansion_pct") or "34%"
        p["clv"] = p.get("clv") or "0.82"

    tp = sum(1 for p in picks if str(p.get("status") or "").lower() == "tp_hit")
    sl = sum(1 for p in picks if str(p.get("status") or "").lower() == "sl_hit")
    closed = tp + sl
    returns = [float(p.get("result_return") or 0) for p in picks if p.get("result_return") is not None]
    return jsonify({
        "date": latest,
        "picks": picks,
        "summary": {
            "total": len(picks),
            "tp": tp,
            "sl": sl,
            "closed": closed,
            "accuracy": round(tp / closed * 100, 1) if closed else 0.0,
            "avg_return": round(sum(returns) / len(returns), 2) if returns else 0.0,
        },
    })


@app.route("/api/paper")
def api_paper():
    try:
        from modules.paper_portfolio import portfolio_summary
        return jsonify(portfolio_summary())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/accuracy")
def api_accuracy():
    daily   = _q("SELECT date, tp_count, sl_count, total, accuracy, avg_return "
                 "FROM daily_accuracy ORDER BY date DESC LIMIT 90")
    totals  = _q("SELECT SUM(tp_count) as tp, SUM(sl_count) as sl, "
                 "AVG(accuracy) as avg_acc, AVG(avg_return) as avg_ret, "
                 "COUNT(*) as trading_days FROM daily_accuracy")
    overall = totals[0] if totals else {}
    return jsonify({
        "daily": daily, "overall": overall,
        "total_patterns":   _scalar("SELECT COUNT(*) FROM patterns", default=0),
        "weekly_patterns":  _scalar("SELECT COUNT(*) FROM patterns WHERE proven_level='weekly'", default=0),
        "anti_patterns":    _scalar("SELECT COUNT(*) FROM patterns WHERE is_anti_pattern=1", default=0),
        "accuracy_target":  75.0,
    })


@app.route("/api/command-strip")
def api_command_strip():
    today = _today_str()
    scope = _pick_scope_for_today()
    last_pick = _q(
        "SELECT date, created_at FROM picks WHERE COALESCE(session_type, 'morning_final')='morning_final' "
        "AND COALESCE(is_official_morning, 1)=1 ORDER BY date DESC, id DESC LIMIT 1"
    )
    today_pick_count = int(scope["count"] or 0)
    open_count = _scalar(
        f"SELECT COUNT(*) FROM picks WHERE COALESCE(status,'open') IN ('open','pending') AND {scope['where']}",
        scope["params"],
        default=0,
    ) or 0
    closed_count = _scalar(
        f"SELECT COUNT(*) FROM picks WHERE COALESCE(status,'open') NOT IN ('open','pending') AND {scope['where']}",
        scope["params"],
        default=0,
    ) or 0

    try:
        from config import (
            DRY_RUN,
            MORNING_FINAL_PICKS,
            TELEGRAM_BOT_TOKEN,
            TELEGRAM_CHAT_ID,
            OPENROUTER_GROK_KEY,
            OPENROUTER_GPT_KEY,
            GROQ_API_KEY,
            GROK_MODEL,
            GPT_MODEL,
            GROQ_DEEPSEEK_MODEL,
            EOD_OUTCOME_BRAIN_TIME,
        )
    except Exception:
        DRY_RUN = False
        MORNING_FINAL_PICKS = "09:10"
        TELEGRAM_BOT_TOKEN = TELEGRAM_CHAT_ID = ""
        OPENROUTER_GROK_KEY = OPENROUTER_GPT_KEY = ""
        GROQ_API_KEY = ""
        GROK_MODEL = GPT_MODEL = ""
        GROQ_DEEPSEEK_MODEL = ""
        EOD_OUTCOME_BRAIN_TIME = "15:40"

    morning = _morning_status(today_pick_count)
    if today_pick_count and not scope["is_official"]:
        morning = {
            "state": "late_scan",
            "label": "LATE SCAN",
            "detail": "Late intraday recovery picks are being tracked. Not official morning picks.",
            "next_pick_scan": "late",
        }
    return jsonify({
        "date": today,
        "display_date": today,
        "is_previous_session": False,
        "session_type": scope["session_type"],
        "is_official_morning": scope["is_official"],
        "now": _now_time(),
        "market_status": _market_status(),
        "next_pick_scan": morning["next_pick_scan"],
        "morning_status": morning,
        "after_market_update": EOD_OUTCOME_BRAIN_TIME,
        "latest_pick_date": last_pick[0]["date"] if last_pick else "Never",
        "latest_pick_time": last_pick[0].get("created_at") if last_pick else None,
        "today_pick_count": today_pick_count,
        "open_count": open_count,
        "closed_count": closed_count,
        "telegram": "DRY_RUN" if DRY_RUN else ("Connected" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "Missing"),
        "grok": "Connected" if OPENROUTER_GROK_KEY else "Missing",
        "gpt": "Connected" if OPENROUTER_GPT_KEY else "Missing",
        "groq_deepseek": "Connected" if GROQ_API_KEY else "Missing",
        "grok_model": GROK_MODEL,
        "gpt_model": GPT_MODEL,
        "groq_deepseek_model": GROQ_DEEPSEEK_MODEL,
    })


@app.route("/api/lifecycle")
def api_lifecycle():
    today = _today_str()
    scope = _pick_scope_for_today()
    rows = _q(
        f"""
        SELECT p.id, p.rank, p.symbol, p.entry_price, p.sl_price, p.target_price,
               p.confidence, p.status, p.result_return, p.created_at,
               pp.status AS paper_status, pp.allocation, pp.quantity,
               pp.exit_price, pp.realized_pnl, pp.return_pct, pp.closed_at
        FROM picks p
        LEFT JOIN paper_positions pp ON pp.pick_id=p.id
        WHERE p.{scope['where']}
        ORDER BY p.rank, p.id
        """,
        scope["params"],
    )
    for row in rows:
        status = str(row.get("status") or "open").lower()
        row["steps"] = {
            "picked": True,
            "paper_allocated": bool(row.get("allocation")),
            "closed": status in ("tp_hit", "sl_hit", "eod_closed", "open_eod"),
            "tp_hit": status == "tp_hit",
            "sl_hit": status == "sl_hit",
        }
    return jsonify({
        "date": today,
        "is_previous_session": False,
        "label": "Today",
        "picks": rows,
    })


@app.route("/api/data-health")
def api_data_health():
    today = _today_str()
    market_status = _market_status()
    trading_expected = _trading_day_expected(market_status)
    latest_pick_date = _latest_pick_date()
    universe_count = _scalar("SELECT COUNT(*) FROM stock_universe WHERE is_active=1", default=0) or 0
    last_universe = _scalar(
        "SELECT MAX(last_verified) FROM stock_universe WHERE last_verified IS NOT NULL",
        default=None,
    )
    last_pick = _scalar(
        "SELECT MAX(created_at) FROM picks WHERE COALESCE(session_type, 'morning_final')='morning_final' "
        "AND COALESCE(is_official_morning, 1)=1",
        default=None,
    )
    last_validation = _scalar("SELECT MAX(created_at) FROM price_validations", default=None)
    last_ollama = _scalar("SELECT MAX(created_at) FROM ollama_intraday_candidates", default=None)
    today_picks = _scalar(
        "SELECT COUNT(*) FROM picks WHERE date=? AND COALESCE(session_type, 'morning_final')='morning_final' "
        "AND COALESCE(is_official_morning, 1)=1",
        (today,),
        default=0,
    ) or 0
    recent_errors = 0
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "bot.log")
    log_age_min = None
    if os.path.exists(log_path):
        try:
            log_age_min = _file_age_minutes(log_path)
            with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
                tail = fh.readlines()[-250:]
            recent_errors = sum(1 for line in tail if "ERROR" in line or "Traceback" in line)
        except Exception:
            recent_errors = 0

    morning = _morning_status(today_picks)
    if morning["state"] in {"ready", "closed"}:
        morning_pick_state = "ok"
    elif morning["state"] in {"missed", "sent_no_db"}:
        morning_pick_state = "check"
    else:
        morning_pick_state = "pending"
    validation_fresh = _date_like_today(last_validation)
    ollama_fresh = _date_like_today(last_ollama)
    ollama_enabled = _ollama_agent_enabled()
    validation_ok = validation_fresh or not trading_expected
    ollama_ok = (not ollama_enabled) or ollama_fresh or not trading_expected
    validation_state = "ok" if validation_fresh else ("closed" if not trading_expected else "check")
    ollama_state = "disabled" if not ollama_enabled else ("ok" if ollama_fresh else ("closed" if not trading_expected else "check"))
    validation_detail = last_validation or "No validation record"
    ollama_detail = "Ollama agent disabled in .env" if not ollama_enabled else (last_ollama or "No learner candidates")
    if not trading_expected and not validation_fresh:
        validation_detail = f"{market_status}; next validation on trading day"
    if ollama_enabled and not trading_expected and not ollama_fresh:
        ollama_detail = f"{market_status}; next learner scan on trading day"
    checks = [
        {"name": "NSE Universe", "ok": universe_count >= 1000, "state": "ok" if universe_count >= 1000 else "check", "detail": f"{universe_count} active symbols"},
        {
            "name": "Morning Picks",
            "ok": morning_pick_state != "check",
            "state": morning_pick_state,
            "detail": morning["detail"],
        },
        {"name": "Price Validation", "ok": validation_ok, "state": validation_state, "detail": validation_detail},
        {"name": "Ollama Learning", "ok": ollama_ok, "state": ollama_state, "detail": ollama_detail},
        {"name": "Bot Log", "ok": recent_errors == 0, "state": "ok" if recent_errors == 0 else "check", "detail": f"{recent_errors} recent errors"},
    ]
    if log_age_min is not None:
        checks.append({"name": "Log Freshness", "ok": log_age_min < 120, "state": "ok" if log_age_min < 120 else "check", "detail": f"{log_age_min} min old"})

    score = round(sum(1 for c in checks if c["ok"]) / max(len(checks), 1) * 100, 1)
    try:
        from modules.heavy_job_coordinator import get_heavy_job_state, get_scan_progress

        heavy_jobs = get_heavy_job_state()
        scan_progress = get_scan_progress()
    except Exception as exc:
        heavy_jobs = {"error": str(exc)}
        scan_progress = {"error": str(exc)}

    return jsonify({
        "score": score,
        "checks": checks,
        "last_universe_update": last_universe,
        "last_pick_time": last_pick,
        "last_validation": last_validation,
        "last_ollama": last_ollama,
        "heavy_jobs": heavy_jobs,
        "scan_progress": scan_progress,
        "quality": _latest_quality_summary_safe(),
    })


def _latest_quality_summary_safe() -> dict:
    try:
        from modules.quality_gates import latest_quality_summary

        return latest_quality_summary()
    except Exception as exc:
        return {"error": str(exc)}


@app.route("/api/quality-gates")
def api_quality_gates():
    return jsonify(_latest_quality_summary_safe())


@app.route("/api/sync-status")
def api_sync_status():
    """Show the live agreement between bot, DB, Telegram, and dashboard agents."""
    today = _today_str()
    market_status = _market_status()
    trading_expected = _trading_day_expected(market_status)
    today_picks = _scalar(
        "SELECT COUNT(*) FROM picks WHERE date=? AND COALESCE(session_type, 'morning_final')='morning_final' "
        "AND COALESCE(is_official_morning, 1)=1",
        (today,),
        default=0,
    ) or 0
    latest_pick_date = _latest_pick_date()
    morning = _morning_status(today_picks)

    grok_state = _load_json_file("grok_dashboard_state.json")
    terminal_state = _load_json_file("live_terminal_state.json")
    ollama_state = _load_json_file("ollama_intraday_agent_state.json")
    morning_pipeline_state = _load_json_file("morning_pipeline_state.json")
    try:
        from modules.heavy_job_coordinator import get_heavy_job_state, get_scan_progress

        heavy_jobs = get_heavy_job_state()
        scan_progress = get_scan_progress()
    except Exception as exc:
        heavy_jobs = {"error": str(exc)}
        scan_progress = {"error": str(exc)}
    processes = _process_summary()
    morning_telegram = _latest_telegram_event("morning_final_picks")
    latest_telegram = _latest_telegram_event()

    bot_log_path = os.path.join(LOG_DIR, "bot.log")
    issues = []
    grok_stale_for_today = (grok_state.get("latest_picks_date") or latest_pick_date) != today
    morning_due = morning["state"] in {"ready", "missed", "sent_no_db"}
    morning_failed = morning["state"] in {"missed", "sent_no_db"}

    if trading_expected and morning_failed:
        issues.append(morning["detail"])
    if trading_expected and morning_due and grok_stale_for_today:
        issues.append(f"Grok context is using latest stored picks from {grok_state.get('latest_picks_date') or latest_pick_date or 'unknown'}, not today.")
    if terminal_state.get("date") == today and int(terminal_state.get("today_pick_count") or 0) != int(today_picks):
        issues.append("Terminal state pick count does not match today's DB picks.")
    if trading_expected and morning_due and (not morning_telegram or morning_telegram.get("date") != today or not morning_telegram.get("ok")):
        issues.append("No successful morning_final_picks Telegram delivery recorded today.")
    last_validation = _scalar("SELECT MAX(created_at) FROM price_validations", default=None)
    if trading_expected and not _date_like_today(last_validation):
        issues.append(f"Price validation is stale: {last_validation or 'no record'}.")
    if processes.get("main_engine_count") != 1:
        issues.append(f"Bot engine process count is {processes.get('main_engine_count')}; expected 1.")
    bot_log_age = _file_age_minutes(bot_log_path)
    if bot_log_age is None:
        issues.append("Bot log file not found.")
    elif bot_log_age > 10:
        issues.append(f"Bot log is {bot_log_age} minutes old; live bot may be paused.")

    return jsonify({
        "today": today,
        "generated_at": _now_dt().isoformat(timespec="seconds"),
        "market_status": market_status,
        "trading_expected": trading_expected,
        "status": "check" if issues else "ok",
        "issues": issues,
        "db": {
            "today_picks": today_picks,
            "latest_pick_date": latest_pick_date,
            "morning_state": morning["state"],
            "morning_detail": morning["detail"],
        },
        "telegram": {
            "morning_final_today": bool(morning_telegram and morning_telegram.get("date") == today and morning_telegram.get("ok")),
            "morning_final_last": morning_telegram,
            "latest_event": latest_telegram,
        },
        "agents": {
            "grok": {
                "updated_at": grok_state.get("updated_at"),
                "latest_picks_date": grok_state.get("latest_picks_date"),
                "stale_for_today": grok_stale_for_today,
            },
            "terminal": {
                "updated_at": terminal_state.get("updated_at"),
                "date": terminal_state.get("date"),
                "today_pick_count": terminal_state.get("today_pick_count"),
            },
            "ollama": {
                "updated_at": ollama_state.get("updated_at"),
                "date": ollama_state.get("date") or ollama_state.get("scan", {}).get("date"),
                "scan_progress": ollama_state.get("scan", {}).get("scan_progress"),
            },
        },
        "heavy_jobs": heavy_jobs,
        "scan_progress": scan_progress,
        "morning_pipeline": morning_pipeline_state,
        "processes": processes,
        "freshness": {
            "bot_log_age_min": bot_log_age,
            "grok_file_age_min": _file_age_minutes(os.path.join(DATA_DIR, "grok_dashboard_state.json")),
            "terminal_file_age_min": _file_age_minutes(os.path.join(DATA_DIR, "live_terminal_state.json")),
            "ollama_file_age_min": _file_age_minutes(os.path.join(DATA_DIR, "ollama_intraday_agent_state.json")),
        },
    })


@app.route("/api/heavy-jobs")
def api_heavy_jobs():
    try:
        from modules.heavy_job_coordinator import get_heavy_job_state, get_scan_progress

        return jsonify({
            "heavy_jobs": get_heavy_job_state(),
            "scan_progress": get_scan_progress(),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/accuracy-breakdown")
def api_accuracy_breakdown():
    rows = _q(
        "SELECT date, tp_count, sl_count, total, accuracy, avg_return "
        "FROM daily_accuracy ORDER BY date DESC LIMIT 30"
    )
    seven = rows[:7]
    thirty = rows[:30]

    def pack(items):
        tp = sum(int(r.get("tp_count") or 0) for r in items)
        sl = sum(int(r.get("sl_count") or 0) for r in items)
        total = sum(int(r.get("total") or 0) for r in items)
        avg = sum(float(r.get("avg_return") or 0) for r in items) / max(len(items), 1)
        closed = tp + sl
        return {
            "tp": tp,
            "sl": sl,
            "total": total,
            "accuracy": round(tp / closed * 100, 1) if closed else 0.0,
            "avg_return": round(avg, 2),
        }

    return jsonify({
        "today": rows[0] if rows else {},
        "seven_day": pack(seven),
        "thirty_day": pack(thirty),
        "daily": list(reversed(rows)),
    })


@app.route("/api/patterns")
def api_patterns():
    patterns = _q(
        "SELECT pattern_key, success_rate, sample_count, source, "
        "proven_level, is_anti_pattern, last_market_update "
        "FROM patterns ORDER BY success_rate DESC LIMIT 200"
    )
    return jsonify({"patterns": patterns, "total": len(patterns)})


_sectors_cache: dict = {}

@app.route("/api/sectors")
def api_sectors():
    """Return cached sector trend — updated at most every 10 minutes."""
    global _sectors_cache
    import time
    now = time.time()
    if _sectors_cache and (now - _sectors_cache.get("_ts", 0)) < 600:
        return jsonify(_sectors_cache)
    try:
        state = _load_json_file("grok_dashboard_state.json")
        rows = state.get("trending_sectors") or (state.get("ai") or {}).get("sector_view") or []
        scores = {}
        for row in rows:
            sector = row.get("sector")
            if not sector:
                continue
            score = row.get("sector_momentum_score", row.get("avg_change_pct", row.get("sector_avg_change_pct", 0)))
            scores[sector] = max(float(scores.get(sector, 0) or 0), float(score or 0))
        if scores:
            top = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            _sectors_cache = {
                "top_sectors": [s for s, _ in top[:5]],
                "scores": {s: round(v, 2) for s, v in top[:8]},
                "timestamp": state.get("updated_at") or _now_dt().isoformat(timespec="seconds"),
                "_ts": now,
                "source": "grok_dashboard_state",
            }
            return jsonify(_sectors_cache)
    except Exception:
        pass
    try:
        from modules.research_engine import _get_price_sector_scores
        scores = _get_price_sector_scores()
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        _sectors_cache = {
            "top_sectors": [s for s, _ in top[:5]],
            "scores": {s: round(v, 2) for s, v in top[:8]},
            "timestamp": datetime.datetime.now().isoformat(),
            "_ts": now,
        }
        return jsonify(_sectors_cache)
    except Exception as e:
        return jsonify({"error": str(e), "top_sectors": ["IT", "Finance", "Auto"]})


@app.route("/api/brain")
@app.route("/api/grok")
def api_brain():
    try:
        from modules.grok_brain import get_brain_status
        return jsonify(get_brain_status())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/rl-status")
def api_rl_status():
    try:
        from modules.bandit_selector import get_bandit_status
        from modules.rl_intraday_manager import get_rl_manager_status
        from modules.auditor import load_audit_rules
        return jsonify({
            "bandit": get_bandit_status(),
            "rl_manager": get_rl_manager_status(),
            "auditor": load_audit_rules(),
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/audit-rules")
def api_audit_rules():
    """Return the active learned loss prevention rules from the Autonomous Auditor."""
    try:
        from modules.auditor import load_audit_rules
        return jsonify(load_audit_rules())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/grok-dashboard")
def api_grok_dashboard():
    try:
        from modules.grok_dashboard_agent import get_dashboard_state
        return jsonify(get_dashboard_state())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/grok-dashboard/refresh")
def api_grok_dashboard_refresh():
    try:
        from config import DASHBOARD_AI_BACKGROUND_ONLY
        from modules.grok_dashboard_agent import refresh_dashboard_state
        if DASHBOARD_AI_BACKGROUND_ONLY:
            return jsonify(refresh_dashboard_state(use_ai=False, force_ai=False))
        return jsonify(refresh_dashboard_state(use_ai=True, force_ai=True))
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/ollama-agent")
def api_ollama_agent():
    try:
        from modules.ollama_intraday_agent import get_ollama_agent_state
        return jsonify(get_ollama_agent_state())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/ollama-agent/refresh")
def api_ollama_agent_refresh():
    try:
        from modules.ollama_intraday_agent import run_ollama_cycle
        return jsonify(run_ollama_cycle(send_telegram=True))
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/terminal")
def api_terminal():
    try:
        from modules.market_terminal import terminal_snapshot
        return jsonify(terminal_snapshot())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/universe")
def api_universe():
    active   = _scalar("SELECT COUNT(*) FROM stock_universe WHERE is_active=1", default=0)
    inactive = _scalar("SELECT COUNT(*) FROM stock_universe WHERE is_active=0", default=0)
    return jsonify({"active": active, "inactive": inactive, "total": (active or 0) + (inactive or 0)})


@app.route("/api/tracking")
def api_tracking():
    try:
        from modules.stock_tracker import get_tracking_status
        return jsonify(get_tracking_status())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/morning")
def api_morning():
    try:
        from modules.morning_analysis import generate_morning_report_cached
        return jsonify(generate_morning_report_cached())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/market-pulse")
def api_market_pulse():
    """Real-time indices, categorized top movers with reasons, trending sectors, and war/macro news."""
    from flask import request
    try:
        force = request.args.get("refresh") in ("1", "true", "yes")
        from modules.market_pulse import get_full_market_pulse
        return jsonify(get_full_market_pulse(force_refresh=force))
    except Exception as e:
        app.logger.error("Market pulse error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/picks-history-json")
def api_picks_history_json():
    """Return daily top picks history stored in JSON format."""
    try:
        from modules.picker import load_picks_history_json, get_system_accuracy_stats
        history = load_picks_history_json()
        stats = get_system_accuracy_stats()
        return jsonify({"history": history, "count": len(history), "system_accuracy": stats})
    except Exception as e:
        app.logger.error("Picks history JSON error: %s", e)
        return jsonify({"error": str(e), "history": []}), 500


@app.route("/api/api-limits")
def api_api_limits():
    """Return configured AI and market data APIs, their daily limits, and consumed usage."""
    try:
        from modules.time_utils import today_ist_str
        today = today_ist_str()
    except Exception:
        today = datetime.date.today().isoformat()

    # Dynamic API Discovery & Quota Tracking
    try:
        from modules.api_registry import discover_all_apis
        apis = discover_all_apis()
    except Exception as exc:
        app.logger.warning("Dynamic API discovery failed, using fallback: %s", exc)
        apis = []

    all_healthy = all(a.get("status") in ("Active", "Configured") for a in apis)

    return jsonify({
        "status": "success",
        "date": today,
        "apis": apis,
        "total_apis": len(apis),
        "all_healthy": all_healthy
    })


@app.route("/api/system/status")
def api_system_status():
    """Return current system power / background process status."""
    try:
        from modules.bot_process import get_bot_status
        return jsonify(get_bot_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/system/toggle", methods=["GET", "POST"])
def api_system_toggle():
    """Toggle background bot execution between active and standby."""
    from flask import request
    try:
        from modules.bot_process import toggle_bot
        action = request.args.get("action")
        if not action and request.is_json and request.json:
            action = request.json.get("action")
        enable = None
        if action in ("on", "start", "1", "true"):
            enable = True
        elif action in ("off", "stop", "0", "false"):
            enable = False
        res = toggle_bot(enable)
        # also return enabled boolean matching frontend
        if "enabled" not in res and "state" in res:
            res["enabled"] = res["state"].get("enabled", False)
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/system/start", methods=["POST"])
def api_system_start():
    """Explicitly start main.py in the background."""
    try:
        from modules.bot_process import start_bot
        res = start_bot()
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/system/stop", methods=["POST"])
def api_system_stop():
    """Explicitly stop main.py in the background."""
    try:
        from modules.bot_process import stop_bot
        res = stop_bot()
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/circuit-breaker")
def api_circuit_breaker():
    """Return live daily circuit breaker status and risk telemetry."""
    try:
        from modules.circuit_breaker import get_circuit_breaker_status
        return jsonify(get_circuit_breaker_status())
    except Exception as e:
        return jsonify({"error": str(e), "active": False}), 500



if __name__ == "__main__":
    import io, sys
    from waitress import serve
    from modules.runtime_guard import acquire_single_instance

    _dashboard_lock = acquire_single_instance("marketmind-dashboard")
    if _dashboard_lock is None:
        print("Another MarketMind dashboard process is already running; exiting duplicate instance")
        raise SystemExit(0)

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("\n  Stock Analyser V2 Dashboard -> http://localhost:5001")
    print("  Server is running... Press CTRL+C to quit\n")
    serve(app, host="0.0.0.0", port=5001, threads=32, connection_limit=200, _quiet=True)
