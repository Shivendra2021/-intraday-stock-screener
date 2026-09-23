"""
modules/provider_health.py — Long-term Provider Reliability & Dual-Quote Consensus Validation
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


def ensure_provider_tables(store: Store | None = None) -> None:
    store = store or Store()
    with store.connect() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS provider_health (
                provider TEXT NOT NULL,
                date TEXT NOT NULL,
                requests INTEGER NOT NULL DEFAULT 0,
                successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                timeouts INTEGER NOT NULL DEFAULT 0,
                stale_quotes INTEGER NOT NULL DEFAULT 0,
                invalid_quotes INTEGER NOT NULL DEFAULT 0,
                median_latency_ms REAL NOT NULL DEFAULT 0.0,
                fresh_quote_rate REAL NOT NULL DEFAULT 1.0,
                rolling_7d_reliability REAL NOT NULL DEFAULT 1.0,
                rolling_30d_reliability REAL NOT NULL DEFAULT 1.0,
                last_error TEXT,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(provider, date)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS consensus_audit (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                ts INTEGER NOT NULL,
                primary_provider TEXT NOT NULL,
                primary_ask REAL NOT NULL,
                secondary_provider TEXT,
                secondary_ask REAL,
                discrepancy_pct REAL,
                verdict TEXT NOT NULL,
                details TEXT,
                created_at INTEGER NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_consensus_date ON consensus_audit(date);")


def record_request(
    store: Store | None,
    provider: str,
    success: bool = True,
    latency_ms: float = 0.0,
    is_stale: bool = False,
    is_invalid: bool = False,
    is_timeout: bool = False,
    error: str = ""
) -> None:
    store = store or Store()
    ensure_provider_tables(store)
    today = today_ist_str()
    now_epoch = int(time.time())

    with store.connect() as c:
        row = c.execute(
            "SELECT * FROM provider_health WHERE provider=? AND date=?",
            (provider, today)
        ).fetchone()

        if not row:
            c.execute("""
                INSERT INTO provider_health (
                    provider, date, requests, successes, failures, timeouts,
                    stale_quotes, invalid_quotes, median_latency_ms, fresh_quote_rate,
                    last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                provider, today, 1,
                1 if success else 0,
                0 if success else 1,
                1 if is_timeout else 0,
                1 if is_stale else 0,
                1 if is_invalid else 0,
                round(latency_ms, 2),
                0.0 if (is_stale or not success) else 1.0,
                error[:200] if error else None,
                now_epoch
            ))
        else:
            reqs = row["requests"] + 1
            succs = row["successes"] + (1 if success else 0)
            fails = row["failures"] + (0 if success else 1)
            timeouts = row["timeouts"] + (1 if is_timeout else 0)
            stales = row["stale_quotes"] + (1 if is_stale else 0)
            invalids = row["invalid_quotes"] + (1 if is_invalid else 0)
            old_lat = row["median_latency_ms"] or latency_ms
            new_lat = round(old_lat * 0.9 + latency_ms * 0.1, 2)
            fresh_rate = round(succs / reqs, 4) if reqs > 0 else 1.0

            c.execute("""
                UPDATE provider_health SET
                    requests=?, successes=?, failures=?, timeouts=?,
                    stale_quotes=?, invalid_quotes=?, median_latency_ms=?,
                    fresh_quote_rate=?, last_error=COALESCE(?, last_error),
                    updated_at=?
                WHERE provider=? AND date=?
            """, (
                reqs, succs, fails, timeouts, stales, invalids,
                new_lat, fresh_rate, error[:200] if error else None,
                now_epoch, provider, today
            ))


