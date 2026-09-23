"""
modules/winner_discovery.py — Post-Market Full-Universe Winner Discovery Lab (Research Only)
Studies all major intraday movers (>= 7% and >= 10%) without altering live production weights.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
import time
import pandas as pd
import numpy as np

from modules.quant_store import Store, dumps
from modules.quant_time import now_ist, today_ist_str

LOG = logging.getLogger(__name__)


def ensure_winner_tables(store: Store | None = None) -> None:
    store = store or Store()
    with store.connect() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS winner_discovery (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                sector TEXT NOT NULL,
                session_open REAL NOT NULL,
                prev_close REAL NOT NULL,
                day_high REAL NOT NULL,
                day_low REAL NOT NULL,
                day_close REAL NOT NULL,
                max_return_pct REAL NOT NULL,
                close_return_pct REAL NOT NULL,
                is_runner_7pct INTEGER NOT NULL,
                is_runner_10pct INTEGER NOT NULL,
                pre_move_features TEXT NOT NULL,
                rejection_by_quant TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_winner_date ON winner_discovery(date);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_winner_runners ON winner_discovery(date, is_runner_7pct);")


def extract_pre_move_features(bars_5m: pd.DataFrame, daily_base: dict | None) -> dict:
    """Extract features strictly available in the opening window (first 3-4 bars) before the move."""
    if bars_5m.empty:
        return {}

    opening = bars_5m.iloc[:3]  # 09:15, 09:20, 09:25
    op = float(bars_5m["open"].iloc[0])
    high_orb = float(opening["high"].max())
    low_orb = float(opening["low"].min())
    vol_orb = float(opening["volume"].sum())

    prev_close = float(daily_base.get("prev_close", op)) if daily_base else op
    gap_pct = round((op / prev_close - 1) * 100, 2) if prev_close > 0 else 0.0
    orb_range_pct = round((high_orb - low_orb) / op * 100, 2) if op > 0 else 0.0

    typical = (opening["high"] + opening["low"] + opening["close"]) / 3
    vwap_orb = float((typical * opening["volume"]).sum() / vol_orb) if vol_orb > 0 else op

    return {
        "gap_pct": gap_pct,
        "orb_range_pct": orb_range_pct,
        "vwap_distance_orb": round((float(opening["close"].iloc[-1]) / vwap_orb - 1) * 100, 2),
        "atr_pct": daily_base.get("atr_pct", 2.5) if daily_base else 2.5,
        "daily_trend": daily_base.get("daily_trend", 0.0) if daily_base else 0.0,
        "turnover": daily_base.get("turnover", 0.0) if daily_base else 0.0,
    }


def analyze_session_winners(
    store: Store | None = None,
    date: str | None = None,
    threshold_pct: float = 7.0,
    universe_symbols: dict[str, str] | None = None
) -> dict:
    """
    Scan full universe after market close to identify all intraday runners >= 7%.
    Store findings for research and hypothesis generation.
    NEVER modifies production weights or parameters.
    """
    store = store or Store()
    ensure_winner_tables(store)
    session_date = date or today_ist_str()
    now_epoch = int(time.time())

    from modules.quant_data import universe
    symbols = universe_symbols or universe()

    # Get official Quant signals published today to cross-reference
    official_signals = {s["symbol"] for s in store.signals(session_date)}

    # Get rejections recorded in observations for this session
    with store.connect() as c:
        obs_rows = c.execute(
            "SELECT symbol, reason FROM observations WHERE date=?",
            (session_date,)
        ).fetchall()
        observed_rejections = {r["symbol"]: r["reason"] for r in obs_rows}

    winners = []
    runners_7 = 0
    runners_10 = 0

    for symbol, sector in symbols.items():
        bars_1d = store.bars(symbol, "1d")
        bars_5m = store.bars(symbol, "5m")

        if bars_5m.empty:
            continue

        day_bars = bars_5m[bars_5m.index.date == dt.date.fromisoformat(session_date)]
        if len(day_bars) < 10:
            continue

        op = float(day_bars["open"].iloc[0])
        hi = float(day_bars["high"].max())
        lo = float(day_bars["low"].min())
        cl = float(day_bars["close"].iloc[-1])

        if op <= 0:
            continue

        prev_close = op
        if not bars_1d.empty:
            hist_1d = bars_1d[bars_1d.index.date < dt.date.fromisoformat(session_date)]
            if not hist_1d.empty:
                prev_close = float(hist_1d["close"].iloc[-1])

        max_ret = round((hi / op - 1) * 100, 2)
        close_ret = round((cl / op - 1) * 100, 2)

        is_7 = int(max_ret >= threshold_pct)
        is_10 = int(max_ret >= 10.0)

        if is_7:
            runners_7 += 1
        if is_10:
            runners_10 += 1

        if is_7 or max_ret >= 5.0:
            # Determine why Quant V4 picked or rejected this mover
            if symbol in official_signals:
                quant_status = "selected_by_quant"
            elif symbol in observed_rejections:
                quant_status = f"rejected:{observed_rejections[symbol]}"
            else:
                quant_status = "not_in_morning_watchlist"

            daily_features = {"prev_close": prev_close, "atr_pct": round(float((hi - lo) / op * 100), 2)}
            pre_features = extract_pre_move_features(day_bars, daily_features)

            winner_id = f"win:{session_date}:{symbol}"
            with store.connect() as c:
                c.execute("""
                    INSERT OR REPLACE INTO winner_discovery (
                        id, date, symbol, sector, session_open, prev_close,
                        day_high, day_low, day_close, max_return_pct, close_return_pct,
                        is_runner_7pct, is_runner_10pct, pre_move_features,
                        rejection_by_quant, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    winner_id, session_date, symbol, sector, op, prev_close,
                    hi, lo, cl, max_ret, close_ret, is_7, is_10,
                    dumps(pre_features), quant_status, now_epoch
                ))

            winners.append({
                "symbol": symbol,
                "sector": sector,
                "max_return_pct": max_ret,
                "close_return_pct": close_ret,
                "is_runner_7pct": bool(is_7),
                "is_runner_10pct": bool(is_10),
                "quant_status": quant_status,
                "pre_move_features": pre_features
            })

    winners.sort(key=lambda w: w["max_return_pct"], reverse=True)

    result = {
        "date": session_date,
        "scanned_universe": len(symbols),
        "runners_7pct_count": runners_7,
        "runners_10pct_count": runners_10,
        "top_winners": winners[:20],
        "research_note": "Winner discovery is isolated research; production model weights remain unchanged."
    }

    store.put(f"winner_discovery:{session_date}", result)
    return result


def get_winner_discovery_report(store: Store | None = None, date: str | None = None) -> dict:
    store = store or Store()
    ensure_winner_tables(store)
    session_date = date or today_ist_str()

    cached = store.get(f"winner_discovery:{session_date}")
    if cached:
        return cached

    with store.connect() as c:
        rows = c.execute("""
            SELECT * FROM winner_discovery
            WHERE date=?
            ORDER BY max_return_pct DESC
            LIMIT 50
        """, (session_date,)).fetchall()

        runners_7 = sum(r["is_runner_7pct"] for r in rows)
        runners_10 = sum(r["is_runner_10pct"] for r in rows)

        return {
            "date": session_date,
            "scanned_universe": len(rows),
            "runners_7pct_count": runners_7,
            "runners_10pct_count": runners_10,
            "top_winners": [{**dict(r), "pre_move_features": json.loads(r["pre_move_features"])} for r in rows],
            "research_note": "Winner discovery is isolated research; production model weights remain unchanged."
        }
