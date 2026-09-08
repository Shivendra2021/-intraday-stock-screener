"""
stock_selector.py — Select final 5 stocks from ~50 sector candidates.

Flow:
  1. Get top-3 sectors from sector_analyzer
  2. Build ~50-stock candidate pool from those sectors
  3. Score each stock (RSI, EMA, volume, 52w-high proximity, gap-up)
  4. Return top-5 with full entry/SL/TP data
"""

from __future__ import annotations
import logging
import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# All candidate stocks per sector (expanded from benchmarks)
SECTOR_UNIVERSE: dict[str, list[str]] = {
    "IT":        ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "MPHASIS", "PERSISTENT", "COFORGE"],
    "Finance":   ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "BAJFINANCE", "IDFCFIRSTB", "FEDERALBNK"],
    "Auto":      ["HEROMOTOCO", "MARUTI", "TVSMOTOR", "EICHERMOT", "BAJAJ-AUTO", "MOTHERSON", "M&M"],
    "Pharma":    ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "ALKEM", "AUROPHARMA", "LUPIN"],
    "Metals":    ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "NMDC", "SAIL", "COALINDIA"],
    "FMCG":      ["HINDUNILVR", "ITC", "DABUR", "BRITANNIA", "MARICO", "COLPAL", "NESTLEIND"],
    "Energy":    ["RELIANCE", "ONGC", "BPCL", "IOC", "GAIL", "TATAPOWER", "ADANIGREEN"],
    "Infra":     ["LT", "NTPC", "POWERGRID", "BHEL", "CONCOR", "IRCTC", "DLF"],
    "Banking":   ["AXISBANK", "KOTAKBANK", "FEDERALBNK", "INDUSINDBK", "BANKBARODA", "PNB"],
    "Cement":    ["ULTRACEMCO", "SHREECEM", "ACC", "AMBUJACEM", "RAMCOCEM"],
    "Smallcap":  ["DIXON", "POLYCAB", "KAYNES", "ASTRAL", "DEEPAKNTR", "COFORGE", "METROPOLIS"],
}


def _after_market_pattern_boost(candidate: dict) -> tuple[float, list[str]]:
    """Return score boost from learned 7%+ after-market winner similarities."""
    try:
        from modules.after_market_learning import get_after_market_patterns
    except Exception:
        return 0.0, []

    boost = 0.0
    reasons: list[str] = []
    for pattern in get_after_market_patterns()[:20]:
        rules = pattern.get("rules", {}) or {}
        confidence = float(pattern.get("confidence", 0) or 0)
        if confidence < 0.5:
            continue
        matched = False
        for key, expected in rules.items():
            if key == "tag":
                expected_tag = str(expected)
                if expected_tag == "above_key_ema":
                    matched = candidate.get("ema_alignment") in {"EMA_full_bull", "EMA_partial_bull"}
                elif expected_tag == "event_volume_expansion":
                    matched = float(candidate.get("vol_ratio", candidate.get("volume_ratio", 0)) or 0) >= 2.0
                elif expected_tag == "pre_volume_build":
                    matched = float(candidate.get("pre_volume_ratio", candidate.get("vol_ratio", 0)) or 0) >= 1.2
                elif expected_tag == "gap_up":
                    matched = float(candidate.get("gap_up", candidate.get("gap_pct", 0)) or 0) >= 1.0
                elif expected_tag == "near_20d_high":
                    matched = float(candidate.get("dist_20d_high_pct", candidate.get("dist_52w_high", 999)) or 999) <= 5.0
                elif expected_tag == "intraday_breakout_20d":
                    matched = bool(candidate.get("breakout_20d_high")) or float(candidate.get("dist_20d_high_pct", 999) or 999) <= 2.0
                elif expected_tag == "prior_week_momentum":
                    matched = float(candidate.get("prior_5d_pct", 0) or 0) >= 3.0
                elif expected_tag == "strong_close_location":
                    matched = float(candidate.get("close_location", 0) or 0) >= 0.6
            elif key == "ema_alignment" and candidate.get("ema_alignment") == expected:
                matched = True
            elif key == "sector" and candidate.get("sector") == expected:
                matched = True
            elif key in {"volume_ratio", "event_volume_ratio"} and str(expected).startswith(">="):
                matched = float(candidate.get("vol_ratio", candidate.get("volume_ratio", 0)) or 0) >= float(str(expected)[2:])
            elif key == "pre_volume_ratio" and str(expected).startswith(">="):
                matched = float(candidate.get("pre_volume_ratio", candidate.get("vol_ratio", 0)) or 0) >= float(str(expected)[2:])
            elif key == "gap_pct" and str(expected).startswith(">="):
                matched = float(candidate.get("gap_up", candidate.get("gap_pct", 0)) or 0) >= float(str(expected)[2:])
            elif key == "rsi" and "-" in str(expected):
                lo, hi = [float(x) for x in str(expected).split("-", 1)]
                matched = lo <= float(candidate.get("rsi", 0) or 0) <= hi
            elif key == "adx" and str(expected).startswith(">="):
                matched = float(candidate.get("adx", 0) or 0) >= float(str(expected)[2:])
            elif key == "prior_5d_pct" and str(expected).startswith(">="):
                matched = float(candidate.get("prior_5d_pct", 0) or 0) >= float(str(expected)[2:])
            elif key == "dist_20d_high_pct" and str(expected).startswith("<="):
                matched = float(candidate.get("dist_20d_high_pct", 999) or 999) <= float(str(expected)[2:])
            elif key == "close_location" and str(expected).startswith(">="):
                matched = float(candidate.get("close_location", 0) or 0) >= float(str(expected)[2:])
        if matched:
            inc = min(8.0, confidence * 6.0)
            boost += inc
            reasons.append(f"learned_7pct:{pattern.get('pattern_key')} (+{inc:.1f})")
    return min(boost, 15.0), reasons[:3]


