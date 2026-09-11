# Milestone 3 Survey Report: Dashboard Telemetry, Telegram Alert Broadcaster & Operations

**Date**: 2026-09-09  
**Investigator**: Explorer Subagent 3  
**Focus**: Dashboard Telemetry, Telegram Alert Broadcaster, Operational Readiness (6 Market Phases), Documentation & Milestone 3 Roadmap

---

## Executive Summary

A comprehensive diagnostic audit and operational readiness survey was conducted on the Intraday Stock Screener codebase. The system possesses a sophisticated dual-session architecture, APScheduler-driven execution pipeline, Waitress-backed WSGI web server on port 5001, dual AI brain integration (xAI Grok + OpenAI GPT / Groq DeepSeek), and a multi-channel Telegram alert broadcaster.

However, several critical gaps and areas requiring resolution were discovered:
1. **Static Mock Data & Fabricated Metrics**: Multiple endpoints (`/api/market-pulse`, `/api/sectors`, `/api/api-limits`) and backend modules (`modules/market_pulse.py`, `modules/picker.py`, `dashboard/templates/index.html`) contain hardcoded mock stock prices, fabricated win rates (81.3% with 13 TP / 3 SL fallback), hardcoded sector inflows/outflows, and stale 2024 geopolitical news items.
2. **Telegram HTML Escaping Vulnerability**: The Telegram broadcaster uses `parse_mode: "HTML"` without sanitizing dynamic stock catalyst/news strings (`<`, `>`, `&`), creating a risk of HTTP 400 "Can't parse entities" message drops.
3. **Missing Operational Guides**: There is currently **no** Markdown operational guide and **no** printable HTML guide in the repository (only an abbreviated 49-line README.md and a legacy binary DOCX/PDF in a gitignored directory).
4. **Execution Pipeline Alignment**: The cron scheduling in `main.py` is robust and aligns closely with the required 6 market phases, but requires clear operational documentation, health checklists, and failover runbooks for tomorrow's full trading day.

---

## 1. Dashboard Telemetry & Web Frontend Audit

### 1.1 Architecture & Server Configuration
- **Server Entrypoint**: `dashboard/app.py`
- **WSGI Runner**: Waitress (`waitress.serve(app, host="0.0.0.0", port=5001, threads=32, connection_limit=200, _quiet=True)`).
- **Process Guard**: Protected with single-instance mutex `acquire_single_instance("marketmind-dashboard")`.
- **Database Connection**: SQLite `data/history.db` with WAL mode and lazy schema migrations (`_ensure_dashboard_db()`).
- **Cache Control**: No-cache response headers configured via `@app.after_request`.

### 1.2 Endpoint Inventory & Functionality
| Endpoint | Method | Data Source | Notes & Status |
|---|---|---|---|
| `/` | GET | `dashboard/templates/index.html` | Dark glassmorphism single-page application. |
| `/api/health` | GET | `data/history.db` & `grok_brain.py` | Returns universe count, win rate, market status, and AI brain connectivity. |
| `/api/picks` | GET | `picks` table (SQLite) | Returns today's active/official picks with prices, upside %, and technical reasons. |
| `/api/results` | GET | `daily_accuracy` & `picks` | Today's trade accuracy and performance outcomes. |
| `/api/history` | GET | `picks` table (SQLite) | 500 most recent picks, overall TP/SL count, and historical win rate. |
| `/api/past-session` | GET | `picks` table | Latest available trading session picks. |
| `/api/paper` | GET | `modules.paper_portfolio` | Real-time simulated paper trading positions and PnL. |
| `/api/accuracy` | GET | `daily_accuracy` & `patterns` | 90-day accuracy progression and pattern library counts. |
| `/api/command-strip`| GET | Config & system state | Top banner showing API statuses, bot running mode, and next scan time. |
| `/api/lifecycle` | GET | `picks` + `paper_positions` | Complete lifecycle progression per stock pick. |
| `/api/data-health` | GET | System logs & tables | Comprehensive health scoring (universe, morning picks, price validation, logs). |
| `/api/sync-status` | GET | Process & state JSONs | Cross-checks DB, Telegram audit log, Grok state, and running processes. |
| `/api/market-pulse` | GET | `modules/market_pulse.py` | Real-time index benchmarks, categorized top movers, trending sectors, macro news. |
| `/api/picks-history-json` | GET | `data/daily_picks_history.json` | Top 3 daily picks history in JSON format. |
| `/api/api-limits` | GET | `grok_brain_state.json` & config | Daily API quotas, used calls, and remaining limits. |
| `/api/system/status`| GET | `modules/bot_process.py` | Background bot process state and PID tracking. |
| `/api/system/toggle`| GET/POST | `modules/bot_process.py` | Interactive start/stop toggle for the background bot engine. |

