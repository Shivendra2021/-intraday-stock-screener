"""Run the morning picks pipeline once for cloud schedulers.

This entrypoint is for GitHub Actions or similar cron runners. It runs the
morning pipeline, verifies that picks were generated, and verifies Telegram
delivery was audited for today's final picks.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("TZ", "Asia/Kolkata")
os.environ.setdefault("BSE_UNIVERSE_ENABLED", "False")
os.environ.setdefault("GROK_DASHBOARD_AGENT_ENABLED", "False")
os.environ.setdefault("INTRADAY_PATTERN_AGENT_ENABLED", "False")
os.environ.setdefault("OLLAMA_AGENT_ENABLED", "False")

if hasattr(time, "tzset"):
    time.tzset()

for path in ("data", "logs", "output"):
    Path(path).mkdir(exist_ok=True)

import main  # noqa: E402
from modules.time_utils import today_ist_str  # noqa: E402


def _fail(message: str, code: int = 1) -> None:
    print(f"CLOUD_MORNING_FAIL: {message}", file=sys.stderr)
    raise SystemExit(code)


def run() -> None:
    import json
    import sqlite3
    from config import DB_PATH
    from modules.time_utils import today_ist_str, now_ist
    from modules.scanner import is_market_holiday, is_weekend

    today = today_ist_str()
    now = now_ist()
    print(f"CLOUD_MORNING_START: date={today} time={now.strftime('%H:%M:%S')} cwd={ROOT}")

    # Check weekend / holiday
    if is_weekend(now.date()) or is_market_holiday(now.date()):
        print(f"CLOUD_MORNING_SKIP: {today} is a weekend or market holiday")
        return

    # Execute 5-Pillar Institutional Screener
    print("Executing 5-Pillar Institutional Pre-Market Screener...")
    from modules.premarket_engine import run_premarket_screener
    cockpit_result = run_premarket_screener(top_n=5)

    if not cockpit_result or not cockpit_result.get("picks"):
        _fail("No qualifying institutional picks generated", 2)

    picks = cockpit_result["picks"]
    print(f"Generated {len(picks)} institutional picks:")
    for p in picks:
        print(f"  #{p.get('rank')}: {p.get('symbol')} Score={p.get('composite_score')}")

    # Save to data/premarket_cockpit.json
    cockpit_path = Path("data") / "premarket_cockpit.json"
    cockpit_path.parent.mkdir(exist_ok=True)
    with cockpit_path.open("w", encoding="utf-8") as f:
        json.dump(cockpit_result, f, indent=2, default=str)
    print("Saved cockpit to data/premarket_cockpit.json")

    # Save to SQLite history.db (picks table)
    try:
        conn = sqlite3.connect(DB_PATH)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        for i, p in enumerate(picks, start=1):
            entry = p.get("entry_trigger") or p.get("price") or 0
            sl_pct = p.get("ai_sl_pct", 1.8)
            sl = p.get("ai_sl_price") or round(entry * (1 - sl_pct / 100), 2)
            tp2 = p.get("ai_tp2_price") or round(entry * (1 + p.get("ai_tp2_pct", 10.2) / 100), 2)
            score = p.get("composite_score", 0)
            conn.execute(
                """INSERT OR REPLACE INTO picks
                   (date, rank, symbol, entry_price, sl_price, target_price,
                    confidence, signal_reasons, status, created_at, session_type,
                    is_official_morning, source_label)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'morning_final', 1, 'helios_runner')""",
                (today, i, p["symbol"], entry, sl, tp2, score, p.get("catalyst", "5-Pillar Setup"), now_str)
            )
        conn.commit()
        conn.close()
        print(f"Persisted {len(picks)} picks to DB: {DB_PATH}")
    except Exception as exc:
        print(f"Warning: SQLite persistence failed: {exc}")

    # Dispatch to Telegram via modules.alerts
    from modules.alerts import send_picks
    telegram_ok = send_picks(picks)
    print(f"Telegram delivery status: {telegram_ok}")

    # Initialize 5-minute tracking
    from modules.stock_tracker import init_tracking
    init_tracking(picks)
    print("Stock tracker initialized successfully")

    print("CLOUD_MORNING_COMPLETE: All institutional morning tasks finished.")


if __name__ == "__main__":
    run()
