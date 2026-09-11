# Comprehensive Core Engine & Runtime Diagnostic Survey Report

**Author**: Explorer Subagent 1 (`teamwork_preview_explorer_survey_1`)  
**Mission**: Core Engine & Runtime Diagnostic Survey  
**Target Milestone**: Milestone 1 (System Diagnostic & Bug Resolution)  
**Date**: 2026-09-09  
**Status**: Complete  

---

## Executive Summary

A comprehensive architectural and runtime diagnostic audit was conducted across the **Intraday Stock Screener** (MarketMind Pro) repository. The audit covered all 55 modules in `modules/`, entry point orchestrator `main.py`, configuration engine `config.py`, dashboard backend `dashboard/app.py`, test suites in `tests/`, runner scripts, and operational dependencies.

### Core Survey Findings:
1. **Compilation & Syntax**: Full workspace compilation (`python -m compileall -q .`) completed with zero syntax errors.
2. **Critical Import Failure in Core Scanner**: `modules/universe_scanner.py:54, 57` attempts `from modules.scanner import _get_nse_symbol`. This function **does not exist** in `modules/scanner.py`. In worker processes, this triggers an `ImportError` that is caught silently by an overly broad `except Exception`, causing **every single symbol to fail analysis** (`(None, 'error')`).
3. **Test Runner Pollution & Hangs**: Multiple root-level `test_*.py` files (`test_complete_system.py`, `test_eod_report.py`, `test_final_picks.py`, `test_pattern_picks.py`, `test_accuracy.py`) lack `if __name__ == "__main__":` guards. When standard `pytest` executes from the project root, it discovers and imports these files, executing live web scans, database mutations, and external Telegram broadcasts at import time, hanging pytest collection indefinitely.
4. **Permanent Disconnect in News Integration**: `modules/news_provider.py` returns market news in dictionary key `"items"`, while consumer `modules/market_pulse.py:474` checks `n_data.get("news")`. Because `"news"` is always `None`, live news is completely discarded, and the market pulse is forced to fall back on static curated news.
5. **Static & Fabricated Fallback Metrics**: Multiple modules hardcode static market data and fictitious performance metrics:
   - `modules/market_pulse.py:133-136, 159-163`: Hardcoded index levels for NIFTY 50 (`23,431.50` / `23,635.10`), BANK NIFTY (`56,295.55` / `56,777.55`), and SENSEX (`74,764.23` / `75,577.60`).
   - `modules/market_pulse.py:308-325`: Hardcoded top movers and percentage changes (`TIMKEN (+2.40%)`, `TATASTEEL (+2.50%)`, `COFORGE (-5.38%)`, `INFY (-4.34%)`).
   - `modules/market_pulse.py:335-461`: Hardcoded `get_trending_sectors()` dictionary with fictitious inflows/outflows (`+2.15%`, `-3.85%`).
   - `modules/market_pulse.py:498-579`: 5 static curated geopolitical news headlines from past months.
   - `modules/picker.py:128, 142-149`: Hardcodes `win_rate = 81.3%`, `13 TP Hit / 3 SL Hit` whenever the database is empty or on query exception.
   - `dashboard/app.py:1135-1165`: Hardcoded API consumption counters (`grok_used = 79`, `groq_used = 14`, etc.).
   - `dashboard/templates/index.html:1534, 1541, 2064-2076`: Hardcoded `81.2% Win Rate` and `13 TP / 3 SL Historic Wins`.
6. **Division-by-Zero Vulnerabilities**:
   - `modules/stock_tracker.py:444`: `round((price - entry) / entry * 100, 2)` inside `close_and_report_eod()` lacks zero-check on `entry`.
   - `modules/universe_scanner.py:81, 89`: `((current_price - price_5d_ago) / price_5d_ago) * 100` and `((current_price - prev_close) / prev_close) * 100` lack zero-checks.
   - `modules/picker.py:54`: `(target_price - price) / price * 100` lacks zero-check on `price`.
   - `modules/continuous_learning.py:156`: `((price - float(close.iloc[0])) / float(close.iloc[0])) * 100` lacks zero-check.
