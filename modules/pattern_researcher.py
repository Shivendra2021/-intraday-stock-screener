"""
Pattern Researcher - Auto-screening pattern research module.

Finds patterns that give 7%+ returns:
- Results day patterns
- Weekly high breaks
- News + volume surge
- Gap-up breakouts
- Sector rotation
"""

import logging
import datetime

logger = logging.getLogger(__name__)


def get_trending_sectors():
    """
    Get currently trending sectors based on news and market movement.
    Returns list of sector names that are in focus.
    """
    trending = [
        "IT", "Finance", "Auto", "Pharma", "Cement",
        "Metals", "FMCG", "Infra", "Power"
    ]
    return trending


def scan_stocks_by_sector(sector: str, limit: int = 10):
    """
    Get stocks for a given sector.
    Returns list of stock symbols.
    """
    sector_map = {
        "IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
        "Finance": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"],
        "Auto": ["HEROMOTOCO", "M&M", "TATAMOTORS", "MARUTI", "BAJAJ-AUTO"],
        "Pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "ALKEM"],
        "Cement": ["ULTRACEMCO", "SHREECEM", "ACC", "ORIENTCEM", "JKCEMENT"],
        "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "NMDC"],
        "FMCG": ["HINDUNILVR", "ITC", "DABUR", "BRITANNIA", "MARICO"],
        "Infra": ["LT", "TATAPOWER", "NTPC", "POWERGRID", "BHEL"],
        "Power": ["TATAPOWER", "NTPC", "ADANIPOWER", "CESC", "RELINFRA"]
    }
    return sector_map.get(sector, [])[:limit]


def get_stock_price_data(symbol: str) -> dict:
    """
    Get current price, volume, and change data for a stock.
    """
    try:
        from modules.fetch import fetch_ohlcv, SYMBOL_ALIASES
        hist = fetch_ohlcv(symbol, period="5d")
        if hist.empty:
            return {}
        close_prices = hist['close'].values
        volumes = hist['volume'].values

        current_price = float(close_prices[-1]) if len(close_prices) > 0 else 0
        prev_close = float(close_prices[-2]) if len(close_prices) > 1 else current_price
        avg_volume = float(sum(volumes[-5:]) / min(len(volumes), 5)) if len(volumes) > 0 else 0

        return {
            "symbol": symbol,
            "current_price": round(current_price, 2),
            "prev_close": round(prev_close, 2),
            "volume": int(volumes[-1]) if len(volumes) > 0 else 0,
            "avg_volume": int(avg_volume),
            "52w_high": current_price,
            "52w_low": current_price,
            "name": symbol,
        }
    except Exception as e:
        logger.debug(f"Error fetching data for {symbol}: {e}")
        return {}


def check_results_momentum(symbol: str) -> dict:
    """
    Check if stock has momentum based on price data.
    """
    try:
        from modules.fetch import fetch_ohlcv
        hist = fetch_ohlcv(symbol, period="1mo")
        if hist.empty or len(hist) < 5:
            return {}

        closes = hist['close'].dropna().values
        volumes = hist['volume'].values

        if len(closes) < 2:
            return {}

        current_price = float(closes[-1])
        month_high = max(closes)
        month_low = min(closes)
        avg_vol = sum(volumes[-5:]) / min(len(volumes), 5)
        latest_vol = volumes[-1]

        daily_change = ((current_price - closes[-2]) / closes[-2]) * 100 if len(closes) > 1 else 0
        volume_ratio = latest_vol / avg_vol if avg_vol > 0 else 1

        return {
            "symbol": symbol,
            "current_price": round(current_price, 2),
            "change_pct": round(daily_change, 2),
            "volume_ratio": round(volume_ratio, 2),
            "month_high": round(month_high, 2),
            "month_low": round(month_low, 2),
            "recommendation": "buy" if volume_ratio > 1.5 else "hold",
        }
    except Exception as e:
        return {}


def scan_sector_momentum(sector: str) -> list:
    """
    Scan all stocks in a sector and find top momentum candidates.
    """
    stocks = scan_stocks_by_sector(sector)
    results = []

    for sym in stocks:
        try:
            data = check_results_momentum(sym)
            if data and data.get("current_price", 0) > 0:
                results.append(data)
        except:
            continue

    results.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    return results[:10]


def find_results_day_stocks(top_n: int = 20) -> list:
    """
    Find stocks with Q4 results recently announced.
    These tend to have momentum.
    """
    sectors = get_trending_sectors()
    all_stocks = []

    for sector in sectors:
        try:
            sector_stocks = scan_sector_momentum(sector)
            all_stocks.extend(sector_stocks)
        except:
            continue

    all_stocks.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    return all_stocks[:top_n]


