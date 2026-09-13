"""
stock_selector.py — Select final 5 stocks from ~50 sector candidates.

Flow:
  1. Get top-3 sectors from sector_analyzer
  2. Build ~50-stock candidate pool from those sectors
  3. Score each stock (RSI, RVOL20, EMA200 alignment, ATR exhaustion, VWAP)
  4. Gate/boost score with composite quant formula
  5. Return top-N with full entry/SL/TP data

New Quant Scoring Formula (v2):
  Score = (30 × RVOL_Score) + (25 × Macro_Trend_Score) + (25 × Unspent_ATR_Score) - Audit_Penalties
  Range: 0-100 (after clamping)
"""

from __future__ import annotations
import logging
import datetime
import json
import os
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

AUDIT_RULES_PATH = "data/audit_rules.json"


def _load_audit_penalties() -> dict[str, float]:
    """Load symbol-level audit penalty scores from audit_rules.json (0-20 range)."""
    try:
        if os.path.exists(AUDIT_RULES_PATH):
            with open(AUDIT_RULES_PATH, "r", encoding="utf-8") as f:
                rules = json.load(f)
            penalties: dict[str, float] = {}
            for rule in rules.get("penalty_rules", []):
                sym = rule.get("symbol", "")
                pts = float(rule.get("penalty_pts", 0))
                if sym and pts > 0:
                    penalties[sym] = min(20.0, pts)
            return penalties
    except Exception:
        pass
    return {}


def _calc_rvol_score(vol_series: "pd.Series", current_vol: float) -> tuple[float, float]:
    """
    Calculate RVOL = current_vol / SMA(Vol, 20) and return (rvol, normalized_score 0-1).
    Score = 1.0 at RVOL >= 2.0, 0.0 at RVOL < 0.5.
    """
    avg_20 = float(vol_series.rolling(20, min_periods=10).mean().iloc[-1])
    if avg_20 <= 0:
        return 1.0, 0.5
    rvol = current_vol / avg_20
    if rvol >= 2.0:
        score = 1.0
    elif rvol >= 1.8:
        score = 0.85
    elif rvol >= 1.5:
        score = 0.65
    elif rvol >= 1.2:
        score = 0.45
    elif rvol >= 1.0:
        score = 0.3
    else:
        score = max(0.0, rvol / 1.0 * 0.2)
    return round(rvol, 4), round(score, 4)


def _calc_atr_exhaustion_score(day_high: float, day_low: float, daily_atr: float) -> tuple[float, float]:
    """
    Calculate how much of daily ATR the stock has already consumed.
    Daily Expansion % = (Day High - Day Low) / Daily ATR * 100
    Returns (expansion_pct, normalized_score 0-1).
    Score = 1.0 at < 40% consumed (high continuation potential).
    Score = 0.0 at >= 90% consumed (move is over, skip).
    Returns (-1, -1) as sentinel if stock should be EXCLUDED (>= 90% consumed).
    """
    if daily_atr <= 0:
        return 0.0, 0.5
    expansion_pct = (day_high - day_low) / daily_atr * 100
    if expansion_pct >= 90.0:
        return round(expansion_pct, 2), -1.0  # sentinel: exclude
    elif expansion_pct <= 40.0:
        score = 1.0
    elif expansion_pct <= 60.0:
        score = 0.7
    elif expansion_pct <= 75.0:
        score = 0.4
    else:
        score = 0.15
    return round(expansion_pct, 2), round(score, 4)