7. **Large-Cap Leakage in Fallback Lists**: The SQLite database `stock_universe` contains 2,489 active symbols with all 86 large caps properly deactivated (`is_active = 0`). However, fallback constant `_EXTENDED_UNIVERSE` in `modules/universe_scanner.py:162-280` and `SECTOR_UNIVERSE` in `modules/stock_selector.py:22-34` hardcode Nifty 50 large caps (`RELIANCE`, `TCS`, `INFY`), creating a leak path if the primary scanner fails.

---

## 1. Codebase Architecture & Structural Inventory

### 1.1 Root Configuration and Orchestration
- **`config.py` (216 lines)**: Central settings module. Defines market timing intervals (07:30 to 16:00), universe mode (`small_midcap`), `LARGECAP_EXCLUDE_LIST` (86 mega-caps), OpenRouter/Grok/Groq API keys, RL parameters, and scheduler timings.
- **`main.py` (941 lines)**: Main bot entry point. Houses the dual-session execution loop:
  - **Session 1 (Morning Pipeline)**: 07:50 universe scan → 08:20 deep research → 08:45 dual-brain debate → 08:55 final picks lock → 09:00 Telegram broadcast.
  - **Session 2 (Intraday & Learning)**: 5-minute price tracking, hourly updates, 15:00 preclose scan, 15:31 EOD close, 15:35 winner finder, 15:40 outcome brain, 15:50 after-market learning, 16:00 pattern learning.
  - Background agents: `automation_supervisor.py`, `terminal_updater.py`, `grok_dashboard_agent.py`, `ollama_intraday_agent.py`.

### 1.2 Modules Inventory (`modules/` — 55 Files)
| Category | Primary Modules | Purpose |
|---|---|---|
| **Universe & Data Fetching** | `scanner.py`, `universe_scanner.py`, `universe_cleaner.py`, `fetch.py`, `price_validation.py` | Symbol universe management, 16-worker parallel scanning, Yahoo/jugaad data fetching, multi-source price sanity checks. |
| **Technical & Pattern Analysis** | `analyzer.py`, `stock_selector.py`, `picker.py`, `pattern_researcher.py`, `intraday_pattern_agent.py` | Technical indicators (RSI, EMA, MACD, BB, ADX, ATR), pattern classification, risk-reward calculation, Top 3 picks selection. |
| **Intelligence & LLM Brains** | `grok_brain.py`, `dual_brain.py`, `brain_commands.py`, `eod_outcome_brain.py`, `grok_dashboard_agent.py`, `ollama_intraday_agent.py` | OpenRouter Grok-3 mini / GPT-4o / Groq DeepSeek multi-brain validation, morning debate, candidate review. |
| **Tracking & Trade Lifecycle** | `stock_tracker.py`, `paper_portfolio.py`, `accuracy_tracker.py`, `tracker.py` | Live 5-minute market tracking, TP/SL alerts, paper position execution, win-rate tracking. |
| **Reinforcement Learning** | `bandit_selector.py`, `rl_intraday_manager.py` | Contextual LinUCB bandit for candidate ranking; PPO-inspired intraday trailing stop & exit policy. |
| **Learning & Post-Market** | `after_market_learning.py`, `market_learner.py`, `pattern_learner.py`, `winner_finder.py`, `continuous_learning.py` | End-of-day winner analysis (+7% intraday gainers), pattern extraction, weight updating. |
| **Alerts & Telemetry** | `alerts.py`, `market_pulse.py`, `news.py`, `news_provider.py`, `terminal_updater.py` | HTML Telegram broadcaster, dynamic market pulse API, RSS/TheNewsAPI aggregator. |
| **System Reliability** | `automation_supervisor.py`, `heavy_job_coordinator.py`, `db_migrations.py`, `runtime_guard.py`, `self_healing.py` | Windows sleep/wake recovery, heavy-job concurrency locks, SQLite schema migrations. |

