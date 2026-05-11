"""Live intraday pattern scanner for small-cap 7%+ move setups.

Research/advisory only. This module does not place trades.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

HOT_THEMES = {
    "DEFENCE_INFRA",
    "REAL_ESTATE",
    "AUTO_ANCILLARY",
    "SPECIALITY_CHEM",
    "RAIL_DEFENCE",
    "LOGISTICS",
    "PHARMA",
    "GREEN_ENERGY",
    "5G_TELECOM",
    "ELECTRONICS",
    "AGROCHEM",
    "HOME_INFRA",
    "MEDIA_DIGITAL",
    "EV_AUTO",
}

TRENDLYNE_SECTORS = [
    "Banking & Finance",
    "Commercial Services",
    "Div. Consumer Services",
    "Pharma & Biotech",
    "Utilities",
    "Retailing",
    "Metals & Mining",
    "Hardware Tech",
    "Transportation",
    "Healthcare",
    "Media",
    "Realty",
    "Chemicals & Petrochem",
    "Diversified",
    "Consumer Durables",
    "Automobiles",
    "General Industrials",
    "Forest Materials",
    "Telecom Equipment",
]

PRIORITY_SECTORS = {
    "General Industrials": 1,
    "Commercial Services": 2,
    "Realty": 3,
    "Chemicals & Petrochem": 4,
    "Automobiles": 5,
}

THEME_KEYWORDS = {
    "DEFENCE_INFRA": {"BIRLA", "BEL", "BDL", "HAL", "PARAS", "ZENTEC", "DYNAMATECH", "MAZDOCK", "COCHINSHIP"},
    "REAL_ESTATE": {"DLF", "LODHA", "OBEROIRLTY", "GODREJPROP", "SOBHA", "PRESTIGE", "BRIGADE"},
    "AUTO_ANCILLARY": {"MOTHERSON", "CRAFTSMAN", "NRBBEARING", "AUTO", "MINDACORP", "SONACOMS"},
    "SPECIALITY_CHEM": {"CHEM", "ALKYL", "AARTI", "DEEPAK", "FLUORO", "TATVA", "CHEMFAB"},
    "RAIL_DEFENCE": {"RAIL", "IRCON", "RVNL", "TITAGARH", "BEML", "RITES", "TEXRAIL"},
    "LOGISTICS": {"LOG", "TCI", "MAHLOG", "GATEWAY", "VRL", "TIGERLOGS"},
    "PHARMA": {"PHARMA", "HEAL", "DRUG", "LIFE", "BIO", "MED"},
    "GREEN_ENERGY": {"GREEN", "SOLAR", "WAAREE", "SUZLON", "OLECTRA", "KPI"},
    "5G_TELECOM": {"HFCL", "ITI", "TEJAS", "RAILTEL", "SUBEX", "STLTECH"},
    "ELECTRONICS": {"DIXON", "AVALON", "KAYNES", "PGEL", "CENTUM"},
    "AGROCHEM": {"AGRO", "CROP", "INSECT", "PIIND", "DHANUKA"},
    "HOME_INFRA": {"CABLE", "PIPE", "PLY", "WIRE", "POLYCAB", "KEI", "HAVELLS"},
    "MEDIA_DIGITAL": {"TV", "MEDIA", "DIGI", "QUICKHEAL", "NAZARA"},
    "EV_AUTO": {"OLECTRA", "GREAVES", "TATAMOTORS", "JBM", "SMLISUZU"},
}

SECTOR_KEYWORDS = {
    "Banking & Finance": {"BANK", "FIN", "CAP", "CREDIT", "SEC"},
    "Commercial Services": {"SERV", "INFO", "SOFT", "DIGI", "TECH", "QUICKHEAL"},
    "Pharma & Biotech": {"PHARMA", "DRUG", "BIO", "LIFE", "HEALTH"},
    "Utilities": {"POWER", "ENERGY", "GRID", "GAS"},
    "Retailing": {"RETAIL", "MART", "SHOP", "FOOD"},
    "Metals & Mining": {"STEEL", "METAL", "MINE", "ZINC", "ALUM"},
    "Hardware Tech": {"TECH", "ELECT", "AVALON", "DIXON", "KAYNES"},
    "Transportation": {"LOG", "RAIL", "PORT", "SHIP", "TRANS"},
    "Healthcare": {"HOSP", "CARE", "METROPOLIS", "THYRO"},
    "Media": {"MEDIA", "TV", "DIGITAL", "ENT"},
    "Realty": {"REAL", "PROP", "DLF", "SOBHA", "LODHA"},
    "Chemicals & Petrochem": {"CHEM", "PETRO", "FLUOR", "ALKYL"},
    "Consumer Durables": {"CABLE", "WIRE", "HOME", "DURABLE", "HAVELLS"},
    "Automobiles": {"AUTO", "MOTOR", "BEARING", "CRAFTSMAN", "TYRE"},
    "General Industrials": {"IND", "INFRA", "CABLE", "ENGINE", "PREC", "CAST", "FAB"},
    "Telecom Equipment": {"TELE", "SUBEX", "HFCL", "ITI", "TEJAS"},
}

PATTERN_OUTPUTS = {
    "UPPER_CIRCUIT": {
        "confidence": 90,
        "expected_return_pct": "18-20%",
        "entry_rule": "Bid at UC price at 09:15. If UC holds past 09:30, position locked.",
        "exit_rule": "Hold till 15:15. EXIT IMMEDIATELY if UC breaks at any point.",
        "stop_loss": "UC break = full exit, no averaging",
        "position_size_pct": 1,
        "risk_level": "HIGH",
    },
    "GAP_AND_GO": {
        "confidence": 75,
        "expected_return_pct": "12-20%",
        "entry_rule": "Enter at 09:30 if gap holding. Buy on first 1-2% pullback after open.",
        "exit_rule": "Target HOD extension. Partial exit at +8%, trail stop rest.",
        "stop_loss": "Below pre-market/previous close price (gap level)",
        "position_size_pct": 2,
        "risk_level": "MEDIUM",
    },
    "SECTOR_BREAKOUT": {
        "confidence": 65,
        "expected_return_pct": "7-12%",
        "entry_rule": "Enter on HOD break with volume. Time window: 10:00 to 11:30 only.",
        "exit_rule": "Target R:R 1:2. Partial at +5%, trail stop to entry for rest.",
        "stop_loss": "Below Opening Range Low (low of first 15 min candle)",
        "position_size_pct": 3,
        "risk_level": "LOW-MEDIUM",
    },
}

_agent_thread: threading.Thread | None = None
_agent_running = False


@dataclass
class TimingState:
    phase: str
    allow_new_entries: bool
    allow_uc: bool
    allow_gap: bool
    allow_breakout: bool


def _num(value: Any, default: float = 0.0) -> float:
    try:
        val = float(value)
        return default if math.isnan(val) or math.isinf(val) else val
    except Exception:
        return default


def _now_ist() -> dt.datetime:
    return dt.datetime.now()


def timing_state(now: dt.datetime | None = None) -> TimingState:
    now = now or _now_ist()
    t = now.time()
    def between(start: str, end: str) -> bool:
        s = dt.time.fromisoformat(start)
        e = dt.time.fromisoformat(end)
        return s <= t < e

    if between("09:00", "09:15"):
        return TimingState("PRE_MARKET", False, False, False, False)
    if between("09:15", "09:20"):
        return TimingState("UC_SCAN", True, True, False, False)
    if between("09:20", "09:30"):
        return TimingState("GAP_SCAN", True, False, True, False)
    if between("09:30", "10:00"):
        return TimingState("GAP_HOLD_CHECK", True, False, True, False)
    if between("10:00", "11:30"):
        return TimingState("BREAKOUT_WINDOW", True, False, False, True)
    if between("11:30", "13:00"):
        return TimingState("HOLD_ONLY", False, False, False, False)
    if between("13:00", "14:30"):
        return TimingState("DEAD_ZONE", False, False, False, False)
    if between("14:30", "15:00"):
        return TimingState("EOD_MOMENTUM", False, False, False, False)
    if between("15:00", "15:15"):
        return TimingState("EXIT_ALL", False, False, False, False)
    if t >= dt.time.fromisoformat("15:15"):
        return TimingState("MARKET_CLOSED", False, False, False, False)
    return TimingState("OFF_HOURS", False, False, False, False)


def _init_tables() -> None:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS intraday_pattern_alerts (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               timestamp TEXT,
               symbol TEXT,
               pattern TEXT,
               confidence_score REAL,
               alert_tier TEXT,
               payload_json TEXT,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP,
               UNIQUE(date, symbol, pattern)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS intraday_sector_heatmap (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               timestamp TEXT,
               sector TEXT,
               sector_avg_change_pct REAL,
               sector_advance_count INTEGER,
               sector_decline_count INTEGER,
               sector_7plus_count INTEGER,
               sector_momentum_score REAL,
               is_hot INTEGER,
               payload_json TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS intraday_pattern_daily_report (
               date TEXT PRIMARY KEY,
               report_json TEXT,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.commit()


def infer_sector(symbol: str) -> str:
    sym = symbol.upper()
    try:
        from modules.stock_selector import SECTOR_UNIVERSE

        for sector, symbols in SECTOR_UNIVERSE.items():
            if sym in symbols:
                return {
                    "IT": "Commercial Services",
                    "Finance": "Banking & Finance",
                    "Auto": "Automobiles",
                    "Pharma": "Pharma & Biotech",
                    "Metals": "Metals & Mining",
                    "Energy": "Utilities",
                    "Infra": "General Industrials",
                    "Cement": "General Industrials",
                    "Smallcap": "Diversified",
                }.get(sector, sector)
    except Exception:
        pass

    for sector, keywords in SECTOR_KEYWORDS.items():
        if any(k in sym for k in keywords):
            return sector
    return "Diversified"


def infer_theme(symbol: str, sector: str) -> str:
    sym = symbol.upper()
    for theme, keywords in THEME_KEYWORDS.items():
        if any(k in sym for k in keywords):
            return theme
    if sector == "Realty":
        return "REAL_ESTATE"
    if sector == "Automobiles":
        return "AUTO_ANCILLARY"
    if sector == "Chemicals & Petrochem":
        return "SPECIALITY_CHEM"
    if sector == "Telecom Equipment":
        return "5G_TELECOM"
    if sector == "Pharma & Biotech":
        return "PHARMA"
    return "UNKNOWN"


def _universe(limit: int | None = None) -> list[str]:
    from modules.scanner import get_universe

    symbols = []
    for symbol in get_universe():
        sym = str(symbol).strip().upper().replace(".NS", "")
        if not sym or sym.isdigit() or any(ch.isspace() for ch in sym):
            continue
        symbols.append(sym)

    priority = {sector: rank for sector, rank in PRIORITY_SECTORS.items()}
    symbols.sort(key=lambda s: (priority.get(infer_sector(s), 99), s))
    return symbols[:limit] if limit else symbols


def _fetch_realtime_batch(symbols: list[str]) -> list[dict[str, Any]]:
    import yfinance as yf
    from modules.fetch import SYMBOL_ALIASES

    tickers = []
    reverse = {}
    for symbol in symbols:
        alias = SYMBOL_ALIASES.get(symbol, symbol)
        ticker = f"{alias}.NS"
        tickers.append(ticker)
        reverse[ticker] = symbol

    if not tickers:
        return []

    try:
        df = yf.download(
            tickers,
            period="5d",
            interval="5m",
            auto_adjust=True,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.debug("Pattern batch download failed: %s", exc)
        return []

    if df is None or df.empty:
        return []

    rows = []
    today = dt.date.today()
    for ticker in tickers:
        try:
            raw = df[ticker] if isinstance(df.columns, pd.MultiIndex) else df
            raw = raw.dropna(how="all")
            if raw.empty:
                continue
            raw.columns = [str(c).lower() for c in raw.columns]
            day = raw[pd.to_datetime(raw.index).date == today]
            if day.empty:
                day = raw.tail(min(75, len(raw)))
            if day.empty or len(day) < 1:
                continue

            hist = raw[pd.to_datetime(raw.index).date < today]
            daily = hist.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
            prev_close = _num(daily["close"].iloc[-1]) if not daily.empty else _num(day["open"].iloc[0])
            avg_daily_volume = _num(daily["volume"].tail(20).mean()) if not daily.empty else _num(day["volume"].sum())
            avg_daily_volume_inr = avg_daily_volume * prev_close

            first = day.iloc[0]
            latest = day.iloc[-1]
            first_15 = day.iloc[:3] if len(day) >= 3 else day
            range_45 = day.iloc[:9] if len(day) >= 9 else day
            current_price = _num(latest["close"])
            open_price = _num(first["open"])
            high_price = _num(day["high"].max())
            low_price = _num(day["low"].min())
            current_volume = _num(day["volume"].sum())
            volume_15 = _num(first_15["volume"].sum())
            avg_volume_per_min = avg_daily_volume / 375 if avg_daily_volume > 0 else 0
            sector = infer_sector(reverse[ticker])
            theme = infer_theme(reverse[ticker], sector)

            rows.append(
                {
                    "symbol": reverse[ticker],
                    "sector": sector,
                    "theme": theme,
                    "current_price": current_price,
                    "open_price": open_price,
                    "high_price": high_price,
                    "low_price": low_price,
                    "prev_close": prev_close,
                    "gap_pct": (open_price - prev_close) / prev_close * 100 if prev_close > 0 else 0,
                    "change_pct": (current_price - prev_close) / prev_close * 100 if prev_close > 0 else 0,
                    "open_to_high_pct": (high_price - open_price) / open_price * 100 if open_price > 0 else 0,
                    "open_to_close_pct": (current_price - open_price) / open_price * 100 if open_price > 0 else 0,
                    "current_volume": current_volume,
                    "volume_first_15min": volume_15,
                    "volume_ratio": current_volume / avg_daily_volume if avg_daily_volume > 0 else 0,
                    "volume_15_ratio": volume_15 / avg_daily_volume if avg_daily_volume > 0 else 0,
                    "avg_daily_volume": avg_daily_volume,
                    "avg_daily_volume_inr": avg_daily_volume_inr,
                    "avg_volume_per_min": avg_volume_per_min,
                    "price_9_15": open_price,
                    "price_9_30": _num(first_15["close"].iloc[-1]),
                    "range_high_09_15_10_00": _num(range_45["high"].max()),
                    "range_low_09_15_10_00": _num(range_45["low"].min()),
                    "range_volume_09_15_10_00": _num(range_45["volume"].sum()),
                    "market_cap_cr": _estimate_market_cap_cr(reverse[ticker], current_price, avg_daily_volume_inr),
                    "upper_circuit_price": _estimate_upper_circuit(prev_close),
                    "prev_day_upper_circuit": _estimate_upper_circuit(prev_close),
                    "prev_day_change_pct": _prev_day_change(daily),
                    "weekly_change_pct": _weekly_change(daily),
                    "timestamp": _now_ist().strftime("%H:%M:%S"),
                }
            )
        except Exception as exc:
            logger.debug("Pattern row failed for %s: %s", ticker, exc)
    return rows


def _estimate_market_cap_cr(symbol: str, current_price: float, avg_daily_volume_inr: float) -> float | None:
    """Best-effort cap proxy using liquidity, without extra Yahoo metadata calls."""
    if current_price <= 0 or avg_daily_volume_inr <= 0:
        return None
    # Conservative liquidity-derived proxy to keep unknowns mostly in watchlist, not Tier 1.
    return min(6000.0, max(250.0, avg_daily_volume_inr / 100_000))


def _estimate_upper_circuit(prev_close: float) -> float:
    return round(prev_close * 1.20, 2) if prev_close > 0 else 0.0


def _prev_day_change(daily: pd.DataFrame) -> float:
    if daily is None or len(daily) < 2:
        return 0.0
    prev = _num(daily["close"].iloc[-2])
    last = _num(daily["close"].iloc[-1])
    return (last - prev) / prev * 100 if prev > 0 else 0.0


def _weekly_change(daily: pd.DataFrame) -> float:
    if daily is None or len(daily) < 5:
        return 0.0
    base = _num(daily["close"].iloc[-5])
    last = _num(daily["close"].iloc[-1])
    return (last - base) / base * 100 if base > 0 else 0.0


def _index_change(symbol: str) -> float:
    import yfinance as yf

    try:
        df = yf.download(symbol, period="2d", interval="5m", auto_adjust=True, progress=False)
        if df is None or df.empty:
            return 0.0
        df.columns = [str(c[0]).lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
        today = df[pd.to_datetime(df.index).date == dt.date.today()]
        if today.empty:
            return 0.0
        open_price = _num(today["open"].iloc[0])
        close_price = _num(today["close"].iloc[-1])
        return (close_price - open_price) / open_price * 100 if open_price > 0 else 0.0
    except Exception:
        return 0.0


def market_context() -> dict[str, Any]:
    nifty = _index_change("^NSEI")
    smallcap = _index_change("^CNXSC")
    return {
        "nifty_change_pct": round(nifty, 3),
        "smallcap_index_change_pct": round(smallcap, 3),
        "nifty_up": nifty > 0,
        "smallcap_index_up": smallcap > 0,
        "market_tailwind": nifty > 0.3 or smallcap > 0.5,
        "market_red_kill": nifty < -0.5,
    }


def sector_heatmap(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("sector") or "Diversified"].append(row)

    heatmap = {}
    for sector in TRENDLYNE_SECTORS:
        members = grouped.get(sector, [])
        changes = [_num(x.get("change_pct")) for x in members]
        avg_change = mean(changes) if changes else 0.0
        advance = sum(1 for x in changes if x > 0)
        decline = sum(1 for x in changes if x < 0)
        plus7 = sum(1 for x in changes if x >= 7)
        total = len(changes)
        score = (advance / total * avg_change) if total else 0.0
        heatmap[sector] = {
            "sector": sector,
            "sector_avg_change_pct": round(avg_change, 3),
            "sector_advance_count": advance,
            "sector_decline_count": decline,
            "sector_7plus_count": plus7,
            "sector_momentum_score": round(score, 3),
            "is_hot": score > 1.5 and plus7 >= 3,
            "symbols": [x["symbol"] for x in members],
        }
    return heatmap


def _sector_peers_active(row: dict[str, Any], rows: list[dict[str, Any]], min_change: float = 0.0) -> list[str]:
    return [
        r["symbol"]
        for r in rows
        if r["symbol"] != row["symbol"]
        and r.get("sector") == row.get("sector")
        and _num(r.get("change_pct")) > min_change
    ][:8]


def mandatory_filter(row: dict[str, Any], rows: list[dict[str, Any]], context: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    labels: list[str] = []
    missing_or_failed: list[str] = []

    market_cap = row.get("market_cap_cr")
    if market_cap is not None and _num(market_cap, 999999) < _cfg("INTRADAY_PATTERN_MARKET_CAP_MAX_CR", 5000):
        labels.append("micro_small_cap")
    else:
        missing_or_failed.append("market_cap")

    peers = _sector_peers_active(row, rows)
    if len(peers) >= 3:
        labels.append("sector_cluster_active")
    else:
        missing_or_failed.append("sector_cluster_active")

    if context.get("market_tailwind"):
        labels.append("market_tailwind")
    else:
        missing_or_failed.append("market_tailwind")

    if _num(row.get("avg_daily_volume_inr"), 999999999) < _cfg("INTRADAY_PATTERN_LOW_LIQUIDITY_MAX_INR", 50_000_000):
        labels.append("low_liquidity_flag")
    else:
        missing_or_failed.append("low_liquidity_flag")

    if _num(row.get("weekly_change_pct")) > 0:
        labels.append("weekly_uptrend")
    else:
        missing_or_failed.append("weekly_uptrend")

    if row.get("theme") in HOT_THEMES:
        labels.append("hot_theme")
    else:
        missing_or_failed.append("hot_theme")

    prev_uc = _num(row.get("prev_day_upper_circuit"))
    prev_close = _num(row.get("prev_close"))
    if prev_uc > 0 and prev_close / prev_uc > 0.95:
        labels.append("circuit_proximity")
    else:
        missing_or_failed.append("circuit_proximity")

    if _num(row.get("volume_15_ratio")) > 3:
        labels.append("volume_surge_confirmed")
    else:
        missing_or_failed.append("volume_surge_confirmed")

    return len(labels) == 8, labels, missing_or_failed


def classify_pattern(row: dict[str, Any], rows: list[dict[str, Any]], now: dt.datetime | None = None) -> str | None:
    state = timing_state(now)
    peers = _sector_peers_active(row, rows, min_change=1.0)
    price = _num(row.get("current_price"))
    uc = _num(row.get("upper_circuit_price"))
    prev_change = _num(row.get("prev_day_change_pct"))

    if (
        state.allow_uc
        and uc > 0
        and price >= uc * 0.995
        and (prev_change > 10 or _num(row.get("prev_close")) / max(_num(row.get("prev_day_upper_circuit")), 1) > 0.95)
    ):
        return "UPPER_CIRCUIT"

    if (
        state.allow_gap
        and _num(row.get("gap_pct")) >= 7
        and _num(row.get("volume_15_ratio")) > 3
        and _num(row.get("price_9_30")) > _num(row.get("price_9_15"))
        and len(peers) >= 1
    ):
        return "GAP_AND_GO"

    range_high = _num(row.get("range_high_09_15_10_00"))
    break_volume = _num(row.get("current_volume"))
    avg_per_min = _num(row.get("avg_volume_per_min"))
    if (
        state.allow_breakout
        and _num(row.get("gap_pct")) < 5
        and price > range_high > 0
        and avg_per_min > 0
        and break_volume > avg_per_min * 5
        and len(_sector_peers_active(row, rows)) >= 3
    ):
        return "SECTOR_BREAKOUT"

    return None


def confidence_score(row: dict[str, Any], rows: list[dict[str, Any]], context: dict[str, Any]) -> int:
    score = 0
    if context.get("nifty_up") and context.get("smallcap_index_up"):
        score += 20
    elif context.get("nifty_up") or context.get("smallcap_index_up"):
        score += 10

    peer_count = len(_sector_peers_active(row, rows))
    score += min(peer_count * 4, 20)

    vol_ratio = _num(row.get("volume_ratio"))
    if vol_ratio > 10:
        score += 20
    elif vol_ratio > 5:
        score += 15
    elif vol_ratio > 3:
        score += 10
    elif vol_ratio > 2:
        score += 5

    cap = row.get("market_cap_cr")
    if cap is not None:
        cap = _num(cap)
        if cap < 500:
            score += 15
        elif cap < 2000:
            score += 10
        elif cap < 5000:
            score += 5

    if row.get("theme") in HOT_THEMES:
        score += 10

    weekly = _num(row.get("weekly_change_pct"))
    if weekly > 5:
        score += 10
    elif weekly > 0:
        score += 5

    prev_uc = _num(row.get("prev_day_upper_circuit"))
    if prev_uc > 0 and _num(row.get("prev_close")) / prev_uc > 0.95:
        score += 5

    try:
        from modules.ollama_intraday_agent import ollama_intraday_boost

        score += ollama_intraday_boost(row)
    except Exception:
        pass

    return min(100, int(round(score)))


def alert_tier(score: int) -> str:
    if score >= 80:
        return "TIER 1 - STRONG BUY SIGNAL"
    if score >= 60:
        return "TIER 2 - MONITOR CLOSELY"
    if score >= 40:
        return "TIER 3 - ON WATCHLIST"
    return "NO SIGNAL"


def build_alert(row: dict[str, Any], rows: list[dict[str, Any]], context: dict[str, Any], pattern: str, score: int) -> dict[str, Any]:
    price = _num(row.get("current_price"))
    gap = _num(row.get("gap_pct"))
    peers = _sector_peers_active(row, rows, min_change=0.0)
    spec = PATTERN_OUTPUTS[pattern]
    stop = price * 0.92 if pattern == "GAP_AND_GO" else _num(row.get("range_low_09_15_10_00"), price * 0.97)
    if pattern == "UPPER_CIRCUIT":
        stop = _num(row.get("upper_circuit_price"))
    return {
        "timestamp": _now_ist().strftime("%H:%M:%S"),
        "symbol": row["symbol"],
        "pattern": pattern,
        "confidence_score": score,
        "alert_tier": alert_tier(score),
        "current_price": round(price, 2),
        "gap_pct": round(gap, 2),
        "volume_ratio": round(_num(row.get("volume_ratio")), 2),
        "sector": row.get("sector"),
        "sector_peers_active": peers[:5],
        "theme": row.get("theme"),
        "market_cap_cr": round(_num(row.get("market_cap_cr")), 2) if row.get("market_cap_cr") is not None else None,
        "entry_price": round(price, 2),
        "stop_loss": round(stop, 2),
        "target_1": round(price * 1.08, 2),
        "target_2": round(price * 1.16, 2),
        "expected_return_pct": spec["expected_return_pct"],
        "risk_level": spec["risk_level"],
        "position_size_pct": spec["position_size_pct"],
        "exit_latest_by": "15:15",
        "entry_rule": spec["entry_rule"],
        "exit_rule": spec["exit_rule"],
        "notes": (
            f"{len(peers)} peers green in sector. Volume {_num(row.get('volume_ratio')):.1f}x avg. "
            f"Theme: {row.get('theme')}. Nifty {context.get('nifty_change_pct')}%, Smallcap {context.get('smallcap_index_change_pct')}%."
        ),
    }


def _format_alert(alert: dict[str, Any]) -> str:
    return (
        f"<b>{alert['alert_tier']}</b>\n"
        f"<b>{alert['symbol']}</b> - {alert['pattern']} | Score {alert['confidence_score']}\n"
        f"Price: {alert['current_price']} | Gap: {alert['gap_pct']}% | Vol: {alert['volume_ratio']}x\n"
        f"Sector: {alert['sector']} | Theme: {alert['theme']}\n"
        f"Peers: {', '.join(alert['sector_peers_active']) or 'N/A'}\n"
        f"Entry: {alert['entry_price']} | SL: {alert['stop_loss']} | T1: {alert['target_1']} | T2: {alert['target_2']}\n"
        f"Exit by: {alert['exit_latest_by']} | Risk: {alert['risk_level']} | Size: {alert['position_size_pct']}%\n"
        f"{alert['notes']}\n\n"
        "<i>Research only. Not a trade recommendation.</i>"
    )


def _store_heatmap(heatmap: dict[str, dict[str, Any]]) -> None:
    from config import DB_PATH

    today = dt.date.today().isoformat()
    stamp = _now_ist().strftime("%H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        for sector, row in heatmap.items():
            conn.execute(
                """INSERT INTO intraday_sector_heatmap
                   (date, timestamp, sector, sector_avg_change_pct, sector_advance_count,
                    sector_decline_count, sector_7plus_count, sector_momentum_score, is_hot, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    today,
                    stamp,
                    sector,
                    row["sector_avg_change_pct"],
                    row["sector_advance_count"],
                    row["sector_decline_count"],
                    row["sector_7plus_count"],
                    row["sector_momentum_score"],
                    1 if row["is_hot"] else 0,
                    json.dumps(row, ensure_ascii=False),
                ),
            )
        conn.commit()


