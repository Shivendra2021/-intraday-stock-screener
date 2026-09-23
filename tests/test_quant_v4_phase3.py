"""
tests/test_quant_v4_phase3.py — Unit Tests for Market Regime & Sector Intelligence
"""
import pytest
import datetime as dt
import pandas as pd
from modules.quant_store import Store
from modules.market_regime import compute_market_regime, compute_sector_metrics


@pytest.fixture
def store(tmp_path, monkeypatch):
    import config
    db_path = str(tmp_path / "test_regime.db")
    monkeypatch.setattr(config, "QUANT_DB_PATH", db_path)
    return Store(db_path)


def make_nifty_bars(start_dt, prices):
    times = pd.date_range(start_dt, periods=len(prices), freq="5min", tz="Asia/Kolkata")
    rows = []
    for p in prices:
        rows.append({"open": p, "high": p * 1.001, "low": p * 0.999, "close": p, "volume": 50000})
    return pd.DataFrame(rows, index=times)


def test_market_regime_point_in_time_safety(store):
    start = "2026-09-01 09:15"
    prices = [25000 + i * 15 for i in range(15)]
    bars = make_nifty_bars(start, prices)

    asof = pd.Timestamp("2026-09-01 09:45", tz="Asia/Kolkata")
    first_regime = compute_market_regime(store, asof, bars)
    assert first_regime["regime_label"] == "TREND_UP"

    # Add massive crash in the future (after asof)
    future_bars = make_nifty_bars("2026-09-01 10:30", [24000 - i * 50 for i in range(10)])
    combined_bars = pd.concat([bars, future_bars])

    # Re-evaluating at the SAME past asof MUST yield identical results
    second_regime = compute_market_regime(store, asof, combined_bars)
    assert second_regime["regime_label"] == first_regime["regime_label"]
    assert second_regime["nifty_return_15m"] == first_regime["nifty_return_15m"]


def test_market_regime_trend_down(store):
    start = "2026-09-02 09:15"
    prices = [25000 - i * 20 for i in range(15)]
    bars = make_nifty_bars(start, prices)

    asof = pd.Timestamp("2026-09-02 09:45", tz="Asia/Kolkata")
    regime = compute_market_regime(store, asof, bars)
    assert regime["regime_label"] == "TREND_DOWN"
    assert regime["nifty_return_15m"] < 0


def test_sector_ranking_and_relative_strength(store):
    asof = pd.Timestamp("2026-09-03 09:45", tz="Asia/Kolkata")
    stock_returns = {
        "TCS": 2.5, "INFY": 3.0, "WIPRO": 2.0,  # IT sector avg ~2.5%
        "HDFCBANK": -0.5, "SBIN": -0.2, "ICICIBANK": 0.0, # Banking sector avg ~-0.2%
        "SUNPHARMA": 1.2, "CIPLA": 1.5 # Pharma avg ~1.35%
    }
    sector_map = {
        "TCS": "IT", "INFY": "IT", "WIPRO": "IT",
        "HDFCBANK": "Banking", "SBIN": "Banking", "ICICIBANK": "Banking",
        "SUNPHARMA": "Pharma", "CIPLA": "Pharma"
    }

    ranked = compute_sector_metrics(store, asof, stock_returns, sector_map)
    assert len(ranked) == 3
    assert ranked["IT"]["sector_rank"] == 1
    assert ranked["IT"]["return_15m"] == 2.5
    assert ranked["Banking"]["sector_rank"] == 3
