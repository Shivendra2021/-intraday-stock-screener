"""Run EOD outcome reconciliation once.

Useful for GitHub Actions, Task Scheduler, or manual repair runs.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("TZ", "Asia/Kolkata")

if hasattr(time, "tzset"):
    time.tzset()

for path in ("data", "logs", "output"):
    Path(path).mkdir(exist_ok=True)

from modules.eod_outcome_brain import reconcile_daily_outcomes  # noqa: E402


def run() -> None:
    result = reconcile_daily_outcomes(send_telegram=True, review_with_brain=True)
    stats = result.get("stats", {})
    print(
        "EOD_OUTCOME_BRAIN_RESULT: "
        f"date={result.get('date')} updates={len(result.get('updates', []))} "
        f"tp={stats.get('tp_count')} sl={stats.get('sl_count')} "
        f"accuracy={stats.get('accuracy')} avg_return={stats.get('avg_return')}"
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    run()
