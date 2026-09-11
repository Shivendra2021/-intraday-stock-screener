# Active Trading Intelligence Engines & Data Flow Survey Report

**Agent**: `teamwork_preview_explorer_survey_2`  
**Date**: 2026-09-09  
**Repository**: `c:\Users\shubh\OneDrive\Desktop\Intraday Stock Screener`  
**Focus**: Active Trading Intelligence Engines & Data Flow Diagnostic Audit  

---

## Executive Summary

This survey conducted an in-depth audit across the four core active trading intelligence pillars of MarketMind Pro:
1. **Small & Midcap Universe Restriction (2,489 Symbols)**: Confirmed in database. Exactly 2,489 active symbols exist in SQLite `stock_universe` (`is_active = 1`), with 86 large caps explicitly set to `is_active = 0` via `LARGECAP_EXCLUDE_LIST`. However, fallback data in `modules/universe_scanner.py` and `modules/stock_selector.py` contains large caps and lacks exclusionary guards.
2. **Dynamic Live Market Pulse & Top Movers Calculation Engine**: Critical deficiencies identified. `/api/market-pulse` and `modules/market_pulse.py` contain substantial **hardcoded static and fabricated mock data** for index prices (fallback), top movers (fixed 30-stock basket with fabricated fallback percentages like TIMKEN +2.40%, COFORGE -5.38%), 100% hardcoded trending sector flows (`get_trending_sectors()`), and static geopolitical news items.
3. **3-Period Intraday High-Return Targets (+5% to +8% with ATR Stops)**: Implemented in `modules/grok_brain.py` and `modules/picker.py`. Targets dynamically adjust per period (Morning ORB: 5.2%–8.0%, Midday VWAP: 5.0%–7.0%, Afternoon Push: 5.0%–7.5%). The ATR stop logic (`sl_price = max(sl_atr, sl_pct)`) is mathematically sound, bounding maximum risk to <= 2.0% while yielding nominal Risk-to-Reward >= 2.5:1. Minor hardening needed for zero/negative ATR edges and alignment in `modules/stock_selector.py`.
4. **30-Minute News Cache**: Persistent JSON cache is implemented in `modules/news_provider.py` (`data/news_cache.json`) with an 1800-second TTL and atomic file writes. An in-memory 30-minute sentiment cache is in `modules/news.py`. However, a **critical dictionary key mismatch bug** was found in `modules/market_pulse.py` (checks `n_data.get("news")` instead of `n_data.get("items")`), completely blinding the market pulse engine from live news and forcing fallback to static headlines.

---

## 1. Small & Midcap Universe Restriction (2,489 Symbols)

### 1.1 Where Symbols are Stored
* **Primary Database Storage**: SQLite database `data/history.db` under table `stock_universe`:
  * Schema: `symbol TEXT PRIMARY KEY, exchange TEXT, sector TEXT, is_active INTEGER, last_verified TEXT`.
  * Verified DB state:
    * Total rows in `stock_universe`: **2,615**
    * Active symbols (`is_active = 1`): **Exactly 2,489**
    * Inactive symbols (`is_active = 0`): **126**
      * 86 symbols: Exactly matches `LARGECAP_EXCLUDE_LIST` (Nifty 50 and mega-caps).
      * 40 symbols: Delisted, suspended, or Rights Entitlements (`-RE`) symbols pruned by `modules/universe_cleaner.py` (e.g., `EDUCOMP`, `SKIL`, `AVG-RE`, `ESSEN-RE3`, `MCDOWELL-N`, `PEL`).
* **Configuration Definition**: `config.py` (lines 119–142):
  * `UNIVERSE_MODE = os.getenv("UNIVERSE_MODE", "small_midcap").strip().lower()`
  * `INTRADAY_MAX_MARKET_CAP_CR = float(os.getenv("INTRADAY_MAX_MARKET_CAP_CR", "25000"))`
  * `LARGECAP_EXCLUDE_LIST = {"RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", ..., "INDHOTEL", "MOTHERSON"}` (86 mega-caps).
* **Code-level Fallback Lists**:
  * `modules/scanner.py` (lines 19–42): `SMALL_MIDCAP_FALLBACK` (112 high-momentum small/midcap tickers).
  * `modules/universe_scanner.py` (lines 162–610): `_EXTENDED_UNIVERSE` (~500 symbols).