### 1.3 Dashboard Web Service (`dashboard/` — 1,323 lines)
- **`dashboard/app.py`**: Flask WSGI app served on port `5001` with Waitress (32 threads, single-instance mutex).
- Exposes 36 REST endpoints including `/api/market-pulse`, `/api/picks`, `/api/accuracy`, `/api/health`, `/api/terminal`, and `/api/system/start`.
- Template `dashboard/templates/index.html` (90,870 bytes) provides complete command-center UI.

---

## 2. Identified Runtime Errors, Flaws, and Vulnerabilities

### 2.1 Critical Import & Logic Errors

#### Bug 1: Missing `_get_nse_symbol` breaks `universe_scanner.py`
- **Location**: `modules/universe_scanner.py:54, 57`
  ```python
  54: from modules.scanner import _get_nse_symbol
  ...
  57: nse_sym = _get_nse_symbol(symbol)
  ```
- **Observation**: Running `.venv\Scripts\python -c "from modules.scanner import _get_nse_symbol"` results in:
  ```
  ImportError: cannot import name '_get_nse_symbol' from 'modules.scanner'
  ```
- **Impact**: In `_quick_analyze_symbol_with_reason(symbol)`, this import is attempted on every stock. The `except Exception:` block at lines 119-120 catches the `ImportError` and returns `(None, "error")`. Consequently, **all 16 parallel scan batches fail 100% of symbols**, forcing `main.py` to trigger fallback scans or report zero candidates.
- **Remediation**: Either implement `_get_nse_symbol(symbol: str) -> str` in `modules/scanner.py` or use `_clean_symbol(symbol)` and append `.NS` directly in `universe_scanner.py`.

#### Bug 2: News Key Mismatch breaks Live News in `modules/market_pulse.py`
- **Location**: `modules/market_pulse.py:472-475`
  ```python
  472: from modules.news_provider import fetch_market_news
  473: n_data = fetch_market_news(limit=6)
  474: if n_data and n_data.get("news"):
  475:     for item in n_data["news"][:4]:
  ```
- **Observation**: `modules/news_provider.py:133, 148` returns:
  ```python
  {"items": items, "provider": ..., "count": ...}
  ```
- **Impact**: `n_data.get("news")` evaluates to `None`. The live news list is always empty (`live_news = []`). The engine always defaults to appending outdated static curated headlines from lines 498-579.
- **Remediation**: Change `n_data.get("news")` to `n_data.get("items") or n_data.get("news") or []`.

---

### 2.2 Test Suite Execution Bottlenecks & Missing Import Guards

#### Flaw 3: Top-Level Execution in Root `test_*.py` Files Hangs Pytest
- **Location**:
  - `test_complete_system.py:17-37`: Calls `generate_morning_report()`, `send_morning_health_check()`, `send_morning_news()`, `generate_detailed_eod_report()` at root level.
  - `test_eod_report.py:8-15`: Calls `_get_top10_performers()` and `send_end_of_day_report()`.
  - `test_final_picks.py:9-19`: Calls `generate_picks_for_tomorrow()` and `send_morning_final_picks()`.
  - `test_pattern_picks.py:4-11`: Calls `generate_picks_for_tomorrow()` and `send_pattern_picks()`.
  - `test_accuracy.py:8-25`: Mutates `data/accuracy.db` on import.
- **Observation**: Running `.venv\Scripts\pytest -v` causes pytest to discover root `test_*.py` files. Importing `test_complete_system.py` begins executing network calls and scraping live market data, causing pytest test collection to hang indefinitely.
- **Impact**: Automation scripts and CI/CD pipelines running `pytest` fail or hang.
- **Remediation**: Wrap all top-level executable code in root test scripts with `if __name__ == "__main__":` blocks or relocate them to `tools/manual_tests/`.

