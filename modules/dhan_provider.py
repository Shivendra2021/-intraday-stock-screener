"""
modules/dhan_provider.py — DhanHQ Broker API Provider for MarketMind Pro.

Provides:
  - Live quote and LTP fetching via official DhanHQ SDK or REST API
  - Symbol to Security-ID resolution cached in data/dhan_scrip_master.json
  - Multi-source broker price validation
  - Fail-open resilience (returns None on any error without crashing pipeline)
"""

from __future__ import annotations

import json
import logging
import os
import requests
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DHAN_CLIENT = None
_SCRIP_CACHE: dict[str, int] = {}
_SCRIP_CACHE_PATH = os.path.join("data", "dhan_scrip_master.json")

_DEFAULT_SCRIP_IDS: dict[str, int] = {
    "RELIANCE": 2885,
    "TCS": 11536,
    "HDFCBANK": 1333,
    "INFY": 1594,
    "ICICIBANK": 4963,
    "SBIN": 3045,
    "BHARTIARTL": 10604,
    "ITC": 1660,
    "KOTAKBANK": 1922,
    "LT": 11483,
    "AXISBANK": 5900,
    "TATAMOTORS": 3456,
    "SUNPHARMA": 3351,
    "MARUTI": 10999,
    "TITAN": 3506,
    "BAJFINANCE": 317,
    "WIPRO": 3787,
    "HCLTECH": 7229,
    "NTPC": 11630,
    "POWERGRID": 14977,
}


def is_dhan_configured() -> bool:
    try:
        from config import DHAN_ACCESS_TOKEN, DHAN_ENABLED
        return bool(DHAN_ENABLED and DHAN_ACCESS_TOKEN)
    except Exception:
        return False


def get_dhan_credentials() -> tuple[str, str]:
    try:
        from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN
        client_id = (DHAN_CLIENT_ID or "").strip()
        access_token = (DHAN_ACCESS_TOKEN or "").strip()
        return client_id, access_token
    except Exception:
        return "", ""


