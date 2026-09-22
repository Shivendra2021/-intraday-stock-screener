"""Chronological bar replay with conservative fills, partials, costs and missing data.

All fills are SIMULATED. Signals use the next bar, never the signal bar's high.
The same evaluator labels historical candidates and accounts for live paper picks.
"""
from __future__ import annotations

import datetime as dt
import pandas as pd


def evaluate(row, bars, cost_bps=None, slippage_bps=None, cutoff="15:20"):
    from config import (QUANT_COST_BPS, QUANT_SLIPPAGE_BPS, QUANT_MIN_STOP_PCT, QUANT_MAX_STOP_PCT,
                        RUNNER_TP1_PCT, RUNNER_TP2_PCT)
    cost = (row.get("cost_bps", QUANT_COST_BPS) if cost_bps is None else cost_bps) / 100
    slip = (row.get("slippage_bps", QUANT_SLIPPAGE_BPS) if slippage_bps is None else slippage_bps) / 10000
    date = dt.date.fromisoformat(row["date"])
    # Reserve a full processing/notification interval. Both backtests and live
    # paper signals enter at the following boundary, not an already elapsed open.
    entry_ts = int(row.get("entry_ts", row["ts"] + 300))
    boundary = pd.Timestamp(entry_ts, unit="s", tz="UTC")
    future = bars[(bars.index.date == date) & (bars.index >= boundary)]
    future = future[future.index.strftime("%H:%M") < cutoff]
    unknown = {"resolved": False, "status": "unresolved", "reason": "missing_entry_or_exit_bars",
               "return_pct": None, "hit7": None, "hit10": None, "fills": [], "execution": "simulated"}
    if future.empty:
        return unknown
    first = future.iloc[0]
    # Missing entry interval cannot be filled retrospectively several bars later.
    if int(future.index[0].timestamp()) != entry_ts:
        return unknown
    entry = float(first.open) * (1 + slip)
    stop = float(row["stop"])
    risk = (entry - stop) / entry * 100
    if abs(entry / row["price"] - 1) > 0.01 or not QUANT_MIN_STOP_PCT <= risk <= QUANT_MAX_STOP_PCT:
        return {**unknown, "resolved": True, "status": "unfilled", "reason": "entry_gap_or_invalid_risk"}
    tp1 = entry * (1 + RUNNER_TP1_PCT / 100)
    tp2 = entry * (1 + RUNNER_TP2_PCT / 100)
    if row.get("upper") and tp1 > row["upper"]:
        return {**unknown, "resolved": True, "status": "unfilled", "reason": "target_outside_price_band"}
    if row.get("upper") and tp2 > row["upper"]:
        tp2 = row["upper"] * 0.998
    remaining, gross, hit7, hit10 = 1.0, 0.0, False, False
    fills = []
    last_ts = entry_ts - 300
    max_up, max_down = 0.0, 0.0
    status = "open"
    for bar in future.itertuples():
        ts = int(bar.Index.timestamp())
        if ts != last_ts + 300 or bar.volume <= 0:
            return {**unknown, "reason": "missing_or_untradable_interval", "fills": fills}
        last_ts = ts
        max_up = max(max_up, (bar.high / entry - 1) * 100)
        max_down = min(max_down, (bar.low / entry - 1) * 100)
        # If stop and target occur in one bar, stop wins (order is unknowable).
        if bar.low <= stop:
            exit_price = min(float(bar.open), stop) * (1 - slip)
            gross += remaining * (exit_price / entry - 1) * 100
            fills.append({"ts": ts, "fraction": remaining, "price": exit_price, "reason": "stop"})
            remaining, status = 0.0, "stop_exit"
            break
        if not hit7 and bar.high >= tp1:
            hit7 = True
            exit_price = tp1 * (1 - slip)
            gross += 0.5 * (exit_price / entry - 1) * 100
            fills.append({"ts": ts, "fraction": 0.5, "price": exit_price, "reason": "target7"})
            remaining = 0.5
        if bar.high >= tp2:
            hit10 = True
            exit_price = tp2 * (1 - slip)
            gross += remaining * (exit_price / entry - 1) * 100
            fills.append({"ts": ts, "fraction": remaining, "price": exit_price, "reason": "target10"})
            remaining, status = 0.0, "target_exit"
            break
        # Runner stop is updated only for the NEXT bar. Cannot use a new high to
        # invent a favorable stop execution earlier in the same candle.
        if hit7:
            stop = max(stop, entry * 1.035)
    if remaining:
        finish = pd.Timestamp(f"{date} {cutoff}", tz="Asia/Kolkata")
        if future.index[-1] + pd.Timedelta(minutes=5) != finish:
            return {**unknown, "status": "open", "fills": fills, "entry": entry,
                    "hit7_so_far": hit7, "gross_realized_pct": gross}
        exit_price = float(future.close.iloc[-1]) * (1 - slip)
        gross += remaining * (exit_price / entry - 1) * 100
        fills.append({"ts": int(finish.timestamp()), "fraction": remaining, "price": exit_price, "reason": "eod"})
        status = "eod_exit"
    return {"resolved": True, "status": status, "entry": entry, "return_pct": round(gross - cost, 5),
            "gross_return_pct": round(gross, 5), "cost_pct": cost, "hit7": int(hit7), "hit10": int(hit10),
            "max_favorable_pct": round(max_up, 4), "max_adverse_pct": round(max_down, 4),
            "fills": fills, "execution": "simulated", "reason": "chronological_5m_replay"}
