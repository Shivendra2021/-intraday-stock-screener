"""Bloomberg-style scoring helpers for intraday research candidates."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _ollama_symbols() -> set[str]:
    state = _load_json(os.path.join("data", "ollama_intraday_agent_state.json"))
    study = state.get("study") or {}
    scan = state.get("scan") or {}
    symbols = {str(sym).upper() for sym in study.get("top_symbols", []) if sym}
    symbols.update(str(row.get("symbol", "")).upper() for row in scan.get("winners", [])[:20])
    return symbols


def _daily_learning() -> dict[str, Any]:
    return _load_json(os.path.join("data", "daily_winner_learning.json"))


def _daily_learning_symbols() -> set[str]:
    data = _daily_learning()
    return {str(sym).upper() for sym in data.get("top_symbols", []) if sym}


def _daily_learning_sectors() -> set[str]:
    data = _daily_learning()
    return {
        str(row.get("sector", "")).upper()
        for row in data.get("sector_summary", [])[:8]
        if row.get("sector")
    }


def _regime() -> dict[str, Any]:
    try:
        from modules.market_regime import classify_regime

        return classify_regime()
    except Exception:
        return {"regime": "UNKNOWN", "tracker_bias": "find_stock_specific_strength"}


def _confidence_label(score: float) -> str:
    if score >= 82:
        return "A"
    if score >= 68:
        return "B"
    if score >= 52:
        return "C"
    return "WATCH_ONLY"


def _pattern_edge(pattern_key: str) -> dict[str, Any]:
    if not pattern_key:
        return {}
    try:
        from modules.pattern_backtester import get_pattern_edge

        return get_pattern_edge(pattern_key)
    except Exception:
        return {}


def _hot_sectors() -> set[str]:
    state = _load_json(os.path.join("data", "grok_dashboard_state.json"))
    sectors = state.get("trending_sectors") or []
    return {
        str(row.get("sector") or row.get("name") or "").upper()
        for row in sectors[:5]
        if row.get("sector") or row.get("name")
    }


def score_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Attach terminal_score and reason tags to one candidate."""
    symbol = str(candidate.get("symbol", "")).replace(".NS", "").upper()
    sector = str(candidate.get("sector", "")).upper()
    score = _safe_float(candidate.get("score"))
    vol = _safe_float(candidate.get("volume_ratio") or candidate.get("vol_ratio"), 1.0)
    rsi = _safe_float(candidate.get("rsi"), 50.0)
    adx = _safe_float(candidate.get("adx"), 0.0)
    change = _safe_float(candidate.get("price_change_pct") or candidate.get("daily_change") or candidate.get("change_pct"))
    gap = _safe_float(candidate.get("gap_up") or candidate.get("gap_up_pct") or candidate.get("gap_pct"))
    rr = _safe_float(candidate.get("risk_reward"), 0.0)
    pattern_key = str(candidate.get("pattern_key", "") or "")
    open_to_high = _safe_float(candidate.get("open_to_high_pct"))
    open_to_close = _safe_float(candidate.get("open_to_close_pct"))
    first_15m_return = _safe_float(candidate.get("first_15m_return_pct"))
    first_15m_volume = _safe_float(candidate.get("first_15m_volume_ratio"))

    terminal_score = score
    reasons: list[str] = []
    regime = _regime()

    if vol >= 2.0:
        terminal_score += 12
        reasons.append("volume shock >=2x")
    elif vol >= 1.3:
        terminal_score += 6
        reasons.append("volume above average")

    if 45 <= rsi <= 72:
        terminal_score += 8
        reasons.append("RSI in momentum zone")
    elif rsi > 78:
        terminal_score -= 6
        reasons.append("RSI extended")

    if adx >= 22:
        terminal_score += 8
        reasons.append("trend strength")

    if 0 <= gap <= 4:
        terminal_score += 6
        reasons.append("controlled gap")
    elif gap > 7:
        terminal_score -= 8
        reasons.append("gap too stretched")

    if 0 <= change <= 8:
        terminal_score += 6
        reasons.append("positive continuation")
    elif change < -4:
        terminal_score -= 6
        reasons.append("weak daily momentum")

    if rr >= 2:
        terminal_score += 5
        reasons.append("RR >=2")

    if symbol in _ollama_symbols():
        terminal_score += 14
        reasons.append("Ollama winner-pattern match")

    if symbol in _daily_learning_symbols():
        terminal_score += 10
        reasons.append("daily GPT winner-learning match")

    if sector and sector in _hot_sectors():
        terminal_score += 8
        reasons.append("hot sector")

    if sector and sector in _daily_learning_sectors():
        terminal_score += 7
        reasons.append("sector matched daily 7pct winners")

    if open_to_high >= 7:
        terminal_score += 10
        reasons.append("7pct intraday tracker behavior")

    if open_to_close > 0:
        terminal_score += 5
        reasons.append("green close relative strength")

    if first_15m_return >= 1.0:
        terminal_score += 6
        reasons.append("early strength")

    if first_15m_volume >= 2.0:
        terminal_score += 6
        reasons.append("first-15m volume expansion")

    if regime.get("regime") in {"RED_MARKET", "DIP_MARKET"}:
        if open_to_close > 0 or change > 0:
            terminal_score += 10
            reasons.append("red-market relative strength")
        elif change < -2:
            terminal_score -= 8
            reasons.append("weak in red market")

    edge = _pattern_edge(pattern_key)
    if edge:
        if edge.get("proven_edge"):
            terminal_score += 8
            reasons.append(f"backtested edge {float(edge.get('hit_rate', 0)):.0%}")
        elif int(edge.get("total_trades", 0) or 0) >= 3:
            terminal_score -= 4
            reasons.append("pattern edge unproven")

    if _safe_float(candidate.get("price") or candidate.get("entry_price")) < 50:
        terminal_score -= 20
        reasons.append("low-price risk")

    enriched = {**candidate}
    enriched["terminal_score"] = round(max(0, min(100, terminal_score)), 2)
    enriched["terminal_reasons"] = reasons[:6]
    enriched["confidence_grade"] = _confidence_label(enriched["terminal_score"])
    enriched["market_regime"] = regime.get("regime")
    enriched["tracker_bias"] = regime.get("tracker_bias")
    if edge:
        enriched["pattern_edge"] = edge
    if reasons and not enriched.get("signal_reasons"):
        enriched["signal_reasons"] = "; ".join(reasons[:4])
    return enriched


