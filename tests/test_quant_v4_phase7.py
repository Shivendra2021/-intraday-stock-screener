import os
import tempfile
import pytest
from modules.quant_store import Store, dumps
from modules.experiment_registry import (
    ensure_experiment_tables,
    register_experiment,
    update_experiment_status,
    get_experiment,
    list_experiments,
    can_promote_experiment,
    promote_experiment,
)


@pytest.fixture
def temp_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = Store(path)
    ensure_experiment_tables(store)
    yield store
    if os.path.exists(path):
        os.remove(path)


def test_experiment_registration_and_listing(temp_store):
    exp = register_experiment(
        experiment_id="exp-regime-01",
        version_tag="q4.1-regime",
        base_model_id="model_abc123",
        hypothesis="Adding Nifty trend regime improves win-rate by 4%",
        features_spec={"extra_features": ["market_regime", "relative_strength"]},
        store=temp_store,
    )
    assert exp["experiment_id"] == "exp-regime-01"
    assert exp["status"] == "proposed"

    retrieved = get_experiment("exp-regime-01", store=temp_store)
    assert retrieved is not None
    assert retrieved["version_tag"] == "q4.1-regime"
    assert "market_regime" in retrieved["features_spec"]

    all_exps = list_experiments(store=temp_store)
    assert len(all_exps) == 1


def test_promotion_gate_rejects_insufficient_forward_evidence(temp_store):
    register_experiment(
        experiment_id="exp-early-01",
        version_tag="q4.1-test",
        base_model_id="m_early",
        hypothesis="Early model test",
        features_spec=[],
        store=temp_store,
    )

    # State still proposed -> should reject
    ok, msg = can_promote_experiment("exp-early-01", store=temp_store)
    assert not ok
    assert "must be 'forward_testing' or 'shadow'" in msg

    # Transition to forward_testing with only 5 sessions and 8 trades
    update_experiment_status(
        "exp-early-01",
        "forward_testing",
        forward_metrics={"days": 5, "trades": 8, "lower_mean_bound": 0.4, "mean_net_pct": 1.2},
        store=temp_store,
    )

    # Should fail min sessions (needs 20)
    ok, msg = can_promote_experiment("exp-early-01", min_forward_sessions=20, store=temp_store)
    assert not ok
    assert "Insufficient forward sessions" in msg

    # Should fail promotion attempt
    promoted, p_msg = promote_experiment("exp-early-01", "Attempt early promote", store=temp_store)
    assert not promoted
    assert "Insufficient forward sessions" in p_msg

    # Verify status changed to rejected
    exp = get_experiment("exp-early-01", store=temp_store)
    assert exp["status"] == "rejected"


def test_promotion_gate_accepts_validated_model(temp_store):
    # Insert dummy model in models table
    with temp_store.connect() as c:
        c.execute("INSERT INTO models (id, created_at, value, promoted) VALUES (?, ?, ?, 0)",
                  ("model_winner", 1710000000, dumps({"id": "model_winner"}),))

    register_experiment(
        experiment_id="exp-winner-01",
        version_tag="q4.2-proven",
        base_model_id="model_winner",
        hypothesis="High-beta runner breakout model",
        features_spec=["rvol", "gap_pct", "atr_pct"],
        store=temp_store,
    )

    # Valid metrics: 25 sessions, 42 trades, positive lower bound +0.32%, mean net +1.45%
    fwd_metrics = {
        "days": 25,
        "trades": 42,
        "lower_mean_bound": 0.32,
        "mean_net_pct": 1.45,
    }

    update_experiment_status(
        "exp-winner-01",
        "forward_testing",
        forward_metrics=fwd_metrics,
        store=temp_store,
    )

    ok, msg = can_promote_experiment("exp-winner-01", store=temp_store)
    assert ok
    assert "criteria satisfied" in msg

    promoted, p_msg = promote_experiment("exp-winner-01", "25 days verified forward alpha", store=temp_store)
    assert promoted

    exp = get_experiment("exp-winner-01", store=temp_store)
    assert exp["status"] == "promoted"
    assert exp["promotion_reason"] == "25 days verified forward alpha"

    # Verify model in models table was set to promoted = 1
    with temp_store.connect() as c:
        row = c.execute("SELECT promoted FROM models WHERE id='model_winner'").fetchone()
        assert row[0] == 1
