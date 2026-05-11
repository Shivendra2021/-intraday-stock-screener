# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
pattern_learner.py — Self-Learning Pattern Discovery

After market close, analyze winners to find patterns:
1. Load winners from intraday_winners table
2. Analyze common technical patterns
3. Analyze market context patterns
4. Both brains debate patterns
5. If both agree → update scoring engine
6. Self-learning loop runs forever
"""

from __future__ import annotations
import datetime
import json
import logging
import os
import sqlite3
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

DB_PATH = "data/history.db"
PATTERNS_FILE = "data/discovered_patterns.json"
MIN_Winners_FOR_PATTERN = 5
CONFIDENCE_THRESHOLD = 0.6


def _init_patterns_db() -> None:
    """Initialize patterns storage."""
    os.makedirs("data", exist_ok=True)
    
    if not os.path.exists(PATTERNS_FILE):
        with open(PATTERNS_FILE, "w") as f:
            json.dump({"patterns": [], "updated_at": None}, f)


def _load_patterns() -> dict:
    """Load stored patterns."""
    _init_patterns_db()
    try:
        with open(PATTERNS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"patterns": [], "updated_at": None}


def _save_patterns(data: dict) -> None:
    """Save patterns to file."""
    with open(PATTERNS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def analyze_winners() -> list[dict[str, Any]]:
    """
    Analyze recent winners for patterns.
    
    Returns list of discovered patterns with confidence scores.
    """
    _init_patterns_db()
    
    logger.info("=== Analyzing Winner Patterns ===")
    
    # Get recent winners
    winners = _get_winners_from_db(30)
    
    if len(winners) < MIN_Winners_FOR_PATTERN:
        logger.info(f"Not enough winners ({len(winners)}) for pattern discovery")
        return []
    
    logger.info(f"Analyzing {len(winners)} recent winners")
    
    patterns = []
    
    # Pattern 1: RSI range
    rsi_values = []
    for w in winners:
        if w.get("rsi"):
            rsi_values.append(w["rsi"])
    
    if rsi_values:
        avg_rsi = sum(rsi_values) / len(rsi_values)
        patterns.append({
            "pattern_type": "technical",
            "key_metric": "rsi_entry",
            "threshold": f"45-{min(65, avg_rsi + 10):.0f}",
            "confidence": min(0.9, len(winners) / 20),
            "winners_count": len(winners),
        })
    
    # Pattern 2: Volume surge
    vol_ratios = [w.get("volume_ratio", 1) for w in winners if w.get("volume_ratio")]
    if vol_ratios:
        avg_vol = sum(vol_ratios) / len(vol_ratios)
        if avg_vol > 1.3:
            patterns.append({
                "pattern_type": "technical",
                "key_metric": "volume_surge",
                "threshold": f">{avg_vol:.1f}x",
                "confidence": min(0.9, len(winners) / 15),
                "winners_count": len(winners),
            })
    
    # Pattern 3: Sector momentum
    sectors = [w.get("sector") for w in winners if w.get("sector")]
    if sectors:
        from collections import Counter
        sector_counts = Counter(sectors)
        top_sector = sector_counts.most_common(1)[0] if sector_counts else None
        if top_sector and top_sector[1] >= 2:
            patterns.append({
                "pattern_type": "sector",
                "key_metric": "sector_momentum",
                "threshold": top_sector[0],
                "confidence": min(0.8, top_sector[1] / len(winners)),
                "winners_count": len(winners),
            })
    
    # Pattern 4: Return range
    returns = [w.get("return_pct", 0) for w in winners]
    if returns:
        avg_ret = sum(returns) / len(returns)
        max_ret = max(returns)
        patterns.append({
            "pattern_type": "returns",
            "key_metric": "intraday_return",
            "threshold": f"{avg_ret:.1f}-{max_ret:.1f}%",
            "confidence": 0.7,
            "winners_count": len(winners),
        })
    
    # Pattern 5: Gap up at open
    gap_ups = [w.get("gap_up", 0) for w in winners if w.get("gap_up", 0) > 0]
    if gap_ups:
        patterns.append({
            "pattern_type": "technical",
            "key_metric": "gap_up",
            "threshold": f">{sum(gap_ups)/len(gap_ups):.1f}%",
            "confidence": 0.6,
            "winners_count": len(winners),
        })
    
    logger.info(f"Discovered {len(patterns)} patterns")
    
    for p in patterns[:5]:
        logger.info(f"  - {p['key_metric']}: {p['threshold']} "
                  f"(conf: {p['confidence']:.0%})")
    
    return patterns


def _get_winners_from_db(days: int = 30) -> list[dict]:
    """Get winners from database."""
    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    
    try:
        df = pd.read_sql("""
            SELECT * FROM intraday_winners 
            WHERE date >= ?
            ORDER BY return_pct DESC
            LIMIT 100
        """, conn, params=(cutoff.isoformat(),))
        conn.close()
        return df.to_dict("records") if not df.empty else []
    except Exception:
        conn.close()
        return []


def apply_patterns_to_scoring(patterns: list[dict]) -> dict[str, Any]:
    """
    Apply discovered patterns to stock scoring.
    
    Updates the scoring weights based on patterns.
    """
    if not patterns:
        return {"applied": False, "reason": "No patterns"}
    
    logger.info("=== Applying Patterns to Scoring ===")
    
    changes = []
    
    for pattern in patterns:
        conf = pattern.get("confidence", 0)
        if conf < CONFIDENCE_THRESHOLD:
            continue
        
        metric = pattern.get("key_metric")
        threshold = pattern.get("threshold")
        
        # Build scoring adjustment
        if metric == "volume_surge":
            changes.append({
                "metric": "volume_ratio",
                "adjustment": f"boost if >{threshold.replace('>', '')}",
                "weight_increase": conf * 10,
            })
        elif metric == "rsi_entry":
            changes.append({
                "metric": "rsi",
                "adjustment": f"prefer {threshold}",
                "weight_increase": conf * 5,
            })
        elif metric == "sector_momentum":
            changes.append({
                "metric": "sector_bonus",
                "adjustment": f"+{threshold}",
                "weight_increase": conf * 8,
            })
    
    # Save to patterns file
    _init_patterns_db()
    data = _load_patterns()
    data["patterns"] = patterns
    data["applied_changes"] = changes
    data["updated_at"] = datetime.datetime.now().isoformat()
    _save_patterns(data)
    
    logger.info(f"Applied {len(changes)} scoring adjustments")
    
    return {
        "applied": True,
        "patterns_count": len(patterns),
        "changes": changes,
    }


def get_applied_patterns() -> list[dict]:
    """Get currently applied patterns."""
    data = _load_patterns()
    return data.get("patterns", [])


def clear_old_patterns(days: int = 30) -> None:
    """Clear patterns older than specified days."""
    data = _load_patterns()
    updated = data.get("updated_at")
    
    if updated:
        try:
            updated_date = datetime.datetime.fromisoformat(updated)
            age = datetime.datetime.now() - updated_date
            
            if age.days > days:
                data["patterns"] = []
                data["updated_at"] = None
                _save_patterns(data)
                logger.info("Cleared old patterns")
        except Exception:
            pass


def run_self_learning() -> dict[str, Any]:
    """
    Main self-learning loop.
    
    Runs after market close:
    1. Get today's winners
    2. Analyze patterns
    3. Both brains debate (if configured)
    4. Apply to scoring
    5. Store for next day
    """
    logger.info("=== Starting Self-Learning Loop ===")
    
    # Get recent winners for analysis
    winners = _get_winners_from_db(7)
    
    if len(winners) < MIN_Winners_FOR_PATTERN:
        logger.warning(f"Not enough winners for learning: {len(winners)}")
        return {"success": False, "reason": "Not enough data"}
    
    # Analyze patterns
    patterns = analyze_winners()
    
    if not patterns:
        return {"success": False, "reason": "No patterns found"}
    
    # Apply to scoring
    result = apply_patterns_to_scoring(patterns)
    
    logger.info(f"Self-learning complete: {result}")
    
    return {
        "success": True,
        "patterns_found": len(patterns),
        "applied": result.get("applied", False),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Run self-learning
    result = run_self_learning()
    print(f"\nSelf-Learning Result: {result}")