### 1.2 How the Universe is Filtered
1. **Fetch**: `modules/scanner.py:get_universe()` (lines 228–285) attempts `_fetch_nse_via_nsepython()` (`nse_eq_symbols()`), falls back to `_fetch_nse_via_api()` (`https://archives.nseindia.com/content/equities/EQUITY_L.csv`), and then to `SMALL_MIDCAP_FALLBACK`.
2. **Exclusion**:
   ```python
   # modules/scanner.py:270-278
   if UNIVERSE_MODE == "small_midcap":
       before_cnt = len(stocks)
       stocks = [s for s in stocks if s["symbol"].upper() not in LARGECAP_EXCLUDE_LIST]
   ```
3. **Database Sync**: `modules/scanner.py:_upsert_to_db()` (lines 207–225) sets `is_active = 0` for all existing entries and reactivates only the filtered stocks (`is_active = 1`).
4. **Delisting Pruning**: `modules/universe_cleaner.py:prune_delisted_symbols()` (lines 172–250) verifies Yahoo Finance / NSE quotes in batches of 200; symbols with zero volume or missing quotes are marked `is_active = 0`.

### 1.3 Strictness of Large-Cap Exclusion & Identified Leaks
* **Where Large Caps are Strictly Excluded**:
  * `modules/scanner.py`: `is_small_or_midcap(symbol)` (line 44) checks `clean_sym not in LARGECAP_EXCLUDE_LIST`.
  * `modules/analyzer.py` (lines 274–276): Calls `if not is_small_or_midcap(symbol): return None`.
  * `modules/research_engine.py` (lines 363–369): Filters candidates with `is_small_or_midcap(s)`.
  * `modules/grok_brain.py` (line 429): System prompt explicitly instructs Grok: *"Large caps are strictly excluded. We only focus on high-beta Small & Midcaps targeting 5.0% to 8.0% intraday gains."*
* **Where Large Caps Leak (Vulnerabilities)**:
  1. **`modules/universe_scanner.py:_EXTENDED_UNIVERSE` (lines 148–160)**: If `modules.scanner.get_universe()` throws an uncaught exception, `get_full_universe()` returns `_EXTENDED_UNIVERSE`, which begins with `"RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"`. It does not apply `LARGECAP_EXCLUDE_LIST`!
  2. **`modules/stock_selector.py:SECTOR_UNIVERSE` (lines 22–34)**: Sector mapping dictionaries contain large caps (`TCS`, `INFY`, `HDFCBANK`, `RELIANCE`). If `select_top_stocks()` is invoked, it pulls directly from `SECTOR_UNIVERSE` without filtering `is_small_or_midcap()`.
  3. **`modules/market_pulse.py:get_top_movers_and_reasons()` (lines 180–183)**: Explicitly tracks a `"large_cap"` category featuring `["TATASTEEL", "JSWSTEEL", "HAL", "LT", "ITC", "INFY", "HDFCBANK", "TCS", "ICICIBANK", "SBIN"]`.

---

## 2. Dynamic Live Market Pulse & Top Movers Calculation Engine

### 2.1 Live Calculation vs. Static / Fabricated Data
Investigation confirms that while `modules/market_pulse.py` attempts dynamic fetches from Yahoo Finance, it is **heavily laden with static, fabricated mock data** in both normal operation and fallback paths.

#### Issue A: Static Trending Sectors (100% Mock Data)
* **Location**: `modules/market_pulse.py:get_trending_sectors()` (lines 330–462).
* **Observation**: The function does not query any database, API, or live ticker feeds. It returns a hardcoded static dictionary:
  * Buying sectors: `"Nifty Metal & Mining"` (`inflow_pct: 2.15`, `"TATASTEEL (+2.50%), JSWSTEEL (+0.98%)"`), `"Nifty Capital Goods & Industrials"` (`inflow_pct: 1.85`), `"Nifty Energy & Utilities"` (`inflow_pct: 1.40`), `"Nifty Pharma & Healthcare"` (`inflow_pct: 0.45`).
  * Losing sectors: `"Nifty IT & Software Services"` (`outflow_pct: -3.85`, `"COFORGE (-5.38%), INFY (-4.34%)"`), `"Nifty Realty"` (`outflow_pct: -2.65`), `"Nifty Smallcap Telecom"` (`outflow_pct: -2.10`), `"Nifty Banking"` (`outflow_pct: -0.85`).
* **Verdict**: **100% Fabricated Static Data**. Violates Acceptance Criterion: *"No static or fabricated stock prices/percentages remain in the active market pulse endpoints."*

