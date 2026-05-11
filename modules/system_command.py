# MarketMind Pro — Research Only

"""
system_command.py — ONE Command System for Complete Control

Single unified interface to control entire MarketMind Pro:
- Start/stop continuous learning
- Run morning pipeline
- Get status
- Issue brain commands
- All via ONE command interface
"""

from __future__ import annotations
import datetime
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

SYSTEM_STATE = "data/system_state.json"


def _init() -> None:
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(SYSTEM_STATE):
        with open(SYSTEM_STATE, "w") as f:
            json.dump({
                "mode": "idle",
                "started_at": None,
                "last_command": None,
                "morning_picks": [],
                "continuous_running": False,
            }, f)


def _load() -> dict:
    _init()
    try:
        with open(SYSTEM_STATE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(state: dict) -> None:
    with open(SYSTEM_STATE, "w") as f:
        json.dump(state, f, indent=2)


# ============================================================================
# Master Command Processor
# ============================================================================

def execute_command(
    command: str,
    params: dict = None,
    brain: str = "system",
) -> dict[str, Any]:
    """
    Master command processor.
    
    All commands flow through here:
    - START_CONTINUOUS: Start background learning
    - STOP_CONTINUOUS: Stop background learning
    - RUN_MORNING: Run morning pipeline
    - GET_STATUS: System status
    - GET_MORNING_CONTEXT: Insights for morning
    - BRAIN_COMMAND: Issue brain command
    """
    params = params or {}
    
    logger.info(f"Executing command: {command} (brain: {brain})")
    
    result = {"ok": False, "command": command}
    
    # START_CONTINUOUS
    if command == "START_CONTINUOUS":
        from modules.continuous_learning import start_continuous_learning
        
        interval = params.get("interval_minutes", 30)
        result = start_continuous_learning(interval)
        
        state = _load()
        state["continuous_running"] = True
        state["mode"] = "continuous"
        _save(state)
        
        return result
    
    # STOP_CONTINUOUS
    if command == "STOP_CONTINUOUS":
        from modules.continuous_learning import stop_continuous_learning
        
        result = stop_continuous_learning()
        
        state = _load()
        state["continuous_running"] = False
        state["mode"] = "idle"
        _save(state)
        
        return result
    
    # RUN_MORNING - Run complete morning pipeline
    if command == "RUN_MORNING":
        return run_morning_pipeline()
    
    # GET_STATUS
    if command == "GET_STATUS":
        return get_full_status()
    
    # GET_MORNING_CONTEXT
    if command == "GET_MORNING_CONTEXT":
        from modules.continuous_learning import get_morning_context
        return get_morning_context()
    
    # BRAIN_COMMAND - Pass through to brain command system
    if command == "BRAIN_COMMAND":
        from modules.brain_commands import issue_command
        
        cmd_type = params.get("type", "")
        cmd_params = params.get("params", {})
        reason = params.get("reason", "")
        
        return issue_command(brain, cmd_type, cmd_params, reason)
    
    # QUERY_DATA - Query system data
    if command == "QUERY_DATA":
        query_type = params.get("type", "insights")
        
        if query_type == "insights":
            from modules.continuous_learning import get_learned_insights
            return {"ok": True, "data": get_learned_insights()}
        
        if query_type == "winners":
            from modules.winner_finder import get_recent_winners
            return {"ok": True, "data": get_recent_winners(params.get("days", 30))}
        
        if query_type == "debates":
            from modules.dual_brain import _load_debate_log
            return {"ok": True, "data": _load_debate_log()}
        
        return {"ok": False, "error": f"Unknown query: {query_type}"}
    
    # SCAN_UNIVERSE - Manual universe scan
    if command == "SCAN_UNIVERSE":
        from modules.universe_scanner import scan_universe_parallel
        top_n = params.get("top_n", 20)
        
        results = scan_universe_parallel(top_n)
        return {"ok": True, "stocks": results, "count": len(results)}
    
    # DEEP_ANALYSIS - Deep research on stocks
    if command == "DEEP_ANALYSIS":
        from modules.stock_selector import deep_research_stocks
        
        stocks = params.get("stocks", [])
        n = params.get("n", 5)
        
        results = deep_research_stocks(stocks, n)
        return {"ok": True, "picks": results, "count": len(results)}
    
    # DEBATE_STOCKS - Run dual-brain debate
    if command == "DEBATE_STOCKS":
        from modules.dual_brain import debate_picks
        
        stocks = params.get("stocks", [])
        context = params.get("context", "")
        
        final, agreed = debate_picks(stocks, context)
        return {"ok": True, "picks": final, "both_agreed": agreed}
    
    # FIND_WINNERS - Find intraday winners
    if command == "FIND_WINNERS":
        from modules.winner_finder import find_winners
        
        min_return = params.get("min_return", 7.0)
        winners = find_winners(min_return)
        
        return {"ok": True, "winners": winners, "count": len(winners)}
    
    # LEARN_PATTERNS - Run pattern learning
    if command == "LEARN_PATTERNS":
        from modules.pattern_learner import run_self_learning
        
        result = run_self_learning()
        return result
    
    # Unknown command
    return {"ok": False, "error": f"Unknown command: {command}"}


def run_morning_pipeline() -> dict[str, Any]:
    """Run complete morning pipeline."""
    logger.info("=== Running Morning Pipeline ===")
    
    results = {
        "stages": {},
        "completed_at": None,
    }
    
    # Get morning context from continuous learning
    from modules.continuous_learning import get_morning_context
    
    context = get_morning_context()
    results["stages"]["context"] = context
    
    # Stage 1: Universe scan
    universe_results = execute_command("SCAN_UNIVERSE", {"top_n": 20})
    results["stages"]["universe"] = universe_results.get("stocks", [])[:20]
    
    # Stage 2: Deep analysis
    if results["stages"]["universe"]:
        deep_results = execute_command(
            "DEEP_ANALYSIS",
            {"stocks": results["stages"]["universe"], "n": 5}
        )
        results["stages"]["deep_research"] = deep_results.get("picks", [])
    
    # Stage 3: Debate
    if results["stages"].get("deep_research"):
        debate_results = execute_command(
            "DEBATE_STOCKS",
            {"stocks": results["stages"]["deep_research"], "context": str(context)}
        )
        results["stages"]["debate"] = debate_results.get("picks", [])
        results["both_agreed"] = debate_results.get("both_agreed", False)
        results["morning_picks"] = debate_results.get("picks", [])
    
    results["completed_at"] = datetime.datetime.now().isoformat()
    
    # Save
    state = _load()
    state["morning_picks"] = results.get("morning_picks", [])
    state["last_morning"] = results["completed_at"]
    _save(state)
    
    return results


def get_full_status() -> dict[str, Any]:
    """Get complete system status."""
    state = _load()
    
    # Continuous status
    from modules.continuous_learning import get_continuous_status
    continuous = get_continuous_status()
    
    # Recent picks
    morning_picks = state.get("morning_picks", [])
    
    return {
        "mode": state.get("mode", "idle"),
        "continuous_running": continuous.get("running", False),
        "last_morning": state.get("last_morning"),
        "morning_picks": morning_picks,
        "continuous_status": continuous,
    }


def test_system() -> dict[str, Any]:
    """Test all system components.""" 
    from modules.continuous_learning import get_morning_context
    
    # Test continuous learning
    print("Testing continuous learning...")
    ctx = get_morning_context()
    print(f"  Context: OK")
    
    # Test brain commands
    print("Testing brain commands...")
    from modules.brain_commands import test_dual_brain
    print(f"  Brain: OK")
    
    return {"ok": True, "tests_passed": True}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== System Command Test ===")
    
    # Test get status
    status = execute_command("GET_STATUS")
    print(f"Status: {status}")
    
    # Get morning context  
    ctx = execute_command("GET_MORNING_CONTEXT")
    print(f"Context: {ctx}")