### 1.3 Static Mock Data & Fabricated Metrics (Critical Findings)
The acceptance criteria in `ORIGINAL_REQUEST.md` explicitly mandates:
> *"No static or fabricated stock prices/percentages remain in the active market pulse endpoints."*

The survey identified the following violations:
1. **`modules/market_pulse.py` (Lines 132-143, 159-163)**:
   - Contains hardcoded fallback prices for NIFTY 50 (`23,635.10`), BANK NIFTY (`56,777.55`), and SENSEX (`75,577.60`).
2. **`modules/market_pulse.py` (Lines 305-324)**:
   - Hardcoded fallback top movers list: `TIMKEN (+2.40%)`, `TATASTEEL (+2.50%)`, `CGPOWER (+1.78%)`, `NATIONALUM (+1.77%)`, `COFORGE (-5.38%)`, `INFY (-4.34%)`, `GODREJPROP (-2.60%)`, `PERSISTENT (-2.54%)`.
3. **`modules/market_pulse.py` (Lines 330-461 — `get_trending_sectors()`)**:
   - **Entirely fabricated/hardcoded**: Returns static mock strings for "Nifty Metal & Mining" (+2.15%), "Nifty Capital Goods" (+1.85%), "Nifty Energy" (+1.40%), "Nifty IT" (-3.85%), "Nifty Realty" (-2.65%) with static driver texts and institutional flow blurbs.
4. **`modules/market_pulse.py` (Lines 498-579 — `get_geopolitical_market_news()`)**:
   - Contains 5 hardcoded static news items dating back several months (e.g. Red Sea tanker war, NATO munitions, China property stimulus) that are appended whenever fewer than 4 live news items are fetched.
5. **`modules/picker.py` (Lines 128-149 — `get_system_accuracy_stats()`)**:
   - When no closed picks exist in the database, it fabricates `win_rate = 81.3%`, `avg_return = 5.4%`, and falls back to `13 TP Hit / 3 SL Hit` (16 total).
6. **`dashboard/templates/index.html` (Lines 1534, 1541, 2051-2076, 2110)**:
   - Frontend templates hardcode default fallbacks `81.2% Win Rate`, `13 TP / 3 SL Historic Wins`, `Avg Profit: +5.05%`, `TP: 13 | SL: 3`, and static API numbers `Grok 79/200`, `Groq 14/14.4k`, `News 12/50`.
7. **`dashboard/app.py` (Lines 1135-1165 — `api_api_limits()`)**:
   - Hardcodes default numbers: `grok_used = 79`, `groq_used = 14`, `news_used = 12`, `telegram_used = 8`, `nse_quotes_used = 240`.

---

## 2. Telegram Alert Broadcaster Audit

### 2.1 Configuration & Architecture
- **Implementation**: Raw HTTP requests via `requests.post` to `https://api.telegram.org/bot{TOKEN}/sendMessage`.
- **Credentials**: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` loaded from environment / `config.py`.
- **DRY_RUN Handling**: Respects `DRY_RUN=True` by logging the full alert payload and writing an audit record without sending out network calls.
- **AI Alert Review**: Alerts pass through `modules.grok_brain.review_telegram_alert(text)` where Grok appends concise AI sentiment/risk notes when enabled.
- **Length Constraint**: Enforces `MAX_TELEGRAM_CHARS = 3900` (well within Telegram's 4096 character ceiling).

### 2.2 Error Handling, Rate Limiting & Auditing
- **Retry Mechanism**: Exponential backoff on status `429` (Too Many Requests) or `503` (Service Unavailable) with wait times `1s, 2s, 4s` across 3 attempts.
- **Audit Logging**: Every send attempt is recorded in `data/telegram_delivery.jsonl` with timestamp, date, `event_type`, `ok` boolean, and sanitized details.
- **Credential Security**: `_safe_error_text()` redacts the Telegram token before writing to logs or audit trails.

### 2.3 Message Types & Triggers
1. `send_morning_final_picks`: Broadcasts the official top-3 picks at 08:55 / 09:10 with complete technical data (Entry, SL, Target, Score, Risk classification, RSI, ADX, Volume Ratio, EMA alignment, Patterns, and setup rationale).
2. `send_tp_hit` / `send_sl_hit`: Triggered by `stock_tracker.py` during market hours when a stock crosses target or stop loss.
3. `send_intraday_alert`: Fired when a mid/smallcap stock surges >3% with volume spike.
4. `send_preclose` / `send_preclose_alert`: Triggered at 15:00 for momentum plays before market close.
5. `send_end_of_day_report` / `send_eod_detailed_report`: Broadcast at 15:35 with top 10 gainers and losers.
6. `send_summary`: End-of-day summary of daily accuracy and average returns.
7. `send_heartbeat`: Scheduled at 18:00 to confirm bot vitality.
8. `send_no_picks`: Diagnostic alert if no stocks pass filters.

### 2.4 Critical Telegram Bug / Vulnerability Identified
- **HTML Entity Unescaping Risk**: All alert payloads specify `"parse_mode": "HTML"`. However, dynamic text inserted into the messages (e.g. `reasons`, `symbol`, `driver`, `headline`) is **not** escaped with `html.escape()`.
- If an automated catalyst description or news snippet contains `<` or `>` or unescaped `&`, Telegram will reject the payload with `HTTP 400: Bad Request: can't parse entities in message text`.
- **Remediation**: Wrap all dynamic string insertions with `html.escape()` or sanitize them before formatting HTML tags.

