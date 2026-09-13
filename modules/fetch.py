"""
fetch.py — Centralised, robust OHLCV / price fetching for NSE symbols.

Fetch strategy (in order):
  1. yfinance  <alias>.NS  — up to 3 retries with 2s delay between each
  2. yfinance  <alias>.BO  — BSE fallback
  3. jugaad-data NSELive   — if yfinance completely fails (rate-limited / blocked)
  4. Returns None if all sources fail (never raises, never crashes)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# ── Symbol alias map ───────────────────────────────────────────────────────────
# Key   = canonical NSE symbol (as stored in DB / universe, NO suffix)
# Value = Yahoo Finance ticker prefix (without exchange suffix)
SYMBOL_ALIASES: dict[str, str] = {
    "TATAMOTORS": "TMCV",    # Tata Motors split into two entities in 2024
    # Add more as Yahoo Finance renames tickers:
    # "OLDNAME": "NEWNAME",
}

# ── Config ─────────────────────────────────────────────────────────────────────
_MAX_RETRIES     = 3
_RETRY_DELAY     = 2.0   # seconds between retries
_CALL_DELAY      = 0.3   # seconds between consecutive yfinance calls (reduced from 1.5)
_MIN_ROWS        = 20    # minimum rows for OHLCV to be considered valid


# ── Internal helpers ───────────────────────────────────────────────────────────

def _clean_symbol(symbol: str) -> str:
    """Strip any exchange suffix (.NS / .BO / .BSE) and upper-case."""
    sym = symbol.upper().strip()
    for sfx in (".NS", ".BO", ".BSE", ".NSE"):
        if sym.endswith(sfx):
            sym = sym[: -len(sfx)]
    return sym


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns, lower-case all names, and drop NaN prices."""
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [
        c[0].lower() if isinstance(c, tuple) else str(c).lower()
        for c in df.columns
    ]
    if "close" in df.columns:
        df = df.dropna(subset=["close"])
    return df


def _min_rows_for_period(period: str) -> int:
    period = str(period).lower().strip()
    if period.endswith("d"):
        try:
            return max(2, min(_MIN_ROWS, int(period[:-1]) - 1))
        except ValueError:
            return 2
    return _MIN_ROWS


def _download_with_retry(ticker_sym: str, period: str) -> Optional[pd.DataFrame]:
    """
    Download yfinance OHLCV with up to _MAX_RETRIES retries.
    Returns None on all failures (caller handles fallback).
    """
    import yfinance as yf

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            df = yf.download(
                ticker_sym,
                period=period,
                interval="1d",
                auto_adjust=True,
                progress=False,
            )
            min_rows = _min_rows_for_period(period)
            if df is not None and not df.empty and len(df) >= min_rows:
                logger.debug("yfinance OK: %s (%s rows)", ticker_sym, len(df))
                return df
            # Empty result but no exception — likely a genuine 404 / delisted
            logger.debug("yfinance empty result for %s (attempt %s)", ticker_sym, attempt)
            return None

        except Exception as exc:
            exc_name = type(exc).__name__
            is_rate_limit = "RateLimit" in exc_name or "429" in str(exc)

            if is_rate_limit:
                wait = _RETRY_DELAY * attempt
                logger.warning(
                    "Rate-limited on %s — waiting %.0fs (attempt %s/%s)",
                    ticker_sym, wait, attempt, _MAX_RETRIES,
                )
                time.sleep(wait)
            else:
                logger.exception("yfinance error for %s (attempt %s/%s)", ticker_sym, attempt, _MAX_RETRIES)
                return None   # 404, connection reset, etc — don't retry

    logger.debug("All %s yfinance attempts failed for %s", _MAX_RETRIES, ticker_sym)
    return None


