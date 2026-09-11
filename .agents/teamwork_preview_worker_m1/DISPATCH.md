## 2026-09-09T15:09:48Z

You are Worker M1 for the Intraday Stock Screener project.
Your assigned working directory is: c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\.agents\teamwork_preview_worker_m1

MANDATORY FIRST STEP: Read ORIGINAL_REQUEST.md located at:
c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\ORIGINAL_REQUEST.md
Also read PROJECT.md at:
c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\PROJECT.md
And review the explorer survey reports:
c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\.agents\teamwork_preview_explorer_survey_1\survey_report.md
c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\.agents\teamwork_preview_explorer_survey_1\handoff.md

EXCLUSIVE FILE WRITE OWNERSHIP:
- modules/universe_scanner.py
- modules/stock_tracker.py
- modules/picker.py
- modules/continuous_learning.py
- modules/market_pulse.py
- test_complete_system.py, test_eod_report.py, test_final_picks.py, test_pattern_picks.py, test_accuracy.py
- pytest.ini

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

YOUR ASSIGNED TASKS (Milestone 1: Core System Diagnostic & Bug Resolution):
1. In `modules/universe_scanner.py`:
   - Fix `ImportError: cannot import name '_get_nse_symbol' from 'modules.scanner'` (lines 54, 57). Provide robust symbol normalization (e.g. `symbol.upper().strip() + ('.NS' if not symbol.endswith('.NS') else '')` or as used across scanner). Ensure `_quick_analyze_symbol_with_reason(symbol)` succeeds and does not return `(None, 'error')`.
   - Protect against division-by-zero on line 81 (`price_5d_ago > 0`) and line 89 (`prev_close > 0`).
2. In `modules/stock_tracker.py`:
   - Protect against division-by-zero on line 444 (`if entry and entry > 0:` else `0.0`).
3. In `modules/picker.py`:
   - Protect against division-by-zero on line 54 (`if price and price > 0:` else `0.0`).
   - Remove static/fabricated fallback in `get_historical_accuracy()` (lines 128, 142-149) which returns hardcoded 81.3% win rate and 13 TP / 3 SL. Return honest zero/empty metrics when no closed trades exist in the database (e.g., win_rate: 0.0, tp_count: 0, sl_count: 0, total_closed: 0, avg_return: 0.0, label: "0 Closed Trades", sublabel: "Awaiting Market Execution").
4. In `modules/continuous_learning.py`:
   - Protect against division-by-zero on line 156 (`float(close.iloc[0]) > 0`).
5. In `modules/market_pulse.py`:
   - Fix line 474 dictionary key mismatch: change `n_data.get("news")` to check `n_data.get("items")` (or handle both `n_data.get("items") or n_data.get("news") or []`).
6. Guard root test scripts & configure pytest:
   - Wrap top-level code in `if __name__ == "__main__":` for `test_complete_system.py`, `test_eod_report.py`, `test_final_picks.py`, `test_pattern_picks.py`, and `test_accuracy.py` so that importing them does not trigger live network calls, telegram alerts, or database mutations.
   - Create or update `pytest.ini` with `testpaths = tests` so generic `pytest` runs collect only designated tests in `tests/`.
7. Execute Verifications:
   - Run python compile check: `.venv\Scripts\python -m compileall -q .`
   - Run pytest: `.venv\Scripts\pytest tests/ -v`
   - Run root pytest: `.venv\Scripts\pytest -v` (must complete quickly without hanging)
   - Verify scanner worker: `.venv\Scripts\python -c "from modules.universe_scanner import _quick_analyze_symbol_with_reason; print('Worker result:', _quick_analyze_symbol_with_reason('INFY'))"`
   - Verify news key handling: `.venv\Scripts\python -c "from modules.news_provider import fetch_market_news; d = fetch_market_news(limit=2); items = d.get('items') or d.get('news') or []; print('Items found:', len(items))"`

Document your changes, diffs, and verification commands/outputs in:
`c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\.agents\teamwork_preview_worker_m1\changes.md`
and write a standard handoff report in:
`c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener\.agents\teamwork_preview_worker_m1\handoff.md`.
Notify orchestrator via send_message when complete.
