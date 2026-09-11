# Handoff Report — Active Trading Intelligence Engines & Data Flow Survey

**Author**: `teamwork_preview_explorer_survey_2` (Explorer Subagent)  
**Target**: Orchestrator / Implementer  
**Type**: Hard Handoff (Investigation Complete)  
**Date**: 2026-09-09  

---

## 1. Observation

1. **Database Universe Verification**:
   * Command executed:
     ```bash
     python -c "import sqlite3, config; conn = sqlite3.connect('data/history.db'); c = conn.cursor(); total = c.execute('SELECT count(*) FROM stock_universe').fetchone()[0]; active = c.execute('SELECT count(*) FROM stock_universe WHERE is_active=1').fetchone()[0]; large = [s for s in config.LARGECAP_EXCLUDE_LIST if c.execute('SELECT count(*) FROM stock_universe WHERE symbol=?', (s,)).fetchone()[0] > 0]; active_large = [s for s in config.LARGECAP_EXCLUDE_LIST if c.execute('SELECT count(*) FROM stock_universe WHERE symbol=? AND is_active=1', (s,)).fetchone()[0] > 0]; print('total:', total, 'active:', active, 'large_in_db:', len(large), 'active_large:', len(active_large), 'len(LARGECAP_EXCLUDE_LIST):', len(config.LARGECAP_EXCLUDE_LIST))"
     ```
   * Result:
     `total: 2615 active: 2489 large_in_db: 86 active_large: 0 len(LARGECAP_EXCLUDE_LIST): 86`
   * Breakdown of 126 inactive rows (`is_active = 0`): 86 are the exact items in `config.py:LARGECAP_EXCLUDE_LIST`; 40 are delisted/inactive/rights entitlement symbols (`EDUCOMP`, `SKIL`, `AVG-RE`, `ESSEN-RE3`, `MCDOWELL-N`, `PEL`, etc.).

2. **Large-Cap Leaks in Fallback Code**:
   * `modules/universe_scanner.py:159-165`:
     ```python
     def get_full_universe() -> list[str]:
         # ...
         return _EXTENDED_UNIVERSE
     _EXTENDED_UNIVERSE = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", ...]
     ```
     `_EXTENDED_UNIVERSE` contains large caps and is not filtered by `LARGECAP_EXCLUDE_LIST`.
   * `modules/stock_selector.py:22-34`:
     ```python
     SECTOR_UNIVERSE = {
         "IT": ["TCS", "INFY", "WIPRO", ...],
         "Finance": ["HDFCBANK", "ICICIBANK", "SBIN", ...],
         "Energy": ["RELIANCE", ...]
     }
     ```
     Hardcodes Nifty 50 mega-caps.

3. **Static and Fabricated Data in Market Pulse Engine**:
   * `modules/market_pulse.py:159-163`:
     ```python
     indices = [
         {"key": "nifty", "symbol": "^NSEI", "name": "NIFTY 50", "price": 23635.10, "change_pct": -0.61, ...},
         {"key": "banknifty", "symbol": "^NSEBANK", "name": "BANK NIFTY", "price": 56777.55, "change_pct": -0.54, ...},
         {"key": "sensex", "symbol": "^BSESN", "name": "SENSEX", "price": 75577.60, "change_pct": -0.73, ...},
     ]
     ```
   * `modules/market_pulse.py:179-183`:
     ```python
     basket = {
         "large_cap": ["TATASTEEL", "JSWSTEEL", "HAL", "LT", "ITC", "INFY", "HDFCBANK", "TCS", "ICICIBANK", "SBIN"],
         "mid_cap": ["TIMKEN", "CGPOWER", "TRENT", "AUROPHARMA", "FEDERALBNK", "POLYCAB", "PERSISTENT", "GODREJPROP", "COFORGE", "VOLTAS"],
         "small_cap": ["NATIONALUM", "NMDC", "KAYNES", "SJVN", "BSOFT", "TEJASNET", "NBCC", "CDSL", "IRFC", "SUZLON"]
     }
     ```
     Only tracks 30 fixed stocks; does not query the 2,489 universe.
   * `modules/market_pulse.py:304-325`:
     Fabricated fallback returns hardcoded percentage changes: `TIMKEN (+2.40%)`, `TATASTEEL (+2.50%)`, `CGPOWER (+1.78%)`, `COFORGE (-5.38%)`, `INFY (-4.34%)`, `GODREJPROP (-2.60%)`.
   * `modules/market_pulse.py:330-462`:
     `get_trending_sectors()` returns a 100% hardcoded python dictionary of buying and losing sectors (`inflow_pct: 2.15`, `outflow_pct: -3.85`).
   * `dashboard/app.py:1099-1110`:
     Exposes `get_full_market_pulse()` directly over HTTP endpoint `/api/market-pulse`.

4. **3-Period Intraday Return & ATR Stop Calculation**:
   * `modules/grok_brain.py:368-414`:
     - Morning ORB (`09:15-10:15`): `round(min(8.0, max(5.2, 5.0 + (vol - 1.2)*1.0 + max(0.0, gap)*0.4)), 1)` -> [5.2% to 8.0%]
     - Midday VWAP (`10:15-12:30`): `round(min(7.0, max(5.0, 4.8 + (rsi - 50)*0.12)), 1)` -> [5.0% to 7.0%]
     - Afternoon Push (`12:30-14:15`): `round(min(7.5, max(5.0, 5.0 + (adx / 25.0))), 1)` -> [5.0% to 7.5%]
   * `modules/picker.py:38-40`:
     ```python
     sl_atr  = price - (atr * SL_ATR_MULTIPLIER)
     sl_pct  = price * (1 - MAX_SL_PCT / 100)
     sl_price = max(sl_atr, sl_pct)  # tighter of two
     ```
     With `SL_ATR_MULTIPLIER = 1.5`, `MAX_SL_PCT = 2.0%`, `MIN_RISK_REWARD = 2.0`.
   * `modules/stock_selector.py:293`:
     Hardcodes `target_pct = 6.5` instead of referencing `evaluate_stock_intraday_period()`.