def _load_scrip_cache() -> dict[str, int]:
    global _SCRIP_CACHE
    if _SCRIP_CACHE:
        return _SCRIP_CACHE

    _SCRIP_CACHE.update(_DEFAULT_SCRIP_IDS)

    if os.path.exists(_SCRIP_CACHE_PATH):
        try:
            with open(_SCRIP_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _SCRIP_CACHE.update({str(k).upper(): int(v) for k, v in data.items()})
                    logger.debug("Loaded %d Dhan scrip mappings from %s", len(_SCRIP_CACHE), _SCRIP_CACHE_PATH)
        except Exception as exc:
            logger.debug("Failed to read Dhan scrip cache: %s", exc)

    return _SCRIP_CACHE


def _save_scrip_cache(new_mappings: dict[str, int]) -> None:
    try:
        os.makedirs(os.path.dirname(_SCRIP_CACHE_PATH), exist_ok=True)
        existing = {}
        if os.path.exists(_SCRIP_CACHE_PATH):
            with open(_SCRIP_CACHE_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        existing.update({str(k).upper(): int(v) for k, v in new_mappings.items()})
        with open(_SCRIP_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception as exc:
        logger.debug("Failed to save Dhan scrip cache: %s", exc)


def get_security_id(symbol: str) -> Optional[int]:
    sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    cache = _load_scrip_cache()
    if sym in cache:
        return cache[sym]

    try:
        from dhanhq import Security
        scrip_url = getattr(Security, "COMPACT_CSV_URL", "https://images.dhan.co/api-data/api-scrip-master.csv")
        resp = requests.get(scrip_url, timeout=10)
        if resp.status_code == 200:
            new_map = {}
            for line in resp.text.splitlines()[1:]:
                parts = line.split(",")
                if len(parts) >= 3:
                    for p in parts:
                        if p.strip().upper() == sym:
                            try:
                                sec_id = int(parts[0] if parts[0].isdigit() else parts[2])
                                new_map[sym] = sec_id
                                _SCRIP_CACHE[sym] = sec_id
                                _save_scrip_cache(new_map)
                                return sec_id
                            except (ValueError, IndexError):
                                pass
    except Exception as exc:
        logger.debug("Dhan scrip master resolution error for %s: %s", sym, exc)

    return None


def get_dhan_client() -> Any:
    global _DHAN_CLIENT
    if _DHAN_CLIENT is not None:
        return _DHAN_CLIENT

    if not is_dhan_configured():
        return None

    client_id, access_token = get_dhan_credentials()
    if not access_token:
        return None

    try:
        from dhanhq import dhanhq, DhanContext
        cid = client_id if client_id else "1000000000"
        context = DhanContext(cid, access_token)
        _DHAN_CLIENT = dhanhq(context)
        logger.info("DhanHQ client initialized successfully")
        return _DHAN_CLIENT
    except Exception as exc:
        logger.warning("DhanHQ SDK initialization failed: %s", exc)
        return None


def get_dhan_price(symbol: str) -> Optional[float]:
    if not is_dhan_configured():
        return None

    sec_id = get_security_id(symbol)
    if not sec_id:
        return None

    client_id, access_token = get_dhan_credentials()
    if not access_token:
        return None

    url = "https://api.dhan.co/v2/marketfeed/ltp"
    headers = {
        "access-token": access_token,
        "client-id": client_id if client_id else "1000000000",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"NSE_EQ": [sec_id]}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", {}).get("NSE_EQ", {})
            sec_data = items.get(str(sec_id)) or items.get(sec_id, {})
            ltp = sec_data.get("last_price")
            if ltp and float(ltp) > 0:
                return float(ltp)
    except Exception as exc:
        logger.debug("Dhan REST LTP failed for %s (id: %s): %s", symbol, sec_id, exc)

    try:
        client = get_dhan_client()
        if client:
            res = client.quote_data({"NSE_EQ": [sec_id]})
            if isinstance(res, dict) and res.get("status") == "success":
                data = res.get("data", {}).get("NSE_EQ", {}).get(str(sec_id), {})
                ltp = data.get("last_price")
                if ltp and float(ltp) > 0:
                    return float(ltp)
    except Exception as exc:
        logger.debug("Dhan SDK quote_data failed for %s: %s", symbol, exc)

    return None


def get_dhan_quote(symbol: str) -> Optional[dict]:
    if not is_dhan_configured():
        return None

    sec_id = get_security_id(symbol)
    if not sec_id:
        return None

    client_id, access_token = get_dhan_credentials()
    url = "https://api.dhan.co/v2/marketfeed/quote"
    headers = {
        "access-token": access_token,
        "client-id": client_id if client_id else "1000000000",
        "Content-Type": "application/json",
    }
    payload = {"NSE_EQ": [sec_id]}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=6)
        if resp.status_code == 200:
            data = resp.json().get("data", {}).get("NSE_EQ", {}).get(str(sec_id), {})
            ohlc = data.get("ohlc", {})
            depth = data.get("depth", {})
            buy_depth = depth.get("buy", [{}])[0] if depth.get("buy") else {}
            sell_depth = depth.get("sell", [{}])[0] if depth.get("sell") else {}
            return {
                "symbol": symbol.upper(),
                "security_id": sec_id,
                "last_price": float(data.get("last_price", 0) or 0),
                "open": float(ohlc.get("open", 0) or 0),
                "high": float(ohlc.get("high", 0) or 0),
                "low": float(ohlc.get("low", 0) or 0),
                "close": float(ohlc.get("close", 0) or 0),
                "volume": int(data.get("volume", 0) or 0),
                "bid": float(buy_depth.get("price", 0) or 0),
                "ask": float(sell_depth.get("price", 0) or 0),
                "source": "dhanhq",
            }
    except Exception as exc:
        logger.debug("Dhan full quote failed for %s: %s", symbol, exc)

    return None
