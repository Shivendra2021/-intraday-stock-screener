# Orchestration Plan - Intraday Stock Screener Gen 2

## Mission Objective
Fulfill requirements R1, R2, and R3 to achieve full operational readiness for tomorrow's live trading day, backed by verified tests, dynamic live data pipelines, and a complete 6-phase operational runbook.

## Work Decomposition & Milestones

### Track A: Implementation Track
1. **Milestone M1: Core System Diagnostic & Bug Resolution**
   - Address survey findings:
     - Fix `_get_nse_symbol` ImportError in `modules/universe_scanner.py`.
     - Guard root test scripts (`test_*.py`) with `if __name__ == '__main__':` or isolate to prevent live network hangs during pytest.
     - Hardened division-by-zero checks across `stock_tracker.py`, `universe_scanner.py`, `picker.py`, and `continuous_learning.py`.
     - Fix news cache dictionary key mismatch (`"items"` vs `"news"` in `modules/market_pulse.py:474`).
     - Remove static mock / dummy price and percentage fallbacks in core modules.
   - Verification: All modules compile (`python -m py_compile`), unit tests pass without errors.

2. **Milestone M2: Active Trading Intelligence Engines**
   - Address survey findings:
     - Enforce Small & Midcap exclusion (`config.LARGECAP_EXCLUDE_LIST`) across fallback universes (`_EXTENDED_UNIVERSE`, `SECTOR_UNIVERSE`).
     - Dynamic live market pulse & top movers calculation engine (ensure live/cached calculation without hardcoded numbers).
     - 3-period intraday high-return target verification (+5% to +8% targeting with ATR stops bounded by <=2%).
     - 30-minute news cache integration and integrity check.
   - Verification: Intelligence engines produce live/dynamic outputs and respect constraints.

3. **Milestone M3: Operational Readiness & Guides**
   - Telegram HTML entity escaping (`html.escape()` on dynamic text to prevent 400 Bad Request).
   - Dashboard web service verification on port 5001 (Waitress WSGI).
   - Author complete 6-phase master operational runbook in markdown (`OPERATIONAL_GUIDE.md`) and self-contained printable HTML (`operational_guide.html`).
   - Verification: Runbook covers 08:30 to 16:00 chronological pipeline; HTML renders cleanly with `@media print`.

### Track B: Requirement-Driven E2E Testing Track
- Design opaque-box test suite independent of implementation details:
  - Tier 1: Feature Coverage (>=5 per feature across universe filter, market pulse, 3-period targets, news cache, alerts, dashboard).
  - Tier 2: Boundary & Corner Cases (empty DB, missing network, zero volumes, extreme ATRs, special chars in news/alerts).
  - Tier 3: Cross-Feature Combinations (scanner + pulse + picker + alert pipeline integration).
  - Tier 4: Real-World Intraday Market Scenarios (Pre-Market -> ORB -> VWAP -> Afternoon Surge -> Square-Off -> Post-Market).
- Publish `TEST_INFRA.md` and `TEST_READY.md`.

### Final Phase: Milestone M4 & Forensic Audit
- Pass 100% of E2E tests (Tiers 1-4).
- Dispatch Challengers for Tier 5 adversarial stress testing.
- Dispatch Forensic Auditor for binary veto integrity verification.
- Final completion report to parent / Sentinel.