def _alert_seen(symbol: str, pattern: str) -> bool:
    from config import DB_PATH

    today = dt.date.today().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT 1 FROM intraday_pattern_alerts WHERE date=? AND symbol=? AND pattern=?",
            (today, symbol, pattern),
        ).fetchone()
    return bool(row)


def _store_alert(alert: dict[str, Any]) -> None:
    from config import DB_PATH

    today = dt.date.today().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO intraday_pattern_alerts
               (date, timestamp, symbol, pattern, confidence_score, alert_tier, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                today,
                alert["timestamp"],
                alert["symbol"],
                alert["pattern"],
                alert["confidence_score"],
                alert["alert_tier"],
                json.dumps(alert, ensure_ascii=False),
            ),
        )
        conn.commit()


def _send_alert(alert: dict[str, Any]) -> None:
    from modules.alerts import send_raw_alert

    _store_alert(alert)
    send_raw_alert(_format_alert(alert), review_with_grok=False)


def _learn_from_movers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    movers = [r for r in rows if max(_num(r.get("open_to_high_pct")), _num(r.get("change_pct"))) >= _cfg("INTRADAY_PATTERN_MIN_MOVER_PCT", 7.0)]
    if not movers:
        return {"winner_count": 0, "pattern_count": 0}

    features = []
    for row in movers:
        feature = {
            "symbol": row["symbol"],
            "date": dt.date.today().isoformat(),
            "return_pct": round(max(_num(row.get("open_to_high_pct")), _num(row.get("change_pct"))), 4),
            "open_to_high_pct": round(_num(row.get("open_to_high_pct")), 4),
            "open_to_close_pct": round(_num(row.get("open_to_close_pct")), 4),
            "volume_ratio": round(_num(row.get("volume_ratio")), 4),
            "gap_pct": round(_num(row.get("gap_pct")), 4),
            "rsi": 50.0,
            "adx": 20.0,
            "ema_alignment": "UNKNOWN",
            "sector": row.get("sector"),
            "pattern_key": f"{row.get('sector')}__VOL_{int(_num(row.get('volume_ratio')))}x__GAP_{int(_num(row.get('gap_pct')))}",
            "features_json": row,
        }
        features.append(feature)

    if len(features) < 2:
        _store_after_market_patterns(features, [])
        return {"winner_count": len(features), "pattern_count": 0, "patterns": []}

    from modules.after_market_learning import learn_similarities
    patterns = learn_similarities(features, min_support=2)
    _store_after_market_patterns(features, patterns)
    return {"winner_count": len(features), "pattern_count": len(patterns), "patterns": patterns[:5]}


