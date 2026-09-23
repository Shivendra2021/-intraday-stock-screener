"""
tests/test_quant_v4_phase4.py — Unit Tests for Winner Discovery Research Lab
"""
import pytest
import datetime as dt
import pandas as pd
from modules.quant_store import Store
from modules.winner_discovery import analyze_session_winners, get_winner_discovery_report


@pytest.fixture
def store(tmp_path, monkeypatch):
    import config
    db_path = str(tmp_path / "test_winner.db")
    monkeypatch.setattr(config, "QUANT_DB_PATH", db_path)
    return Store(db_path)


def make_runner_bars(symbol, date_str, op, hi, lo, cl):
    times = pd.date_range(f"{date_str} 09:15", periods=75, freq="5min", tz="Asia/Kolkata")
    rows = []
    for i in range(75):
        if i == 0:
            o, h, l, c = op, op * 1.01, op * 0.99, op * 1.005
        elif i == 40: # mid-day massive breakout to high
            o, h, l, c = op * 1.04, hi, op * 1.03, hi * 0.995
        elif i == 74:
            o, h, l, c = cl * 0.998, cl * 1.002, cl * 0.995, cl
        else:
            o, h, l, c = op * 1.02, op * 1.03, op * 1.01, op * 1.025
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": 100000})
    return pd.DataFrame(rows, index=times)


def test_winner_discovery_detection_and_isolation(store):
    date_str = "2026-09-04"
    # Create 1 runner (+8.5% excursion) and 1 non-runner (+2.0% excursion)
    runner_bars = make_runner_bars("RUNNER", date_str, op=100.0, hi=108.5, lo=99.0, cl=107.0)
    normal_bars = make_runner_bars("NORMAL", date_str, op=200.0, hi=204.0, lo=198.0, cl=201.0)

    store.save_bars("RUNNER", "5m", runner_bars, "test")
    store.save_bars("NORMAL", "5m", normal_bars, "test")

    universe_test = {"RUNNER": "Capital Goods", "NORMAL": "IT"}

    # Mock initial dummy model to verify weights NEVER change
    dummy_model = {"id": "test_m1", "weights": {"7": [0.1, 0.2], "10": [0.05, 0.1]}}
    store.put("active_model", dummy_model)

    res = analyze_session_winners(store, date=date_str, threshold_pct=7.0, universe_symbols=universe_test)

    assert res["runners_7pct_count"] == 1
    assert res["runners_10pct_count"] == 0
    assert len(res["top_winners"]) == 1

    winner = res["top_winners"][0]
    assert winner["symbol"] == "RUNNER"
    assert winner["max_return_pct"] == 8.5
    assert winner["is_runner_7pct"] is True

    # Pre-move features must be captured strictly from opening window
    pre = winner["pre_move_features"]
    assert "gap_pct" in pre
    assert "orb_range_pct" in pre

    # Verify model weights are completely unchanged (isolation guaranteed)
    persisted_model = store.get("active_model")
    assert persisted_model == dummy_model

    # Verify retrieval report
    report = get_winner_discovery_report(store, date=date_str)
    assert report["runners_7pct_count"] == 1
    assert report["top_winners"][0]["symbol"] == "RUNNER"