def rank_candidates(candidates: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    """Rank candidates by terminal score, falling back to normal score."""
    best_by_symbol: dict[str, dict[str, Any]] = {}
    for row in candidates:
        enriched = score_candidate(row)
        symbol = str(enriched.get("symbol", "")).replace(".NS", "").upper()
        if not symbol:
            continue
        current = best_by_symbol.get(symbol)
        if current is None or _safe_float(enriched.get("terminal_score")) > _safe_float(current.get("terminal_score")):
            best_by_symbol[symbol] = enriched
    ranked = list(best_by_symbol.values())
    ranked.sort(key=lambda row: (_safe_float(row.get("terminal_score")), _safe_float(row.get("score"))), reverse=True)
    for idx, row in enumerate(ranked, start=1):
        row["terminal_rank"] = idx
    return ranked[:limit] if limit else ranked


def terminal_snapshot(limit: int = 20) -> dict[str, Any]:
    """Return a compact market-terminal snapshot for dashboard/API use."""
    from config import DB_PATH

    try:
        from modules.time_utils import today_ist_str

        today = today_ist_str()
    except Exception:
        today = dt.date.today().isoformat()
    picks: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT symbol, rank, entry_price, sl_price, target_price, confidence AS score,
                          signal_reasons, status, created_at
                   FROM picks
                  WHERE date=?
                    AND COALESCE(session_type, 'morning_final')='morning_final'
                    AND COALESCE(is_official_morning, 1)=1
                  ORDER BY rank""",
                (today,),
            ).fetchall()
        picks = [dict(row) for row in rows]
    except Exception:
        picks = []

    grok = _load_json(os.path.join("data", "grok_dashboard_state.json"))
    ollama = _load_json(os.path.join("data", "ollama_intraday_agent_state.json"))
    intraday = _load_json(os.path.join("data", "intraday_pattern_agent_report.json"))

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "today_picks": rank_candidates(picks, limit=limit),
        "hot_sectors": list(_hot_sectors()),
        "ollama_top_symbols": sorted(_ollama_symbols())[:limit],
        "intraday_watchlist": intraday.get("watchlist", [])[:limit],
        "grok_ai": grok.get("ai", {}),
        "ollama_study": ollama.get("study", {}),
    }
