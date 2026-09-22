"""
modules/catalyst_search.py — Real-Time Stock Catalyst & News Search Engine.

Supports:
  - SerpApi Google News Engine (India localization: gl=in, hl=en)
  - Tavily Search API (optional secondary)
  - 6-Hour smart disk caching (data/catalyst_cache.json)
  - Strict daily budget enforcement (default 8 calls/day to protect 250 monthly quota)
  - Automatic catalyst classification (order_win, earnings, fda_approval, capex)
  - Fail-open resilience
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import requests
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join("data", "catalyst_cache.json")


def _get_today_str() -> str:
    try:
        from modules.time_utils import today_ist_str
        return today_ist_str()
    except Exception:
        return datetime.date.today().isoformat()


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.debug("Error reading catalyst cache: %s", e)
    return {}


def _save_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logger.debug("Error saving catalyst cache: %s", e)


def _classify_catalyst(title: str, snippet: str) -> str:
    """Categorize the type of catalyst based on headline content."""
    text = (title + " " + snippet).lower()
    if any(w in text for w in ("order", "contract", "bagged", "secured", "tender", "deal", "awarded")):
        return "order_win"
    elif any(w in text for w in ("profit", "revenue", "results", "q1", "q2", "q3", "q4", "ebitda", "margin", "earnings")):
        return "earnings_beat"
    elif any(w in text for w in ("approval", "fda", "clearance", "patent", "licence", "license")):
        return "regulatory_approval"
    elif any(w in text for w in ("acquisition", "stake", "merger", "buyout", "invest")):
        return "strategic_investment"
    elif any(w in text for w in ("expansion", "plant", "capex", "capacity", "facility")):
        return "capex_expansion"
    elif any(w in text for w in ("target", "upgrade", "buy call", "brokerage")):
        return "brokerage_upgrade"
    return "general_momentum"


def get_stock_catalyst(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Search real-time Google News / Web for stock catalyst.
    Applies 6-hour caching and daily budget enforcement.
    Returns:
      {
        "symbol": "TCS",
        "has_catalyst": True,
        "headline": "...",
        "source": "Economic Times",
        "date": "2 hours ago",
        "catalyst_type": "order_win",
        "summary": "[Economic Times] Secured ₹340 Cr contract"
      }
    """
    sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()

    # Config checks
    try:
        from config import (
            CATALYST_SEARCH_ENABLED,
            CATALYST_MAX_DAILY_SEARCHES,
            SERPAPI_KEY,
            TAVILY_API_KEY,
        )
    except Exception:
        CATALYST_SEARCH_ENABLED = True
        CATALYST_MAX_DAILY_SEARCHES = 8
        SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
        TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

    if not CATALYST_SEARCH_ENABLED or (not SERPAPI_KEY and not TAVILY_API_KEY):
        return None

    today = _get_today_str()
    cache = _load_cache()

    # 1. Check local cache (valid for 6 hours)
    if sym in cache:
        item = cache[sym]
        cached_ts = item.get("cached_at", "")
        try:
            cached_dt = datetime.datetime.fromisoformat(cached_ts)
            if (datetime.datetime.now() - cached_dt).total_seconds() < 21600:  # 6 hours
                logger.debug("Catalyst cache hit for %s", sym)
                return item.get("data")
        except Exception:
            pass

    # 2. Check daily budget
    today_count = sum(1 for v in cache.values() if v.get("date") == today and v.get("api_called"))
    if today_count >= CATALYST_MAX_DAILY_SEARCHES:
        logger.info("Daily catalyst search budget reached (%d/%d) — skipping %s",
                    today_count, CATALYST_MAX_DAILY_SEARCHES, sym)
        return None

    # 3. Query SerpApi Google News Engine
    if SERPAPI_KEY:
        try:
            url = "https://serpapi.com/search"
            params = {
                "api_key": SERPAPI_KEY,
                "engine": "google_news",
                "q": f"{sym} share news NSE",
                "gl": "in",
                "hl": "en",
            }
            resp = requests.get(url, params=params, timeout=7)
            if resp.status_code == 200:
                data = resp.json()
                news_items = data.get("news_results", [])
                if news_items:
                    top_item = news_items[0]
                    title = top_item.get("title", "").strip()
                    source = top_item.get("source", {}).get("name", "Financial News")
                    date_str = top_item.get("date", "Recent")
                    snippet = top_item.get("snippet", "")
                    cat_type = _classify_catalyst(title, snippet)

                    result = {
                        "symbol": sym,
                        "has_catalyst": True,
                        "headline": title,
                        "source": source,
                        "date": date_str,
                        "catalyst_type": cat_type,
                        "summary": f"[{source}] {title}",
                    }

                    # Record API usage
                    try:
                        from modules.api_registry import record_api_call
                        record_api_call("serpapi_news")
                    except Exception:
                        pass

                    # Cache result
                    cache[sym] = {
                        "date": today,
                        "cached_at": datetime.datetime.now().isoformat(),
                        "api_called": True,
                        "data": result,
                    }
                    _save_cache(cache)
                    logger.info("Catalyst discovered for %s via SerpApi: %s", sym, result["summary"])
                    return result
        except Exception as exc:
            logger.debug("SerpApi catalyst lookup error for %s: %s", sym, exc)

    # 4. Fallback to Tavily if configured
    if TAVILY_API_KEY:
        try:
            url = "https://api.tavily.com/search"
            payload = {
                "api_key": TAVILY_API_KEY,
                "query": f"{sym} stock news today NSE",
                "search_depth": "basic",
                "max_results": 2,
            }
            resp = requests.post(url, json=payload, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    top = results[0]
                    title = top.get("title", "")
                    content = top.get("content", "")
                    cat_type = _classify_catalyst(title, content)
                    res = {
                        "symbol": sym,
                        "has_catalyst": True,
                        "headline": title,
                        "source": "Tavily Web Search",
                        "date": "Today",
                        "catalyst_type": cat_type,
                        "summary": f"[Web News] {title}",
                    }
                    cache[sym] = {
                        "date": today,
                        "cached_at": datetime.datetime.now().isoformat(),
                        "api_called": True,
                        "data": res,
                    }
                    _save_cache(cache)
                    return res
        except Exception as exc:
            logger.debug("Tavily catalyst lookup error for %s: %s", sym, exc)

    return None
