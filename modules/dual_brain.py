# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.

"""
dual_brain.py — Dual-Brain Debate + Command System

Brain 1 (Qwen 3.7 Max): Primary analyst
Brain 2 (Gemma 3 4B): Independent challenger
Both can ISSUE COMMANDS - executed only when BOTH agree
"""

from __future__ import annotations
import datetime
import json
import logging
import os
import time
from typing import Any

import requests

from modules.time_utils import now_ist, today_ist_str

logger = logging.getLogger(__name__)

DEBATE_LOG_FILE = "data/dual_brain_debates.json"
MAX_DEBATE_ROUNDS = 3


def _config() -> dict:
    from config import (
        DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, QWEN_MAX_MODEL,
        OPENROUTER_GEMMA_KEY, OPENROUTER_BASE_URL, OPENROUTER_GEMMA_MODEL,
    )
    return {
        "qwen_key": DASHSCOPE_API_KEY,
        "qwen_base_url": DASHSCOPE_BASE_URL,
        "qwen_model": QWEN_MAX_MODEL,
        "gemma_key": OPENROUTER_GEMMA_KEY,
        "gemma_base_url": OPENROUTER_BASE_URL,
        "gemma_model": OPENROUTER_GEMMA_MODEL,
    }


def _load_debate_log() -> dict:
    if not os.path.exists(DEBATE_LOG_FILE):
        return {}
    try:
        with open(DEBATE_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_debate_log(log: dict) -> None:
    os.makedirs(os.path.dirname(DEBATE_LOG_FILE), exist_ok=True)
    with open(DEBATE_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, sort_keys=True)


def _call_openrouter(messages, api_key, model, max_tokens=600, base_url: str | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "temperature": 0.3, "max_tokens": max_tokens}
    try:
        url = base_url or _config().get("base_url") or "https://openrouter.ai/api/v1/chat/completions"
        if "openrouter.ai" in url:
            headers.update({"HTTP-Referer": "https://marketmind.pro", "X-Title": "MarketMind Pro"})
        for attempt in range(3):
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.status_code == 429 and attempt < 2:
                time.sleep(0.75 * (attempt + 1))
                continue
            break
        if response.status_code >= 400:
            return {"ok": False, "error": response.text[:300]}
        data = response.json()
        message = data["choices"][0].get("message", {})
        content = (message.get("content") or "").strip()
        if not content:
            return {"ok": False, "error": "empty model content"}
        return {"ok": True, "content": content}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _format_picks(picks: list[dict]) -> str:
    lines = []
    for i, p in enumerate(picks, 1):
        sym = p.get("symbol", "UNKNOWN")
        price = float(p.get("price", 0) or 0)
        rsi = float(p.get("rsi", 50) or 50)
        rvol = p.get("rvol", p.get("vol_ratio", "1.0"))
        adr = p.get("adr_exp", p.get("expansion_pct", 0))
        pen = float(p.get("audit_penalty", 0) or 0)
        pen_str = f" | AuditPen={pen:.1f}pts" if pen > 0 else ""
        lines.append(f"{i}. {sym}: Price={price:.1f} RSI={rsi:.1f} RVOL={rvol} ATR_Exp={adr}%{pen_str}")
    return "\n".join(lines)


def _parse_json(text: str) -> dict:
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
            pass
    return {}


def _normalize_final_vote(raw_vote: Any, picks: list[dict]) -> dict[str, str]:
    """Coerce model vote output into {SYMBOL: YES/NO} without failing the pipeline."""
    symbols = [str(p.get("symbol", "")).upper() for p in picks if p.get("symbol")]
    if isinstance(raw_vote, dict):
        normalized: dict[str, str] = {}
        for key, value in raw_vote.items():
            symbol = str(key or "").upper()
            vote = str(value or "NO").upper()
            normalized[symbol] = "YES" if vote in {"YES", "APPROVE", "BUY"} else "NO"
        return normalized

    if isinstance(raw_vote, list):
        normalized = {}
        for item in raw_vote:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).upper()
            vote = str(item.get("vote", item.get("final_vote", "NO"))).upper()
            if symbol:
                normalized[symbol] = "YES" if vote in {"YES", "APPROVE", "BUY"} else "NO"
        return normalized

    if raw_vote:
        logger.warning("Brain returned unstructured final votes; treating as unapproved")
    return {symbol: "NO" for symbol in symbols}


