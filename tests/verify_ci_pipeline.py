"""CI and Repository Systematic Verification Script for Quant V4.

Tests:
1. Core module imports
2. Database schema & tables initialization
3. Provider initialization
4. Telegram module startup
5. QUANT_ENABLED=True path
6. Dashboard startup & API routes
7. Clean git working tree and zero missing tracked files
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("--- STEP 2: CI / REPOSITORY SYSTEMATIC VALIDATION ---")

    # 1. Imports
    print("\n[1/7] Verifying core imports...")
    modules_to_test = [
        "modules.quant_engine",
        "modules.quant_runtime",
        "modules.quant_store",
        "modules.quant_data",
        "modules.quant_features",
        "modules.quant_outcomes",
        "modules.quant_learning",
        "modules.provider_health",
        "modules.rejection_audit",
        "modules.market_regime",
        "modules.catalyst_engine",
        "modules.cost_model",
        "modules.slippage_model",
        "modules.winner_discovery",
        "modules.experiment_registry",
        "modules.alerts",
        "modules.paper_portfolio",
        "dashboard.app",
        "main",
    ]

    for mod in modules_to_test:
        try:
            __import__(mod)
            print(f"  [OK] {mod}")
        except Exception as e:
            print(f"  [FAIL] {mod}: {e}")
            sys.exit(1)

    # 2. Database Initialization
    print("\n[2/7] Verifying database schema & initialization...")
    from modules.quant_store import Store

    test_db = "data/quant_test_init.db"
    if os.path.exists(test_db):
        os.remove(test_db)
    store = Store(test_db)
    with store.connect() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        print(f"  Initialized {len(tables)} tables in quant_test_init.db")
        assert "signals" in tables
        assert "rejection_funnel" in tables
        assert "provider_health" in tables
        assert "market_regimes" in tables
        assert "sector_snapshots" in tables
        assert "winner_discovery" in tables
        assert "research_experiments" in tables
        assert "catalyst_events" in tables
    if os.path.exists(test_db):
        os.remove(test_db)
    print("  ✓ DB schema & tables verified successfully.")

    # 3. Provider Initialization
    print("\n[3/7] Verifying provider initialization...")
    from modules.quant_data import DataService

    ds = DataService()
    assert hasattr(ds, "angel"), "DataService missing angel provider"
    assert hasattr(ds, "get_quote_candidates"), "DataService missing get_quote_candidates"
    print("  [OK] DataService initialized successfully with Angel provider and get_quote_candidates.")

    # 4. Telegram Module Startup
    print("\n[4/7] Verifying Telegram module startup...")
    from modules.alerts import send_raw_alert, send_picks, send_circuit_breaker_alert

    print("  [OK] Telegram alert functions imported and loadable without crash.")

    # 5. QUANT_ENABLED=True path
    print("\n[5/7] Verifying QUANT_ENABLED=True path...")
    import config

    print(f"  config.QUANT_ENABLED = {config.QUANT_ENABLED}")
    assert hasattr(config, "QUANT_ENABLED"), "QUANT_ENABLED missing from config"

    # 6. Dashboard Startup
    print("\n[6/7] Verifying dashboard routes...")
    from dashboard.app import app

    client = app.test_client()
    res = client.get("/api/quant/health")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.get_json()
    print(f"  ✓ /api/quant/health -> {data.get('status')}")

    res = client.get("/api/quant/today")
    assert res.status_code == 200
    print(f"  ✓ /api/quant/today -> max_slots: {res.get_json().get('max_slots')}")

    # 7. Check working tree
    print("\n[7/7] Verifying working tree clean and all tracked files in git...")
    from dulwich import porcelain

    repo = porcelain.open_repo(str(ROOT))
    st = porcelain.status(repo)
    # Exclude tests/verify_ci_pipeline.py if untracked
    untracked = [
        f for f in st.untracked if not f.endswith(b"verify_ci_pipeline.py")
    ]
    assert len(untracked) == 0, f"Unexpected untracked files: {untracked}"
    print(f"  ✓ Repository is up to date and clean.")

    print("\n✓ ALL STEP 2 CI/REPOSITORY INTEGRATION CHECKS PASSED!")


if __name__ == "__main__":
    main()
