"""Read-only Angel One SmartAPI adapter for Quant V3 market data."""
from __future__ import annotations

import datetime as dt
import logging
import socket
import time
from typing import Any

import pandas as pd
import pyotp
import requests

from modules.quant_time import now_ist

LOG = logging.getLogger(__name__)
_AUTH: dict[str, Any] = {}


class AngelDataProvider:
    """Expose authentication, candles and Full Quote only; never order APIs."""

    def __init__(self, store, session=None):
        self.store = store
        self.session = session or requests.Session()

    @staticmethod
    def configured():
        from config import ANGEL_ENABLED, ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET
        return bool(ANGEL_ENABLED and ANGEL_API_KEY and ANGEL_CLIENT_CODE and ANGEL_PIN and ANGEL_TOTP_SECRET)

    def _health(self, status, **fields):
        record = {"status": status, "checked_at": now_ist().isoformat(), **fields}
        self.store.put("angel_health", record)
        return record

    def status(self):
        state = self.store.get("angel_health", {})
        if not self.configured():
            return {"status": "not_configured", "configured": False, **state}
        return {"configured": True, **state}

    def _headers(self, authenticated=False):
        from config import ANGEL_API_KEY
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            local_ip = "127.0.0.1"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "X-UserType": "USER", "X-SourceID": "WEB", "X-ClientLocalIP": local_ip,
                   "X-ClientPublicIP": local_ip, "X-MACAddress": "00:00:00:00:00:00",
                   "X-PrivateKey": ANGEL_API_KEY}
        if authenticated and _AUTH.get("jwt"):
            headers["Authorization"] = "Bearer " + str(_AUTH["jwt"]).removeprefix("Bearer ")
        return headers

    def authenticate(self, force=False):
        from config import ANGEL_BASE_URL, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET, ANGEL_QUOTE_TIMEOUT_SECONDS
        today = str(now_ist().date())
        if not self.configured():
            self._health("not_configured")
            return False
        if not force and _AUTH.get("date") == today and _AUTH.get("jwt"):
            return True
        self._health("authenticating")
        try:
            totp = pyotp.TOTP(ANGEL_TOTP_SECRET.replace(" ", "")).now()
            response = self.session.post(
                ANGEL_BASE_URL.rstrip("/") + "/rest/auth/angelbroking/user/v1/loginByPassword",
                headers=self._headers(), json={"clientcode": ANGEL_CLIENT_CODE, "password": ANGEL_PIN, "totp": totp},
                timeout=ANGEL_QUOTE_TIMEOUT_SECONDS)
            payload = response.json()
            data = payload.get("data") or {}
            if response.status_code != 200 or not payload.get("status") or not data.get("jwtToken"):
                self._health("unavailable", error_code=payload.get("errorcode") or f"http_{response.status_code}")
                return False
            _AUTH.clear(); _AUTH.update({"date": today, "jwt": data["jwtToken"],
                                        "refresh": data.get("refreshToken"), "feed": data.get("feedToken")})
            self._health("ready", authenticated_at=now_ist().isoformat(), expires_at=today + "T23:59:59+05:30")
            return True
        except (requests.RequestException, ValueError, TypeError) as exc:
            self._health("unavailable", error_type=type(exc).__name__)
            return False

    def _post(self, path, body):
        from config import ANGEL_BASE_URL, ANGEL_QUOTE_TIMEOUT_SECONDS
        if not self.authenticate():
            return None
        for attempt in range(2):
            try:
                response = self.session.post(ANGEL_BASE_URL.rstrip("/") + path, headers=self._headers(True),
                                             json=body, timeout=ANGEL_QUOTE_TIMEOUT_SECONDS)
                payload = response.json()
            except (requests.RequestException, ValueError, TypeError) as exc:
                self._health("unavailable", error_type=type(exc).__name__)
                return None
            if response.status_code in (401, 403) and attempt == 0:
                self._health("session_expired")
                if self.authenticate(force=True):
                    continue
            if response.status_code == 429:
                self._health("rate_limited")
                return None
            if response.status_code != 200 or not payload.get("status"):
                self._health("partial_response" if payload.get("data") else "unavailable",
                             error_code=payload.get("errorcode") or f"http_{response.status_code}")
                return None
            return payload
        return None

    def sync_instruments(self, force=False):
        from config import ANGEL_INSTRUMENT_MASTER_URL, ANGEL_QUOTE_TIMEOUT_SECONDS
        cached = self.store.get("angel_instruments", {})
        if not force and cached.get("date") == str(now_ist().date()) and cached.get("symbols"):
            return cached["symbols"]
        if not self.configured():
            self._health("not_configured")
            return cached.get("symbols", {})
        try:
            response = self.session.get(ANGEL_INSTRUMENT_MASTER_URL, timeout=ANGEL_QUOTE_TIMEOUT_SECONDS)
            response.raise_for_status()
            symbols = {}
            for item in response.json():
                symbol = str(item.get("symbol") or "")
                if item.get("exch_seg") == "NSE" and symbol.endswith("-EQ") and item.get("token"):
                    symbols[symbol[:-3]] = {"token": str(item["token"]), "trading_symbol": symbol}
            if not symbols:
                self._health("partial_response", missing="instrument_master")
                return cached.get("symbols", {})
            self.store.put("angel_instruments", {"date": str(now_ist().date()), "symbols": symbols})
            self._health("ready", instrument_count=len(symbols))
            return symbols
        except (requests.RequestException, ValueError, TypeError) as exc:
            self._health("unavailable", error_type=type(exc).__name__)
            return cached.get("symbols", {})

    def full_quotes(self, symbols):
        instruments = self.sync_instruments()
        tokens = [instruments[s]["token"] for s in symbols if s in instruments][:50]
        if not tokens:
            return {}
        payload = self._post("/rest/secure/angelbroking/market/v1/quote/",
                             {"mode": "FULL", "exchangeTokens": {"NSE": tokens}})
        fetched = ((payload or {}).get("data") or {}).get("fetched") or []
        by_token = {str(item.get("token") or item.get("symbolToken")): item for item in fetched}
        output = {}
        for symbol in symbols:
            meta = instruments.get(symbol); item = by_token.get(meta["token"]) if meta else None
            if not item:
                continue
            depth = item.get("depth") or {}
            buy, sell = depth.get("buy") or [], depth.get("sell") or []
            tot_buy = _number(item.get("totBuyQnt")) or sum((_number(b.get("quantity")) or 0) for b in buy)
            tot_sell = _number(item.get("totSellQnt")) or sum((_number(s.get("quantity")) or 0) for s in sell)
            quote = {"price": _number(item.get("ltp")), "bid": _number(buy[0].get("price")) if buy else None,
                     "ask": _number(sell[0].get("price")) if sell else None,
                     "tot_buy_qty": tot_buy,
                     "tot_sell_qty": tot_sell,
                     "depth_buy": buy[:5],
                     "depth_sell": sell[:5],
                     "upper": _number(item.get("upperCircuit")), "lower": _number(item.get("lowerCircuit")),
                     "ts": _timestamp(item.get("exchTradeTime") or item.get("exchFeedTime")),
                     "source": "angel_one", "series": "EQ", "token": meta["token"]}
            if all(quote.get(key) is not None for key in ("ts", "bid", "ask", "upper")):
                output[symbol] = quote
        self._health("ready" if len(output) == len(tokens) else "partial_response",
                     quote_requested=len(tokens), quote_verified=len(output),
                     missing_symbols=[symbol for symbol in symbols if symbol not in output])
        return output

    def get_preopen_auction_depth(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch Level-2 pre-open order book depth for calculating Auction Imbalance Ratio (AIR)."""
        quotes = self.full_quotes(symbols)
        result = {}
        for sym, q in quotes.items():
            tot_buy = float(q.get("tot_buy_qty") or 0.0)
            tot_sell = max(1.0, float(q.get("tot_sell_qty") or 1.0))
            air = round(tot_buy / tot_sell, 2)
            bid = q.get("bid")
            ask = q.get("ask")
            spread_pct = 0.0
            if bid and ask and bid > 0:
                spread_pct = round(((ask - bid) / bid) * 100, 3)
            result[sym] = {
                "tot_buy_qty": tot_buy,
                "tot_sell_qty": tot_sell,
                "air_ratio": air,
                "bid": bid,
                "ask": ask,
                "spread_pct": spread_pct,
                "source": "angel_one_live"
            }
        return result

    def quote(self, symbol):
        return self.full_quotes([symbol]).get(symbol)

    def candles(self, symbol, interval, start, end):
        instruments = self.sync_instruments()
        meta = instruments.get(symbol)
        if not meta:
            return pd.DataFrame()
        angel_interval = "FIVE_MINUTE" if interval == "5m" else "ONE_DAY"
        payload = self._post("/rest/secure/angelbroking/historical/v1/getCandleData",
                             {"exchange": "NSE", "symboltoken": meta["token"], "interval": angel_interval,
                              "fromdate": _format_date(start, interval, False),
                              "todate": _format_date(end, interval, True)})
        rows = (payload or {}).get("data") or []
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"]).set_index("timestamp")


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    try:
        stamp = pd.Timestamp(value)
        stamp = stamp.tz_localize("Asia/Kolkata") if stamp.tz is None else stamp.tz_convert("Asia/Kolkata")
        return int(stamp.timestamp())
    except (TypeError, ValueError):
        return None


def _format_date(value, interval, end):
    value = pd.Timestamp(value).date()
    clock = "15:30" if end else "09:15"
    return f"{value} {clock}" if interval == "5m" else f"{value} 00:00"


def get_live_angel_depth(symbols: list[str]) -> dict[str, dict]:
    """Module-level convenience helper to get live pre-open Level-2 depth if configured."""
    try:
        from modules.quant_store import QuantStore
        provider = AngelDataProvider(QuantStore())
        if provider.configured() and provider.authenticate():
            return provider.get_preopen_auction_depth(symbols)
    except Exception as exc:
        LOG.debug("Angel live depth fetch error: %s", exc)
    return {}

