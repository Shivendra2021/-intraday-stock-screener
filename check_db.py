# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
check_db.py — Print DB stats, recent picks, accuracy, and top patterns.
Usage: python check_db.py
"""

import sqlite3
import os

DB_PATH = "data/history.db"


def section(title):
    print(f"\n{'-'*55}")
    print(f"  {title}")
    print(f"{'-'*55}")


def check_db():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. Run init_system.py first.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Row counts
        section("Table Row Counts")
        tables = ["stock_universe", "picks", "patterns", "pattern_backtests",
                  "pattern_outcomes", "price_validations", "daily_accuracy",
                  "market_winners", "market_losers", "preclose_watchlist",
                  "grok_evidence_reviews"]
        for t in tables:
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                print(f"  {t:<28} {n:>6} rows")
            except Exception as e:
                print(f"  {t:<28} ERROR: {e}")

        # Last 5 picks
        section("Last 5 Picks")
        try:
            rows = conn.execute(
                "SELECT date, rank, symbol, entry_price, sl_price, target_price, "
                "confidence, status, result_return FROM picks ORDER BY id DESC LIMIT 5"
            ).fetchall()
            if not rows:
                print("  No picks yet.")
            else:
                print(f"  Date         # Symbol        Entry    SL      Target  Conf   Status       Return")
                print(f"  {'-'*75}")
                for r in rows:
                    ret = f"{r['result_return']:.2f}%" if r['result_return'] is not None else "-"
                    print(f"  {r['date']} {r['rank']:>2} {r['symbol']:<12} "
                          f"{r['entry_price']:>7.2f} {r['sl_price']:>7.2f} "
                          f"{r['target_price']:>7.2f} {r['confidence']:>5.1f} "
                          f"{r['status']:<11} {ret:>7}")
        except Exception as e:
            print(f"  Error: {e}")

        # Overall accuracy
        section("Overall Accuracy Stats")
        try:
            rows = conn.execute(
                "SELECT SUM(tp_count) as total_tp, SUM(sl_count) as total_sl, "
                "AVG(accuracy) as avg_acc, AVG(avg_return) as avg_ret "
                "FROM daily_accuracy"
            ).fetchone()
            if rows and rows["total_tp"] is not None:
                total = (rows["total_tp"] or 0) + (rows["total_sl"] or 0)
                acc = rows["avg_acc"] or 0
                print(f"  Total TP hits    : {rows['total_tp']}")
                print(f"  Total SL hits    : {rows['total_sl']}")
                print(f"  Overall accuracy : {acc:.1f}%")
                print(f"  Avg daily return : {rows['avg_ret']:.2f}%")
            else:
                print("  No accuracy data yet.")
        except Exception as e:
            print(f"  Error: {e}")

        # Top 10 patterns
        section("Top 10 Patterns by Success Rate")
        try:
            rows = conn.execute(
                "SELECT pattern_key, success_rate, sample_count, proven_level, is_anti_pattern "
                "FROM patterns ORDER BY success_rate DESC LIMIT 10"
            ).fetchall()
            if not rows:
                print("  No patterns learned yet.")
            else:
                print(f"  Pattern Key                                           Rate      N  Level    Anti")
                print(f"  {'-'*65}")
                for r in rows:
                    anti = "YES" if r["is_anti_pattern"] else "-"
                    print(f"  {r['pattern_key']:<50} {r['success_rate']:>5.2f} "
                          f"{r['sample_count']:>5} {r['proven_level']:<8} {anti:>4}")
        except Exception as e:
            print(f"  Error: {e}")

    print(f"\n{'='*55}\n")


if __name__ == "__main__":
    check_db()
