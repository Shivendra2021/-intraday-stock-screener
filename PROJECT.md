# Project: Intraday Stock Screener System Audit & Operational Readiness

## Architecture
The system is an automated intraday algorithmic stock screening, multi-brain LLM analysis, tracking, and notification platform for the Indian equity markets (NSE).
- **Runtime Core**: `main.py` orchestrates the chronological lifecycle via APScheduler across 6 market phases.
- **Universe Scanner**: `modules/universe_scanner.py` runs a 16-worker multiprocessing pool to scan candidates across the active Small & Midcap universe (2,489 stocks from `data/history.db`), filtering out large caps (`config.LARGECAP_EXCLUDE_LIST`).
- **Intelligence Engines**:
  - `modules/market_pulse.py`: Dynamic live market pulse, index changes, sector momentum, top movers, and geopolitical market news.
  - `modules/grok_brain.py` & `modules/picker.py`: 3-period intraday target calculation (+5% to +8% targeting with 1.5 * ATR stops bounded by 2.0% max loss).
  - `modules/news_provider.py`: 30-minute disk-cached market news (`data/news_cache.json`, 1800s TTL).
- **Delivery & Interface**:
  - `modules/alerts.py`: Multi-channel Telegram alert broadcaster with exponential backoff and delivery auditing.
  - `dashboard/app.py`: Waitress WSGI server on port 5001 exposing live telemetry, trade signals, and market pulse endpoints.

## Code Layout
- `main.py`: Operational orchestrator, cron schedules, pipeline coordinator.
- `config.py`: Global configuration, universe thresholds, exclusions, API keys, schedule times.
- `modules/`:
  - `universe_scanner.py`: Multiprocessing scanner, candidate generation.
  - `market_pulse.py`: Live market indices, sector momentum, movers, news integration.
  - `news_provider.py`: 30-min cached news provider.
  - `picker.py`: Levels computation, ATR stops, target returns, win-rate metrics.
  - `stock_tracker.py`: 5-minute intraday tracking loop, trailing stops, EOD reconciliation.
  - `alerts.py`: Telegram broadcaster and formatting.
  - `grok_brain.py`: LLM market intelligence, 3-period target logic, dual-brain debate.
  - `stock_selector.py`: Candidate ranking and sector fallback universe.
  - `continuous_learning.py`: Reinforcement learning, win rate tracking, pattern recognition.
- `dashboard/`:
  - `app.py`: Flask/Waitress backend on port 5001.
  - `templates/index.html`: Dashboard UI.
- `tests/`: Automated unit and integration test suite.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Fix `_get_nse_symbol` ImportError | Resolve missing import in `modules/universe_scanner.py` to restore 16-worker morning scan | M1 | Survey E1 |
| 2 | Guard root test scripts | Add `__main__` guards or isolate root scripts so `pytest` collection does not hang or execute live network calls | M1 | Survey E1 |
| 3 | Division-by-Zero Hardening | Add zero-checks in `stock_tracker.py`, `universe_scanner.py`, `picker.py`, and `continuous_learning.py` | M1 | Survey E1 |
| 4 | News Cache Consumer Integration | Fix `"items"` vs `"news"` dictionary key mismatch in `modules/market_pulse.py:474` | M1 & M2 | Survey E1, E2 |
| 5 | Purge Static Mock & Fabricated Data | Replace hardcoded prices, indices, movers, sectors, and win-rate fallbacks with dynamic/honest values | M1, M2, M3 | Survey E1, E2, E3 |
| 6 | Small & Midcap Universe Fallback Protection | Filter fallback symbol arrays (`_EXTENDED_UNIVERSE`, `SECTOR_UNIVERSE`) with `LARGECAP_EXCLUDE_LIST` | M2 | Survey E2 |
| 7 | Dynamic Market Pulse & Movers Engine | Ensure index metrics, sector flows, and top movers are dynamically calculated from live/cached market data | M2 | Survey E2 |
| 8 | 3-Period Intraday Target & ATR Stops | Verify +5% to +8% targets and <=2% ATR stops across ORB, VWAP, and Afternoon Surge periods | M2 | Survey E2 |
| 9 | Telegram HTML Entity Escaping | Add `html.escape()` to dynamic strings before Telegram HTML dispatch to prevent HTTP 400 Bad Request errors | M3 | Survey E3 |
| 10 | Complete 6-Phase Operational Runbook | Create `OPERATIONAL_GUIDE.md` covering 08:30 to 16:00 execution phases, commands, checklists, failover | M3 | Survey E3 |
| 11 | Printable HTML Operational Guide | Create `operational_guide.html` with zero external dependencies and `@media print` styling for 1-click PDF export | M3 | Survey E3 |
| 12 | Dashboard Telemetry Verification | Validate Waitress WSGI on port 5001 and ensure all endpoints return genuine dynamic telemetry | M3 | Survey E3 |
| 13 | Comprehensive E2E Testing Suite | Build requirement-driven opaque-box E2E test suite (Tiers 1-4) covering all features and operational phases | E2E Track | Architecture |
| 14 | Adversarial Hardening & Final Pass | 100% E2E test pass + Tier 5 Challenger adversarial testing loop and Forensic Audit | M4 (Final) | Architecture |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Core System Diagnostic & Bug Resolution | Resolve `ImportError`, pytest hanging, division-by-zero, news key mismatch, and core exception handling | none | IN_PROGRESS |
| M2 | Active Trading Intelligence Engines | Small/Midcap fallback isolation, dynamic market pulse/top movers, 3-period target & ATR stops verification | M1 | PLANNED |
| M3 | Operational Readiness & Documentation | Author `OPERATIONAL_GUIDE.md`, `operational_guide.html`, fix Telegram escaping, verify dashboard on port 5001 | M1 | PLANNED |
| E2E | E2E Testing Track | Design & implement opaque-box test suite (Tiers 1-4) per requirement methodology; publish `TEST_READY.md` | M1 (parallel) | PLANNED |
| M4 | Final E2E Pass & Adversarial Hardening | Phase 1: 100% E2E test pass (Tiers 1-4). Phase 2: Tier 5 Challenger adversarial hardening and Forensic Audit | M1, M2, M3, E2E | PLANNED |

## Interface Contracts
### Universe Scanner ↔ Morning Pipeline
- `scan_universe_parallel() -> list[dict]`:
  - Returns list of candidate dicts with keys: `symbol`, `name`, `sector`, `current_price`, `score`, `reason`, `breakout_prob`, `momentum_score`.
  - Excludes all symbols where `symbol in config.LARGECAP_EXCLUDE_LIST`.

### Market Pulse ↔ Dashboard & Alerts
- `get_full_market_pulse(force_refresh: bool) -> dict`:
  - Returns keys: `indices` (list of dicts), `market_status` (str), `sectors` (`buying_sectors`, `losing_sectors`), `top_movers` (`gainers`, `losers`), `news` (list of dicts).
  - No hardcoded index prices or fabricated sector percentages.

### News Provider ↔ Consumer
- `fetch_market_news(limit: int) -> dict`:
  - Returns dict with key `"items"` containing list of news item dicts: `title`, `link`, `published`, `source`, `summary`.
  - Consumers must read `n_data.get("items", [])`.

### Telegram Broadcaster ↔ Caller
- `send_alert(text: str, parse_mode: str = "HTML") -> bool`:
  - Dynamic user-supplied text or market notes must be sanitized with `html.escape()` prior to formatting into HTML tags.
