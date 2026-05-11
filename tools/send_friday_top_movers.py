"""Send top intraday movers for a historical date to Telegram."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
from typing import Iterable

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _active_symbols(limit: int | None = None) -> list[str]:
    from config import DB_PATH

    symbols: list[str] = []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT symbol FROM stock_universe WHERE is_active=1 ORDER BY symbol"
            ).fetchall()
        symbols = [str(r[0]).strip().upper() for r in rows if r and r[0]]
    except Exception:
        symbols = []

    if not symbols:
        from modules.scanner import get_universe

        symbols = [str(s).strip().upper() for s in get_universe()]

    cleaned = []
    for symbol in symbols:
        if not symbol or symbol.isdigit():
            continue
        if any(ch.isspace() for ch in symbol):
            continue
        cleaned.append(symbol)

    return cleaned[:limit] if limit else cleaned


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _download_batch(symbols: list[str], target: dt.date) -> list[dict]:
    import yfinance as yf
    from modules.fetch import SYMBOL_ALIASES

    ticker_to_symbol = {}
    tickers = []
    for symbol in symbols:
        alias = SYMBOL_ALIASES.get(symbol, symbol)
        ticker = f"{alias}.NS"
        tickers.append(ticker)
        ticker_to_symbol[ticker] = symbol

    start = target.isoformat()
    end = (target + dt.timedelta(days=1)).isoformat()
    try:
        data = yf.download(
            tickers,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=True,
            group_by="ticker",
            progress=False,
            threads=True,
        )
    except Exception:
        return []

    if data is None or data.empty:
        return []

    rows = []
    for ticker in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if ticker not in data.columns.get_level_values(0):
                    continue
                df = data[ticker].dropna(how="all")
            else:
                df = data.dropna(how="all")
            if df.empty:
                continue

            row = df.iloc[0]
            open_price = float(row.get("Open", row.get("open", 0)) or 0)
            high_price = float(row.get("High", row.get("high", 0)) or 0)
            close_price = float(row.get("Close", row.get("close", 0)) or 0)
            volume = float(row.get("Volume", row.get("volume", 0)) or 0)
            if open_price <= 0 or high_price <= 0 or close_price <= 0:
                continue

            open_to_high = (high_price - open_price) / open_price * 100
            open_to_close = (close_price - open_price) / open_price * 100
            rows.append(
                {
                    "symbol": ticker_to_symbol[ticker],
                    "open": open_price,
                    "high": high_price,
                    "close": close_price,
                    "volume": volume,
                    "open_to_high": open_to_high,
                    "open_to_close": open_to_close,
                }
            )
        except Exception:
            continue

    return rows


def scan_top_movers(target: dt.date, limit: int | None = None, batch_size: int = 120) -> list[dict]:
    symbols = _active_symbols(limit=limit)
    movers: list[dict] = []
    total_batches = max((len(symbols) + batch_size - 1) // batch_size, 1)

    for idx, batch in enumerate(_chunks(symbols, batch_size), start=1):
        print(f"Scanning batch {idx}/{total_batches} ({len(batch)} symbols)...", flush=True)
        movers.extend(_download_batch(batch, target))

    movers.sort(key=lambda r: (r["open_to_high"], r["open_to_close"]), reverse=True)
    return movers


def _format_message(target: dt.date, movers: list[dict], top_n: int) -> str:
    if not movers:
        return (
            f"<b>FRIDAY INTRADAY TOP MOVERS</b>\n"
            f"Date: {target.isoformat()}\n\n"
            "No historical OHLC rows were available for the active universe.\n\n"
            "<i>Research only. Not a trade recommendation.</i>"
        )

    lines = [
        "<b>FRIDAY INTRADAY TOP MOVERS</b>",
        f"Date: {target.isoformat()}",
        f"Scanned: {len(movers)} symbols with data",
        "",
    ]
    for i, row in enumerate(movers[:top_n], start=1):
        lines.append(
            f"{i}. <b>{row['symbol']}</b> | "
            f"O-H +{row['open_to_high']:.2f}% | "
            f"O-C {row['open_to_close']:+.2f}% | "
            f"O {row['open']:.2f} H {row['high']:.2f} C {row['close']:.2f}"
        )

    lines.append("")
    lines.append("<i>Ranked by open-to-high move. Research only. Not a trade recommendation.</i>")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-05-08")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--limit", type=int, default=0, help="Optional symbol limit for testing")
    parser.add_argument("--no-send", action="store_true")
    args = parser.parse_args()

    target = dt.date.fromisoformat(args.date)
    movers = scan_top_movers(target, limit=args.limit or None)
    message = _format_message(target, movers, args.top)
    print(message)

    if args.no_send:
        return 0

    from modules.alerts import send_raw_alert

    ok = send_raw_alert(message, review_with_grok=False)
    print(f"Telegram sent: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
