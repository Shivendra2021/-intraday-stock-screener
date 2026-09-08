# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
quick_status.py — Instant status from terminal.
Shows today's picks, current movers, and bot health.
Usage: python quick_status.py
"""

import sqlite3
import sys
import os
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DB_PATH, DRY_RUN


def today_str():
    try:
        from modules.time_utils import today_ist_str
        return today_ist_str()
    except Exception:
        return datetime.date.today().isoformat()


def market_status():
    try:
        from modules.scanner import is_market_holiday, is_market_open
        from modules.time_utils import today_ist
        today = today_ist()
        if today.weekday() >= 5:
            return "Weekend"
        if is_market_holiday(today):
            return "Holiday"
        return "Open" if is_market_open() else "Closed"
    except Exception:
        return "Unknown"


def is_trading_day(status=None):
    return (status or market_status()) not in {"Weekend", "Holiday"}


def section(title):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


def get_todays_picks():
    """Get today's picks."""
    today = today_str()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT symbol, entry_price, sl_price, target_price, 
                   confidence, status 
                   FROM picks WHERE date=?
                   AND COALESCE(session_type, 'morning_final')='morning_final'
                   AND COALESCE(is_official_morning, 1)=1
                   ORDER BY rank""",
                (today,)
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"Error: {e}")
        return []


def get_current_gainers():
    """Scan for current gainers."""
    try:
        import yfinance as yf
        from modules.scanner import get_universe

        universe = get_universe()
        scan_list = universe[:50]  # Scan top 50

        gainers = []
        for sym in scan_list:
            try:
                ticker = yf.Ticker(f"{sym}.NS")
                df = ticker.history(period="2d", interval="1d")
                if df is None or len(df) < 2:
                    continue
                df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
                prev_close = float(df["close"].values[-2])
                curr_price = float(df["close"].values[-1])
                if prev_close > 0:
                    gain_pct = ((curr_price - prev_close) / prev_close) * 100
                    if gain_pct > 0:
                        gainers.append({
                            "symbol": sym,
                            "gain_pct": round(gain_pct, 2),
                            "price": round(curr_price, 2)
                        })
            except Exception:
                continue

        gainers.sort(key=lambda x: x["gain_pct"], reverse=True)
        return gainers[:10]
    except Exception as e:
        print(f"Error scanning gainers: {e}")
        return []


def get_health():
    """Get bot health stats."""
    stats = {}
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Universe count
            stats["universe"] = conn.execute(
                "SELECT COUNT(*) FROM stock_universe WHERE is_active=1"
            ).fetchone()[0]

            # Today's picks
            today = today_str()
            stats["today_picks"] = conn.execute(
                "SELECT COUNT(*) FROM picks WHERE date=? "
                "AND COALESCE(session_type, 'morning_final')='morning_final' "
                "AND COALESCE(is_official_morning, 1)=1",
                (today,)
            ).fetchone()[0]

            # Overall accuracy
            tp = conn.execute("SELECT SUM(tp_count) FROM daily_accuracy").fetchone()[0] or 0
            sl = conn.execute("SELECT SUM(sl_count) FROM daily_accuracy").fetchone()[0] or 0
            total = tp + sl
            stats["accuracy"] = round(tp / total * 100, 1) if total > 0 else 0
            stats["total_tp"] = tp
            stats["total_sl"] = sl

            # Last activity
            last_pick = conn.execute(
                "SELECT date FROM picks WHERE COALESCE(session_type, 'morning_final')='morning_final' "
                "AND COALESCE(is_official_morning, 1)=1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
            stats["last_pick"] = last_pick[0] if last_pick else "Never"

    except Exception as e:
        print(f"Error: {e}")

    return stats


def main():
    print(f"\n{'='*55}")
    print("  MARKETMIND PRO - QUICK STATUS")
    print(f"{'='*55}")
    try:
        from modules.time_utils import now_ist
        now_label = now_ist().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        now_label = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"  {now_label}")
    print(f"  Mode: {'DRY_RUN (TEST)' if DRY_RUN else 'ACTIVE'}")
    status_now = market_status()
    print(f"  Market: {status_now}")

    # Today's Picks
    section("TODAY'S PICKS")
    picks = get_todays_picks()
    if picks:
        # Calculate upside for display
        print(f"{'#':<4} {'Symbol':<12} {'Entry':>8} {'SL':>8} {'Target':>8} {'Status'}")
        print(f"{'-'*50}")
        for i, p in enumerate(picks, 1):
            entry = p['entry_price']
            target = p['target_price']
            upside = ((target - entry) / entry * 100) if entry > 0 else 0
            print(f"{i:<4} {p['symbol']:<12} {entry:>8.2f} {p['sl_price']:>8.2f} "
                  f"{target:>8.2f} {upside:>6.1f}% {p['status']}")
    else:
        if is_trading_day(status_now):
            print("  No official morning picks generated today yet.")
        else:
            print(f"  {status_now}; official morning picks are not expected today.")

    # Current Gainers
    section("CURRENT TOP MOVERS")
    if not is_trading_day(status_now):
        print(f"  {status_now}; live top-mover scan skipped.")
    else:
        print("  Scanning top 50 stocks...\n")
        gainers = get_current_gainers()
        if gainers:
            print(f"{'#':<4} {'Symbol':<12} {'Gain %':>8} {'Price':>10}")
            print(f"{'-'*34}")
            for i, g in enumerate(gainers, 1):
                print(f"{i:<4} {g['symbol']:<12} +{g['gain_pct']:>7.2f}% {g['price']:>10.2f}")
        else:
            print("  No gainers found.")

    # Health
    section("BOT HEALTH")
    health = get_health()
    status = "HEALTHY" if health.get("universe", 0) > 0 else "ERROR"
    print(f"  Universe:        {health.get('universe', 0)} stocks")
    print(f"  Today's Picks:   {health.get('today_picks', 0)}")
    print(f"  Total TP:         {health.get('total_tp', 0)}")
    print(f"  Total SL:         {health.get('total_sl', 0)}")
    print(f"  Accuracy:        {health.get('accuracy', 0):.1f}%")
    print(f"  Last Pick:       {health.get('last_pick', 'Never')}")
    print(f"  Status:          {status}")

    print(f"\n{'='*55}\n")


if __name__ == "__main__":
    main()
