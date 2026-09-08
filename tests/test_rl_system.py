# tests/test_rl_system.py — Comprehensive Unit Tests for Dual RL System

import os
import tempfile
import pytest
import numpy as np

from modules.bandit_selector import (
    ContextualBandit,
    FEATURE_DIM,
    rank_candidates_with_bandit,
    update_bandit_eod,
)
from modules.rl_intraday_manager import (
    IntradayRLManager,
    ACTION_HOLD,
    ACTION_TRAIL_BREAKEVEN,
    ACTION_TIGHTEN_SL,
    ACTION_TAKE_PROFIT_EARLY,
    process_tick_with_rl,
)


@pytest.fixture
def temp_bandit_weights():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        path = tf.name
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def temp_rl_policy():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        path = tf.name
    yield path
    if os.path.exists(path):
        os.remove(path)


# ── Contextual Bandit (LinUCB) Tests ──────────────────────────────────────────

def test_bandit_feature_extraction():
    bandit = ContextualBandit(alpha=0.25)
    mock_candidate = {
        "symbol": "TATAMOTORS",
        "price": 1000.0,
        "gap_pct": 2.5,
        "rsi": 62.0,
        "vol_ratio": 2.2,
        "atr": 20.0,
        "score": 85.0,
        "sector_score": 0.8,
    }
    vec = bandit.extract_features(mock_candidate)
    assert isinstance(vec, np.ndarray)
    assert vec.shape == (FEATURE_DIM, 1)
    # Check values are normalized and bounded
    assert -1.0 <= vec[0, 0] <= 1.0  # gap
    assert -1.0 <= vec[1, 0] <= 1.0  # rsi
    assert 0.0 <= vec[2, 0] <= 1.0   # vol
    assert vec[7, 0] == 1.0          # intercept bias


def test_bandit_ranking_and_ucb_scores():
    bandit = ContextualBandit(alpha=0.3)
    candidates = [
        {"symbol": "STOCK_A", "price": 100.0, "score": 60.0, "vol_ratio": 1.2, "rsi": 50.0},
        {"symbol": "STOCK_B", "price": 500.0, "score": 90.0, "vol_ratio": 3.0, "rsi": 65.0},
        {"symbol": "STOCK_C", "price": 250.0, "score": 75.0, "vol_ratio": 2.0, "rsi": 58.0},
    ]
    ranked = bandit.rank_candidates(candidates, top_n=2)
    assert len(ranked) == 2
    assert "bandit_ucb_score" in ranked[0]
    assert "bandit_rank" in ranked[0]
    assert ranked[0]["bandit_rank"] == 1
    # Ranked in descending order of UCB score
    assert ranked[0]["bandit_ucb_score"] >= ranked[1]["bandit_ucb_score"]


def test_bandit_update_and_persistence(temp_bandit_weights):
    bandit = ContextualBandit(alpha=0.25, weights_path=temp_bandit_weights)
    mock_pick = {
        "symbol": "INFY",
        "price": 1800.0,
        "score": 80.0,
        "vol_ratio": 2.5,
        "status": "tp_hit",
        "result_return": 4.5,
    }
    initial_pulls = bandit.total_pulls
    bandit.update_with_reward(mock_pick, reward=1.9)
    bandit.save()

    assert bandit.total_pulls == initial_pulls + 1
    assert os.path.exists(temp_bandit_weights)

    # Reload in fresh instance
    reloaded = ContextualBandit(weights_path=temp_bandit_weights)
    assert reloaded.total_pulls == bandit.total_pulls
    assert reloaded.total_rewards > 0


def test_bandit_graceful_fallback_on_corrupt_data():
    empty_cand = {}
    ranked = rank_candidates_with_bandit([empty_cand], top_n=1)
    assert len(ranked) == 1
    assert "bandit_ucb_score" in ranked[0]


# ── PPO Intraday Dynamic Trailing Manager Tests ────────────────────────────────