5. **30-Minute News Cache & Bug in Consumer**:
   * Cache provider: `modules/news_provider.py:79-121` (`data/news_cache.json`, `CACHE_TTL_SECONDS = 1800`).
   * Consumer in `modules/market_pulse.py:472-475`:
     ```python
     from modules.news_provider import fetch_market_news
     n_data = fetch_market_news(limit=6)
     if n_data and n_data.get("news"):
         for item in n_data["news"][:4]:
     ```
     `fetch_market_news()` returns `{"items": [...]}`, but line 474 queries `n_data.get("news")`. As a result, `live_news` is always `[]`, and only hardcoded curated news is returned.

---

## 2. Logic Chain

1. From Observation 1, the SQLite database `stock_universe` contains 2,615 rows, of which exactly 2,489 are active (`is_active = 1`). All 86 large caps in `config.py:LARGECAP_EXCLUDE_LIST` have `is_active = 0`. This proves the 2,489 universe restriction is correctly initialized in SQLite.
2. From Observation 2, fallback mechanisms in `modules/universe_scanner.py` and sector catalogs in `modules/stock_selector.py` bypass this filter by declaring `_EXTENDED_UNIVERSE` and `SECTOR_UNIVERSE` with Nifty 50 tickers (`RELIANCE`, `TCS`, `INFY`). If the main scanner fails or `select_top_stocks` runs, large caps could re-enter candidate pools.
3. From Observation 3, the acceptance criterion requiring *"No static or fabricated stock prices/percentages remain in the active market pulse endpoints"* is currently **violated** by `modules/market_pulse.py`:
   - `get_trending_sectors()` is 100% hardcoded.
   - `get_top_movers_and_reasons()` restricts itself to 30 stocks and falls back to fabricated percentage changes.
   - Fallback index prices are hardcoded.
4. From Observation 4, `evaluate_stock_intraday_period()` in `modules/grok_brain.py` dynamically computes returns between 5.0% and 8.0% based on volatility, gap, RSI, and ADX across three specific market periods. In `modules/picker.py`, `sl_price = max(sl_atr, sl_pct)` selects the higher stop price (closer to entry), correctly bounding maximum loss to 2.0% while tightening to `1.5 * ATR` if lower. Risk-to-reward is mathematically guaranteed to be $\ge 2.5:1$ ($\ge MIN\_RISK\_REWARD$).
5. From Observation 5, the news cache in `modules/news_provider.py` adheres to a 30-minute TTL with atomic file replacement. However, because `modules/market_pulse.py` accesses `n_data.get("news")` instead of `n_data.get("items")`, live/cached news is silently dropped.

---

## 3. Caveats

1. **Exchange Trading Hours**: Investigation was conducted after market hours; dynamic live responses from NSE APIs were verified via codebase tracing, logs, and database inspections rather than open-market WebSocket streams.
2. **Multi-Process Concurrency**: Process pool scaling in `modules/universe_scanner.py` with 16 workers depends on host CPU availability; fallback paths must be hardened against large-cap leakage.
3. **External Rate Limits**: yfinance rate limits frequently trigger the fallback paths in `modules/market_pulse.py`, making the removal of fabricated fallbacks urgent for live operation.

---

## 4. Conclusion

The universe restriction to 2,489 Small & Midcap symbols and the mathematical foundation of 3-period intraday targeting (+5% to +8% with <=2% ATR stops) are structurally sound and verified. However, **Milestone 2 implementation must remediate three critical deficiencies**:
1. Remove all static/fabricated data in `modules/market_pulse.py` (`get_trending_sectors()`, top movers fallback, index fallbacks) and replace them with live/cached computations.
2. Fix the key mismatch bug in `modules/market_pulse.py:474` (`n_data.get("items")`) so the 30-minute news cache flows into the pulse feed.
3. Add exclusionary filters to fallback symbol arrays (`_EXTENDED_UNIVERSE` and `SECTOR_UNIVERSE`) to eliminate any risk of large-cap leakage.

---

## 5. Verification Method

1. **Database Universe & Large-Cap Exclusion Test**:
   ```bash
   python -c "import sqlite3, config; conn = sqlite3.connect('data/history.db'); c = conn.cursor(); active = c.execute('SELECT count(*) FROM stock_universe WHERE is_active=1').fetchone()[0]; leaks = [s for s in config.LARGECAP_EXCLUDE_LIST if c.execute('SELECT count(*) FROM stock_universe WHERE symbol=? AND is_active=1', (s,)).fetchone()[0] > 0]; print(f'Active: {active}, Leaks: {len(leaks)}'); assert active == 2489 and len(leaks) == 0"
   ```
2. **Market Pulse Live Verification**:
   ```bash
   python -c "from modules.market_pulse import get_full_market_pulse; p = get_full_market_pulse(force_refresh=True); print('Keys:', list(p.keys()))"
   ```
3. **News Key Mismatch Bug Verification**:
   ```bash
   python -c "from modules.news_provider import fetch_market_news; d = fetch_market_news(); print('items in d:', 'items' in d, 'news in d:', 'news' in d)"
   ```
4. **Pytest Test Commands**:
   ```bash
   pytest tests/test_market_pulse_and_history.py -v
   pytest tests/test_scanner.py -v
   ```
