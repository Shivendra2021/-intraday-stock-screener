from unittest.mock import Mock, patch


def _response(status=200, payload=None, text=""):
    response = Mock(status_code=status, text=text, headers={})
    response.json.return_value = payload or {}
    return response


def _setup(monkeypatch, tmp_path):
    import config
    import modules.hf_daily_learning as hf
    monkeypatch.setattr(hf, "STATE_FILE", str(tmp_path / "hf_state.json"))
    monkeypatch.setattr(config, "HF_TOKEN", "hf_test")
    monkeypatch.setattr(config, "HF_DAILY_LEARNING_ENABLED", True)
    return hf


def test_hf_uses_only_models_marked_free(monkeypatch, tmp_path):
    hf = _setup(monkeypatch, tmp_path)
    catalog = _response(payload={"data": [{"id": "paid/model", "is_free": False}, {"id": "free/model", "is_free": True}]})
    completion = _response(payload={"choices": [{"message": {"content": "lesson"}}]})
    with patch("modules.hf_daily_learning.requests.get", return_value=catalog), patch("modules.hf_daily_learning.requests.post", return_value=completion) as post:
        result = hf.review_daily_learning([{"role": "user", "content": "learn"}], 12)
    assert result["ok"] is True
    assert result["model"] == "free/model"
    assert post.call_args.kwargs["json"]["model"] == "free/model"


def test_hf_enforces_one_daily_attempt(monkeypatch, tmp_path):
    hf = _setup(monkeypatch, tmp_path)
    hf._save_state({"last_attempt_date": hf._today()})
    with patch("modules.hf_daily_learning.requests.get") as get:
        result = hf.review_daily_learning([{"role": "user", "content": "learn"}])
    assert result == {"ok": False, "skipped": True, "reason": "daily_call_cap"}
    get.assert_not_called()


def test_hf_records_rate_limit(monkeypatch, tmp_path):
    hf = _setup(monkeypatch, tmp_path)
    catalog = _response(payload={"data": [{"id": "free/model", "is_free": True}]})
    limited = _response(status=429, payload={"error": {"metadata": {"headers": {"X-RateLimit-Reset": "2000000000"}}}}, text="limited")
    with patch("modules.hf_daily_learning.requests.get", return_value=catalog), patch("modules.hf_daily_learning.requests.post", return_value=limited):
        result = hf.review_daily_learning([{"role": "user", "content": "learn"}])
    assert result["error"] == "rate_limited"
    assert hf.get_status()["cooldown_until"] is not None


def test_daily_learning_uses_hf_only_after_openrouter_fails(monkeypatch):
    import modules.ollama_intraday_agent as agent
    fallback = {"ok": True, "content": '{"summary":"lesson"}', "model": "free/model"}
    with patch("modules.grok_brain._call_brain", return_value={"ok": False, "error": "cooldown"}), patch("modules.hf_daily_learning.review_daily_learning", return_value=fallback) as hf_call:
        result = agent._call_openrouter_learning({"winners": []})
    assert result["ok"] is True
    assert result["brain_role"] == "huggingface_free_daily_learning"
    hf_call.assert_called_once()
