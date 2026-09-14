"""Quant v3 administration. Commands never send alerts without --notify."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def audit():
    import requests
    import config
    import yfinance as yf
    result = {"paid_services_added": False}
    if config.DHAN_CLIENT_ID and config.DHAN_ACCESS_TOKEN:
        try:
            r = requests.post("https://api.dhan.co/v2/marketfeed/quote", timeout=8,
                              headers={"client-id": config.DHAN_CLIENT_ID, "access-token": config.DHAN_ACCESS_TOKEN},
                              json={"NSE_EQ": [1333]})
            body = r.json()
            result["dhan"] = {"http_status": r.status_code, "api_status": body.get("status"),
                              "error_code": body.get("errorCode"), "has_quote": bool(body.get("data", {}).get("NSE_EQ"))}
        except Exception as e:
            result["dhan"] = {"error_type": type(e).__name__}
    else:
        result["dhan"] = {"status": "missing_client_id_or_token"}
    started = time.monotonic()
    try:
        frame = yf.download("KAYNES.NS", interval="5m", period="5d", auto_adjust=False,
                            threads=False, progress=False, timeout=8)
        result["yahoo"] = {"rows": len(frame), "latest_bar": str(frame.index[-1]) if len(frame) else None,
                           "seconds": round(time.monotonic()-started, 3)}
    except Exception as e:
        result["yahoo"] = {"error_type": type(e).__name__}
    from modules.quant_data import _nse_quote
    quote = _nse_quote("KAYNES")
    result["nse"] = {"quote_available": bool(quote and quote.get("price")),
                     "timestamp_available": bool(quote and quote.get("ts")),
                     "bid_ask_available": bool(quote and quote.get("bid") and quote.get("ask")),
                     "price_band_available": bool(quote and quote.get("upper"))}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["audit", "prepare", "backfill", "cycle", "replay", "train", "learn", "status", "once", "benchmark"])
    parser.add_argument("--db", help="Separate quant research DB; default data/quant.db")
    parser.add_argument("--symbols", help="Comma-separated symbols for replay/benchmark")
    parser.add_argument("--budget", type=int, default=240, help="Download/replay budget in seconds")
    parser.add_argument("--notify", action="store_true", help="Allow actual Telegram delivery")
    parser.add_argument("--offline", action="store_true", help="Use cached data only for cycle")
    args = parser.parse_args()
    os.chdir(ROOT)
    import config
    if args.db:
        config.QUANT_DB_PATH = os.path.abspath(args.db)
    from modules.quant_store import Store
    from modules.quant_engine import prepare, cycle, replay, learn, snapshot
    from modules.quant_learning import train
    from modules.quant_data import DataService
    store = Store()
    symbols = args.symbols.split(",") if args.symbols else None
    if args.command == "audit":
        result = audit(); store.put("provider_audit", result)
    elif args.command == "prepare":
        result = prepare(store, budget=args.budget)
    elif args.command == "backfill":
        service = DataService(store)
        result = service.backfill(symbols=symbols, budget=args.budget)
    elif args.command == "cycle":
        result = cycle(store, notify=args.notify, refresh=not args.offline)
    elif args.command == "replay":
        result = replay(store, symbols=symbols, budget=args.budget)
    elif args.command == "train":
        result = train(store)
    elif args.command == "learn":
        result = replay(store, symbols=symbols, budget=args.budget)
        result["learning"] = train(store)
    elif args.command == "once":
        from modules.quant_runtime import run_once
        result = run_once(notify=args.notify)
    elif args.command == "benchmark":
        service = DataService(store)
        symbols = symbols or ["KAYNES", "PERSISTENT", "DIXON"]
        first = service.refresh(symbols, "5m", "5d", budget=args.budget, force=True)
        second = service.refresh(symbols, "5m", "5d", budget=args.budget)
        result = {"network_refresh": first, "same_bucket_cached_refresh": second,
                  "scope": "Same symbols and candle cache; not an end-to-end comparison with the old strategy."}
        store.put("benchmark", result)
    else:
        result = snapshot(store)
    print(json.dumps(result, indent=2, default=str, allow_nan=False))


if __name__ == "__main__":
    main()
