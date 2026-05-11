# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
market_learner.py — After-market self-learning engine.
Runs at 15:35. Identifies today's winners/losers, extracts indicator patterns,
updates the patterns table with exponential smoothing.
"""

import sqlite3
import logging
import datetime
import pandas as pd

logger = logging.getLogger(__name__)

WINNER_THRESHOLD = 5.5   # % intraday return to qualify as winner
LOSER_THRESHOLD  = -3.0  # % intraday return to qualify as loser
ANTI_PATTERN_LOSER_SHARE  = 0.35  # pattern in 35%+ of losers
ANTI_PATTERN_WINNER_SHARE = 0.15  # AND <15% of winners


# ─────────────────────────────────────────────────────────────────────────────
# Pattern key builder (same logic as analyzer.py for consistency)
# ─────────────────────────────────────────────────────────────────────────────

def _build_pattern_key(rsi: float, vol_ratio: float, macd_val: float,
                        macd_sig: float, ema_alignment: str) -> str:
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

    if vol_ratio < 0.8:
        vol_bucket = "VOL_low"
    elif vol_ratio < 1.2:
        vol_bucket = "VOL_normal"
    elif vol_ratio < 2.0:
        vol_bucket = "VOL_high"
    else:
        vol_bucket = "VOL_veryhigh"

    macd_bucket = "MACD_pos" if macd_val > macd_sig else "MACD_neg"
    return f"{rsi_bucket}__{vol_bucket}__{macd_bucket}__{ema_alignment}"


# ─────────────────────────────────────────────────────────────────────────────
# Yesterday's indicator snapshot for a symbol
# ─────────────────────────────────────────────────────────────────────────────

def _get_yesterday_indicators(symbol: str) -> dict | None:
    """Download 60d of data, calculate indicators as of yesterday's close."""
    try:
        import yfinance as yf
        from modules.analyzer import _build_pattern_key, _calculate_indicators

        df = yf.download(f"{symbol}.NS", period="60d", interval="1d",
                         auto_adjust=True, progress=False)
        if df is None or df.empty or len(df) < 30:
            return None

        # Normalize column names (handle MultiIndex tuples and case)
        df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower()
                      for c in df.columns]

        hist = df.iloc[:-1]
        ind = _calculate_indicators(hist)
        if not ind:
            return None

        # Today's gap
        today_open  = float(df["open"].iloc[-1])
        yest_close  = float(df["close"].iloc[-2])
        gap_up      = (today_open - yest_close) / yest_close * 100 if yest_close > 0 else 0.0

        pattern_key = _build_pattern_key(ind)

        return {
            "rsi":           round(ind.get("rsi", 50), 2),
            "macd_val":      round(ind.get("macd_val", 0), 4),
            "macd_sig":      round(ind.get("macd_sig", 0), 4),
            "ema_alignment": ind.get("ema_alignment", "EMA_bear"),
            "vol_ratio":     round(ind.get("vol_ratio", 1), 3),
            "adx":           round(ind.get("adx", 20), 2),
            "bb_position":   round(ind.get("bb_position", 0.5), 3),
            "gap_up":        round(gap_up, 3),
            "pattern_key":   pattern_key,
        }
    except Exception as e:
        logger.debug(f"Indicator extraction failed for {symbol}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Intraday return calculation
# ─────────────────────────────────────────────────────────────────────────────

def _get_intraday_return(symbol: str) -> float | None:
    """Calculate today's intraday return: max(open_to_high, open_to_close)."""
    try:
        import yfinance as yf
        df = yf.download(f"{symbol}.NS", period="1d", interval="1d",
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        df.columns = [c.lower() if isinstance(c, str) else c[0].lower()
                      for c in df.columns]
        open_p  = float(df["open"].iloc[-1])
        high_p  = float(df["high"].iloc[-1])
        close_p = float(df["close"].iloc[-1])
        if open_p <= 0:
            return None
        open_to_high  = (high_p  - open_p) / open_p * 100
        open_to_close = (close_p - open_p) / open_p * 100
        return round(max(open_to_high, open_to_close), 4)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Exponential smoothing
# ─────────────────────────────────────────────────────────────────────────────

def _smooth_rate(old_rate: float, today_rate: float, sample_count: int) -> float:
    """Apply exponential smoothing to success rate."""
    if sample_count < 10:
        return 0.5 * old_rate + 0.5 * today_rate
    else:
        return 0.7 * old_rate + 0.3 * today_rate


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _upsert_pattern(conn, pattern_key: str, today_rate: float, source: str):
    """Upsert a pattern with exponential smoothing."""
    today_str = datetime.date.today().isoformat()
    existing = conn.execute(
        "SELECT success_rate, sample_count FROM patterns WHERE pattern_key=?",
        (pattern_key,)
    ).fetchone()

    if existing:
        old_rate     = existing[0] or 0.5
        sample_count = existing[1] or 0
        new_rate     = _smooth_rate(old_rate, today_rate, sample_count)
        conn.execute(
            """UPDATE patterns SET success_rate=?, sample_count=?, source=?,
               proven_level='daily', last_market_update=?
               WHERE pattern_key=?""",
            (round(new_rate, 4), sample_count + 1, source, today_str, pattern_key)
        )
    else:
        conn.execute(
            """INSERT INTO patterns
               (pattern_key, success_rate, sample_count, source, proven_level,
                is_anti_pattern, last_market_update)
               VALUES (?, ?, 1, ?, 'daily', 0, ?)""",
            (pattern_key, round(today_rate, 4), source, today_str)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main learning pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_market_learner(symbols: list = None):
    """
    Full market learning pipeline. Runs after market close (15:35).
    """
    from config import DB_PATH
    from modules.scanner import get_universe

    today = datetime.date.today().isoformat()
    logger.info("Market learner started")

    if symbols is None:
        symbols = get_universe()

    winners = []  # {symbol, sector, intraday_return, indicators}
    losers  = []  # {symbol, intraday_return, pattern_key}

    logger.info(f"Scanning {len(symbols)} stocks for today's winners/losers")
    for sym in symbols:
        ret = _get_intraday_return(sym)
        if ret is None:
            continue

        if ret >= WINNER_THRESHOLD:
            ind = _get_yesterday_indicators(sym)
            if ind:
                winners.append({"symbol": sym, "intraday_return": ret, **ind})
        elif ret <= LOSER_THRESHOLD:
            ind = _get_yesterday_indicators(sym)
            if ind:
                losers.append({"symbol": sym, "intraday_return": ret,
                               "pattern_key": ind["pattern_key"]})

    logger.info(f"Winners: {len(winners)}, Losers: {len(losers)}")

    with sqlite3.connect(DB_PATH) as conn:
        # ── Step 2: Save winners ─────────────────────────────────────────────
        for w in winners:
            conn.execute(
                """INSERT INTO market_winners
                   (date, symbol, sector, intraday_return, rsi_yesterday, macd_yesterday,
                    ema_alignment, volume_ratio, bb_position, adx, gap_up, pattern_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (today, w["symbol"], w.get("sector", ""),
                 w["intraday_return"], w.get("rsi", 0), w.get("macd_val", 0),
                 w.get("ema_alignment", ""), w.get("vol_ratio", 1),
                 w.get("bb_position", 0.5), w.get("adx", 0),
                 w.get("gap_up", 0), w.get("pattern_key", ""))
            )

        # ── Step 3: Save losers ──────────────────────────────────────────────
        for l in losers:
            conn.execute(
                """INSERT INTO market_losers (date, symbol, intraday_return, pattern_key)
                   VALUES (?, ?, ?, ?)""",
                (today, l["symbol"], l["intraday_return"], l.get("pattern_key", ""))
            )

        conn.commit()

        # ── Step 4: Update patterns with exponential smoothing ───────────────
        winner_keys = [w["pattern_key"] for w in winners if w.get("pattern_key")]
        loser_keys  = [l["pattern_key"] for l in losers  if l.get("pattern_key")]
        all_keys    = set(winner_keys + loser_keys)
        total_w     = max(len(winner_keys), 1)
        total_l     = max(len(loser_keys),  1)

        for key in all_keys:
            w_count = winner_keys.count(key)
            l_count = loser_keys.count(key)
            total   = w_count + l_count
            if total == 0:
                continue
            today_rate = w_count / total
            _upsert_pattern(conn, key, today_rate, "market_data")

        conn.commit()

        # ── Step 5: Anti-pattern detection ───────────────────────────────────
        for key in all_keys:
            w_share = winner_keys.count(key) / total_w
            l_share = loser_keys.count(key)  / total_l
            if l_share >= ANTI_PATTERN_LOSER_SHARE and w_share < ANTI_PATTERN_WINNER_SHARE:
                conn.execute(
                    "UPDATE patterns SET is_anti_pattern=1 WHERE pattern_key=?", (key,)
                )
                logger.info(f"Anti-pattern flagged: {key}")

        conn.commit()

    logger.info(f"Market learner complete. Updated {len(all_keys)} patterns")
    return {"winners": len(winners), "losers": len(losers), "patterns_updated": len(all_keys)}


def run_weekly_review():
    """
    Runs every Friday at 16:00.
    Promotes 'daily' patterns to 'weekly' if they appeared 3+ of last 5 trading days
    and have success_rate >= 0.60.
    """
    from config import DB_PATH

    logger.info("Weekly pattern review started")
    cutoff = (datetime.date.today() - datetime.timedelta(days=8)).isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        # Find all daily patterns
        daily_patterns = conn.execute(
            "SELECT pattern_key FROM patterns WHERE proven_level='daily'"
        ).fetchall()

        for (key,) in daily_patterns:
            # Count distinct days this key appeared in last ~5 trading days
            days_appeared = conn.execute(
                """SELECT COUNT(DISTINCT date) FROM market_winners
                   WHERE pattern_key=? AND date >= ?""",
                (key, cutoff)
            ).fetchone()[0]

            success_rate = conn.execute(
                "SELECT success_rate FROM patterns WHERE pattern_key=?", (key,)
            ).fetchone()

            if success_rate and days_appeared >= 3 and success_rate[0] >= 0.60:
                conn.execute(
                    "UPDATE patterns SET proven_level='weekly' WHERE pattern_key=?", (key,)
                )
                logger.info(f"Pattern promoted to weekly: {key} "
                            f"(appeared {days_appeared} days, SR={success_rate[0]:.2f})")

        conn.commit()

    logger.info("Weekly review complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_market_learner(["RELIANCE", "TCS", "INFY", "SBIN", "HDFCBANK"])
    print(result)