#### Bottleneck 4: Synchronous Full Universe Scan in Ollama State Helper
- **Location**: `modules/ollama_intraday_agent.py:720-733`
  ```python
  730: state = run_ollama_cycle(send_telegram=False, study=False)
  ```
- **Observation**: Called by `modules/intraday_pattern_agent.py:639-641` via `ollama_intraday_boost(row)`. When `data/ollama_agent_state.json` is missing or >30 minutes old, `get_ollama_agent_state()` synchronously triggers `run_ollama_cycle()` which calls `scan_full_universe()`.
- **Impact**: Unit tests and morning pipeline stages experience sudden 2-to-5 minute synchronous blocking freezes.
- **Remediation**: If state is expired and heavy job lock cannot be acquired or if called in non-daemon mode, return cached state or default empty metrics without synchronously blocking.

---

### 2.3 Division-by-Zero Vulnerabilities

#### Flaw 5: Unprotected Division in `stock_tracker.py` EOD Close
- **Location**: `modules/stock_tracker.py:444`
  ```python
  443: entry = data.get("entry_price", price)
  444: pnl   = round((price - entry) / entry * 100, 2)
  ```
- **Observation**: Line 314 in the same file protects against zero:
  `pnl = round((price - entry) / entry * 100, 2) if entry > 0 else 0.0`.
  Line 444 omitted the `if entry > 0` condition.
- **Impact**: If a tracked pick is initialized with `entry_price <= 0`, `close_and_report_eod()` crashes with `ZeroDivisionError` at 15:31 market close.
- **Remediation**: Add `if entry and entry > 0 else 0.0`.

#### Flaw 6: Unprotected Division in `universe_scanner.py` Metrics
- **Location**: `modules/universe_scanner.py:81, 89`
  ```python
  81: price_change_pct = ((current_price - price_5d_ago) / price_5d_ago) * 100
  ...
  89: gap_up = ((current_price - prev_close) / prev_close) * 100
  ```
- **Impact**: If `price_5d_ago == 0` or `prev_close == 0`, raises `ZeroDivisionError`.
- **Remediation**: Add `if price_5d_ago > 0 else 0.0` and `if prev_close > 0 else 0.0`.

#### Flaw 7: Unprotected Division in `picker.py` Upside Calculation
- **Location**: `modules/picker.py:54`
  ```python
  54: upside_pct = (target_price - price) / price * 100
  ```
- **Impact**: If `price <= 0`, raises `ZeroDivisionError`.
- **Remediation**: Add `if price > 0 else 0.0`.

#### Flaw 8: Unprotected Division in `continuous_learning.py`
- **Location**: `modules/continuous_learning.py:156`
  ```python
  156: change_1m = ((price - float(close.iloc[0])) / float(close.iloc[0])) * 100
  ```
- **Impact**: If `float(close.iloc[0]) == 0`, raises `ZeroDivisionError`.
- **Remediation**: Add zero-check on divisor.

---

### 2.4 Stale Mock Data and Fabricated Fallbacks

#### Flaw 9: Fabricated System Accuracy in `modules/picker.py`
- **Location**: `modules/picker.py:128, 141-149`
  ```python
  128: win_rate = (tp / closed * 100) if closed > 0 else 81.3
  ...
  141: except Exception as exc:
  142:     return {
  143:         "win_rate": 81.3,
  144:         "tp_count": 13,
  145:         "sl_count": 3,
  146:         "total_closed": 16,
  147:         "avg_return": 5.4,
  148:         "label": "81.3% System Accuracy",
  149:         "sublabel": "13 TP Hit / 3 SL Hit",
  150:     }
  ```
