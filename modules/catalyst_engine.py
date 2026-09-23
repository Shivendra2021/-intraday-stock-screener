"""
modules/catalyst_engine.py — Point-in-Time Catalyst & News Intelligence Engine.

Enforces strict point-in-time integrity:
- Every event has explicit published_at (external event time) and ingested_at (system time).
- In backtesting/replay and live confirmation, ONLY events with published_at <= decision_ts
  are included. Any news with published_at > decision_ts is discarded (zero forward leakage).
- Quantitative structured flags only (no LLM buy/sell decisions).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

from modules.quant_store import Store, dumps

LOG = logging.getLogger(__name__)


def ensure_catalyst_tables(store: Optional[Store] = None) -> None:
    """Ensure catalyst_events schema exists in quant.db."""
    store = store or Store()
    with store.connect() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS catalyst_events (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                published_at INTEGER NOT NULL,
                ingested_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                headline TEXT NOT NULL,
                category TEXT NOT NULL,
                high_impact INTEGER NOT NULL DEFAULT 0,
                raw_payload TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_cat_sym_time ON catalyst_events(symbol, published_at);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_cat_pub_time ON catalyst_events(published_at);")


def classify_catalyst(headline: str, text: str = "") -> Tuple[str, bool]:
    """
    Classify catalyst into structured category and detect high-impact threshold.
    Returns: (category, is_high_impact)
    """
    content = (headline + " " + text).lower()
    category = "general"
    high_impact = False

    # High impact triggers
    if any(w in content for w in ("usfda", "fda approval", "500 cr", "1000 cr", "block deal", "sebi clearance")):
        high_impact = True

    if any(w in content for w in ("order", "contract", "bagged", "secured", "tender", "deal", "awarded")):
        category = "order_win"
        if any(w in content for w in ("cr", "crore", "million", "billion")):
            high_impact = True
    elif any(w in content for w in ("profit", "revenue", "results", "q1", "q2", "q3", "q4", "ebitda", "net profit", "earnings")):
        category = "earnings"
        if any(w in content for w in ("surges", "jumps", "doubles", "up 50%", "up 100%", "beats")):
            high_impact = True
    elif any(w in content for w in ("approv", "fda", "usfda", "clearance", "patent", "license", "licence", "regulatory", "sebi")):
        category = "regulatory"
        high_impact = True
    elif any(w in content for w in ("acquisition", "stake", "merger", "buyout", "takeover")):
        category = "corporate_action"
        high_impact = True
    elif any(w in content for w in ("expansion", "plant", "capex", "capacity", "facility")):
        category = "capex_expansion"
    elif any(w in content for w in ("target", "upgrade", "buy call", "brokerage")):
        category = "brokerage_upgrade"

    return category, high_impact


def record_catalyst_event(
    symbol: str,
    headline: str,
    published_at: int,
    source: str = "news",
    category: Optional[str] = None,
    high_impact: Optional[bool] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
    store: Optional[Store] = None,
) -> str:
    """
    Persist an external catalyst event with immutable timestamps into quant.db.
    """
    sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    headline = headline.strip()
    if not headline or published_at <= 0:
        raise ValueError("Valid headline and published_at epoch required")

    derived_cat, derived_hi = classify_catalyst(headline)
    final_cat = category or derived_cat
    final_hi = 1 if (high_impact if high_impact is not None else derived_hi) else 0

    ingested_at = int(time.time())
    # Deterministic ID preventing duplicate insertions
    seed = f"{sym}:{published_at}:{headline}"
    event_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    payload_json = dumps(raw_payload or {})

    store = store or Store()
    ensure_catalyst_tables(store)
    with store.connect() as c:
        c.execute("""
            INSERT OR REPLACE INTO catalyst_events
            (id, symbol, published_at, ingested_at, source, headline, category, high_impact, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (event_id, sym, int(published_at), ingested_at, source, headline, final_cat, final_hi, payload_json))

    return event_id


def get_point_in_time_catalysts(
    symbol: str,
    decision_ts: int,
    lookback_hours: float = 24.0,
    store: Optional[Store] = None,
) -> Dict[str, Any]:
    """
    Retrieve structured catalyst features strictly known prior to decision_ts.
    Guarantee: ANY event with published_at > decision_ts is completely excluded.
    """
    sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    store = store or Store()
    ensure_catalyst_tables(store)

    min_ts = int(decision_ts - (lookback_hours * 3600))

    with store.connect() as c:
        rows = c.execute("""
            SELECT id, symbol, published_at, source, headline, category, high_impact
            FROM catalyst_events
            WHERE symbol = ?
              AND published_at >= ?
              AND published_at <= ?
            ORDER BY published_at DESC
        """, (sym, min_ts, decision_ts)).fetchall()

    if not rows:
        return {
            "news_exists_before_signal": 0,
            "minutes_since_news": -1.0,
            "news_count_2h": 0,
            "earnings_flag": 0,
            "order_win_flag": 0,
            "regulatory_flag": 0,
            "high_impact_flag": 0,
            "latest_headline": "",
            "latest_category": "",
            "event_count": 0,
        }

    latest = rows[0]
    minutes_since = max(0.0, round((decision_ts - latest["published_at"]) / 60.0, 1))

    # 2-hour window count
    cutoff_2h = decision_ts - 7200
    news_2h = sum(1 for r in rows if r["published_at"] >= cutoff_2h)

    earnings = int(any(r["category"] in ("earnings", "earnings_beat", "financial_results") for r in rows))
    order_win = int(any(r["category"] in ("order_win", "contract", "deal") for r in rows))
    regulatory = int(any(r["category"] in ("regulatory", "regulatory_approval", "fda_approval") for r in rows))
    high_impact = int(any(r["high_impact"] == 1 for r in rows))

    return {
        "news_exists_before_signal": 1,
        "minutes_since_news": minutes_since,
        "news_count_2h": news_2h,
        "earnings_flag": earnings,
        "order_win_flag": order_win,
        "regulatory_flag": regulatory,
        "high_impact_flag": high_impact,
        "latest_headline": latest["headline"],
        "latest_category": latest["category"],
        "event_count": len(rows),
    }
