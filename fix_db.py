# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
fix_db.py — Check all 7 tables, recreate missing ones, report health.
Usage: python fix_db.py
"""

import sqlite3
import os

DB_PATH = "data/history.db"

EXPECTED_TABLES = {
    "stock_universe": """CREATE TABLE IF NOT EXISTS stock_universe (
        symbol       TEXT PRIMARY KEY,
        exchange     TEXT,
        sector       TEXT,
        is_active    INTEGER DEFAULT 1,
        last_verified TEXT
    )""",
    "picks": """CREATE TABLE IF NOT EXISTS picks (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        date           TEXT,
        rank           INTEGER,
        symbol         TEXT,
        entry_price    REAL,
        sl_price       REAL,
        target_price   REAL,
        confidence     REAL,
        signal_reasons TEXT,
        status         TEXT DEFAULT 'pending',
        result_return  REAL,
        created_at     TEXT
    )""",
    "patterns": """CREATE TABLE IF NOT EXISTS patterns (
        pattern_key        TEXT PRIMARY KEY,
        success_rate       REAL,
        sample_count       INTEGER,
        source             TEXT,
        proven_level       TEXT DEFAULT 'none',
        is_anti_pattern    INTEGER DEFAULT 0,
        last_market_update TEXT
    )""",
    "daily_accuracy": """CREATE TABLE IF NOT EXISTS daily_accuracy (
        date       TEXT PRIMARY KEY,
        tp_count   INTEGER,
        sl_count   INTEGER,
        total      INTEGER,
        accuracy   REAL,
        avg_return REAL
    )""",
    "market_winners": """CREATE TABLE IF NOT EXISTS market_winners (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        date           TEXT,
        symbol         TEXT,
        sector         TEXT,
        intraday_return REAL,
        rsi_yesterday  REAL,
        macd_yesterday REAL,
        ema_alignment  TEXT,
        volume_ratio   REAL,
        bb_position    REAL,
        adx            REAL,
        gap_up         REAL,
        pattern_key    TEXT
    )""",
    "market_losers": """CREATE TABLE IF NOT EXISTS market_losers (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        date           TEXT,
        symbol         TEXT,
        intraday_return REAL,
        pattern_key    TEXT
    )""",
    "preclose_watchlist": """CREATE TABLE IF NOT EXISTS preclose_watchlist (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        date          TEXT,
        symbol        TEXT,
        open_price    REAL,
        current_price REAL,
        move_pct      REAL,
        vol_ratio     REAL
    )""",
}


def get_existing_tables(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cur.fetchall()}


def check_and_repair():
    if not os.path.exists(DB_PATH):
        print(f"  ✗ Database not found at {DB_PATH} — run init_system.py first")
        return

    print(f"\n{'='*55}")
    print("  MarketMind Pro — Database Health Report")
    print(f"{'='*55}")

    with sqlite3.connect(DB_PATH) as conn:
        existing = get_existing_tables(conn)
        issues = 0

        for table, ddl in EXPECTED_TABLES.items():
            if table in existing:
                # Check for corrupted rows
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    print(f"  ✓ {table:<25} {count:>6} rows")
                except Exception as e:
                    print(f"  ✗ {table:<25} ERROR: {e}")
                    issues += 1
            else:
                print(f"  ✗ {table:<25} MISSING — recreating...")
                try:
                    conn.execute(ddl)
                    conn.commit()
                    print(f"  ✓ {table:<25} recreated successfully")
                except Exception as e:
                    print(f"  ✗ {table:<25} Failed to recreate: {e}")
                    issues += 1

        # Check picks status values
        try:
            bad = conn.execute(
                "SELECT COUNT(*) FROM picks WHERE status NOT IN "
                "('pending','tp_hit','sl_hit','open_eod','target_hit','stopped_out',"
                "'ambiguous_sl_first','closed_eod')"
            ).fetchone()[0]
            if bad > 0:
                print(f"\n  ⚠  {bad} picks with invalid status values found")
                issues += 1
        except Exception:
            pass

        print(f"\n  {'✅ Database healthy' if issues == 0 else f'⚠  {issues} issue(s) found/fixed'}")
        print(f"{'='*55}\n")


if __name__ == "__main__":
    check_and_repair()