---

## 3. Operational Readiness & 6 Market Phases Survey

The trading day lifecycle is managed by `APScheduler` in `main.py`, supported by `modules/automation_supervisor.py` for background catch-up.

### 3.1 Chronological Phase-by-Phase Mapping

| Market Phase | Exact Time Window | Scheduled Bot Actions & Modules | Telegram Alerts | Telemetry & Dashboard State |
|---|---|---|---|---|
| **Phase 1: Pre-Market Setup** | **08:30 – 09:15** | • **07:45**: Health check (`job_health_check`).<br>• **07:50–08:20**: Universe scan (`run_morning_session`) filters out 80+ large-caps, scans 2,400+ small/midcaps.<br>• **08:20–08:45**: Deep research & sector momentum scoring.<br>• **08:35**: Price validation warmup.<br>• **08:45–08:55**: Dual-brain debate (Grok + GPT/Groq) locks top 3 picks.<br>• **08:55**: Official picks locked in DB (`picks` table).<br>• **08:55–09:10**: `job_morning_delivery_guard` ensures delivery before market open. | • Morning Health Check<br>• **Official Final Top-3 Picks** with complete technicals & ATR targets | Dashboard displays `WAITING` -> `SCANNING` -> `RESEARCH` -> `DEBATE` -> `READY` state. Top 3 cards populate. |
| **Phase 2: Morning ORB** | **09:15 – 10:15** | • **09:15**: Market opens.<br>• **09:15–10:15**: Opening Range Breakout (ORB) detection (`INTRADAY_PERIOD_MORNING`).<br>• Every 5 min: `job_tracking_update` checks tick prices against Entry/SL/TP.<br>• Dynamic trailing stop updates via RL Agent (`rl_intraday_manager.py`). | • `TARGET HIT` (if TP reached)<br>• `STOP LOSS HIT` (if SL breached)<br>• **10:00**: Hourly pick status update | Live price ticks update via NSE gateway/Yahoo. PnL meters reflect real-time movement. |
| **Phase 3: Midday VWAP** | **10:15 – 12:30** | • Period config: `INTRADAY_PERIOD_MIDDAY` (VWAP pullbacks & consolidation flags).<br>• 5-min tracking loop active.<br>• Breakeven lock triggered when profit exceeds +1.5% (`RL_BREAKEVEN_TRIGGER_PCT`).<br>• Stop tightened when profit exceeds +2.8%.<br>• Background heavy jobs coordinated by `heavy_job_coordinator` (one heavy job at a time). | • **11:00**: Hourly status<br>• **12:00**: Hourly status<br>• Real-time TP/SL notifications | Command strip shows active pick count vs closed count. Paper portfolio updates equity curves. |
| **Phase 4: Afternoon Surge** | **12:30 – 14:15** | • Period config: `INTRADAY_PERIOD_AFTERNOON` (afternoon volume acceleration & day-high breakouts).<br>• 5-min tracking loop active.<br>• 14:30: `AUTO_LATE_RECOVERY_END` shuts off late intraday recovery scans. | • **13:00**: Hourly status<br>• **14:00**: Hourly status<br>• Real-time TP/SL notifications | Top movers categorized view refreshes every 5 mins. Sparklines track midday momentum. |
| **Phase 5: Square-Off** | **14:15 – 15:30** | • **15:00**: `job_preclose` runs `run_preclose_scan()` for 4–7% volume surge momentum.<br>• **15:15–15:30**: MIS intraday square-off window.<br>• **15:30**: Market Close.<br>• **15:31**: `job_tracking_eod` executes `close_and_report_eod()`, marking all remaining open positions as `open_eod` or `eod_closed` with final PnL. | • **15:00**: Pre-Close Movers Alert<br>• **15:31**: Pick tracking EOD close notifications | All active cards transition to `EOD Closed` or `Target Hit`. Final intraday returns locked. |
| **Phase 6: Post-Market EOD** | **15:30 – 16:00** | • **15:35**: `job_find_winners` discovers the day's top +7% explosive small/midcap winners.<br>• **15:40**: `job_eod_outcome_brain` reconciles daily outcomes and updates SQLite `daily_accuracy`.<br>• **15:50**: `job_after_market_learning` extracts winning features and pattern boosts.<br>• **16:00**: `job_pattern_learning` registers new discovered patterns.<br>• **16:15**: Automated data backup to `data/backups/`.<br>• **18:00**: System heartbeat. | • **15:35**: Market Wrap / Top 10 Performers Report<br>• **15:40**: AI EOD Outcome Reconciliation<br>• **18:00**: Heartbeat | Accuracy chart records day's win rate. Discovered patterns count increments. API quota bars finalize. |

