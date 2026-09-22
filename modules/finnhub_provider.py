"""
modules/finnhub_provider.py — Global Macro Sentiment & Economic Calendar Provider.

Features:
  - Real-time global market news (general, forex, merger)
  - Live Economic Calendar tracking (Fed, RBI, CPI inflation, GDP)
  - Global pre-market sentiment score (-1.0 to +1.0)
  - 10-Minute smart caching in data/finnhub_cache.json
  - Fail-open resilience
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import requests
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join("data", "finnhub_cache.json")
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


def is_finnhub_configured() -> bool:
    try:
        from config import FINNHUB_API_KEY, FINNHUB_ENABLED
        return bool(FINNHUB_ENABLED and FINNHUB_API_KEY)
    except Exception:
        return bool(os.getenv("FINNHUB_API_KEY"))


def _get_api_key() -> str:
    try:
        from config import FINNHUB_API_KEY
        return (FINNHUB_API_KEY or "").strip()
    except Exception:
        return os.getenv("FINNHUB_API_KEY", "").strip()


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def get_global_market_news(category: str = "general", limit: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch top global financial news headlines.
    Caches for 10 minutes.
    """
    if not is_finnhub_configured():
        return []

    cache_key = f"news_{category}"
    cache = _load_cache()
    if cache_key in cache:
        item = cache[cache_key]
        try:
            dt = datetime.datetime.fromisoformat(item.get("cached_at", ""))
            if (datetime.datetime.now() - dt).total_seconds() < 600:  # 10 mins
                return item.get("data", [])[:limit]
        except Exception:
            pass

    key = _get_api_key()
    try:
        url = f"{FINNHUB_BASE_URL}/news"
        params = {"category": category, "token": key}
        resp = requests.get(url, params=params, timeout=6)
        if resp.status_code == 200:
            raw_news = resp.json()
            if isinstance(raw_news, list):
                news_list = []
                for n in raw_news[:limit]:
                    news_list.append({
                        "id": n.get("id"),
                        "headline": n.get("headline", ""),
                        "source": n.get("source", "Finnhub Global"),
                        "url": n.get("url", ""),
                        "summary": n.get("summary", ""),
                        "datetime": n.get("datetime", 0),
                    })

                try:
                    from modules.api_registry import record_api_call
                    record_api_call("finnhub_macro")
                except Exception:
                    pass

                cache[cache_key] = {
                    "cached_at": datetime.datetime.now().isoformat(),
                    "data": news_list,
                }
                _save_cache(cache)
                return news_list
    except Exception as exc:
        logger.debug("Finnhub get_global_market_news error: %s", exc)

    return []


def get_high_impact_macro_events(lookahead_days: int = 2) -> List[Dict[str, Any]]:
    """
    Fetch high-impact economic calendar events (CPI, Fed, RBI, GDP).
    Returns list of upcoming high-impact events for today / tomorrow.
    """
    if not is_finnhub_configured():
        return []

    cache_key = "economic_calendar"
    cache = _load_cache()
    if cache_key in cache:
        item = cache[cache_key]
        try:
            dt = datetime.datetime.fromisoformat(item.get("cached_at", ""))
            if (datetime.datetime.now() - dt).total_seconds() < 1800:  # 30 mins
                return item.get("data", [])
        except Exception:
            pass

    key = _get_api_key()
    today = datetime.date.today()
    from_date = today.isoformat()
    to_date = (today + datetime.timedelta(days=lookahead_days)).isoformat()

    try:
        url = f"{FINNHUB_BASE_URL}/calendar/economic"
        params = {"from": from_date, "to": to_date, "token": key}
        resp = requests.get(url, params=params, timeout=7)
        if resp.status_code == 200:
            data = resp.json()
            events = data.get("economicCalendar", [])
            high_impact = []
            for ev in events:
                impact = ev.get("impact", "")
                event_name = ev.get("event", "")
                country = ev.get("country", "")
                # Focus on High/Medium impact in India, US, or global
                if impact in ("high", "3") or any(w in event_name.lower() for w in ("cpi", "rate", "fed", "rbi", "gdp", "inflation")):
                    high_impact.append({
                        "event": event_name,
                        "country": country,
                        "time": ev.get("time", ""),
                        "impact": impact,
                        "actual": ev.get("actual"),
                        "estimate": ev.get("estimate"),
                        "prev": ev.get("prev"),
                    })

            try:
                from modules.api_registry import record_api_call
                record_api_call("finnhub_macro")
            except Exception:
                pass

            cache[cache_key] = {
                "cached_at": datetime.datetime.now().isoformat(),
                "data": high_impact,
            }
            _save_cache(cache)
            return high_impact
    except Exception as exc:
        logger.debug("Finnhub economic calendar error: %s", exc)

    return []


def get_global_sentiment_score() -> float:
    """
    Estimate pre-market global sentiment score from -1.0 (bearish) to +1.0 (bullish).
    Uses US broad market proxies (SPY, QQQ) quotes from Finnhub.
    """
    if not is_finnhub_configured():
        return 0.0

    key = _get_api_key()
    changes = []
    for ticker in ("SPY", "QQQ"):
        try:
            url = f"{FINNHUB_BASE_URL}/quote"
            resp = requests.get(url, params={"symbol": ticker, "token": key}, timeout=5)
            if resp.status_code == 200:
                q = resp.json()
                dp = q.get("dp")  # percentage change
                if dp is not None:
                    changes.append(float(dp))
        except Exception:
            pass

    if not changes:
        return 0.0

    avg_change = sum(changes) / len(changes)
    # Map +/- 1.5% US move to +/- 1.0 sentiment score
    score = max(-1.0, min(1.0, avg_change / 1.5))
    return round(score, 2)
