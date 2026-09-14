"""
grok_brain.py — AI Brain for MarketMind Pro.

PRIMARY  : configured DashScope Qwen, when available
FALLBACK : free OpenRouter Gemma model pool

Used for:
  1. Reviewing Telegram alerts before they go out
  2. Deep stock analysis (called from research_engine.py)
  3. System health supervision

Fail-open: if both models fail, the bot continues without AI review.
"""

from __future__ import annotations

import datetime
import html
import json
import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

STATE_FILE = "data/grok_brain_state.json"
MAX_TELEGRAM_CHARS = 3900


# ─────────────────────────────────────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────────────────────────────────────

def _config() -> dict:
    from config import (
        DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, QWEN_MAX_MODEL,
        OPENROUTER_GEMMA_KEY, OPENROUTER_BASE_URL, OPENROUTER_GEMMA_MODEL,
        OPENROUTER_FREE_FALLBACK_MODELS,
        XAI_BRAIN_ENABLED, XAI_BRAIN_MAX_DAILY_CALLS,
        XAI_BRAIN_MIN_INTERVAL_SECONDS, XAI_BRAIN_REVIEW_ALERTS,
        XAI_BRAIN_TIMEOUT_SECONDS,
    )
    return {
        "qwen_key":     DASHSCOPE_API_KEY,
        "qwen_base_url": DASHSCOPE_BASE_URL,
        "qwen_model":   QWEN_MAX_MODEL,
        "gemma_key":    OPENROUTER_GEMMA_KEY,
        "gemma_base_url": OPENROUTER_BASE_URL,
        "gemma_model":  OPENROUTER_GEMMA_MODEL,
        "gemma_fallback_models": OPENROUTER_FREE_FALLBACK_MODELS,
        "enabled":      XAI_BRAIN_ENABLED,
        "review_alerts": XAI_BRAIN_REVIEW_ALERTS,
        "max_daily_calls": XAI_BRAIN_MAX_DAILY_CALLS,
        "min_interval": XAI_BRAIN_MIN_INTERVAL_SECONDS,
        "timeout":      XAI_BRAIN_TIMEOUT_SECONDS,
    }


# ─────────────────────────────────────────────────────────────────────────────
# State management
# ─────────────────────────────────────────────────────────────────────────────

def _today_key() -> str:
    return datetime.date.today().isoformat()


