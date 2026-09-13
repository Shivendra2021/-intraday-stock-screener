# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.

"""
dual_brain.py — Dual-Brain Debate + Command System

Brain 1 (GPT): Primary analyst
Brain 2 (Grok): Challenger / fallback reviewer
Both can ISSUE COMMANDS - executed only when BOTH agree
"""

from __future__ import annotations
import datetime
import json
import logging
import os
from typing import Any

import requests

from modules.time_utils import now_ist, today_ist_str

logger = logging.getLogger(__name__)

DEBATE_LOG_FILE = "data/dual_brain_debates.json"
MAX_DEBATE_ROUNDS = 3


def _config() -> dict:
    from config import (
        OPENROUTER_GROK_KEY, OPENROUTER_GPT_KEY, OPENROUTER_BASE_URL,
        GROK_MODEL, GPT_MODEL,
    )
    return {
        "grok_key": OPENROUTER_GROK_KEY,
        "gpt_key": OPENROUTER_GPT_KEY,
        "base_url": OPENROUTER_BASE_URL,
        "grok_model": GROK_MODEL,
        "gpt_model": GPT_MODEL,
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
        "HTTP-Referer": "https://marketmind.pro",
        "X-Title": "MarketMind Pro",
    }
    payload = {"model": model, "messages": messages, "temperature": 0.3, "max_tokens": max_tokens}
    try:
        url = base_url or _config().get("base_url") or "https://openrouter.ai/api/v1/chat/completions"
        response = requests.post(url, headers=headers, json=payload, timeout=60)
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
            vote = str(value or "YES").upper()
            normalized[symbol] = "NO" if vote in {"NO", "REJECT", "REMOVE", "SELL"} else "YES"
        return normalized

    if isinstance(raw_vote, list):
        normalized = {}
        for item in raw_vote:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).upper()
            vote = str(item.get("vote", item.get("final_vote", "YES"))).upper()
            if symbol:
                normalized[symbol] = "NO" if vote in {"NO", "REJECT", "REMOVE", "SELL"} else "YES"
        return normalized

    if raw_vote:
        logger.warning("Brain 2 returned unstructured final_vote=%r; defaulting votes to YES", raw_vote)
    return {symbol: "YES" for symbol in symbols}


def brain1_grok_review(picks: list[dict], context: str = "") -> dict[str, Any]:
    cfg = _config()
    if not cfg["grok_key"]:
        return {"ok": False, "error": "No Grok API key"}

    audit_rules_text = ""
    try:
        from modules.auditor import format_auditor_rules_for_prompt
        audit_rules_text = format_auditor_rules_for_prompt()
    except Exception as e:
        logger.debug("Auditor prompt injection skipped: %s", e)

    system_prompt = (
        "You are Brain 1 (Primary Institutional Analyst). Review Indian intraday stock candidates. "
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
        cfg["grok_key"], cfg["grok_model"], 400, cfg["base_url"],
    )

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Grok failed")}

    parsed = _parse_json(result["content"])
    if not parsed:
        return {"ok": True, "verdict": "reviewed", "picks_with_reason": [{"symbol": p["symbol"], "reason": "Selected", "vote": "YES"} for p in picks[:5]], "commands": []}
    
    return {
        "ok": True,
        "verdict": parsed.get("verdict", "reviewed"),
        "picks_with_reason": parsed.get("picks_with_reason", []),
        "commands": parsed.get("commands", []),
    }


