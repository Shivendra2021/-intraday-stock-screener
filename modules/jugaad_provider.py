"""
modules/jugaad_provider.py — Official NSE Bhavcopy & Live Data Provider using jugaad-data.

Provides:
  - Official NSE historical Bhavcopy daily OHLCV bars with institutional Delivery Volume & VWAP
  - Session-handled live quote extraction fallback
  - Institutional accumulation / delivery percentage metrics
  - Fail-open architecture (returns None on exceptions without blocking caller)
"""

from __future__ import annotations

import datetime
import logging
import warnings
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning, module="jugaad_data")

logger = logging.getLogger(__name__)

_LIVE_NSE = None


def is_jugaad_enabled() -> bool:
    try:
        from config import JUGAAD_DATA_ENABLED
        return bool(JUGAAD_DATA_ENABLED)
    except Exception:
        return True


def get_jugaad_price(symbol: str) -> Optional[float]:
    """
    Fetch live stock price from NSE via jugaad-data NSELive.
    Returns float price or None if unavailable.
    """
    if not is_jugaad_enabled():
        return None

    global _LIVE_NSE
    sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()

    try:
        from jugaad_data.nse import NSELive
        if _LIVE_NSE is None:
            _LIVE_NSE = NSELive()

        quote = _LIVE_NSE.stock_quote(sym)
        if isinstance(quote, dict):
            price_info = quote.get("priceInfo", {})
            lp = price_info.get("lastPrice") or price_info.get("close")
            if lp and float(lp) > 0:
                return float(lp)
    except Exception as exc:
        logger.debug("jugaad_data stock_quote failed for %s: %s", sym, exc)

    return None


def get_jugaad_ohlcv(symbol: str, lookback_days: int = 40) -> Optional[pd.DataFrame]:
    """
    Fetch historical daily OHLCV bars from official NSE Bhavcopy via jugaad-data.
    Returns standardized DataFrame matching modules.fetch conventions:
      columns: ['date', 'open', 'high', 'low', 'close', 'volume', 'vwap', 'delivery_qty', 'delivery_pct']
    """
    if not is_jugaad_enabled():
        return None

    sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=lookback_days)

    try:
        from jugaad_data.nse import stock_df
        df = stock_df(symbol=sym, from_date=start_date, to_date=end_date, series="EQ")
        if df is None or df.empty or len(df) < 5:
            return None

        # Standardize column names (lowercase)
        rename_map = {
            "DATE": "date",
            "OPEN": "open",
            "HIGH": "high",
            "LOW": "low",
            "CLOSE": "close",
            "VOLUME": "volume",
            "VWAP": "vwap",
            "DELIVERY QTY": "delivery_qty",
            "DELIVERY %": "delivery_pct",
        }
        df = df.rename(columns=rename_map)

        # Sort chronologically ascending
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            df.index = pd.DatetimeIndex(df["date"])

        # Ensure numeric columns
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["close"])
        return df

    except Exception as exc:
        logger.debug("jugaad_data stock_df failed for %s: %s", sym, exc)
        return None


def get_jugaad_delivery_metrics(symbol: str) -> Optional[dict]:
    """
    Compute institutional delivery accumulation metrics from official NSE Bhavcopy.
    Returns:
      {
        'delivery_pct': float,         # Latest delivery percentage (e.g. 52.4%)
        'avg_delivery_pct_5d': float,  # 5-day average delivery %
        'is_accumulation': bool,       # Delivery % > 50% and increasing
      }
    """
    df = get_jugaad_ohlcv(symbol, lookback_days=15)
    if df is None or df.empty or "delivery_pct" not in df.columns:
        return None

    try:
        deliv = pd.to_numeric(df["delivery_pct"], errors="coerce").dropna()
        if len(deliv) < 2:
            return None

        latest_deliv = float(deliv.iloc[-1])
        avg_5d = float(deliv.tail(5).mean())
        is_accum = bool(latest_deliv >= 50.0 and latest_deliv >= avg_5d)

        return {
            "symbol": symbol.upper(),
            "delivery_pct": round(latest_deliv, 2),
            "avg_delivery_pct_5d": round(avg_5d, 2),
            "is_accumulation": is_accum,
        }
    except Exception as exc:
        logger.debug("Failed computing delivery metrics for %s: %s", symbol, exc)
        return None
