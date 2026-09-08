r"""Run one automation supervisor pass.

Use this for one-command startup repair or manual diagnosis:
  .venv\Scripts\python.exe tools\system_supervisor.py
  .venv\Scripts\python.exe tools\system_supervisor.py --dry-run
  .venv\Scripts\python.exe tools\system_supervisor.py --quick
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from modules.automation_supervisor import run_once  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Only show what would run.")
    parser.add_argument("--quick", action="store_true", help="Skip heavy deep learning in this foreground pass.")
    args = parser.parse_args()
    result = run_once(dry_run=args.dry_run, skip_deep=args.quick)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
