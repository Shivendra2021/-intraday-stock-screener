"""
Shared fixtures and test environment configuration for E2E tests.
Provides isolated temporary databases, filesystem sandboxing, and
deterministic mocks for offline execution under 60 seconds.
"""

import datetime
import json
import os
import sqlite3
import sys
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture(scope="session")
def base_universe_symbols():
    """Returns a representative list of 50 Small & Midcap symbols + large caps for exclusion testing."""
    small_mid = [
        "SUZLON", "PERSISTENT", "BSOFT", "DIXON", "ANGELONE", "CDSL", "BSE", "KPITTECH",
        "TATAELXSI", "MAZDOCK", "RVNL", "IRFC", "HUDCO", "SJVN", "FACT", "NATIONALUM",
        "NMDC", "EXIDEIND", "AMBER", "KAYNES", "PRESTIGE", "SOBHA", "GODREJPROP",
        "OBEROIRLTY", "DEEPAKNTR", "JUBLFOOD", "TORNTPHARM", "AUROPHARMA", "LUPIN", "GLENMARK",
        "COFORGE", "LTTS", "CYIENT", "SONACOMS", "TIMKEN", "VOLTAS", "BLUESTARCO", "ASTRAL",
        "SUPREMEIND", "CGPOWER", "KEC", "APARINDS", "COCHINSHIP", "RAILTEL", "UNIONBANK",
        "IDFCFIRSTB", "KARURVYSYA", "FEDERALBNK", "MANAPPURAM", "MUTHOOTFIN"
    ]
    large_caps = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]
    return {"small_mid": small_mid, "large_caps": large_caps}


