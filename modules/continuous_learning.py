# MarketMind Pro — Research and Advisory Only

"""
continuous_learning.py — Continuous Learning System (Session 2)

Runs ALWAYS in background, parallel to morning session:
- Continuous NSE universe scan
- Real-time news analysis
- FII/DII flow tracking
- Pattern discovery
- Data insights gathering
- All coordinated via ONE command system
"""

from __future__ import annotations
import datetime
import json
import logging
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

logger = logging.getLogger(__name__)

CONTINUOUS_STATE = "data/continuous_state.json"
MIN_LEARNING_INTERVAL = 300  # 5 minutes between scans


def _init_state() -> None:
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(CONTINUOUS_STATE):
        with open(CONTINUOUS_STATE, "w") as f:
            json.dump({
                "running": False,
                "last_scan": None,
                "insights": [],
                "learned_patterns": [],
                "stock_analysis": {},
                "start_time": None,
            }, f)


def _load_state() -> dict:
    _init_state()
    try:
        with open(CONTINUOUS_STATE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    with open(CONTINUOUS_STATE, "w") as f:
        json.dump(state, f, indent=2)


def _get_universe() -> list[str]:
    """Get full NSE universe."""
    try:
        from modules.scanner import get_universe
        return get_universe() or []
    except Exception:
        pass
    
    return [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN",
        "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    ]


# ============================================================================
# FII/DII Flow Tracking
# ============================================================================

def track_fii_dii_flows() -> dict[str, Any]:
    """Track FII and DII buying/selling patterns."""
    insights = []
    
    try:
        # Try NSE API for FII data
        r = requests.get(
            "https://www.nseindia.com/api/market-summary",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            insights.append({
                "type": "fii_flow",
                "data": data,
                "timestamp": datetime.datetime.now().isoformat(),
            })
    except Exception as e:
        logger.debug(f"FII tracking: {e}")
    
    return {"fii_insights": insights, "count": len(insights)}


# ============================================================================
# News Analysis
# ============================================================================

def analyze_market_news() -> dict[str, Any]:
    """Analyze latest market news for insights."""
    try:
        from modules.news_provider import fetch_market_news

        payload = fetch_market_news(limit=20)
        news_items = payload.get("items", [])
    except Exception as e:
        logger.debug(f"News tracking: {e}")
        news_items = []
    
    # Extract key insights
    keywords = {"result": [], "budget": [], "quarter": [], " IPO": [], "bonus": [], "dividend": [], "buyback": []}
    for news in news_items:
        title = (news.get("title", "") + " " + news.get("desc", "")).lower()
        for kw in keywords:
            if kw in title:
                keywords[kw].append(news)
    
    return {
        "news_items": news_items[:10],
        "keyword_analysis": {k: len(v) for k, v in keywords.items()},
        "timestamp": datetime.datetime.now().isoformat(),
    }


# ============================================================================
# Stock Analysis Engine
# ============================================================================

def analyze_stock_batch(symbols: list[str], batch_size: int = 50) -> dict[str, Any]:
    """Quick analyze batch of stocks."""
    results = {}
    
    try:
        from modules.fetch import fetch_ohlcv
        
        for sym in symbols[:batch_size]:
            try:
                df = fetch_ohlcv(sym, period="1mo")
                if df is None or df.empty:
                    continue
                
                close = df["close"].astype(float)
                volume = df["volume"].astype(float)
                
                # Quick metrics
                price = float(close.iloc[-1])
                change_1m = ((price - float(close.iloc[0])) / float(close.iloc[0])) * 100
                vol_ratio = float(volume.iloc[-1]) / volume.mean() if volume.mean() > 0 else 1.0
                
                results[sym] = {
                    "price": price,
                    "change_1m": change_1m,
                    "volume_ratio": vol_ratio,
                    "atr": float((df["high"] - df["low"]).mean()) if "high" in df.columns else 0,
                    "analyzed_at": datetime.datetime.now().isoformat(),
                }
            except Exception:
                continue
    
    except Exception as e:
        logger.debug(f"Stock batch analysis: {e}")
    
    return results


def find_data_insights(all_analysis: dict) -> list[dict]:
    """Find insights from analyzed data."""
    insights = []
    
    if not all_analysis:
        return insights
    
    # Find momentum stocks
    momentum = [(s, d.get("change_1m", 0)) for s, d in all_analysis.items() if d.get("change_1m")]
    momentum.sort(key=lambda x: x[1], reverse=True)
    
    if momentum[:5]:
        insights.append({
            "type": "momentum",
            "description": "Top 5 momentum stocks",
            "symbols": [s for s, _ in momentum[:5]],
        })
    
    # Find volume surge
    volume_surge = [(s, d.get("volume_ratio", 1)) for s, d in all_analysis.items() if d.get("volume_ratio", 1) > 2]
    volume_surge.sort(key=lambda x: x[1], reverse=True)
    
    if volume_surge[:5]:
        insights.append({
            "type": "volume_surge",
            "description": "Stocks with unusual volume",
            "symbols": [s for s, _ in volume_surge[:5]],
        })
    
    return insights


# ============================================================================
# Store Analysis Results
# ============================================================================

def store_continuous_learned(insights: list[dict], analysis: dict) -> None:
    """Store learned data for next session."""
    state = _load_state()
    
    state["last_scan"] = datetime.datetime.now().isoformat()
    state["insights"] = (state.get("insights", []) + insights)[-50:]
    state["stock_analysis"] = {**state.get("stock_analysis", {}), **analysis}
    
    _save_state(state)


def get_learned_insights() -> list[dict]:
    """Get insights for morning session."""
    state = _load_state()
    return state.get("insights", [])


# ============================================================================
# Main Continuous Learning Loop
# ============================================================================

def run_continuous_learning_cycle() -> dict[str, Any]:
    """One cycle of continuous learning."""
    logger.info("=== Continuous Learning Cycle ===")
    
    cycle_data = {
        "started_at": datetime.datetime.now().isoformat(),
        "fii_flows": {},
        "news": {},
        "insights": [],
    }
    
    # 1. Track FII/DII flows
    try:
        cycle_data["fii_flows"] = track_fii_dii_flows()
    except Exception as e:
        logger.debug(f"FII: {e}")
    
    # 2. Analyze news
    try:
        cycle_data["news"] = analyze_market_news()
        logger.info(f"News: {cycle_data['news'].get('keyword_analysis', {})}")
    except Exception as e:
        logger.debug(f"News: {e}")
    
    # 3. Quick stock scan (random sample)
    universe = _get_universe()
    import random
    sample = random.sample(universe, min(100, len(universe)))
    
    try:
        analysis = analyze_stock_batch(sample, 50)
        cycle_data["insights"] = find_data_insights(analysis)
        
        # Store
        store_continuous_learned(cycle_data["insights"], analysis)
        
        logger.info(f"Insights: {[i.get('type') for i in cycle_data['insights']]}")
    except Exception as e:
        logger.debug(f"Stock scan: {e}")
    
    cycle_data["completed_at"] = datetime.datetime.now().isoformat()
    
    return cycle_data


# ============================================================================
# Start/Stop Continuous Learning
# ============================================================================

_continuous_thread = None
_running = False


def start_continuous_learning(interval_minutes: int = 30, run_immediate: bool = True) -> dict[str, Any]:
    """Start continuous learning in background."""
    global _continuous_thread, _running
    
    if _running:
        return {"ok": False, "error": "Already running"}
    
    _running = True
    
    state = _load_state()
    state["running"] = True
    state["start_time"] = datetime.datetime.now().isoformat()
    _save_state(state)
    
    def _run_loop():
        while _running:
            try:
                run_continuous_learning_cycle()
            except Exception as e:
                logger.error(f"Continuous cycle error: {e}")
            
            time.sleep(interval_minutes * 60)
    
    _continuous_thread = threading.Thread(target=_run_loop, daemon=True)
    _continuous_thread.start()
    
    if run_immediate:
        run_continuous_learning_cycle()
    
    logger.info(f"Continuous learning started (every {interval_minutes} min)")
    return {"ok": True, "message": f"Running in background every {interval_minutes} min"}


def stop_continuous_learning() -> dict[str, Any]:
    """Stop continuous learning."""
    global _running, _continuous_thread
    
    if not _running:
        return {"ok": False, "error": "Not running"}
    
    _running = False
    
    state = _load_state()
    state["running"] = False
    state["stopped_at"] = datetime.datetime.now().isoformat()
    _save_state(state)
    
    logger.info("Continuous learning stopped")
    return {"ok": True, "message": "Stopped"}


def get_continuous_status() -> dict[str, Any]:
    """Get continuous learning status."""
    state = _load_state()
    insights = get_learned_insights()
    
    return {
        "running": state.get("running", False),
        "last_scan": state.get("last_scan"),
        "start_time": state.get("start_time"),
        "insights_count": len(insights),
        "recent_insights": insights[-10:],
    }


def get_morning_context() -> dict[str, Any]:
    """Get prepared context for morning session."""
    insights = get_learned_insights()
    
    # Group by type
    momentum_stocks = []
    volume_stocks = []
    sector_stocks = []
    
    for i in insights:
        if i.get("type") == "momentum":
            momentum_stocks.extend(i.get("symbols", []))
        elif i.get("type") == "volume_surge":
            volume_stocks.extend(i.get("symbols", []))
    
    state = _load_state()
    
    return {
        "momentum_stocks": momentum_stocks[:10],
        "volume_surge_stocks": volume_stocks[:10],
        "insights_summary": {
            "total": len(insights),
            "last_updated": state.get("last_scan"),
        },
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== Continuous Learning Test ===")
    
    # Run one cycle
    result = run_continuous_learning_cycle()
    print(f"Cycle complete: {list(result.keys())}")
    
    # Check insights
    insights = get_learned_insights()
    print(f"Insights: {len(insights)}")
    
    # Morning context
    ctx = get_morning_context()
    print(f"Morning context: {ctx}")
