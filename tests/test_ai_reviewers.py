from unittest.mock import Mock, patch


def _response(content):
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    return response


def test_qwen_is_primary_and_gemma_is_fallback(monkeypatch, tmp_path):
    import config
    import modules.grok_brain as brain
    monkeypatch.setattr(brain, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "MISTRAL_API_KEY", "")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.setattr(config, "OPENROUTER_GEMMA_KEY", "gemma-test")
    with patch("modules.grok_brain.requests.post", return_value=_response("Qwen result")) as post:
        result = brain._call_brain([{"role": "user", "content": "test"}], 12)
    assert result["ok"] is True
    assert result["model"] == config.QWEN_MAX_MODEL
    assert post.call_args.args[0] == config.DASHSCOPE_BASE_URL


def test_gemma_runs_only_after_qwen_failure(monkeypatch, tmp_path):
    import config
    import modules.grok_brain as brain
    monkeypatch.setattr(brain, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "MISTRAL_API_KEY", "")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.setattr(config, "OPENROUTER_GEMMA_KEY", "gemma-test")
    failed = Mock(status_code=503, text="temporarily unavailable")
    with patch("modules.grok_brain.requests.post", side_effect=[failed, _response("Gemma result")]) as post:
        result = brain._call_brain([{"role": "user", "content": "test"}], 12)
    assert result["ok"] is True
    assert result["model"] == config.OPENROUTER_GEMMA_MODEL
    assert post.call_args_list[1].args[0] == config.OPENROUTER_BASE_URL


def test_legacy_ollama_and_groq_defaults_are_disabled():
    import config
    assert config.OLLAMA_AGENT_ENABLED is False
    assert config.GROQ_DEEPSEEK_ENABLED is False