#### Issue B: Narrow Basket & Fabricated Fallback in Top Movers
* **Location**: `modules/market_pulse.py:get_top_movers_and_reasons()` (lines 169–328).
* **Observations**:
  1. **Not Universe-Driven**: Instead of querying top movers from the active 2,489 stock universe in `data/history.db` or scanning current market percentage changes, it downloads a fixed, arbitrary 30-symbol list (`basket = {"large_cap": [...10...], "mid_cap": [...10...], "small_cap": [...10...]}`).
  2. **Fabricated Fallback (lines 304–325)**: When `yfinance` download fails or returns empty data (e.g. rate limits or offline), it returns hardcoded prices and percentage moves:
     * Gainers: `TIMKEN` (₹3173.40, +2.40%), `TATASTEEL` (₹188.75, +2.50%), `CGPOWER` (₹926.95, +1.78%), `NATIONALUM` (₹377.60, +1.77%).
     * Losers: `COFORGE` (₹1845.00, -5.38%), `INFY` (₹1035.00, -4.34%), `GODREJPROP` (₹1857.10, -2.60%), `PERSISTENT` (₹5419.00, -2.54%).
* **Verdict**: **Fails Acceptance Criteria**. Fallback data is completely fabricated.

#### Issue C: Hardcoded Indices Fallback
* **Location**: `modules/market_pulse.py:get_market_indices()` (lines 132–143 & 159–164).
* **Observation**:
  * Default prices on exception: `^NSEI` (23635.10, -0.61%), `^NSEBANK` (56777.55, -0.54%), `^BSESN` (75577.60, -0.73%).
  * Sparklines are fabricated linear arrays `[23720, 23740, 23680, 23650, 23635]`.

#### Issue D: Dashboard Endpoint Exposure
* **Location**: `dashboard/app.py` (lines 1099–1110):
  * `@app.route("/api/market-pulse")` directly calls `get_full_market_pulse(force_refresh=force)`.
  * The frontend UI renders these fabricated numbers directly to the user dashboard.

---

## 3. 3-Period Intraday High-Return Targets (+5% to +8% with ATR Stops)

### 3.1 Architecture & Computation Points
The 3-period intraday targeting logic is implemented across two key modules:
* **Period Classification & Target Calculation**: `modules/grok_brain.py:evaluate_stock_intraday_period(stock)` (lines 368–414).
* **Level Generation & Risk/Reward Validation**: `modules/picker.py:_calculate_levels(stock)` (lines 20–69).

### 3.2 Period Breakdown & Target Mathematical Formulae
| Period Code | Prime Time Window | Strategy Name | Formula / Dynamic Target Return | Range Bounds |
|---|---|---|---|---|
| `MORNING_ORB` | 09:15 – 10:15 AM | Opening Range Breakout (ORB) on 2x+ Vol Surge | `round(min(8.0, max(5.2, 5.0 + (vol - 1.2)*1.0 + max(0.0, gap)*0.4)), 1)` | **+5.2% to +8.0%** |
| `MIDDAY_VWAP` | 10:15 – 12:30 PM | VWAP / EMA 9 Pullback hold, buy institutional absorption | `round(min(7.0, max(5.0, 4.8 + (rsi - 50)*0.12)), 1)` | **+5.0% to +7.0%** |
| `AFTERNOON_PUSH` | 12:30 – 02:15 PM | High-of-Day Breakout on secondary volume surge | `round(min(7.5, max(5.0, 5.0 + (adx / 25.0))), 1)` | **+5.0% to +7.5%** |

### 3.3 Mathematical Soundness of ATR Stops and Targets
* **Stop Loss Formula (`modules/picker.py:38–40`)**:
  ```python
  sl_atr   = price - (atr * SL_ATR_MULTIPLIER)  # SL_ATR_MULTIPLIER = 1.5
  sl_pct   = price * (1 - MAX_SL_PCT / 100)      # MAX_SL_PCT = 2.0%
  sl_price = max(sl_atr, sl_pct)                  # Higher price = tighter stop
  ```
* **Soundness Evaluation**:
  1. **Tighter Stop Selection**: Because `sl_price` is below entry price, `max(sl_atr, sl_pct)` selects the value closest to current price. If `1.5 * ATR` implies a 3.5% drop, `max()` caps the maximum loss at exactly 2.0% (`MAX_SL_PCT`). If `1.5 * ATR` implies a 1.2% drop, `max()` tightens the stop to 1.2%. This is mathematically sound and controls drawdown.
  2. **Risk-to-Reward Consistency**:
     * Maximum Risk: $\le 2.0\%$
     * Minimum Target: $\ge 5.0\%$
     * Minimum nominal R:R: $\frac{5.0\%}{2.0\%} = 2.5:1$
     * Because `MIN_RISK_REWARD = 2.0`, valid picks consistently satisfy the risk/reward threshold.
  3. **Potential Edge Cases**:
     * If `atr` is 0 or NaN, `sl_atr` equals `price`, resulting in `risk = 0`, which is handled gracefully by `if risk <= 0: return None`.
     * In `modules/stock_selector.py` (lines 291–300), `target_pct = 6.5` is statically set rather than using `evaluate_stock_intraday_period()`. If `stock_selector.py` is called independently, it will diverge from `picker.py`.