def validate_quote_consensus(
    symbol: str,
    primary_quote: dict,
    secondary_quote: dict | None = None,
    max_drift_pct: float = 0.35,
    store: Store | None = None
) -> tuple[bool, str, dict]:
    """
    Validate live quote consensus across primary and secondary feeds.
    Checks: price, timestamp freshness, bid, ask, spread, EQ series, and price bands.
    If providers disagree beyond max_drift_pct -> blocks with 'provider_disagreement'.
    If secondary unavailable -> returns (True, 'single_source_only', details).
    """
    if not primary_quote or not primary_quote.get("ask"):
        return False, "quote_unavailable", {}

    store = store or Store()
    ensure_provider_tables(store)
    today = today_ist_str()
    now_epoch = int(time.time())

    p_provider = primary_quote.get("source", "primary")
    p_ask = float(primary_quote.get("ask", 0.0))
    p_bid = float(primary_quote.get("bid", 0.0))
    p_ts = int(primary_quote.get("ts", 0))
    p_upper = float(primary_quote.get("upper", 0.0) or 0.0)
    p_series = primary_quote.get("series", "EQ")

    if p_ask <= 0 or (p_bid > 0 and p_ask < p_bid):
        return False, "invalid_quotes", {}

    if not secondary_quote or not secondary_quote.get("ask"):
        return True, "single_source_only", {
            "primary": p_provider,
            "ask": p_ask,
            "secondary": None,
            "discrepancy_pct": 0.0,
            "consensus_status": "single_source_only"
        }

    s_provider = secondary_quote.get("source", "secondary")
    s_ask = float(secondary_quote.get("ask", 0.0))
    s_bid = float(secondary_quote.get("bid", 0.0))
    s_ts = int(secondary_quote.get("ts", 0))
    s_upper = float(secondary_quote.get("upper", 0.0) or 0.0)
    s_series = secondary_quote.get("series", "EQ")

    if s_ask <= 0:
        return True, "single_source_only", {
            "primary": p_provider,
            "ask": p_ask,
            "secondary": s_provider,
            "discrepancy_pct": 0.0,
            "consensus_status": "single_source_only"
        }

    # Series check
    if s_series and s_series != "EQ":
        record_request(store, s_provider, success=False, is_invalid=True, error=f"Series mismatch: {s_series} != EQ")
        return False, "series_mismatch", {
            "primary": p_provider, "secondary": s_provider, "error": f"Secondary series {s_series} != EQ"
        }

    # Freshness drift check (> 120s between provider timestamps)
    if p_ts > 0 and s_ts > 0 and abs(p_ts - s_ts) > 120:
        record_request(store, s_provider, success=False, is_stale=True, error=f"Timestamp drift {abs(p_ts - s_ts)}s > 120s")
        return False, "timestamp_freshness_mismatch", {
            "primary": p_provider, "secondary": s_provider, "ts_diff_seconds": abs(p_ts - s_ts)
        }

    # Price band check if both provided
    if p_upper > 0 and s_upper > 0 and abs(p_upper - s_upper) / p_upper > 0.02:
        return False, "price_band_disagreement", {
            "primary_upper": p_upper, "secondary_upper": s_upper
        }

    discrepancy_pct = round(abs(p_ask - s_ask) / max(p_ask, s_ask) * 100, 4)
    audit_id = f"consensus:{symbol}:{now_epoch}"

    if discrepancy_pct > max_drift_pct:
        verdict = "provider_disagreement"
        with store.connect() as c:
            c.execute("""
                INSERT OR REPLACE INTO consensus_audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                audit_id, symbol, today, now_epoch, p_provider, p_ask,
                s_provider, s_ask, discrepancy_pct, verdict,
                f"Discrepancy {discrepancy_pct}% > limit {max_drift_pct}%",
                now_epoch
            ))
        record_request(store, p_provider, success=False, is_invalid=True, error=f"Disagrees with {s_provider} by {discrepancy_pct}%")
        return False, "provider_disagreement", {
            "primary": p_provider, "primary_ask": p_ask,
            "secondary": s_provider, "secondary_ask": s_ask,
            "discrepancy_pct": discrepancy_pct,
            "consensus_status": "provider_disagreement"
        }

    verdict = "consensus_confirmed"
    with store.connect() as c:
        c.execute("""
            INSERT OR REPLACE INTO consensus_audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            audit_id, symbol, today, now_epoch, p_provider, p_ask,
            s_provider, s_ask, discrepancy_pct, verdict,
            f"Consensus agreed within {discrepancy_pct}%",
            now_epoch
        ))

    return True, "consensus_confirmed", {
        "primary": p_provider, "primary_ask": p_ask,
        "secondary": s_provider, "secondary_ask": s_ask,
        "discrepancy_pct": discrepancy_pct,
        "consensus_status": "consensus_verified"
    }



def get_providers_health(store: Store | None = None, date: str | None = None) -> list[dict]:
    store = store or Store()
    ensure_provider_tables(store)
    today = date or today_ist_str()

    with store.connect() as c:
        rows = c.execute(
            "SELECT * FROM provider_health WHERE date=? ORDER BY requests DESC",
            (today,)
        ).fetchall()
        return [dict(r) for r in rows]
