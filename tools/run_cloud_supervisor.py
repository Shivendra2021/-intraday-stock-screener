"""Run one time-aware automation pass for GitHub Actions.

This is the cloud entrypoint for the same supervisor used locally. It is
intentionally one-shot because GitHub-hosted runners are temporary.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("BSE_UNIVERSE_ENABLED", "False")
os.environ.setdefault("GROK_DASHBOARD_AGENT_ENABLED", "False")
os.environ.setdefault("INTRADAY_PATTERN_AGENT_ENABLED", "False")
os.environ.setdefault("OLLAMA_AGENT_ENABLED", "False")


def main() -> int:
    from modules.automation_supervisor import run_once

    result = run_once(dry_run=False, skip_deep=False)
    print("CLOUD_SUPERVISOR_RESULT:")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    jobs = result.get("jobs") or {}
    failed = []
    for job_id, payload in jobs.items():
        if isinstance(payload, dict) and payload.get("ok") is False and not payload.get("timeout"):
            failed.append(job_id)

    if failed:
        print(f"CLOUD_SUPERVISOR_FAIL: failed_jobs={failed}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
