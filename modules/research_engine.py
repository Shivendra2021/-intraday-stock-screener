"""
research_engine.py — Intelligent Research Engine for MarketMind Pro.

Flow:
  1. Find top-3 trending sectors (via price momentum + news)
  2. Scan universe for: 52-week high proximity, result-day patterns,
     volume surges, smallcap breakouts — focused on 6-7% intraday patterns
  3. Deep-score top 20 candidates
  4. AI deep analysis (Grok primary → GPT fallback)
  5. Return final picks with full data for Telegram

This replaces the old pattern_researcher.py for morning picks.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Sector definitions with representative benchmark stocks
# ─────────────────────────────────────────────────────────────────────────────

SECTOR_STOCKS: dict[str, list[str]] = {
    "IT":        ["MPHASIS", "PERSISTENT", "COFORGE", "BSOFT", "KPITTECH", "TATAELXSI", "CYIENT", "SONATSOFTW"],
    "Finance":   ["ANGELONE", "CDSL", "BSE", "MANAPPURAM", "MUTHOOTFIN", "POONAWALLA", "DELTACORP", "MFSL"],
    "Auto":      ["EXIDEIND", "AMBER", "SONACOMS", "TIMKEN", "SUNDRMFAST", "ELECON"],
    "Pharma":    ["ALKEM", "AUROPHARMA", "LUPIN", "TORNTPHARM", "BIOCON", "GLENMARK", "IPCALAB", "LAURUSLABS", "GRANULES"],
    "Cement":    ["RAMCOCEM", "JKCEMENT", "HEIDELBERG", "ORIENTCEM", "INDIACEM"],
    "Metals":    ["NMDC", "SAIL", "NATIONALUM", "HINDCOPPER", "JINDALSAW", "WELCORP"],
    "FMCG":      ["JYOTHYLAB", "RADICO", "TASTYBITE", "DEVYANI", "SAPPHIRE", "BIKAJI"],
    "Infra":     ["BHEL", "CONCOR", "PRESTIGE", "SOBHA", "GODREJPROP", "OBEROIRLTY", "RVNL", "IRFC", "HUDCO", "SJVN", "MAZDOCK", "COCHINSHIP", "RAILTEL", "NBCC", "RITES", "IRCON", "NCC"],
    "Energy":    ["TATAPOWER", "SUZLON", "CESC", "TORNTPOWER", "SJVN"],
    "Banking":   ["IDFCFIRSTB", "KARURVYSYA", "FEDERALBNK", "UNIONBANK", "UCOBANK"],
    "Smallcap":  ["DIXON", "POLYCAB", "PIIND", "AAVAS", "NUVAMA", "RATEGAIN",
                  "KAYNES", "JYOTHYLAB", "ASTRAL", "GRINDWELL", "ELGIEQUIP",
                  "COFORGE", "DEEPAKNTR", "BLUEDART", "METROPOLIS", "LATENTVIEW",
                  "TEJASNET", "NETWEB"],
}

# Patterns giving consistent 6-7% intraday returns:
# 1. Gap-up >1% + high volume + RSI 55-70 + EMA bullish
# 2. 52-week high proximity (<3%) + ADX >25
# 3. Result day (detected by volume 3x+ spike)
# 4. Sector rotation momentum (top sector + individual stock momentum)


# ─────────────────────────────────────────────────────────────────────────────
# News-based sector sentiment
# ─────────────────────────────────────────────────────────────────────────────

def _get_news_sector_scores() -> dict[str, float]:
    """
    Pull headlines from NewsAPI + TheNewsAPI and score each sector.
    Returns {sector: score} where score > 0 = positive sentiment.
    """
    scores: dict[str, float] = {s: 0.0 for s in SECTOR_STOCKS}
    keywords = {
        "IT":       ["IT", "technology", "software", "TCS", "Infosys", "tech stocks"],
        "Finance":  ["banking", "HDFC", "ICICI", "RBI", "interest rate", "finance"],
        "Auto":     ["automobile", "auto", "EV", "electric vehicle", "car sales"],
        "Pharma":   ["pharma", "drug", "medicine", "FDA", "healthcare"],
        "Cement":   ["cement", "infrastructure", "construction", "housing"],
        "Metals":   ["steel", "metals", "mining", "iron ore", "copper"],
        "FMCG":     ["FMCG", "consumer goods", "HUL", "ITC", "Dabur"],
        "Energy":   ["energy", "oil", "Reliance", "ONGC", "petroleum"],
        "Infra":    ["infrastructure", "roads", "railways", "L&T", "power"],
        "Banking":  ["bank", "SBI", "credit", "loan", "NPA"],
        "Smallcap": ["smallcap", "midcap", "SME", "emerging"],
    }

    try:
        from modules.news_provider import fetch_market_news

        payload = fetch_market_news(limit=30)
        headlines = [
            ((item.get("title", "") or "") + " " + (item.get("desc", "") or "")).lower()
            for item in payload.get("items", [])
        ]

        for headline in headlines:
            for sector, kws in keywords.items():
                for kw in kws:
                    if kw.lower() in headline:
                        scores[sector] += 1.0

    except Exception as e:
        logger.warning("News sentiment fetch failed: %s", e)

    return scores


# ─────────────────────────────────────────────────────────────────────────────
# Price-momentum sector scoring
# ─────────────────────────────────────────────────────────────────────────────

def _get_price_sector_scores() -> dict[str, float]:
    """
    Score each sector by average 5-day price change of benchmark stocks.
    Fast: uses only 3 benchmark stocks per sector to minimise API calls.
    Gracefully skips any symbol where fetch_ohlcv returns None or empty.
    """
    from modules.fetch import fetch_ohlcv

    scores: dict[str, float] = {}
    benchmarks = {s: stocks[:3] for s, stocks in SECTOR_STOCKS.items()}

    for sector, syms in benchmarks.items():
        changes = []
        for sym in syms:
            try:
                df = fetch_ohlcv(sym, period="5d")
                # fetch_ohlcv now returns None on failure — handle both None and empty
                if df is None or df.empty or len(df) < 2:
                    logger.warning("Sector score: no data for %s (%s), skipping", sym, sector)
                    continue
                chg = (float(df["close"].iloc[-1]) - float(df["close"].iloc[0])) / float(df["close"].iloc[0]) * 100
                changes.append(chg)
            except Exception as e:
                logger.warning("Sector score error for %s: %s", sym, e)
                continue
        scores[sector] = float(np.mean(changes)) if changes else 0.0

    return scores


def get_top_sectors(n: int = 3) -> list[str]:
    """Return top-N trending sectors. Falls back to default list if all scoring fails."""
    DEFAULT_SECTORS = ["IT", "Finance", "Auto"]

    try:
        price_scores = _get_price_sector_scores()
    except Exception as e:
        logger.warning("Price sector scoring failed: %s", e)
        price_scores = {}

    try:
        news_scores = _get_news_sector_scores()
    except Exception as e:
        logger.warning("News sector scoring failed: %s", e)
        news_scores = {}

    # If both sources returned nothing, return safe defaults
    if not price_scores and not news_scores:
        logger.warning("Sector scoring completely failed — using defaults: %s", DEFAULT_SECTORS)
        return DEFAULT_SECTORS[:n]

    combined: dict[str, float] = {}
    all_sectors = set(list(price_scores.keys()) + list(news_scores.keys()))
    for s in all_sectors:
        combined[s] = price_scores.get(s, 0.0) * 1.5 + news_scores.get(s, 0.0) * 0.5

    top = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    result = [s for s, _ in top[:n]]

    # If somehow result is empty after scoring, use defaults
    if not result:
        logger.warning("No sectors ranked — using defaults")
        return DEFAULT_SECTORS[:n]

    logger.info("Top trending sectors: %s (scores: %s)", result,
                {s: round(v, 2) for s, v in top[:n]})
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Stock candidate discovery
# ─────────────────────────────────────────────────────────────────────────────

def _score_candidate(sym: str) -> dict | None:
    """
    Deep single-stock scoring for 6-7% intraday return patterns.
    Returns None if stock doesn't meet minimum criteria or data is unavailable.
    Never raises — all exceptions are caught and return None.
    """
    from modules.fetch import fetch_ohlcv

    try:
        df = fetch_ohlcv(sym, period="3mo")
        # fetch_ohlcv returns None on failure — handle both None and empty DataFrame
        if df is None or df.empty or len(df) < 30:
            logger.warning("_score_candidate: no/insufficient data for %s", sym)
            return None

        close  = df["close"].astype(float)
        high_s = df["high"].astype(float)
        low_s  = df["low"].astype(float)
        vol    = df["volume"].astype(float)
        open_s = df["open"].astype(float) if "open" in df.columns else close

        price = float(close.iloc[-1])
        from config import MIN_PRICE_FILTER
        if price < MIN_PRICE_FILTER:
            return None

        # Volume metrics
        avg_vol_20 = float(vol.rolling(20).mean().iloc[-1])
        latest_vol = float(vol.iloc[-1])
        vol_ratio  = latest_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

        if avg_vol_20 < 50_000:
            return None

        # 52-week high proximity
        high_52w = float(high_s.rolling(252, min_periods=60).max().iloc[-1])
        dist_52w_pct = (high_52w - price) / high_52w * 100 if high_52w > 0 else 999

        # Gap up
        prev_close = float(close.iloc[-2]) if len(close) > 1 else price
        today_open = float(open_s.iloc[-1])
        gap_up_pct = (today_open - prev_close) / prev_close * 100 if prev_close > 0 else 0

        # Daily change
        daily_chg = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0

        # EMA
        ema9  = float(close.ewm(span=9,  adjust=False, min_periods=9).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False, min_periods=21).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False, min_periods=50).mean().iloc[-1])
        ema_bull = price > ema9 > ema21 > ema50
        ema_partial = price > ema21 and not ema_bull
        ema_alignment = "EMA_full_bull" if ema_bull else ("EMA_partial_bull" if ema_partial else "EMA_bear")

        # RSI
        delta = close.diff()
        gain  = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = float((100 - (100 / (1 + rs))).fillna(50).iloc[-1])

        # MACD
        ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
        ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
        macd_line   = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
        macd_val = float(macd_line.iloc[-1])
        macd_sig = float(signal_line.iloc[-1])

        # ATR
        prev_c = close.shift(1)
        tr = pd.concat([high_s - low_s, (high_s - prev_c).abs(), (low_s - prev_c).abs()], axis=1).max(axis=1)
        atr = float(tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean().iloc[-1])

        # ADX
        up   = high_s.diff()
        down = -low_s.diff()
        pdm  = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high_s.index)
        ndm  = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=low_s.index)
        atr_s = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean().replace(0, np.nan)
        pdi  = 100 * pdm.ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr_s
        ndi  = 100 * ndm.ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr_s
        dx   = ((pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan) * 100)
        adx  = float(dx.ewm(alpha=1/14, min_periods=14, adjust=False).mean().fillna(20).iloc[-1])

        # Bollinger position
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_up  = float((bb_mid + 2 * bb_std).iloc[-1])
        bb_lo  = float((bb_mid - 2 * bb_std).iloc[-1])
        bb_rng = bb_up - bb_lo
        bb_pos = (price - bb_lo) / bb_rng if bb_rng > 0 else 0.5

        # ── Pattern detection ────────────────────────────────────────────────
        is_52w_near    = dist_52w_pct <= 3.0                # near 52-week high
        is_result_day  = vol_ratio >= 3.0                   # result/event day volume spike
        is_gap_breakout = gap_up_pct >= 1.5 and vol_ratio >= 1.5
        is_momentum    = ema_bull and rsi >= 55 and vol_ratio >= 1.3

        # ── Score (0-100) ────────────────────────────────────────────────────
        score = 0.0

        # RSI sweet spot for momentum: 55-70
        if 55 <= rsi <= 70:
            score += 25
        elif 50 <= rsi < 55 or 70 < rsi <= 78:
            score += 12

        # EMA alignment
        if ema_bull:
            score += 20
        elif ema_partial:
            score += 8

        # Volume surge
        if vol_ratio >= 3.0:
            score += 20
        elif vol_ratio >= 2.0:
            score += 15
        elif vol_ratio >= 1.5:
            score += 10
        elif vol_ratio >= 1.2:
            score += 4

        # 52-week high proximity (breakout setup)
        if dist_52w_pct <= 1.0:
            score += 15
        elif dist_52w_pct <= 3.0:
            score += 10
        elif dist_52w_pct <= 5.0:
            score += 5

        # MACD
        if macd_val > 0 and macd_val > macd_sig:
            score += 10
        elif macd_val > macd_sig:
            score += 4

        # ADX (trend strength)
        if adx >= 30:
            score += 10
        elif adx >= 22:
            score += 5

        # Gap up
        if gap_up_pct >= 2.0:
            score += 8
        elif gap_up_pct >= 1.0:
            score += 4

        score = min(100, score)

        patterns = []
        if is_52w_near:    patterns.append("52wk_high_proximity")
        if is_result_day:  patterns.append("result_day_volume")
        if is_gap_breakout: patterns.append("gap_breakout")
        if is_momentum:    patterns.append("ema_momentum")

        return {
            "symbol":         sym,
            "score":          round(score, 2),
            "price":          round(price, 2),
            "rsi":            round(rsi, 2),
            "adx":            round(adx, 2),
            "atr":            round(atr, 4),
            "macd_val":       round(macd_val, 4),
            "macd_sig":       round(macd_sig, 4),
            "ema_alignment":  ema_alignment,
            "vol_ratio":      round(vol_ratio, 2),
            "gap_up":         round(gap_up_pct, 2),
            "daily_change":   round(daily_chg, 2),
            "dist_52w_high":  round(dist_52w_pct, 2),
            "52w_high":       round(high_52w, 2),
            "bb_position":    round(bb_pos, 3),
            "avg_volume":     int(avg_vol_20),
            "patterns":       patterns,
            "signal_reasons": "; ".join(patterns) if patterns else "momentum",
        }

    except Exception as e:
        logger.debug("Score candidate failed for %s: %s", sym, e)
        return None


def _get_sector_candidates(top_sectors: list[str]) -> list[str]:
    """Get stock candidates from top sectors + smallcap universe (filtered for Small & Midcap only)."""
    from modules.scanner import is_small_or_midcap
    candidates = set()
    for sector in top_sectors:
        candidates.update(SECTOR_STOCKS.get(sector, []))
    # Always include smallcap
    candidates.update(SECTOR_STOCKS.get("Smallcap", []))
    return [s for s in candidates if is_small_or_midcap(s)]



def scan_for_picks(
    top_sectors: list[str],
    extra_universe: list[str] | None = None,
    max_workers: int = 6,
) -> list[dict]:
    """
    Full research scan — serial execution (avoids multiprocessing + yfinance conflicts).
    """
    candidates = _get_sector_candidates(top_sectors)
    if extra_universe:
        candidates = list(set(candidates) | set(extra_universe[:100]))

    logger.info("Research scan: %s candidates from sectors %s", len(candidates), top_sectors)

    results = []
    for sym in candidates:
        try:
            r = _score_candidate(sym)
            if r is not None:
                results.append(r)
        except Exception as e:
            logger.warning("scan_for_picks: error on %s: %s", sym, e)
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Research scan complete: %s/%s stocks scored", len(results), len(candidates))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Full research pipeline (called from main.py)
# ─────────────────────────────────────────────────────────────────────────────

def run_full_research(
    full_universe: list[str] | None = None,
    top_n: int = 5,
) -> dict[str, Any]:
    """
    Master research pipeline:
      1. Find top-3 trending sectors
      2. Scan candidates (sector + smallcap + universe sample)
      3. Take top-20, run AI deep analysis
      4. Return structured result

    Returns:
      {
        "top_sectors": [...],
        "top20": [...],          # top 20 scored candidates
        "final_picks": [...],    # top-N with entry/SL/TP
        "ai_analysis": "...",    # AI commentary string
      }
    """
    from config import MIN_SCORE_THRESHOLD, MIN_RISK_REWARD, MIN_TARGET_MOVE_PCT, MAX_TARGET_MOVE_PCT

    logger.info("=== RESEARCH ENGINE: Full pipeline start ===")

    # Step 1: trending sectors
    top_sectors = get_top_sectors(3)

    # Step 2: scan
    extras = full_universe[:200] if full_universe else []
    all_scored = scan_for_picks(top_sectors, extra_universe=extras)

    top20 = [s for s in all_scored if s["score"] >= MIN_SCORE_THRESHOLD][:20]
    if not top20:
        top20 = all_scored[:10]  # fallback: take best even if below threshold
        logger.warning("Score threshold relaxed — using top-10 fallback")

    # Step 3: AI deep analysis
    ai_analysis = ""
    try:
        from modules.grok_brain import analyse_stocks_deep
        sector_context = ", ".join(top_sectors)
        ai_analysis = analyse_stocks_deep(top20, sector_context=sector_context)
        logger.info("AI analysis complete")
    except Exception as e:
        logger.warning("AI analysis failed: %s", e)
        ai_analysis = "[AI analysis unavailable]"

    # Step 4: Build final picks with entry/SL/TP
    final_picks = []
    for i, stock in enumerate(top20[:top_n], start=1):
        price = stock["price"]
        atr   = stock.get("atr", price * 0.015)
        move_pct = (MIN_TARGET_MOVE_PCT + MAX_TARGET_MOVE_PCT) / 2  # 6.5%

        sl_atr  = price - (atr * 1.5)
        sl_pct  = price * 0.98         # 2% SL
        sl_price = max(sl_atr, sl_pct)
        target  = price * (1 + move_pct / 100)

        risk   = price - sl_price
        reward = target - price
        rr     = round(reward / risk, 2) if risk > 0 else 0

        final_picks.append({
            **stock,
            "rank":         i,
            "entry_price":  round(price, 2),
            "sl_price":     round(sl_price, 2),
            "target_price": round(target, 2),
            "upside_pct":   round(move_pct, 2),
            "risk_reward":  rr,
            "sector":       _guess_sector(stock["symbol"]),
        })

    logger.info("Research engine complete: sectors=%s, top20=%s, picks=%s",
                top_sectors, len(top20), len(final_picks))

    return {
        "top_sectors":  top_sectors,
        "top20":        top20,
        "final_picks":  final_picks,
        "ai_analysis":  ai_analysis,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def _guess_sector(symbol: str) -> str:
    """Reverse-lookup a symbol to its sector."""
    for sector, stocks in SECTOR_STOCKS.items():
        if symbol in stocks:
            return sector
    return "Unknown"
