"""
Morning Analysis Module - News, Health Check, and Pattern Research.

Morning routine:
- 08:00: Health check + system status
- 08:30: News analysis + sector trends  
- 08:55: Final picks synthesis
"""

import logging
import datetime
import json
import os
import yfinance as yf

logger = logging.getLogger(__name__)


def get_system_health(fast: bool = False) -> dict:
    """
    Check system health - database, logs, connectivity.
    """
    import os
    import sqlite3

    health = {
        "status": "healthy",
        "issues": [],
        "checks": {}
    }

    # Check database
    try:
        from config import DB_PATH

        db_path = DB_PATH
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            tables = {
                row[0]
                for row in cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

            required = {"stock_universe", "picks", "patterns", "daily_accuracy"}
            missing = sorted(required - tables)
            if missing:
                health["checks"]["database"] = f"Missing tables: {', '.join(missing)}"
                health["issues"].append(f"DB missing tables: {', '.join(missing)}")
            else:
                cursor.execute("SELECT COUNT(*) FROM stock_universe WHERE is_active = 1")
                active_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM stock_universe WHERE is_active = 0")
                inactive_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM picks WHERE date = ?", (datetime.date.today().isoformat(),))
                today_picks = cursor.fetchone()[0]
                health["checks"]["database"] = (
                    f"OK ({active_count} active, {inactive_count} inactive, {today_picks} picks today)"
                )
            conn.close()
        else:
            health["checks"]["database"] = "Not found"
            health["issues"].append("Database not found")
    except Exception as e:
        health["checks"]["database"] = f"Error: {e}"
        health["issues"].append(f"DB error: {e}")

    # Check logs
    try:
        log_path = "logs/bot.log"
        if os.path.exists(log_path):
            size = os.path.getsize(log_path)
            health["checks"]["logs"] = f"OK ({size/1024:.1f} KB)"
        else:
            health["checks"]["logs"] = "Not found"
    except Exception as e:
        health["checks"]["logs"] = f"Error: {e}"

    # Check last run
    try:
        import time
        log_path = "logs/bot.log"
        if os.path.exists(log_path):
            mtime = os.path.getmtime(log_path)
            age = datetime.datetime.now() - datetime.datetime.fromtimestamp(mtime)
            health["checks"]["last_run"] = f"{age.days}d {age.seconds//3600}h ago"
    except Exception as e:
        health["checks"]["last_run"] = "Unknown"

    if fast:
        health["checks"]["yfinance"] = "Skipped in fast dashboard mode"
        health["checks"]["nsepython"] = "Skipped in fast dashboard mode"
        if health["issues"]:
            health["status"] = "warning"
        return health

    # Check market data sources used for stock cross-checks.
    try:
        yf_hist = yf.Ticker("RELIANCE.NS").history(period="5d", interval="1d")
        health["checks"]["yfinance"] = "OK" if yf_hist is not None and not yf_hist.empty else "No recent data"
        if yf_hist is None or yf_hist.empty:
            health["issues"].append("YFinance returned no RELIANCE data")
    except Exception as e:
        health["checks"]["yfinance"] = f"Error: {e}"
        health["issues"].append(f"YFinance error: {e}")

    try:
        from nsepython import nse_eq
        nse_data = nse_eq("RELIANCE")
        price_info = nse_data.get("priceInfo", {}) if isinstance(nse_data, dict) else {}
        price = price_info.get("lastPrice") or price_info.get("close")
        health["checks"]["nsepython"] = "OK" if price else "No quote returned"
    except ImportError:
        health["checks"]["nsepython"] = "Not installed (optional)"
    except Exception as e:
        health["checks"]["nsepython"] = f"Warning: {str(e)[:60]}"

    if health["issues"]:
        health["status"] = "warning"

    return health


def get_market_news() -> dict:
    """
    Get relevant market news from various sources.
    """
    news_data = {
        "headlines": [],
        "sectors_in_news": set(),
        "stock_specific": {}
    }

    trending_sectors = [
        "IT", "Finance", "Auto", "Pharma", "Cement",
        "Metals", "FMCG", "Infra", "Power"
    ]

    sector_keywords = {
        "IT": ["IT", "software", "tech", " Infosys", " TCS", " Wipro"],
        "Finance": ["bank", "finance", "NBFC", "HDFC", "ICICI"],
        "Auto": ["auto", "car", "vehicle", "Hero", "Maruti", "Bajaj"],
        "Pharma": ["pharma", "drug", "Sun Pharma", "Dr Reddy"],
        "Cement": ["cement", "Ultratech", "Ambuja"],
        "Metals": ["steel", "metal", "Tata Steel", "JSW"],
        "FMCG": ["FMCG", "consumer", "HUL", "Nestle"],
        "Infra": ["infrastructure", "L&T", "Adani"],
        "Power": ["power", "electricity", "NTPC", "Tata Power"]
    }

    all_news = []
    try:
        from modules.news_provider import fetch_market_news

        payload = fetch_market_news(limit=20)
        for item in payload.get("items", []):
            text = ((item.get("title") or "") + " " + (item.get("desc") or "")).lower()
            matched_sector = ""
            for sector, kws in sector_keywords.items():
                if any(kw.lower() in text for kw in kws):
                    matched_sector = sector
                    break
            all_news.append({
                "sector": matched_sector,
                "headline": item.get("title", ""),
                "source": item.get("source") or item.get("provider") or payload.get("provider"),
            })
    except Exception as exc:
        logger.debug("Market news provider failed: %s", exc)

    if not all_news:
        for i in range(len(trending_sectors)):
            all_news.append({
                "sector": trending_sectors[i],
                "headline": f"Sector update: {trending_sectors[i]} sector showing momentum",
                "source": "pattern_analyzer"
            })

    for n in all_news:
        news_data["headlines"].append(n)
        if n["sector"]:
            news_data["sectors_in_news"].add(n["sector"])

    return news_data


def analyze_sector_trends(fast: bool = False) -> dict:
    """
    Analyze current sector trends.
    """
    sectors = {
        "IT": ["INFY", "TCS", "WIPRO", "HCLTECH"],
        "Finance": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK"],
        "Auto": ["BAJAJ-AUTO", "HEROMOTOCO", "M&M", "TATAMOTORS"],
        "Pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB"],
        "Cement": ["ULTRACEMCO", "AMBUJACEM", "SHREECEM"],
        "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL"],
        "FMCG": ["HINDUNILVR", "ITC", "DABUR", "BRITANNIA"],
    }

    if fast:
        try:
            with open("data/grok_dashboard_state.json", "r", encoding="utf-8") as fp:
                state = json.load(fp)
            trends = {}
            for row in state.get("trending_sectors", [])[:7]:
                name = row.get("sector") or row.get("name")
                if name:
                    trends[name] = {
                        "avg_change": float(row.get("avg_change") or row.get("score") or 0),
                        "count": int(row.get("count") or 0),
                    }
            if trends:
                return trends
        except Exception:
            pass

    sector_analysis = {}

    for sector_name, stock_list in sectors.items():
        try:
            from modules.fetch import fetch_ohlcv
            changes = []
            for sym in stock_list[:3]:
                try:
                    df = fetch_ohlcv(sym, period="5d")
                    if not df.empty and len(df) >= 2:
                        closes = df['close'].dropna().values
                        change = ((closes[-1] - closes[-2]) / closes[-2]) * 100
                        changes.append(change)
                except Exception:
                    continue
            if changes:
                sector_analysis[sector_name] = {
                    "avg_change": round(float(sum(changes) / len(changes)), 2),
                    "count": len(changes)
                }
        except Exception as e:
            logger.debug(f"Sector {sector_name} error: {e}")

    return sector_analysis


def generate_morning_report(fast: bool = False) -> dict:
    """
    Generate complete morning analysis report.
    """
    logger.info("Generating morning report...")

    report = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "system_health": get_system_health(fast=fast),
        "news": get_market_news(),
        "sector_trends": analyze_sector_trends(fast=fast),
    }

    logger.info("Morning report generated")
    return report


def generate_morning_report_cached(max_age_seconds: int = 600) -> dict:
    """Fast dashboard-safe report with a short JSON cache."""
    path = "data/morning_report_cache.json"
    try:
        if os.path.exists(path):
            age = datetime.datetime.now().timestamp() - os.path.getmtime(path)
            if age <= max_age_seconds:
                with open(path, "r", encoding="utf-8") as fp:
                    return json.load(fp)
    except Exception:
        pass

    report = generate_morning_report(fast=True)
    try:
        os.makedirs("data", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(report, fp, indent=2, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.debug("Could not write morning report cache: %s", exc)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report = generate_morning_report()
    print(f"System Health: {report['system_health']['status']}")
    print(f"Sectors in News: {report['news']['sectors_in_news']}")
    print(f"Sector Trends: {report['sector_trends']}")
