"""Cross-source price validation before picks are persisted."""

from __future__ import annotations

import datetime
import json
import logging
import statistics

import requests

logger = logging.getLogger(__name__)


def _clean_price(value) -> float | None:
    try:
        price = float(value)
        return price if price > 0 else None
    except Exception:
        return None


def yahoo_price(symbol: str) -> float | None:
    """Return latest price via modules.fetch (handles aliases, retries, BO fallback)."""
    from modules.fetch import fetch_price
    return fetch_price(symbol)


def nse_price(symbol: str) -> float | None:
    """Fetch official NSE quote, trying jugaad-data first, then direct requests session."""
    try:
        from modules.jugaad_provider import get_jugaad_price
        p = get_jugaad_price(symbol)
        if p and p > 0:
            return _clean_price(p)
    except Exception as exc:
        logger.debug("jugaad_price fallback for %s: %s", symbol, exc)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.nseindia.com/get-quotes/equity",
    }
    url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
    try:
        from modules.http_session import get_http_session
        session = get_http_session()
        response = session.get(url, headers=headers, timeout=8)
        if response.status_code == 401 or response.status_code == 403:
            # Refresh NSE homepage cookie in pooled session
            session.get("https://www.nseindia.com", headers=headers, timeout=8)
            response = session.get(url, headers=headers, timeout=8)
        if response.status_code != 200:
            return None
        data = response.json()
        price_info = data.get("priceInfo", {})
        return _clean_price(price_info.get("lastPrice") or price_info.get("close"))
    except Exception as exc:
        logger.debug("NSE price failed for %s: %s", symbol, exc)
    return None


def broker_price(symbol: str) -> float | None:
    """Fetch live quote from connected broker: DhanHQ (primary) or Zerodha Kite (secondary)."""
    # 1. Try DhanHQ broker API
    try:
        from modules.dhan_provider import is_dhan_configured, get_dhan_price
        if is_dhan_configured():
            dp = get_dhan_price(symbol)
            if dp and dp > 0:
                return _clean_price(dp)
    except Exception as exc:
        logger.debug("Dhan broker quote failed for %s: %s", symbol, exc)

    # 2. Try Zerodha Kite broker API
    try:
        from config import ZERODHA_ACCESS_TOKEN, ZERODHA_API_KEY
    except Exception:
        return None

    if not ZERODHA_API_KEY or not ZERODHA_ACCESS_TOKEN:
        return None

    headers = {
        "X-Kite-Version": "3",
        "Authorization": f"token {ZERODHA_API_KEY}:{ZERODHA_ACCESS_TOKEN}",
    }
    try:
        response = requests.get(
            "https://api.kite.trade/quote",
            headers=headers,
            params={"i": f"NSE:{symbol}"},
            timeout=8,
        )
        if response.status_code != 200:
            logger.debug("Broker quote failed for %s: %s", symbol, response.text[:160])
            return None
        data = response.json().get("data", {}).get(f"NSE:{symbol}", {})
        return _clean_price(data.get("last_price"))
    except Exception as exc:
        logger.debug("Broker quote failed for %s: %s", symbol, exc)
    return None


def validate_price(symbol: str, expected_price: float | None = None) -> dict:
    from config import (
        BROKER_QUOTE_REQUIRED,
        PRICE_VALIDATION_MAX_SPREAD_PCT,
        PRICE_VALIDATION_MIN_SOURCES,
    )

    prices = {
        "yahoo": yahoo_price(symbol),
        "nse": nse_price(symbol),
        "broker": broker_price(symbol),
    }
    usable = {k: v for k, v in prices.items() if v}
    source_count = len(usable)
    consensus = statistics.median(usable.values()) if usable else _clean_price(expected_price)

    spread_pct = 0.0
    if len(usable) >= 2:
        low = min(usable.values())
        high = max(usable.values())
        spread_pct = ((high - low) / consensus * 100) if consensus else 999.0

    broker_ok = bool(prices["broker"]) or not BROKER_QUOTE_REQUIRED
    status = "passed"
    reasons = []
    if source_count < PRICE_VALIDATION_MIN_SOURCES:
        status = "failed"
        reasons.append(f"only {source_count} source(s)")
    if spread_pct > PRICE_VALIDATION_MAX_SPREAD_PCT:
        status = "failed"
        reasons.append(f"spread {spread_pct:.2f}%")
    if not broker_ok:
        status = "failed"
        reasons.append("broker quote missing")

    result = {
        "symbol": symbol,
        "status": status,
        "consensus_price": round(consensus, 4) if consensus else None,
        "spread_pct": round(spread_pct, 4),
        "sources_ok": source_count,
        "yahoo_price": prices["yahoo"],
        "nse_price": prices["nse"],
        "broker_price": prices["broker"],
        "details": "; ".join(reasons) if reasons else "validated",
    }
    record_price_validation(result)
    return result


def record_price_validation(result: dict) -> None:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    import sqlite3

    try:
        from modules.time_utils import now_ist, today_ist_str

        now = now_ist().isoformat(timespec="seconds")
        today = today_ist_str()
    except Exception:
        now = datetime.datetime.now().isoformat(timespec="seconds")
        today = datetime.date.today().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO price_validations
               (date, symbol, yahoo_price, nse_price, broker_price, consensus_price,
                spread_pct, sources_ok, status, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                today,
                result.get("symbol"),
                result.get("yahoo_price"),
                result.get("nse_price"),
                result.get("broker_price"),
                result.get("consensus_price"),
                result.get("spread_pct"),
                result.get("sources_ok"),
                result.get("status"),
                result.get("details") or json.dumps(result, default=str),
                now,
            ),
        )
        conn.commit()
