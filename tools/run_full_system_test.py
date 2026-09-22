"""Full System & API Diagnostic Test Suite.

Tests:
1. All core modules & classes
2. Database schema & table records
3. Live dashboard HTTP API endpoints
4. External provider connectivity (Telegram, Angel One, Market Data)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("TZ", "Asia/Kolkata")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def test_modules() -> dict[str, dict]:
    results = {}
    print("\n[1/4] TESTING CORE MODULES...")

    # 1. Premarket Engine
    try:
        from modules.premarket_engine import run_premarket_screener, compute_auction_imbalance, detect_vcp_compression
        res = run_premarket_screener(top_n=3)
        picks = res.get("picks", [])
        if len(picks) > 0:
            results["premarket_engine"] = {"ok": True, "detail": f"Generated {len(picks)} picks ({[p['symbol'] for p in picks]})"}
        else:
            results["premarket_engine"] = {"ok": False, "error": "No picks returned"}
    except Exception as exc:
        results["premarket_engine"] = {"ok": False, "error": str(exc)}
    print(f"  - premarket_engine: {'PASS' if results['premarket_engine']['ok'] else 'FAIL'}")

    # 2. Stock Tracker
    try:
        from modules.stock_tracker import _load, update_tracking
        tracking = _load()
        results["stock_tracker"] = {"ok": True, "detail": f"Loaded {len(tracking)} tracked positions"}
    except Exception as exc:
        results["stock_tracker"] = {"ok": False, "error": str(exc)}
    print(f"  - stock_tracker: {'PASS' if results['stock_tracker']['ok'] else 'FAIL'}")

    # 3. Alerts
    try:
        from modules.alerts import _safe_error_text
        safe = _safe_error_text("Token test sample")
        results["alerts"] = {"ok": True, "detail": "Alert engine loaded with token scrubbing"}
    except Exception as exc:
        results["alerts"] = {"ok": False, "error": str(exc)}
    print(f"  - alerts: {'PASS' if results['alerts']['ok'] else 'FAIL'}")

    # 4. After Market Learning
    try:
        from modules.after_market_learning import get_after_market_patterns
        patterns = get_after_market_patterns()
        results["after_market_learning"] = {"ok": True, "detail": f"{len(patterns)} patterns available"}
    except Exception as exc:
        results["after_market_learning"] = {"ok": False, "error": str(exc)}
    print(f"  - after_market_learning: {'PASS' if results['after_market_learning']['ok'] else 'FAIL'}")

    # 5. Angel Data
    try:
        from modules.angel_data import AngelDataProvider
        from modules.quant_store import QuantStore
        p = AngelDataProvider(QuantStore())
        status = p.status()
        results["angel_data"] = {"ok": True, "detail": f"Configured: {status.get('configured')}, Status: {status.get('status')}"}
    except Exception as exc:
        results["angel_data"] = {"ok": False, "error": str(exc)}
    print(f"  - angel_data: {'PASS' if results['angel_data']['ok'] else 'FAIL'}")

    # 6. Paper Portfolio
    try:
        from modules.paper_portfolio import portfolio_summary
        summ = portfolio_summary()
        results["paper_portfolio"] = {"ok": True, "detail": f"Account cash: Rs.{summ.get('account', {}).get('cash_balance', 0):.2f}"}
    except Exception as exc:
        results["paper_portfolio"] = {"ok": False, "error": str(exc)}
    print(f"  - paper_portfolio: {'PASS' if results['paper_portfolio']['ok'] else 'FAIL'}")

    # 7. Historical Backtester
    try:
        from modules.historical_backtester import get_backtest_report
        rep = get_backtest_report()
        curated = rep.get("curated_portfolio", {})
        pf = curated.get("profit_factor")
        wr = curated.get("win_rate_pct")
        results["historical_backtester"] = {"ok": True, "detail": f"Profit Factor: {pf}, Win Rate: {wr}%"}
    except Exception as exc:
        results["historical_backtester"] = {"ok": False, "error": str(exc)}
    print(f"  - historical_backtester: {'PASS' if results['historical_backtester']['ok'] else 'FAIL'}")

    # 8. Circuit Breaker
    try:
        from modules.circuit_breaker import get_circuit_breaker_status
        cb = get_circuit_breaker_status()
        results["circuit_breaker"] = {"ok": True, "detail": f"Halted: {cb.get('is_halted')}, SL hits today: {cb.get('sl_hit_count')}"}
    except Exception as exc:
        results["circuit_breaker"] = {"ok": False, "error": str(exc)}
    print(f"  - circuit_breaker: {'PASS' if results['circuit_breaker']['ok'] else 'FAIL'}")

    # 9. Price Validation
    try:
        from modules.price_validation import validate_price
        v = validate_price("RELIANCE", 1250.0)
        results["price_validation"] = {"ok": True, "detail": f"Status: {v.get('status')}, Consensus: {v.get('consensus_price')}"}
    except Exception as exc:
        results["price_validation"] = {"ok": False, "error": str(exc)}
    print(f"  - price_validation: {'PASS' if results['price_validation']['ok'] else 'FAIL'}")

    return results


def test_database() -> dict[str, dict]:
    print("\n[2/4] TESTING SQLITE DATABASE & PERSISTENCE...")
    import sqlite3
    from config import DB_PATH

    results = {}
    if not os.path.exists(DB_PATH):
        results["db_exists"] = {"ok": False, "error": f"{DB_PATH} not found"}
        return results

    results["db_exists"] = {"ok": True, "detail": f"Found database at {DB_PATH}"}

    try:
        conn = sqlite3.connect(DB_PATH)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        results["tables"] = {"ok": True, "detail": f"Found {len(tables)} tables: {', '.join(tables[:8])}..."}

        expected_tables = ["picks", "paper_positions", "paper_account", "daily_accuracy"]
        for t in expected_tables:
            if t in tables:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                results[f"table_{t}"] = {"ok": True, "detail": f"{cnt} rows"}
            else:
                results[f"table_{t}"] = {"ok": False, "error": f"Table {t} missing"}
        conn.close()
    except Exception as exc:
        results["db_query"] = {"ok": False, "error": str(exc)}

    for k, v in results.items():
        print(f"  - {k}: {'PASS' if v['ok'] else 'FAIL'} ({v.get('detail') or v.get('error')})")

    return results


def test_apis() -> dict[str, dict]:
    print("\n[3/4] TESTING LIVE DASHBOARD HTTP ENDPOINTS (http://localhost:5001)...")
    import requests

    BASE_URL = "http://localhost:5001"
    endpoints = [
        ("GET", "/"),
        ("GET", "/quant"),
        ("GET", "/api/health"),
        ("GET", "/api/premarket/cockpit"),
        ("POST", "/api/premarket/run"),
        ("GET", "/api/tracking"),
        ("POST", "/api/tracking/update"),
        ("GET", "/api/learning/patterns"),
        ("GET", "/api/backtest/results"),
        ("GET", "/api/paper"),
        ("GET", "/api/history"),
        ("GET", "/api/accuracy"),
        ("GET", "/api/quant"),
    ]

    results = {}
    for method, ep in endpoints:
        url = BASE_URL + ep
        try:
            timeout = 45 if method == "POST" else 15
            if method == "POST":
                resp = requests.post(url, json={}, timeout=timeout)
            else:
                resp = requests.get(url, timeout=timeout)

            status = resp.status_code
            is_json = "application/json" in resp.headers.get("Content-Type", "")
            
            if status in (200, 201):
                detail = f"HTTP {status}"
                if is_json:
                    j = resp.json()
                    detail += f" (JSON keys: {list(j.keys())[:4]})"
                results[f"{method} {ep}"] = {"ok": True, "detail": detail}
            else:
                results[f"{method} {ep}"] = {"ok": False, "error": f"HTTP {status}: {resp.text[:100]}"}
        except Exception as exc:
            results[f"{method} {ep}"] = {"ok": False, "error": str(exc)}

        print(f"  - {method} {ep}: {'PASS' if results[f'{method} {ep}']['ok'] else 'FAIL'}")

    return results


def test_external_providers() -> dict[str, dict]:
    print("\n[4/4] TESTING EXTERNAL PROVIDERS & CREDENTIALS...")
    import requests
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ANGEL_API_KEY, ANGEL_CLIENT_CODE

    results = {}

    # 1. Telegram Bot Connectivity
    if TELEGRAM_BOT_TOKEN:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=8)
            if r.status_code == 200:
                data = r.json().get("result", {})
                bot_name = data.get("username", "Unknown")
                results["telegram_bot"] = {"ok": True, "detail": f"Connected to @{bot_name}"}
            else:
                results["telegram_bot"] = {"ok": False, "error": f"Telegram API returned {r.status_code}: {r.text[:80]}"}
        except Exception as exc:
            results["telegram_bot"] = {"ok": False, "error": str(exc)}
    else:
        results["telegram_bot"] = {"ok": False, "error": "TELEGRAM_BOT_TOKEN not configured"}
    print(f"  - telegram_bot: {'PASS' if results['telegram_bot']['ok'] else 'FAIL'}")

    # 2. Angel One Configuration
    if ANGEL_API_KEY and ANGEL_CLIENT_CODE:
        results["angel_credentials"] = {"ok": True, "detail": f"Client code configured: {ANGEL_CLIENT_CODE}"}
    else:
        results["angel_credentials"] = {"ok": False, "warning": "Angel One credentials empty in local env (active in GitHub Actions Secrets)"}
    print(f"  - angel_credentials: {'PASS' if results['angel_credentials'].get('ok') else 'NOTE'} ({results['angel_credentials'].get('detail') or results['angel_credentials'].get('warning')})")

    # 3. Yahoo Finance Data Feed
    try:
        import yfinance as yf
        ticker = yf.Ticker("RELIANCE.NS")
        info = ticker.fast_info
        last_price = getattr(info, "last_price", None)
        if last_price and last_price > 0:
            results["yahoo_finance"] = {"ok": True, "detail": f"RELIANCE.NS live quote: Rs.{last_price:.2f}"}
        else:
            results["yahoo_finance"] = {"ok": False, "error": "No price returned"}
    except Exception as exc:
        results["yahoo_finance"] = {"ok": False, "error": str(exc)}
    print(f"  - yahoo_finance: {'PASS' if results['yahoo_finance']['ok'] else 'FAIL'}")

    return results


def main() -> None:
    print("=" * 65)
    print("      HELIOS INTRADAY SUPER-RUNNER: FULL SYSTEM & API AUDIT     ")
    print("=" * 65)

    mod_res = test_modules()
    db_res = test_database()
    api_res = test_apis()
    ext_res = test_external_providers()

    all_tests = {**mod_res, **db_res, **api_res, **ext_res}
    total = len(all_tests)
    passed = sum(1 for v in all_tests.values() if v.get("ok"))
    failed = total - passed

    print("\n" + "=" * 65)
    print(f"AUDIT SUMMARY: {passed}/{total} Passed ({(passed/total)*100:.1f}%)")
    print("=" * 65)

    if failed > 0:
        print("\nIDENTIFIED ISSUES / ERRORS:")
        for name, data in all_tests.items():
            if not data.get("ok"):
                print(f"  ❌ {name}: {data.get('error') or data.get('warning')}")
    else:
        print("\nAll systems, modules, database tables, and API endpoints passed with 0 errors!")

    # Save test report artifact
    report_path = Path("data") / "system_test_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "results": all_tests
        }, f, indent=2)
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()
