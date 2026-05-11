# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
evaluator.py — Runs at 15:35. Close out pending picks, log accuracy.
"""

import sqlite3
import logging
import datetime

logger = logging.getLogger(__name__)


def _fetch_closing_price(symbol: str) -> float | None:
    """Fetch today's closing price from yfinance."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.NS")
        df = ticker.history(period="1d", interval="1d")
        if df is not None and not df.empty:
            # Normalize column names
            df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
            return float(df["close"].values[-1])
    except Exception as e:
        logger.debug(f"Close price fetch failed for {symbol}: {e}")
    return None


def run_evaluator():
    """
    End-of-day evaluation:
    1. Close remaining 'pending' picks as 'open_eod' with closing price return.
    2. Count tp/sl/open_eod.
    3. Write daily_accuracy row.
    4. Send daily summary alert.
    """
    from config import DB_PATH
    from modules.alerts import send_summary
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()

    today = datetime.date.today().isoformat()
    logger.info(f"Running evaluator for {today}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Close pending picks at EOD price
        pending = conn.execute(
            "SELECT id, symbol, entry_price FROM picks WHERE date=? AND status='pending'",
            (today,)
        ).fetchall()

        for pick in pending:
            close_price = _fetch_closing_price(pick["symbol"])
            if close_price:
                ret = (close_price - pick["entry_price"]) / pick["entry_price"] * 100
            else:
                ret = 0.0
            conn.execute(
                "UPDATE picks SET status='open_eod', result_return=? WHERE id=?",
                (round(ret, 4), pick["id"])
            )
        conn.commit()
        logger.info(f"Closed {len(pending)} pending picks as open_eod")

        try:
            from modules.post_market_learning import run_post_market_learning
            learning = run_post_market_learning(today)
            logger.info(f"Post-market learning: {learning}")
        except Exception as e:
            logger.error(f"Post-market learning failed: {e}")

        # Aggregate today's picks
        rows = conn.execute(
            "SELECT status, result_return FROM picks WHERE date=?", (today,)
        ).fetchall()

    tp_count    = sum(1 for r in rows if r["status"] == "tp_hit")
    sl_count    = sum(1 for r in rows if r["status"] == "sl_hit")
    total       = len(rows)
    closed      = tp_count + sl_count
    accuracy    = (tp_count / closed * 100) if closed > 0 else 0.0
    returns     = [r["result_return"] for r in rows if r["result_return"] is not None]
    avg_return  = sum(returns) / len(returns) if returns else 0.0

    logger.info(f"Today: TP={tp_count} SL={sl_count} Total={total} Accuracy={accuracy:.1f}%")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_accuracy
               (date, tp_count, sl_count, total, accuracy, avg_return)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (today, tp_count, sl_count, total, round(accuracy, 2), round(avg_return, 4))
        )
        conn.commit()

    stats = {
        "tp_count":   tp_count,
        "sl_count":   sl_count,
        "total":      total,
        "accuracy":   accuracy,
        "avg_return": avg_return,
    }
    send_summary(stats)
    logger.info("Evaluator complete")
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    stats = run_evaluator()
    print(stats)
