# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
analyzer.py — Download OHLCV, calculate indicators, score every stock in universe.
Uses multiprocessing.Pool(8) for parallelism (Windows-safe).
"""

import logging
import sqlite3
import datetime
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Single-stock analysis (runs in worker process)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_ohlcv(symbol: str, period: str = "3mo") -> pd.DataFrame:
    """
    Download yfinance OHLCV via the centralised fetch module.
    Handles: symbol aliases (e.g. TATAMOTORS→TMCV), NS→BO fallback,
    rate-limit backoff, and silent failure.
    """
    from modules.fetch import fetch_ohlcv
    return fetch_ohlcv(symbol, period)


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100)
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain == 0)), 50)
    return rsi.fillna(50)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    atr = _atr(high, low, close, length).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / length, min_periods=length, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / length, min_periods=length, adjust=False).mean() / atr
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(alpha=1 / length, min_periods=length, adjust=False).mean().fillna(20)


def _calculate_indicators(df: pd.DataFrame) -> dict:
    """Calculate all technical indicators. Returns dict of indicator values."""
    try:
        import pandas_ta as ta
    except ImportError as e:
        logger.debug(f"pandas_ta not installed; using built-in indicators: {e}")
        ta = None

    if df.empty or len(df) < 30:
        return {}

    try:
        close  = df["close"].astype(float)
        high   = df["high"].astype(float)
        low    = df["low"].astype(float)
        volume = df["volume"].astype(float)

        # RSI(14)
        if ta:
            rsi_series = ta.rsi(close, length=14)
            rsi = float(rsi_series.values[-1]) if rsi_series is not None and not rsi_series.empty else 50.0
        else:
            rsi = float(_rsi(close, length=14).values[-1])

        # MACD
        if ta:
            macd_df = ta.macd(close, fast=12, slow=26, signal=9)
            if macd_df is not None and not macd_df.empty:
                macd_val  = float(macd_df.iloc[-1, 0])
                macd_sig  = float(macd_df.iloc[-1, 2])
            else:
                macd_val = macd_sig = 0.0
        else:
            macd_line = _ema(close, 12) - _ema(close, 26)
            signal_line = _ema(macd_line, 9)
            macd_val = float(macd_line.values[-1]) if pd.notna(macd_line.values[-1]) else 0.0
            macd_sig = float(signal_line.values[-1]) if pd.notna(signal_line.values[-1]) else 0.0

        # EMA 9, 21, 50
        if ta:
            ema9  = ta.ema(close, length=9)
            ema21 = ta.ema(close, length=21)
            ema50 = ta.ema(close, length=50)
        else:
            ema9 = _ema(close, 9)
            ema21 = _ema(close, 21)
            ema50 = _ema(close, 50)
        ema9_val  = float(ema9.values[-1])  if ema9  is not None and not ema9.empty  else float(close.values[-1])
        ema21_val = float(ema21.values[-1]) if ema21 is not None and not ema21.empty else float(close.values[-1])
        ema50_val = float(ema50.values[-1]) if ema50 is not None and not ema50.empty else float(close.values[-1])

        price = float(close.values[-1])
        ema_full_bull = (price > ema9_val > ema21_val > ema50_val)
        ema_partial   = (price > ema21_val) and not ema_full_bull

        if ema_full_bull:
            ema_alignment = "EMA_full_bull"
        elif ema_partial:
            ema_alignment = "EMA_partial_bull"
        else:
            ema_alignment = "EMA_bear"

        # Bollinger Bands
        if ta:
            bb = ta.bbands(close, length=20, std=2)
            if bb is not None and not bb.empty:
                bb_upper = float(bb.iloc[-1, 0])
                bb_lower = float(bb.iloc[-1, 2])
                bb_range = bb_upper - bb_lower
                bb_position = (price - bb_lower) / bb_range if bb_range > 0 else 0.5
            else:
                bb_position = 0.5
        else:
            bb_mid = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            bb_upper = float((bb_mid + 2 * bb_std).values[-1])
            bb_lower = float((bb_mid - 2 * bb_std).values[-1])
            bb_range = bb_upper - bb_lower
            bb_position = (price - bb_lower) / bb_range if bb_range > 0 else 0.5

        # ADX(14)
        if ta:
            adx_df = ta.adx(high, low, close, length=14)
            if adx_df is not None and not adx_df.empty:
                adx = float(adx_df.iloc[-1, 0])
            else:
                adx = 20.0
        else:
            adx = float(_adx(high, low, close, length=14).values[-1])

        # ATR(14)
        if ta:
            atr_series = ta.atr(high, low, close, length=14)
            atr = float(atr_series.values[-1]) if atr_series is not None and not atr_series.empty else price * 0.02
        else:
            atr_series = _atr(high, low, close, length=14)
            atr = float(atr_series.values[-1]) if pd.notna(atr_series.values[-1]) else price * 0.02

        # Volume ratio (today vs 20-day avg)
        vol_20avg = float(volume.rolling(20).mean().values[-1])
        vol_today = float(volume.values[-1])
        vol_ratio = vol_today / vol_20avg if vol_20avg > 0 else 1.0

        # Gap up (today open vs yesterday close)
        prev_close = float(close.values[-2]) if len(close) > 1 else price
        today_open = float(df["open"].values[-1]) if "open" in df.columns else price
        gap_up = ((today_open - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

        # Avg daily volume (20-day)
        avg_volume = vol_20avg

        return {
            "price":         price,
            "rsi":           rsi,
            "macd_val":      macd_val,
            "macd_sig":      macd_sig,
            "ema9":          ema9_val,
            "ema21":         ema21_val,
            "ema50":         ema50_val,
            "ema_alignment": ema_alignment,
            "ema_full_bull": ema_full_bull,
            "bb_position":   bb_position,
            "adx":           adx,
            "atr":           atr,
            "vol_ratio":     vol_ratio,
            "gap_up":        gap_up,
            "avg_volume":    avg_volume,
        }
    except Exception as e:
        logger.debug(f"Indicator calculation error: {e}")
        return {}


def _load_patterns() -> dict:
    """Load learned patterns from DB. Returns {pattern_key: (success_rate, proven_level, is_anti)}."""
    try:
        from config import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT pattern_key, success_rate, proven_level, is_anti_pattern FROM patterns"
            ).fetchall()
        return {r[0]: (r[1], r[2], r[3]) for r in rows}
    except Exception:
        return {}


def _build_pattern_key(ind: dict) -> str:
    """Build deterministic pattern key from indicator snapshot."""
    rsi = ind.get("rsi", 50.0)
    if rsi < 40:
        rsi_bucket = "RSI_under40"
    elif rsi < 50:
        rsi_bucket = "RSI_40to50"
    elif rsi < 55:
        rsi_bucket = "RSI_50to55"
    elif rsi < 65:
        rsi_bucket = "RSI_55to65"
    elif rsi < 70:
        rsi_bucket = "RSI_65to70"
    else:
        rsi_bucket = "RSI_over70"

    vr = ind.get("vol_ratio", 1.0)
    if vr < 0.8:
        vol_bucket = "VOL_low"
    elif vr < 1.2:
        vol_bucket = "VOL_normal"
    elif vr < 2.0:
        vol_bucket = "VOL_high"
    else:
        vol_bucket = "VOL_veryhigh"

    macd_bucket = "MACD_pos" if ind.get("macd_val", 0) > ind.get("macd_sig", 0) else "MACD_neg"
    ema_bucket  = ind.get("ema_alignment", "EMA_bear")

    return f"{rsi_bucket}__{vol_bucket}__{macd_bucket}__{ema_bucket}"


def _score_stock(symbol: str) -> dict | None:
    """
    Full pipeline for a single stock:
    download → indicators → filters → score → return dict.
    Returns None if stock fails filters.
    """
    from config import MIN_PRICE_FILTER, MIN_VOLUME_FILTER, MIN_SCORE_THRESHOLD

    df = _fetch_ohlcv(symbol)
    if df.empty:
        return None

    ind = _calculate_indicators(df)
    if not ind:
        return None

    price      = ind.get("price", 0)
    avg_volume = ind.get("avg_volume", 0)

    # Hard filters
    if price < MIN_PRICE_FILTER:
        return None
    if avg_volume < MIN_VOLUME_FILTER:
        return None

    # ── Sentiment ─────────────────────────────────────────────────────────────
    try:
        from modules.news import get_sentiment
        sentiment = get_sentiment(symbol)
    except Exception:
        sentiment = 0.0

    # ── Pattern boost ─────────────────────────────────────────────────────────
    patterns = _load_patterns()
    pattern_key = _build_pattern_key(ind)
    pattern_boost = 0.0
    if pattern_key in patterns:
        sr, proven, is_anti = patterns[pattern_key]
        if is_anti:
            pattern_boost = -10.0
        elif proven == "weekly":
            pattern_boost = sr * 20
        elif proven == "daily":
            pattern_boost = sr * 15
        else:
            pattern_boost = sr * 8

    # ── Sub-scores (0–100 each) ───────────────────────────────────────────────
    rsi = ind["rsi"]
    # RSI score: best at 50-65 for momentum
    if 50 <= rsi <= 65:
        rsi_score = 100
    elif 40 <= rsi < 50 or 65 < rsi <= 70:
        rsi_score = 70
    elif 30 <= rsi < 40 or 70 < rsi <= 80:
        rsi_score = 40
    else:
        rsi_score = 10

    # MACD score
    macd_val = ind["macd_val"]
    macd_sig = ind["macd_sig"]
    if macd_val > 0 and macd_val > macd_sig:
        macd_score = 100
    elif macd_val > macd_sig:
        macd_score = 60
    elif macd_val > 0:
        macd_score = 40
    else:
        macd_score = 10

    # EMA score
    if ind["ema_alignment"] == "EMA_full_bull":
        ema_score = 100
    elif ind["ema_alignment"] == "EMA_partial_bull":
        ema_score = 50
    else:
        ema_score = 10

    # Volume score
    vr = ind["vol_ratio"]
    if vr >= 2.0:
        volume_score = 100
    elif vr >= 1.5:
        volume_score = 80
    elif vr >= 1.2:
        volume_score = 60
    elif vr >= 0.8:
        volume_score = 30
    else:
        volume_score = 10

    # Breakout score (BB position + ADX + gap)
    bb_pos  = ind["bb_position"]  # 0=at lower, 1=at upper
    adx     = ind["adx"]
    gap_pct = ind["gap_up"]
    breakout_score = 0
    if bb_pos > 0.8:
        breakout_score += 40
    elif bb_pos > 0.5:
        breakout_score += 20
    if adx >= 25:
        breakout_score += 40
    elif adx >= 20:
        breakout_score += 20
    if gap_pct >= 1.5:
        breakout_score += 20
    elif gap_pct >= 0.5:
        breakout_score += 10
    breakout_score = min(100, breakout_score)

    # Sentiment score (normalize -1..1 to 0..100)
    sentiment_score = (sentiment + 1.0) / 2.0 * 100

    # ── Final score ───────────────────────────────────────────────────────────
    score = (
        rsi_score       * 0.15 +
        macd_score      * 0.15 +
        ema_score       * 0.10 +
        volume_score    * 0.20 +
        breakout_score  * 0.15 +
        sentiment_score * 0.10 +
        pattern_boost   * 0.15
    )
    score = max(0, min(100, score))

    if score < MIN_SCORE_THRESHOLD:
        return None

    signal_reasons = []
    if rsi_score >= 70:
        signal_reasons.append(f"RSI={rsi:.1f}(bullish)")
    if macd_score >= 60:
        signal_reasons.append("MACD_crossover")
    if ind["ema_alignment"] == "EMA_full_bull":
        signal_reasons.append("EMA_full_bull")
    if vr >= 1.5:
        signal_reasons.append(f"Vol={vr:.1f}x")
    if gap_pct >= 1.0:
        signal_reasons.append(f"Gap+{gap_pct:.1f}%")
    if pattern_key in patterns and not patterns[pattern_key][2]:
        signal_reasons.append(f"Pattern:{pattern_key[:30]}")

    return {
        "symbol":         symbol,
        "score":          round(score, 2),
        "price":          price,
        "rsi":            round(rsi, 2),
        "macd_val":       round(macd_val, 4),
        "macd_sig":       round(macd_sig, 4),
        "ema_alignment":  ind["ema_alignment"],
        "bb_position":    round(ind["bb_position"], 3),
        "adx":            round(ind["adx"], 2),
        "atr":            round(ind["atr"], 4),
        "vol_ratio":      round(vr, 3),
        "gap_up":         round(gap_pct, 3),
        "sentiment":      round(sentiment, 3),
        "pattern_key":    pattern_key,
        "signal_reasons": "; ".join(signal_reasons),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

def analyze_all(symbols: list = None) -> list:
    """
    Score all stocks in universe. Returns list of dicts, sorted by score desc.
    Uses multiprocessing.Pool with dynamic sizing.
    """
    import multiprocessing
    import os

    if symbols is None:
        from modules.scanner import get_universe
        symbols = get_universe()

    # Dynamic pool size based on available cores
    pool_size = min(8, os.cpu_count() or 4)
    logger.info(f"Analyzing {len(symbols)} symbols with Pool({pool_size})...")

    results = []
    try:
        with multiprocessing.Pool(pool_size) as pool:
            raw = pool.map(_score_stock, symbols)
        results = [r for r in raw if r is not None]
    except Exception as e:
        logger.error(f"Multiprocessing failed, falling back to serial: {e}")
        for sym in symbols:
            try:
                r = _score_stock(sym)
                if r:
                    results.append(r)
            except Exception as ex:
                logger.debug(f"Serial fallback error for {sym}: {ex}")

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"analyze_all complete: {len(results)} stocks passed filters")
    return results


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # Windows required
    logging.basicConfig(level=logging.INFO)
    results = analyze_all(["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"])
    for r in results:
        print(f"{r['symbol']:15} score={r['score']:.1f}  RSI={r['rsi']:.1f}  vol={r['vol_ratio']:.2f}x")