def _jugaad_fallback(symbol: str, period_days: int = 60) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV via jugaad-data official NSE Bhavcopy as last-resort fallback.
    Returns DataFrame with columns [open, high, low, close, volume] or None.
    """
    try:
        from modules.jugaad_provider import get_jugaad_ohlcv
        df = get_jugaad_ohlcv(symbol, lookback_days=period_days)
        if df is not None and not df.empty and len(df) >= 5:
            logger.info("jugaad bhavcopy fallback OK for %s (%d rows)", symbol, len(df))
            return df
    except Exception as exc:
        logger.debug("jugaad bhavcopy fallback failed for %s: %s", symbol, exc)

    try:
        from jugaad_data.nse import NSELive
        import datetime

        nse = NSELive()
        quote = nse.stock_quote(symbol)
        if not quote:
            return None

        price_info = quote.get("priceInfo", {})
        last_price = price_info.get("lastPrice") or price_info.get("close")
        if not last_price:
            return None

        today = datetime.date.today()
        df = pd.DataFrame([{
            "open":   price_info.get("open", last_price),
            "high":   price_info.get("intraDayHighLow", {}).get("max", last_price),
            "low":    price_info.get("intraDayHighLow", {}).get("min", last_price),
            "close":  last_price,
            "volume": quote.get("marketDeptOrderBook", {}).get("tradeInfo", {}).get("totalTradedVolume", 0),
        }], index=[pd.Timestamp(today)])

        logger.info("jugaad snapshot fallback OK for %s price=%.2f", symbol, last_price)
        return df

    except ImportError:
        logger.debug("jugaad-data not installed, skipping fallback")
        return None
    except Exception as exc:
        logger.exception("jugaad fallback failed for %s", symbol)
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    """
    Download daily OHLCV for *symbol* (NSE canonical name, no suffix needed).

    Strategy
    --------
    1. Clean symbol (strip any .NS/.BO suffix)
    2. Resolve alias  (e.g. TATAMOTORS → TMCV)
    3. Try <alias>.NS  with retry + 2s delay
    4. Sleep 1.5s, try <alias>.BO
    5. If alias differs from original, try original.NS / original.BO
    6. jugaad-data NSELive fallback
    7. Return None with WARNING (never raises, never crashes)
    """
    symbol = _clean_symbol(symbol)
    alias  = SYMBOL_ALIASES.get(symbol, symbol)

    # Build candidate list: alias.NS → alias.BO → (if alias≠sym) sym.NS → sym.BO
    candidates: list[str] = [f"{alias}.NS", f"{alias}.BO"]
    if alias != symbol:
        candidates += [f"{symbol}.NS", f"{symbol}.BO"]

    for ticker_sym in candidates:
        df = _download_with_retry(ticker_sym, period)
        time.sleep(_CALL_DELAY)   # polite pause between calls
        if df is not None and not df.empty:
            return _normalize_columns(df)

    # Last resort: jugaad-data
    df = _jugaad_fallback(symbol)
    if df is not None and not df.empty:
        return _normalize_columns(df)

    logger.warning("fetch_ohlcv: no data for %s (tried %s + jugaad)", symbol, candidates)
    return None


def fetch_price(symbol: str) -> Optional[float]:
    """
    Return the latest close price for *symbol*.
    Tries yfinance fast_info first, then history, then jugaad.
    Returns None on total failure (never raises).
    """
    import yfinance as yf

    symbol = _clean_symbol(symbol)
    alias  = SYMBOL_ALIASES.get(symbol, symbol)

    candidates = [f"{alias}.NS", f"{alias}.BO"]
    if alias != symbol:
        candidates += [f"{symbol}.NS", f"{symbol}.BO"]

    for ticker_sym in candidates:
        try:
            ticker = yf.Ticker(ticker_sym)
            # fast_info is cheapest (cached metadata, no extra HTTP)
            fi = getattr(ticker, "fast_info", None)
            if fi:
                try:
                    price = float(fi.last_price)
                    if price > 0:
                        return price
                except Exception:
                    pass

            # Fallback to history
            hist = ticker.history(period="2d", interval="1d")
            if hist is not None and not hist.empty:
                val = float(hist["Close"].iloc[-1])
                if val > 0:
                    return val
        except Exception as exc:
            logger.debug("fetch_price error for %s (%s): %s", symbol, ticker_sym, exc)
        time.sleep(0.3)

    # 1. DhanHQ live broker quote fallback
    try:
        from modules.dhan_provider import is_dhan_configured, get_dhan_price
        if is_dhan_configured():
            dp = get_dhan_price(symbol)
            if dp and dp > 0:
                logger.info("fetch_price: DhanHQ fallback OK for %s price=%.2f", symbol, dp)
                return dp
    except Exception as exc:
        logger.debug("fetch_price: DhanHQ fallback failed for %s: %s", symbol, exc)

    # 2. jugaad-data NSE live quote fallback
    try:
        from modules.jugaad_provider import get_jugaad_price
        jp = get_jugaad_price(symbol)
        if jp and jp > 0:
            logger.info("fetch_price: jugaad live fallback OK for %s price=%.2f", symbol, jp)
            return jp
    except Exception as exc:
        logger.debug("fetch_price: jugaad live fallback failed for %s: %s", symbol, exc)

    # 3. jugaad bhavcopy / snapshot fallback for price
    df = _jugaad_fallback(symbol)
    if df is not None and not df.empty and "close" in df.columns:
        return float(df["close"].iloc[-1])

    return None
