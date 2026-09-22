"""Run intraday stock tracking pass once for cloud schedulers (GitHub Actions).

This entrypoint loads active picks from data/pick_tracking.json, fetches live
quotes, checks Breakeven / Target 1 / Target 2 / Stop Loss conditions, and fires
instant Telegram alerts if any runner achieves a milestone.
"""

from __future__ import annotations

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

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run() -> None:
    from modules.scanner import is_market_holiday, is_weekend
    from modules.stock_tracker import _load, update_tracking, send_hourly_status
    from modules.time_utils import now_ist, today_ist_str

    today = today_ist_str()
    now = now_ist()
    print(f"CLOUD_TRACKER_START: date={today} time={now.strftime('%H:%M:%S')} cwd={ROOT}")

    if is_weekend(now.date()) or is_market_holiday(now.date()):
        print(f"CLOUD_TRACKER_SKIP: {today} is a weekend or market holiday")
        return

    tracking = _load()
    if not tracking:
        print("CLOUD_TRACKER_INFO: No tracked positions found in data/pick_tracking.json")
        return

    active_count = sum(1 for sym, d in tracking.items() if str(d.get("status", "")).upper() == "ACTIVE")
    print(f"CLOUD_TRACKER_RUN: Found {len(tracking)} total positions ({active_count} ACTIVE)")

    if active_count == 0:
        print("CLOUD_TRACKER_INFO: All positions are closed/resolved for today")
        return

    # Update live tracking, evaluate trailing stops and fire milestone alerts
    updated = update_tracking()

    # Log summary for cloud run logs
    print("CLOUD_TRACKER_STATUS:")
    for sym, d in updated.items():
        entry = d.get("entry_price", 0)
        curr = d.get("current_price", entry)
        pnl = d.get("pnl_pct", 0.0)
        status = d.get("status", "ACTIVE")
        stage = d.get("stage", "STAGE_1")
        sl = d.get("sl_price", 0)
        print(f"  {sym}: Rs.{curr:.2f} (Entry: Rs.{entry:.2f}, PnL: {pnl:+.2f}%, SL: Rs.{sl:.2f}, Status: {status}, Stage: {stage})")

    # Send hourly status if running on an hour boundary
    minute = now.minute
    if minute >= 55 or minute <= 5:
        try:
            print("Sending scheduled hourly Telegram status update...")
            send_hourly_status()
        except Exception as exc:
            print(f"Warning: hourly status dispatch error: {exc}")

    print("CLOUD_TRACKER_COMPLETE: Live tracking pass successfully finished.")


if __name__ == "__main__":
    run()
