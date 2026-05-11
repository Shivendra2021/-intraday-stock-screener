# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
preclose_watchlist.py — 3 PM scan: stocks up 4–7% with volume spike.
"""

import sqlite3
import logging
import datetime

logger = logging.getLogger(__name__)


def _fetch_intraday_snapshot(symbol: str) -> dict | None:
    """Fetch today's open, current price, and volume ratio for a symbol."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.NS")
        df = ticker.history(period="2d", interval="1d")
        if df is None or len(df) < 2:
            return None

        # Normalize column names
        df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
        
        open_price    = float(df["open"].values[-1])
        current_price = float(df["close"].values[-1])
        vol_today     = float(df["volume"].values[-1])
        vol_prev      = float(df["volume"].values[-2])

        move_pct  = (current_price - open_price) / open_price * 100
        vol_ratio = vol_today / vol_prev if vol_prev > 0 else 1.0

        return {
            "symbol":        symbol,
            "open_price":    round(open_price, 2),
            "current_price": round(current_price, 2),
            "move_pct":      round(move_pct, 2),
            "vol_ratio":     round(vol_ratio, 2),
        }
    except Exception as e:
        logger.debug(f"Preclose snapshot failed for {symbol}: {e}")
        return None


def run_preclose_scan():
    """
    Scan universe for stocks:
    - move_pct between 4% and 7% (open to current)
    - vol_ratio >= 1.5
    Take top 10, write to preclose_watchlist, send Telegram alert.
    """
    from config import DB_PATH
    from modules.scanner import get_universe
    from modules.alerts import send_preclose

    today = datetime.date.today().isoformat()
    universe = get_universe()
    logger.info(f"Pre-close scan: checking {len(universe)} symbols")

    candidates = []
    for sym in universe:
        snap = _fetch_intraday_snapshot(sym)
        if snap is None:
            continue
        if 4.0 <= snap["move_pct"] <= 7.0 and snap["vol_ratio"] >= 1.5:
            candidates.append(snap)

    candidates.sort(key=lambda x: x["move_pct"], reverse=True)
    top10 = candidates[:10]

    if not top10:
        logger.info("Pre-close scan: no qualifying stocks found")
        return []

    # Write to DB
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM preclose_watchlist WHERE date=?", (today,))
        for s in top10:
            conn.execute(
                """INSERT INTO preclose_watchlist
                   (date, symbol, open_price, current_price, move_pct, vol_ratio)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (today, s["symbol"], s["open_price"], s["current_price"],
                 s["move_pct"], s["vol_ratio"])
            )
        conn.commit()

    logger.info(f"Pre-close watchlist: {[s['symbol'] for s in top10]}")
    send_preclose(top10)
    return top10


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = run_preclose_scan()
    for r in results:
        print(f"{r['symbol']:12} +{r['move_pct']:.1f}%  Vol:{r['vol_ratio']:.1f}x")