@pytest.fixture
def mock_ohlcv_dataframe():
    """Generate a realistic 5-day OHLCV DataFrame."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=5, freq="D")
    data = {
        "open": [100.0, 102.0, 101.5, 103.0, 105.0],
        "high": [103.0, 104.5, 103.0, 106.0, 108.5],
        "low": [99.0, 101.0, 100.5, 102.0, 104.0],
        "close": [102.0, 101.5, 103.0, 105.0, 107.5],
        "volume": [100000, 120000, 110000, 180000, 250000],
    }
    df = pd.DataFrame(data, index=dates)
    return df


@pytest.fixture
def test_env(tmp_path):
    """
    Sets up an isolated test sandbox with its own SQLite database,
    temporary data/ and logs/ folders, and patched config paths.
    """
    db_path = str(tmp_path / "test_history.db")
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Initialize tables using modules.db_migrations
    from modules.db_migrations import ensure_research_tables

    with patch("config.DB_PATH", db_path):
        ensure_research_tables()

    # Pre-populate stock_universe with 2489 active symbols
    conn = sqlite3.connect(db_path)
    try:
        today = datetime.date.today().isoformat()
        symbols_to_insert = []
        # Add some known symbols
        known_symbols = [
            "SUZLON", "PERSISTENT", "BSOFT", "DIXON", "ANGELONE", "CDSL", "BSE", "KPITTECH",
            "TATAELXSI", "MAZDOCK", "RVNL", "IRFC", "HUDCO", "SJVN", "FACT", "NATIONALUM",
            "NMDC", "EXIDEIND", "AMBER", "KAYNES", "PRESTIGE", "SOBHA", "GODREJPROP",
            "OBEROIRLTY", "DEEPAKNTR", "JUBLFOOD", "TORNTPHARM", "AUROPHARMA", "LUPIN", "GLENMARK",
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"  # Large caps
        ]
        for s in known_symbols:
            symbols_to_insert.append((s, "NSE", "IT" if "T" in s else "Industrials", 1, today))

        # Pad up to 2489 total symbols
        for i in range(len(known_symbols), 2489):
            sym = f"SYM{i:04d}"
            symbols_to_insert.append((sym, "NSE", "Manufacturing", 1, today))

        conn.executemany(
            "INSERT OR REPLACE INTO stock_universe (symbol, exchange, sector, is_active, last_verified) VALUES (?, ?, ?, ?, ?)",
            symbols_to_insert
        )
        conn.commit()
    finally:
        conn.close()

    news_cache_file = str(data_dir / "news_cache.json")
    system_state_file = str(data_dir / "system_state.json")
    telegram_audit_file = str(data_dir / "telegram_delivery.jsonl")

    env_overrides = {
        "config.DB_PATH": db_path,
        "config.DRY_RUN": False,
        "config.TELEGRAM_BOT_TOKEN": "mock_bot_token_12345",
        "config.TELEGRAM_CHAT_ID": "mock_chat_id_67890",
        "modules.news_provider.NEWS_CACHE_FILE": news_cache_file,
        "modules.market_pulse.SYSTEM_STATE_PATH": system_state_file,
    }

    class TestEnvironment:
        def __init__(self):
            self.tmp_path = tmp_path
            self.db_path = db_path
            self.data_dir = data_dir
            self.logs_dir = logs_dir
            self.news_cache_file = news_cache_file
            self.system_state_file = system_state_file
            self.telegram_audit_file = telegram_audit_file
            self.env_overrides = env_overrides

        def get_db_connection(self):
            return sqlite3.connect(self.db_path)

    env = TestEnvironment()
    return env


@pytest.fixture
def mock_external_network(monkeypatch, mock_ohlcv_dataframe):
    """
    Mocks external HTTP requests (Telegram, TheNewsAPI, RSS feeds) and yfinance
    to ensure 100% offline, deterministic, sub-second execution.
    """
    # 1. Mock fetch_ohlcv in modules.fetch
    def fake_fetch_ohlcv(symbol, period="5d"):
        # Make a deepcopy or slight variation based on symbol
        df = mock_ohlcv_dataframe.copy()
        if "RELIANCE" in symbol or "TCS" in symbol:
            df["close"] = df["close"] * 25.0
            df["volume"] = 5000000
        elif "SUZLON" in symbol:
            df["close"] = [45.0, 46.0, 48.0, 50.5, 54.0]
            df["volume"] = 25000000
        elif "PENNY" in symbol:
            df["close"] = [5.0, 5.1, 4.9, 5.0, 5.2]
            df["volume"] = 10000
        return df

    monkeypatch.setattr("modules.fetch.fetch_ohlcv", fake_fetch_ohlcv)

    # 2. Mock yfinance download
    class FakeYF:
        @staticmethod
        def download(tickers, period="5d", interval="1d", progress=False, **kwargs):
            if isinstance(tickers, str):
                return fake_fetch_ohlcv(tickers, period)
            # Multi-ticker download
            rows = []
            for t in tickers:
                df = fake_fetch_ohlcv(t, period)
                df["ticker"] = t
                rows.append(df)
            combined = pd.concat(rows)
            return combined

    try:
        import yfinance
        monkeypatch.setattr("yfinance.download", FakeYF.download)
    except ImportError:
        pass

    # 3. Mock requests.post and requests.get
    def fake_requests_post(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "api.telegram.org" in url:
            resp.json.return_value = {"ok": True, "result": {"message_id": 1001}}
            resp.text = json.dumps({"ok": True, "result": {"message_id": 1001}})
        elif "openrouter.ai" in url or "api.groq.com" in url:
            resp.json.return_value = {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "ok": True,
                            "verdict": "APPROVED",
                            "risk_level": "LOW",
                            "brief_review": "Strong multi-timeframe alignment across high-beta Small/Midcaps.",
                            "watch_items": ["SUZLON", "KPITTECH"],
                            "next_action": "Execute ORB entries above morning VWAP"
                        })
                    }
                }],
                "model": "x-ai/grok-3-mini",
            }
            resp.text = json.dumps(resp.json.return_value)
        else:
            resp.json.return_value = {"status": "ok"}
            resp.text = '{"status": "ok"}'
        return resp

    def fake_requests_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "thenewsapi.com" in url:
            resp.json.return_value = {
                "data": [
                    {
                        "title": "RBI policy stance eases market liquidity concerns across NSE Midcaps",
                        "description": "Domestic institutional inflows surge as small/midcap momentum accelerates.",
                        "source": "Financial Express",
                        "published_at": "2026-09-09T08:15:00Z"
                    },
                    {
                        "title": "Crude oil stabilizes near $78 as maritime corridor tensions cool",
                        "description": "Upstream and downstream energy shares see sector rotation.",
                        "source": "Economic Times",
                        "published_at": "2026-09-09T08:20:00Z"
                    }
                ]
            }
            resp.text = json.dumps(resp.json.return_value)
        elif "archives.nseindia.com" in url:
            csv_content = "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE\nSUZLON,Suzlon Energy Ltd,EQ,19-OCT-2005,2,1,INE040H01021,2\nKPITTECH,KPIT Tech Ltd,EQ,22-APR-2019,10,1,INE04I401011,10\n"
            resp.text = csv_content
        else:
            resp.json.return_value = {}
            resp.text = "{}"
        return resp

    monkeypatch.setattr("requests.post", fake_requests_post)
    monkeypatch.setattr("requests.get", fake_requests_get)

    return {"fetch_ohlcv": fake_fetch_ohlcv, "post": fake_requests_post, "get": fake_requests_get}


@pytest.fixture
def dashboard_client(test_env, mock_external_network, monkeypatch):
    """
    Creates a test client for Flask dashboard/app.py connected to the test database.
    """
    import dashboard.app as dashboard_app

    monkeypatch.setattr("dashboard.app.DB_PATH", test_env.db_path)
    monkeypatch.setattr("config.DB_PATH", test_env.db_path)
    monkeypatch.setattr("dashboard.app.DATA_DIR", str(test_env.data_dir))
    monkeypatch.setattr("dashboard.app.LOG_DIR", str(test_env.logs_dir))

    dashboard_app._ensure_dashboard_db()

    with dashboard_app.app.test_client() as client:
        yield client