---

## 4. 30-Minute News Cache

### 4.1 Implementation Architecture
Two separate news caching mechanisms exist:
1. **Market News Disk Cache (`modules/news_provider.py`)**:
   * Storage: `data/news_cache.json` (lines 79–121).
   * TTL: `CACHE_TTL_SECONDS = 1800` (30 minutes).
   * Fetch order: `TheNewsAPI` $\rightarrow$ Google News & Economic Times RSS feeds $\rightarrow$ Disk cache.
   * Atomic file writing via temporary file replacement (`news_cache.json.tmp` $\rightarrow$ `news_cache.json`).
   * Bypass: `fetch_market_news(force_refresh=True)`.
2. **Per-Symbol Sentiment Memory Cache (`modules/news.py`)**:
   * Storage: `_sentiment_cache: dict[str, tuple[float, float]]` (symbol $\rightarrow$ `(score, timestamp)`).
   * TTL: `_CACHE_TTL_SECONDS = 1800` (30 minutes).
   * In-memory only; not persisted to disk.

### 4.2 Critical Bug Identified in `modules/market_pulse.py`
* **Defect**: In `modules/market_pulse.py` (line 474):
  ```python
  # modules/market_pulse.py:472-475
  from modules.news_provider import fetch_market_news
  n_data = fetch_market_news(limit=6)
  if n_data and n_data.get("news"):          # <--- BUG: key is "items", not "news"
      for item in n_data["news"][:4]:
  ```
  `fetch_market_news()` in `modules/news_provider.py` returns `{"items": [...], "count": ...}`.
* **Impact**: `n_data.get("news")` evaluates to `None` 100% of the time. The loop never runs, `live_news` remains empty (`[]`), and `modules/market_pulse.py` only ever outputs the 5 static hardcoded curated headlines.

---

## 5. File Paths, Line References & Milestone 2 Remediation Plan

### 5.1 File Paths & Line Reference Index
| Subsystem | File Path | Line Range | Role / Issue |
|---|---|---|---|
| Universe & Large-Cap Exclusion | `config.py` | 118–142 | `LARGECAP_EXCLUDE_LIST` (86 mega-caps) & universe configs |
| Universe Database & Pruning | `modules/scanner.py` | 44–52, 207–285 | `is_small_or_midcap()`, `get_universe()`, `stock_universe` DB upsert |
| Delisting & Staleness Pruning | `modules/universe_cleaner.py` | 78–125, 172–250 | Validates Yahoo/NSE active trading; sets `is_active = 0` |
| Fallback Universe Leak | `modules/universe_scanner.py` | 148–160 | `get_full_universe()` fallback contains unfiltered large caps |
| Sector Universe Leak | `modules/stock_selector.py` | 22–34 | `SECTOR_UNIVERSE` has hardcoded large caps |
| Market Pulse Engine | `modules/market_pulse.py` | 77–167 | `get_market_indices()` has static fallback index values |
| Market Pulse Movers | `modules/market_pulse.py` | 169–328 | `get_top_movers_and_reasons()` has static 30-stock basket & fake fallback prices |
| Market Pulse Sectors | `modules/market_pulse.py` | 330–462 | `get_trending_sectors()` is 100% hardcoded mock data |
| Market Pulse News Consumer | `modules/market_pulse.py` | 472–475 | Dictionary key mismatch (`n_data.get("news")` vs `"items"`) |
| Dashboard API Routes | `dashboard/app.py` | 1099–1110 | `/api/market-pulse` exposing fabricated data to UI |
| 3-Period Intraday Timing | `modules/grok_brain.py` | 368–414 | `evaluate_stock_intraday_period()` 3-period formula (+5% to +8%) |
| Intraday ATR Stop & Target Levels | `modules/picker.py` | 20–69 | `_calculate_levels()` ATR stop loss & risk-reward gating |
| 30-Minute News Cache | `modules/news_provider.py` | 79–160 | `data/news_cache.json` disk cache with 1800s TTL |
| Per-Stock Sentiment Cache | `modules/news.py` | 18–21, 124–143 | `_sentiment_cache` 30-minute in-memory sentiment cache |

---

### 5.2 Concrete Remediation Steps for Milestone 2

