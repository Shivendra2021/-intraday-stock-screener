"""Cached market data with Angel One primary and fail-closed free fallbacks."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time

import numpy as np
import pandas as pd
import requests

from modules.quant_store import Store
from modules.quant_time import now_ist

LOG = logging.getLogger(__name__)
IST = "Asia/Kolkata"
_session = None


def normalize(frame, interval):
    if frame is None or frame.empty:
        return pd.DataFrame()
    frame = frame.copy()
    frame.columns = [str(x[0] if isinstance(x, tuple) else x).lower() for x in frame.columns]
    required = ["open", "high", "low", "close", "volume"]
    if not set(required) <= set(frame.columns):
        return pd.DataFrame()
    frame = frame[required].apply(pd.to_numeric, errors="coerce").dropna()
    idx = pd.DatetimeIndex(frame.index)
    frame.index = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    valid = (np.isfinite(frame).all(axis=1) & (frame["low"] > 0) & (frame["volume"] >= 0)
             & (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
             & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)))
    frame = frame[valid]
    if interval != "1d":
        frame = frame.between_time("09:15", "15:29")
    return frame


def universe():
    from config import DB_PATH
    try:
        with sqlite3.connect(f"file:{os.path.abspath(DB_PATH)}?mode=ro", uri=True) as c:
            rows = c.execute("SELECT symbol,sector FROM stock_universe WHERE is_active=1 ORDER BY symbol").fetchall()
        symbols = {str(s): str(sec or "Unknown") for s, sec in rows
                   if re.fullmatch(r"[A-Z0-9&._-]+", str(s))}
        if symbols:
            return symbols
    except sqlite3.Error:
        pass
    from modules.scanner import SMALL_MIDCAP_FALLBACK
    return dict.fromkeys(SMALL_MIDCAP_FALLBACK, "Unknown")


def _worker(request):
    import yfinance as yf
    store = Store(request["path"])
    symbols = request["symbols"]
    tickers = [s + ".NS" for s in symbols]
    kwargs = dict(interval=request["interval"], auto_adjust=False, progress=False,
                  group_by="ticker", threads=4, timeout=10)
    if request.get("start"):
        kwargs["start"] = request["start"]
    else:
        kwargs["period"] = request["period"]
    data = yf.download(tickers, **kwargs)
    updated = []
    for symbol, ticker in zip(symbols, tickers):
        try:
            frame = data[ticker] if isinstance(data.columns, pd.MultiIndex) else data
            frame = normalize(frame, request["interval"])
            if not frame.empty:
                store.save_bars(symbol, request["interval"], frame, "yahoo")
                updated.append(symbol)
        except (KeyError, ValueError):
            continue
    return {"updated": updated}


class DataService:
    def __init__(self, store=None):
        self.store = store or Store()
        from modules.angel_data import AngelDataProvider
        self.angel = AngelDataProvider(self.store)

    def _angel_refresh(self, symbols, interval, period, budget):
        if not self.angel.configured() or budget <= 2:
            return []
        started, updated = time.monotonic(), []
        days = 365 if period == "1y" else int(re.sub(r"\D", "", str(period)) or 59)
        end = now_ist().date()
        start = end - dt.timedelta(days=days)
        for symbol in symbols:
            if time.monotonic() - started >= budget:
                break
            frame = normalize(self.angel.candles(symbol, interval, start, end), interval)
            if not frame.empty:
                self.store.save_bars(symbol, interval, frame, "angel_one")
                updated.append(symbol)
        return updated

    def refresh(self, symbols, interval="5m", period="59d", budget=90, force=False):
        """Download batches in killable children; keep valid cache on failure.

        A timed-out download is never counted as fresh. No change to the source
        timestamp occurs when a cached candle is read.
        """
        started = time.monotonic()
        symbols = list(dict.fromkeys(symbols))
        now = now_ist()
        bucket = now.strftime("%Y-%m-%d") if interval == "1d" else str(int(now.timestamp()) // 300)
        last = self.store.get("downloads", {})
        pending = [s for s in symbols if force or last.get(f"{interval}:{s}") != bucket]
        angel_updated = self._angel_refresh(pending, interval, period, min(budget * .55, 45))
        for symbol in angel_updated:
            last[f"{interval}:{symbol}"] = bucket
        pending = [s for s in pending if s not in angel_updated]
        updated, failed = [], []
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for offset in range(0, len(pending), 20):
            left = budget - (time.monotonic() - started)
            if left <= 2:
                break
            batch = pending[offset:offset + 20]
            request = {"path": os.path.abspath(self.store.path), "symbols": batch,
                       "interval": interval, "period": period}
            # Re-fetch overlap for corrections; avoid repeatedly pulling full history.
            if not force:
                with self.store.connect() as c:
                    maxima = [c.execute("SELECT MAX(ts) FROM bars WHERE symbol=? AND interval=?", (s, interval)).fetchone()[0] for s in batch]
                if all(maxima):
                    overlap = 5 * 86400 if interval == "1d" else 86400
                    request["start"] = dt.datetime.fromtimestamp(min(maxima) - overlap, dt.timezone.utc).strftime("%Y-%m-%d")
            try:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                proc = subprocess.run([sys.executable, "-B", "-m", "modules.quant_data"],
                                      input=json.dumps(request), capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", cwd=root, env=env,
                                      timeout=min(45, left))
                result = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.returncode == 0 else {}
                good = result.get("updated", [])
            except (subprocess.TimeoutExpired, ValueError, IndexError):
                good = []
            updated.extend(good)
            failed.extend(s for s in batch if s not in good)
            for s in good:
                last[f"{interval}:{s}"] = bucket
            self.store.put("downloads", last)
        updated = angel_updated + updated
        result = {"requested": len(symbols), "cache_hits": len(symbols) - len(pending) - len(angel_updated),
                  "updated": len(updated), "failed": len(failed),
                  "deferred": max(0, len(symbols) - len(updated) - len(failed) - (len(symbols) - len(pending) - len(angel_updated))),
                  "elapsed_seconds": round(time.monotonic() - started, 3), "interval": interval}
        source = "angel_one+yahoo" if angel_updated and len(updated) > len(angel_updated) else ("angel_one" if angel_updated else "yahoo")
        self.store.put("data_health", {**result, "checked_at": now.isoformat(), "source": source,
                                       "angel_updated": len(angel_updated), "fallback_updated": len(updated)-len(angel_updated)})
        return result

    def backfill(self, symbols, target_sessions=None, budget=600):
        """Resumable Angel five-minute backfill; only complete 75-bar NSE sessions survive."""
        from config import QUANT_BACKFILL_TARGET_SESSIONS, ANGEL_HISTORY_BATCH_DAYS
        target = target_sessions or QUANT_BACKFILL_TARGET_SESSIONS
        if not self.angel.configured():
            result = {"status": "not_configured", "target_sessions": target, "updated": 0}
            self.store.put("backfill", result)
            return result
        symbols = list(dict.fromkeys(symbols))
        cursor = int(self.store.get("angel_backfill_cursor", 0)) % max(1, len(symbols))
        ordered = symbols[cursor:] + symbols[:cursor]
        started, updated, complete_sessions = time.monotonic(), 0, 0
        end = now_ist().date() - dt.timedelta(days=1)
        horizon = max(75, int(target * 1.8))
        start = end - dt.timedelta(days=horizon)
        visited = 0
        for symbol in ordered:
            if time.monotonic() - started >= budget:
                break
            existing = self.store.bars(symbol, "5m")
            counts = existing.groupby(existing.index.date).size() if not existing.empty else pd.Series(dtype=int)
            if int((counts == 75).sum()) >= target:
                visited += 1
                continue
            frames = []
            chunk_start = start
            while chunk_start <= end and time.monotonic() - started < budget:
                chunk_end = min(end, chunk_start + dt.timedelta(days=ANGEL_HISTORY_BATCH_DAYS - 1))
                frame = normalize(self.angel.candles(symbol, "5m", chunk_start, chunk_end), "5m")
                if not frame.empty:
                    frames.append(frame)
                chunk_start = chunk_end + dt.timedelta(days=1)
            if frames:
                frame = pd.concat(frames).sort_index()
                duplicated_dates = set(frame.index[frame.index.duplicated(keep=False)].date)
                counts = frame.groupby(frame.index.date).size()
                positive_volume = frame.groupby(frame.index.date)["volume"].apply(lambda values: bool((values > 0).all()))
                # Very large overnight jumps commonly indicate an unadjusted split/bonus discontinuity.
                daily = frame.groupby(frame.index.date).agg(open=("open", "first"), close=("close", "last"))
                discontinuity = set(daily.index[(daily.open / daily.close.shift(1) - 1).abs() > .45])
                valid_dates = {date for date in counts[counts == 75].index
                               if positive_volume.get(date, False) and date not in duplicated_dates and date not in discontinuity}
                frame = frame[[date in valid_dates for date in frame.index.date]]
                if not frame.empty:
                    self.store.save_bars(symbol, "5m", frame, "angel_one")
                    updated += 1; complete_sessions += len(valid_dates)
            visited += 1
            self.store.put("angel_backfill_cursor", (cursor + visited) % max(1, len(symbols)))
        result = {"status": "complete" if visited == len(symbols) else "backfilling",
                  "target_sessions": target, "visited": visited, "universe": len(symbols),
                  "updated": updated, "complete_sessions_downloaded": complete_sessions,
                  "elapsed_seconds": round(time.monotonic() - started, 3)}
        self.store.put("backfill", result)
        return result

    def get_quote_candidates(self, symbol):
        """
        Obtain independent primary and secondary verified quotes for consensus validation.
        Returns: (primary_quote, secondary_quote)
        """
        def complete(value):
            return bool(value and value.get("series") == "EQ"
                        and all(value.get(k) is not None for k in ("ts", "bid", "ask", "upper", "lower")))

        primary, secondary = None, None

        # 1. Primary quote from Angel One
        q_angel = self.angel.quote(symbol)
        if complete(q_angel):
            q_angel["source"] = "angel_one"
            primary = q_angel

        # 2. Secondary candidate from Dhan
        q_dhan = _dhan_quote(symbol)
        if q_dhan and q_dhan.get("series") == "EQ" and q_dhan.get("ask") and q_dhan.get("ts"):
            if primary is None:
                primary = q_dhan
            else:
                secondary = q_dhan

        # 3. Secondary candidate from NSE if secondary still missing
        if secondary is None:
            q_nse = _nse_quote(symbol)
            if q_nse and q_nse.get("series") == "EQ" and q_nse.get("ask") and q_nse.get("ts"):
                if primary is None:
                    primary = q_nse
                elif primary.get("source") != "nse":
                    secondary = q_nse

        now_time = time.time()
        if primary:
            primary["checked_at"] = now_time
            self.store.put(f"quote:{symbol}", primary)
            self.store.put("quote_health", {
                "status": "verified",
                "source": primary.get("source"),
                "secondary_source": secondary.get("source") if secondary else None,
                "symbol": symbol,
                "checked_at": now_time
            })
        else:
            self.store.put("quote_health", {
                "status": "live_quote_unavailable",
                "symbol": symbol,
                "checked_at": now_time
            })

        return primary, secondary

    def quote(self, symbol):
        primary, _ = self.get_quote_candidates(symbol)
        return primary

    def refresh_1m(self, symbols, budget=30):
        """
        Bounded 1-minute candle ingestion specifically for active signals and open paper trades.
        Never downloads full universe 1m data unnecessarily.
        """
        started = time.monotonic()
        symbols = list(dict.fromkeys(symbols))
        if not symbols or budget <= 2:
            return []
        updated = []
        end_date = now_ist().date()
        start_date = end_date - dt.timedelta(days=2)
        for symbol in symbols:
            if time.monotonic() - started >= budget:
                break
            frame = pd.DataFrame()
            if self.angel.configured():
                try:
                    frame = normalize(self.angel.candles(symbol, "1m", start_date, end_date), "1m")
                except Exception:
                    frame = pd.DataFrame()
            if not frame.empty:
                self.store.save_bars(symbol, "1m", frame, "angel_one")
                updated.append(symbol)
            else:
                try:
                    import yfinance as yf
                    ticker = symbol + ".NS" if not symbol.endswith((".NS", ".BO")) else symbol
                    df = yf.download(ticker, interval="1m", period="2d", progress=False)
                    if not df.empty:
                        norm_df = normalize(df, "1m")
                        if not norm_df.empty:
                            self.store.save_bars(symbol, "1m", norm_df, "yahoo")
                            updated.append(symbol)
                except Exception:
                    pass
        return updated



def _float(value):
    try:
        number = float(str(value).replace(",", ""))
        return number if np.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _epoch(value):
    try:
        stamp = pd.Timestamp(value)
        stamp = stamp.tz_localize(IST) if stamp.tz is None else stamp.tz_convert(IST)
        return int(stamp.timestamp())
    except (ValueError, TypeError):
        return None


def _dhan_quote(symbol):
    from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN, DHAN_ENABLED
    if not (DHAN_ENABLED and DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN):
        return None
    from modules.dhan_provider import get_security_id
    sid = get_security_id(symbol)
    if not sid:
        return None
    try:
        r = requests.post("https://api.dhan.co/v2/marketfeed/quote", timeout=6,
                          headers={"client-id": DHAN_CLIENT_ID, "access-token": DHAN_ACCESS_TOKEN},
                          json={"NSE_EQ": [sid]})
        if r.status_code != 200:
            return None
        d = r.json().get("data", {}).get("NSE_EQ", {}).get(str(sid), {})
        depth = d.get("depth", {})
        bid = (depth.get("buy") or [{}])[0].get("price")
        ask = (depth.get("sell") or [{}])[0].get("price")
        return {"price": _float(d.get("last_price")), "bid": _float(bid), "ask": _float(ask),
                "upper": _float(d.get("upper_circuit_limit")), "ts": _epoch(d.get("last_trade_time")),
                "source": "dhan", "series": "EQ"} if d else None
    except (requests.RequestException, ValueError, TypeError):
        return None


def _nse_quote(symbol):
    global _session
    try:
        if _session is None:
            _session = requests.Session()
            _session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*",
                                     "Referer": "https://www.nseindia.com/get-quotes/equity"})
            _session.get("https://www.nseindia.com", timeout=6)
        r = _session.get("https://www.nseindia.com/api/quote-equity", params={"symbol": symbol, "section": "trade_info"}, timeout=6)
        if r.status_code != 200:
            return None
        trade = r.json()
        r = _session.get("https://www.nseindia.com/api/quote-equity", params={"symbol": symbol}, timeout=6)
        if r.status_code != 200:
            return None
        d = r.json()
        pi, meta = d.get("priceInfo", {}), d.get("metadata", {})
        book = trade.get("marketDeptOrderBook", {})
        return {"price": _float(pi.get("lastPrice")),
                "bid": _float((book.get("bid") or [{}])[0].get("price")),
                "ask": _float((book.get("ask") or [{}])[0].get("price")),
                "upper": _float(pi.get("upperCP")),
                "ts": _epoch(meta.get("lastUpdateTime") or d.get("lastUpdateTime")),
                "series": meta.get("series"), "source": "nse"}
    except (requests.RequestException, ValueError, TypeError):
        return None


if __name__ == "__main__":
    try:
        print(json.dumps(_worker(json.load(sys.stdin))))
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__}))
        raise SystemExit(1)
