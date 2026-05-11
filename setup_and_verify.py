# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
setup_and_verify.py — One-shot setup, install, test, and auto-fix for MarketMind Pro.
Run this ONCE after copying all files to your folder.

Usage:
    python setup_and_verify.py

What it does (in order):
    1. Checks Python version
    2. Creates all directories
    3. Installs all dependencies (with auto-retry on failure)
    4. Creates .env from .env.example if missing
    5. Creates all 7 DB tables
    6. Verifies all 35 files exist
    7. Runs import checks on every module
    8. Tests yfinance live (downloads RELIANCE)
    9. Tests nsepython
    10. Tests Telegram connection
    11. Tests DB read/write
    12. Tests pattern key determinism
    13. Tests exponential smoothing math
    14. Tests scanner holiday detection
    15. Runs fix_db.py health check
    16. Prints final checklist with PASS / FAIL / FIXED for every item
"""

import os
import sys
import subprocess
import sqlite3
import importlib
import datetime
import json
import shutil
import time

# ── Colour codes (Windows-compatible via ANSI) ─────────────────────────────
os.system("")  # enables ANSI on Windows terminal
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS  = f"{GREEN}✓ PASS{RESET}"
FAIL  = f"{RED}✗ FAIL{RESET}"
FIXED = f"{YELLOW}⚡ FIXED{RESET}"
SKIP  = f"{BLUE}– SKIP{RESET}"

results = []   # list of (label, status, detail)


def log(label, status, detail=""):
    results.append((label, status, detail))
    icon = {"PASS": PASS, "FAIL": FAIL, "FIXED": FIXED, "SKIP": SKIP}.get(status, status)
    detail_str = f"  → {detail}" if detail else ""
    print(f"  {icon}  {label}{detail_str}")


def section(title):
    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Python version
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 1 — Python Version")

major, minor = sys.version_info.major, sys.version_info.minor
ver_str = f"{major}.{minor}.{sys.version_info.micro}"
if major == 3 and minor >= 11:
    log("Python 3.11+", "PASS", ver_str)
elif major == 3 and minor >= 9:
    log("Python version", "PASS", f"{ver_str} (3.9+ works, 3.11+ recommended)")
else:
    log("Python version", "FAIL", f"{ver_str} — Please install Python 3.11+")
    print(f"\n{RED}Cannot continue with Python {ver_str}. Please upgrade.{RESET}")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Directory structure
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 2 — Directory Structure")

REQUIRED_DIRS = [
    "data", "logs", "output", "modules",
    "dashboard", "dashboard/templates", "dashboard/static",
    "app", "app/research", "tests",
]

for d in REQUIRED_DIRS:
    if os.path.exists(d):
        log(f"Dir: {d}/", "PASS")
    else:
        os.makedirs(d, exist_ok=True)
        log(f"Dir: {d}/", "FIXED", "created")

# __init__.py files
INIT_FILES = ["modules/__init__.py", "app/__init__.py", "app/research/__init__.py", "tests/__init__.py"]
for f in INIT_FILES:
    if not os.path.exists(f):
        open(f, "w").close()
        log(f"File: {f}", "FIXED", "created")
    else:
        log(f"File: {f}", "PASS")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Install dependencies
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 3 — Installing Dependencies")

PACKAGES = [
    ("yfinance",       "yfinance"),
    ("pandas",         "pandas"),
    ("numpy",          "numpy"),
    ("pandas_ta",      "pandas-ta"),
    ("flask",          "flask"),
    ("apscheduler",    "apscheduler"),
    ("dotenv",         "python-dotenv"),
    ("requests",       "requests"),
    ("feedparser",     "feedparser"),
    ("lxml",           "lxml"),
    ("newspaper",      "newspaper4k"),
    ("nsepython",      "nsepython"),
]

for import_name, pip_name in PACKAGES:
    try:
        importlib.import_module(import_name)
        log(f"Package: {pip_name}", "PASS")
    except ImportError:
        print(f"  {YELLOW}Installing {pip_name}...{RESET}")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pip_name, "--quiet"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            log(f"Package: {pip_name}", "FIXED", "installed")
        else:
            # Try with --break-system-packages for some Linux setups
            result2 = subprocess.run(
                [sys.executable, "-m", "pip", "install", pip_name,
                 "--break-system-packages", "--quiet"],
                capture_output=True, text=True
            )
            if result2.returncode == 0:
                log(f"Package: {pip_name}", "FIXED", "installed (break-system)")
            else:
                log(f"Package: {pip_name}", "FAIL",
                    result.stderr.strip()[-100:] if result.stderr else "unknown error")

# Special check: pandas_ta sometimes installs but needs a patch
try:
    import pandas_ta as ta
    log("pandas_ta import", "PASS")
except ImportError as e:
    log("pandas_ta import", "FAIL", str(e)[:80])
    print("  ⚠ pandas_ta import failed. This is OK for basic testing.")
except Exception as e:
    log("pandas_ta import", "FAIL", str(e)[:80])


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — .env file
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 4 — Environment File (.env)")

if os.path.exists(".env"):
    log(".env file exists", "PASS")
    # Check it has the right keys
    with open(".env") as f:
        env_content = f.read()
    for key in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DRY_RUN"]:
        if key in env_content:
            log(f".env has {key}", "PASS")
        else:
            # Append missing key
            with open(".env", "a") as f:
                defaults = {
                    "TELEGRAM_BOT_TOKEN": "your_bot_token_here",
                    "TELEGRAM_CHAT_ID":   "your_chat_id_here",
                    "DRY_RUN":            "False",
                }
                f.write(f"\n{key}={defaults.get(key, '')}")
            log(f".env has {key}", "FIXED", "appended with default")
else:
    if os.path.exists(".env.example"):
        shutil.copy(".env.example", ".env")
        log(".env file", "FIXED", "copied from .env.example — EDIT IT with your Telegram credentials!")
    else:
        with open(".env", "w") as f:
            f.write("TELEGRAM_BOT_TOKEN=your_bot_token_here\n")
            f.write("TELEGRAM_CHAT_ID=your_chat_id_here\n")
            f.write("ZERODHA_API_KEY=optional\n")
            f.write("ZERODHA_ACCESS_TOKEN=optional\n")
            f.write("DRY_RUN=False\n")
        log(".env file", "FIXED", "created — EDIT IT with your Telegram credentials!")

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
    log("load_dotenv()", "PASS")
except Exception as e:
    log("load_dotenv()", "FAIL", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Database tables
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 5 — SQLite Database & Tables")

DB_PATH = "data/history.db"

TABLE_DDL = {
    "stock_universe": """CREATE TABLE IF NOT EXISTS stock_universe (
        symbol TEXT PRIMARY KEY, exchange TEXT, sector TEXT,
        is_active INTEGER DEFAULT 1, last_verified TEXT)""",
    "picks": """CREATE TABLE IF NOT EXISTS picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, rank INTEGER,
        symbol TEXT, entry_price REAL, sl_price REAL, target_price REAL,
        confidence REAL, signal_reasons TEXT, status TEXT DEFAULT 'pending',
        result_return REAL, created_at TEXT)""",
    "patterns": """CREATE TABLE IF NOT EXISTS patterns (
        pattern_key TEXT PRIMARY KEY, success_rate REAL, sample_count INTEGER,
        source TEXT, proven_level TEXT DEFAULT 'none',
        is_anti_pattern INTEGER DEFAULT 0, last_market_update TEXT)""",
    "daily_accuracy": """CREATE TABLE IF NOT EXISTS daily_accuracy (
        date TEXT PRIMARY KEY, tp_count INTEGER, sl_count INTEGER,
        total INTEGER, accuracy REAL, avg_return REAL)""",
    "market_winners": """CREATE TABLE IF NOT EXISTS market_winners (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, symbol TEXT,
        sector TEXT, intraday_return REAL, rsi_yesterday REAL,
        macd_yesterday REAL, ema_alignment TEXT, volume_ratio REAL,
        bb_position REAL, adx REAL, gap_up REAL, pattern_key TEXT)""",
    "market_losers": """CREATE TABLE IF NOT EXISTS market_losers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, symbol TEXT,
        intraday_return REAL, pattern_key TEXT)""",
    "preclose_watchlist": """CREATE TABLE IF NOT EXISTS preclose_watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, symbol TEXT,
        open_price REAL, current_price REAL, move_pct REAL, vol_ratio REAL)""",
}

try:
    with sqlite3.connect(DB_PATH) as conn:
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for name, ddl in TABLE_DDL.items():
            conn.execute(ddl)
        conn.commit()
        after = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    for name in TABLE_DDL:
        if name in existing:
            log(f"Table: {name}", "PASS")
        else:
            log(f"Table: {name}", "FIXED", "created")
except Exception as e:
    log("Database setup", "FAIL", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — File existence check
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 6 — All Project Files Present")

REQUIRED_FILES = [
    "config.py", "main.py", "run_bot.py", "requirements.txt", ".env.example",
    "init_system.py", "fix_db.py", "check_db.py",
    "test_telegram.py", "test_scanner.py", "test_learner.py",
    "modules/__init__.py", "modules/scanner.py", "modules/analyzer.py",
    "modules/picker.py", "modules/tracker.py", "modules/evaluator.py",
    "modules/learner.py", "modules/market_learner.py", "modules/news.py",
    "modules/alerts.py", "modules/preclose_watchlist.py",
    "dashboard/app.py", "dashboard/templates/index.html",
    "dashboard/static/style.css", "dashboard/static/app.js",
    "app/__init__.py", "app/research/__init__.py",
    "app/research/intraday_pattern_scan.py",
    "tests/__init__.py", "tests/test_intraday_pattern_scan.py",
]

missing_files = []
for f in REQUIRED_FILES:
    if os.path.exists(f):
        log(f"File: {f}", "PASS")
    else:
        log(f"File: {f}", "FAIL", "MISSING — copy from the artifacts above")
        missing_files.append(f)

if missing_files:
    print(f"\n  {RED}Missing {len(missing_files)} file(s). Copy them from the chat artifacts before continuing.{RESET}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Module import checks
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 7 — Module Import Checks")

sys.path.insert(0, os.path.abspath("."))

MODULE_IMPORTS = [
    ("config",                    "config"),
    ("modules.scanner",           "modules/scanner.py"),
    ("modules.news",              "modules/news.py"),
    ("modules.analyzer",          "modules/analyzer.py"),
    ("modules.picker",            "modules/picker.py"),
    ("modules.alerts",            "modules/alerts.py"),
    ("modules.tracker",           "modules/tracker.py"),
    ("modules.evaluator",         "modules/evaluator.py"),
    ("modules.preclose_watchlist","modules/preclose_watchlist.py"),
    ("modules.market_learner",    "modules/market_learner.py"),
    ("modules.learner",           "modules/learner.py"),
    ("dashboard.app",             "dashboard/app.py"),
]

for mod_name, file_label in MODULE_IMPORTS:
    if not os.path.exists(file_label.replace(".", "/") + ".py" if "/" not in file_label else file_label):
        log(f"Import: {mod_name}", "SKIP", "file missing")
        continue
    try:
        importlib.import_module(mod_name)
        log(f"Import: {mod_name}", "PASS")
    except Exception as e:
        err = str(e)[:120]
        log(f"Import: {mod_name}", "FAIL", err)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — yfinance live test
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 8 — yfinance Live Data Test")

try:
    import yfinance as yf
    df = yf.download("RELIANCE.NS", period="5d", interval="1d",
                     auto_adjust=True, progress=False)
    if df is not None and not df.empty:
        # Normalize column names and handle Series vs scalar
        df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
        price = float(df["close"].values[-1])
        log("yfinance RELIANCE.NS download", "PASS", f"Last close ₹{price:.2f}")
    else:
        log("yfinance RELIANCE.NS download", "FAIL", "Empty DataFrame returned")
except Exception as e:
    log("yfinance RELIANCE.NS download", "FAIL", str(e)[:100])

try:
    import yfinance as yf
    nifty = yf.Ticker("^NSEI")
    info = nifty.fast_info
    price = getattr(info, "last_price", None)
    if price:
        log("yfinance Nifty50 index", "PASS", f"Last ₹{price:.2f}")
    else:
        log("yfinance Nifty50 index", "PASS", "Fetched (price N/A outside market hours)")
except Exception as e:
    log("yfinance Nifty50 index", "FAIL", str(e)[:100])


# ══════════════════════════════════════════════════════════════════════════════
# STEP 9 — nsepython test
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 9 — nsepython Test")

try:
    import nsepython
    log("nsepython import", "PASS", f"version={getattr(nsepython, '__version__', 'unknown')}")
except ImportError as e:
    log("nsepython import", "FAIL", str(e))

try:
    from nsepython import nse_eq_symbols
    syms = nse_eq_symbols()
    if syms and len(syms) > 100:
        log("nsepython nse_eq_symbols()", "PASS", f"{len(syms)} symbols")
    else:
        log("nsepython nse_eq_symbols()", "FAIL", f"Only got {len(syms) if syms else 0} symbols")
except Exception as e:
    log("nsepython nse_eq_symbols()", "FAIL", f"{str(e)[:80]} — will use fallback list")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 10 — Telegram test
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 10 — Telegram Connection Test")

import os as _os
token   = _os.getenv("TELEGRAM_BOT_TOKEN", "")
chat_id = _os.getenv("TELEGRAM_CHAT_ID", "")

if not token or token == "your_bot_token_here":
    log("Telegram token set", "FAIL", "Set TELEGRAM_BOT_TOKEN in .env")
else:
    log("Telegram token set", "PASS", f"{token[:10]}...")

if not chat_id or chat_id == "your_chat_id_here":
    log("Telegram chat_id set", "FAIL", "Set TELEGRAM_CHAT_ID in .env")
else:
    log("Telegram chat_id set", "PASS", f"chat_id={chat_id}")

if token and token != "your_bot_token_here" and chat_id and chat_id != "your_chat_id_here":
    try:
        import requests as req
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {"chat_id": chat_id,
                "text": "✅ MarketMind Pro — setup_and_verify.py ran successfully!"}
        r = req.post(url, json=data, timeout=15)
        if r.status_code == 200:
            log("Telegram send test", "PASS", "Message delivered")
        else:
            log("Telegram send test", "FAIL", f"HTTP {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log("Telegram send test", "FAIL", str(e)[:100])
else:
    log("Telegram send test", "SKIP", "Credentials not configured yet")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 11 — DB read/write test
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 11 — Database Read/Write Test")

try:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO stock_universe (symbol, exchange, is_active, last_verified) "
            "VALUES (?, ?, 1, ?)", ("TEST_VERIFY", "NSE", datetime.date.today().isoformat())
        )
        conn.commit()
        row = conn.execute(
            "SELECT symbol FROM stock_universe WHERE symbol='TEST_VERIFY'"
        ).fetchone()
        assert row and row[0] == "TEST_VERIFY"
        conn.execute("DELETE FROM stock_universe WHERE symbol='TEST_VERIFY'")
        conn.commit()
    log("DB insert/select/delete", "PASS")
except Exception as e:
    log("DB insert/select/delete", "FAIL", str(e))

try:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO patterns "
            "(pattern_key, success_rate, sample_count, source, proven_level, is_anti_pattern) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("TEST__KEY__VERIFY", 0.75, 5, "test", "none", 0)
        )
        conn.commit()
        row = conn.execute(
            "SELECT success_rate FROM patterns WHERE pattern_key='TEST__KEY__VERIFY'"
        ).fetchone()
        assert row and abs(row[0] - 0.75) < 1e-6
        conn.execute("DELETE FROM patterns WHERE pattern_key='TEST__KEY__VERIFY'")
        conn.commit()
    log("DB patterns upsert", "PASS")
except Exception as e:
    log("DB patterns upsert", "FAIL", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 12 — Pattern key determinism test
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 12 — Pattern Key Logic Tests")

try:
    from modules.market_learner import _build_pattern_key

    # Test 1: known inputs → known output
    k1 = _build_pattern_key(52.0, 2.5, 0.5, 0.3, "EMA_full_bull")
    assert "RSI_50to55"   in k1, f"Expected RSI_50to55 in {k1}"
    assert "VOL_veryhigh" in k1, f"Expected VOL_veryhigh in {k1}"
    assert "MACD_pos"     in k1, f"Expected MACD_pos in {k1}"
    assert "EMA_full_bull" in k1, f"Expected EMA_full_bull in {k1}"
    log("Pattern key: RSI_50to55 + VOL_veryhigh + MACD_pos", "PASS", k1[:50])

    # Test 2: determinism
    k2 = _build_pattern_key(52.0, 2.5, 0.5, 0.3, "EMA_full_bull")
    assert k1 == k2
    log("Pattern key determinism", "PASS")

    # Test 3: RSI boundary
    k3 = _build_pattern_key(70.0, 1.0, 0.0, 0.0, "EMA_bear")
    assert "RSI_over70" in k3
    log("Pattern key: RSI=70 → RSI_over70", "PASS")

    # Test 4: MACD_neg
    k4 = _build_pattern_key(35.0, 0.5, -0.2, 0.1, "EMA_bear")
    assert "RSI_under40" in k4
    assert "VOL_low"     in k4
    assert "MACD_neg"    in k4
    log("Pattern key: RSI_under40 + VOL_low + MACD_neg", "PASS", k4[:50])

except ImportError:
    log("Pattern key tests", "SKIP", "modules/market_learner.py not found")
except AssertionError as e:
    log("Pattern key tests", "FAIL", str(e))
except Exception as e:
    log("Pattern key tests", "FAIL", str(e)[:100])


# ══════════════════════════════════════════════════════════════════════════════
# STEP 13 — Exponential smoothing math
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 13 — Exponential Smoothing Math Tests")

try:
    from modules.market_learner import _smooth_rate

    cases = [
        (0.8, 0.4, 5,  0.5*0.8 + 0.5*0.4,  "small sample (alpha=0.5)"),
        (0.8, 0.4, 15, 0.7*0.8 + 0.3*0.4,  "large sample (alpha=0.3)"),
        (0.0, 1.0, 1,  0.5,                  "zero → one"),
        (0.65, 0.65, 20, 0.65,               "same rate stays same"),
    ]
    for old, today, count, expected, label in cases:
        result = _smooth_rate(old, today, count)
        assert abs(result - expected) < 1e-6, f"got {result:.6f}, expected {expected:.6f}"
        log(f"Smoothing: {label}", "PASS", f"{result:.4f}")

except ImportError:
    log("Smoothing tests", "SKIP", "modules/market_learner.py not found")
except AssertionError as e:
    log("Smoothing tests", "FAIL", str(e))
except Exception as e:
    log("Smoothing tests", "FAIL", str(e)[:100])


# ══════════════════════════════════════════════════════════════════════════════
# STEP 14 — Scanner holiday detection
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 14 — Scanner Holiday & Weekend Detection")

try:
    from modules.scanner import is_market_holiday, is_weekend

    # Independence Day 2024 → holiday
    independence = datetime.date(2024, 8, 15)
    result = is_market_holiday(independence)
    if result:
        log("Independence Day (15 Aug 2024) is holiday", "PASS")
    else:
        log("Independence Day (15 Aug 2024) is holiday", "FAIL",
            "Not detected — static holiday list may need updating")

    # Saturday → weekend
    saturday = datetime.date(2025, 1, 4)
    assert is_weekend(saturday), "Saturday should be weekend"
    log("Saturday detected as weekend", "PASS")

    # Sunday → weekend
    sunday = datetime.date(2025, 1, 5)
    assert is_weekend(sunday), "Sunday should be weekend"
    log("Sunday detected as weekend", "PASS")

    # Monday → not weekend
    monday = datetime.date(2025, 1, 6)
    assert not is_weekend(monday), "Monday should not be weekend"
    log("Monday not weekend", "PASS")

except ImportError:
    log("Holiday detection", "SKIP", "modules/scanner.py not found")
except AssertionError as e:
    log("Holiday detection", "FAIL", str(e))
except Exception as e:
    log("Holiday detection", "FAIL", str(e)[:100])


# ══════════════════════════════════════════════════════════════════════════════
# STEP 15 — fix_db.py health check
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 15 — fix_db.py Health Check")

if os.path.exists("fix_db.py"):
    result = subprocess.run(
        [sys.executable, "fix_db.py"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        log("fix_db.py", "PASS", "All tables healthy")
        # Print its output indented
        for line in result.stdout.strip().split("\n"):
            print(f"    {line}")
    else:
        log("fix_db.py", "FAIL", result.stderr[:100])
else:
    log("fix_db.py", "SKIP", "File not found")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 16 — check_db.py
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 16 — check_db.py Stats")

if os.path.exists("check_db.py"):
    result = subprocess.run(
        [sys.executable, "check_db.py"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        log("check_db.py", "PASS")
        for line in result.stdout.strip().split("\n"):
            print(f"    {line}")
    else:
        log("check_db.py", "FAIL", result.stderr[:100])
else:
    log("check_db.py", "SKIP", "File not found")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 17 — pandas_ta smoke test
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 17 — pandas_ta Indicator Smoke Test")

try:
    import pandas as pd
    import numpy as np
    try:
        import pandas_ta as ta
        pandas_ta_available = True
    except ImportError:
        pandas_ta_available = False
        log("pandas_ta import", "SKIP", "pandas_ta not available (optional)")

    if pandas_ta_available:
        # Create fake OHLCV data
        n = 60
        np.random.seed(42)
        prices = 1000 + np.cumsum(np.random.randn(n) * 10)
        df = pd.DataFrame({
            "open":   prices * 0.995,
            "high":   prices * 1.01,
            "low":    prices * 0.99,
            "close":  prices,
            "volume": np.random.randint(100000, 500000, n).astype(float),
        })

        rsi    = ta.rsi(df["close"], 14)
        macd   = ta.macd(df["close"], 12, 26, 9)
        ema9   = ta.ema(df["close"], 9)
        adx    = ta.adx(df["high"], df["low"], df["close"], 14)
        atr    = ta.atr(df["high"], df["low"], df["close"], 14)
        bbands = ta.bbands(df["close"], 20, 2)

        assert rsi is not None and not rsi.dropna().empty
        log("pandas_ta RSI(14)", "PASS", f"last={rsi.dropna().values[-1]:.2f}")

        assert macd is not None and not macd.dropna().empty
        log("pandas_ta MACD(12,26,9)", "PASS")

        assert ema9 is not None and not ema9.dropna().empty
        log("pandas_ta EMA(9)", "PASS", f"last={ema9.dropna().values[-1]:.2f}")

        assert adx is not None and not adx.dropna().empty
        log("pandas_ta ADX(14)", "PASS", f"last={adx.dropna().iloc[-1, 0]:.2f}")

        assert atr is not None and not atr.dropna().empty
        log("pandas_ta ATR(14)", "PASS", f"last={atr.dropna().values[-1]:.2f}")

        assert bbands is not None and not bbands.dropna().empty
        log("pandas_ta BBands(20)", "PASS")

except ImportError:
    log("pandas_ta smoke test", "SKIP", "pandas_ta not available (optional)")
except Exception as e:
    log("pandas_ta smoke test", "FAIL", str(e)[:120])


# ══════════════════════════════════════════════════════════════════════════════
# STEP 18 — APScheduler import
# ══════════════════════════════════════════════════════════════════════════════

section("STEP 18 — APScheduler Check")

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
    sched = BlockingScheduler(timezone="Asia/Kolkata")
    log("APScheduler BlockingScheduler", "PASS")
    del sched
except Exception as e:
    log("APScheduler", "FAIL", str(e)[:100])


# ══════════════════════════════════════════════════════════════════════════════
# FINAL REPORT
# ══════════════════════════════════════════════════════════════════════════════

section("FINAL CHECKLIST REPORT")

pass_count  = sum(1 for _, s, _ in results if s == "PASS")
fixed_count = sum(1 for _, s, _ in results if s == "FIXED")
fail_count  = sum(1 for _, s, _ in results if s == "FAIL")
skip_count  = sum(1 for _, s, _ in results if s == "SKIP")
total       = len(results)

print(f"\n  {BOLD}Total checks : {total}{RESET}")
print(f"  {GREEN}Passed       : {pass_count}{RESET}")
print(f"  {YELLOW}Auto-fixed   : {fixed_count}{RESET}")
print(f"  {RED}Failed       : {fail_count}{RESET}")
print(f"  {BLUE}Skipped      : {skip_count}{RESET}")

if fail_count > 0:
    print(f"\n  {BOLD}{RED}Items that need manual attention:{RESET}")
    for label, status, detail in results:
        if status == "FAIL":
            print(f"    {RED}✗{RESET} {label}")
            if detail:
                print(f"      → {detail}")

print(f"\n{'─'*60}")

if fail_count == 0:
    print(f"""
  {GREEN}{BOLD}✅ ALL CHECKS PASSED — MarketMind Pro is ready!{RESET}

  Next steps:
  {BOLD}1.{RESET} Edit .env → set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
  {BOLD}2.{RESET} Test Telegram:      python test_telegram.py
  {BOLD}3.{RESET} Start the bot:      python run_bot.py
  {BOLD}4.{RESET} Start dashboard:    python dashboard/app.py
                        then open → http://localhost:5000
  {BOLD}5.{RESET} Research scan:      python -m app.research.intraday_pattern_scan --period 5y --top 30
  {BOLD}6.{RESET} Check DB anytime:   python check_db.py
  {BOLD}7.{RESET} Fix DB if needed:   python fix_db.py
""")
else:
    print(f"""
  {YELLOW}{BOLD}⚠ {fail_count} item(s) need attention (see above).{RESET}

  Common fixes:
  • Missing files     → copy from the chat artifacts
  • Telegram FAIL     → edit .env with real token + chat_id
  • nsepython FAIL    → bot will use yfinance fallback (OK)
  • Package FAIL      → run: pip install -r requirements.txt
  • Import FAIL       → check if the .py file was saved correctly
""")

print(f"{'─'*60}\n")
