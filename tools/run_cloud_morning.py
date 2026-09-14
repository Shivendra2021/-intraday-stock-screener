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
    from config import QUANT_ENABLED
    if QUANT_ENABLED:
        from modules.quant_runtime import run_once
        result = run_once(notify=True)
        print(f"QUANT_RESULT: {result.get('status')}")
        return
    today = today_ist_str()
    print(f"CLOUD_MORNING_START: date={today} cwd={ROOT}")

    if not main._is_trading_day():
        print("CLOUD_MORNING_SKIP: not a trading day")
        return

    if main._morning_already_done_today():
        print("CLOUD_MORNING_SKIP: picks already exist today")
        if not main._telegram_event_success_today("morning_final_picks"):
            picks = main._load_todays_picks()
            if picks:
                print("CLOUD_MORNING_RESEND: stored picks found, resending Telegram")
                if not main._send_telegram(picks, agreed=False):
                    _fail("stored picks exist but Telegram resend failed", 3)
        return

    main.run_morning_session()

    pick_count = main._today_pick_count()
    telegram_ok = main._telegram_event_success_today("morning_final_picks")
    print(f"CLOUD_MORNING_RESULT: picks={pick_count} telegram_ok={telegram_ok}")

    if pick_count <= 0:
        _fail("morning pipeline finished without stored picks", 2)
    if not telegram_ok:
        _fail("morning picks were not delivered to Telegram", 3)


if __name__ == "__main__":
    run()
