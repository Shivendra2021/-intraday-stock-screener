## 2026-09-09T15:48:47Z

You are teamwork_preview_worker_m1_gen2, the Diagnostic & Bug Resolution Worker for Milestone M1.

Working Directory: c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\.agents\teamwork_preview_worker_m1_gen2
Parent Conversation ID: 8818e294-6360-4a87-a436-f55bdded3485

Read the following documents immediately before starting:
1. c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\ORIGINAL_REQUEST.md
2. c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\PROJECT.md
3. c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\.agents\teamwork_preview_explorer_survey_1\survey_report.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your Exclusively Owned Files:
- modules/scanner.py
- modules/universe_scanner.py
- modules/stock_tracker.py
- modules/picker.py
- modules/continuous_learning.py
- modules/market_pulse.py (news dictionary key fix and zero checks)
- modules/ollama_intraday_agent.py
- Root test scripts: test_complete_system.py, test_eod_report.py, test_final_picks.py, test_pattern_picks.py, test_accuracy.py
- pytest.ini

Tasks to Execute for Milestone M1:
1. Fix `_get_nse_symbol` ImportError:
   Implement `_get_nse_symbol(symbol: str) -> str` in `modules/scanner.py` (and export it in `__all__` if used) or make sure `from modules.scanner import _get_nse_symbol` in `modules/universe_scanner.py` works seamlessly and cleans symbols appropriately (e.g. stripping exchange suffixes and returning NSE ticker format).
2. Guard root test scripts:
   Wrap top-level execution code in `test_complete_system.py`, `test_eod_report.py`, `test_final_picks.py`, `test_pattern_picks.py`, `test_accuracy.py` inside `if __name__ == "__main__":` guards so that importing them during `pytest` test collection does not hang, execute live web scans, or mutate databases.
   Also configure `pytest.ini` with `testpaths = tests` to ensure default pytest invocations focus on the test suite.
3. Fix Division-by-Zero Vulnerabilities:
   - `modules/stock_tracker.py:444`: Guard `round((price - entry) / entry * 100, 2)` with `if entry and entry > 0 else 0.0`.
   - `modules/universe_scanner.py:81, 89`: Guard price change and gap up calculations with zero checks on `price_5d_ago` and `prev_close`.
   - `modules/picker.py:54`: Guard upside calculation with zero check on `price`.
   - `modules/continuous_learning.py:156`: Guard percentage change calculation with zero check on `float(close.iloc[0])`.
4. Fix News Cache Consumer Key Mismatch:
   In `modules/market_pulse.py:474`, change `n_data.get("news")` to `n_data.get("items") or n_data.get("news") or []`.
5. Fix Synchronous Scan Bottleneck:
   In `modules/ollama_intraday_agent.py`, ensure that if state is expired and lock cannot be acquired or during non-daemon execution, return cached/empty state gracefully without triggering a synchronous 3-minute blocking universe scan.
6. Verification:
   Run `python -m compileall -q .` to confirm zero syntax errors.
   Run `pytest tests/ -v` to confirm existing test suite passes without hanging.
7. Reporting:
   Write `changes.md` and `handoff.md` in your assigned working directory (`.agents/teamwork_preview_worker_m1_gen2/`).
   Notify parent via `send_message` with recipient `8818e294-6360-4a87-a436-f55bdded3485`.
