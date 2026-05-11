"""
sector_analyzer.py — Find top-3 trending sectors from ~11 NSE sectors.

Uses:
  1. Price momentum of 3 benchmark stocks per sector (yfinance)
  2. News sentiment from NewsAPI + TheNewsAPI
  3. FII/DII data from NSE India (optional)

Returns top-N sectors with scores.
"""

from __future__ import annotations
import logging
import time
import numpy as np

logger = logging.getLogger(__name__)

# ── Benchmark stocks per sector (3 per sector for speed) ──────────────────────
SECTOR_BENCHMARKS: dict[str, list[str]] = {
    "IT":        ["TCS", "INFY", "HCLTECH"],
    "Finance":   ["HDFCBANK", "ICICIBANK", "SBIN"],
    "Auto":      ["HEROMOTOCO", "MARUTI", "TVSMOTOR"],
    "Pharma":    ["SUNPHARMA", "DRREDDY", "CIPLA"],
    "Metals":    ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
    "FMCG":      ["HINDUNILVR", "ITC", "DABUR"],
    "Energy":    ["RELIANCE", "ONGC", "TATAPOWER"],
    "Infra":     ["LT", "NTPC", "POWERGRID"],
    "Banking":   ["AXISBANK", "KOTAKBANK", "FEDERALBNK"],
    "Cement":    ["ULTRACEMCO", "SHREECEM", "ACC"],
    "Smallcap":  ["DIXON", "POLYCAB", "KAYNES"],
}

# ── News keywords per sector ───────────────────────────────────────────────────
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "IT":       ["IT", "technology", "software", "TCS", "Infosys", "tech"],
    "Finance":  ["banking", "HDFC", "ICICI", "RBI", "rate", "finance", "loan"],
    "Auto":     ["auto", "EV", "electric vehicle", "car sales", "automobile"],
    "Pharma":   ["pharma", "drug", "FDA", "medicine", "healthcare"],
    "Metals":   ["steel", "metals", "mining", "iron", "copper", "aluminium"],
    "FMCG":     ["FMCG", "consumer", "HUL", "Dabur", "ITC"],
    "Energy":   ["energy", "oil", "crude", "Reliance", "ONGC", "petroleum"],
    "Infra":    ["infrastructure", "roads", "railways", "L&T", "power grid"],
    "Banking":  ["bank", "SBI", "credit", "NPA", "deposit"],
    "Cement":   ["cement", "construction", "housing", "real estate"],
    "Smallcap": ["smallcap", "midcap", "SME", "emerging"],
}


def _price_momentum_scores() -> dict[str, float]:
    """Score sectors by average 5-day % change of 3 benchmark stocks."""
    from modules.fetch import fetch_ohlcv

    scores: dict[str, float] = {}
    for sector, syms in SECTOR_BENCHMARKS.items():
        changes = []
        for sym in syms:
            try:
                df = fetch_ohlcv(sym, period="5d")
                if df is None or df.empty or len(df) < 2:
                    continue
                pct = (float(df["close"].iloc[-1]) - float(df["close"].iloc[0])) / float(df["close"].iloc[0]) * 100
                changes.append(pct)
            except Exception as e:
                logger.debug("Price momentum error %s: %s", sym, e)
            time.sleep(0.5)
        scores[sector] = float(np.mean(changes)) if changes else 0.0
        logger.debug("Sector %s momentum: %.2f%%", sector, scores[sector])
    return scores


def _news_sentiment_scores() -> dict[str, float]:
    """Score sectors by how many headlines match sector keywords."""
    scores: dict[str, float] = {s: 0.0 for s in SECTOR_BENCHMARKS}
    headlines: list[str] = []

    try:
        from modules.news_provider import fetch_market_news

        payload = fetch_market_news(limit=30)
        headlines = [
            ((item.get("title", "") or "") + " " + (item.get("desc", "") or "")).lower()
            for item in payload.get("items", [])
        ]

    except Exception as e:
        logger.debug("News config error: %s", e)

    for headline in headlines:
        for sector, kws in SECTOR_KEYWORDS.items():
            for kw in kws:
                if kw.lower() in headline:
                    scores[sector] += 1.0
                    break

    return scores


def get_top_sectors(n: int = 3) -> list[str]:
    """
    Return top-N trending sectors combining price momentum + news sentiment.
    Falls back to ["IT", "Finance", "Auto"] if all data sources fail.
    """
    DEFAULT = ["IT", "Finance", "Auto"]

    try:
        price = _price_momentum_scores()
    except Exception as e:
        logger.warning("Price sector scoring failed: %s", e)
        price = {}

    try:
        news = _news_sentiment_scores()
    except Exception as e:
        logger.warning("News sector scoring failed: %s", e)
        news = {}

    if not price and not news:
        logger.warning("All sector scoring failed — using defaults")
        return DEFAULT[:n]

    combined: dict[str, float] = {}
    for s in SECTOR_BENCHMARKS:
        combined[s] = price.get(s, 0.0) * 1.5 + news.get(s, 0.0) * 0.5

    top = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    result = [s for s, _ in top[:n]]

    if not result:
        return DEFAULT[:n]

    logger.info("Top sectors: %s | scores: %s", result,
                {s: round(v, 2) for s, v in top[:n]})
    return result


def get_sector_stocks(sectors: list[str]) -> list[str]:
    """Return all stocks from the given sectors (no duplicates)."""
    seen: set[str] = set()
    result: list[str] = []
    for s in sectors:
        for sym in SECTOR_BENCHMARKS.get(s, []):
            if sym not in seen:
                seen.add(sym)
                result.append(sym)
    return result