---

## 4. Documentation & Operational Guides Survey

### 4.1 Current Repository Documentation
- **`README.md`**: 49 lines. Contains basic install instructions, `.env` skeleton, and common command lines. Missing phase details, failover protocols, and emergency procedures.
- **`output/doc/Stock_Analyser_V2_Complete_System_Blueprint.docx` & `.pdf`**: Binary documentation files in a gitignored output directory. These cannot be viewed or rendered directly in web browsers and are not part of source control.
- **Existing Markdown Operational Guides**: **NONE**.
- **Existing Printable HTML Operational Guides**: **NONE**.

### 4.2 Documentation Requirements for Milestone 3
To satisfy Acceptance Criteria R3, the project requires two new operational deliverables:
1. `OPERATIONAL_GUIDE.md`:
   - Complete chronological runbook detailing all 6 market phases from 08:30 AM to 16:00 PM.
   - Operator pre-flight checklist (environment variables, internet connectivity, API quotas, database validation).
   - Startup commands (`run_system.ps1`, `run_dashboard.bat`, Windows Task Scheduler setup).
   - Failure recovery protocols (missed morning picks catch-up, Telegram delivery failure, API rate-limit exhaustion, orphaned process recovery).
   - Real-time monitoring & troubleshooting matrix.
2. `operational_guide.html`:
   - Beautiful, standalone, zero-dependency HTML document matching the Markdown guide.
   - Modern typography, high-contrast dark theme for screen viewing, and `@media print` CSS stylesheet.
   - Print-friendly layout (page-break controls, clean margins, crisp black-and-white print styles) enabling instant one-click Save as PDF / Print.

---

## 5. Concrete Action Plan for Milestone 3

### Action Item 1: Create Master Operational Guide (`OPERATIONAL_GUIDE.md`)
- Author comprehensive, highly detailed operations runbook.
- Include precise execution timeline covering all 6 market phases.
- Detail operator commands, Windows PowerShell scripts, and monitoring URLs.
- Include failover playbooks for missed morning scans, rate limits, and network disconnects.

### Action Item 2: Create Printable HTML Operational Guide (`operational_guide.html`)
- Build a polished, responsive HTML document.
- Include dedicated `@media print` styling: clean headers, forced page breaks before major phases, print-optimized font sizes and contrast.
- Ensure 100% fidelity to `OPERATIONAL_GUIDE.md`.

### Action Item 3: Eliminate Static Mock Data & Fabricated Metrics
- **Dynamic Sectors**: Replace hardcoded `get_trending_sectors()` in `modules/market_pulse.py` with dynamic calculation aggregating price changes and volume ratios across the small/midcap universe. When market is closed or pre-market, display genuine "Pre-Market Awaiting Open" state rather than fabricated numbers.
- **Dynamic News**: Remove the 5 hardcoded static news items in `get_geopolitical_market_news()`. Display exclusively live RSS / NewsAPI headlines, or a clean fallback message if news APIs are offline.
- **Purge Fabricated Accuracy**: Update `modules/picker.py` `get_system_accuracy_stats()` so that when zero closed picks exist, it displays `0.0% Win Rate (0 TP / 0 SL)` instead of injecting `81.3% / 13 TP / 3 SL`.
- **Align Dashboard UI**: Update `dashboard/templates/index.html` and `dashboard/app.py` `/api/api-limits` to display actual dynamically computed metrics rather than static numbers.

### Action Item 4: Secure Telegram Broadcaster
- Apply `html.escape()` to all dynamic strings inserted into Telegram HTML messages in `modules/alerts.py` to eliminate HTTP 400 entity parse errors.

### Action Item 5: Comprehensive Verification Pass
- Run full pytest test suite to ensure zero regressions.
- Verify dashboard launches on `http://localhost:5001` and serves telemetry endpoints cleanly.
- Verify Telegram pipeline dry-run delivery and audit log output.
