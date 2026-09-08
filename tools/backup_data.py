"""tools/backup_data.py — Automated backup utility for MarketMind Pro.
Creates timestamped backups of history.db and daily_picks_history.json.
Rotates old backups keeping the most recent 14 snapshots.
"""

from __future__ import annotations

import datetime
import glob
import logging
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backup")

BACKUP_DIR = "data/backups"
MAX_BACKUPS = 14


def run_backup() -> list[str]:
    """Execute backup for critical state files."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    targets = [
        "data/history.db",
        "data/daily_picks_history.json",
        "data/grok_brain_state.json",
        "data/discovered_patterns.json",
    ]
    backed_up: list[str] = []

    for fpath in targets:
        if os.path.exists(fpath):
            fname = os.path.basename(fpath)
            dest = os.path.join(BACKUP_DIR, f"{fname}.{now_str}.bak")
            shutil.copy2(fpath, dest)
            backed_up.append(dest)
            logger.info("Backed up %s -> %s", fpath, dest)

    # Rotate older backups
    for fpath in targets:
        fname = os.path.basename(fpath)
        pattern = os.path.join(BACKUP_DIR, f"{fname}.*.bak")
        files = sorted(glob.glob(pattern), key=os.path.getmtime)
        if len(files) > MAX_BACKUPS:
            for old in files[:-MAX_BACKUPS]:
                try:
                    os.remove(old)
                    logger.info("Rotated old backup: %s", old)
                except Exception as exc:
                    logger.warning("Could not remove old backup %s: %s", old, exc)

    logger.info("Backup complete: %d files archived to %s", len(backed_up), BACKUP_DIR)
    return backed_up


if __name__ == "__main__":
    run_backup()

