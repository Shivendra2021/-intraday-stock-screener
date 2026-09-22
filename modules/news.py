# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
news.py — Fetch Google News RSS per symbol, parse with newspaper4k, return sentiment score.
"""

import logging
import re
import time
import feedparser
import requests

logger = logging.getLogger(__name__)

# Session-level cache: symbol -> (score, timestamp)
_sentiment_cache: dict = {}
_CACHE_TTL_SECONDS = 1800  # 30 minutes

# Simple positive / negative word lists for lightweight sentiment scoring
_POSITIVE_WORDS = {
    "surge", "gain", "rally", "profit", "growth", "record", "high", "beat",
    "positive", "upgrade", "buy", "outperform", "strong", "rise", "rose",
    "jumped", "soar", "boom", "bullish", "breakout", "revenue", "earnings",
    "winner", "benefit", "opportunity", "expand", "increase", "improve",
    "recovery", "up", "above", "exceed", "guidance", "dividend", "awarded",
    "launch", "partnership", "deal", "contract", "win", "acquisition",
}

_NEGATIVE_WORDS = {
    "fall", "drop", "loss", "decline", "crash", "plunge", "sell", "downgrade",
    "weak", "below", "miss", "concern", "risk", "fraud", "probe", "bearish",
    "cut", "layoff", "debt", "default", "warning", "negative", "penalty",
    "fine", "lawsuit", "regulatory", "recall", "halt", "suspend", "dip",
    "underperform", "reduce", "lower", "disappointing", "restructure",
}


def _score_text(text: str) -> float:
    """Score text from -1.0 to +1.0 using word frequency."""
    if not text:
        return 0.0
    words = re.findall(r"\b[a-z]+\b", text.lower())
    if not words:
        return 0.0
    pos = sum(1 for w in words if w in _POSITIVE_WORDS)
    neg = sum(1 for w in words if w in _NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 4)


def _fetch_rss_headlines(symbol: str) -> list:
    """Fetch Google News RSS headlines for the symbol."""
    query = f"{symbol}+NSE+stock+India"
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        feed = feedparser.parse(url)
        titles = [entry.get("title", "") for entry in feed.entries[:15]]
        return titles
    except Exception as e:
        logger.debug(f"RSS fetch failed for {symbol}: {e}")
        return []


def _fetch_article_text(url: str) -> str:
    """Use newspaper4k to parse article body text. Falls back to requests+beautifulsoup4."""
    try:
        import newspaper
        article = newspaper.Article(url)
        article.download()
        article.parse()
        return article.text[:2000]  # limit to 2000 chars
    except Exception:
        # Fallback: use requests + beautifulsoup4
        try:
            import requests
            from bs4 import BeautifulSoup
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                soup = BeautifulSoup(r.content, "html.parser")
                # Extract paragraph text
                paragraphs = soup.find_all("p")
                text = " ".join([p.get_text() for p in paragraphs])
                return text[:2000]
        except Exception:
            pass
        return ""


def _fetch_nse_announcements(symbol: str) -> str:
    """Check NSE announcements page for the symbol."""
    try:
        url = f"https://www.nseindia.com/api/corp-announcements?index=equities&symbol={symbol}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        }
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            texts = []
            for item in data[:5]:
                texts.append(item.get("desc", "") + " " + item.get("subject", ""))
            return " ".join(texts)
    except Exception as e:
        logger.debug(f"NSE announcements fetch failed for {symbol}: {e}")
    return ""


def get_sentiment(symbol: str) -> float:
    """
    Return sentiment score for symbol: float from -1.0 (very negative) to +1.0 (very positive).
    Combines Google News RSS titles + NSE announcements.
    Results are cached for 30 minutes per session.
    """
    now = time.time()
    if symbol in _sentiment_cache:
        score, ts = _sentiment_cache[symbol]
        if now - ts < _CACHE_TTL_SECONDS:
            return score

    all_text = ""

    # Google News RSS headlines
    headlines = _fetch_rss_headlines(symbol)
    all_text += " ".join(headlines)

    # NSE announcements
    announcements = _fetch_nse_announcements(symbol)
    all_text += " " + announcements

    score = _score_text(all_text)
    _sentiment_cache[symbol] = (score, now)
    logger.debug(f"Sentiment {symbol}: {score:.3f} (from {len(headlines)} headlines)")
    return score


def get_stock_sentiment(symbol: str) -> float:
    """Backward-compatible alias for per-stock sentiment."""
    return get_sentiment(symbol)


def get_market_sentiment() -> float:
    """
    Return overall market sentiment by averaging Nifty/market keywords from RSS.
    Returns float -1.0 to +1.0.
    """
    queries = ["Nifty50+India+market", "Sensex+today", "Indian+stock+market+today"]
    texts = []
    for q in queries:
        url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                texts.append(entry.get("title", ""))
        except Exception:
            continue
    combined = " ".join(texts)
    score = _score_text(combined)
    logger.info(f"Overall market sentiment: {score:.3f}")
    return score


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print(get_sentiment("RELIANCE"))
    print(get_sentiment("TCS"))
    print(f"Market sentiment: {get_market_sentiment()}")
