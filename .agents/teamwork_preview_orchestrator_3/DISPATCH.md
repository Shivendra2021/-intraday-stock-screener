## 2026-09-09T16:30:00Z
<USER_REQUEST>
You are the Project Orchestrator (teamwork_preview_orchestrator), generation 3.

Your assigned working directory is:
`c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\.agents\teamwork_preview_orchestrator_3`

The project root workspace is:
`c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener`

The authoritative user request is recorded at:
`c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\ORIGINAL_REQUEST.md`

## Context & Succession
Previous orchestrators encountered network disconnects and were re-spawned.
Phase 0 surveys have ALREADY been executed and synthesized into:
`c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\PROJECT.md`
Survey reports and previous worker states exist in:
- `.agents/teamwork_preview_explorer_survey_1/`
- `.agents/teamwork_preview_explorer_survey_2/`
- `.agents/teamwork_preview_explorer_survey_3/`
- `.agents/teamwork_preview_worker_m1_gen2/`
- `.agents/teamwork_preview_test_writer_e2e_gen2/`

## Requirements to Fulfill

### R1. Comprehensive System Diagnostic & Bug Resolution
Audit all core runtime components (`main.py`, `config.py`, `modules/*.py`, and `dashboard/app.py`). Identify and resolve any remaining syntax issues, unhandled exceptions, division-by-zero risks, timeout bottlenecks, and stale mock data fallbacks.

### R2. Verification of Active Trading Intelligence Engines
Verify end-to-end integration of the Small & Midcap universe restriction (2,489 symbols filtered, all large caps excluded), the dynamic live market pulse & top movers calculation engine, the 3-period intraday high-return targets (+5% to +8% targeting with ATR stops), and the 30-minute news cache.

### R3. Tomorrow's Single-Day Operational Readiness Verification
Validate that the bot engine, AI brain, dashboard telemetry, and Telegram alert broadcaster operate reliably without failure from pre-market setup (08:30 AM) through post-market reconciliation (16:00 PM). Ensure the operational guide accurately reflects the system's execution pipeline.

## Acceptance Criteria
### Diagnostics & Integrity
- All python modules compile and pass smoke testing without unhandled exceptions.
- No static or fabricated stock prices/percentages remain in the active market pulse endpoints.
- The dashboard web service (`http://localhost:5001`) and Telegram delivery pipeline are 100% operational.

### Master Operational Readiness
- Chronological breakdown covers every market phase: Pre-Market (08:30–09:15), Morning ORB (09:15–10:15), Midday VWAP (10:15–12:30), Afternoon Surge (12:30–14:15), Square-Off (14:15–15:30), and Post-Market EOD (15:30–16:00).
- Complete operational guide available in both markdown and printable HTML formats.

## Operational Discipline
1. Initialize your `BRIEFING.md`, `plan.md`, and maintain `progress.md` in your working directory.
2. Review existing files, survey findings, and previous progress, then dispatch Workers, Reviewers, and Testers to drive all requirements to 100% completion.
3. Keep `progress.md` updated with timestamped entries so sentinel monitoring can track liveness and status.
4. When all tasks are fully accomplished, verified with passing tests and ready for independent audit, deliver your completion report to Sentinel.
</USER_REQUEST>
