# Handoff Report: Milestone 3 Survey — Dashboard, Telegram Alerts & Operations

**Date**: 2026-09-09  
**Agent**: Explorer Subagent 3 (`teamwork_preview_explorer_survey_3`)  
**Parent Agent**: `0d6e8edb-9654-4cc7-b83e-ead2b88d425e`  
**Milestone**: Milestone 3 Survey  
**Type**: Hard Handoff (Investigation Complete)

---

## 1. Observation

### 1.1 Dashboard & Frontend Telemetry
1. `dashboard/app.py` line 1322:
   ```python
   serve(app, host="0.0.0.0", port=5001, threads=32, connection_limit=200, _quiet=True)
   ```
   The dashboard runs on port 5001 via Waitress WSGI server, with single-instance mutex locking via `acquire_single_instance("marketmind-dashboard")` (line 1314).
2. Hardcoded mock metrics in `dashboard/app.py`:
   - Line 1000: `return jsonify({"error": str(e), "top_sectors": ["IT", "Finance", "Auto"]})`
   - Lines 1135–1165:
     ```python
     grok_used = 79
     ...
     groq_used = 14
     news_used = 12
     telegram_used = 8
     ...
     nse_quotes_used = 240
     ```
3. Hardcoded mock metrics in `modules/market_pulse.py`:
   - Lines 133–136:
     ```python
     defaults = {
         "^NSEI": {"price": 23431.50, "prev": 23635.10, "high": 23758.95, "low": 23400.40},
         "^NSEBANK": {"price": 56295.55, "prev": 56777.55, "high": 57150.20, "low": 56220.10},
         "^BSESN": {"price": 74764.23, "prev": 75577.60, "high": 76180.50, "low": 74680.20},
     }
     ```
   - Lines 159–163: Fallback NIFTY 50 price `23,635.10`, BANK NIFTY `56,777.55`, SENSEX `75,577.60`.
   - Lines 308–320: Fallback top movers hardcodes TIMKEN (+2.40%), TATASTEEL (+2.50%), CGPOWER (+1.78%), NATIONALUM (+1.77%), COFORGE (-5.38%), INFY (-4.34%), GODREJPROP (-2.60%), PERSISTENT (-2.54%).
   - Lines 335–461 (`get_trending_sectors()`): Entirely static dictionary defining "Nifty Metal & Mining" (+2.15%), "Nifty Capital Goods" (+1.85%), "Nifty Energy" (+1.40%), "Nifty IT" (-3.85%), "Nifty Realty" (-2.65%) with static institutional flow blurbs.
   - Lines 498–579 (`get_geopolitical_market_news()`): Contains 5 hardcoded static news items (Red Sea, NATO munitions, Fed minutes, PBOC stimulus, RBI repo) appended when live news is < 4 items.
4. Hardcoded accuracy fallback in `modules/picker.py`:
   - Lines 128–149:
     ```python
     win_rate = (tp / closed * 100) if closed > 0 else 81.3
     avg_ret = conn.execute("SELECT AVG(result_return) FROM picks WHERE result_return IS NOT NULL").fetchone()[0] or 5.4
     ...
     return {
         "win_rate": 81.3,
         "tp_count": 13,
         "sl_count": 3,
         "total_closed": 16,
         "avg_return": 5.4,
         "label": "81.3% System Accuracy",
         "sublabel": "13 TP Hit / 3 SL Hit",
     }
     ```
5. Frontend templates hardcoded values in `dashboard/templates/index.html`:
   - Lines 1534, 1541: `Overall Accuracy: <span id="header-accuracy-rate">81.2%</span> Win Rate`, `13 TP / 3 SL Historic Wins`
   - Lines 2064–2076: `systemAccuracyStats.win_rate || '81.2'%`, `13 TP Hit • 3 SL Hit`, `Avg Profit: +5.05%`, `Total Closed: 16`, `TP: 13 | SL: 3`.

### 1.2 Telegram Alert Broadcaster
1. `modules/alerts.py` line 50:
   ```python
   def _send(text: str, review_with_grok: bool = True, event_type: str = "telegram_message") -> bool:
   ```
   - Sends HTML via raw HTTP requests (`requests.post(url, json=payload, timeout=15)`).
   - Retry logic on 429/503 with exponential backoff (`2 ** attempt` — 1s, 2s, 4s).
   - Audits every delivery to `data/telegram_delivery.jsonl` with token redaction.
2. Missing HTML entity escaping:
   - Dynamic parameters (e.g. `reasons`, `symbol`, `note`) in `modules/alerts.py` lines 461–542 are formatted directly into HTML strings without `html.escape()`. Characters like `<`, `>`, `&` will cause Telegram API 400 Bad Request entity parsing errors.