def gemma_challenge_review(picks: list[dict], context: str = "") -> dict[str, Any]:
    cfg = _config()
    if not cfg["gemma_key"]:
        return {"ok": False, "error": "No OpenRouter Gemma API key"}

    audit_rules_text = ""
    try:
        from modules.auditor import format_auditor_rules_for_prompt
        audit_rules_text = format_auditor_rules_for_prompt()
    except Exception as e:
        logger.debug("Auditor prompt injection skipped: %s", e)

    system_prompt = (
        "You are the independent challenger. Review Indian intraday stock candidates. "
        "You can ISSUE COMMANDS: ADD_PICK, REMOVE_PICK, ADD_WATCH. "
        "Enforce active risk rules and veto setups that violate institutional criteria. "
        "Return JSON with: verdict, picks_with_reason, commands (optional), key_concerns."
    )
    if audit_rules_text:
        system_prompt += f"\n\n{audit_rules_text}"

    picks_text = _format_picks(picks)
    user_content = f"Context: {context}\n\nPicks:\n{picks_text}\n\nReview and issue commands if needed."

    result = _call_openrouter(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        cfg["gemma_key"], cfg["gemma_model"], 400, cfg["gemma_base_url"],
    )

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Gemma failed")}

    parsed = _parse_json(result["content"])
    if not parsed:
        return {"ok": True, "verdict": "reviewed", "picks_with_reason": [{"symbol": p["symbol"], "reason": "Selected", "vote": "YES"} for p in picks[:5]], "commands": []}
    
    return {
        "ok": True,
        "verdict": parsed.get("verdict", "reviewed"),
        "picks_with_reason": parsed.get("picks_with_reason", []),
        "commands": parsed.get("commands", []),
    }


def qwen_primary_review(picks: list[dict], context: str = "") -> dict[str, Any]:
    cfg = _config()
    if not cfg["qwen_key"]:
        return {"ok": False, "error": "No Qwen API key"}

    audit_rules_text = ""
    try:
        from modules.auditor import format_auditor_rules_for_prompt
        audit_rules_text = format_auditor_rules_for_prompt()
    except Exception as e:
        logger.debug("Auditor prompt injection skipped: %s", e)

    system_prompt = (
        "You are the primary institutional analyst. Review picks and enforce institutional loss prevention rules. "
        "ISSUE COMMANDS to add/remove: ADD_PICK, REMOVE_PICK, ADD_WATCH. "
        "If a pick matches an active Auditor Failure Signature, issue REMOVE_PICK with the Rule ID. "
        "Return JSON: verdict, adjustments, commands (optional), final_vote, risk_flags."
    )
    if audit_rules_text:
        system_prompt += f"\n\n{audit_rules_text}"

    picks_text = _format_picks(picks)
    user_content = f"Context: {context}\n\nBrain 1 picks:\n{picks_text}\n\nChallenge and issue commands."

    result = _call_openrouter(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        cfg["qwen_key"], cfg["qwen_model"], 500, cfg["qwen_base_url"],
    )

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Qwen failed")}

    parsed = _parse_json(result["content"])
    if not parsed:
        return {"ok": True, "verdict": "challenged", "adjustments": [], "final_vote": {}, "commands": [], "risk_flags": []}
    
    return {
        "ok": True,
        "verdict": parsed.get("verdict", "challenged"),
        "adjustments": parsed.get("adjustments", []),
        "final_vote": parsed.get("final_vote", {}),
        "commands": parsed.get("commands", []),
        "risk_flags": parsed.get("risk_flags", [])[:3],
    }


def _execute_command(command: str, params: dict, reason: str, brain: str) -> dict:
    """Execute a command from brain."""
    try:
        from modules.brain_commands import issue_command
        
        result = issue_command(brain, command, params, reason)
        if result.get("status") == "pending":
            logger.info("Command %s is pending explicit approval from the other brain", result.get("id"))
        return result
    except Exception as e:
        logger.debug(f"Command {command}: {e}")
        return {"ok": False, "error": str(e)}


