"""
modules/fred_provider.py — Federal Reserve Economic Data (FRED) Provider.

Tracks vital macroeconomic indicators driving Indian markets and FII flows:
  - Brent Crude Oil (DCOILBRENTEU) — Key for Indian inflation, oil marketing, paints, tires
  - US 10-Year Treasury Yield (DGS10) — Primary driver of FII capital flows in emerging markets
  - CBOE Volatility Index (VIXCLS) — Global market fear gauge
  - US Broad Dollar Index (DTWEXBGS) — USD/INR currency strength

Features:
  - 1-Hour smart disk caching (data/fred_cache.json)
  - Fail-open architecture
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import requests
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join("data", "fred_cache.json")
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Key Series IDs
SERIES_MAP = {
    "brent_crude": "DCOILBRENTEU",
    "us_10y_yield": "DGS10",
    "global_vix": "VIXCLS",
    "dollar_index": "DTWEXBGS",
}


def is_fred_configured() -> bool:
    try:
        from config import FRED_API_KEY, FRED_ENABLED
        return bool(FRED_ENABLED and FRED_API_KEY)
    except Exception:
        return bool(os.getenv("FRED_API_KEY"))


def _get_api_key() -> str:
    try:
        from config import FRED_API_KEY
        return (FRED_API_KEY or "").strip()
    except Exception:
        return os.getenv("FRED_API_KEY", "").strip()


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


def get_macro_indicator(series_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the latest single observation for a given FRED series ID.
    Caches for 1 hour.
    """
    if not is_fred_configured():
        return None

    cache = _load_cache()
    if series_id in cache:
        item = cache[series_id]
        try:
            dt = datetime.datetime.fromisoformat(item.get("cached_at", ""))
            if (datetime.datetime.now() - dt).total_seconds() < 3600:  # 1 hour
                return item.get("data")
        except Exception:
            pass

    key = _get_api_key()
    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }

    try:
        resp = requests.get(FRED_BASE_URL, params=params, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            obs = data.get("observations", [])
            if obs:
                val_str = obs[0].get("value", "")
                try:
                    val = float(val_str)
                except ValueError:
                    val = None

                res = {
                    "series_id": series_id,
                    "date": obs[0].get("date", ""),
                    "value": val,
                }

                try:
                    from modules.api_registry import record_api_call
                    record_api_call("fred_macro")
                except Exception:
                    pass

                cache[series_id] = {
                    "cached_at": datetime.datetime.now().isoformat(),
                    "data": res,
                }
                _save_cache(cache)
                return res
    except Exception as exc:
        logger.debug("FRED indicator error for %s: %s", series_id, exc)

    return None


def get_macro_snapshot() -> Dict[str, Any]:
    """
    Fetch complete macroeconomic snapshot across all core series.
    Returns:
      {
        'brent_crude': {'value': 109.51, 'date': '2026-09-09'},
        'us_10y_yield': {'value': 4.95, 'date': '2026-09-10'},
        'global_vix': {'value': 17.84, 'date': '2026-09-10'},
        'crude_pressure': bool, # True if Brent > $85 (negative for Indian smallcaps)
      }
    """
    snapshot = {}
    for name, series_id in SERIES_MAP.items():
        res = get_macro_indicator(series_id)
        if res and res.get("value") is not None:
            snapshot[name] = res

    # Derived market bias
    brent = snapshot.get("brent_crude", {}).get("value")
    us10y = snapshot.get("us_10y_yield", {}).get("value")
    vix = snapshot.get("global_vix", {}).get("value")

    snapshot["crude_pressure"] = bool(brent and brent > 85.0)
    snapshot["fii_yield_pressure"] = bool(us10y and us10y > 4.5)
    snapshot["high_volatility_regime"] = bool(vix and vix > 20.0)

    return snapshot
