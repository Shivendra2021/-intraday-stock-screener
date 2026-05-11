# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
brain_commands.py — Dual-Brain Command Authority System

Both brains can issue commands to the system:
- QUERY: Ask the system to do something
- ADD_STOCK: Add a stock to watchlist
- REMOVE_STOCK: Remove a stock from picks
- UPDATE_PATTERN: Update pattern scoring
- ADJUST_WEIGHTS: Adjust stock weights
- EXECUTE: Execute a system action
- ALERT: Send alert to Telegram

Commands are executed ONLY when both brains agree.
"""

from __future__ import annotations
import datetime
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

COMMANDS_LOG = "data/brain_commands.json"
PENDING_COMMANDS = "data/pending_commands.json"


def _init_command_store() -> None:
    """Initialize command storage."""
    os.makedirs("data", exist_ok=True)
    for f in [COMMANDS_LOG, PENDING_COMMANDS]:
        if not os.path.exists(f):
            with open(f, "w") as fp:
                json.dump({"commands": [], "updated": None}, fp)


def _load_commands() -> dict:
    """Load executed commands."""
    _init_command_store()
    try:
        with open(COMMANDS_LOG, "r") as f:
            return json.load(f)
    except Exception:
        return {"commands": [], "updated": None}


def _save_commands(data: dict) -> None:
    """Save executed commands."""
    with open(COMMANDS_LOG, "w") as f:
        json.dump(data, f, indent=2)


def _load_pending() -> list:
    """Load pending commands."""
    _init_command_store()
    try:
        with open(PENDING_COMMANDS, "r") as f:
            return json.load(f).get("commands", [])
    except Exception:
        return []


def _save_pending(commands: list) -> None:
    """Save pending commands."""
    _init_command_store()
    with open(PENDING_COMMANDS, "w") as f:
        json.dump({"commands": commands, "updated": datetime.datetime.now().isoformat()}, f)


# ============================================================================
# Command Types
# ============================================================================

VALID_COMMANDS = {
    "QUERY": "Query system for information",
    "ADD_WATCH": "Add stock to watchlist",
    "REMOVE_WATCH": "Remove stock from watchlist",
    "ADD_PICK": "Add stock to today's picks",
    "REMOVE_PICK": "Remove stock from today's picks",
    "UPDATE_PATTERN": "Update pattern scoring",
    "ADJUST_WEIGHT": "Adjust stock/scoring weight",
    "SEND_ALERT": "Send alert to Telegram",
    "PAUSE_SCAN": "Pause market scanning",
    "RESUME_SCAN": "Resume market scanning",
    "FORCE_PICK": "Force pick specific stock",
}


# ============================================================================
# Brain Command Issuance
# ============================================================================

def issue_command(
    brain: str,
    command: str,
    params: dict[str, Any],
    reason: str = "",
) -> dict[str, Any]:
    """
    Brain issues a command.
    
    Args:
        brain: "grok" or "gpt"
        command: Command type (see VALID_COMMANDS)
        params: Command parameters
        reason: Why this command is being issued
    
    Returns:
        Command record with id
    """
    _init_command_store()
    
    if command not in VALID_COMMANDS:
        return {"ok": False, "error": f"Invalid command: {command}"}
    
    cmd_id = f"{brain}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{command}"
    
    cmd_record = {
        "id": cmd_id,
        "brain": brain,
        "command": command,
        "params": params,
        "reason": reason,
        "timestamp": datetime.datetime.now().isoformat(),
        "status": "pending",
        "votes": {brain: "YES"},
    }
    
    # Save as pending
    pending = _load_pending()
    pending.append(cmd_record)
    _save_pending(pending)
    
    logger.info(f"Brain [{brain}] issued command: {command} -> {params}")
    
    # Check if both brains agree
    return check_command_approval(cmd_id)


def vote_command(
    cmd_id: str,
    brain: str,
    vote: str,
    reason: str = "",
) -> dict[str, Any]:
    """
    Second brain votes on pending command.
    
    Args:
        cmd_id: Command ID
        brain: "grok" or "gpt"
        vote: "YES" or "NO"
        reason: Reasoning for vote
    
    Returns:
        Approval result
    """
    pending = _load_pending()
    
    cmd = None
    for c in pending:
        if c.get("id") == cmd_id:
            cmd = c
            break
    
    if not cmd:
        return {"ok": False, "error": "Command not found"}
    
    if brain == cmd.get("brain"):
        return {"ok": False, "error": "Cannot vote on own command"}
    
    # Record vote
    cmd.setdefault("votes", {})[brain] = vote
    cmd["vote_reason"] = reason
    cmd["status"] = "voting"
    
    _save_pending(pending)
    
    # Check if both agree
    return check_command_approval(cmd_id)


def check_command_approval(cmd_id: str) -> dict[str, Any]:
    """
    Check if command is approved (both brains voted YES).
    """
    pending = _load_pending()
    
    cmd = None
    for c in pending:
        if c.get("id") == cmd_id:
            cmd = c
            break
    
    if not cmd:
        return {"ok": False, "error": "Command not found"}
    
    votes = cmd.get("votes", {})
    
    # Need YES from both
    if "grok" not in votes or "gpt" not in votes:
        return {"ok": True, "status": "pending", "votes": votes}
    
    if votes.get("grok") == "YES" and votes.get("gpt") == "YES":
        # Execute command
        return execute_command(cmd_id)
    
    return {"ok": True, "status": "rejected", "votes": votes}


def execute_command(cmd_id: str) -> dict[str, Any]:
    """
    Execute approved command.
    """
    pending = _load_pending()
    
    cmd = None
    for c in pending:
        if c.get("id") == cmd_id:
            cmd = c
            break
    
    if not cmd:
        return {"ok": False, "error": "Command not found"}
    
    command = cmd.get("command")
    params = cmd.get("params")
    
    result = {"ok": False, "error": "Not implemented"}
    
    # Execute based on command type
    try:
        if command == "ADD_WATCH":
            result = _add_to_watch(params)
        elif command == "REMOVE_WATCH":
            result = _remove_from_watch(params)
        elif command == "ADD_PICK":
            result = _add_pick(params)
        elif command == "REMOVE_PICK":
            result = _remove_pick(params)
        elif command == "UPDATE_PATTERN":
            result = _update_pattern(params)
        elif command == "ADJUST_WEIGHT":
            result = _adjust_weight(params)
        elif command == "SEND_ALERT":
            result = _send_alert(params)
        elif command == "FORCE_PICK":
            result = _force_pick(params)
        else:
            result = {"ok": True, "message": f"Command {command} is informational only"}
    
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    
    # Update command status
    cmd["status"] = "executed" if result.get("ok") else "failed"
    cmd["result"] = result
    cmd["executed_at"] = datetime.datetime.now().isoformat()
    
    # Remove from pending, add to log
    pending = [c for c in pending if c.get("id") != cmd_id]
    _save_pending(pending)
    
    # Save to log
    log = _load_commands()
    log["commands"].append(cmd)
    log["updated"] = datetime.datetime.now().isoformat()
    _save_commands(log)
    
    logger.info(f"Command executed: {cmd_id} -> {result}")
    
    return result


def _add_to_watch(params: dict) -> dict:
    """Add stock to watchlist."""
    symbol = params.get("symbol")
    if not symbol:
        return {"ok": False, "error": "Symbol required"}
    
    # Add to watchlist file
    watch_file = "data/watchlist.json"
    try:
        with open(watch_file, "r") as f:
            watch = json.load(f)
    except Exception:
        watch = {"symbols": []}
    
    if symbol not in watch.get("symbols", []):
        watch.setdefault("symbols", []).append(symbol)
        with open(watch_file, "w") as f:
            json.dump(watch, f, indent=2)
    
    return {"ok": True, "message": f"Added {symbol} to watchlist"}


def _remove_from_watch(params: dict) -> dict:
    """Remove stock from watchlist."""
    symbol = params.get("symbol")
    if not symbol:
        return {"ok": False, "error": "Symbol required"}
    
    watch_file = "data/watchlist.json"
    try:
        with open(watch_file, "r") as f:
            watch = json.load(f)
        
        symbols = watch.get("symbols", [])
        if symbol in symbols:
            symbols.remove(symbol)
            with open(watch_file, "w") as f:
                json.dump(watch, f, indent=2)
        
        return {"ok": True, "message": f"Removed {symbol} from watchlist"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _add_pick(params: dict) -> dict:
    """Add to today's picks."""
    return _add_to_watch(params)


