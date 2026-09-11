"""Reliable market-news provider with API and RSS fallback."""

from __future__ import annotations

import datetime
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


RSS_FEEDS = [
    "https://news.google.com/rss/search?q=Indian%20stock%20market%20NSE&hl=en-IN&gl=IN&ceid=IN:en",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
]


def _from_thenewsapi(limit: int) -> list[dict[str, Any]]:
    from config import THENEWSAPI_KEY

    if not THENEWSAPI_KEY:
        return []
    try:
        response = requests.get(
            "https://api.thenewsapi.com/v1/news/all",
            params={
                "api_token": THENEWSAPI_KEY,
                "search": "Indian stock market NSE",
                "language": "en",
                "limit": min(limit, 25),
            },
            timeout=8,
        )
        if response.status_code != 200:
            logger.debug("TheNewsAPI returned HTTP %s", response.status_code)
            return []
    except Exception as e:
        logger.debug("TheNewsAPI request failed: %s", e)
        return []
    rows = []
    for article in response.json().get("data", [])[:limit]:
        rows.append(
            {
                "title": article.get("title", ""),
                "desc": article.get("description", ""),
                "source": article.get("source") or "TheNewsAPI",
                "published": article.get("published_at"),
                "provider": "thenewsapi",
            }
        )
    return rows


def _from_rss(limit: int) -> list[dict[str, Any]]:
    try:
        import feedparser
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[: max(1, limit - len(rows))]:
                rows.append(
                    {
                        "title": getattr(entry, "title", ""),
                        "desc": getattr(entry, "summary", ""),
                        "source": getattr(feed.feed, "title", "RSS"),
                        "published": getattr(entry, "published", ""),
                        "provider": "rss",
                    }
                )
                if len(rows) >= limit:
                    return rows
        except Exception as exc:
            logger.debug("RSS news fetch failed for %s: %s", url, exc)
    return rows


NEWS_CACHE_FILE = "data/news_cache.json"
CACHE_TTL_SECONDS = 1800  # 30 minutes


def _load_cached_news() -> dict[str, Any] | None:
    """Load news from local disk cache if still within 30-minute TTL."""
    import json
    import os
    import time

    if not os.path.exists(NEWS_CACHE_FILE):
        return None
    try:
        with open(NEWS_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_epoch = data.get("cache_epoch", 0)
        if (time.time() - cached_epoch) < CACHE_TTL_SECONDS and data.get("items"):
            logger.debug("Loaded %s news items from 30-min cache (age: %ds)",
                         len(data.get("items", [])), int(time.time() - cached_epoch))
            return data
    except Exception as exc:
        logger.debug("Error reading news cache: %s", exc)
    return None


def _save_cached_news(payload: dict[str, Any]) -> None:
    """Save news payload to local disk cache."""
    import json
    import os
    import time

    try:
        os.makedirs(os.path.dirname(NEWS_CACHE_FILE) or ".", exist_ok=True)
        to_save = dict(payload)
        to_save["cache_epoch"] = time.time()
        temp_file = f"{NEWS_CACHE_FILE}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(to_save, f, indent=2)
        os.replace(temp_file, NEWS_CACHE_FILE)
        logger.debug("Saved news payload to %s", NEWS_CACHE_FILE)
    except Exception as exc:
        logger.debug("Could not save news cache: %s", exc)


def fetch_market_news(limit: int = 20, force_refresh: bool = False) -> dict[str, Any]:
    """
    Return market news with 30-minute disk caching to preserve API quotas.
    Falls back gracefully from TheNewsAPI to RSS feeds.
    """
    if not force_refresh:
        cached = _load_cached_news()
        if cached:
            items = cached.get("items", [])[:limit]
            return {
                "items": items,
                "provider": cached.get("provider", "cached"),
                "count": len(items),
                "timestamp": cached.get("timestamp", datetime.datetime.now().isoformat(timespec="seconds")),
                "cached": True,
            }

    items = _from_thenewsapi(limit)
    provider = "thenewsapi"
    if len(items) < max(3, min(limit, 10)):
        rss_items = _from_rss(limit - len(items))
        items.extend(rss_items)
        provider = "thenewsapi+rss" if items and provider == "thenewsapi" else "rss"

    payload = {
        "items": items[:limit],
        "provider": provider if items else "none",
        "count": len(items[:limit]),
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "cached": False,
    }

    if items:
        _save_cached_news(payload)

    return payload