def _calc_macro_alignment_score(price: float, ema200: float, vwap: float,
                                  weekly_trend: str = "unknown") -> tuple[str, float]:
    """
    Multi-Timeframe (MTF) macro alignment check.
    Checks 3 tiers:
      - Weekly Trend: EMA10w > EMA30w (macro tailwind)
      - Daily Trend:  Price > EMA200 (structural bull)
      - Intraday:     Price > VWAP (session momentum)
    
    Returns (alignment_label, score 0-1).
    """
    above_ema200 = price > ema200 if ema200 > 0 else True
    above_vwap = price > vwap if vwap > 0 else True

    # Base dual-timeframe score
    if above_ema200 and above_vwap:
        label, base_score = "full_bull", 1.0
    elif not above_ema200 and not above_vwap:
        label, base_score = "full_bear", 0.0
    elif above_ema200:
        label, base_score = "ema_bull_vwap_bear", 0.5
    else:
        label, base_score = "ema_bear_vwap_bull", 0.35

    # Weekly trend MTF bonus/penalty (±0.10)
    if weekly_trend == "bull":
        base_score = min(1.0, base_score + 0.10)
        label = label + "_weekly_bull"
    elif weekly_trend == "bear":
        base_score = max(0.0, base_score - 0.10)
        label = label + "_weekly_bear"

    return label, round(base_score, 4)


def _calc_weekly_trend(df_daily: "pd.DataFrame") -> str:
    """
    Determine weekly macro trend by resampling daily bars to weekly.
    Returns 'bull' if Weekly EMA10 > Weekly EMA30, 'bear' otherwise.
    Zero extra API calls — pure resampling of existing daily data.
    """
    try:
        if df_daily is None or len(df_daily) < 20:
            return "unknown"
        if not isinstance(df_daily.index, pd.DatetimeIndex):
            if "date" in df_daily.columns:
                df = df_daily.set_index(pd.to_datetime(df_daily["date"]))
            else:
                try:
                    df = df_daily.set_index(pd.to_datetime(df_daily.index))
                except Exception:
                    return "unknown"
        else:
            df = df_daily
        weekly = df["close"].resample("W").last().dropna()
        if len(weekly) < 6:
            return "unknown"
        ema10w = float(weekly.ewm(span=10, adjust=False).mean().iloc[-1])
        min_p = min(6, len(weekly))
        ema30w = float(weekly.ewm(span=30, adjust=False, min_periods=min_p).mean().iloc[-1])
        return "bull" if ema10w > ema30w else "bear"
    except Exception:
        return "unknown"


def _calc_vwap(df_intraday: "pd.DataFrame") -> float:
    """Calculate VWAP from intraday OHLCV data."""
    try:
        tp = (df_intraday["high"].astype(float) + df_intraday["low"].astype(float) + df_intraday["close"].astype(float)) / 3
        vol = df_intraday["volume"].astype(float)
        cumvol = vol.cumsum()
        if float(cumvol.iloc[-1]) <= 0:
            return float(df_intraday["close"].iloc[-1])
        vwap = float((tp * vol).cumsum().iloc[-1] / cumvol.iloc[-1])
        return vwap
    except Exception:
        return 0.0


def _calc_close_location_value(price: float, day_high: float, day_low: float) -> float:
    """
    Close Location Value (CLV): measures where price closed within the day's range.
    CLV = (Price - Low) / (High - Low)  ∈ [0, 1]
    CLV > 0.80 = aggressive buying pressure (institutional accumulation)
    CLV < 0.20 = selling pressure / distribution
    Zero cost: uses price data already fetched.
    """
    if day_high <= day_low or day_high <= 0:
        return 0.5  # neutral fallback
    clv = (price - day_low) / (day_high - day_low)
    return round(max(0.0, min(1.0, clv)), 4)


def _calc_spread_to_atr_ratio(bid: float, ask: float, atr: float) -> float:
    """
    Spread-to-ATR ratio: detects illiquidity traps.
    High spread relative to ATR = stock is too illiquid to trade safely.
    Returns ratio (lower is better). Threshold: reject if > 0.02 (2% of ATR).
    Zero cost: uses bid/ask already fetched in _check_bid_ask_spread.
    """
    if atr <= 0 or bid <= 0 or ask <= 0:
        return 0.0  # unknown, fail-open
    spread = max(0.0, ask - bid)
    return round(spread / atr, 6)