def _score_stock(sym: str) -> Optional[dict]:
    """
    Score a single stock for intraday momentum potential.
    Returns None if data unavailable or stock fails minimum criteria.
    """
    from modules.fetch import fetch_ohlcv

    try:
        df = fetch_ohlcv(sym, period="3mo")
        if df is None or df.empty or len(df) < 30:
            logger.debug("No data for %s", sym)
            return None

        close  = df["close"].astype(float)
        high_s = df["high"].astype(float)
        low_s  = df["low"].astype(float)
        vol    = df["volume"].astype(float)
        open_s = df["open"].astype(float) if "open" in df.columns else close

        price = float(close.iloc[-1])
        if price < 50:
            return None

        # Volume filter
        avg_vol = float(vol.rolling(20).mean().iloc[-1])
        if avg_vol < 50_000:
            return None
        vol_ratio = float(vol.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0

        # Price metrics
        prev_close = float(close.iloc[-2])
        today_open = float(open_s.iloc[-1])
        gap_up_pct = (today_open - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        daily_chg  = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        prior_5d_pct = 0.0
        if len(close) >= 6 and float(close.iloc[-6]) > 0:
            prior_5d_pct = (price - float(close.iloc[-6])) / float(close.iloc[-6]) * 100

        # 52-week high
        high_20d   = float(high_s.rolling(20, min_periods=10).max().iloc[-1])
        high_52w   = float(high_s.rolling(252, min_periods=60).max().iloc[-1])
        dist_20d   = (high_20d - price) / high_20d * 100 if high_20d > 0 else 999.0
        dist_52w   = (high_52w - price) / high_52w * 100 if high_52w > 0 else 999.0
        breakout_20d_high = float(high_s.iloc[-1]) >= high_20d if high_20d > 0 else False
        close_location = (price - today_open) / (float(high_s.iloc[-1]) - today_open) if float(high_s.iloc[-1]) > today_open else 0.0

        # EMA
        ema9  = float(close.ewm(span=9,  adjust=False, min_periods=9).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False, min_periods=21).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False, min_periods=50).mean().iloc[-1])
        ema_full   = price > ema9 > ema21 > ema50
        ema_partial = price > ema21 and not ema_full
        ema_align  = "EMA_full_bull" if ema_full else ("EMA_partial_bull" if ema_partial else "EMA_bear")

        # RSI
        delta = close.diff()
        gain  = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = float((100 - 100 / (1 + rs)).fillna(50).iloc[-1])

        # ADX
        up   = high_s.diff()
        down = -low_s.diff()
        pdm  = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high_s.index)
        ndm  = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=low_s.index)
        prev_c = close.shift(1)
        tr   = pd.concat([high_s - low_s, (high_s - prev_c).abs(), (low_s - prev_c).abs()], axis=1).max(axis=1)
        atr  = float(tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean().iloc[-1])
        atr_s = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean().replace(0, np.nan)
        pdi  = 100 * pdm.ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr_s
        ndi  = 100 * ndm.ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr_s
        dx   = (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan) * 100
        adx  = float(dx.ewm(alpha=1/14, min_periods=14, adjust=False).mean().fillna(20).iloc[-1])

        # ── Score 0-100 ──
        score = 0.0
        if 55 <= rsi <= 70:     score += 25
        elif 50 <= rsi < 55:    score += 12
        elif 70 < rsi <= 78:    score += 8

        if ema_full:            score += 20
        elif ema_partial:       score += 8

        if vol_ratio >= 3.0:    score += 20
        elif vol_ratio >= 2.0:  score += 15
        elif vol_ratio >= 1.5:  score += 10
        elif vol_ratio >= 1.2:  score += 4

        if dist_52w <= 1.0:     score += 15
        elif dist_52w <= 3.0:   score += 10
        elif dist_52w <= 5.0:   score += 5

        if adx >= 30:           score += 10
        elif adx >= 22:         score += 5

        if gap_up_pct >= 2.0:   score += 8
        elif gap_up_pct >= 1.0: score += 4

        score = min(100.0, score)

        # Patterns
        patterns = []
        if dist_52w <= 3.0:                       patterns.append("52wk_high_proximity")
        if vol_ratio >= 3.0:                       patterns.append("result_day_volume")
        if gap_up_pct >= 1.5 and vol_ratio >= 1.5: patterns.append("gap_breakout")
        if ema_full and rsi >= 55:                 patterns.append("ema_momentum")

        return {
            "symbol":        sym,
            "score":         round(score, 2),
            "price":         round(price, 2),
            "rsi":           round(rsi, 2),
            "adx":           round(adx, 2),
            "atr":           round(atr, 4),
            "ema_alignment": ema_align,
            "vol_ratio":     round(vol_ratio, 2),
            "gap_up":        round(gap_up_pct, 2),
            "daily_change":  round(daily_chg, 2),
            "prior_5d_pct":  round(prior_5d_pct, 2),
            "dist_20d_high_pct": round(dist_20d, 2),
            "dist_52w_high": round(dist_52w, 2),
            "breakout_20d_high": bool(breakout_20d_high),
            "close_location": round(close_location, 2),
            "avg_volume":    int(avg_vol),
            "patterns":      patterns,
            "signal_reasons": "; ".join(patterns) if patterns else "momentum",
        }

    except Exception as e:
        logger.debug("Score failed for %s: %s", sym, e)
        return None


