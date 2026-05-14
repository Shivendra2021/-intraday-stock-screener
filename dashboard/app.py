"""
dashboard/app.py — MarketMind Pro Dashboard  http://localhost:5001
"""
import sqlite3
import datetime
import os
import sys

from flask import Flask, jsonify, render_template

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH

app = Flask(__name__, template_folder="templates", static_folder="static")


def _ensure_dashboard_db() -> None:
    """Ensure dashboard-required SQLite tables/columns exist before serving."""
    try:
        from modules.db_migrations import ensure_research_tables
        ensure_research_tables()
    except Exception as exc:
        app.logger.error("Dashboard DB migration failed: %s", exc)


_ensure_dashboard_db()


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
        import datetime as dt
        today = dt.date.today()
        if today.weekday() >= 5:
            return "Weekend"
        if is_market_holiday(today):
            return "Holiday"
        return "Open ✅" if is_market_open() else "Closed 🔴"
    except Exception:
        return "Unknown"


def _health_info() -> dict:
    try:
        from config import DRY_RUN
    except Exception:
        DRY_RUN = False

    n_universe  = _scalar("SELECT COUNT(*) FROM stock_universe WHERE is_active=1", default=0)
    last_picks  = _scalar("SELECT date FROM picks ORDER BY id DESC LIMIT 1", default="Never")
    total_tp    = _scalar("SELECT COUNT(*) FROM picks WHERE status='tp_hit'", default=0) or 0
    total_sl    = _scalar("SELECT COUNT(*) FROM picks WHERE status='sl_hit'", default=0) or 0
    total_tracked = _scalar("SELECT COUNT(*) FROM picks", default=0) or 0
    avg_return = _scalar(
        "SELECT AVG(result_return) FROM picks WHERE result_return IS NOT NULL",
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
        "check_time":      datetime.datetime.now().strftime("%H:%M:%S"),
        "brain":           brain,
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


@app.route("/api/picks")
def api_picks():
    today = datetime.date.today().isoformat()
    picks = _q(
        "SELECT id, rank, symbol, entry_price, sl_price, target_price, "
        "confidence, signal_reasons, status, result_return, created_at, "
        "validated_price, price_validation_status, edge_status, grok_review "
        "FROM picks WHERE date=? ORDER BY rank",
        (today,)
    )
    for p in picks:
        ep = p.get("entry_price") or 0
        tp = p.get("target_price") or 0
        p["upside_pct"] = round((tp - ep) / ep * 100, 2) if ep > 0 else 0.0
    return jsonify({
        "date":          today,
        "market_status": _market_status(),
        "n_universe":    _scalar("SELECT COUNT(*) FROM stock_universe WHERE is_active=1", default=0),
        "picks":         picks,
    })


@app.route("/api/results")
def api_results():
    today = datetime.date.today().isoformat()
    acc_row = _q("SELECT * FROM daily_accuracy WHERE date=?", (today,))
    picks   = _q("SELECT rank, symbol, entry_price, sl_price, target_price, "
                 "status, result_return FROM picks WHERE date=? ORDER BY rank", (today,))
    return jsonify({"date": today, "accuracy": acc_row[0] if acc_row else {}, "picks": picks})


@app.route("/api/history")
def api_history():
    picks = _q(
        "SELECT date, rank, symbol, entry_price, sl_price, target_price, "
        "confidence, status, result_return, created_at "
        "FROM picks ORDER BY id DESC LIMIT 500"
    )
    tp    = _scalar("SELECT COUNT(*) FROM picks WHERE status='tp_hit'", default=0) or 0
    sl    = _scalar("SELECT COUNT(*) FROM picks WHERE status='sl_hit'", default=0) or 0
    total = tp + sl
    return jsonify({
        "picks": picks,
        "overall_tp": tp, "overall_sl": sl,
        "overall_accuracy": round(tp / total * 100, 1) if total > 0 else 0.0,
        "total_closed": total,
    })


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
        from modules.grok_dashboard_agent import refresh_dashboard_state
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


if __name__ == "__main__":
    import io, sys
    from waitress import serve
    from modules.runtime_guard import acquire_single_instance

    _dashboard_lock = acquire_single_instance("marketmind-dashboard")
    if _dashboard_lock is None:
        print("Another MarketMind dashboard process is already running; exiting duplicate instance")
        raise SystemExit(0)

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("\n  MarketMind Pro Dashboard -> http://localhost:5001")
    print("  Server is running... Press CTRL+C to quit\n")
    serve(app, host="0.0.0.0", port=5001, _quiet=True)
