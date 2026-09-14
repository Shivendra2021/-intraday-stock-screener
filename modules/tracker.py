# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
tracker.py — Every 5 minutes: check open picks against live prices, scan for intraday movers.
"""

import sqlite3
import logging
import datetime
import pandas as pd

logger = logging.getLogger(__name__)


def _fetch_live_price(symbol: str) -> float | None:
    """Fetch latest price via yfinance 1m data."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{symbol}.NS")
        df = ticker.history(period="1d", interval="1m")
        if df is None or df.empty:
            ticker = yf.Ticker(f"{symbol}.BO")
            df = ticker.history(period="1d", interval="1m")
        if df is not None and not df.empty:
            # Normalize column names and handle Series vs scalar
            df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
            close_val = df["close"].values[-1] if "close" in df.columns else df["Close".lower()].values[-1]
            return float(close_val)
    except Exception as e:
        logger.debug(f"Live price fetch failed for {symbol}: {e}")
    return None


def _get_open_picks() -> list:
    """Return all picks with status='pending' for today."""
    from config import DB_PATH
    try:
        from modules.time_utils import today_ist_str

        today = today_ist_str()
    except Exception:
        today = datetime.date.today().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM picks WHERE status='pending' AND date=? AND COALESCE(source_label,'') NOT LIKE 'quant_v3:%' "
            "AND COALESCE(session_type, 'morning_final')='morning_final' "
            "AND COALESCE(is_official_morning, 1)=1",
            (today,),
        ).fetchall()
    return [dict(r) for r in rows]


def _update_pick_status(pick_id: int, status: str, result_return: float):
    """Update pick status and result in DB."""
    from config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE picks SET status=?, result_return=? WHERE id=? AND COALESCE(source_label,'') NOT LIKE 'quant_v3:%' "
            "AND COALESCE(session_type, 'morning_final')='morning_final' "
            "AND COALESCE(is_official_morning, 1)=1",
            (status, round(result_return, 4), pick_id)
        )
        conn.commit()


def _scan_intraday_movers(universe_sample: list = None) -> list:
    """
    Scan for stocks up 3%+ with volume spike.
    Uses a sample to avoid rate-limiting yfinance.
    """
    try:
        import yfinance as yf
        from modules.scanner import get_universe

        if universe_sample is None:
            universe = get_universe()
            # Deterministic first 100 instead of random.sample
            universe_sample = universe[:100]

        movers = []
        for sym in universe_sample:
            try:
                ticker = yf.Ticker(f"{sym}.NS")
                df = ticker.history(period="2d", interval="1d")
                if df is None or len(df) < 2:
                    continue
                # Normalize column names
                df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
                prev_close = float(df["close"].values[-2])
                curr_price = float(df["close"].values[-1])
                curr_vol   = float(df["volume"].values[-1])
                prev_vol   = float(df["volume"].values[-2])

                move_pct  = (curr_price - prev_close) / prev_close * 100
                vol_ratio = curr_vol / prev_vol if prev_vol > 0 else 1.0

                if move_pct >= 3.0 and vol_ratio >= 1.5:
                    movers.append({
                        "symbol":    sym,
                        "move_pct":  round(move_pct, 2),
                        "vol_ratio": round(vol_ratio, 2),
                        "price":     round(curr_price, 2),
                    })
            except Exception:
                continue

        movers.sort(key=lambda x: x["move_pct"], reverse=True)
        return movers[:10]

    except Exception as e:
        logger.error(f"Intraday mover scan failed: {e}")
        return []