- **Impact**: Violates Acceptance Criteria requirement that no static or fabricated percentages remain. When no trades have closed, the system claims 81.3% historical accuracy.
- **Remediation**: Return `win_rate: 0.0`, `total_closed: 0`, and `label: "Awaiting Completed Trades"`.

#### Flaw 10: Static Indices, Movers, Sectors & News in `modules/market_pulse.py`
- **Location**:
  - `modules/market_pulse.py:133-136, 159-163`: Hardcoded index prices and point changes.
  - `modules/market_pulse.py:308-325`: Hardcoded top movers and percentage changes (`TIMKEN (+2.40%)`, `TATASTEEL (+2.50%)`, etc.).
  - `modules/market_pulse.py:335-461`: `get_trending_sectors()` is 100% hardcoded python dictionary.
  - `modules/market_pulse.py:498-579`: Hardcoded 5 news items from past months.
- **Impact**: Active endpoint `/api/market-pulse` delivers stale, static, and fabricated data to dashboard users and API consumers whenever yfinance is rate-limited or during weekend/pre-market hours.
- **Remediation**: Query real OHLCV data from `data/history.db` or return explicit empty/live states (`status: "awaiting_feed"`) rather than static fake prices.

#### Flaw 11: Static Hardcoded Values in Dashboard & Template
- **Location**:
  - `dashboard/app.py:1135-1165`: Hardcoded usage numbers (`grok_used = 79`, `groq_used = 14`, `news_used = 12`, `telegram_used = 8`, `nse_quotes_used = 240`).
  - `dashboard/templates/index.html:1534, 1541, 2064-2076`: Hardcoded `81.2% Win Rate`, `13 TP Hit • 3 SL Hit`.
- **Impact**: Telemetry displays fabricated API usage and win rates regardless of actual system operation.
- **Remediation**: Bind dashboard telemetry to SQLite audit logs (`data/telegram_delivery.jsonl`, `grok_evidence_reviews`, and `daily_accuracy`).

---

### 2.5 Universe Integrity & Large-Cap Leakage

#### Flaw 12: Large-Cap Leaks in Fallback Constants
- **Location**:
  - `modules/universe_scanner.py:162-280`: `_EXTENDED_UNIVERSE` includes `RELIANCE`, `TCS`, `HDFCBANK`, `INFY`, `ICICIBANK`, `SBIN`.
  - `modules/stock_selector.py:22-34`: `SECTOR_UNIVERSE` hardcodes Nifty 50 tickers.
- **Observation**: The SQLite database `stock_universe` contains 2,615 rows, of which exactly 2,489 are active (`is_active = 1`). All 86 large caps in `config.py:LARGECAP_EXCLUDE_LIST` have `is_active = 0`.
- **Impact**: If `modules/scanner.py:get_universe()` fails or falls back, `universe_scanner.py` loads `_EXTENDED_UNIVERSE`, which injects large caps into the active trading engine.
- **Remediation**: Filter `_EXTENDED_UNIVERSE` and `SECTOR_UNIVERSE` through `is_small_or_midcap()` or `LARGECAP_EXCLUDE_LIST`.

---

## 3. Test Suite, Runner Scripts & Environment Assessment

### 3.1 Python Environment & Requirements
- **Python Version**: Python 3.14.4 (Windows 64-bit).
- **Virtual Environment**: `.venv` contains all dependencies in `requirements.txt` (`yfinance`, `nsepython`, `newspaper4k`, `flask`, `apscheduler`, `python-dotenv`, `requests`, `pandas`, `numpy`, `lxml`, `feedparser`, `jugaad-data`, `curl_cffi`, `newsapi-python`, `waitress`).
- All 15 required packages import cleanly.

