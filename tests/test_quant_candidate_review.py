import json
from unittest.mock import Mock, patch

import pandas as pd

from modules.quant_daily_review import _free_models, run_daily_review
from modules.quant_review import review
from modules.quant_store import Store


def row():
    ts = int(pd.Timestamp("2026-08-31 09:35", tz="Asia/Kolkata").timestamp())
    return {"symbol": "TEST", "date": "2026-08-31", "ts": ts, "entry_ts": ts + 300,
            "sector": "IT", "p7": .5, "p10": .2, "expected_net_pct": 1.2,
            "model_id": "model", "feature_version": "q3.1"}


def test_review_is_deterministic_and_ai_free():
    qualified = review(row(), model_ready=True, quote_reason="eligible", in_window=True)
    assert qualified["decision"] == "qualified"
    assert qualified["reason"] == "all_deterministic_gates_passed"
    assert review(row(), model_ready=True, quote_reason="quote_stale", in_window=True)["decision"] == "rejected"
    assert review(row(), model_ready=False, quote_reason="model_collecting_evidence", in_window=True)["decision"] == "watchlist"


def test_review_ledger_persists_decision(tmp_path):
    store = Store(tmp_path / "quant.db")
    item = row(); ident = store.observe(item, "eligible")
    verdict = review(item, model_ready=True, quote_reason="eligible", in_window=True)
    store.record_review(ident, item, verdict["decision"], verdict)
    saved = store.reviews("2026-08-31")
    assert saved[0]["decision"] == "qualified"
    assert saved[0]["payload"]["gates"]["data"]["pass"] is True


def test_daily_reviewer_rejects_paid_openrouter_models(monkeypatch):
    import config
    monkeypatch.setattr(config, "OPENROUTER_GEMMA_MODEL", "paid/model")
    monkeypatch.setattr(config, "OPENROUTER_FREE_FALLBACK_MODELS", ("free/model:free", "also-paid"))
    assert _free_models() == ("free/model:free",)


def test_daily_review_uses_free_openrouter_once(monkeypatch, tmp_path):
    import config
    store = Store(tmp_path / "quant.db")
    monkeypatch.setattr(config, "OPENROUTER_GEMMA_KEY", "test-key")
    monkeypatch.setattr(config, "OPENROUTER_GEMMA_MODEL", "free/model:free")
    monkeypatch.setattr(config, "OPENROUTER_FREE_FALLBACK_MODELS", ())
    monkeypatch.setattr(config, "QUANT_AI_DAILY_REVIEW_ENABLED", True)
    response = Mock(status_code=200, headers={})
    response.json.return_value = {"choices": [{"message": {"content": "{\\\"summary\\\":\\\"lesson\\\"}"}}]}
    with patch("modules.quant_daily_review.requests.post", return_value=response) as post, \
         patch("modules.hf_daily_learning.review_daily_learning") as hf:
        result = run_daily_review(store, {"status": "candidate_rejected"}, now=pd.Timestamp("2026-08-31 16:00", tz="Asia/Kolkata"))
        second = run_daily_review(store, {"status": "candidate_rejected"}, now=pd.Timestamp("2026-08-31 16:01", tz="Asia/Kolkata"))
    assert result["ok"] is True and result["provider"] == "openrouter"
    assert post.call_args.kwargs["json"]["model"].endswith(":free")
    assert second["reason"] == "daily_call_cap"
    hf.assert_not_called()