def brain2_gpt_review(picks: list[dict], context: str = "") -> dict[str, Any]:
    cfg = _config()
    if not cfg["gpt_key"]:
        return {"ok": False, "error": "No GPT API key"}

    audit_rules_text = ""
    try:
        from modules.auditor import format_auditor_rules_for_prompt
        audit_rules_text = format_auditor_rules_for_prompt()
    except Exception as e:
        logger.debug("Auditor prompt injection skipped: %s", e)

    system_prompt = (
        "You are Brain 2 (Challenger & Risk Committee). Challenge weak picks and enforce institutional loss prevention rules. "
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
        cfg["gpt_key"], cfg["gpt_model"], 500, cfg["base_url"],
    )

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "GPT failed")}

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
    if len(draft_picks) < 3:
        return draft_picks, True
    
    logger.info(f"=== Dual-Brain Debate: {len(draft_picks)} picks ===")
    
    brain1 = brain2_gpt_review(draft_picks, context)
    if not brain1.get("ok"):
        return draft_picks, False
    
    brain1_votes = _normalize_final_vote(brain1.get("final_vote", {}), draft_picks)
    brain1_picks = []
    if not brain1_picks:
        brain1_picks = [
            {
                "symbol": p["symbol"],
                "reason": "GPT primary approved" if brain1_votes.get(p["symbol"], "YES") == "YES" else "GPT primary rejected",
                "vote": brain1_votes.get(p["symbol"], "YES"),
            }
            for p in draft_picks[:5]
        ]
    
    logger.info(f"Brain 1 GPT primary: {len(brain1_picks)} reviewed")
    
    brain2 = brain1_grok_review(draft_picks, context)
    if not brain2.get("ok"):
        brain2 = {"ok": True, "verdict": "grok_unavailable", "picks_with_reason": [], "commands": []}
    
    brain2_picks = brain2.get("picks_with_reason", [])
    brain2_votes = {str(p.get("symbol", "")).upper(): str(p.get("vote", "YES")).upper() for p in brain2_picks}
    logger.info(f"Brain 2 Grok challenger: verdict={brain2.get('verdict')}")
    
    # Process commands from Brain 1
    for cmd in brain1.get("commands", []):
        _execute_command(cmd.get("command", ""), cmd.get("params", {}), cmd.get("reason", ""), "gpt")
    
    # Process commands from Brain 2
    for cmd in brain2.get("commands", []):
        _execute_command(cmd.get("command", ""), cmd.get("params", {}), cmd.get("reason", ""), "grok")
    
    # Build approved picks
    approved = []
    rejected = []
    
    for p in draft_picks:
        sym = p["symbol"]
        g1_vote = "YES"
        for b1p in brain1_picks:
            if b1p.get("symbol") == sym:
                g1_vote = b1p.get("vote", "YES")
                break
        g2_vote = brain2_votes.get(sym, "YES")
        
        if g1_vote == "YES" and g2_vote == "YES":
            reason = "Approved by both brains"
            for b1p in brain1_picks:
                if b1p.get("symbol") == sym:
                    reason = b1p.get("reason", "Approved")
                    break
            approved.append({**p, "reason": reason, "brain1_vote": g1_vote, "brain2_vote": g2_vote})
        else:
            rejected.append(sym)
    
    both_agreed = len(approved) >= 3
    
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
    
    if cfg["grok_key"]:
        system_prompt = "You are Brain 1. Pick patterns. Can ISSUE: UPDATE_PATTERN, ADJUST_WEIGHT."
        result = _call_openrouter(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Winners: {[w.get('symbol') for w in winners[:10]]}\nPatterns: {patterns}"}],
            cfg["grok_key"], cfg["grok_model"], 300, cfg["base_url"],
        )
        if result.get("ok"):
            parsed = _parse_json(result["content"])
            for cmd in parsed.get("commands", []):
                _execute_command(cmd.get("command", ""), cmd.get("params", {}), cmd.get("reason", ""), "grok")
    
    if cfg["gpt_key"]:
        system_prompt = "You are Brain 2. Challenge patterns. Can ISSUE commands."
        result = _call_openrouter(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Patterns: {patterns}"}],
            cfg["gpt_key"], cfg["gpt_model"], 300, cfg["base_url"],
        )
        if result.get("ok"):
            parsed = _parse_json(result["content"])
            for cmd in parsed.get("commands", []):
                _execute_command(cmd.get("command", ""), cmd.get("params", {}), cmd.get("reason", ""), "gpt")
    
    return patterns, True


def test_dual_brain() -> dict[str, Any]:
    cfg = _config()
    grok_status = "error"
    if cfg["grok_key"]:
        r = _call_openrouter([{"role": "system", "content": "OK"}, {"role": "user", "content": "Test"}], cfg["grok_key"], cfg["grok_model"], 10, cfg["base_url"])
        grok_status = "ok" if r.get("ok") else "error"
    
    gpt_status = "error"
    if cfg["gpt_key"]:
        r = _call_openrouter([{"role": "system", "content": "OK"}, {"role": "user", "content": "Test"}], cfg["gpt_key"], cfg["gpt_model"], 10, cfg["base_url"])
        gpt_status = "ok" if r.get("ok") else "error"
    
    return {"grok": grok_status, "gpt": gpt_status, "both_ready": grok_status == "ok" and gpt_status == "ok"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = test_dual_brain()
    print(f"Grok: {result['grok']}, GPT: {result['gpt']}, Both: {result['both_ready']}")