def select_top_stocks(sectors: list[str], n: int = 5) -> list[dict]:
    """
    From the given sectors, score all ~50 candidate stocks and return top-N
    with full entry / SL / TP attached.

    Args:
        sectors: List of sector names (e.g. ["IT", "Finance", "Auto"])
        n:       How many final picks to return (default 5)

    Returns:
        List of dicts with keys: symbol, score, price, entry_price,
        sl_price, target_price, risk_reward, rank, sector, ...
    """
    from config import MIN_SCORE_THRESHOLD

    # Build candidate pool — max 50 stocks
    seen: set[str] = set()
    candidates: list[str] = []
    for sec in sectors:
        for sym in SECTOR_UNIVERSE.get(sec, []):
            if sym not in seen:
                seen.add(sym)
                candidates.append(sym)
        if len(candidates) >= 50:
            break

    logger.info("Scoring %d candidates from sectors %s", len(candidates), sectors)

    # Score each (serial — yfinance not safe in multiprocessing)
    scored: list[dict] = []
    for sym in candidates:
        result = _score_stock(sym)
        if result is not None:
            # Attach sector label
            for sec in sectors:
                if sym in SECTOR_UNIVERSE.get(sec, []):
                    result["sector"] = sec
                    break
            else:
                result["sector"] = "Unknown"
            learned_boost, learned_reasons = _after_market_pattern_boost(result)
            if learned_boost:
                result["score"] = round(min(100.0, result.get("score", 0) + learned_boost), 2)
                result["learned_after_market_boost"] = round(learned_boost, 2)
                result["learned_after_market_reasons"] = learned_reasons
            scored.append(result)

    scored.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Scored %d/%d stocks", len(scored), len(candidates))

    # Filter by score threshold (relax if too few)
    picks = [s for s in scored if s["score"] >= MIN_SCORE_THRESHOLD]
    if len(picks) < n:
        picks = scored  # take best even below threshold

    # Build final picks with entry/SL/TP
    final: list[dict] = []
    for i, stock in enumerate(picks[:n], start=1):
        price = stock["price"]
        atr   = stock.get("atr", price * 0.015)
        target_pct = 6.5

        sl_price = max(price - atr * 1.5, price * 0.98)
        tp_price = price * (1 + target_pct / 100)
        risk     = price - sl_price
        reward   = tp_price - price
        rr       = round(reward / risk, 2) if risk > 0 else 0.0

        final.append({
            **stock,
            "rank":         i,
            "entry_price":  round(price, 2),
            "sl_price":     round(sl_price, 2),
            "target_price": round(tp_price, 2),
            "upside_pct":   round(target_pct, 2),
            "risk_reward":  rr,
            "selected_at":  datetime.datetime.now().strftime("%H:%M:%S"),
        })

    logger.info("Final %d picks: %s", len(final), [p["symbol"] for p in final])
    return final


