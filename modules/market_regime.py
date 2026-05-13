"""Market regime snapshot for research scoring."""

from __future__ import annotations

import json
import os
from typing import Any

from modules.time_utils import now_ist, today_ist_str

STATE_FILE = "data/market_regime.json"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _change_from_yfinance(ticker: str) -> float | None:
    try:
        import yfinance as yf

        df = yf.download(ticker, period="5d", interval="1d", auto_adjust=True, progress=False)
        if df is None or df.empty or len(df) < 2:
            return None
        close = df["Close"] if "Close" in df.columns else df["close"]
        last = _safe_float(close.iloc[-1])
        prev = _safe_float(close.iloc[-2])
        if prev <= 0:
            return None
        return round((last - prev) / prev * 100, 3)
    except Exception:
        return None


def classify_regime(force_refresh: bool = False) -> dict[str, Any]:
    """Classify broad market state without blocking the pipeline if data is unavailable."""
    if not force_refresh and os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fp:
                state = json.load(fp)
            if state.get("date") == today_ist_str():
                return state
        except Exception:
            pass

    nifty = _change_from_yfinance("^NSEI")
    smallcap = _change_from_yfinance("^CNXSC")
    midcap = _change_from_yfinance("NIFTY_MIDCAP_100.NS")
    values = [v for v in [nifty, smallcap, midcap] if v is not None]
    avg = round(sum(values) / len(values), 3) if values else 0.0

    if avg <= -1.2:
        regime = "RED_MARKET"
        tracker_bias = "find_relative_strength"
    elif avg <= -0.35:
        regime = "DIP_MARKET"
        tracker_bias = "find_green_close_outliers"
    elif avg >= 1.0:
        regime = "BULL_MARKET"
        tracker_bias = "find_momentum_continuation"
    elif avg >= 0.25:
        regime = "GREEN_MARKET"
        tracker_bias = "find_sector_leaders"
    else:
        regime = "SIDEWAYS_MARKET"
        tracker_bias = "find_stock_specific_strength"

    state = {
        "date": today_ist_str(),
        "updated_at": now_ist().isoformat(timespec="seconds"),
        "regime": regime,
        "tracker_bias": tracker_bias,
        "nifty_change_pct": nifty,
        "smallcap_change_pct": smallcap,
        "midcap_change_pct": midcap,
        "avg_index_change_pct": avg,
    }
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fp:
        json.dump(state, fp, indent=2, ensure_ascii=False)
    return state