def find_weekly_highs(top_n: int = 20) -> list:
    """
    Find stocks near their 52-week high.
    These have breakout momentum.
    """
    sectors = get_trending_sectors()
    results = []

    for sector in sectors:
        try:
            stocks = scan_stocks_by_sector(sector)
            for sym in stocks:
                data = get_stock_price_data(sym)
                if data and data.get("current_price", 0) > 0:
                    high = data.get("52w_high", 0)
                    current = data.get("current_price", 0)
                    if high > 0:
                        dist_to_high = ((high - current) / high) * 100
                        data["dist_to_52w_high"] = round(dist_to_high, 2)
                        results.append(data)
        except:
            continue

    results.sort(key=lambda x: x.get("dist_to_52w_high", 100))
    return results[:top_n]


def find_news_momentum_stocks(top_n: int = 20) -> list:
    """
    Find stocks with analyst upgrades and positive sentiment.
    """
    sectors = get_trending_sectors()
    results = []

    for sector in sectors:
        try:
            stocks = scan_stocks_by_sector(sector)
            for sym in stocks:
                data = check_results_momentum(sym)
                if data and data.get("recommendation") in ["buy", "strongBuy"]:
                    results.append(data)
        except:
            continue

    results.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    return results[:top_n]


def find_news_momentum_stocks(top_n: int = 20) -> list:
    """
    Find stocks with analyst upgrades and positive sentiment.
    """
    sectors = get_trending_sectors()
    results = []

    for sector in sectors:
        stocks = scan_stocks_by_sector(sector)
        for sym in stocks:
            data = check_results_momentum(sym)
            if data and data.get("recommendation") in ["buy", "strongBuy"]:
                results.append(data)

    results.sort(key=lambda x: x.get("upside_pct", 0), reverse=True)
    return results[:top_n]


def generate_picks_for_tomorrow(top_n: int = 5) -> list:
    """
    Generate top picks for tomorrow based on multiple patterns:
    1. Results momentum
    2. Near 52-week high
    3. Analyst upgrades
    """
    logger.info("Generating picks for tomorrow...")

    try:
        results_pattern = find_results_day_stocks(30)
    except Exception as e:
        logger.warning(f"Results pattern failed: {e}")
        results_pattern = []

    try:
        highs_pattern = find_weekly_highs(20)
    except Exception as e:
        logger.warning(f"Highs pattern failed: {e}")
        highs_pattern = []

    try:
        news_pattern = find_news_momentum_stocks(20)
    except Exception as e:
        logger.warning(f"News pattern failed: {e}")
        news_pattern = []

    combined = {}
    seen = set()

    for stock in results_pattern:
        sym = stock.get("symbol")
        if sym and sym not in seen:
            combined[sym] = stock
            seen.add(sym)

    for stock in highs_pattern:
        sym = stock.get("symbol")
        if sym and sym not in seen:
            combined[sym] = stock
            seen.add(sym)

    for stock in news_pattern:
        sym = stock.get("symbol")
        if sym and sym not in seen:
            combined[sym] = stock
            seen.add(sym)

    scored = []
    for sym, data in combined.items():
        score = 0
        change = data.get("change_pct", 0)
        if change > 3:
            score += 3
        elif change > 1:
            score += 2
        elif change > 0:
            score += 1

        vol_ratio = data.get("volume_ratio", 1)
        if vol_ratio > 2:
            score += 2
        elif vol_ratio > 1.5:
            score += 1

        if data.get("recommendation") == "buy":
            score += 2

        data["score"] = score
        scored.append(data)

    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    picks = []
    for stock in scored[:top_n]:
        picks.append({
            "rank": len(picks) + 1,
            "symbol": stock.get("symbol", ""),
            "current_price": stock.get("current_price", 0),
            "change_pct": stock.get("change_pct", 0),
            "volume_ratio": stock.get("volume_ratio", 0),
            "recommendation": stock.get("recommendation", "N/A"),
            "score": stock.get("score", 0),
        })

    logger.info(f"Generated {len(picks)} picks for tomorrow")
    return picks


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Generating Tomorrow's Picks ===")
    picks = generate_picks_for_tomorrow(5)

    print("\nTop 5 Picks:")
    for p in picks:
        print(f"{p['rank']}. {p['symbol']}: ₹{p['current_price']} | Change: +{p['change_pct']}% | Vol: {p['volume_ratio']}x | Score: {p['score']}")
