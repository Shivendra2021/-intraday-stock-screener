"""
modules/twelve_data_provider.py — Twelve Data API Integration for MarketMind Pro.

Provides:
  - Real-time USD/INR forex exchange rate tracking (vital for Indian IT/Pharma export sectors & FII flows)
  - International market cues and equity pricing
  - 15-minute smart disk caching (data/twelve_data_cache.json) to respect free-tier rate limits (8 req/min, 800 req/day)
  - Fail-open architecture (domestic Indian NSE symbols return None gracefully on Basic plan)
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import requests
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join("data", "twelve_data_cache.json")
BASE_URL = "https://api.twelvedata.com"


def is_twelve_data_configured() -> bool:
    try:
        from config import TWELVE_DATA_API_KEY, TWELVE_DATA_ENABLED
        return bool(TWELVE_DATA_ENABLED and TWELVE_DATA_API_KEY)
    except Exception:
        return bool(os.getenv("TWELVE_DATA_API_KEY"))


def _get_api_key() -> str:
    try:
        from config import TWELVE_DATA_API_KEY
        return (TWELVE_DATA_API_KEY or "").strip()
    except Exception:
        return os.getenv("TWELVE_DATA_API_KEY", "").strip()


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


def get_usdinr_rate() -> Optional[float]:
    """
    Fetch the real-time USD/INR currency exchange rate.
    Cached for 15 minutes to preserve rate limits.
    """
    if not is_twelve_data_configured():
        return None

    cache = _load_cache()
    if "USD/INR" in cache:
        item = cache["USD/INR"]
        try:
            dt = datetime.datetime.fromisoformat(item.get("cached_at", ""))
            if (datetime.datetime.now() - dt).total_seconds() < 900:  # 15 minutes
                return float(item.get("price"))
        except Exception:
            pass

    key = _get_api_key()
    if not key:
        return None

    url = f"{BASE_URL}/price"
    params = {
        "symbol": "USD/INR",
        "apikey": key,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "price" in data and data.get("status") != "error":
                price = float(data["price"])
                cache["USD/INR"] = {
                    "price": price,
                    "cached_at": datetime.datetime.now().isoformat(),
                }
                _save_cache(cache)
                try:
                    from modules.api_registry import record_api_call
                    record_api_call("twelve_data", 1)
                except Exception:
                    pass
                return price
            else:
                logger.debug("Twelve Data USD/INR response message: %s", data.get("message"))
    except Exception as exc:
        logger.warning("Failed fetching USD/INR from Twelve Data: %s", exc)

    return None


def get_twelve_data_price(symbol: str) -> Optional[float]:
    """
    Fetch price for a symbol via Twelve Data with fail-open handling.
    Returns None if unsupported (e.g., NSE paywalled on free tier) or on error.
    """
    if not is_twelve_data_configured() or not symbol:
        return None

    sym_clean = symbol.strip().upper()
    cache = _load_cache()
    if sym_clean in cache:
        item = cache[sym_clean]
        try:
            dt = datetime.datetime.fromisoformat(item.get("cached_at", ""))
            if (datetime.datetime.now() - dt).total_seconds() < 300:  # 5 minutes
                return float(item.get("price"))
        except Exception:
            pass

    key = _get_api_key()
    if not key:
        return None

    url = f"{BASE_URL}/price"
    params = {
        "symbol": sym_clean,
        "apikey": key,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "price" in data and data.get("status") != "error":
                price = float(data["price"])
                cache[sym_clean] = {
                    "price": price,
                    "cached_at": datetime.datetime.now().isoformat(),
                }
                _save_cache(cache)
                try:
                    from modules.api_registry import record_api_call
                    record_api_call("twelve_data", 1)
                except Exception:
                    pass
                return price
            else:
                logger.debug("Twelve Data price unavailable for %s: %s", sym_clean, data.get("message"))
    except Exception as exc:
        logger.debug("Twelve Data price request failed for %s: %s", sym_clean, exc)

    return None
