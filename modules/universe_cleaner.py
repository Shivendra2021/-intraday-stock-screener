# MarketMind Pro - Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.

"""
universe_cleaner.py - Validate active NSE symbols with batched price data checks.

The exchange universe can contain stale names or symbols that no longer return
market data. This module keeps the database and in-memory scanner cache aligned
to the symbols that still have recent OHLCV data.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from typing import Iterable

import pandas as pd

logger = logging.getLogger(__name__)


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _is_nse_equity_symbol(symbol: str) -> bool:
    symbol = _normalize_symbol(symbol)
    if not symbol or symbol.isdigit():
        return False
    # Yahoo NSE symbols do not accept already-suffixed or index-like values here.
    return "." not in symbol and "^" not in symbol


def _extract_close(df: pd.DataFrame, ticker: str) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)

    if isinstance(df.columns, pd.MultiIndex):
        level0 = [str(v).upper() for v in df.columns.get_level_values(0)]
        level1 = [str(v).upper() for v in df.columns.get_level_values(1)]
        ticker_u = ticker.upper()

        if ticker_u in level0:
            sub = df[ticker]
            for col in sub.columns:
                if str(col).lower() == "close":
                    return pd.to_numeric(sub[col], errors="coerce")

        if ticker_u in level1:
            for col in df.columns:
                if str(col[0]).lower() == "close" and str(col[1]).upper() == ticker_u:
                    return pd.to_numeric(df[col], errors="coerce")

        return pd.Series(dtype=float)

    for col in df.columns:
        if str(col).lower() == "close":
            return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(dtype=float)


def _has_recent_price(close: pd.Series) -> bool:
    if close is None or close.empty:
        return False
    close = close.dropna()
    if close.empty:
        return False
    return bool((close.tail(5) > 0).any())


def _mark_symbols(active_symbols: list[str], inactive_symbols: list[str]) -> None:
    from config import DB_PATH

    today = datetime.date.today().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        for symbol in active_symbols:
            conn.execute(
                """
                UPDATE stock_universe
                   SET is_active = 1,
                       last_verified = ?
                 WHERE symbol = ?
                """,
                (today, symbol),
            )
        for symbol in inactive_symbols:
            conn.execute(
                """
                UPDATE stock_universe
                   SET is_active = 0,
                       last_verified = ?
                 WHERE symbol = ?
                """,
                (today, symbol),
            )
        conn.commit()


def _load_active_nse_symbols() -> list[str]:
    from config import DB_PATH

    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                """
                SELECT symbol
                  FROM stock_universe
                 WHERE is_active = 1
                   AND UPPER(COALESCE(exchange, 'NSE')) = 'NSE'
                 ORDER BY symbol
                """
            ).fetchall()
        return [_normalize_symbol(row[0]) for row in rows if _is_nse_equity_symbol(row[0])]
    except Exception as exc:
        logger.warning("Could not load active NSE symbols from DB: %s", exc)
        return []


def _confirm_inactive_with_nse(symbols: list[str]) -> tuple[list[str], list[str]]:
    """
    Confirm Yahoo no-data symbols with NSE before marking inactive.

    Yahoo batch downloads can produce false negatives for active NSE names. A
    symbol is only treated as inactive when both Yahoo and NSE quote checks fail.
    """
    if not symbols:
        return [], []

    rescued: list[str] = []
    confirmed_inactive: list[str] = []

    try:
        from modules.price_validation import nse_price
    except Exception as exc:
        logger.warning("NSE quote confirmation unavailable; leaving %s symbols unverified: %s", len(symbols), exc)
        return [], []

    for symbol in symbols:
        try:
            price = nse_price(symbol)
            if price and price > 0:
                rescued.append(symbol)
            else:
                confirmed_inactive.append(symbol)
        except Exception:
            confirmed_inactive.append(symbol)

    logger.info(
        "NSE confirmation complete: rescued=%s confirmed_inactive=%s",
        len(rescued),
        len(confirmed_inactive),
    )
    return rescued, confirmed_inactive


def _sync_scanner_cache(active_symbols: list[str]) -> None:
    try:
        import modules.scanner as scanner

        scanner._universe_cache = list(active_symbols)
    except Exception as exc:
        logger.debug("Could not sync scanner cache: %s", exc)


def prune_delisted_symbols(
    symbols: list[str],
    batch_size: int | None = None,
    persist: bool = True,
) -> dict:
    """
    Return and optionally persist active/inactive symbols using recent NSE prices.

    A symbol is considered active when Yahoo Finance returns at least one recent
    positive close for SYMBOL.NS. Symbols that fail this test are marked inactive
    so later analysis jobs do not waste time on dead tickers.
    """
    from config import UNIVERSE_VALIDATION_BATCH_SIZE, UNIVERSE_VALIDATION_LOOKBACK_DAYS

    import yfinance as yf

    batch_size = int(batch_size or UNIVERSE_VALIDATION_BATCH_SIZE or 200)
    lookback = max(2, int(UNIVERSE_VALIDATION_LOOKBACK_DAYS or 5))

    clean_symbols = []
    skipped_symbols = []
    for symbol in symbols or []:
        symbol = _normalize_symbol(symbol)
        if _is_nse_equity_symbol(symbol):
            clean_symbols.append(symbol)
        elif symbol:
            skipped_symbols.append(symbol)

    clean_symbols = sorted(set(clean_symbols))
    active: list[str] = []
    inactive: list[str] = []
    unverified: list[str] = []

    logger.info("Validating %s NSE symbols in batches of %s", len(clean_symbols), batch_size)
    for batch in _chunks(clean_symbols, batch_size):
        from modules.fetch import SYMBOL_ALIASES
        tickers = [f"{SYMBOL_ALIASES.get(symbol.upper(), symbol)}.NS" for symbol in batch]
        try:
            data = yf.download(
                tickers if len(tickers) > 1 else tickers[0],
                period=f"{lookback}d",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            logger.warning("Price validation batch failed (%s symbols): %s", len(batch), exc)
            unverified.extend(batch)
            continue

        if (data is None or data.empty) and len(batch) > 1:
            logger.warning("Price validation batch returned no data; leaving %s symbols unchanged", len(batch))
            unverified.extend(batch)
            continue

        for symbol, ticker in zip(batch, tickers):
            close = _extract_close(data, ticker)
            if _has_recent_price(close):
                active.append(symbol)
            else:
                inactive.append(symbol)

    inactive.extend(skipped_symbols)
    active = sorted(set(active))
    inactive = sorted(set(inactive) - set(active))
    unverified = sorted(set(unverified) - set(active) - set(inactive))

    if inactive:
        original_inactive = list(inactive)
        rescued, confirmed_inactive = _confirm_inactive_with_nse(inactive)
        active = sorted(set(active + rescued))
        inactive = sorted(set(confirmed_inactive) - set(active))
        unverified.extend(sorted(set(original_inactive) - set(rescued) - set(confirmed_inactive)))
        unverified = sorted(set(unverified) - set(active) - set(inactive))

    if persist:
        _mark_symbols(active, inactive)
        _sync_scanner_cache(active)

    logger.info(
        "Universe price validation complete: active=%s inactive_or_delisted=%s unverified=%s",
        len(active),
        len(inactive),
        len(unverified),
    )

    return {
        "active_symbols": active,
        "inactive_symbols": inactive,
        "active_count": len(active),
        "inactive_count": len(inactive),
        "unverified_count": len(unverified),
        "checked_count": len(clean_symbols),
        "skipped_count": len(skipped_symbols),
    }


def refresh_and_clean_universe(force_refresh: bool = True) -> dict:
    """
    Refresh exchange symbols, validate NSE price availability, and sync cache.
    """
    from modules.scanner import get_universe

    if force_refresh:
        get_universe(force_refresh=True)

    symbols = _load_active_nse_symbols()
    if not symbols:
        symbols = [s for s in get_universe(force_refresh=False) if _is_nse_equity_symbol(s)]

    return prune_delisted_symbols(symbols, persist=True)