def _scan_top_gainers(num_stocks: int = 50) -> list:
    """
    Scan for top gainers - stocks up the most today.
    Returns top 10 gainers with percentage.
    """
    try:
        import yfinance as yf
        from modules.scanner import get_universe

        universe = get_universe()
        # Scan first N stocks
        scan_list = universe[:num_stocks]

        gainers = []
        for sym in scan_list:
            try:
                ticker = yf.Ticker(f"{sym}.NS")
                df = ticker.history(period="2d", interval="1d")
                if df is None or len(df) < 2:
                    continue
                # Normalize column names
                df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
                prev_close = float(df["close"].values[-2])
                curr_price = float(df["close"].values[-1])

                if prev_close > 0:
                    gain_pct = ((curr_price - prev_close) / prev_close) * 100
                    gainers.append({
                        "symbol":    sym,
                        "gain_pct":  round(gain_pct, 2),
                        "price":     round(curr_price, 2),
                    })
            except Exception:
                continue

        gainers.sort(key=lambda x: x["gain_pct"], reverse=True)
        return gainers[:10]

    except Exception as e:
        logger.error(f"Top gainers scan failed: {e}")
        return []


def _get_top10_performers(num_stocks: int = 500) -> list:
    """
    Scan for top 10 performers of the day - after market close.
    Returns top 10 gainers and top 10 losers.
    """
    try:
        import yfinance as yf
        from modules.scanner import get_universe

        universe = get_universe()
        # Scan more stocks for better results
        scan_list = universe[:num_stocks]

        gainers = []
        losers = []

        for sym in scan_list:
            try:
                ticker = yf.Ticker(f"{sym}.NS")
                df = ticker.history(period="2d", interval="1d")
                if df is None or len(df) < 2:
                    continue
                # Normalize column names
                df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
                prev_close = float(df["close"].values[-2])
                curr_price = float(df["close"].values[-1])

                if prev_close > 0:
                    gain_pct = ((curr_price - prev_close) / prev_close) * 100
                    stock_data = {
                        "symbol":    sym,
                        "gain_pct":  round(gain_pct, 2),
                        "price":     round(curr_price, 2),
                    }
                    if gain_pct > 0:
                        gainers.append(stock_data)
                    else:
                        losers.append(stock_data)
            except Exception:
                continue

        gainers.sort(key=lambda x: x["gain_pct"], reverse=True)
        losers.sort(key=lambda x: x["gain_pct"])

        return {
            "gainers": gainers[:10],
            "losers": losers[:10]
        }

    except Exception as e:
        logger.error(f"Top performers scan failed: {e}")
        return {"gainers": [], "losers": []}


def run_tracker():
    """
    Main tracker function — called every 5 minutes.
    1. Check open picks vs live prices.
    2. Scan for intraday momentum movers.
    """
    from modules.alerts import send_tp_hit, send_sl_hit, send_intraday_alert

    logger.info("Tracker run started")

    # ── Check open picks ──────────────────────────────────────────────────────
    open_picks = _get_open_picks()
    logger.info(f"Checking {len(open_picks)} open picks")

    for pick in open_picks:
        price = _fetch_live_price(pick["symbol"])
        if price is None:
            logger.debug(f"Could not fetch price for {pick['symbol']}")
            continue

        entry  = pick["entry_price"]
        target = pick["target_price"]
        sl     = pick["sl_price"]

        if price >= target:
            ret = (price - entry) / entry * 100
            _update_pick_status(pick["id"], "tp_hit", ret)
            logger.info(f"TP HIT: {pick['symbol']} +{ret:.2f}%")
            send_tp_hit(pick["symbol"], ret)

        elif price <= sl:
            ret = (price - entry) / entry * 100  # negative
            _update_pick_status(pick["id"], "sl_hit", ret)
            logger.info(f"SL HIT: {pick['symbol']} {ret:.2f}%")
            send_sl_hit(pick["symbol"], abs(ret))

        else:
            logger.debug(f"{pick['symbol']}: ₹{price:.2f} (tracking — "
                         f"SL=₹{sl:.2f}, Target=₹{target:.2f})")

    # ── Intraday momentum scan ────────────────────────────────────────────────
    movers = _scan_intraday_movers()
    if movers:
        logger.info(f"Intraday movers found: {[m['symbol'] for m in movers[:5]]}")
        send_intraday_alert(movers)

    logger.info("Tracker run complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_tracker()
