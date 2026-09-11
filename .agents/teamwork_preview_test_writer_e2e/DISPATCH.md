## 2026-09-09T15:09:48Z
You are the E2E Test Writer for the Intraday Stock Screener project.
Your assigned working directory is: c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\.agents\teamwork_preview_test_writer_e2e

MANDATORY FIRST STEP: Read ORIGINAL_REQUEST.md located at:
c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\ORIGINAL_REQUEST.md
Also read PROJECT.md at:
c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\PROJECT.md

EXCLUSIVE FILE WRITE OWNERSHIP:
- tests/e2e/ (all files within tests/e2e/, e.g., test_tier1_features.py, test_tier2_boundaries.py, test_tier3_combinations.py, test_tier4_scenarios.py, conftest.py)
- TEST_INFRA.md at project root
- TEST_READY.md at project root (when suite is complete and passing)

YOUR MISSION (E2E Testing Track):
Design and build a comprehensive, requirement-driven, opaque-box E2E test suite following the systematic 4-tier methodology:
1. Tier 1 - Feature Coverage (>=5 test cases per feature across all core features in PROJECT.md Feature Inventory):
   - Scanner parallel evaluation & small/midcap universe filtering (2489 active symbols, large cap exclusions)
   - Market pulse live calculations & data feeds
   - 3-period intraday target calculations (+5% to +8% targeting with 1.5 * ATR stops bounded by <=2.0% max loss)
   - 30-minute news cache validation (freshness, 1800s TTL, fallback behavior)
   - Telegram alert formatting & HTML escaping
   - Dashboard web service endpoints (/api/market-pulse, /api/picks, /api/status, port 5001)
2. Tier 2 - Boundary & Corner Cases (>=5 test cases per feature):
   - Zero and negative prices, empty universe results, missing database files, network timeouts, extreme volatility gaps, rate limits.
3. Tier 3 - Cross-Feature Combinations (Pairwise interactions):
   - Scanner -> AI Brain -> Target/Stop Calculator -> Telegram Alert Broadcaster -> Dashboard telemetry.
4. Tier 4 - Real-World Application Scenarios (Realistic market day workflows):
   - Simulate complete 6-market-phase chronological lifecycle:
     - Phase 1: Pre-Market Setup (08:30–09:15)
     - Phase 2: Morning ORB (09:15–10:15)
     - Phase 3: Midday VWAP (10:15–12:30)
     - Phase 4: Afternoon Surge (12:30–14:15)
     - Phase 5: Square-Off (14:15–15:30)
     - Phase 6: Post-Market EOD (15:30–16:00)

Requirements for Tests:
- Must run cleanly with: `.venv\Scripts\pytest tests/e2e/ -v`
- Mock external network calls where appropriate to ensure deterministic, offline-capable, fast execution (< 60s).
- Create `TEST_INFRA.md` at project root documenting test runner, tier count, feature coverage matrix.
- Once all E2E tests pass 100%, publish `TEST_READY.md` at project root.
- Document results in `handoff.md` in your working directory and notify orchestrator via send_message.