### 1.3 Market Phase Execution Pipeline in `main.py`
1. APScheduler registration in `main.py` lines 847–871:
   - 07:45: `job_health_check`
   - 07:50 (`MORNING_UNIVERSE_SCAN_START`): `run_morning_session` ("premarket_morning_pipeline")
   - 08:35: `job_price_validation_warmup`
   - 08:55 (`MORNING_FINAL_PICKS`): `job_morning_delivery_guard`
   - 09:10: `job_morning_delivery_guard`
   - 09:15–15:30: Every 5 min `job_tracking_update`
   - 10:00, 11:00, 12:00, 13:00, 14:00: `job_tracking_status`
   - 15:00 (`PRECLOSE_SCAN_TIME`): `job_preclose`
   - 15:31: `job_tracking_eod`
   - 15:35 (`MARKET_LEARNER_START`): `job_find_winners`
   - 15:40 (`EOD_OUTCOME_BRAIN_TIME`): `job_eod_outcome_brain`
   - 15:50 (`AFTER_MARKET_LEARNING_TIME`): `job_after_market_learning`
   - 16:00 (`LEARNER_START`): `job_pattern_learning`
   - 16:15: `run_backup`
   - 18:00: `job_heartbeat`

### 1.4 Documentation & Guides
1. Search with `find_by_name` across the entire workspace for operational guides revealed **0 Markdown guides** and **0 HTML operational guides**.
2. Only `README.md` (49 lines) and binary Word/PDF files in gitignored `output/doc/` exist.
3. No printable operational guide exists in the repository.

### 1.5 Pytest Execution
1. Executed `.venv\Scripts\pytest tests/ -v`:
   - Result: `49 passed in 46.67s` (100% pass rate).

---

## 2. Logic Chain

1. **Static Mock Violation**:
   - `ORIGINAL_REQUEST.md` Acceptance Criteria specifies: *"No static or fabricated stock prices/percentages remain in the active market pulse endpoints."*
   - Direct observations 1.1(2), 1.1(3), 1.1(4), and 1.1(5) prove that static prices (`23,635.10`, `56,777.55`), static sector performance (`+2.15%`, `+1.85%`, `-3.85%`), static news items, and fabricated accuracy metrics (`81.3%`, `13 TP / 3 SL`) exist in `modules/market_pulse.py`, `modules/picker.py`, and `dashboard/templates/index.html`.
   - Therefore, Milestone 3 must purge these fabricated fallbacks and implement dynamic live calculations with honest "Pre-Market / Market Closed" statuses.

2. **Telegram Entity Escaping**:
   - Observation 1.2(2) shows `parse_mode: "HTML"` is used without `html.escape()`.
   - Market data reasons and news summaries often contain characters such as `<` (e.g. `< 50-day EMA`) or `&` (e.g. `M&M`, `L&T`).
   - If unescaped, Telegram's API returns `400: Bad Request: can't parse entities`, dropping the alert.
   - Therefore, Milestone 3 must wrap dynamic text insertions in `html.escape()`.

3. **Missing Operational Guides**:
   - Observation 1.4 confirms that neither `OPERATIONAL_GUIDE.md` nor `operational_guide.html` exists in the repository.
   - `ORIGINAL_REQUEST.md` requires: *"Complete operational guide available in both markdown and printable HTML formats"* covering all 6 market phases.
   - Therefore, Milestone 3 must author both `OPERATIONAL_GUIDE.md` and `operational_guide.html` with full coverage of the 6 phases, operator commands, and emergency failovers.

---

## 3. Caveats

1. The test suite currently validates that `get_trending_sectors()` returns `buying_sectors` and `losing_sectors` with length > 0 (`tests/test_market_pulse_and_history.py` line 75). When making sectors dynamic, the returned schema must preserve `buying_sectors` and `losing_sectors` keys to keep existing tests passing.
2. If the market is closed or outside trading hours, dynamic calculations must cleanly report zero/pre-market status without failing or raising unhandled exceptions.

---

## 4. Conclusion

The system's core architecture and scheduling engine are healthy (49/49 tests pass, port 5001 Waitress server operational, dual-brain debate wired). To fulfill Milestone 3 requirements and achieve complete operational readiness for tomorrow's full trading day, the following tasks must be implemented:
1. **Author `OPERATIONAL_GUIDE.md`**: Chronological runbook across the 6 market phases (08:30 to 16:00), operator checklists, commands, and disaster recovery.
2. **Author `operational_guide.html`**: Zero-dependency printable HTML guide with `@media print` CSS for PDF export.
3. **Purge Static Mock Data**: Clean up `modules/market_pulse.py`, `modules/picker.py`, `dashboard/app.py`, and `dashboard/templates/index.html` to remove fabricated numbers, static sector percentages, and stale news items.
4. **Harden Telegram Broadcaster**: Apply `html.escape()` to dynamic strings before Telegram HTML dispatch.

---

## 5. Verification Method

1. **Verify Test Suite**:
   ```powershell
   .venv\Scripts\pytest tests/ -v
   ```
2. **Verify Dashboard Server**:
   ```powershell
   .venv\Scripts\python.exe dashboard\app.py
   ```
   Check `http://localhost:5001/api/market-pulse` and `http://localhost:5001/api/api-limits` to confirm all responses contain valid JSON without static mock fallbacks.
3. **Verify Guides**:
   - Inspect `OPERATIONAL_GUIDE.md` for complete 6-phase coverage.
   - Open `operational_guide.html` in a web browser and invoke Print Preview (`Ctrl+P`) to verify printable formatting.
4. **Verify Telegram Broadcaster**:
   ```powershell
   .venv\Scripts\python.exe -c "from modules.alerts import send_raw_alert; print(send_raw_alert('Test <b>bold</b> & <tag> check', review_with_grok=False))"
   ```
