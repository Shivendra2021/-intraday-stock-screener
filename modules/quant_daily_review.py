"""Bounded free-only qualitative review for completed Quant sessions."""
from __future__ import annotations

import datetime as dt
import json
import time

import requests

from modules.quant_store import Store
from modules.quant_time import now_ist


def _free_models():
    from config import OPENROUTER_GEMMA_MODEL, OPENROUTER_FREE_FALLBACK_MODELS
    return tuple(model for model in (OPENROUTER_GEMMA_MODEL, *OPENROUTER_FREE_FALLBACK_MODELS)
                 if isinstance(model, str) and (model.endswith(":free") or model == "openrouter/free"))


def _payload(store, learning):
    snap = store.get("runtime", {})
    return {"learning": learning, "runtime": {k: snap.get(k) for k in ("date", "status", "selected", "rejections")},
            "instruction": "Summarize only supplied measured outcomes and rejected gates. Propose filters; do not select stocks or change parameters."}


def _openrouter(messages, state):
    from config import OPENROUTER_GEMMA_KEY, OPENROUTER_BASE_URL
    models = _free_models()
    if not OPENROUTER_GEMMA_KEY:
        return {"ok": False, "reason": "openrouter_not_configured"}
    if not models:
        return {"ok": False, "reason": "no_free_openrouter_model"}
    for model in models:
        try:
            response = requests.post(OPENROUTER_BASE_URL, timeout=30,
                headers={"Authorization": f"Bearer {OPENROUTER_GEMMA_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": 0.1, "max_tokens": 700})
        except requests.RequestException as exc:
            last = {"ok": False, "reason": type(exc).__name__}
            continue
        if response.status_code == 429:
            reset = response.headers.get("X-RateLimit-Reset")
            try: reset = float(reset) / (1000 if float(reset) > 10_000_000_000 else 1)
            except (TypeError, ValueError): reset = None
            return {"ok": False, "reason": "rate_limited", "cooldown_until": reset}
        if response.status_code >= 400:
            last = {"ok": False, "reason": f"http_{response.status_code}"}
            continue
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            return {"ok": False, "reason": "invalid_openrouter_response"}
        return {"ok": True, "provider": "openrouter", "model": model, "content": content}
    return last if "last" in locals() else {"ok": False, "reason": "openrouter_failed"}


def run_daily_review(store=None, learning=None, now=None):
    from config import QUANT_AI_DAILY_REVIEW_ENABLED, QUANT_AI_MAX_DAILY_CALLS
    store = store or Store(); now = now or now_ist(); today = str(now.date())
    state = store.get("quant_ai_review", {})
    if not QUANT_AI_DAILY_REVIEW_ENABLED:
        return {"ok": False, "skipped": True, "reason": "disabled"}
    if state.get("date") == today and state.get("attempts", 0) >= QUANT_AI_MAX_DAILY_CALLS:
        return {"ok": False, "skipped": True, "reason": "daily_call_cap"}
    cooldown = state.get("cooldown_until")
    if cooldown and cooldown > time.time():
        return {"ok": False, "skipped": True, "reason": "provider_cooldown", "cooldown_until": cooldown}
    learning = learning or store.get("learning", {})
    messages = [
        {"role": "system", "content": "You are a post-market evidence summarizer. Use only supplied facts. Return JSON with summary, proposed_filters, avoid_filters, and confidence. Never select stocks, veto candidates, or alter parameters."},
        {"role": "user", "content": json.dumps(_payload(store, learning), default=str)[:16000]},
    ]
    result = _openrouter(messages, state)
    saved = {"date": today, "attempts": 1, "updated_at": now.isoformat(),
             "status": "ok" if result.get("ok") else "review_skipped",
             "provider": result.get("provider"), "model": result.get("model"),
             "provider_error": None if result.get("ok") else result.get("reason", "failed"),
             "cooldown_until": result.get("cooldown_until"), "result": result.get("content", "")[:4000]}
    store.put("quant_ai_review", saved)
    return {**result, "state": saved}
