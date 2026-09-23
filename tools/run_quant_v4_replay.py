"""Quant V4 Historical Replay & Baseline Performance Analysis.

Executes point-in-time historical replay using the exact frozen Quant V4 codebase:
- Bounded 5m historical bar dataset in data/quant.db
- Exact gate, scoring, next-bar entry, TP1/TP2, SL, and EOD outcome evaluation
- Statutory Indian NSE cost modeling and dynamic ATR/RVOL slippage
- Comprehensive metric calculation & multi-dimensional segmentation
- Strict bias identification and evidence reporting (NO fabricated claims)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_v4_replay() -> dict:
    from modules.quant_store import Store
    from modules.quant_learning import training_rows, portfolio
    from modules.cost_model import calculate_intraday_costs, COST_MODEL_VERSION
    from modules.slippage_model import calculate_dynamic_slippage, SLIPPAGE_MODEL_VERSION

    store = Store()
    raw_eligible = training_rows(store)
    
    # Total eligible observations
    total_eligible = len(raw_eligible)
    
    # Official baseline simulated portfolio picks (max 3 picks/session, anti-concentration)
    official_picks = portfolio(raw_eligible, baseline=True)
    
    # Gather dates
    all_dates = sorted(set(r["date"] for r in raw_eligible))
    total_sessions = len(all_dates)
    
    # Separate by execution outcome
    filled_trades = []
    unfilled_trades = []
    unresolved_trades = []
    
    for p in official_picks:
        out = p.get("outcome", {})
        status = out.get("status")
        ret = out.get("return_pct")
        if ret is not None and status != "unfilled":
            filled_trades.append(p)
        elif status == "unfilled":
            unfilled_trades.append(p)
        else:
            unresolved_trades.append(p)

    n_signals = len(official_picks)
    n_filled = len(filled_trades)
    n_unfilled = len(unfilled_trades)
    n_unresolved = len(unresolved_trades)

    # Exit reason breakdown
    tp1_hits = 0
    tp2_hits = 0
    stop_hits = 0
    eod_exits = 0
    
    gross_returns = []
    net_returns = []
    
    for p in filled_trades:
        out = p["outcome"]
        hit7 = bool(out.get("hit7", False))
        hit10 = bool(out.get("hit10", False))
        if hit7:
            tp1_hits += 1
        if hit10:
            tp2_hits += 1
            
        reason = out.get("reason", "")
        if "stop" in reason:
            stop_hits += 1
        elif "target" in reason:
            pass  # Captured in tp1/tp2
        elif "cutoff" in reason or "eod" in reason:
            eod_exits += 1
        else:
            # Check last fill reason
            fills = out.get("fills", [])
            if fills:
                last_reason = fills[-1].get("reason", "")
                if "stop" in last_reason:
                    stop_hits += 1
                elif "target" in last_reason:
                    pass
                else:
                    eod_exits += 1
            else:
                eod_exits += 1

        gross_returns.append(out.get("gross_pct", out.get("return_pct", 0.0)))
        net_returns.append(out.get("return_pct", 0.0))

    gross_arr = np.array(gross_returns) if gross_returns else np.array([0.0])
    net_arr = np.array(net_returns) if net_returns else np.array([0.0])

    p7_rate = (tp1_hits / n_filled) if n_filled > 0 else 0.0
    p10_rate = (tp2_hits / n_filled) if n_filled > 0 else 0.0

    mean_gross = float(np.mean(gross_arr)) if n_filled > 0 else 0.0
    mean_net = float(np.mean(net_arr)) if n_filled > 0 else 0.0
    median_net = float(np.median(net_arr)) if n_filled > 0 else 0.0

    winners = net_arr[net_arr > 0]
    losers = net_arr[net_arr < 0]

    avg_winner = float(np.mean(winners)) if len(winners) > 0 else 0.0
    avg_loser = float(np.mean(losers)) if len(losers) > 0 else 0.0
    win_rate = (len(winners) / n_filled) if n_filled > 0 else 0.0

    # Expectancy = (Win Rate * Avg Win) - (Loss Rate * |Avg Loss|)
    loss_rate = 1.0 - win_rate
    expectancy = (win_rate * avg_winner) - (loss_rate * abs(avg_loser))

    # Profit Factor = Gross Gains / Gross Losses
    total_gain = float(np.sum(winners)) if len(winners) > 0 else 0.0
    total_loss = float(np.sum(np.abs(losers))) if len(losers) > 0 else 0.0
    profit_factor = (total_gain / total_loss) if total_loss > 0 else (99.0 if total_gain > 0 else 0.0)

    # Longest losing streak
    longest_losing_streak = 0
    current_streak = 0
    for r in net_arr:
        if r < 0:
            current_streak += 1
            if current_streak > longest_losing_streak:
                longest_losing_streak = current_streak
        else:
            current_streak = 0

    # Daily returns and 50,000 capital curve (1/3 per slot, unallocated cash earns 0%, no leverage)
    daily_groups = {}
    for p in filled_trades:
        daily_groups.setdefault(p["date"], []).append(p["outcome"]["return_pct"])

    daily_equal_capital_returns = {}
    for d in all_dates:
        trades_today = daily_groups.get(d, [])
        # 3 max slots: sum(returns) / 3
        d_ret = (sum(trades_today) / 3.0) if trades_today else 0.0
        daily_equal_capital_returns[d] = d_ret

    initial_capital = 50000.0
    capital_curve = [initial_capital]
    curr_cap = initial_capital

    for d in sorted(daily_equal_capital_returns.keys()):
        pct = daily_equal_capital_returns[d]
        curr_cap = curr_cap * (1.0 + pct / 100.0)
        capital_curve.append(round(curr_cap, 2))

    cap_arr = np.array(capital_curve)
    peaks = np.maximum.accumulate(cap_arr)
    drawdowns = (cap_arr - peaks) / peaks * 100.0
    max_drawdown = float(abs(np.min(drawdowns)))

    # Segmented performance helper
    def segment_stats(subset: list) -> dict:
        if not subset:
            return {"sample_size": 0, "win_rate": 0.0, "mean_net": 0.0, "p7_rate": 0.0}
        sub_nets = [p["outcome"]["return_pct"] for p in subset if p["outcome"].get("return_pct") is not None]
        if not sub_nets:
            return {"sample_size": len(subset), "win_rate": 0.0, "mean_net": 0.0, "p7_rate": 0.0}
        sub_arr = np.array(sub_nets)
        sub_win = np.mean(sub_arr > 0)
        sub_p7 = np.mean([bool(p["outcome"].get("hit7", False)) for p in subset])
        return {
            "sample_size": len(subset),
            "win_rate": round(float(sub_win * 100), 2),
            "mean_net": round(float(np.mean(sub_arr)), 3),
            "p7_rate": round(float(sub_p7 * 100), 2)
        }

    # 1. By Setup
    setup_groups = {}
    for p in filled_trades:
        s = p.get("setup", "none")
        setup_groups.setdefault(s, []).append(p)
    perf_by_setup = {s: segment_stats(trades) for s, trades in setup_groups.items()}

    # 2. By Market Regime (Point-in-Time label from candle context)
    regime_groups = {}
    for p in filled_trades:
        r = p.get("market_regime", "normal")
        regime_groups.setdefault(r, []).append(p)
    perf_by_regime = {r: segment_stats(trades) for r, trades in regime_groups.items()}

    # 3. By Sector
    sector_groups = {}
    for p in filled_trades:
        sec = p.get("sector", "Unknown")
        sector_groups.setdefault(sec, []).append(p)
    perf_by_sector = {sec: segment_stats(trades) for sec, trades in sector_groups.items()}

    # 4. By RVOL Bucket
    rvol_buckets = {"< 1.5": [], "1.5 - 2.5": [], "2.5 - 4.0": [], "> 4.0": []}
    for p in filled_trades:
        rv = float(p.get("rvol", 1.0))
        if rv < 1.5:
            rvol_buckets["< 1.5"].append(p)
        elif rv <= 2.5:
            rvol_buckets["1.5 - 2.5"].append(p)
        elif rv <= 4.0:
            rvol_buckets["2.5 - 4.0"].append(p)
        else:
            rvol_buckets["> 4.0"].append(p)
    perf_by_rvol = {b: segment_stats(trades) for b, trades in rvol_buckets.items()}

    # 5. By Time-of-Day
    tod_buckets = {"09:30 - 10:00": [], "10:00 - 10:30": [], "10:30 - 11:00": [], "After 11:00": []}
    for p in filled_trades:
        ts = p.get("ts", 0)
        t_obj = dt.datetime.fromtimestamp(ts, dt.timezone.utc).time()
        # rough IST hour: 09:30-10:00 is 04:00-04:30 UTC
        if t_obj < dt.time(4, 30):
            tod_buckets["09:30 - 10:00"].append(p)
        elif t_obj < dt.time(5, 0):
            tod_buckets["10:00 - 10:30"].append(p)
        elif t_obj < dt.time(5, 30):
            tod_buckets["10:30 - 11:00"].append(p)
        else:
            tod_buckets["After 11:00"].append(p)
    perf_by_tod = {b: segment_stats(trades) for b, trades in tod_buckets.items()}

    # 6. By Catalyst Presence
    cat_buckets = {"With Catalyst": [], "No Catalyst": []}
    for p in filled_trades:
        has_cat = bool(p.get("catalyst_flags", {}).get("news_exists_before_signal") or p.get("catalyst_context", {}).get("news_exists_before_signal"))
        if has_cat:
            cat_buckets["With Catalyst"].append(p)
        else:
            cat_buckets["No Catalyst"].append(p)
    perf_by_catalyst = {b: segment_stats(trades) for b, trades in cat_buckets.items()}

    # 7. By Execution Resolution
    res_buckets = {"5m_conservative": filled_trades, "1m": []}  # 1m is 0 in historical archive; 5m is full
    perf_by_res = {b: segment_stats(trades) for b, trades in res_buckets.items()}

    return {
        "dataset_summary": {
            "sessions": total_sessions,
            "date_range": f"{all_dates[0]} to {all_dates[-1]}" if all_dates else "None",
            "eligible_observations": total_eligible,
            "official_simulated_signals": n_signals,
            "filled": n_filled,
            "unfilled": n_unfilled,
            "unresolved": n_unresolved,
        },
        "exits": {
            "tp1_hits": tp1_hits,
            "tp2_hits": tp2_hits,
            "stops": stop_hits,
            "eod_exits": eod_exits,
            "p7_hit_rate": round(p7_rate * 100, 2),
            "p10_hit_rate": round(p10_rate * 100, 2),
        },
        "performance": {
            "mean_gross_return": round(mean_gross, 3),
            "mean_net_return": round(mean_net, 3),
            "median_net_return": round(median_net, 3),
            "average_winner": round(avg_winner, 3),
            "average_loser": round(avg_loser, 3),
            "win_rate": round(win_rate * 100, 2),
            "expectancy": round(expectancy, 3),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "longest_losing_streak": longest_losing_streak,
            "initial_capital": initial_capital,
            "final_capital": capital_curve[-1],
            "capital_return_pct": round((capital_curve[-1] / initial_capital - 1) * 100, 2),
        },
        "segmented": {
            "by_setup": perf_by_setup,
            "by_regime": perf_by_regime,
            "by_sector": perf_by_sector,
            "by_rvol": perf_by_rvol,
            "by_tod": perf_by_tod,
            "by_catalyst": perf_by_catalyst,
            "by_resolution": perf_by_res,
        },
        "biases_and_limitations": {
            "survivorship_bias": "Historical dataset uses current NIFTY/universe active equities; delisted or suspended tickers are absent.",
            "current_universe_bias": "Equities that joined the universe recently are replayed backwards without dynamic historical index membership dates.",
            "missing_historical_spread_depth": "Order-book bid/ask depth was not captured in historical archives; dynamic spread & slippage are modeled via ATR and RVOL.",
            "missing_historical_catalyst_data": "Real-time news wires before September 2026 lack second-level timestamps; past catalyst flags reflect partial backfill.",
            "provider_data_limitations": "5m consolidated bars obscure intra-bar tick sequences; same-bar stop vs target ambiguity is resolved conservatively (SL first)."
        }
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    data = run_v4_replay()
    print("================================================================================")
    print("                 QUANT V4 HISTORICAL POINT-IN-TIME REPLAY REPORT                ")
    print("================================================================================\n")

    ds = data["dataset_summary"]
    print("--- 1. DATASET & OBSERVATION SUMMARY ---")
    print(f"Total Trading Sessions:          {ds['sessions']} ({ds['date_range']})")
    print(f"Total Eligible Observations:      {ds['eligible_observations']}")
    print(f"Official Simulated Signals:       {ds['official_simulated_signals']} (Max 3/session, baseline score >= 60)")
    print(f"Filled Executions:                {ds['filled']}")
    print(f"Unfilled Signals (Gaps / Bands):  {ds['unfilled']}")
    print(f"Unresolved Signals:               {ds['unresolved']}")

    ex = data["exits"]
    print("\n--- 2. EXIT BREAKDOWN & HIT RATES ---")
    print(f"TP1 (+7.0%) Hits:                 {ex['tp1_hits']} (P7 Hit Rate: {ex['p7_hit_rate']}%)")
    print(f"TP2 (+10.2%) Hits:                {ex['tp2_hits']} (P10 Hit Rate: {ex['p10_hit_rate']}%)")
    print(f"Stop-Loss Hits:                   {ex['stops']}")
    print(f"EOD (15:20) Exits:                {ex['eod_exits']}")

    pf = data["performance"]
    print("\n--- 3. PERFORMANCE METRICS (STATUTORY COSTS & DYNAMIC SLIPPAGE DEDUCTED) ---")
    print(f"Mean Gross Return:                {pf['mean_gross_return']:+.3f}%")
    print(f"Mean Net Return:                  {pf['mean_net_return']:+.3f}%")
    print(f"Median Net Return:                {pf['median_net_return']:+.3f}%")
    print(f"Average Winner:                   {pf['average_winner']:+.3f}%")
    print(f"Average Loser:                    {pf['average_loser']:+.3f}%")
    print(f"Win Rate:                         {pf['win_rate']}%")
    print(f"Expectancy:                       {pf['expectancy']:+.3f}% per trade")
    print(f"Profit Factor:                    {pf['profit_factor']}")
    print(f"Max Capital Drawdown:             {pf['max_drawdown_pct']}%")
    print(f"Longest Losing Streak:            {pf['longest_losing_streak']} trades")
    print(f"Simulated ₹50,000 Capital Curve:  ₹{pf['initial_capital']:,.2f} -> ₹{pf['final_capital']:,.2f} ({pf['capital_return_pct']:+.2f}%)")

    seg = data["segmented"]
    print("\n--- 4. SEGMENTED PERFORMANCE BREAKDOWN ---")

    for cat_name, title in [
        ("by_setup", "A. Performance by Setup"),
        ("by_regime", "B. Performance by Market Regime"),
        ("by_sector", "C. Performance by Sector (Top 5)"),
        ("by_rvol", "D. Performance by RVOL Bucket"),
        ("by_tod", "E. Performance by Time-of-Day"),
        ("by_catalyst", "F. Performance by Catalyst Presence"),
        ("by_resolution", "G. Performance by Execution Resolution"),
    ]:
        print(f"\n[{title}]")
        print(f"  {'Segment':<28} | {'N (Trades)':<10} | {'Win Rate':<10} | {'Mean Net':<10} | {'P7 Rate':<10}")
        print("  " + "-" * 75)
        items = list(seg[cat_name].items())
        if cat_name == "by_sector":
            items = sorted(items, key=lambda x: x[1]["sample_size"], reverse=True)[:5]
        for name, s in items:
            print(f"  {name:<28} | {s['sample_size']:<10} | {s['win_rate']:>8.1f}% | {s['mean_net']:>+8.2f}% | {s['p7_rate']:>8.1f}%")

    bl = data["biases_and_limitations"]
    print("\n--- 5. BIASES & DATA LIMITATIONS (RESEARCH GOVERNANCE) ---")
    for k, v in bl.items():
        print(f"  * {k.upper()}: {v}")
    print("\n================================================================================")
    print("NOTE: As mandated by research discipline, statistical significance is not yet established.")
    print("No profitability claims are made; quant_v4.0_baseline remains frozen for forward testing.")
    print("================================================================================\n")