### 3.2 Unit Test Execution
- Command: `.venv\Scripts\pytest tests/ -v`
- Result: **49 passed in 46.67s** (100% pass rate).
- Test Coverage Summary:
  - `tests/test_after_market_learning.py` (4 tests) — PASSED
  - `tests/test_after_market_scoring_boost.py` (2 tests) — PASSED
  - `tests/test_dashboard_migrations.py` (2 tests) — PASSED
  - `tests/test_intraday_pattern_agent.py` (3 tests) — PASSED
  - `tests/test_intraday_pattern_scan.py` (16 tests) — PASSED
  - `tests/test_market_pulse_and_history.py` (7 tests) — PASSED
  - `tests/test_recent_fixes.py` (4 tests) — PASSED
  - `tests/test_rl_system.py` (11 tests) — PASSED

### 3.3 Runner Scripts
- `run_system.ps1`: Orchestrates bot, dashboard, and daily tasks via PowerShell.
- `run_dashboard.bat` / `run_dashboard.ps1`: Launches Waitress dashboard service on `http://localhost:5001`.
- `setup_task.ps1` / `check_task.ps1` / `stop_task.ps1`: Windows Task Scheduler automation.

---

## 4. Prioritized Remediation Strategy for Milestone 1

### Phase 1: Critical Engine Fixes (Priority: Blocker)
1. **Fix `universe_scanner.py` Import**:
   - Define `_get_nse_symbol(symbol: str) -> str` in `modules/scanner.py` (or normalize inline in `universe_scanner.py:54-57`).
   - Eliminate silent error suppression in worker processes.
2. **Isolate Root Test Scripts**:
   - Add `if __name__ == "__main__":` guards to `test_complete_system.py`, `test_eod_report.py`, `test_final_picks.py`, `test_pattern_picks.py`, and `test_accuracy.py`.
   - Ensure clean `pytest` execution from root without hanging.
3. **Fix News Consumer Key Mismatch**:
   - Update `modules/market_pulse.py:474` to consume `n_data.get("items")`.

### Phase 2: Math Safety & Division-by-Zero Protection (Priority: High)
1. **Patch Div-by-Zero in Stock Tracker**:
   - Update `modules/stock_tracker.py:444` to guard `if entry and entry > 0 else 0.0`.
2. **Patch Div-by-Zero in Universe Scanner & Picker**:
   - Update `modules/universe_scanner.py:81, 89` and `modules/picker.py:54`.
3. **Patch Div-by-Zero in Continuous Learning**:
   - Update `modules/continuous_learning.py:156`.

### Phase 3: Elimination of Stale Mock Data & Fabricated Metrics (Priority: High)
1. **Cleanse `modules/market_pulse.py`**:
   - Replace static fallback dictionaries with dynamic database lookups or explicit `"feed_unavailable"` states.
   - Replace hardcoded `get_trending_sectors()` with dynamic calculations from active symbols.
   - Remove hardcoded past-month news articles.
2. **Cleanse `modules/picker.py`**:
   - Remove fake `81.3% Win Rate / 13 TP Hit / 3 SL Hit` fallback.
3. **Cleanse Dashboard UI**:
   - Remove static hardcoded metrics from `dashboard/app.py:1135-1165` and `dashboard/templates/index.html`.

### Phase 4: Universe Integrity & Large-Cap Leak Prevention (Priority: Medium)
1. **Filter Fallback Lists**:
   - Apply `is_small_or_midcap()` filter to `_EXTENDED_UNIVERSE` in `modules/universe_scanner.py` and `SECTOR_UNIVERSE` in `modules/stock_selector.py`.
2. **Add Regression Tests**:
   - Write automated test verifying that no symbol in `LARGECAP_EXCLUDE_LIST` can ever be returned by `universe_scanner.py` or `picker.py`.

---

## Conclusion
The codebase possesses a mature, well-conceived trading system architecture, but critical import bugs (`_get_nse_symbol`), test runner pollution, and ubiquitous static/fabricated mock fallbacks undermine system reliability. Implementing the 4-phase remediation strategy outlined above will establish an airtight foundation for tomorrow's operational readiness.