def _load_state() -> dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def _update_state(**updates: Any) -> None:
    state = _load_state()
    state.update(updates)
    state["last_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_state(state)


def _daily_call_count(state: dict) -> int:
    return int(state.get("daily_calls", {}).get(_today_key(), 0))


def _increment_daily_call(state: dict) -> None:
    calls = state.setdefault("daily_calls", {})
    today = _today_key()
    calls[today] = int(calls.get(today, 0)) + 1
    for day in list(calls):
        if day != today:
            calls.pop(day, None)


def is_enabled() -> bool:
    cfg = _config()
    return bool(cfg["enabled"] and cfg["review_alerts"] and
                (cfg["qwen_key"] or cfg["gemma_key"]))


def get_brain_status() -> dict[str, Any]:
    cfg = _config()
    state = _load_state()
    last_model_used = str(state.get("last_model_used") or "")
    active_models = (str(cfg["qwen_model"]), str(cfg["gemma_model"]), *map(str, cfg["gemma_fallback_models"]))
    if last_model_used and not any(last_model_used.startswith(model) for model in active_models):
        # Do not present a historical legacy-provider result as current V3 state.
        last_model_used = ""
    cooldown_epoch = float(state.get("free_provider_retry_after_epoch", 0) or 0)
    return {
        "enabled": bool(cfg["enabled"] and cfg["review_alerts"]),
        "configured": bool(cfg["qwen_key"] or cfg["gemma_key"]),
        "model": cfg["qwen_model"],
        "qwen_configured": bool(cfg["qwen_key"]),
        "gemma_configured": bool(cfg["gemma_key"]),
        "qwen_model": cfg["qwen_model"],
        "gemma_model": cfg["gemma_model"],
        "daily_calls": _daily_call_count(state),
        "max_daily_calls": cfg["max_daily_calls"],
        "last_ok": state.get("last_ok"),
        "last_error": state.get("last_error"),
        "last_model_used": last_model_used,
        "free_provider_cooldown_until": (
            datetime.datetime.fromtimestamp(cooldown_epoch, datetime.timezone.utc).isoformat()
            if cooldown_epoch > time.time() else None
        ),
    }


def _allow_call() -> tuple[bool, str]:
    cfg = _config()
    state = _load_state()
    if not cfg["enabled"] or not cfg["review_alerts"]:
        return False, "disabled"
    if not cfg["qwen_key"] and not cfg["gemma_key"]:
        return False, "no API keys configured"
    retry_after = float(state.get("free_provider_retry_after_epoch", 0) or 0)
    if retry_after > time.time():
        return False, "free_provider_cooldown"
    if _daily_call_count(state) >= cfg["max_daily_calls"]:
        return False, "daily budget reached"
    last_ts = float(state.get("last_review_epoch", 0) or 0)
    if last_ts and (time.time() - last_ts) < cfg["min_interval"]:
        return False, "min interval guard"
    return True, "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Core OpenRouter call — Grok primary, GPT fallback
# ─────────────────────────────────────────────────────────────────────────────

def _call_openrouter(
    messages: list[dict],
    api_key: str,
    model: str,
    cfg: dict,
    max_tokens: int = 600,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Single bounded OpenAI-compatible model call."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = base_url or cfg["gemma_base_url"]
    if "openrouter.ai" in url:
        headers.update({"HTTP-Referer": "https://marketmind.pro", "X-Title": "MarketMind Pro"})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    try:
        for attempt in range(3):
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=cfg["timeout"],
            )
            if response.status_code == 429:
                retry_after = response.headers.get("X-RateLimit-Reset", "")
                if not retry_after:
                    try:
                        retry_after = response.json().get("error", {}).get("metadata", {}).get("headers", {}).get("X-RateLimit-Reset", "")
                    except (ValueError, AttributeError):
                        retry_after = ""
                try:
                    retry_after_epoch = float(retry_after)
                    if retry_after_epoch > 10_000_000_000:
                        retry_after_epoch /= 1000
                except (TypeError, ValueError):
                    retry_after_epoch = None
                if attempt < 2:
                    time.sleep(0.75 * (attempt + 1))
                    continue
                return {"ok": False, "error": "rate_limited", "status_code": 429,
                        "retry_after_epoch": retry_after_epoch}
            if response.status_code >= 400:
                return {"ok": False, "error": response.text[:300], "status_code": response.status_code}
            data = response.json()
            message = data["choices"][0].get("message", {})
            content = (message.get("content") or "").strip()
            if not content:
                return {"ok": False, "error": "empty model content", "status_code": response.status_code}
            return {"ok": True, "content": content, "model": model}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "request did not complete"}


