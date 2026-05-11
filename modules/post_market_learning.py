"""Post-market learning from actual intraday path versus predicted SL/target."""

from __future__ import annotations

import datetime
import logging
import sqlite3

logger = logging.getLogger(__name__)


def _intraday_path(symbol: str) -> dict | None:
    try:
        import yfinance as yf

        df = yf.Ticker(f"{symbol}.NS").history(period="1d", interval="5m")
        if df is None or df.empty:
            df = yf.Ticker(f"{symbol}.BO").history(period="1d", interval="5m")
        if df is None or df.empty:
            return None
        df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
        return {
            "high": float(df["high"].max()),
            "low": float(df["low"].min()),
            "close": float(df["close"].iloc[-1]),
        }
    except Exception as exc:
        logger.debug("Intraday path failed for %s: %s", symbol, exc)
    return None


def _classify(entry: float, sl: float, target: float, path: dict) -> tuple[str, float]:
    high = path["high"]
    low = path["low"]
    close = path["close"]

    hit_target = high >= target
    hit_sl = low <= sl
    if hit_target and not hit_sl:
        return "target_hit", (target - entry) / entry * 100
    if hit_sl and not hit_target:
        return "stopped_out", (sl - entry) / entry * 100
    if hit_target and hit_sl:
        # Conservative ordering when 5m candles cannot prove which fired first.
        return "ambiguous_sl_first", (sl - entry) / entry * 100
    return "closed_eod", (close - entry) / entry * 100


def _update_pattern_rate(conn: sqlite3.Connection, pattern_key: str, won: bool) -> None:
    if not pattern_key:
        return
    today = datetime.date.today().isoformat()
    row = conn.execute(
        "SELECT success_rate, sample_count FROM patterns WHERE pattern_key=?", (pattern_key,)
    ).fetchone()
    today_rate = 1.0 if won else 0.0
    if row:
        old_rate = row[0] or 0.5
        sample_count = row[1] or 0
        alpha = 0.25 if sample_count >= 10 else 0.5
        new_rate = old_rate * (1 - alpha) + today_rate * alpha
        conn.execute(
            """UPDATE patterns
               SET success_rate=?, sample_count=?, source='post_market_learning',
                   proven_level=CASE
                     WHEN ? >= 0.60 AND ? + 1 >= 10 THEN 'weekly'
                     ELSE 'daily'
                   END,
                   is_anti_pattern=CASE WHEN ? <= 0.35 AND ? + 1 >= 8 THEN 1 ELSE is_anti_pattern END,
                   last_market_update=?
               WHERE pattern_key=?""",
            (
                round(new_rate, 4),
                sample_count + 1,
                new_rate,
                sample_count,
                new_rate,
                sample_count,
                today,
                pattern_key,
            ),
        )
    else:
        conn.execute(
            """INSERT INTO patterns
               (pattern_key, success_rate, sample_count, source, proven_level,
                is_anti_pattern, last_market_update)
               VALUES (?, ?, 1, 'post_market_learning', 'daily', 0, ?)""",
            (pattern_key, today_rate, today),
        )


def run_post_market_learning(target_date: str | None = None) -> dict:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables
    from modules.pattern_backtester import refresh_pattern_backtests

    ensure_research_tables()
    date = target_date or datetime.date.today().isoformat()
    learned = 0
    skipped = 0
    outcomes = {"target_hit": 0, "stopped_out": 0, "ambiguous_sl_first": 0, "closed_eod": 0}
    now = datetime.datetime.now().isoformat(timespec="seconds")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        picks = conn.execute(
            """SELECT * FROM picks
               WHERE date=? AND entry_price IS NOT NULL
               AND sl_price IS NOT NULL AND target_price IS NOT NULL""",
            (date,),
        ).fetchall()

        for pick in picks:
            path = _intraday_path(pick["symbol"])
            if not path:
                skipped += 1
                continue

            outcome, ret = _classify(
                float(pick["entry_price"]),
                float(pick["sl_price"]),
                float(pick["target_price"]),
                path,
            )
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            won = outcome == "target_hit"
            pattern_key = pick["pattern_key"] or ""

            conn.execute(
                """INSERT INTO pattern_outcomes
                   (date, symbol, pattern_key, entry_price, sl_price, target_price,
                    intraday_high, intraday_low, close_price, outcome, result_return,
                    score, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    date,
                    pick["symbol"],
                    pattern_key,
                    pick["entry_price"],
                    pick["sl_price"],
                    pick["target_price"],
                    path["high"],
                    path["low"],
                    path["close"],
                    outcome,
                    round(ret, 4),
                    pick["confidence"],
                    now,
                ),
            )
            conn.execute(
                "UPDATE picks SET status=?, result_return=? WHERE id=? AND status IN ('pending','open_eod')",
                (outcome if outcome != "closed_eod" else "open_eod", round(ret, 4), pick["id"]),
            )
            _update_pattern_rate(conn, pattern_key, won)
            learned += 1

        conn.commit()

    refresh_pattern_backtests()
    logger.info("Post-market learning complete: learned=%s skipped=%s", learned, skipped)
    return {"learned": learned, "skipped": skipped, "outcomes": outcomes}
