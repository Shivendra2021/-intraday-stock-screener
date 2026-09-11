# Master Plan: Intraday Stock Screener Audit & Readiness

## Objective
Execute a complete diagnostic audit and bug-fixing pass across the Intraday Stock Screener system, verify full dynamic market intelligence integration, and validate end-to-end single-day operational readiness.

## Execution Tracks & Milestones

### Phase 0: Survey & Scope Enumeration
- Dispatch 3 parallel Explorers:
  - Explorer 1: Core engine & runtime diagnostic survey (`main.py`, `config.py`, `modules/*.py`, unhandled exceptions, division by zero, timeouts, mock fallbacks).
  - Explorer 2: Active Trading Intelligence Engines & Data flow survey (Small/Midcap 2,489 symbols restriction, dynamic market pulse/top movers, 3-period target +5% to +8% with ATR stops, 30-min news cache).
  - Explorer 3: Dashboard telemetry, Telegram broadcaster, operational timing & guide survey (`dashboard/app.py`, telegram broadcaster, pre-market to post-market operational schedule & documentation).
- Merge explorer findings into `PROJECT.md` Feature Inventory, Code Layout, and Milestones.

### Phase 1: Dual Track Execution
- **Implementation Track**:
  - Milestone 1: Comprehensive System Diagnostic & Bug Resolution (code fixes, exception hardening, mock data purging, import/syntax validation).
  - Milestone 2: Active Trading Intelligence Engines Verification & Integration (universe restriction, live market pulse, targets, news cache).
  - Milestone 3: Tomorrow's Single-Day Operational Readiness & Verification (full trading schedule verification, markdown & printable HTML operational guides, dashboard & telegram pipeline validation).
- **E2E Testing Track**:
  - E2E Test Suite Orchestration (Tiers 1-4: Category-Partition, BVA, Pairwise Combinations, Real-World Market Day Scenarios).
  - Produces `TEST_INFRA.md` and `TEST_READY.md`.

### Phase 2: Final Integration & Acceptance
- Final Milestone Phase 1: 100% E2E test pass across all tiers.
- Final Milestone Phase 2: Adversarial coverage hardening (Tier 5 Challenger loop).
- Independent Forensic Audit (`teamwork_preview_auditor`).
- Synthesis and completion report to Parent/Sentinel.
