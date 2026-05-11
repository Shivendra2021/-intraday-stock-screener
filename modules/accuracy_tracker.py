"""
Accuracy Tracker - Track bot performance over time.

Tracks:
- Total picks given
- Hit rate (TP reached)
- SL hit rate
- Average hold time
- Best performing sectors
- Win/Loss ratio
"""

import logging
import datetime
import json
import os
import sqlite3

logger = logging.getLogger(__name__)

ACCURACY_DB = "data/accuracy.db"


def init_accuracy_db():
    """Initialize accuracy database."""
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(ACCURACY_DB)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS picks_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            symbol TEXT,
            entry_price REAL,
            sl_price REAL,
            tp_price REAL,
            exit_price REAL,
            status TEXT,
            pnl_pct REAL,
            hold_time_minutes INTEGER,
            sector TEXT,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            total_picks INTEGER,
            tp_hit INTEGER,
            sl_hit INTEGER,
            hold INTEGER,
            total_pnl REAL,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def record_pick(pick: dict, sector: str = "Unknown") -> None:
    """
    Record a new pick.
    """
    conn = sqlite3.connect(ACCURACY_DB)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO picks_history 
        (date, symbol, entry_price, sl_price, tp_price, exit_price, status, pnl_pct, hold_time_minutes, sector, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.date.today().strftime("%Y-%m-%d"),
        pick.get("symbol", ""),
        pick.get("entry_price", 0),
        pick.get("sl_price", 0),
        pick.get("target_price", 0),
        0,
        "active",
        0,
        0,
        sector,
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()


def update_pick_status(symbol: str, status: str, exit_price: float = 0, pnl: float = 0) -> None:
    """
    Update pick status when closed.
    """
    conn = sqlite3.connect(ACCURACY_DB)
    cursor = conn.cursor()

    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        UPDATE picks_history 
        SET status = ?, exit_price = ?, pnl_pct = ?, hold_time_minutes = ?
        WHERE symbol = ? AND status = 'active' AND date = ?
    """, (status, exit_price, pnl, 0, symbol, datetime.date.today().strftime("%Y-%m-%d")))

    conn.commit()
    conn.close()


def get_accuracy_stats(days: int = 30) -> dict:
    """
    Get accuracy statistics for last N days.
    """
    if not os.path.exists(ACCURACY_DB):
        init_accuracy_db()
        return {}

    conn = sqlite3.connect(ACCURACY_DB)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'target_hit' THEN 1 ELSE 0 END) as tp_hits,
            SUM(CASE WHEN status = 'stopped_out' THEN 1 ELSE 0 END) as sl_hits,
            SUM(CASE WHEN status = 'hold' THEN 1 ELSE 0 END) as holds,
            AVG(pnl_pct) as avg_pnl
        FROM picks_history 
        WHERE date >= date('now', '-' || ? || ' days')
    """, (days,))

    row = cursor.fetchone()

    total = row[0] or 0
    tp_hits = row[1] or 0
    sl_hits = row[2] or 0
    holds = row[3] or 0
    avg_pnl = row[4] or 0

    accuracy = (tp_hits / total * 100) if total > 0 else 0

    cursor.execute("""
        SELECT sector, COUNT(*), AVG(pnl_pct)
        FROM picks_history 
        WHERE date >= date('now', '-' || ? || ' days')
        GROUP BY sector
    """, (days,))

    sector_stats = {}
    for row in cursor.fetchall():
        sector_stats[row[0]] = {  # type: ignore
            "count": row[1],
            "avg_pnl": round(row[2], 2) if row[2] else 0
        }

    conn.close()

    return {
        "period_days": days,
        "total_picks": total,
        "tp_hits": tp_hits,
        "sl_hits": sl_hits,
        "holds": holds,
        "accuracy_pct": round(accuracy, 1),
        "avg_pnl": round(avg_pnl, 1),
        "sector_performance": sector_stats
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_accuracy_db()

    stats = get_accuracy_stats(30)
    print(f"Total Picks: {stats.get('total_picks', 0)}")
    print(f"Accuracy: {stats.get('accuracy_pct', 0)}%")
    print(f"Average P&L: {stats.get('avg_pnl', 0)}%")