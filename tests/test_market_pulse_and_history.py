"""
tests/test_market_pulse_and_history.py — Tests for market pulse, top movers, sectors,
geopolitical news, and daily picks JSON persistence.
"""

import os
import json
import pytest

from modules.market_pulse import (
    get_system_power_state,
    toggle_system_power,
    get_market_indices,
    get_top_movers_and_reasons,
    get_trending_sectors,
    get_geopolitical_market_news,
    get_full_market_pulse,
)
from modules.picker import save_picks_to_history_json, load_picks_history_json
from config import TOP_N_PICKS


def test_top_n_picks_is_three():
    """Ensure pick quota is 3 as requested."""
    assert TOP_N_PICKS == 3


def test_system_power_toggle():
    """Verify system power toggle turns on and off."""
    toggled_off = toggle_system_power(False)
    assert toggled_off["enabled"] is False
    assert toggled_off["mode"] == "STANDBY"

    toggled_on = toggle_system_power(True)
    assert toggled_on["enabled"] is True
    assert toggled_on["mode"] == "ACTIVE"


def test_market_indices_structure(monkeypatch):
    """Verify NIFTY 50, BANK NIFTY, and SENSEX are present."""
    indices = get_market_indices()
    assert len(indices) == 4
    names = [idx["name"] for idx in indices]
    assert "NIFTY 50" in names
    assert "BANK NIFTY" in names
    assert "SENSEX" in names
    for idx in indices:
        assert "price" in idx
        assert "sparkline" in idx
        assert isinstance(idx["sparkline"], list)


def test_top_movers_and_reasons(monkeypatch):
    """Verify Large, Mid, and Small cap movers have gainers, losers, and reasons."""
    movers = get_top_movers_and_reasons()
    for cap in ["large_cap", "mid_cap", "small_cap"]:
        assert cap in movers
        assert "gainers" in movers[cap]
        assert "losers" in movers[cap]
        # With network disabled, missing movers must remain empty.
        assert movers[cap]["gainers"] == []
        assert movers[cap]["losers"] == []
        for stock in movers[cap]["gainers"] + movers[cap]["losers"]:
            assert "symbol" in stock
            assert "price" in stock
            assert "change_pct" in stock
            assert "reason" in stock
            assert len(stock["reason"]) > 10


def test_trending_sectors():
    """Verify buying and losing sectors."""
    sectors = get_trending_sectors()
    assert "buying_sectors" in sectors
    assert "losing_sectors" in sectors
    assert isinstance(sectors["buying_sectors"], list)
    assert isinstance(sectors["losing_sectors"], list)


def test_geopolitical_market_news():
    """Verify war and macro news affecting stocks."""
    news = get_geopolitical_market_news()
    assert len(news) >= 4
    for item in news:
        assert "headline" in item
        assert "summary" in item
        assert "affected_sectors" in item
        assert len(item["affected_sectors"]) > 0


def test_picks_history_json_persistence(tmp_path, monkeypatch):
    """Verify daily picks are saved to and loaded from JSON with date and time."""
    test_json_file = str(tmp_path / "test_picks_history.json")
    monkeypatch.setattr("config.DAILY_PICKS_JSON_PATH", test_json_file)

    sample_picks = [
        {
            "rank": 1,
            "symbol": "TATASTEEL",
            "entry_price": 154.20,
            "sl_price": 151.00,
            "target_price": 162.00,
            "score": 88.5,
            "status": "pending",
            "sector": "Metals",
            "signal_reasons": "EMA Golden Cross"
        },
        {
            "rank": 2,
            "symbol": "HAL",
            "entry_price": 4380.00,
            "sl_price": 4290.00,
            "target_price": 4560.00,
            "score": 84.0,
            "status": "pending",
            "sector": "Defence",
            "signal_reasons": "Defence Order Flow"
        },
        {
            "rank": 3,
            "symbol": "POLYCAB",
            "entry_price": 6890.00,
            "sl_price": 6750.00,
            "target_price": 7180.00,
            "score": 81.2,
            "status": "pending",
            "sector": "Capital Goods",
            "signal_reasons": "Institutional Inflow"
        },
    ]

    save_picks_to_history_json(sample_picks, date_str="2026-09-08", timestamp_str="2026-09-08T08:55:00")
    loaded = load_picks_history_json()

    assert len(loaded) >= 1
    assert loaded[0]["date"] == "2026-09-08"
    assert loaded[0]["picks_count"] == 3
    assert loaded[0]["picks"][0]["symbol"] == "TATASTEEL"
