# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
scanner.py — Fetch NSE/BSE stock universe, manage holidays, gate market-open checks.
"""

import sqlite3
import logging
import datetime
import requests
import pandas as pd

logger = logging.getLogger(__name__)

# ── Fallback Small & Midcap symbol list (high-momentum, explosive beta) ───────
SMALL_MIDCAP_FALLBACK = [
    "SUZLON", "PERSISTENT", "BSOFT", "DIXON", "ANGELONE", "CDSL", "BSE", "KPITTECH",
    "TATAELXSI", "MAZDOCK", "RVNL", "IRFC", "HUDCO", "SJVN", "FACT", "NATIONALUM",
    "NMDC", "EXIDEIND", "AMBER", "KAYNES", "PRESTIGE", "SOBHA", "GODREJPROP",
    "OBEROIRLTY", "DEEPAKNTR", "JUBLFOOD", "TORNTPHARM", "AUROPHARMA", "LUPIN", "GLENMARK",
    "COFORGE", "LTTS", "CYIENT", "SONACOMS", "TIMKEN", "VOLTAS", "BLUESTARCO", "ASTRAL",
    "SUPREMEIND", "CGPOWER", "KEC", "APARINDS", "COCHINSHIP", "RAILTEL", "UNIONBANK",
    "IDFCFIRSTB", "KARURVYSYA", "FEDERALBNK", "MANAPPURAM", "MUTHOOTFIN", "POONAWALLA",
    "DELTACORP", "TATACOMM", "POLYCAB", "KEI", "CESC", "JYOTHYLAB", "AARTIIND",
    "TATACHEM", "HFCL", "NBCC", "RITES", "IRCON", "NCC", "ELECON", "TEJASNET",
    "NETWEB", "TRIDENT", "ALOKINDS", "LEMONTREE", "CHALET", "DEVYANI", "SAPPHIRE",
    "CUMMINSIND", "ESCORTS", "FORTIS", "GLAXO", "INDUSTOWER", "LICHSGFIN",
    "MCDOWELL-N", "MFSL", "MPHASIS", "MRF", "PAGEIND", "PEL", "PETRONET", "PFC",
    "PIIND", "PVRINOX", "RAMCOCEM", "RECLTD", "SAIL", "SBICARD", "STARHEALTH", "SUNTV",
    "TORNTPOWER", "UBL", "WHIRLPOOL", "ZEEL", "NYKAA", "PAYTM", "ALKEM", "ABBOTINDIA",
    "ACC", "CENTURYTEX", "CROMPTON", "DEEPAKFERT", "GNFC", "GRANULES", "GRAPHITE",
    "HEG", "HINDCOPPER", "IBREALEST", "INDIACEM", "INDIAMART", "INTELLECT", "IPCALAB",
    "JBCHEPHARM", "JINDALSAW", "KIMS", "L&TFH", "LAURUSLABS", "METROPOLIS", "NATCOPHARM",
    "RADICO", "RAYMOND", "ROUTE", "SCHAEFFLER", "SONATSOFTW", "SUNDRMFAST",
    "SYNGENE", "TATAINVEST", "TANLA", "THERMAX", "TRITURBINE", "UCOBANK", "VIPIND", "WELCORP"
]

NIFTY500_FALLBACK = SMALL_MIDCAP_FALLBACK  # Default to Small & Midcap universe


def is_small_or_midcap(symbol: str) -> bool:
    """Return True if symbol is a Small or Midcap stock (not in large-cap exclusion list)."""
    try:
        from config import LARGECAP_EXCLUDE_LIST
        clean_sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
        return clean_sym not in LARGECAP_EXCLUDE_LIST
    except Exception:
        return True


# Known NSE holidays (YYYY-MM-DD) — updated list for 2024-2025
NSE_HOLIDAYS_STATIC = {
    "2024-01-22", "2024-03-25", "2024-03-29", "2024-04-11", "2024-04-14",
    "2024-04-17", "2024-04-21", "2024-05-23", "2024-06-17", "2024-07-17",
    "2024-08-15", "2024-10-02", "2024-10-14", "2024-10-24", "2024-11-01",
    "2024-11-15", "2024-12-25",
    "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-10", "2025-04-14",
    "2025-04-18", "2025-05-01", "2025-06-07", "2025-07-06", "2025-08-15",
    "2025-08-27", "2025-10-02", "2025-10-02", "2025-10-23", "2025-11-05",
    "2025-12-25",
}

_holiday_cache: set = set()
_universe_cache: list = []


# ─────────────────────────────────────────────────────────────────────────────
# Holiday helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_nse_holidays_dynamic() -> set:
    """Try to fetch NSE holidays via NSEPython or NSE API."""
    holidays = set()
    try:
        from nsepython import nse_holidays
        data = nse_holidays()
        if isinstance(data, dict):
            for category in data.values():
                for item in category:
                    dt = item.get("tradingDate", "")
                    if dt:
                        try:
                            parsed = datetime.datetime.strptime(dt, "%d-%b-%Y")
                            holidays.add(parsed.strftime("%Y-%m-%d"))
                        except ValueError:
                            pass
        logger.info(f"Fetched {len(holidays)} NSE holidays dynamically")
    except Exception as e:
        logger.warning(f"Dynamic holiday fetch failed, using static list: {e}")
    return holidays


def _load_holidays():
    global _holiday_cache
    if _holiday_cache:
        return
    dynamic = _fetch_nse_holidays_dynamic()
    # Always include the static list; merge dynamic entries if available
    _holiday_cache = NSE_HOLIDAYS_STATIC.copy()
    if dynamic:
        _holiday_cache.update(dynamic)


def is_market_holiday(date: datetime.date = None) -> bool:
    """Return True if given date (or today) is an NSE holiday."""
    _load_holidays()
    if date is None:
        date = datetime.date.today()
    return date.strftime("%Y-%m-%d") in _holiday_cache


def is_weekend(date: datetime.date = None) -> bool:
    if date is None:
        date = datetime.date.today()
    return date.weekday() >= 5  # Saturday=5, Sunday=6


def is_market_open() -> bool:
    """Return True only if current time is within NSE trading hours."""
    now = datetime.datetime.now()
    if is_weekend() or is_market_holiday(now.date()):
        return False
    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


# ─────────────────────────────────────────────────────────────────────────────
# NSE universe fetch
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_nse_via_nsepython() -> list:
    """Fetch all NSE equity symbols using nsepython."""
    from nsepython import nse_eq_symbols
    symbols = nse_eq_symbols()
    result = []
    for s in symbols:
        s = s.strip().upper()
        if s:
            result.append({"symbol": s, "exchange": "NSE", "sector": ""})
    logger.info(f"nsepython returned {len(result)} NSE symbols")
    return result


def _fetch_nse_via_api() -> list:
    """Fallback: fetch NSE equity list via NSE website CSV."""
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    from io import StringIO
    df = pd.read_csv(StringIO(r.text))
    # Column name varies; normalize
    sym_col = [c for c in df.columns if "symbol" in c.lower() or "SYMBOL" in c]
    if not sym_col:
        return []
    df = df.rename(columns={sym_col[0]: "symbol"})
    result = []
    for _, row in df.iterrows():
        s = str(row["symbol"]).strip().upper()
        if s:
            result.append({"symbol": s, "exchange": "NSE", "sector": ""})
    logger.info(f"NSE CSV API returned {len(result)} symbols")
    return result


def _fetch_bse() -> list:
    """Try BSE equity list. Optional and fail-soft."""
    try:
        url = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?segment=Equity&status=Active"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.bseindia.com/",
        }
        r = requests.get(url, headers=headers, timeout=15)
        content_type = r.headers.get("content-type", "")
        if r.status_code != 200 or "json" not in content_type.lower():
            logger.debug(
                "BSE universe skipped: HTTP %s content-type=%s",
                r.status_code,
                content_type or "unknown",
            )
            return []
        data = r.json()
        result = []
        for item in data.get("Table", []):
            s = str(item.get("scrip_cd", "")).strip()
            if s:
                result.append({"symbol": s, "exchange": "BSE", "sector": ""})
        logger.info(f"BSE returned {len(result)} symbols")
        return result
    except Exception as e:
        logger.debug("BSE universe skipped: %s", e)
        return []


def _fallback_universe() -> list:
    """Use hardcoded Small & Midcap list when all scraping fails."""
    logger.warning("All NSE scraping failed — using Small & Midcap fallback list")
    return [{"symbol": s, "exchange": "NSE", "sector": ""} for s in SMALL_MIDCAP_FALLBACK]


def _upsert_to_db(stocks: list):
    """Upsert stock_universe table with fresh symbol list."""
    from config import DB_PATH
    today = datetime.date.today().isoformat()
    # Mark everything inactive first, then reactivate confirmed ones
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE stock_universe SET is_active = 0")
        for s in stocks:
            conn.execute(
                """INSERT INTO stock_universe (symbol, exchange, sector, is_active, last_verified)
                   VALUES (?, ?, ?, 1, ?)
                   ON CONFLICT(symbol) DO UPDATE SET
                       exchange=excluded.exchange,
                       is_active=1,
                       last_verified=excluded.last_verified""",
                (s["symbol"], s["exchange"], s.get("sector", ""), today)
            )
        conn.commit()
    logger.info(f"Upserted {len(stocks)} symbols to stock_universe")


def get_universe(force_refresh: bool = False) -> list:
    """
    Return list of active stock symbols.
    Filters to Small & Midcap only if UNIVERSE_MODE == 'small_midcap'.
    Tries: nsepython → NSE CSV API → fallback list.
    Caches result in module-level variable for the session.
    """
    global _universe_cache
    if _universe_cache and not force_refresh:
        return _universe_cache

    stocks = []

    # Try nsepython first
    try:
        stocks = _fetch_nse_via_nsepython()
    except Exception as e:
        logger.warning(f"nsepython failed: {e}")

    # Try NSE CSV API
    if not stocks:
        try:
            stocks = _fetch_nse_via_api()
        except Exception as e:
            logger.warning(f"NSE CSV API failed: {e}")

    # Try BSE (additive, non-critical)
    try:
        from config import BSE_UNIVERSE_ENABLED
    except Exception:
        BSE_UNIVERSE_ENABLED = False
    bse_stocks = _fetch_bse() if BSE_UNIVERSE_ENABLED else []
    # Combine — deduplicate by symbol
    all_symbols = {s["symbol"]: s for s in stocks}
    for b in bse_stocks:
        if b["symbol"] not in all_symbols:
            all_symbols[b["symbol"]] = b
    stocks = list(all_symbols.values())

    if not stocks:
        stocks = _fallback_universe()

    # Apply Small & Midcap filter (exclude large caps / mega-caps)
    try:
        from config import UNIVERSE_MODE, LARGECAP_EXCLUDE_LIST
        if UNIVERSE_MODE == "small_midcap":
            before_cnt = len(stocks)
            stocks = [s for s in stocks if s["symbol"].upper() not in LARGECAP_EXCLUDE_LIST]
            logger.info("Small & Midcap universe filter: %s -> %s stocks (excluded %s large caps)",
                        before_cnt, len(stocks), before_cnt - len(stocks))
    except Exception as exc:
        logger.warning("Small/Midcap filter failed: %s", exc)

    _upsert_to_db(stocks)
    _universe_cache = [s["symbol"] for s in stocks]
    logger.info(f"Universe ready: {len(_universe_cache)} symbols")
    return _universe_cache


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    universe = get_universe()
    print(f"Total symbols: {len(universe)}")
    print(f"Sample: {universe[:10]}")
    print(f"Market open: {is_market_open()}")
    print(f"Today holiday: {is_market_holiday()}")
