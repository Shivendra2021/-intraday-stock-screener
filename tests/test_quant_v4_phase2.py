"""
tests/test_quant_v4_phase2.py — Unit Tests for Provider Reliability, Consensus & Rejection Funnel
"""
import pytest
import time
from modules.quant_store import Store
from modules.provider_health import record_request, validate_quote_consensus, get_providers_health
from modules.rejection_audit import record_rejection, get_funnel_summary
from modules.quant_features import quote_gate


@pytest.fixture
def store(tmp_path, monkeypatch):
    import config
    db_path = str(tmp_path / "test_quant.db")
    monkeypatch.setattr(config, "QUANT_DB_PATH", db_path)
    return Store(db_path)


def test_provider_health_recording_and_metrics(store):
    record_request(store, "angel_one", success=True, latency_ms=45.0)
    record_request(store, "angel_one", success=True, latency_ms=55.0)
    record_request(store, "angel_one", success=False, is_timeout=True, error="Timeout 8s")

    records = get_providers_health(store)
    assert len(records) >= 1
    angel = next(r for r in records if r["provider"] == "angel_one")
    assert angel["requests"] == 3
    assert angel["successes"] == 2
    assert angel["failures"] == 1
    assert angel["timeouts"] == 1
    assert angel["fresh_quote_rate"] == pytest.approx(2/3, 0.01)


def test_quote_consensus_matching(store):
    primary = {"source": "angel_one", "ask": 500.0, "bid": 499.8, "ts": time.time(), "upper": 600.0, "series": "EQ"}
    secondary = {"source": "dhan", "ask": 500.5, "bid": 499.5, "ts": time.time(), "upper": 600.0, "series": "EQ"}

    ok, verdict, details = validate_quote_consensus("INFY", primary, secondary, max_drift_pct=0.35, store=store)
    assert ok is True
    assert verdict == "consensus_confirmed"
    assert details["discrepancy_pct"] < 0.35


def test_quote_consensus_disagreement_blocks(store):
    primary = {"source": "angel_one", "ask": 500.0, "bid": 499.8, "ts": time.time(), "upper": 600.0, "series": "EQ"}
    secondary = {"source": "dhan", "ask": 510.0, "bid": 509.0, "ts": time.time(), "upper": 600.0, "series": "EQ"}

    ok, verdict, details = validate_quote_consensus("INFY", primary, secondary, max_drift_pct=0.35, store=store)
    assert ok is False
    assert verdict == "provider_disagreement"
    assert details["discrepancy_pct"] > 0.35

    row = {"symbol": "INFY", "price": 500.0, "stop": 490.0}
    now = time.time()
    assert quote_gate(row, primary, now, secondary_quote=secondary) == "provider_disagreement"


def test_rejection_funnel_audit_ledger(store):
    record_rejection(store, "TATAMOTORS", "liquidity", "insufficient_liquidity", {"turnover": 5000000})
    record_rejection(store, "SBIN", "rvol_gate", "low_rvol", {"rvol": 0.8})
    record_rejection(store, "INFY", "quote_gate", "spread_too_wide", {"spread": 0.45})

    summary = get_funnel_summary(store)
    assert summary["total_rejections"] == 3
    assert summary["rejections_by_stage"]["liquidity"] == 1
    assert summary["rejections_by_reason"]["insufficient_liquidity"] == 1
    assert len(summary["top_rejection_causes"]) == 3