def _call_brain(messages: list[dict], max_tokens: int = 600) -> dict[str, Any]:
    """Run configured Qwen first, then the free OpenRouter Gemma pool."""
    cfg = _config()
    state = _load_state()
    _increment_daily_call(state)
    state["last_review_epoch"] = time.time()
    state["last_review_time"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_state(state)

    if cfg["qwen_key"]:
        result = _call_openrouter(messages, cfg["qwen_key"], cfg["qwen_model"], cfg, max_tokens, cfg["qwen_base_url"])
        if result.get("ok"):
            _update_state(
                last_ok=datetime.datetime.now().isoformat(timespec="seconds"),
                last_error="",
                last_model_used=cfg["qwen_model"],
            )
            logger.info("AI Brain: Qwen primary used %s", cfg["qwen_model"])
            return result
        logger.warning("Qwen primary failed (%s), trying Gemma challenger...", result.get("error", "unknown"))

    last_error = ""
    retry_after_epoch = None
    if cfg["gemma_key"]:
        models = tuple(dict.fromkeys((cfg["gemma_model"], *cfg["gemma_fallback_models"])))
        for model in models:
            result = _call_openrouter(messages, cfg["gemma_key"], model, cfg, max_tokens, cfg["gemma_base_url"])
            if result.get("ok"):
                _update_state(
                    last_ok=datetime.datetime.now().isoformat(timespec="seconds"),
                    last_error="",
                    last_model_used=model + " (OpenRouter free fallback)",
                )
                logger.info("AI Brain: OpenRouter fallback used %s", model)
                return result
            last_error = str(result.get("error", ""))
            retry_after_epoch = result.get("retry_after_epoch") or retry_after_epoch
            logger.warning("OpenRouter model %s failed (%s)", model, last_error)

    updates = {"last_error": f"Configured AI models failed: {last_error[:200]}"}
    if retry_after_epoch:
        updates["free_provider_retry_after_epoch"] = retry_after_epoch
    _update_state(**updates)

    return {"ok": False, "error": "Qwen and Gemma failed"}


# ─────────────────────────────────────────────────────────────────────────────
# JSON parsing helper
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return {}
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def review_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Review any system event. Returns verdict dict."""
    allowed, reason = _allow_call()
    if not allowed:
        return {"ok": False, "skipped": True, "reason": reason}

    system_prompt = (
        "You are the AI Brain for an Indian intraday stock research bot. "
        "You supervise system health, data-source failures, risk flags, morning picks, "
        "pick tracking, and alert quality. Research-only system — no trades placed. "
        "Use only the provided payload. Do NOT invent live prices, targets, or news. "
        "Return compact JSON only with keys: verdict, risk_level, send_ok, brief_review, "
        "watch_items (max 3 strings), next_action. Keep brief_review under 50 words."
    )
    user_prompt = json.dumps(
        {"event_type": event_type, "payload": payload},
        ensure_ascii=True, default=str,
    )
    result = _call_brain([
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ])
    if not result.get("ok"):
        return result

    parsed = _parse_json_object(result.get("content", ""))
    if not parsed:
        return {
            "ok": True, "verdict": "reviewed", "risk_level": "unknown",
            "send_ok": True,
            "brief_review": "AI review returned non-JSON, original alert unchanged.",
            "watch_items": [], "next_action": "Monitor AI output.",
        }
    parsed["ok"] = True
    parsed["model_used"] = result.get("model")
    return parsed


def evaluate_stock_intraday_period(stock: dict) -> dict[str, Any]:
    """
    Finalize specific intraday market period and return criteria for a stock:
    - 09:15 - 10:15 AM: Morning Opening Momentum & ORB Breakout (Target: 5.5% - 8.0%)
    - 10:15 - 12:30 PM: Midday VWAP Pullback & Trend Continuation (Target: 5.0% - 6.5%)
    - 12:30 - 02:15 PM: Afternoon Breakout & European Open Acceleration (Target: 5.0% - 7.0%)
    """
    gap = float(stock.get("gap_up", 0.0) or 0.0)
    vol = float(stock.get("vol_ratio", 1.0) or 1.0)
    rsi = float(stock.get("rsi", 50.0) or 50.0)
    adx = float(stock.get("adx", 20.0) or 20.0)
    ema = str(stock.get("ema_alignment", ""))

    # Morning Opening Momentum: Gap up + heavy volume expansion
    if (gap >= 0.8 and vol >= 1.5) or vol >= 2.2:
        prime_window = "09:15 - 10:15 AM (Morning Momentum)"
        period_code = "MORNING_ORB"
        target_return = round(min(8.0, max(5.2, 5.0 + (vol - 1.2) * 1.0 + max(0.0, gap) * 0.4)), 1)
        strategy = "Opening Range Breakout (ORB) on 2x+ Vol Surge"
        time_cutoff = "10:30 AM (Tighten SL to breakeven if +2.5% achieved)"
        edge_rationale = "Rapid opening liquidity expansion & morning gap momentum"
    # Midday VWAP Consolidation & Continuation
    elif ema in ("EMA_full_bull", "EMA_partial_bull") and 52 <= rsi <= 68:
        prime_window = "10:15 - 12:30 PM (VWAP Continuation)"
        period_code = "MIDDAY_VWAP"
        target_return = round(min(7.0, max(5.0, 4.8 + (rsi - 50) * 0.12)), 1)
        strategy = "VWAP / EMA 9 Pullback hold, buy institutional absorption"
        time_cutoff = "12:45 PM (Exit if trading below VWAP)"
        edge_rationale = "Sustained institutional accumulation with healthy pullback"
    # Afternoon Breakout / European Push
    else:
        prime_window = "12:30 - 02:15 PM (Afternoon Surge)"
        period_code = "AFTERNOON_PUSH"
        target_return = round(min(7.5, max(5.0, 5.0 + (adx / 25.0))), 1)
        strategy = "High-of-Day Breakout on secondary volume surge"
        time_cutoff = "02:45 PM (Square-off before market close)"
        edge_rationale = "Secondary momentum wave & short-squeeze into late session"

    return {
        "prime_window": prime_window,
        "period_code": period_code,
        "target_return_pct": target_return,
        "strategy": strategy,
        "time_cutoff": time_cutoff,
        "edge_rationale": edge_rationale,
    }


def analyse_stocks_deep(stocks: list[dict], sector_context: str = "") -> str:
    """
    Deep AI analysis of top-20 stock candidates.
    Returns a formatted string summary for Telegram.
    Uses Grok as stock analyser; GPT-4o / Groq DeepSeek as fallback.
    Prioritizes Small & Midcap explosive return criteria across specific intraday time periods.
    """
    allowed, reason = _allow_call()
    if not allowed:
        return f"[AI analysis skipped: {reason}]"

    system_prompt = (
        "You are the Chief Intraday Strategist for Indian Small & Midcap momentum stocks. "
        "Large caps are strictly excluded. We only focus on high-beta Small & Midcaps targeting "
        "5.0% to 8.0% intraday gains. "
        "Analyse the provided stock candidates and identify the top 5 most likely to deliver "
        "maximum return during their specific INTRADAY MARKET PERIOD: "
        "- Period 1 (09:15-10:15 AM): Morning ORB breakout & 2x vol surge. "
        "- Period 2 (10:15-12:30 PM): VWAP / EMA-9 pullback continuation. "
        "- Period 3 (12:30-02:15 PM): Afternoon high-of-day acceleration. "
        "For each pick, format strictly on one line: "
        "RANK. SYMBOL | PRIME TIME: [window] | TARGET: [+X%] | STRATEGY: [action] | WHY IT MOVES: [catalyst] | RISK: [stop/invalid]. "
        "Be specific, quantitative, and concise. Max 300 words total."
    )
    user_content = (
        f"Top trending sectors: {sector_context}\n\n"
        f"Small & Midcap candidates (top 20 by quantitative score):\n"
    )
    for s in stocks[:20]:
        timing = evaluate_stock_intraday_period(s)
        user_content += (
            f"- {s.get('symbol')}: Price=₹{s.get('price', 0):.2f} "
            f"RSI={s.get('rsi', 0):.1f} Vol={s.get('vol_ratio', 1):.2f}x "
            f"EMA={s.get('ema_alignment', 'N/A')} ADX={s.get('adx', 0):.1f} "
            f"Score={s.get('score', 0):.1f} Gap={s.get('gap_up', 0):.2f}% "
            f"Suggested Window: {timing['prime_window']} (Target: +{timing['target_return_pct']}%)\n"
        )
    user_content += "\nWhich 5 Small/Midcap stocks have the highest intraday return probability in their specific market time window?"

    result = _call_brain([
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_content},
    ], max_tokens=600)

    if not result.get("ok"):
        return f"[AI analysis failed: {result.get('error', 'unknown')}]"
    model_used = result.get("model", "AI")
    return f"🤖 <b>AI Intraday Period Analysis ({model_used.split('/')[-1]})</b>:\n{result['content']}"


def review_telegram_alert(text: str, event_type: str = "telegram_alert") -> str:
    """
    Review a Telegram alert and append a compact AI note.
    Returns original text unchanged when AI is unavailable or throttled.
    """
    if not text:
        return text

    review = review_event(
        event_type,
        {
            "outgoing_alert": text[:3200],
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        },
    )

    if not review.get("ok"):
        reason = review.get("reason") or review.get("error", "unavailable")
        logger.info("AI Brain skipped alert review: %s", reason)
        return text

    verdict    = html.escape(str(review.get("verdict",      "reviewed"))[:80])
    risk       = html.escape(str(review.get("risk_level",   "unknown"))[:40])
    brief      = html.escape(str(review.get("brief_review", ""))[:500])
    next_action= html.escape(str(review.get("next_action",  ""))[:220])
    watch_items = review.get("watch_items", [])
    model_used = review.get("model_used", "AI")

    lines = [
        "",
        f"<b>🤖 AI Brain Review</b> ({model_used.split('/')[-1] if '/' in str(model_used) else model_used})",
        f"Verdict: {verdict} | Risk: {risk}",
    ]
    if brief:
        lines.append(f"Review: {brief}")
    if watch_items:
        clean = [html.escape(str(i)[:120]) for i in watch_items[:3]]
        lines.append("Watch: " + "; ".join(clean))
    if next_action:
        lines.append(f"Next: {next_action}")

    reviewed = text + "\n".join(lines)
    if len(reviewed) <= MAX_TELEGRAM_CHARS:
        return reviewed

    room = MAX_TELEGRAM_CHARS - len("\n".join(lines)) - 80
    trimmed = text[:max(room, 500)].rstrip()
    return trimmed + "\n\n<i>Alert trimmed.</i>\n" + "\n".join(lines)


def test_connection() -> dict[str, Any]:
    """Quick connectivity test."""
    allowed, reason = _allow_call()
    if not allowed:
        return {"ok": False, "reason": reason, "status": get_brain_status()}

    result = _call_brain([
        {"role": "system", "content": "Return JSON: {\"verdict\":\"ok\",\"risk_level\":\"low\",\"send_ok\":true,\"brief_review\":\"Connection test passed.\",\"watch_items\":[],\"next_action\":\"None.\"}"},
        {"role": "user",   "content": "Connection test for MarketMind AI Brain."},
    ], max_tokens=80)

    result["status"] = get_brain_status()
    return result
