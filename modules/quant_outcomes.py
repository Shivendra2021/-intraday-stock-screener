"""Chronological bar replay with conservative fills, partials, costs and missing data.

All fills are SIMULATED. Signals use the next bar, never the signal bar's high.
The same evaluator labels historical candidates and accounts for live paper picks.
Supports both 1-minute execution archives and 5-minute conservative fallbacks.
"""
from __future__ import annotations

import datetime as dt
import pandas as pd

from modules.cost_model import COST_MODEL_VERSION
from modules.slippage_model import SLIPPAGE_MODEL_VERSION, calculate_dynamic_slippage


def evaluate(row, bars, cost_bps=None, slippage_bps=None, cutoff="15:20", interval=None):
    from config import (QUANT_COST_BPS, QUANT_SLIPPAGE_BPS, QUANT_MIN_STOP_PCT, QUANT_MAX_STOP_PCT,
                        RUNNER_TP1_PCT, RUNNER_TP2_PCT)

    # Detect interval / resolution
    is_1m = False
    if interval == "1m":
        is_1m = True
    elif len(bars) >= 2:
        step_diff = (bars.index[1] - bars.index[0]).total_seconds()
        if step_diff == 60:
            is_1m = True

    execution_res = "1m" if is_1m else "5m_conservative"
    step_seconds = 60 if is_1m else 300

    # Determine dynamic slippage if not explicitly passed
    if slippage_bps is None and ("spread_pct" in row or "rvol" in row):
        dynamic_slip = calculate_dynamic_slippage(
            spread_pct=row.get("spread_pct"),
            rvol=row.get("rvol"),
            atr_pct=row.get("atr_pct"),
            turnover=row.get("turnover"),
            base_fallback_bps=QUANT_SLIPPAGE_BPS,
        )
        effective_slip_bps = dynamic_slip["slippage_bps"]
    else:
        effective_slip_bps = row.get("slippage_bps", QUANT_SLIPPAGE_BPS) if slippage_bps is None else slippage_bps

    cost = (row.get("cost_bps", QUANT_COST_BPS) if cost_bps is None else cost_bps) / 100
    slip = effective_slip_bps / 10000
    date = dt.date.fromisoformat(row["date"])

    # Reserve full processing interval. Both backtests and live paper signals enter at boundary.
    default_step = 60 if is_1m else 300
    entry_ts = int(row.get("entry_ts", row["ts"] + default_step))
    boundary = pd.Timestamp(entry_ts, unit="s", tz="UTC")
    future = bars[(bars.index.date == date) & (bars.index >= boundary)]
    future = future[future.index.strftime("%H:%M") < cutoff]
    unknown = {
        "resolved": False,
        "status": "unresolved",
        "reason": "missing_entry_or_exit_bars",
        "return_pct": None,
        "hit7": None,
        "hit10": None,
        "fills": [],
        "execution": "simulated",
        "execution_resolution": execution_res,
        "cost_model_version": COST_MODEL_VERSION,
        "slippage_model_version": SLIPPAGE_MODEL_VERSION,
    }
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
    last_ts = entry_ts - step_seconds
    max_up, max_down = 0.0, 0.0
    status = "open"
    for bar in future.itertuples():
        ts = int(bar.Index.timestamp())
        if ts != last_ts + step_seconds or bar.volume <= 0:
            return {**unknown, "reason": "missing_or_untradable_interval", "fills": fills}
        last_ts = ts
        max_up = max(max_up, (bar.high / entry - 1) * 100)
        max_down = min(max_down, (bar.low / entry - 1) * 100)
        # If stop and target occur in one bar, stop wins (order is unknowable / SL first).
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
        if future.index[-1] + pd.Timedelta(seconds=step_seconds) != finish:
            return {**unknown, "status": "open", "fills": fills, "entry": entry,
                    "hit7_so_far": hit7, "gross_realized_pct": gross}
        exit_price = float(future.close.iloc[-1]) * (1 - slip)
        gross += remaining * (exit_price / entry - 1) * 100
        fills.append({"ts": int(finish.timestamp()), "fraction": remaining, "price": exit_price, "reason": "eod"})
        status = "eod_exit"

    avg_exit = sum(f["fraction"] * f["price"] for f in fills) if fills else entry
    qty = max(1, int(100000.0 / entry))
    from modules.cost_model import calculate_intraday_costs
    costs = calculate_intraday_costs(entry, avg_exit, qty)
    if cost_bps is not None:
        statutory_cost_pct = cost_bps / 100.0
    elif "cost_bps" in row:
        statutory_cost_pct = row["cost_bps"] / 100.0
    else:
        statutory_cost_pct = costs["cost_pct"]
    net_return = round(gross - statutory_cost_pct, 5)

    return {
        "resolved": True,
        "status": status,
        "entry": entry,
        "return_pct": net_return,
        "net_return_pct": net_return,
        "gross_return_pct": round(gross, 5),
        "cost_pct": round(statutory_cost_pct, 5),
        "brokerage_cost": costs["brokerage"],
        "stt_cost": costs["stt"],
        "exchange_cost": costs["turnover_fee"],
        "sebi_cost": costs["sebi_fee"],
        "stamp_cost": costs["stamp_duty"],
        "gst_cost": costs["gst"],
        "total_transaction_cost": costs["total_charges"],
        "slippage_bps": effective_slip_bps,
        "hit7": int(hit7),
        "hit10": int(hit10),
        "max_favorable_pct": round(max_up, 4),
        "max_adverse_pct": round(max_down, 4),
        "fills": fills,
        "execution": "simulated",
        "execution_resolution": execution_res,
        "cost_model_version": COST_MODEL_VERSION,
        "slippage_model_version": SLIPPAGE_MODEL_VERSION,
        "reason": f"chronological_{execution_res}_replay",
    }