def _is_earnings_frozen(sym: str) -> bool:
    """
    Check if the stock should be frozen due to earnings today or a macro event
    within 30 minutes. Uses config EARNINGS_FREEZE_SYMBOLS and MACRO_EVENTS_TODAY.
    Always returns False if config keys are absent (fail-open).
    """
    try:
        import config
        earnings_today: list[str] = getattr(config, "EARNINGS_FREEZE_SYMBOLS", [])
        if sym in earnings_today:
            return True
        macro_events: list[dict] = getattr(config, "MACRO_EVENTS_TODAY", [])
        now = datetime.datetime.now()
        for evt in macro_events:
            try:
                evt_time = datetime.datetime.strptime(evt.get("time", ""), "%H:%M")
                evt_dt = now.replace(hour=evt_time.hour, minute=evt_time.minute, second=0, microsecond=0)
                if 0 <= (evt_dt - now).total_seconds() <= 1800:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _check_bid_ask_spread(sym: str, price: float, atr: float = 0.0) -> bool:
    """
    Check if bid-ask spread is within acceptable range (< 0.05% of price
    and spread/ATR <= 0.02 if ATR is provided).
    Returns True if spread is acceptable (or unknown — fail-open).
    Uses yfinance fast_info if available.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{sym}.NS")
        info = ticker.fast_info
        bid = getattr(info, "bid", None) or 0.0
        ask = getattr(info, "ask", None) or 0.0
        if bid > 0 and ask > 0:
            if price > 0:
                spread_pct = (ask - bid) / price * 100
                if spread_pct > 0.05:
                    return False  # too wide
            if atr > 0:
                spread_atr = _calc_spread_to_atr_ratio(bid, ask, atr)
                if spread_atr > 0.02:
                    return False  # illiquidity trap relative to ATR
    except Exception:
        pass
    return True  # fail-open


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
    Score a single stock for intraday momentum potential using the MT5 Institutional Quant Engine:
      1. RVOL(20) Breakout Filter (gated at >= 1.8x, bull trap flagged if < 1.0)
      2. ATR Exhaustion / ADR Cap (excluded if >= 90%, boosted if < 40%)
      3. Dual-Timeframe Macro Alignment (Price > EMA200 AND Price > VWAP)
      4. Self-Learning Auditor penalty deduction
      5. Macro Event Horizon & Earnings Freeze (News Guard)
      6. Composite Quant Formula: Score = 30*RVOL + 25*Macro + 25*Unspent_ATR - Audit_Penalties + Tech_Boost
    """
    from modules.fetch import fetch_ohlcv
    from modules.scanner import is_small_or_midcap
    from modules.auditor import get_audit_penalty

    if not is_small_or_midcap(sym):
        return None

    # Component 5: Earnings freeze check
    if _is_earnings_frozen(sym):
        logger.debug("Stock %s disqualified: Earnings freeze active", sym)
        return None

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
        avg_vol = float(vol.rolling(20, min_periods=10).mean().iloc[-1])
        if avg_vol < 50_000:
            return None
        current_vol = float(vol.iloc[-1])

        # Component 1: Vectorized Relative Volume (RVOL 20)
        rvol, rvol_score = _calc_rvol_score(vol, current_vol)

        # Price metrics
        prev_close = float(close.iloc[-2])
        today_open = float(open_s.iloc[-1])
        day_high   = float(high_s.iloc[-1])
        day_low    = float(low_s.iloc[-1])
        gap_up_pct = (today_open - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        daily_chg  = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        prior_5d_pct = 0.0
        if len(close) >= 6 and float(close.iloc[-6]) > 0:
            prior_5d_pct = (price - float(close.iloc[-6])) / float(close.iloc[-6]) * 100

        # Highs and breakout checks
        high_20d   = float(high_s.rolling(20, min_periods=10).max().iloc[-1])
        high_52w   = float(high_s.rolling(252, min_periods=60).max().iloc[-1])
        dist_20d   = (high_20d - price) / high_20d * 100 if high_20d > 0 else 999.0
        dist_52w   = (high_52w - price) / high_52w * 100 if high_52w > 0 else 999.0
        breakout_20d_high = day_high >= high_20d if high_20d > 0 else False
        close_location = (price - today_open) / (day_high - today_open) if day_high > today_open else 0.0

        # Component 1 Bull Trap Warning: New intraday high on RVOL < 1.0
        bull_trap_warning = bool(breakout_20d_high and rvol < 1.0)
        if bull_trap_warning:
            rvol_score = 0.0  # Penalize low volume fakeouts

        # ATR calculation
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

        # Component 2: ATR Exhaustion / Average Daily Range (ADR) Cap
        expansion_pct, unspent_atr_score = _calc_atr_exhaustion_score(day_high, day_low, atr)
        if unspent_atr_score < 0:
            # Rejection rule: >= 90% of daily ATR already consumed
            logger.debug("Stock %s disqualified: ATR Exhaustion %.1f%% >= 90%%", sym, expansion_pct)
            return None

        # Component 5 & 6: Bid-Ask spread (< 0.05%) & Spread-to-ATR (<= 0.02) check
        if not _check_bid_ask_spread(sym, price, atr):
            logger.debug("Stock %s disqualified: Bid-Ask spread / Spread-to-ATR check failed", sym)
            return None

        # EMA Indicators
        ema9   = float(close.ewm(span=9,   adjust=False, min_periods=9).mean().iloc[-1])
        ema21  = float(close.ewm(span=21,  adjust=False, min_periods=21).mean().iloc[-1])
        ema50  = float(close.ewm(span=50,  adjust=False, min_periods=50).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False, min_periods=30).mean().iloc[-1]) if len(close) >= 30 else 0.0
        vwap   = _calc_vwap(df)

        ema_full    = price > ema9 > ema21 > ema50
        ema_partial = price > ema21 and not ema_full
        ema_align   = "EMA_full_bull" if ema_full else ("EMA_partial_bull" if ema_partial else "EMA_bear")

        # Component 3: Multi-Timeframe Macro Alignment (Weekly + Daily EMA200 + VWAP)
        weekly_trend = _calc_weekly_trend(df)
        macro_align, macro_score = _calc_macro_alignment_score(price, ema200, vwap, weekly_trend)
        if "full_bear" in macro_align:
            # Rejection rule: price < EMA200 AND price < VWAP -> reject long signal
            logger.debug("Stock %s rejected: Full bear macro alignment (below EMA200 and VWAP)", sym)
            return None

        # Check resistance: Running directly into major EMA200 overhead (< 0.75% below EMA200)
        if ema200 > price and ((ema200 - price) / price * 100) < 0.75:
            macro_score = max(0.0, macro_score - 0.3)

        # RSI
        delta = close.diff()
        gain  = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = float((100 - 100 / (1 + rs)).fillna(50).iloc[-1])

        # Component 4: Self-Learning Auditor penalty deduction
        audit_penalty, audit_reasons = get_audit_penalty(sym, {
            "rsi": rsi,
            "rvol": rvol,
            "expansion_pct": expansion_pct,
            "macro_alignment": macro_align,
            "breakout_20d_high": breakout_20d_high,
            "price": price,
        })

        # Microstructure: Close Location Value (CLV) — buying pressure signal
        clv = _calc_close_location_value(price, day_high, day_low)

        # Technical momentum base boost (0 - 25 pts, increased from 20 for microstructure)
        tech_boost = 0.0
        if 55 <= rsi <= 70:
            tech_boost += 8.0
        elif 50 <= rsi < 55:
            tech_boost += 4.0
        if adx >= 25:
            tech_boost += 6.0
        if dist_52w <= 3.0:
            tech_boost += 6.0
        # Microstructure CLV bonus: aggressive buying pressure at close
        if clv >= 0.80:
            tech_boost += 5.0  # strong institutional accumulation signal
        elif clv <= 0.20:
            tech_boost -= 3.0  # distribution / selling pressure penalty

        # Composite Institutional Quant Score Formula (v3 — with MTF + Microstructure):
        # Score = (30 × RVOL) + (25 × Macro MTF) + (25 × Unspent ATR) - Audit Penalties + Tech Boost
        quant_score = (30.0 * rvol_score) + (25.0 * macro_score) + (25.0 * unspent_atr_score) - audit_penalty + tech_boost
        final_score = round(min(100.0, max(0.0, quant_score)), 2)

        # Patterns
        patterns = []
        if rvol >= 1.8:                            patterns.append(f"high_rvol_{rvol:.1f}x")
        if unspent_atr_score >= 0.9:               patterns.append(f"unspent_atr_{expansion_pct:.0f}%")
        if "full_bull" in macro_align:             patterns.append("macro_trend_aligned")
        if dist_52w <= 3.0:                        patterns.append("52wk_high_proximity")
        if gap_up_pct >= 1.5 and rvol >= 1.5:      patterns.append("gap_breakout")
        if ema_full and rsi >= 55:                  patterns.append("ema_momentum")
        if bull_trap_warning:                      patterns.append("bull_trap_warning")
        if clv >= 0.80:                            patterns.append("clv_accumulation")
        if weekly_trend == "bull":                 patterns.append("weekly_bull_trend")

        return {
            "symbol":            sym,
            "score":             final_score,
            "quant_score":       final_score,
            "price":             round(price, 2),
            "rsi":               round(rsi, 2),
            "adx":               round(adx, 2),
            "atr":               round(atr, 4),
            "rvol":              round(rvol, 2),
            "rvol_score":        round(rvol_score, 2),
            "expansion_pct":     round(expansion_pct, 2),
            "unspent_atr_score": round(unspent_atr_score, 2),
            "macro_alignment":   macro_align,
            "macro_score":       round(macro_score, 2),
            "ema200":            round(ema200, 2),
            "vwap":              round(vwap, 2),
            "audit_penalty":     round(audit_penalty, 2),
            "audit_reasons":     audit_reasons,
            "bull_trap_warning": bull_trap_warning,
            "ema_alignment":     ema_align,
            "weekly_trend":      weekly_trend,
            "clv":               round(clv, 4),
            "vol_ratio":         round(rvol, 2),
            "gap_up":            round(gap_up_pct, 2),
            "daily_change":      round(daily_chg, 2),
            "prior_5d_pct":      round(prior_5d_pct, 2),
            "dist_20d_high_pct": round(dist_20d, 2),
            "dist_52w_high":     round(dist_52w, 2),
            "breakout_20d_high": bool(breakout_20d_high),
            "close_location":    round(close_location, 2),
            "avg_volume":        int(avg_vol),
            "patterns":          patterns,
            "signal_reasons":    "; ".join(patterns) if patterns else "quant_momentum",
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
            
            # MT5 Institutional Quant Engine components
            rvol, rvol_score = _calc_rvol_score(volume, float(volume.iloc[-1]))
            day_high = float(high.iloc[-1])
            day_low  = float(low.iloc[-1])
            atr_val  = float(atr.iloc[-1]) if hasattr(atr, 'iloc') else float(atr)
            expansion_pct, unspent_atr_score = _calc_atr_exhaustion_score(day_high, day_low, atr_val)

            # Rejection rule: If ATR consumed >= 90%, do not buy
            if unspent_atr_score < 0:
                logger.debug("deep_research: %s disqualified by ATR exhaustion %.1f%%", sym, expansion_pct)
                continue

            # Component 5 & 6: Bid-Ask spread & Spread-to-ATR check
            if not _check_bid_ask_spread(sym, price, atr_val):
                logger.debug("deep_research: %s disqualified by bid-ask / spread-to-ATR", sym)
                continue

            ema200 = float(close.ewm(span=200, adjust=False, min_periods=30).mean().iloc[-1]) if len(close) >= 30 else 0.0
            vwap = _calc_vwap(df)
            weekly_trend = _calc_weekly_trend(df)
            macro_align, macro_score = _calc_macro_alignment_score(price, ema200, vwap, weekly_trend)

            # Rejection rule: Price below EMA200 and below VWAP
            if "full_bear" in macro_align:
                logger.debug("deep_research: %s rejected by macro bear alignment", sym)
                continue

            # Check resistance: Running directly into major EMA200 overhead (< 0.75% below EMA200)
            if ema200 > price and ((ema200 - price) / price * 100) < 0.75:
                macro_score = max(0.0, macro_score - 0.3)

            # Bull trap check
            high_20d = float(high.rolling(20, min_periods=10).max().iloc[-1])
            is_new_high = day_high >= high_20d if high_20d > 0 else False
            bull_trap_warning = bool(is_new_high and rvol < 1.0)
            if bull_trap_warning:
                rvol_score = 0.0

            # Self-Learning Auditor penalty
            from modules.auditor import get_audit_penalty
            audit_penalty, audit_reasons = get_audit_penalty(sym, {
                "rsi": rsi,
                "rvol": rvol,
                "expansion_pct": expansion_pct,
                "macro_alignment": macro_align,
                "breakout_20d_high": is_new_high,
                "price": price,
            })

            # Microstructure: Close Location Value (CLV)
            clv = _calc_close_location_value(price, day_high, day_low)

            # Base momentum & technical bonus (0 - 25 pts)
            tech_bonus = 0.0
            if 45 <= rsi <= 65:
                tech_bonus += 6.0
            if macd_bull:
                tech_bonus += 4.0
            if adx >= 25:
                tech_bonus += 4.0
            if gap_high <= 5:
                tech_bonus += 3.0
            if news_score > 0:
                tech_bonus += 3.0
            # Microstructure CLV bonus
            if clv >= 0.80:
                tech_bonus += 5.0
            elif clv <= 0.20:
                tech_bonus -= 3.0

            # Composite Quant Score Formula (0 - 100):
            # Score = (30 × RVOL) + (25 × Macro Alignment) + (25 × Unspent ATR) - Audit Penalties + Tech Bonus
            quant_score = (30.0 * rvol_score) + (25.0 * macro_score) + (25.0 * unspent_atr_score) - audit_penalty + tech_bonus
            score = round(min(100.0, max(0.0, quant_score)), 2)

            patterns = list(stock.get("patterns", []))
            if clv >= 0.80 and "clv_accumulation" not in patterns:
                patterns.append("clv_accumulation")
            if weekly_trend == "bull" and "weekly_bull_trend" not in patterns:
                patterns.append("weekly_bull_trend")

            detailed.append({
                **stock,
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
                "rvol": round(rvol, 2),
                "rvol_score": round(rvol_score, 2),
                "expansion_pct": round(expansion_pct, 2),
                "unspent_atr_score": round(unspent_atr_score, 2),
                "macro_alignment": macro_align,
                "macro_score": round(macro_score, 2),
                "ema200": round(ema200, 2),
                "vwap": round(vwap, 2),
                "weekly_trend": weekly_trend,
                "clv": round(clv, 4),
                "audit_penalty": round(audit_penalty, 2),
                "audit_reasons": audit_reasons,
                "bull_trap_warning": bull_trap_warning,
                "patterns": patterns,
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

        # Real-time catalyst detection (SerpApi Google News & Tavily)
        catalyst_info = None
        try:
            from modules.catalyst_search import get_stock_catalyst
            catalyst_info = get_stock_catalyst(stock.get("symbol", ""))
        except Exception as exc:
            logger.debug("Catalyst lookup failed for %s: %s", stock.get("symbol"), exc)

        final.append({
            **stock,
            "rank": i,
            "entry_price": round(price, 2),
            "sl_price": round(sl_price, 2),
            "target_price": round(tp_price, 2),
            "upside_pct": round(target_pct, 2),
            "risk_reward": rr,
            "catalyst": catalyst_info.get("summary") if catalyst_info else None,
            "catalyst_headline": catalyst_info.get("headline") if catalyst_info else None,
            "catalyst_type": catalyst_info.get("catalyst_type") if catalyst_info else None,
            "research_time": datetime.datetime.now().strftime("%H:%M:%S"),
        })
    
    logger.info(f"Deep research complete: {len(final)} picks")
    return final
