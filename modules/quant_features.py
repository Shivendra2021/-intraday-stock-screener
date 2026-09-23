"""Identical point-in-time features for historical replay and live decisions."""
from __future__ import annotations

import numpy as np
import pandas as pd
import datetime as dt
from functools import lru_cache

VERSION = "q3.1"
FEATURES = ("gap_pct", "rvol", "atr_pct", "range_atr", "vwap_distance",
            "opening_breakout", "compression", "momentum", "close_location",
            "daily_trend", "rsi", "time_fraction", "log_turnover")


@lru_cache(maxsize=512)
def previous_session(date):
    from modules.scanner import is_market_holiday
    previous = date - dt.timedelta(days=1)
    while previous.weekday() >= 5 or is_market_holiday(previous):
        previous -= dt.timedelta(days=1)
    return previous


def daily_features(daily, date):
    history = daily[daily.index.date < date].tail(220)
    if len(history) < 40 or history.index[-1].date() != previous_session(date):
        return None
    close = history["close"]
    # Corporate actions / corrupt data require review, never become momentum.
    if close.pct_change().tail(20).abs().max() > 0.35:
        return None
    tr = pd.concat([history.high - history.low, (history.high - close.shift()).abs(),
                    (history.low - close.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1/14, adjust=False).mean().iloc[-1])
    delta = close.diff()
    gain = float(delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean().iloc[-1])
    loss = float((-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean().iloc[-1])
    rsi = 100 - 100 / (1 + gain / loss) if loss > 0 else (100.0 if gain > 0 else 50.0)
    price = float(close.iloc[-1])
    if price <= 0 or atr <= 0 or not np.isfinite(atr):
        return None
    return {"prev_close": price, "atr": atr, "atr_pct": atr / price * 100,
            "daily_trend": (price / float(close.ewm(span=20, adjust=False).mean().iloc[-1]) - 1) * 100,
            "rsi": rsi, "turnover": float((history.close * history.volume).tail(20).median())}


def build_features(symbol, daily, intraday, asof, sector="Unknown", prepared=None):
    """Exclude unfinished bars and today's daily candle; no future labels enter X."""
    from config import QUANT_COST_BPS, QUANT_SLIPPAGE_BPS
    asof = pd.Timestamp(asof)
    asof = asof.tz_localize("Asia/Kolkata") if asof.tz is None else asof.tz_convert("Asia/Kolkata")
    date = asof.date()
    base = prepared or daily_features(daily, date)
    if not base or intraday.empty:
        return None
    complete = intraday[intraday.index + pd.Timedelta(minutes=5) <= asof]
    day = complete[complete.index.date == date]
    if len(day) < 4 or day.index[0].strftime("%H:%M") != "09:15":
        return None
    expected = int((day.index[-1] - day.index[0]).total_seconds() / 300) + 1
    if len(day) != expected or (day.volume <= 0).any():
        return None
    ts = day.index[-1] + pd.Timedelta(minutes=5)
    previous = complete[(complete.index.date < date) & (complete.index.time <= day.index[-1].time())]
    totals = previous.groupby(previous.index.date).volume.agg(["sum", "count"]).tail(20)
    totals = totals[totals["count"] == len(day)]
    if len(totals) < 5 or float(totals["sum"].median()) <= 0:
        return None
    px = float(day.close.iloc[-1])
    op = float(day.open.iloc[0])
    if abs(op / base["prev_close"] - 1) > 0.35:
        return None
    rvol = float(day.volume.sum() / totals["sum"].median())
    typical = (day.high + day.low + day.close) / 3
    vwap = float((typical * day.volume).sum() / day.volume.sum())
    opening_high = float(day.high.iloc[:3].max())
    prior = day.iloc[:-1].tail(3)
    width = float(prior.high.max() - prior.low.min())
    breakout = px > opening_high and float(day.close.iloc[-2]) <= opening_high
    compressed = width < 0.45 * base["atr"] and px > float(prior.high.max())
    continuation = (len(day) >= 6 and px > vwap and float(day.low.iloc[-3:-1].min()) <= vwap * 1.003
                    and px > float(day.high.iloc[-2]))
    # Dedicated 7% to 10% Super-Runner Setup:
    # High-Beta stock (Daily ATR >= 2.8%), breaking out above 15m high with volume expansion
    super_runner = (base["atr_pct"] >= 2.8 and px > opening_high and rvol >= 1.8 and (px / op - 1) * 100 >= 0.5)
    if super_runner:
        setup = "super_runner"
    elif breakout:
        setup = "opening_expansion"
    elif compressed:
        setup = "compression_breakout"
    elif continuation:
        setup = "vwap_continuation"
    else:
        setup = "none"
    high, low = float(day.high.max()), float(day.low.min())
    # A structural stop; setups requiring excessive risk are rejected, not tightened artificially.
    stop = min(px - base["atr"] * 0.25, float(prior.low.min()))
    result = {"symbol": symbol, "date": str(date), "ts": int(ts.timestamp()), "sector": sector,
              "feature_version": VERSION, "price": px, "stop": stop, "setup": setup,
              "cost_bps": QUANT_COST_BPS, "slippage_bps": QUANT_SLIPPAGE_BPS,
              "gap_pct": (op / base["prev_close"] - 1) * 100, "rvol": rvol,
              "atr_pct": base["atr_pct"], "atr": base["atr"], "turnover": base["turnover"],
              "range_atr": (high - low) / base["atr"], "vwap_distance": (px / vwap - 1) * 100,
              "vwap": vwap, "opening_breakout": (px / opening_high - 1) * 100,
              "compression": width / base["atr"],
              "momentum": (px / float(day.close.iloc[-4]) - 1) * 100,
              "close_location": (px - low) / (high - low) if high > low else 0.5,
              "daily_trend": base["daily_trend"], "rsi": base["rsi"],
              "time_fraction": (ts.hour * 60 + ts.minute - 555) / 375,
              "log_turnover": float(np.log1p(base["turnover"]))}
    if not all(np.isfinite(result[k]) for k in FEATURES + ("price", "stop")):
        return None
    result["baseline_score"] = float(np.clip(20 * np.log1p(rvol) + 15 * result["close_location"]
                                             + 5 * min(result["momentum"], 3) + 5 * min(base["atr_pct"], 5), 0, 100))
    return result


def gate(row):
    from config import QUANT_MIN_DAILY_VALUE, QUANT_MIN_PRICE, QUANT_MIN_STOP_PCT, QUANT_MAX_STOP_PCT
    # Relax liquidity threshold slightly for high-beta runner candidates to allow small/midcap runners
    min_val = QUANT_MIN_DAILY_VALUE * 0.5 if row.get("setup") == "super_runner" else QUANT_MIN_DAILY_VALUE
    if row["price"] < QUANT_MIN_PRICE or row["turnover"] < min_val:
        return "insufficient_liquidity"
    risk = (row["price"] - row["stop"]) / row["price"] * 100
    if not QUANT_MIN_STOP_PCT <= risk <= QUANT_MAX_STOP_PCT:
        return "invalid_structural_stop"
    if row["setup"] == "none":
        return "no_entry_trigger"
    if row["rvol"] < 1.4 or row["vwap_distance"] <= 0:
        return "weak_participation"
    return "eligible"



def quote_gate(row, quote, now, secondary_quote=None):
    from config import QUANT_QUOTE_MAX_AGE_SECONDS, QUANT_MAX_SPREAD_PCT, QUANT_MIN_CIRCUIT_HEADROOM_PCT
    if quote and quote.get("provider_disagreement"):
        return "provider_disagreement"

    consensus_status = "single_source_only"
    consensus_diff = 0.0
    sec_source = "none"

    if secondary_quote:
        from modules.provider_health import validate_quote_consensus
        ok, reason, details = validate_quote_consensus(row["symbol"], quote, secondary_quote)
        if not ok:
            return reason
        consensus_status = "consensus_confirmed"
        consensus_diff = details.get("discrepancy_pct", 0.0)
        sec_source = secondary_quote.get("source", "secondary")

    row["consensus_status"] = consensus_status
    row["secondary_provider"] = sec_source
    row["consensus_diff_pct"] = consensus_diff

    if not quote or not quote.get("ts"):
        return "quote_unavailable"
    age = now.timestamp() - quote["ts"]
    if age < -5 or age > QUANT_QUOTE_MAX_AGE_SECONDS:
        return "quote_stale"
    if quote.get("series") != "EQ":
        return "series_not_verified"
    bid, ask, upper = quote.get("bid"), quote.get("ask"), quote.get("upper")
    if not bid or not ask or not upper or bid <= 0 or ask < bid:
        return "spread_or_price_band_unavailable"
    if (ask - bid) / ask * 100 > QUANT_MAX_SPREAD_PCT:
        return "spread_too_wide"
    if abs(ask / row["price"] - 1) > 0.01:
        return "entry_already_moved"
    if upper and upper > 0:
        headroom_pct = (upper - ask) / ask * 100
        min_headroom = 7.0 + QUANT_MIN_CIRCUIT_HEADROOM_PCT
        if headroom_pct < min_headroom:
            return "insufficient_price_band_headroom"
    return "eligible"
