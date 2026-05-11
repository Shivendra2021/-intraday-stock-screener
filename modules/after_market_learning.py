# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.

"""
after_market_learning.py — Post-close 7%+ winner similarity learner.

Runs after market close:
1. Finds stocks with at least 7% open-to-high/open-to-close intraday move.
2. Extracts technical, volume, gap, sector, and lightweight news/fundamental context.
3. Learns common similarities and stores them in SQLite + JSON.
4. Exposes learned boosts for the next morning stock selection loop.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
from collections import Counter
from statistics import mean
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

LEARNED_PATTERNS_JSON = "data/after_market_patterns.json"


def _today() -> str:
    return datetime.date.today().isoformat()


def _init_storage() -> None:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    os.makedirs("data", exist_ok=True)
    ensure_research_tables()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS after_market_winner_features (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT NOT NULL,
               symbol TEXT NOT NULL,
               return_pct REAL,
               open_to_high_pct REAL,
               open_to_close_pct REAL,
               volume_ratio REAL,
               gap_pct REAL,
               rsi REAL,
               adx REAL,
               ema_alignment TEXT,
               sector TEXT,
               pattern_key TEXT,
               features_json TEXT,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP,
               UNIQUE(date, symbol)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS after_market_learned_patterns (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT NOT NULL,
               pattern_key TEXT NOT NULL,
               confidence REAL,
               support_count INTEGER,
               avg_return_pct REAL,
               rules_json TEXT,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP,
               UNIQUE(date, pattern_key)
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def _ema_alignment(close: pd.Series) -> str:
    ema9 = float(close.ewm(span=9, adjust=False, min_periods=9).mean().iloc[-1])
    ema21 = float(close.ewm(span=21, adjust=False, min_periods=21).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False, min_periods=50).mean().iloc[-1])
    price = float(close.iloc[-1])
    if price > ema9 > ema21 > ema50:
        return "EMA_full_bull"
    if price > ema21:
        return "EMA_partial_bull"
    return "EMA_bear"


def _rsi(close: pd.Series) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    return float((100 - 100 / (1 + rs)).fillna(50).iloc[-1])


def _adx(high: pd.Series, low: pd.Series, close: pd.Series) -> float:
    up = high.diff()
    down = -low.diff()
    pdm = pd.Series(((up > down) & (up > 0)) * up, index=high.index).fillna(0.0)
    ndm = pd.Series(((down > up) & (down > 0)) * down, index=low.index).fillna(0.0)
    prev_c = close.shift(1)
    tr = pd.concat([high - low, (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean().replace(0, pd.NA)
    pdi = 100 * pdm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr
    ndi = 100 * ndm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr
    dx = (pdi - ndi).abs() / (pdi + ndi).replace(0, pd.NA) * 100
    return float(dx.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean().fillna(20).iloc[-1])


def _bucketize(feature: dict[str, Any]) -> str:
    rsi = float(feature.get("rsi", 50))
    vol = float(feature.get("volume_ratio", 1))
    gap = float(feature.get("gap_pct", 0))
    adx = float(feature.get("adx", 20))
    rsi_bucket = "RSI_50_65" if 50 <= rsi <= 65 else ("RSI_65_75" if 65 < rsi <= 75 else "RSI_other")
    vol_bucket = "VOL_2x" if vol >= 2 else ("VOL_1_5x" if vol >= 1.5 else "VOL_normal")
    gap_bucket = "GAP_2pct" if gap >= 2 else ("GAP_0_2pct" if gap > 0 else "GAP_flat")
    adx_bucket = "ADX_strong" if adx >= 25 else "ADX_normal"
    return f"{rsi_bucket}__{vol_bucket}__{gap_bucket}__{adx_bucket}__{feature.get('ema_alignment', 'EMA_unknown')}"


def extract_winner_features(symbol: str, min_return_pct: float = 7.0) -> dict[str, Any] | None:
    """Return feature row if symbol had a >= min_return_pct intraday move today."""
    try:
        from modules.fetch import fetch_ohlcv
        from modules.news import get_stock_sentiment
        from modules.stock_selector import SECTOR_UNIVERSE

        df = fetch_ohlcv(symbol, period="3mo")
        if df is None or df.empty or len(df) < 30:
            return None
        df = df.copy()
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        open_s = df["open"].astype(float)
        volume = df["volume"].astype(float)
        latest = df.iloc[-1]

        open_price = float(latest["open"])
        high_price = float(latest["high"])
        close_price = float(latest["close"])
        if open_price <= 0:
            return None

        open_to_high = (high_price - open_price) / open_price * 100
        open_to_close = (close_price - open_price) / open_price * 100
        return_pct = max(open_to_high, open_to_close)
        if return_pct < min_return_pct:
            return None

        prev_close = float(close.iloc[-2]) if len(close) >= 2 else open_price
        avg_volume = float(volume.rolling(20).mean().iloc[-1])
        volume_ratio = float(latest["volume"]) / avg_volume if avg_volume > 0 else 1.0
        gap_pct = (open_price - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        sector = "Unknown"
        for sec, syms in SECTOR_UNIVERSE.items():
            if symbol in syms:
                sector = sec
                break

        feature = {
            "symbol": symbol,
            "date": _today(),
            "return_pct": round(return_pct, 4),
            "open_to_high_pct": round(open_to_high, 4),
            "open_to_close_pct": round(open_to_close, 4),
            "open_price": round(open_price, 4),
            "high_price": round(high_price, 4),
            "close_price": round(close_price, 4),
            "volume_ratio": round(volume_ratio, 4),
            "gap_pct": round(gap_pct, 4),
            "rsi": round(_rsi(close), 4),
            "adx": round(_adx(high, low, close), 4),
            "ema_alignment": _ema_alignment(close),
            "sector": sector,
            "news_sentiment": round(float(get_stock_sentiment(symbol)), 4),
        }
        feature["pattern_key"] = _bucketize(feature)
        return feature
    except Exception as exc:
        logger.debug("Feature extraction failed for %s: %s", symbol, exc)
        return None


def learn_similarities(features: list[dict[str, Any]], min_support: int = 2) -> list[dict[str, Any]]:
    """Learn common winner rules from extracted feature rows."""
    if not features:
        return []
    n = len(features)
    patterns: list[dict[str, Any]] = []

    def add_rule(key: str, value: Any, matched: list[dict[str, Any]]) -> None:
        if len(matched) < min_support and n >= min_support:
            return
        support = len(matched)
        avg_ret = mean(float(x.get("return_pct", 0)) for x in matched)
        patterns.append({
            "pattern_key": f"{key}:{value}",
            "confidence": round(support / n, 4),
            "support_count": support,
            "avg_return_pct": round(avg_ret, 4),
            "rules": {key: value},
            "symbols": [x["symbol"] for x in matched],
        })

    for key in ["pattern_key", "ema_alignment", "sector"]:
        counts = Counter(x.get(key) for x in features if x.get(key))
        for value, _ in counts.most_common(5):
            add_rule(key, value, [x for x in features if x.get(key) == value])

    numeric_rules = [
        ("volume_ratio", ">=", 1.5),
        ("volume_ratio", ">=", 2.0),
        ("gap_pct", ">=", 1.0),
        ("gap_pct", ">=", 2.0),
        ("rsi", "between", (50, 65)),
        ("rsi", "between", (55, 75)),
        ("adx", ">=", 25),
    ]
    for key, op, threshold in numeric_rules:
        if op == ">=":
            matched = [x for x in features if float(x.get(key, 0)) >= float(threshold)]
            value = f">={threshold}"
        else:
            lo, hi = threshold
            matched = [x for x in features if lo <= float(x.get(key, 0)) <= hi]
            value = f"{lo}-{hi}"
        add_rule(key, value, matched)

    patterns.sort(key=lambda p: (p["confidence"], p["avg_return_pct"], p["support_count"]), reverse=True)
    return patterns[:20]


def _store_results(features: list[dict[str, Any]], patterns: list[dict[str, Any]]) -> None:
    from config import DB_PATH

    _init_storage()
    today = _today()
    conn = sqlite3.connect(DB_PATH)
    try:
        for f in features:
            conn.execute(
                """INSERT OR REPLACE INTO after_market_winner_features
                   (date, symbol, return_pct, open_to_high_pct, open_to_close_pct,
                    volume_ratio, gap_pct, rsi, adx, ema_alignment, sector, pattern_key, features_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    today, f["symbol"], f.get("return_pct"), f.get("open_to_high_pct"),
                    f.get("open_to_close_pct"), f.get("volume_ratio"), f.get("gap_pct"),
                    f.get("rsi"), f.get("adx"), f.get("ema_alignment"), f.get("sector"),
                    f.get("pattern_key"), json.dumps(f, ensure_ascii=False, default=str),
                ),
            )
        for p in patterns:
            conn.execute(
                """INSERT OR REPLACE INTO after_market_learned_patterns
                   (date, pattern_key, confidence, support_count, avg_return_pct, rules_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    today, p["pattern_key"], p.get("confidence"), p.get("support_count"),
                    p.get("avg_return_pct"), json.dumps(p, ensure_ascii=False, default=str),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    payload = {"date": today, "features": features, "patterns": patterns, "updated_at": datetime.datetime.now().isoformat()}
    with open(LEARNED_PATTERNS_JSON, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False)


def get_after_market_patterns() -> list[dict[str, Any]]:
    """Return latest learned after-market winner patterns for scoring/context."""
    try:
        with open(LEARNED_PATTERNS_JSON, "r", encoding="utf-8") as fp:
            return json.load(fp).get("patterns", [])
    except Exception:
        return []


def run_after_market_learning(symbols: list[str] | None = None, min_return_pct: float = 7.0, max_symbols: int | None = None) -> dict[str, Any]:
    """Full post-close learning loop."""
    from config import INTRADAY_MIN_RETURN_PCT
    from modules.scanner import get_universe

    min_return_pct = float(min_return_pct or INTRADAY_MIN_RETURN_PCT)
    _init_storage()
    if symbols is None:
        symbols = get_universe()
    if max_symbols:
        symbols = symbols[:max_symbols]

    logger.info("After-market learning: scanning %d symbols for >= %.1f%% winners", len(symbols), min_return_pct)
    features = []
    for sym in symbols:
        feat = extract_winner_features(sym, min_return_pct=min_return_pct)
        if feat:
            features.append(feat)
    features.sort(key=lambda x: x.get("return_pct", 0), reverse=True)

    patterns = learn_similarities(features)
    _store_results(features, patterns)
    logger.info("After-market learning complete: %d winners, %d learned patterns", len(features), len(patterns))
    return {
        "success": True,
        "date": _today(),
        "winner_count": len(features),
        "pattern_count": len(patterns),
        "top_winners": features[:10],
        "patterns": patterns[:10],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_after_market_learning(max_symbols=200), indent=2))