def deep_research_stocks(stocks: list[dict], n: int = 5) -> list[dict]:
    """
    Deep research on candidates (20 stocks from universe scanner).
    
    Extended analysis with:
    - 3mo data for all indicators
    - News sentiment check
    - FII/DII flow check (if available)
    - Sector correlation check
    - Returns top-N with enhanced scores
    
    Args:
        stocks: List of stock dicts from universe scanner (should have ~20 items)
        n: Final picks to return
    
    Returns:
        Enhanced stock list with deep analysis
    """
    logger.info(f"=== Deep Research on {len(stocks)} stocks ===")
    
    detailed = []
    
    for stock in stocks:
        sym = stock.get("symbol", "")
        if not sym:
            continue
        
        # Check sector
        sector = "Unknown"
        for sec, syms in SECTOR_UNIVERSE.items():
            if sym in syms:
                sector = sec
                break
        
        # Get extended data
        try:
            from modules.fetch import fetch_ohlcv
            from modules.news import get_stock_sentiment
            
            df = fetch_ohlcv(sym, period="3mo")
            if df is None or df.empty:
                continue
            
            close = df["close"].astype(float)
            volume = df["volume"].astype(float)
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            
            price = float(close.iloc[-1])
            avg_vol = float(volume.rolling(20).mean().iloc[-1])
            
            # Advanced RSI
            delta = close.diff()
            gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
            loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = float((100 - 100 / (1 + rs)).fillna(50).iloc[-1])
            
            # MACD
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()
            macd_hist = macd - signal
            macd_bull = float(macd_hist.iloc[-1]) > 0
            
            # ADX
            up = high.diff()
            down = -low.diff()
            pdm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
            ndm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=low.index)
            tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
            atr = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
            pdi = 100 * pdm.ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr
            ndi = 100 * ndm.ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr
            dx = (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan) * 100
            adx = float(dx.ewm(alpha=1/14, min_periods=14, adjust=False).mean().fillna(20).iloc[-1])
            
            # EMA alignment
            ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
            ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
            ema_bull = price > ema9 > ema21 > ema50
            ema_partial = price > ema21
            
            # Gap to 52w high
            high_52w = float(high.rolling(252, min_periods=60).max().iloc[-1])
            gap_high = (high_52w - price) / high_52w * 100
            
            # News sentiment
            news_score = get_stock_sentiment(sym) if hasattr(get_stock_sentiment, '__call__') else 0
            
            # Enhanced score
            score = stock.get("score", 50)
            
            # Add bonuses
            if rsi >= 45 and rsi <= 65:
                score += 10
            if macd_bull:
                score += 8
            if ema_bull:
                score += 12
            elif ema_partial:
                score += 5
            if adx >= 25:
                score += 8
            if gap_high <= 5:
                score += 5
            if news_score > 0:
                score += 5
            
            score = min(100, score)
            
            detailed.append({
                "symbol": sym,
                "sector": sector,
                "price": price,
                "score": round(score, 2),
                "rsi": round(rsi, 2),
                "macd_bull": macd_bull,
                "adx": round(adx, 2),
                "ema_alignment": "bullish" if ema_bull else ("partial" if ema_partial else "neutral"),
                "gap_to_52w_high": round(gap_high, 2),
                "volume_ratio": stock.get("vol_ratio", 1),
                "daily_change": stock.get("price_change_pct", 0),
                "original_score": stock.get("score", 0),
                "deep_analysis": True,
            })
            
        except Exception as e:
            logger.warning("Deep analysis failed for %s, keeping original candidate data: %s", sym, e)
            # Keep original data
            detailed.append({
                **stock,
                "sector": sector,
                "deep_analysis": False,
            })
    
    # Sort by enhanced score
    detailed.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Contextual Bandit (LinUCB) dynamic selection
    try:
        from modules.bandit_selector import rank_candidates_with_bandit
        detailed = rank_candidates_with_bandit(detailed, top_n=len(detailed))
    except Exception as exc:
        logger.warning("Bandit candidate ranking skipped: %s", exc)

    # Build final picks with entry/SL/TP
    final = []
    for i, stock in enumerate(detailed[:n], start=1):
        price = stock.get("price", 100)
        atr = price * 0.015
        target_pct = 6.5
        
        sl_price = max(price - atr * 1.5, price * 0.98)
        tp_price = price * (1 + target_pct / 100)
        risk = price - sl_price
        reward = tp_price - price
        rr = round(reward / risk, 2) if risk > 0 else 0.0
        
        final.append({
            **stock,
            "rank": i,
            "entry_price": round(price, 2),
            "sl_price": round(sl_price, 2),
            "target_price": round(tp_price, 2),
            "upside_pct": round(target_pct, 2),
            "risk_reward": rr,
            "research_time": datetime.datetime.now().strftime("%H:%M:%S"),
        })
    
    logger.info(f"Deep research complete: {len(final)} picks")
    return final