def _remove_pick(params: dict) -> dict:
    """Remove from today's picks."""
    return _remove_from_watch(params)


def _update_pattern(params: dict) -> dict:
    """Update pattern scoring."""
    from modules.pattern_learner import apply_patterns_to_scoring
    
    pattern = params.get("pattern", {})
    patterns = [pattern] if pattern else []
    
    result = apply_patterns_to_scoring(patterns)
    return result


def _adjust_weight(params: dict) -> dict:
    """Adjust scoring weights."""
    weight_file = "data/scoring_weights.json"
    
    weight_type = params.get("type")
    value = params.get("value")
    
    try:
        with open(weight_file, "r") as f:
            weights = json.load(f)
    except Exception:
        weights = {}
    
    weights[weight_type] = value
    weights["updated"] = datetime.datetime.now().isoformat()
    
    with open(weight_file, "w") as f:
        json.dump(weights, f, indent=2)
    
    return {"ok": True, "message": f"Adjusted {weight_type} to {value}"}


def _send_alert(params: dict) -> dict:
    """Send alert to Telegram."""
    message = params.get("message", "")
    if not message:
        return {"ok": False, "error": "Message required"}
    
    try:
        from modules.alerts import _send
        _send(message)
        return {"ok": True, "message": "Alert sent"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _force_pick(params: dict) -> dict:
    """Force pick a stock."""
    return _add_pick(params)


def get_pending_commands() -> list:
    """Get all pending commands."""
    return _load_pending()


def get_command_log(limit: int = 50) -> list:
    """Get executed command log."""
    log = _load_commands()
    return log.get("commands", [])[-limit:]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test
    print("Testing brain commands...")
    
    # Grok issues a command
    result = issue_command("grok", "ADD_WATCH", {"symbol": "RELIANCE"}, "Strong momentum")
    print(f"Grok command: {result}")
    
    # GPT votes
    if result.get("status") == "pending":
        result = vote_command(result.get("id"), "gpt", "YES", "Agrees with Grok")
        print(f"GPT vote: {result}")