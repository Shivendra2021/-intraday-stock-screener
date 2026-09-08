"""
grok_brain.py — AI Brain for MarketMind Pro.

PRIMARY  : Grok-3-mini  via OpenRouter
FALLBACK : GPT-4o       via OpenRouter

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
        OPENROUTER_GROK_KEY, OPENROUTER_GPT_KEY, OPENROUTER_BASE_URL,
        GROK_MODEL, GPT_MODEL,
        GROQ_API_KEY, GROQ_BASE_URL, GROQ_DEEPSEEK_MODEL,
        GROQ_DEEPSEEK_ENABLED, GROQ_DEEPSEEK_TIMEOUT_SECONDS,
        XAI_BRAIN_ENABLED, XAI_BRAIN_MAX_DAILY_CALLS,
        XAI_BRAIN_MIN_INTERVAL_SECONDS, XAI_BRAIN_REVIEW_ALERTS,
        XAI_BRAIN_TIMEOUT_SECONDS,
    )
    return {
        "grok_key":     OPENROUTER_GROK_KEY,
        "gpt_key":      OPENROUTER_GPT_KEY,
        "base_url":     OPENROUTER_BASE_URL,
        "grok_model":   GROK_MODEL,
        "gpt_model":    GPT_MODEL,
        "groq_key":     GROQ_API_KEY,
        "groq_base_url": GROQ_BASE_URL,
        "groq_deepseek_model": GROQ_DEEPSEEK_MODEL,
        "groq_deepseek_enabled": GROQ_DEEPSEEK_ENABLED,
        "groq_timeout": GROQ_DEEPSEEK_TIMEOUT_SECONDS,
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
                (cfg["grok_key"] or cfg["gpt_key"] or (cfg["groq_deepseek_enabled"] and cfg["groq_key"])))


def get_brain_status() -> dict[str, Any]:
    cfg = _config()
    state = _load_state()
    return {
        "enabled": bool(cfg["enabled"] and cfg["review_alerts"]),
        "grok_configured": bool(cfg["grok_key"]),
        "gpt_configured": bool(cfg["gpt_key"]),
        "groq_configured": bool(cfg["groq_key"]),
        "groq_deepseek_enabled": bool(cfg["groq_deepseek_enabled"]),
        "grok_model": cfg["grok_model"],
        "gpt_model": cfg["gpt_model"],
        "groq_deepseek_model": cfg["groq_deepseek_model"],
        "daily_calls": _daily_call_count(state),
        "max_daily_calls": cfg["max_daily_calls"],
        "last_ok": state.get("last_ok"),
        "last_error": state.get("last_error"),
        "last_model_used": state.get("last_model_used"),
    }


def _allow_call() -> tuple[bool, str]:
    cfg = _config()
    state = _load_state()
    if not cfg["enabled"] or not cfg["review_alerts"]:
        return False, "disabled"
    if not cfg["grok_key"] and not cfg["gpt_key"] and not (cfg["groq_deepseek_enabled"] and cfg["groq_key"]):
        return False, "no API keys configured"
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
) -> dict[str, Any]:
    """Single attempt to call OpenRouter with a given model/key."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://marketmind.pro",
        "X-Title": "MarketMind Pro",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    try:
        response = requests.post(
            cfg["base_url"],
            headers=headers,
            json=payload,
            timeout=cfg["timeout"],
        )
        if response.status_code == 429:
            return {"ok": False, "error": "rate_limited", "status_code": 429}
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


def _strip_reasoning_tags(content: str) -> str:
    """Remove DeepSeek-style private reasoning blocks before user-facing output."""
    text = str(content or "").strip()
    text = text.replace("<think>\n</think>", "")
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def _call_groq_deepseek(messages: list[dict], cfg: dict, max_tokens: int = 600) -> dict[str, Any]:
    """Single attempt to call Groq's OpenAI-compatible DeepSeek-R1 distill endpoint."""
    if not cfg.get("groq_deepseek_enabled") or not cfg.get("groq_key"):
        return {"ok": False, "error": "Groq DeepSeek disabled or missing key"}
    headers = {
        "Authorization": f"Bearer {cfg['groq_key']}",
        "Content-Type": "application/json",
    }
    candidates = [
        cfg["groq_deepseek_model"],
        "llama-3.3-70b-versatile",
        "groq/compound-mini",
        "openai/gpt-oss-20b",
    ]
    seen: set[str] = set()
    last_error = ""
    for model in [m for m in candidates if not (m in seen or seen.add(m))]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        try:
            response = requests.post(
                cfg["groq_base_url"],
                headers=headers,
                json=payload,
                timeout=cfg["groq_timeout"],
            )
            if response.status_code == 429:
                return {"ok": False, "error": "groq_rate_limited", "status_code": 429}
            if response.status_code >= 400:
                last_error = response.text[:300]
                if any(term in last_error.lower() for term in ("decommissioned", "not found", "does not exist", "invalid model")):
                    logger.warning("Groq model %s unavailable, trying next fallback", model)
                    continue
                return {"ok": False, "error": last_error, "status_code": response.status_code}
            data = response.json()
            message = data["choices"][0].get("message", {})
            content = _strip_reasoning_tags(message.get("content") or "")
            if not content:
                last_error = "empty Groq DeepSeek content"
                continue
            return {"ok": True, "content": content, "model": model}
        except Exception as exc:
            last_error = str(exc)
    return {"ok": False, "error": last_error or "No Groq fallback model succeeded"}


def _call_brain(messages: list[dict], max_tokens: int = 600) -> dict[str, Any]:
    """Try GPT first, Grok second, then Groq DeepSeek as controlled fallback."""
    cfg = _config()
    state = _load_state()
    _increment_daily_call(state)
    state["last_review_epoch"] = time.time()
    state["last_review_time"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_state(state)

    # 1. Try GPT as the primary brain.
    if cfg["gpt_key"]:
        result = _call_openrouter(messages, cfg["gpt_key"], cfg["gpt_model"], cfg, max_tokens)
        if result.get("ok"):
            _update_state(
                last_ok=datetime.datetime.now().isoformat(timespec="seconds"),
                last_error="",
                last_model_used=cfg["gpt_model"],
            )
            logger.info("AI Brain: GPT primary used %s", cfg["gpt_model"])
            return result
        logger.warning("GPT primary failed (%s), trying Grok fallback...", result.get("error", "unknown"))

    # 2. Fallback to Grok.
    if cfg["grok_key"]:
        result = _call_openrouter(messages, cfg["grok_key"], cfg["grok_model"], cfg, max_tokens)
        if result.get("ok"):
            _update_state(
                last_ok=datetime.datetime.now().isoformat(timespec="seconds"),
                last_error="",
                last_model_used=cfg["grok_model"] + " (fallback)",
            )
            logger.info("AI Brain: Grok fallback used %s", cfg["grok_model"])
            return result
        logger.warning("Grok fallback failed (%s), trying Groq DeepSeek...", result.get("error", "unknown"))

    # 3. Controlled reasoning fallback through Groq DeepSeek-R1 distill.
    result = _call_groq_deepseek(messages, cfg, max_tokens)
    if result.get("ok"):
        model_used = result.get("model") or cfg["groq_deepseek_model"]
        _update_state(
            last_ok=datetime.datetime.now().isoformat(timespec="seconds"),
            last_error="",
            last_model_used=model_used + " (groq fallback)",
        )
        logger.info("AI Brain: Groq DeepSeek fallback used %s", model_used)
        return result

    _update_state(last_error=f"All AI providers failed: {result.get('error','')[:200]}")

    return {"ok": False, "error": "All AI providers failed"}


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
