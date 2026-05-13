"""Run after-market full-universe winner learning once for cloud schedulers."""

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

import main  # noqa: E402
from config import INTRADAY_MIN_RETURN_PCT  # noqa: E402
from modules.ollama_intraday_agent import daily_winner_learning, scan_full_universe  # noqa: E402
from modules.time_utils import today_ist_str  # noqa: E402


def run() -> None:
    today = today_ist_str()
    print(f"CLOUD_AFTER_MARKET_START: date={today} cwd={ROOT}")

    if not main._is_trading_day():
        print("CLOUD_AFTER_MARKET_SKIP: not a trading day")
        return

    scan = scan_full_universe()
    print(
        "CLOUD_AFTER_MARKET_SCAN: "
        f"scanned={scan.get('symbols_scanned')} winners={scan.get('winner_count')} candidates={scan.get('candidates_found')}"
    )

    result = daily_winner_learning(
        min_return_pct=INTRADAY_MIN_RETURN_PCT,
        force=True,
        send_telegram=True,
    )
    print(
        "CLOUD_AFTER_MARKET_RESULT: "
        f"winners={result.get('winner_count')} ai_ok={(result.get('ai') or {}).get('ok')}"
    )

    if result.get("winner_count", 0) <= 0:
        print("CLOUD_AFTER_MARKET_NO_WINNERS: scan completed but no 7%+ movers were found")


if __name__ == "__main__":
    run()