def test_rl_manager_state_encoding():
    manager = IntradayRLManager()
    track_dict = {
        "symbol": "RELIANCE",
        "entry_price": 2500.0,
        "current_price": 2550.0,
        "sl_price": 2450.0,
        "tp_price": 2660.0,
        "atr": 35.0,
        "rsi": 62.0,
    }
    state = manager.encode_state(track_dict)
    assert isinstance(state, np.ndarray)
    assert state.shape == (8,)
    # Normalized PnL: (2550-2500)/2500 * 100 = 2.0% -> 2.0 / 5.0 = 0.4
    assert np.isclose(state[0], 0.4, atol=0.01)


def test_rl_manager_breakeven_lock():
    manager = IntradayRLManager(breakeven_trigger_pct=1.5)
    # Price is up +2.0% (>= 1.5%), SL is still below entry
    track_dict = {
        "symbol": "HDFCBANK",
        "entry_price": 1000.0,
        "current_price": 1020.0,  # +2.0%
        "sl_price": 980.0,         # Still below entry
        "tp_price": 1065.0,
    }
    decision = manager.evaluate_tick(track_dict)
    assert decision["action"] == ACTION_TRAIL_BREAKEVEN
    assert decision["sl_modified"] is True
    # New stop loss should be at or slightly above entry price
    assert decision["new_sl"] >= 1000.0


def test_rl_manager_tighten_stop():
    manager = IntradayRLManager(tighten_trigger_pct=2.8)
    # Price is up +3.5% (>= 2.8%), already above breakeven
    track_dict = {
        "symbol": "ICICIBANK",
        "entry_price": 1000.0,
        "current_price": 1035.0,  # +3.5%
        "sl_price": 1005.0,        # Breakeven already
        "tp_price": 1065.0,
    }
    decision = manager.evaluate_tick(track_dict)
    assert decision["action"] == ACTION_TIGHTEN_SL
    assert decision["sl_modified"] is True
    assert decision["new_sl"] > 1005.0


def test_rl_manager_early_take_profit_on_reversal():
    manager = IntradayRLManager(take_profit_trigger_pct=4.2)
    # Stock ran up to +4.5% (1045) then pulled back to 1030 (1.4% pullback)
    track_dict = {
        "symbol": "SBIN",
        "entry_price": 1000.0,
        "current_price": 1030.0,
        "sl_price": 1015.0,
        "tp_price": 1065.0,
        "price_history": [
            {"price": 1000.0},
            {"price": 1020.0},
            {"price": 1045.0},  # Peak +4.5%
            {"price": 1030.0},  # Pullback
        ],
    }
    decision = manager.evaluate_tick(track_dict)
    assert decision["action"] == ACTION_TAKE_PROFIT_EARLY
    assert decision["trigger_early_exit"] is True
    assert decision["exit_type"] == "tp_early"


def test_rl_manager_hold_on_flat_position():
    manager = IntradayRLManager()
    track_dict = {
        "symbol": "TCS",
        "entry_price": 4000.0,
        "current_price": 4010.0,  # +0.25% (normal noise)
        "sl_price": 3920.0,
        "tp_price": 4260.0,
    }
    decision = manager.evaluate_tick(track_dict)
    assert decision["action"] == ACTION_HOLD
    assert decision["sl_modified"] is False
    assert decision["trigger_early_exit"] is False


def test_rl_manager_persistence(temp_rl_policy):
    manager = IntradayRLManager(policy_path=temp_rl_policy)
    manager.total_decisions = 42
    manager.save()
    assert os.path.exists(temp_rl_policy)

    reloaded = IntradayRLManager(policy_path=temp_rl_policy)
    assert reloaded.total_decisions == 42


def test_process_tick_with_rl_safe_fallback():
    # Calling on empty or broken dict must never crash
    res = process_tick_with_rl({})
    assert "action" in res
    assert "action_name" in res
