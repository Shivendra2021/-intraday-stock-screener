# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
winner_finder.py — Find 7%+ Intraday Return Stocks

At market close (15:30+):
1. Load full NSE universe
2. Fetch today's OHLC
3. Calculate intraday return: ((close - open) / open) * 100
4. Filter: return >= 7% (minimum criteria)
5. If no matches → return highest found
6. Store in database for pattern learning
"""

from __future__ import annotations
import datetime
import logging
import sqlite3
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

MIN_RETURN_PCT = 7.0
DB_PATH = "data/history.db"


def _init_db() -> None:
    """Initialize intraday_winners table."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS intraday_winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            open_price REAL,
            close_price REAL,
            high_price REAL,
            low_price REAL,
            return_pct REAL,
            sector TEXT,
            volume_ratio REAL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, symbol)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_winners_date 
        ON intraday_winners(date)
    """)
    conn.commit()
    conn.close()


def _get_universe() -> list[str]:
    """Get full universe for scanning."""
    try:
        from modules.scanner import get_universe
        return get_universe() or []
    except Exception:
        pass
    
    return [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN",
        "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
        "SUNPHARMA", "TITAN", "BAJFINANCE", "ULTRACEMCO", "WIPRO", "NESTLEIND",
        "HCLTECH", "POWERGRID", "NTPC", "TECHM", "JSWSTEEL", "TATASTEEL", "ONGC",
        "TATAMOTORS", "BAJAJFINSV", "ADANIENT", "ADANIPORTS", "COALINDIA", "DIVISLAB",
    ]


def _analyze_stock(symbol: str) -> dict[str, Any] | None:
    """Analyze single stock for intraday return."""
    try:
        from modules.fetch import fetch_ohlcv
        
        # Get today's data (1d period with extended hours)
        df = fetch_ohlcv(symbol, period="5d")
        if df is None or df.empty or len(df) < 1:
            return None
        
        # Get today's data (last row)
        latest = df.iloc[-1]
        
        open_price = float(latest.get("open", 0))
        close_price = float(latest.get("close", 0))
        high_price = float(latest.get("high", 0))
        low_price = float(latest.get("low", 0))
        
        if open_price <= 0 or close_price <= 0:
            return None
        
        intraday_return = ((close_price - open_price) / open_price) * 100
        
        # Volume ratio
        avg_volume = df["volume"].astype(float).mean()
        volume = float(latest.get("volume", 0))
        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        
        return {
            "symbol": symbol,
            "open_price": open_price,
            "close_price": close_price,
            "high_price": high_price,
            "low_price": low_price,
            "return_pct": intraday_return,
            "volume_ratio": vol_ratio,
            "volume": volume,
        }
        
    except Exception as e:
        return None


def find_winners(min_return_pct: float = MIN_RETURN_PCT) -> list[dict[str, Any]]:
    """
    Main function: Find stocks with 7%+ intraday return.
    
    Args:
        min_return_pct: Minimum return percentage (default 7%)
    
    Returns:
        List of winning stocks sorted by return descending
    """
    _init_db()
    
    logger.info(f"=== Finding Intraday Winners (>={min_return_pct}%) ===")
    
    universe = _get_universe()
    logger.info(f"Scanning {len(universe)} stocks...")
    
    winners = []
    all_returns = []
    
    # Batch analyze for efficiency
    from concurrent.futures import ThreadPoolExecutor
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_analyze_stock, universe[:200]))
    
    for result in results:
        if result:
            ret = result["return_pct"]
            all_returns.append({"symbol": result["symbol"], "return_pct": ret})
            
            if ret >= min_return_pct:
                winners.append(result)
    
    # Sort by return
    winners.sort(key=lambda x: x["return_pct"], reverse=True)
    
    # Log stats
    logger.info(f"Found {len(winners)} stocks with >={min_return_pct}% return")
    
    if all_returns:
        all_returns.sort(key=lambda x: x["return_pct"], reverse=True)
        max_return = all_returns[0].get("return_pct", 0) if all_returns else 0
        avg_return = sum(r["return_pct"] for r in all_returns) / len(all_returns)
        logger.info(f"Max intraday return: {max_return:.2f}%, Avg: {avg_return:.2f}%")
    
    # Store winners in DB
    if winners:
        _store_winners(winners)
    
    return winners


def _store_winners(winners: list[dict]) -> None:
    """Store winners in database."""
    conn = sqlite3.connect(DB_PATH)
    today = datetime.date.today().isoformat()
    
    for w in winners:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO intraday_winners 
                (date, symbol, open_price, close_price, high_price, low_price, 
                 return_pct, volume_ratio, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                today,
                w["symbol"],
                w.get("open_price"),
                w.get("close_price"),
                w.get("high_price"),
                w.get("low_price"),
                w.get("return_pct"),
                w.get("volume_ratio"),
                f"Auto-detected >={MIN_RETURN_PCT}% return",
            ))
        except Exception as e:
            logger.debug(f"Failed to store {w.get('symbol')}: {e}")
    
    conn.commit()
    conn.close()
    logger.info(f"Stored {len(winners)} winners in database")


def get_recent_winners(days: int = 30) -> list[dict[str, Any]]:
    """Get recent winners from database."""
    _init_db()
    
    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    
    df = pd.read_sql("""
        SELECT * FROM intraday_winners 
        WHERE date >= ?
        ORDER BY return_pct DESC
    """, conn, params=(cutoff.isoformat(),))
    
    conn.close()
    
    return df.to_dict("records") if not df.empty else []


def get_winner_patterns(days: int = 30) -> dict[str, Any]:
    """
    Find common patterns among recent winners.
    
    Returns metrics for pattern learning.
    """
    recent = get_recent_winners(days)
    
    if not recent:
        return {}
    
    # Calculate common metrics
    import numpy as np
    
    returns = [w.get("return_pct", 0) for w in recent]
    volumes = [w.get("volume_ratio", 1) for w in recent]
    
    return {
        "count": len(recent),
        "avg_return_pct": np.mean(returns),
        "max_return_pct": np.max(returns),
        "min_return_pct": np.min(returns),
        "avg_volume_ratio": np.mean(volumes),
        "top_symbols": [w.get("symbol") for w in recent[:10]],
        "all_symbols": [w.get("symbol") for w in recent],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    winners = find_winners(7.0)
    print(f"\nFound {len(winners)} winners:")
    for w in winners[:10]:
        print(f"  {w['symbol']}: {w['return_pct']:.2f}%")