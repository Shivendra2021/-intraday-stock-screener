# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
learner.py — Runs at 15:45. Learns from today's own picks (tp_hit vs sl_hit).
Updates patterns table with source='own_picks'.
"""

import sqlite3
import logging
import datetime

logger = logging.getLogger(__name__)


def _get_todays_results() -> tuple[list, list]:
    """Return (winners, losers) from today's picks."""
    from config import DB_PATH
    try:
        from modules.time_utils import today_ist_str

        today = today_ist_str()
    except Exception:
        today = datetime.date.today().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM picks WHERE date=? "
            "AND COALESCE(session_type, 'morning_final')='morning_final' "
            "AND COALESCE(is_official_morning, 1)=1",
            (today,),
        ).fetchall()

    winners = [dict(r) for r in rows if r["status"] == "tp_hit"]
    losers  = [dict(r) for r in rows if r["status"] == "sl_hit"]
    return winners, losers


def _extract_pattern_key_from_pick(pick: dict) -> str | None:
    """
    Re-derive pattern_key for a pick using today's indicator data.
    Falls back to building from stored signal_reasons if available.
    """
    symbol = pick.get("symbol")
    if not symbol:
        return None
    if pick.get("pattern_key"):
        return pick.get("pattern_key")

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

        ind = _calculate_indicators(df.iloc[:-1])
        return _build_pattern_key(ind) if ind else None

    except Exception as e:
        logger.debug(f"Pattern key extraction failed for {symbol}: {e}")
        return None


def _update_own_picks_patterns(winner_keys: list, loser_keys: list):
    """Update patterns table based on own picks performance."""
    from config import DB_PATH
    try:
        from modules.time_utils import today_ist_str

        today_str = today_ist_str()
    except Exception:
        today_str = datetime.date.today().isoformat()
    all_keys  = set(winner_keys + loser_keys)

    if not all_keys:
        logger.info("No pattern keys to update from own picks")
        return

    with sqlite3.connect(DB_PATH) as conn:
        for key in all_keys:
            w = winner_keys.count(key)
            l = loser_keys.count(key)
            total = w + l
            if total == 0:
                continue

            today_rate = w / total
            existing = conn.execute(
                "SELECT success_rate, sample_count FROM patterns WHERE pattern_key=?", (key,)
            ).fetchone()

            if existing:
                old_rate     = existing[0] or 0.5
                sample_count = existing[1] or 0
                alpha        = 0.5 if sample_count < 10 else 0.3
                new_rate     = (1 - alpha) * old_rate + alpha * today_rate
                conn.execute(
                    """UPDATE patterns SET success_rate=?, sample_count=?,
                       source='own_picks', last_market_update=?
                       WHERE pattern_key=?""",
                    (round(new_rate, 4), sample_count + 1, today_str, key)
                )
            else:
                conn.execute(
                    """INSERT INTO patterns
                       (pattern_key, success_rate, sample_count, source, proven_level,
                        is_anti_pattern, last_market_update)
                       VALUES (?, ?, 1, 'own_picks', 'none', 0, ?)""",
                    (key, round(today_rate, 4), today_str)
                )

        conn.commit()
    logger.info(f"Updated {len(all_keys)} patterns from own picks")


def run_learner():
    """
    Main own-picks learning loop.
    Extracts indicator patterns from today's picks and updates patterns table.
    """
    logger.info("Own-picks learner started")

    winners, losers = _get_todays_results()
    logger.info(f"Today's picks: {len(winners)} TP hits, {len(losers)} SL hits")

    if not winners and not losers:
        logger.info("No completed picks to learn from today")
        return

    winner_keys = []
    for pick in winners:
        key = _extract_pattern_key_from_pick(pick)
        if key:
            winner_keys.append(key)

    loser_keys = []
    for pick in losers:
        key = _extract_pattern_key_from_pick(pick)
        if key:
            loser_keys.append(key)

    _update_own_picks_patterns(winner_keys, loser_keys)
    
    # Update Contextual Bandit with today's realized results
    try:
        from modules.bandit_selector import update_bandit_eod
        update_bandit_eod(winners + losers)
    except Exception as exc:
        logger.warning("Contextual Bandit EOD update skipped: %s", exc)

    logger.info(f"Own-picks learner complete. "
                f"Winner keys: {winner_keys}, Loser keys: {loser_keys}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_learner()