def _store_after_market_patterns(features: list[dict[str, Any]], patterns: list[dict[str, Any]]) -> None:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    today = dt.date.today().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        for f in features:
            conn.execute(
                """INSERT OR REPLACE INTO after_market_winner_features
                   (date, symbol, return_pct, open_to_high_pct, open_to_close_pct,
                    volume_ratio, gap_pct, rsi, adx, ema_alignment, sector, pattern_key, features_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    today,
                    f["symbol"],
                    f["return_pct"],
                    f["open_to_high_pct"],
                    f["open_to_close_pct"],
                    f["volume_ratio"],
                    f["gap_pct"],
                    f["rsi"],
                    f["adx"],
                    f["ema_alignment"],
                    f.get("sector"),
                    f["pattern_key"],
                    json.dumps(f, ensure_ascii=False, default=str),
                ),
            )
        for p in patterns:
            conn.execute(
                """INSERT OR REPLACE INTO after_market_learned_patterns
                   (date, pattern_key, confidence, support_count, avg_return_pct, rules_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (today, p["pattern_key"], p.get("confidence"), p.get("support_count"), p.get("avg_return_pct"), json.dumps(p, ensure_ascii=False)),
            )
        conn.commit()

    payload = {"date": today, "features": features, "patterns": patterns, "updated_at": _now_ist().isoformat(timespec="seconds")}
    with open("data/after_market_patterns.json", "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False, default=str)


def _kill_switch_alerts(rows: list[dict[str, Any]], heatmap: dict[str, dict[str, Any]], context: dict[str, Any]) -> list[str]:
    alerts = []
    if context.get("market_red_kill"):
        alerts.append("MARKET TURNED RED - EXIT ALL SMALL CAP POSITIONS; suppressing new BUY signals.")
    for sector, row in heatmap.items():
        if row.get("is_hot") and row.get("sector_momentum_score", 0) < -1.0:
            alerts.append(f"SECTOR MOMENTUM BROKEN - EXIT {sector} STOCKS")
    return alerts


def run_pattern_cycle(max_symbols: int | None = None, send_alerts: bool = True) -> dict[str, Any]:
    _init_tables()
    max_symbols = max_symbols or int(_cfg("INTRADAY_PATTERN_MAX_SYMBOLS_PER_CYCLE", 450))
    rows = _fetch_realtime_batch(_universe(max_symbols))
    context = market_context()
    heatmap = sector_heatmap(rows)
    _store_heatmap(heatmap)

    state = timing_state()
    kill_alerts = _kill_switch_alerts(rows, heatmap, context)
    emitted = []
    watchlist = []

    if send_alerts:
        from modules.alerts import send_raw_alert
        for msg in kill_alerts:
            send_raw_alert(f"<b>RISK KILL SWITCH</b>\n{msg}", review_with_grok=False)

    if not context.get("market_red_kill") and state.allow_new_entries:
        for row in rows:
            passed, labels, failed = mandatory_filter(row, rows, context)
            pattern = classify_pattern(row, rows)
            score = confidence_score(row, rows, context)
            row["filter_labels"] = labels
            row["filter_failed"] = failed
            row["confidence_score"] = score
            row["pattern"] = pattern
            if pattern and score >= 40:
                watchlist.append(row)
            if passed and pattern and score >= int(_cfg("INTRADAY_PATTERN_MIN_ALERT_SCORE", 60)) and not _alert_seen(row["symbol"], pattern):
                alert = build_alert(row, rows, context, pattern, score)
                emitted.append(alert)
                if send_alerts:
                    _send_alert(alert)

    learned = _learn_from_movers(rows)
    report = {
        "timestamp": _now_ist().isoformat(timespec="seconds"),
        "phase": state.phase,
        "scanned": len(rows),
        "market": context,
        "hot_sectors": [s for s, h in heatmap.items() if h.get("is_hot")],
        "watchlist": sorted(watchlist, key=lambda x: x["confidence_score"], reverse=True)[:25],
        "alerts": emitted,
        "learned": learned,
    }
    _write_report(report)
    logger.info("Intraday pattern cycle: scanned=%s alerts=%s learned=%s", len(rows), len(emitted), learned)
    return report


def _write_report(report: dict[str, Any]) -> None:
    from config import DB_PATH

    today = dt.date.today().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO intraday_pattern_daily_report (date, report_json, created_at)
               VALUES (?, ?, ?)""",
            (today, json.dumps(report, ensure_ascii=False, default=str), _now_ist().isoformat(timespec="seconds")),
        )
        conn.commit()
    with open("data/intraday_pattern_agent_report.json", "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2, ensure_ascii=False, default=str)


def _cfg(name: str, default: Any) -> Any:
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default


def start_intraday_pattern_agent(interval_minutes: int | None = None) -> dict[str, Any]:
    global _agent_thread, _agent_running

    if _agent_running:
        return {"ok": False, "error": "intraday pattern agent already running"}
    _init_tables()
    interval_minutes = interval_minutes or int(_cfg("INTRADAY_PATTERN_SCAN_INTERVAL_MINUTES", 5))
    _agent_running = True

    def _loop() -> None:
        from modules.scanner import is_market_holiday, is_market_open, is_weekend

        while _agent_running:
            try:
                today = dt.date.today()
                if is_weekend(today) or is_market_holiday(today):
                    logger.info("Intraday pattern agent sleeping: non-trading day")
                    time.sleep(60 * 60)
                    continue

                state = timing_state()
                if is_market_open() or state.phase in {"PRE_MARKET", "MARKET_CLOSED"}:
                    run_pattern_cycle(send_alerts=True)
                if state.phase == "MARKET_CLOSED":
                    _send_daily_report_once()
                    time.sleep(60 * 60)
                else:
                    time.sleep(max(60, interval_minutes * 60))
            except Exception as exc:
                logger.error("Intraday pattern agent cycle failed: %s", exc)
                time.sleep(300)

    _agent_thread = threading.Thread(target=_loop, name="intraday-pattern-agent", daemon=True)
    _agent_thread.start()
    logger.info("Intraday pattern agent started (every %s min)", interval_minutes)
    return {"ok": True, "interval_minutes": interval_minutes}


def stop_intraday_pattern_agent() -> dict[str, Any]:
    global _agent_running
    _agent_running = False
    return {"ok": True}


_last_daily_report_sent: str | None = None


def _send_daily_report_once() -> None:
    global _last_daily_report_sent
    today = dt.date.today().isoformat()
    if _last_daily_report_sent == today:
        return
    report = {}
    try:
        with open("data/intraday_pattern_agent_report.json", "r", encoding="utf-8") as fp:
            report = json.load(fp)
    except Exception:
        return
    from modules.alerts import send_raw_alert

    learned = report.get("learned", {})
    hot = ", ".join(report.get("hot_sectors", [])[:5]) or "None"
    msg = (
        "<b>INTRADAY PATTERN AGENT - EOD REPORT</b>\n"
        f"Scanned: {report.get('scanned', 0)}\n"
        f"Alerts: {len(report.get('alerts', []))}\n"
        f"Hot sectors: {hot}\n"
        f"7%+ movers learned: {learned.get('winner_count', 0)}\n"
        f"Patterns stored: {learned.get('pattern_count', 0)}"
    )
    send_raw_alert(msg, review_with_grok=False)
    _last_daily_report_sent = today


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_pattern_cycle(max_symbols=80, send_alerts=False), indent=2, default=str))
