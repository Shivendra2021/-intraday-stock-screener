# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
init_system.py — Run once to set up MarketMind Pro from scratch.
Usage: python init_system.py
"""

import os
import sys
import sqlite3
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "data/history.db"

DIRS = ["data", "logs", "output", "modules", "dashboard/templates", "dashboard/static",
        "app/research", "tests"]

CREATE_TABLES = [
    """CREATE TABLE IF NOT EXISTS stock_universe (
        symbol       TEXT PRIMARY KEY,
        exchange     TEXT,
        sector       TEXT,
        is_active    INTEGER DEFAULT 1,
        last_verified TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS picks (
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
        created_at     TEXT,
        pattern_key    TEXT,
        validated_price REAL,
        price_validation_status TEXT,
        edge_status    TEXT,
        grok_review    TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS patterns (
        pattern_key        TEXT PRIMARY KEY,
        success_rate       REAL,
        sample_count       INTEGER,
        source             TEXT,
        proven_level       TEXT DEFAULT 'none',
        is_anti_pattern    INTEGER DEFAULT 0,
        last_market_update TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS daily_accuracy (
        date      TEXT PRIMARY KEY,
        tp_count  INTEGER,
        sl_count  INTEGER,
        total     INTEGER,
        accuracy  REAL,
        avg_return REAL
    )""",
    """CREATE TABLE IF NOT EXISTS market_winners (
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
    """CREATE TABLE IF NOT EXISTS market_losers (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        date           TEXT,
        symbol         TEXT,
        intraday_return REAL,
        pattern_key    TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS preclose_watchlist (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        date          TEXT,
        symbol        TEXT,
        open_price    REAL,
        current_price REAL,
        move_pct      REAL,
        vol_ratio     REAL
    )""",
    """CREATE TABLE IF NOT EXISTS price_validations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        symbol TEXT,
        yahoo_price REAL,
        nse_price REAL,
        broker_price REAL,
        consensus_price REAL,
        spread_pct REAL,
        sources_ok INTEGER,
        status TEXT,
        details TEXT,
        created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS pattern_backtests (
        pattern_key TEXT PRIMARY KEY,
        total_trades INTEGER,
        wins INTEGER,
        losses INTEGER,
        hit_rate REAL,
        avg_return REAL,
        max_loss REAL,
        proven_edge INTEGER DEFAULT 0,
        source TEXT,
        last_backtest TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS pattern_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        symbol TEXT,
        pattern_key TEXT,
        entry_price REAL,
        sl_price REAL,
        target_price REAL,
        intraday_high REAL,
        intraday_low REAL,
        close_price REAL,
        outcome TEXT,
        result_return REAL,
        score REAL,
        created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS grok_evidence_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        event_type TEXT,
        candidate_count INTEGER,
        verdict TEXT,
        risk_level TEXT,
        brief_review TEXT,
        next_action TEXT,
        created_at TEXT
    )""",
]


def step(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def create_directories():
    step("1/5 — Creating directory structure")
    for d in DIRS:
        os.makedirs(d, exist_ok=True)
        print(f"  [OK] {d}/")
    # Touch __init__.py files
    for pkg in ["modules", "app", "app/research"]:
        init_file = os.path.join(pkg, "__init__.py")
        if not os.path.exists(init_file):
            open(init_file, "w").close()
            print(f"  [OK] {init_file}")


def create_database():
    step("2/5 — Creating SQLite database and tables")
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        for sql in CREATE_TABLES:
            conn.execute(sql)
        conn.commit()
    print(f"  [OK] Database created at {DB_PATH}")
    print(f"  [OK] {len(CREATE_TABLES)} tables created")


def install_dependencies():
    step("3/5 — Installing Python dependencies")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("  [OK] All dependencies installed successfully")
    else:
        print(f"  [X] pip error: {result.stderr[-500:]}")
        print("  → Try running manually: pip install -r requirements.txt")


def test_telegram():
    step("4/5 — Testing Telegram connection")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or token == "your_bot_token_here":
        print("  ⚠ TELEGRAM_BOT_TOKEN not set in .env — skipping")
        return
    if not chat_id or chat_id == "your_chat_id_here":
        print("  ⚠ TELEGRAM_CHAT_ID not set in .env — skipping")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": "✅ MarketMind Pro — System initialised successfully!"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("  [OK] Telegram test message sent successfully")
        else:
            print(f"  [X] Telegram error: {r.status_code} — {r.text}")
    except Exception as e:
        print(f"  [X] Telegram connection failed: {e}")


def test_scanner():
    step("5/5 — Quick scanner smoke test")
    try:
        import yfinance as yf
        nifty = yf.Ticker("^NSEI")
        info = nifty.fast_info
        price = info.last_price if hasattr(info, "last_price") else "N/A"
        print(f"  [OK] yfinance working — Nifty50 last: {price}")
    except Exception as e:
        print(f"  [X] yfinance test failed: {e}")

    try:
        import nsepython
        print("  [OK] nsepython imported successfully")
    except ImportError:
        print("  ⚠ nsepython not available — will fall back to yfinance universe")


def main():
    print("\n" + "#"*60)
    print("  MarketMind Pro - System Initialisation")
    print("#"*60)

    create_directories()
    create_database()
    install_dependencies()
    test_telegram()
    test_scanner()

    print("\n" + "#"*60)
    print("  Setup complete!")
    print("  Next steps:")
    print("  1. Copy .env.example to .env and fill in your Telegram credentials")
    print("  2. Run: python run_bot.py")
    print("  3. Dashboard: http://localhost:5000")
    print("#"*60 + "\n")


if __name__ == "__main__":
    main()
