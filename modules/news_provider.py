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


def fetch_market_news(limit: int = 20) -> dict[str, Any]:
    """Return market news without relying on the invalid NewsAPI key."""
    items = _from_thenewsapi(limit)
    provider = "thenewsapi"
    if len(items) < max(3, min(limit, 10)):
        rss_items = _from_rss(limit - len(items))
        items.extend(rss_items)
        provider = "thenewsapi+rss" if items and provider == "thenewsapi" else "rss"

    return {
        "items": items[:limit],
        "provider": provider if items else "none",
        "count": len(items[:limit]),
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }
