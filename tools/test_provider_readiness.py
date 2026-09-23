"""Provider Readiness Test for Quant V4 Research Architecture.

Tests connectivity, latency, freshness, and quote completeness for:
1. Angel One Historical 5m
2. Angel One Selective 1m
3. Angel One Live Quote
4. Dhan Secondary Quote
5. NSE Secondary Quote
6. Yahoo Historical Fallback
7. Telegram Delivery Channel

Also demonstrates live get_quote_candidates() and consensus validation across dual feeds.
NEVER prints tokens or API secrets.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_provider_readiness() -> dict:
    import config
    from modules.quant_store import Store
    from modules.quant_time import now_ist
    import datetime as dt

    store = Store()
    test_symbol = "RELIANCE"
    results = {}

    # 1. Angel One Provider Checks
    from modules.angel_data import AngelDataProvider
    angel = AngelDataProvider(store)
    angel_configured = angel.configured()

    # 1a. Angel historical 5m
    t0 = time.monotonic()
    angel_5m_ok = False
    angel_5m_err = None
    angel_5m_freshness = "N/A"
    angel_5m_count = 0
    if angel_configured:
        try:
            end = now_ist().date()
            start = end - dt.timedelta(days=7)
            bars_5m = angel.candles(test_symbol, "5m", start, end)
            latency_5m = (time.monotonic() - t0) * 1000
            if bars_5m is not None and not bars_5m.empty:
                angel_5m_ok = True
                angel_5m_count = len(bars_5m)
                angel_5m_freshness = str(bars_5m.index[-1])
            else:
                angel_5m_err = "Empty DataFrame returned"
        except Exception as e:
            latency_5m = (time.monotonic() - t0) * 1000
            angel_5m_err = f"{type(e).__name__}: {e}"
    else:
        latency_5m = 0.0
        angel_5m_err = "Credentials not configured in environment"

    results["angel_historical_5m"] = {
        "provider": "Angel One (SmartAPI Historical 5m)",
        "configured": "yes" if angel_configured else "no",
        "connectivity": "CONNECTED" if angel_5m_ok else "OFFLINE",
        "freshness": angel_5m_freshness,
        "quote_completeness": f"{angel_5m_count} bars (OHLCV)" if angel_5m_ok else "0 bars",
        "latency_ms": round(latency_5m, 1),
        "error": angel_5m_err or "None"
    }

    # 1b. Angel selective 1m
    t0 = time.monotonic()
    angel_1m_ok = False
    angel_1m_err = None
    angel_1m_freshness = "N/A"
    angel_1m_count = 0
    if angel_configured:
        try:
            end = now_ist().date()
            start = end - dt.timedelta(days=2)
            bars_1m = angel.candles(test_symbol, "1m", start, end)
            latency_1m = (time.monotonic() - t0) * 1000
            if bars_1m is not None and not bars_1m.empty:
                angel_1m_ok = True
                angel_1m_count = len(bars_1m)
                angel_1m_freshness = str(bars_1m.index[-1])
            else:
                angel_1m_err = "Empty DataFrame returned"
        except Exception as e:
            latency_1m = (time.monotonic() - t0) * 1000
            angel_1m_err = f"{type(e).__name__}: {e}"
    else:
        latency_1m = 0.0
        angel_1m_err = "Credentials not configured in environment"

    results["angel_selective_1m"] = {
        "provider": "Angel One (Selective 1m Stream)",
        "configured": "yes" if angel_configured else "no",
        "connectivity": "CONNECTED" if angel_1m_ok else "OFFLINE",
        "freshness": angel_1m_freshness,
        "quote_completeness": f"{angel_1m_count} bars (OHLCV)" if angel_1m_ok else "0 bars",
        "latency_ms": round(latency_1m, 1),
        "error": angel_1m_err or "None"
    }

    # 1c. Angel live quote
    t0 = time.monotonic()
    angel_quote_ok = False
    angel_quote_err = None
    angel_quote_freshness = "N/A"
    angel_quote_comp = "N/A"
    if angel_configured:
        try:
            q = angel.quote(test_symbol)
            latency_q = (time.monotonic() - t0) * 1000
            if q and q.get("ask") and q.get("bid"):
                angel_quote_ok = True
                angel_quote_freshness = f"ts={q.get('ts')}"
                angel_quote_comp = f"price={q.get('price')}, bid={q.get('bid')}, ask={q.get('ask')}"
            else:
                angel_quote_err = "Missing bid/ask or quote empty"
        except Exception as e:
            latency_q = (time.monotonic() - t0) * 1000
            angel_quote_err = f"{type(e).__name__}: {e}"
    else:
        latency_q = 0.0
        angel_quote_err = "Credentials not configured in environment"

    results["angel_live_quote"] = {
        "provider": "Angel One (SmartAPI Live Level-2 Quote)",
        "configured": "yes" if angel_configured else "no",
        "connectivity": "CONNECTED" if angel_quote_ok else "OFFLINE",
        "freshness": angel_quote_freshness,
        "quote_completeness": angel_quote_comp if angel_quote_ok else "Incomplete",
        "latency_ms": round(latency_q, 1),
        "error": angel_quote_err or "None"
    }

    # 2. Dhan secondary quote
    from modules.quant_data import _dhan_quote
    dhan_configured = bool(getattr(config, "DHAN_ENABLED", False) and getattr(config, "DHAN_CLIENT_ID", None) and getattr(config, "DHAN_ACCESS_TOKEN", None))
    t0 = time.monotonic()
    dhan_ok = False
    dhan_err = None
    dhan_freshness = "N/A"
    dhan_comp = "N/A"
    if dhan_configured:
        try:
            dq = _dhan_quote(test_symbol)
            lat_dhan = (time.monotonic() - t0) * 1000
            if dq and dq.get("ask") and dq.get("bid"):
                dhan_ok = True
                dhan_freshness = f"ts={dq.get('ts')}"
                dhan_comp = f"price={dq.get('price')}, bid={dq.get('bid')}, ask={dq.get('ask')}"
            else:
                dhan_err = "Empty or incomplete response"
        except Exception as e:
            lat_dhan = (time.monotonic() - t0) * 1000
            dhan_err = f"{type(e).__name__}: {e}"
    else:
        lat_dhan = 0.0
        dhan_err = "DHAN_CLIENT_ID / ACCESS_TOKEN not configured"

    results["dhan_secondary_quote"] = {
        "provider": "Dhan (Marketfeed V2 Secondary Quote)",
        "configured": "yes" if dhan_configured else "no",
        "connectivity": "CONNECTED" if dhan_ok else "OFFLINE",
        "freshness": dhan_freshness,
        "quote_completeness": dhan_comp if dhan_ok else "Incomplete",
        "latency_ms": round(lat_dhan, 1),
        "error": dhan_err or "None"
    }

    # 3. NSE secondary quote
    from modules.quant_data import _nse_quote
    t0 = time.monotonic()
    nse_ok = False
    nse_err = None
    nse_freshness = "N/A"
    nse_comp = "N/A"
    try:
        nq = _nse_quote(test_symbol)
        lat_nse = (time.monotonic() - t0) * 1000
        if nq and nq.get("ask") and nq.get("bid"):
            nse_ok = True
            nse_freshness = f"ts={nq.get('ts')}"
            nse_comp = f"price={nq.get('price')}, bid={nq.get('bid')}, ask={nq.get('ask')}"
        else:
            nse_err = "NSE live rate limited or market closed"
    except Exception as e:
        lat_nse = (time.monotonic() - t0) * 1000
        nse_err = f"{type(e).__name__}: {e}"

    results["nse_secondary_quote"] = {
        "provider": "NSE (Statutory Direct Market Depth)",
        "configured": "yes",
        "connectivity": "CONNECTED" if nse_ok else "RATE_LIMITED_OR_OFFLINE",
        "freshness": nse_freshness,
        "quote_completeness": nse_comp if nse_ok else "Incomplete",
        "latency_ms": round(lat_nse, 1),
        "error": nse_err or "None"
    }

    # 4. Yahoo historical fallback
    import yfinance as yf
    t0 = time.monotonic()
    yf_ok = False
    yf_err = None
    yf_freshness = "N/A"
    yf_count = 0
    try:
        ydf = yf.download(f"{test_symbol}.NS", period="5d", interval="5m", progress=False)
        lat_yf = (time.monotonic() - t0) * 1000
        if ydf is not None and not ydf.empty:
            yf_ok = True
            yf_count = len(ydf)
            yf_freshness = str(ydf.index[-1])
        else:
            yf_err = "Empty DataFrame from Yahoo Finance"
    except Exception as e:
        lat_yf = (time.monotonic() - t0) * 1000
        yf_err = f"{type(e).__name__}: {e}"

    results["yahoo_historical_fallback"] = {
        "provider": "Yahoo Finance (Free Fail-Closed Fallback)",
        "configured": "yes",
        "connectivity": "CONNECTED" if yf_ok else "OFFLINE",
        "freshness": yf_freshness,
        "quote_completeness": f"{yf_count} bars (OHLCV)" if yf_ok else "0 bars",
        "latency_ms": round(lat_yf, 1),
        "error": yf_err or "None"
    }

    # 5. Telegram delivery
    import requests
    tg_token = getattr(config, "TELEGRAM_BOT_TOKEN", None) or os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = getattr(config, "TELEGRAM_CHAT_ID", None) or os.getenv("TELEGRAM_CHAT_ID")
    tg_configured = bool(tg_token and tg_chat)
    t0 = time.monotonic()
    tg_ok = False
    tg_err = None
    if tg_configured:
        try:
            # Safe getMe call — validates token without sending spam message
            resp = requests.get(f"https://api.telegram.org/bot{tg_token}/getMe", timeout=5)
            lat_tg = (time.monotonic() - t0) * 1000
            if resp.status_code == 200 and resp.json().get("ok"):
                tg_ok = True
            else:
                tg_err = f"HTTP {resp.status_code}: {resp.text[:60]}"
        except Exception as e:
            lat_tg = (time.monotonic() - t0) * 1000
            tg_err = f"{type(e).__name__}: {e}"
    else:
        lat_tg = 0.0
        tg_err = "TELEGRAM_BOT_TOKEN / CHAT_ID not configured"

    results["telegram_delivery"] = {
        "provider": "Telegram Bot API (Operational Dispatch)",
        "configured": "yes" if tg_configured else "no",
        "connectivity": "CONNECTED" if tg_ok else "OFFLINE",
        "freshness": "Real-time Gateway",
        "quote_completeness": "Operational Channel Ready" if tg_ok else "Disabled",
        "latency_ms": round(lat_tg, 1),
        "error": tg_err or "None"
    }

    # 6. Live get_quote_candidates() and Consensus Demonstration
    from modules.quant_data import DataService
    from modules.provider_health import validate_quote_consensus
    ds = DataService(store)
    primary, secondary = ds.get_quote_candidates(test_symbol)
    
    # Run consensus check
    consensus_valid, consensus_verdict, consensus_details = validate_quote_consensus(
        symbol=test_symbol,
        primary_quote=primary,
        secondary_quote=secondary,
        max_drift_pct=0.35,
        store=store
    )

    demo_info = {
        "symbol": test_symbol,
        "primary_source": primary.get("source") if primary else "None",
        "primary_price": primary.get("price") if primary else None,
        "secondary_source": secondary.get("source") if secondary else "None",
        "secondary_price": secondary.get("price") if secondary else None,
        "consensus_valid": consensus_valid,
        "verdict": consensus_verdict,
        "details": consensus_details
    }

    return results, demo_info


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("================================================================================")
    print("                      QUANT V4 PROVIDER READINESS REPORT                        ")
    print("================================================================================\n")

    report, demo = run_provider_readiness()

    for k, v in report.items():
        print(f"Provider:           {v['provider']}")
        print(f"Configured:         {v['configured']}")
        print(f"Connectivity:       {v['connectivity']}")
        print(f"Freshness:          {v['freshness']}")
        print(f"Quote Completeness: {v['quote_completeness']}")
        print(f"Latency:            {v['latency_ms']} ms")
        print(f"Error:              {v['error']}")
        print("-" * 80)

    print("\n================================================================================")
    print("           LIVE DUAL-PROVIDER CONSENSUS VALIDATION DEMONSTRATION                ")
    print("================================================================================")
    print(f"Target Symbol:       {demo['symbol']}")
    print(f"Primary Candidate:   Provider={demo['primary_source']} | Price={demo['primary_price']}")
    print(f"Secondary Candidate: Provider={demo['secondary_source']} | Price={demo['secondary_price']}")
    print(f"Consensus Passed:    {demo['consensus_valid']}")
    print(f"Verdict:             {demo['verdict']}")
    print(f"Audit Details:       {demo['details']}")

    # Demonstrate dual independent quote verification across scenarios
    from modules.provider_health import validate_quote_consensus
    from modules.quant_store import Store
    demo_store = Store()
    now_ts = int(time.time())

    # Scenario A: Independent Dual Quotes Agree (drift = 0.12% < 0.35%)
    q_prim_a = {"price": 1248.0, "bid": 1247.5, "ask": 1248.0, "ts": now_ts, "source": "angel_one", "series": "EQ"}
    q_sec_a = {"price": 1249.5, "bid": 1249.0, "ask": 1249.5, "ts": now_ts, "source": "dhan", "series": "EQ"}
    ok_a, verdict_a, det_a = validate_quote_consensus("RELIANCE", q_prim_a, q_sec_a, max_drift_pct=0.35, store=demo_store)

    print("\n[Scenario A: Dual Feeds Agree within 0.35% threshold]")
    print(f"  Primary Feed:   Angel One Ask = Rs {q_prim_a['ask']}")
    print(f"  Secondary Feed: Dhan Ask      = Rs {q_sec_a['ask']}")
    print(f"  Price Drift:    {det_a.get('discrepancy_pct', 0.0):.3f}% (max 0.35%)")
    print(f"  Consensus:      Passed={ok_a} | Verdict={verdict_a}")

    # Scenario B: Independent Dual Quotes Disagree (drift = 0.88% > 0.35%)
    q_prim_b = {"price": 1248.0, "bid": 1247.5, "ask": 1248.0, "ts": now_ts, "source": "angel_one", "series": "EQ"}
    q_sec_b = {"price": 1259.0, "bid": 1258.5, "ask": 1259.0, "ts": now_ts, "source": "nse", "series": "EQ"}
    ok_b, verdict_b, det_b = validate_quote_consensus("RELIANCE", q_prim_b, q_sec_b, max_drift_pct=0.35, store=demo_store)

    print("\n[Scenario B: Dual Feeds Disagree beyond 0.35% threshold (Drift Spike)]")
    print(f"  Primary Feed:   Angel One Ask = Rs {q_prim_b['ask']}")
    print(f"  Secondary Feed: NSE Ask        = Rs {q_sec_b['ask']}")
    print(f"  Price Drift:    {det_b.get('discrepancy_pct', 0.0):.3f}% (max 0.35%)")
    print(f"  Consensus:      Passed={ok_b} | Verdict={verdict_b} (QUARANTINED / REJECTED)")
    print("================================================================================\n")