def debate_picks(draft_picks: list[dict], context: str = "", max_rounds: int = MAX_DEBATE_ROUNDS) -> tuple[list[dict], bool]:
    if not draft_picks:
        return [], False
    
    logger.info(f"=== Dual-Brain Debate: {len(draft_picks)} picks ===")
    
    brain1 = qwen_primary_review(draft_picks, context)
    if not brain1.get("ok"):
        return [], False
    
    brain1_votes = _normalize_final_vote(brain1.get("final_vote", {}), draft_picks)
    brain1_picks = []
    if not brain1_picks:
        brain1_picks = [
            {
                "symbol": p["symbol"],
                "reason": "Qwen primary approved" if brain1_votes.get(p["symbol"], "NO") == "YES" else "Qwen primary rejected",
                "vote": brain1_votes.get(p["symbol"], "NO"),
            }
            for p in draft_picks[:5]
        ]
    
    logger.info(f"Brain 1 Qwen primary: {len(brain1_picks)} reviewed")
    
    brain2 = gemma_challenge_review(draft_picks, context)
    if not brain2.get("ok"):
        return [], False
    
    brain2_picks = brain2.get("picks_with_reason", [])
    brain2_votes = {str(p.get("symbol", "")).upper(): str(p.get("vote", "NO")).upper() for p in brain2_picks}
    logger.info(f"Brain 2 Gemma challenger: verdict={brain2.get('verdict')}")
    
    # Process commands from Brain 1
    for cmd in brain1.get("commands", []):
        _execute_command(cmd.get("command", ""), cmd.get("params", {}), cmd.get("reason", ""), "qwen")
    
    # Process commands from Brain 2
    for cmd in brain2.get("commands", []):
        _execute_command(cmd.get("command", ""), cmd.get("params", {}), cmd.get("reason", ""), "gemma")
    
    # Build approved picks
    approved = []
    rejected = []
    
    for p in draft_picks:
        sym = p["symbol"]
        g1_vote = "YES"
        for b1p in brain1_picks:
            if b1p.get("symbol") == sym:
                g1_vote = b1p.get("vote", "NO")
                break
        g2_vote = brain2_votes.get(sym, "NO")
        
        if g1_vote == "YES" and g2_vote == "YES":
            reason = "Approved by both brains"
            for b1p in brain1_picks:
                if b1p.get("symbol") == sym:
                    reason = b1p.get("reason", "Approved")
                    break
            approved.append({**p, "reason": reason, "brain1_vote": g1_vote, "brain2_vote": g2_vote})
        else:
            rejected.append(sym)
    
    both_agreed = bool(approved) and len(approved) == len(draft_picks)
    
    # Log
    debate_log = _load_debate_log()
    today = today_ist_str()
    if today not in debate_log:
        debate_log[today] = []
    debate_log[today].append({
        "timestamp": now_ist().isoformat(timespec="seconds"),
        "approved": [p["symbol"] for p in approved],
        "rejected": rejected,
        "both_agreed": both_agreed,
    })
    _save_debate_log(debate_log)
    
    logger.info(f"Debate: {len(approved)} approved, {len(rejected)} rejected, both_agreed={both_agreed}")
    
    return approved[:5], both_agreed


def debate_patterns(winners: list[dict], patterns: list[dict]) -> tuple[list[dict], bool]:
    logger.info(f"=== Pattern Debate: {len(patterns)} patterns ===")
    
    cfg = _config()
    
    if cfg["qwen_key"]:
        system_prompt = "You are Brain 1 (Qwen primary). Pick patterns. Can ISSUE: UPDATE_PATTERN, ADJUST_WEIGHT."
        result = _call_openrouter(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Winners: {[w.get('symbol') for w in winners[:10]]}\nPatterns: {patterns}"}],
            cfg["qwen_key"], cfg["qwen_model"], 300, cfg["qwen_base_url"],
        )
        if result.get("ok"):
            parsed = _parse_json(result["content"])
            for cmd in parsed.get("commands", []):
                _execute_command(cmd.get("command", ""), cmd.get("params", {}), cmd.get("reason", ""), "qwen")
    
    if cfg["gemma_key"]:
        system_prompt = "You are Brain 2 (Gemma challenger). Challenge patterns. Can ISSUE commands."
        result = _call_openrouter(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Patterns: {patterns}"}],
            cfg["gemma_key"], cfg["gemma_model"], 300, cfg["gemma_base_url"],
        )
        if result.get("ok"):
            parsed = _parse_json(result["content"])
            for cmd in parsed.get("commands", []):
                _execute_command(cmd.get("command", ""), cmd.get("params", {}), cmd.get("reason", ""), "gemma")
    
    return patterns, True


def test_dual_brain() -> dict[str, Any]:
    cfg = _config()
    qwen_status = "error"
    if cfg["qwen_key"]:
        r = _call_openrouter([{"role": "system", "content": "Reply only: OK"}, {"role": "user", "content": "Test"}], cfg["qwen_key"], cfg["qwen_model"], 10, cfg["qwen_base_url"])
        qwen_status = "ok" if r.get("ok") else "error"
    
    gemma_status = "error"
    if cfg["gemma_key"]:
        r = _call_openrouter([{"role": "system", "content": "Reply only: OK"}, {"role": "user", "content": "Test"}], cfg["gemma_key"], cfg["gemma_model"], 10, cfg["gemma_base_url"])
        gemma_status = "ok" if r.get("ok") else "error"
    
    return {"qwen": qwen_status, "gemma": gemma_status, "both_ready": qwen_status == "ok" and gemma_status == "ok"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = test_dual_brain()
    print(f"Qwen: {result['qwen']}, Gemma: {result['gemma']}, Both: {result['both_ready']}")