#### Remediation 1: Eliminate Static/Fabricated Data from Market Pulse Engine
1. **Dynamic Top Movers**:
   * Refactor `modules/market_pulse.py:get_top_movers_and_reasons()` to fetch top gainers and losers dynamically from the active `stock_universe` (or intraday snapshot table/memory cache in `modules/intraday_pattern_agent.py`), rather than a static 30-stock basket.
   * Eliminate all hardcoded mock stock prices (`TIMKEN`, `TATASTEEL`, `COFORGE`, etc.) in the fallback branch. On fetch failure, return genuinely empty lists (`"gainers": [], "losers": []`) or query recent prices from `data/history.db` (`picks` or `price_validations` table).
2. **Dynamic Trending Sectors**:
   * Rewrite `modules/market_pulse.py:get_trending_sectors()` to compute dynamic sector performance by aggregating price changes from `modules/intraday_pattern_agent.py:intraday_sector_heatmap` table or `modules/research_engine.py:_get_price_sector_scores()`.
   * Completely remove the static dictionary in `modules/market_pulse.py` lines 336–459.
3. **Indices Fallback**:
   * Replace static numbers (23635.10, 56777.55) in `get_market_indices()` with the most recent valid close price retrieved from `data/history.db` or return explicit `None`/stale indicators.

#### Remediation 2: Fix News Cache Key Mismatch in `modules/market_pulse.py`
* Change line 474 of `modules/market_pulse.py`:
  ```python
  # Before:
  if n_data and n_data.get("news"):
      for item in n_data["news"][:4]:
  # After:
  news_items = (n_data.get("items") or n_data.get("news") or []) if n_data else []
  if news_items:
      for item in news_items[:4]:
  ```
  This immediately connects the 30-minute news cache in `modules/news_provider.py` to the market pulse endpoint.

#### Remediation 3: Plug Large-Cap Exclusion Leaks
1. **`modules/universe_scanner.py`**:
   * In `get_full_universe()` (lines 148–160), wrap `_EXTENDED_UNIVERSE` with an exclusionary filter:
     ```python
     from config import LARGECAP_EXCLUDE_LIST
     return [s for s in _EXTENDED_UNIVERSE if s.upper() not in LARGECAP_EXCLUDE_LIST]
     ```
2. **`modules/stock_selector.py`**:
   * Filter `candidates` against `is_small_or_midcap(s)` in `select_top_stocks()`:
     ```python
     from modules.scanner import is_small_or_midcap
     candidates = [s for s in candidates if is_small_or_midcap(s)]
     ```
   * Update `select_top_stocks()` line 293 to use `evaluate_stock_intraday_period(stock)` instead of hardcoding `target_pct = 6.5`.

#### Remediation 4: Target & ATR Stop Edge Case Hardening
1. In `modules/picker.py:_calculate_levels()`:
   * Explicitly sanitize `atr`:
     ```python
     if atr is None or atr <= 0 or not (price > 0):
         return None
     ```
2. In `modules/grok_brain.py:evaluate_stock_intraday_period()`:
   * Guard against `vol_ratio` or `rsi` being `None` or `NaN` to prevent calculation blowups.

---

### 5.3 Verification Methods for Milestone 2
* **Universe Verification**:
  ```bash
  python -c "import sqlite3, config; conn = sqlite3.connect('data/history.db'); c = conn.cursor(); active = c.execute('SELECT count(*) FROM stock_universe WHERE is_active=1').fetchone()[0]; large_leaks = [s for s in config.LARGECAP_EXCLUDE_LIST if c.execute('SELECT count(*) FROM stock_universe WHERE symbol=? AND is_active=1', (s,)).fetchone()[0] > 0]; print(f'Active: {active}, Large-Cap Leaks: {len(large_leaks)}'); assert active >= 2000 and len(large_leaks) == 0"
  ```
* **No-Fabricated-Data Scan in Endpoints**:
  ```bash
  python -c "from modules.market_pulse import get_full_market_pulse; pulse = get_full_market_pulse(force_refresh=True); print('Indices:', len(pulse.get('indices', []))); print('Movers:', len(pulse.get('movers', {}))); print('Sectors:', len(pulse.get('sectors', {})))"
  ```
* **News Cache Roundtrip Test**:
  ```bash
  python -c "from modules.news_provider import fetch_market_news; n1 = fetch_market_news(); n2 = fetch_market_news(); print('Cached:', n2.get('cached'), 'Items:', len(n2.get('items', []))); assert n2.get('cached') is True"
  ```
* **Pytest Suite**:
  ```bash
  pytest tests/test_market_pulse_and_history.py tests/test_scanner.py -v
  ```
