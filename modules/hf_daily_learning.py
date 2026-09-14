"""Free-only Hugging Face fallback for one after-market learning review daily."""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Any

import requests

from modules.time_utils import now_ist

STATE_FILE = "data/hf_daily_learning_state.json"
FREE_MODEL_PREFERENCE = ("qwen", "deepseek", "llama", "mistral", "gemma")


def _config() -> dict[str, Any]:
    from config import HF_DAILY_LEARNING_ENABLED, HF_ROUTER_URL, HF_TOKEN
    return {"enabled": HF_DAILY_LEARNING_ENABLED, "token": HF_TOKEN, "base_url": HF_ROUTER_URL.rstrip("/")}


def _load_state() -> dict[str, Any]:
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def _today() -> str:
    return str(now_ist().date())


def _retry_after_epoch(response: requests.Response) -> float | None:
    value = response.headers.get("X-RateLimit-Reset", "")
    if not value:
        try:
            value = response.json().get("error", {}).get("metadata", {}).get("headers", {}).get("X-RateLimit-Reset", "")
        except (ValueError, AttributeError):
            value = ""
    try:
        result = float(value)
        return result / 1000 if result > 10_000_000_000 else result
    except (TypeError, ValueError):
        return None


def _choose_free_model(models: list[dict[str, Any]]) -> str | None:
    free = [str(item.get("id", "")).strip() for item in models if item.get("is_free") is True and item.get("id")]
    if not free:
        return None
    return sorted(free, key=lambda model: (
        next((i for i, term in enumerate(FREE_MODEL_PREFERENCE) if term in model.lower()), len(FREE_MODEL_PREFERENCE)),
        model,
    ))[0]


def get_status() -> dict[str, Any]:
    cfg, state = _config(), _load_state()
    retry_epoch = float(state.get("retry_after_epoch", 0) or 0)
    return {
        "enabled": bool(cfg["enabled"]),
        "configured": bool(cfg["token"]),
        "daily_call_cap": 1,
        "last_attempt_date": state.get("last_attempt_date"),
        "selected_model": state.get("selected_model"),
        "last_provider": state.get("last_provider"),
        "last_status": state.get("last_status"),
        "last_error": state.get("last_error"),
        "cooldown_until": dt.datetime.fromtimestamp(retry_epoch, dt.timezone.utc).isoformat() if retry_epoch > time.time() else None,
    }


def review_daily_learning(messages: list[dict[str, str]], max_tokens: int = 900) -> dict[str, Any]:
    """Run at most one free Hugging Face chat completion for today's daily lesson."""
    cfg, state, today = _config(), _load_state(), _today()
    if not cfg["enabled"]:
        return {"ok": False, "skipped": True, "reason": "disabled"}
    if not cfg["token"]:
        return {"ok": False, "skipped": True, "reason": "no_hf_token"}
    if state.get("last_attempt_date") == today:
        return {"ok": False, "skipped": True, "reason": "daily_call_cap"}
    if float(state.get("retry_after_epoch", 0) or 0) > time.time():
        return {"ok": False, "skipped": True, "reason": "provider_cooldown"}

    headers = {"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"}
    try:
        catalog = requests.get(f"{cfg['base_url']}/models", headers=headers, timeout=15)
        if catalog.status_code >= 400:
            return {"ok": False, "error": "model_catalog_unavailable", "status_code": catalog.status_code}
        model = _choose_free_model(catalog.json().get("data", []))
        if not model:
            state.update({"selected_model": None, "last_status": "no_free_model", "last_error": "No currently free Hugging Face chat model"})
            _save_state(state)
            return {"ok": False, "error": "no_free_model"}

        state.update({"last_attempt_date": today, "selected_model": model, "last_provider": "huggingface", "last_status": "attempted", "last_error": ""})
        _save_state(state)
        response = requests.post(
            f"{cfg['base_url']}/chat/completions",
            headers=headers,
            json={"model": model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens},
            timeout=45,
        )
        if response.status_code >= 400:
            retry_epoch = _retry_after_epoch(response)
            state.update({"last_status": "rate_limited" if response.status_code == 429 else "failed", "last_error": response.text[:300]})
            if retry_epoch:
                state["retry_after_epoch"] = retry_epoch
            _save_state(state)
            return {"ok": False, "error": "rate_limited" if response.status_code == 429 else "hf_request_failed", "status_code": response.status_code}
        content = (response.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        if not content:
            state.update({"last_status": "failed", "last_error": "empty model content"})
            _save_state(state)
            return {"ok": False, "error": "empty_model_content"}
        state.update({"last_status": "ok", "last_error": "", "last_ok": now_ist().isoformat(timespec="seconds")})
        _save_state(state)
        return {"ok": True, "content": content, "model": model, "provider": "huggingface"}
    except requests.RequestException as exc:
        state.update({"last_status": "failed", "last_error": str(exc)[:300]})
        _save_state(state)
        return {"ok": False, "error": "hf_request_failed"}
