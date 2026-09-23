"""
modules/rejection_audit.py — Point-in-time Candidate Funnel & Rejection Audit Ledger
Never overwrites rejection history. Records every candidate's journey through the pipeline.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
import time

from modules.quant_store import Store
from modules.quant_time import now_ist, today_ist_str

LOG = logging.getLogger(__name__)

# Canonical stages of the evaluation funnel
STAGES = (
    "universe",
    "history_valid",
    "watchlist",
    "intraday_context",
    "setup_trigger",
    "rvol_gate",
    "structural_risk",
    "model_gate",
    "expected_return",
    "quote_verified",
    "selected"
)


def ensure_funnel_tables(store: Store | None = None) -> None:
    store = store or Store()
    with store.connect() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS rejection_funnel (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                ts INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                stage TEXT NOT NULL,
                reason TEXT NOT NULL,
                details TEXT,
                model_version TEXT,
                feature_version TEXT,
                provenance TEXT DEFAULT 'live',
                created_at INTEGER NOT NULL
            )
        """)
        columns = [r[1] for r in c.execute("PRAGMA table_info(rejection_funnel)").fetchall()]
        if "model_version" not in columns:
            c.execute("ALTER TABLE rejection_funnel ADD COLUMN model_version TEXT")
        if "feature_version" not in columns:
            c.execute("ALTER TABLE rejection_funnel ADD COLUMN feature_version TEXT")
        if "provenance" not in columns:
            c.execute("ALTER TABLE rejection_funnel ADD COLUMN provenance TEXT DEFAULT 'live'")
        c.execute("CREATE INDEX IF NOT EXISTS idx_funnel_date_stage ON rejection_funnel(date, stage);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_funnel_reason ON rejection_funnel(date, reason);")


def record_rejection(
    store: Store | None,
    symbol: str,
    stage: str,
    reason: str,
    details: dict | str = "",
    date: str | None = None,
    ts: int | None = None,
    model_version: str | None = None,
    feature_version: str | None = None,
    provenance: str = "live"
) -> None:
    """Record an immutable candidate rejection entry in the funnel audit ledger."""
    store = store or Store()
    ensure_funnel_tables(store)
    today = date or today_ist_str()
    epoch_ts = ts or int(time.time())
    now_epoch = int(time.time())
    audit_id = f"rej:{today}:{symbol}:{epoch_ts}:{stage}"

    details_str = json.dumps(details) if isinstance(details, dict) else str(details)

    try:
        with store.connect() as c:
            c.execute("""
                INSERT OR IGNORE INTO rejection_funnel (
                    id, date, ts, symbol, stage, reason, details,
                    model_version, feature_version, provenance, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (audit_id, today, epoch_ts, symbol, stage, reason, details_str,
                  model_version, feature_version, provenance, now_epoch))
    except Exception as exc:
        LOG.debug("Could not record rejection for %s: %s", symbol, exc)



def get_funnel_summary(store: Store | None = None, date: str | None = None) -> dict:
    """Return aggregated counts, percentages, and top causes for the funnel."""
    store = store or Store()
    ensure_funnel_tables(store)
    today = date or today_ist_str()

    with store.connect() as c:
        rows = c.execute("""
            SELECT stage, reason, COUNT(*) as cnt
            FROM rejection_funnel
            WHERE date=?
            GROUP BY stage, reason
            ORDER BY cnt DESC
        """, (today,)).fetchall()

        by_stage = {}
        by_reason = {}
        total_rejections = 0

        for r in rows:
            stg = r["stage"]
            rsn = r["reason"]
            count = r["cnt"]
            by_stage[stg] = by_stage.get(stg, 0) + count
            by_reason[rsn] = by_reason.get(rsn, 0) + count
            total_rejections += count

        top_causes = sorted(by_reason.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "date": today,
            "total_rejections": total_rejections,
            "rejections_by_stage": by_stage,
            "rejections_by_reason": by_reason,
            "top_rejection_causes": [{"reason": r, "count": c} for r, c in top_causes]
        }
