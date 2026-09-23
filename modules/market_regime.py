"""
modules/market_regime.py — Deterministic Point-in-Time Market Regime & Sector Context Engine
No look-ahead information. Strictly uses completed candles prior to the decision timestamp.
"""
from __future__ import annotations

import datetime as dt
import logging
import numpy as np
import pandas as pd
import time

from modules.quant_store import Store
from modules.quant_time import now_ist, today_ist_str

LOG = logging.getLogger(__name__)

REGIMES = ("TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL", "LOW_VOL", "MIXED")


def ensure_regime_tables(store: Store | None = None) -> None:
    store = store or Store()
    with store.connect() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS market_regimes (
                date TEXT NOT NULL,
                ts INTEGER NOT NULL,
                regime_label TEXT NOT NULL,
                nifty_return_15m REAL,
                nifty_return_60m REAL,
                nifty_vs_vwap REAL,
                advance_decline_ratio REAL,
                percent_above_vwap REAL,
                india_vix REAL,
                vix_change_pct REAL,
                market_breadth REAL,
                provenance TEXT NOT NULL,
                PRIMARY KEY(date, ts)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS sector_snapshots (
                date TEXT NOT NULL,
                ts INTEGER NOT NULL,
                sector TEXT NOT NULL,
                return_15m REAL,
                return_60m REAL,
                sector_rvol REAL,
                sector_rank INTEGER,
                breadth_pct REAL,
                PRIMARY KEY(date, ts, sector)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_regime_date ON market_regimes(date);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sector_snap_date ON sector_snapshots(date, ts);")


def compute_market_regime(
    store: Store | None,
    asof: pd.Timestamp | dt.datetime | str,
    nifty_bars: pd.DataFrame | None = None,
    provenance: str = "live"
) -> dict:
    """
    Compute point-in-time market regime using only completed index bars up to asof.
    """
    store = store or Store()
    ensure_regime_tables(store)

    asof_ts = pd.Timestamp(asof)
    if asof_ts.tz is None:
        asof_ts = asof_ts.tz_localize("Asia/Kolkata")
    else:
        asof_ts = asof_ts.tz_convert("Asia/Kolkata")

    date_str = str(asof_ts.date())
    epoch_ts = int(asof_ts.timestamp())

    # Check cache in DB
    with store.connect() as c:
        row = c.execute(
            "SELECT * FROM market_regimes WHERE date=? AND ts=?",
            (date_str, epoch_ts)
        ).fetchone()
        if row:
            return dict(row)

    if nifty_bars is None or nifty_bars.empty:
        nifty_bars = store.bars("^NSEI", "5m")

    default_regime = {
        "date": date_str,
        "ts": epoch_ts,
        "regime_label": "MIXED",
        "nifty_return_15m": 0.0,
        "nifty_return_60m": 0.0,
        "nifty_vs_vwap": 0.0,
        "advance_decline_ratio": 1.0,
        "percent_above_vwap": 50.0,
        "india_vix": 14.0,
        "vix_change_pct": 0.0,
        "market_breadth": 0.0,
        "provenance": provenance
    }

    if nifty_bars is None or nifty_bars.empty:
        return default_regime

    # Point-in-time strict slice: candle must be completed before asof
    complete = nifty_bars[nifty_bars.index + pd.Timedelta(minutes=5) <= asof_ts]
    day = complete[complete.index.date == asof_ts.date()]

    if len(day) < 3:
        return default_regime

    px = float(day["close"].iloc[-1])
    op = float(day["open"].iloc[0])
    high = float(day["high"].max())
    low = float(day["low"].min())

    ret_15m = float((px / day["close"].iloc[-3] - 1) * 100) if len(day) >= 3 else 0.0
    ret_60m = float((px / day["close"].iloc[-12] - 1) * 100) if len(day) >= 12 else float((px / op - 1) * 100)

    # Intraday VWAP of Nifty
    typical = (day["high"] + day["low"] + day["close"]) / 3
    vol = day["volume"]
    total_vol = vol.sum()
    vwap = float((typical * vol).sum() / total_vol) if total_vol > 0 else px
    vwap_dist = float((px / vwap - 1) * 100) if vwap > 0 else 0.0

    day_range_pct = float((high - low) / op * 100) if op > 0 else 0.0

    # Deterministic Classification
    if ret_15m > 0.08 and vwap_dist > 0.03 and px > op:
        regime = "TREND_UP"
    elif ret_15m < -0.08 and vwap_dist < -0.03 and px < op:
        regime = "TREND_DOWN"
    elif day_range_pct > 1.5:
        regime = "HIGH_VOL"
    elif day_range_pct < 0.35 and abs(ret_15m) < 0.10:
        regime = "LOW_VOL"
    elif abs(vwap_dist) < 0.10 and abs(ret_15m) < 0.15:
        regime = "RANGE"
    else:
        regime = "MIXED"

    result = {
        "date": date_str,
        "ts": epoch_ts,
        "regime_label": regime,
        "nifty_return_15m": round(ret_15m, 4),
        "nifty_return_60m": round(ret_60m, 4),
        "nifty_vs_vwap": round(vwap_dist, 4),
        "advance_decline_ratio": 1.0,
        "percent_above_vwap": 50.0,
        "india_vix": 14.0,
        "vix_change_pct": 0.0,
        "market_breadth": round(ret_60m, 4),
        "provenance": provenance
    }

    with store.connect() as c:
        c.execute("""
            INSERT OR REPLACE INTO market_regimes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            result["date"], result["ts"], result["regime_label"],
            result["nifty_return_15m"], result["nifty_return_60m"],
            result["nifty_vs_vwap"], result["advance_decline_ratio"],
            result["percent_above_vwap"], result["india_vix"],
            result["vix_change_pct"], result["market_breadth"],
            result["provenance"]
        ))

    return result


def compute_sector_metrics(
    store: Store | None,
    asof: pd.Timestamp | dt.datetime | str,
    stock_returns: dict[str, float],
    sector_map: dict[str, str]
) -> dict:
    """
    Compute sector rankings and relative strengths for all active sectors.
    """
    store = store or Store()
    ensure_regime_tables(store)

    asof_ts = pd.Timestamp(asof)
    if asof_ts.tz is None:
        asof_ts = asof_ts.tz_localize("Asia/Kolkata")
    else:
        asof_ts = asof_ts.tz_convert("Asia/Kolkata")

    date_str = str(asof_ts.date())
    epoch_ts = int(asof_ts.timestamp())

    sectors_data: dict[str, list[float]] = {}
    for sym, ret in stock_returns.items():
        sec = sector_map.get(sym, "Unknown")
        if sec and sec != "Unknown":
            sectors_data.setdefault(sec, []).append(ret)

    sector_medians = []
    for sec, rets in sectors_data.items():
        if rets:
            med = float(np.median(rets))
            breadth = float(sum(r > 0 for r in rets) / len(rets) * 100)
            sector_medians.append({"sector": sec, "return_15m": round(med, 2), "breadth_pct": round(breadth, 1)})

    sector_medians.sort(key=lambda s: s["return_15m"], reverse=True)
    ranked_sectors = {}

    with store.connect() as c:
        for rank, s in enumerate(sector_medians, start=1):
            s["sector_rank"] = rank
            ranked_sectors[s["sector"]] = s
            c.execute("""
                INSERT OR REPLACE INTO sector_snapshots (date, ts, sector, return_15m, return_60m, sector_rvol, sector_rank, breadth_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (date_str, epoch_ts, s["sector"], s["return_15m"], s["return_15m"], 1.0, rank, s["breadth_pct"]))

    return ranked_sectors


def get_latest_market_regime(store: Store | None, date: str) -> dict | None:
    """Retrieve the latest computed market regime snapshot for the given date."""
    store = store or Store()
    ensure_regime_tables(store)
    with store.connect() as c:
        row = c.execute("SELECT * FROM market_regimes WHERE date=? ORDER BY ts DESC LIMIT 1", (date,)).fetchone()
    return dict(row) if row else None


def get_latest_sector_snapshots(store: Store | None, date: str) -> list[dict]:
    """Retrieve the latest computed sector snapshots for the given date."""
    store = store or Store()
    ensure_regime_tables(store)
    with store.connect() as c:
        # Get latest timestamp on that date
        latest_ts_row = c.execute("SELECT MAX(ts) FROM sector_snapshots WHERE date=?", (date,)).fetchone()
        if not latest_ts_row or not latest_ts_row[0]:
            return []
        latest_ts = latest_ts_row[0]
        rows = c.execute("SELECT * FROM sector_snapshots WHERE date=? AND ts=? ORDER BY sector_rank ASC", (date, latest_ts)).fetchall()
    return [dict(r) for r in rows]

