"""Local Ollama agent for studying NSE intraday high-return behavior."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any

import pandas as pd
import requests

from modules.time_utils import now_ist, today_ist_str

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

STATE_FILE = "data/ollama_intraday_agent_state.json"
DAILY_LEARNING_FILE = "data/daily_winner_learning.json"
_agent_thread: threading.Thread | None = None
_agent_running = False


def _now() -> str:
    return now_ist().isoformat(timespec="seconds")


def _today() -> str:
    return today_ist_str()


def _connect() -> sqlite3.Connection:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _safe_num(value: Any, default: float = 0.0) -> float:
    try:
        val = float(value)
        if pd.isna(val):
            return default
        return val
    except Exception:
        return default


def _clean_symbols(symbols: list[str]) -> list[str]:
    clean = []
    for symbol in symbols:
        sym = str(symbol or "").strip().upper().replace(".NS", "")
        if not sym or sym.isdigit() or "." in sym or "^" in sym or any(ch.isspace() for ch in sym):
            continue
        clean.append(sym)
    return sorted(set(clean))


def _universe() -> list[str]:
    from config import OLLAMA_AGENT_MAX_SYMBOLS
    from modules.scanner import get_universe

    symbols = _clean_symbols(get_universe(force_refresh=False) or [])
    if OLLAMA_AGENT_MAX_SYMBOLS and OLLAMA_AGENT_MAX_SYMBOLS > 0:
        return symbols[:OLLAMA_AGENT_MAX_SYMBOLS]
    return symbols


def _extract_ticker_frame(data: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if data is None or data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        try:
            frame = data[ticker].copy()
        except Exception:
            return pd.DataFrame()
    else:
        frame = data.copy()
    frame = frame.dropna(how="all")
    if frame.empty:
        return pd.DataFrame()
    frame.columns = [str(col).lower() for col in frame.columns]
    return frame


def _daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(set(frame.columns)):
        return pd.DataFrame()
    daily = frame.resample("1D").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return daily.dropna()


def _score(row: dict[str, Any]) -> float:
    score = 0.0
    score += max(0.0, row.get("open_to_high_pct", 0.0)) * 2.0
    score += max(0.0, row.get("return_pct", 0.0)) * 1.5
    score += min(25.0, max(0.0, row.get("first_15m_volume_ratio", 0.0)) * 4.0)
    score += min(20.0, max(0.0, row.get("volume_ratio", 0.0)) * 3.0)
    score += 10.0 if row.get("first_15m_return_pct", 0.0) > 1.2 else 0.0
    score += 8.0 if row.get("gap_pct", 0.0) > 0.5 else 0.0
    score += 8.0 if row.get("weekly_change_pct", 0.0) > 3.0 else 0.0
    return round(score, 3)


def _features(symbol: str, frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty:
        return None
    today = dt.date.today()
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index)
    day = frame[pd.to_datetime(frame.index).date == today]
    if day.empty:
        day = frame.tail(min(75, len(frame)))
    if day.empty:
        return None

    daily = _daily_bars(frame)
    if daily.empty:
        return None

    first = day.iloc[0]
    latest = day.iloc[-1]
    first_15 = day.iloc[:3] if len(day) >= 3 else day
    open_price = _safe_num(first.get("open"))
    high_price = _safe_num(day["high"].max())
    low_price = _safe_num(day["low"].min())
    close_price = _safe_num(latest.get("close"))
    if open_price <= 0 or close_price <= 0:
        return None

    hist = daily[pd.to_datetime(daily.index).date < today]
    prev_close = _safe_num(hist["close"].iloc[-1]) if not hist.empty else open_price
    avg_daily_volume = _safe_num(hist["volume"].tail(20).mean()) if not hist.empty else _safe_num(daily["volume"].mean())
    day_volume = _safe_num(day["volume"].sum())
    first_15_volume = _safe_num(first_15["volume"].sum())
    first_15_close = _safe_num(first_15["close"].iloc[-1])

    row = {
        "symbol": symbol,
        "open_price": round(open_price, 4),
        "high_price": round(high_price, 4),
        "low_price": round(low_price, 4),
        "close_price": round(close_price, 4),
        "return_pct": round((close_price - open_price) / open_price * 100, 4),
        "open_to_high_pct": round((high_price - open_price) / open_price * 100, 4),
        "open_to_close_pct": round((close_price - open_price) / open_price * 100, 4),
        "gap_pct": round((open_price - prev_close) / prev_close * 100, 4) if prev_close > 0 else 0.0,
        "first_15m_return_pct": round((first_15_close - open_price) / open_price * 100, 4) if open_price > 0 else 0.0,
        "first_15m_volume_ratio": round(first_15_volume / (avg_daily_volume / 25), 4) if avg_daily_volume > 0 else 0.0,
        "volume_ratio": round(day_volume / avg_daily_volume, 4) if avg_daily_volume > 0 else 0.0,
        "prev_day_change_pct": 0.0,
        "weekly_change_pct": 0.0,
    }
    if len(hist) >= 2:
        prior = _safe_num(hist["close"].iloc[-2])
        last = _safe_num(hist["close"].iloc[-1])
        row["prev_day_change_pct"] = round((last - prior) / prior * 100, 4) if prior > 0 else 0.0
    if len(hist) >= 5:
        base = _safe_num(hist["close"].iloc[-5])
        last = _safe_num(hist["close"].iloc[-1])
        row["weekly_change_pct"] = round((last - base) / base * 100, 4) if base > 0 else 0.0

    try:
        from modules.intraday_pattern_agent import infer_sector

        row["sector"] = infer_sector(symbol)
    except Exception:
        row["sector"] = "UNKNOWN"
    row["score"] = _score(row)
    return row


def scan_full_universe() -> dict[str, Any]:
    from config import OLLAMA_AGENT_CHUNK_SIZE, OLLAMA_AGENT_MIN_RETURN_PCT, OLLAMA_AGENT_TOP_CANDIDATES
    from modules.fetch import SYMBOL_ALIASES
    import yfinance as yf

    symbols = _universe()
    scan_time = now_ist().strftime("%H:%M:%S")
    candidates: list[dict[str, Any]] = []
    failed_batches = 0
    logger.info("Ollama intraday agent scanning %s NSE symbols", len(symbols))

    for batch in _chunks(symbols, max(10, OLLAMA_AGENT_CHUNK_SIZE)):
        tickers = [f"{SYMBOL_ALIASES.get(sym, sym)}.NS" for sym in batch]
        reverse = dict(zip(tickers, batch))
        try:
            data = yf.download(
                tickers,
                period="7d",
                interval="5m",
                auto_adjust=True,
                group_by="ticker",
                progress=False,
                threads=True,
            )
        except Exception as exc:
            failed_batches += 1
            logger.debug("Ollama agent batch download failed: %s", exc)
            continue
        for ticker in tickers:
            row = _features(reverse[ticker], _extract_ticker_frame(data, ticker))
            if row:
                candidates.append(row)

    candidates.sort(key=lambda row: (row.get("open_to_high_pct", 0), row.get("score", 0)), reverse=True)
    winners = [row for row in candidates if row.get("open_to_high_pct", 0) >= OLLAMA_AGENT_MIN_RETURN_PCT]
    top = candidates[: max(5, OLLAMA_AGENT_TOP_CANDIDATES)]
    _store_candidates(scan_time, top, winners)
    return {
        "date": _today(),
        "scan_time": scan_time,
        "symbols_scanned": len(symbols),
        "candidates_found": len(candidates),
        "winner_count": len(winners),
        "failed_batches": failed_batches,
        "top_candidates": top,
        "winners": winners[: max(5, OLLAMA_AGENT_TOP_CANDIDATES)],
    }


def _store_candidates(scan_time: str, top: list[dict[str, Any]], winners: list[dict[str, Any]]) -> None:
    rows = {row["symbol"]: row for row in top}
    for row in winners:
        rows[row["symbol"]] = row
    today = _today()
    with _connect() as conn:
        for row in rows.values():
            conn.execute(
                """INSERT OR REPLACE INTO ollama_intraday_candidates
                   (date, scan_time, symbol, return_pct, open_to_high_pct, open_to_close_pct,
                    gap_pct, first_15m_return_pct, first_15m_volume_ratio, volume_ratio,
                    prev_day_change_pct, weekly_change_pct, sector, score, features_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    today,
                    scan_time,
                    row.get("symbol"),
                    row.get("return_pct"),
                    row.get("open_to_high_pct"),
                    row.get("open_to_close_pct"),
                    row.get("gap_pct"),
                    row.get("first_15m_return_pct"),
                    row.get("first_15m_volume_ratio"),
                    row.get("volume_ratio"),
                    row.get("prev_day_change_pct"),
                    row.get("weekly_change_pct"),
                    row.get("sector"),
                    row.get("score"),
                    json.dumps(row, ensure_ascii=False, default=str),
                ),
            )
        conn.commit()


def _ollama_available() -> bool:
    from config import OLLAMA_BASE_URL

    try:
        response = requests.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=5)
        return response.status_code == 200
    except Exception:
        return False


def _call_ollama(payload: dict[str, Any]) -> dict[str, Any]:
    from config import OLLAMA_AGENT_TIMEOUT_SECONDS, OLLAMA_BASE_URL, OLLAMA_MODEL

    prompt = (
        "You are a local NSE intraday winner-research agent. Study the provided full-universe scan. "
        "Find pre-move behavior shared by stocks with the highest open-to-high and open-to-close returns. "
        "Use only this data. Do not invent live prices. Return JSON only with keys: summary, "
        "winner_profile, force_filters, avoid_filters, top_symbols, next_scan_focus. "
        "force_filters and avoid_filters must be arrays of short rules the scanner can apply."
        "\n\nDATA:\n"
        + json.dumps(payload, ensure_ascii=True, default=str)[:9000]
    )
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_predict": 450},
            },
            timeout=OLLAMA_AGENT_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            return {"ok": False, "error": response.text[:300]}
        text = (response.json().get("response") or "").strip()
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = {"summary": text[:1000], "winner_profile": "", "force_filters": [], "avoid_filters": [], "top_symbols": []}
        parsed["ok"] = True
        parsed["model"] = OLLAMA_MODEL
        return parsed
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def _call_openrouter_learning(payload: dict[str, Any]) -> dict[str, Any]:
    """Use GPT as primary after-market learner, with Grok fallback."""
    try:
        from modules.dual_brain import _call_openrouter
        from config import (
            OPENROUTER_BASE_URL,
            OPENROUTER_GPT_KEY,
            OPENROUTER_GROK_KEY,
            GPT_MODEL,
            GROK_MODEL,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}

    system_prompt = (
        "You are the primary GPT learning brain for an Indian NSE intraday research system. "
        "Study only the supplied full-universe winner data. Find repeated pre-move behavior "
        "before 7%+ open-to-high or green close moves, sector heat, market-condition context, "
        "upper-circuit style behavior, avoid conditions, and tomorrow scoring rules. "
        "Return compact JSON only with keys: summary, common_pre_move_behaviors, sector_patterns, "
        "market_condition_lessons, upper_circuit_clues, next_day_filters, avoid_filters, top_symbols, confidence."
    )
    user_prompt = json.dumps(payload, ensure_ascii=True, default=str)[:16000]
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    if OPENROUTER_GPT_KEY:
        result = _call_openrouter(messages, OPENROUTER_GPT_KEY, GPT_MODEL, 900, OPENROUTER_BASE_URL)
        if result.get("ok"):
            parsed = _parse_json(result.get("content", ""))
            parsed["ok"] = True
            parsed["model"] = GPT_MODEL
            parsed["brain_role"] = "gpt_primary"
            return parsed
        logger.warning("GPT daily learning failed, trying Grok fallback: %s", result.get("error"))

    if OPENROUTER_GROK_KEY:
        result = _call_openrouter(messages, OPENROUTER_GROK_KEY, GROK_MODEL, 900, OPENROUTER_BASE_URL)
        if result.get("ok"):
            parsed = _parse_json(result.get("content", ""))
            parsed["ok"] = True
            parsed["model"] = GROK_MODEL
            parsed["brain_role"] = "grok_fallback"
            return parsed
        return {"ok": False, "error": result.get("error", "Grok fallback failed")}

    return {"ok": False, "error": "No OpenRouter GPT/Grok key configured"}


def _parse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return {"summary": str(text or "")[:1200]}


def study_scan(scan: dict[str, Any]) -> dict[str, Any]:
    if not _ollama_available():
        study = {
            "ok": False,
            "error": "Ollama server unavailable",
            "summary": "Ollama is not reachable; stored numerical scan only.",
            "force_filters": [],
            "avoid_filters": [],
            "top_symbols": [row.get("symbol") for row in scan.get("top_candidates", [])[:10]],
        }
    else:
        study = _call_ollama(
            {
                "date": scan.get("date"),
                "scan_time": scan.get("scan_time"),
                "symbols_scanned": scan.get("symbols_scanned"),
                "winner_count": scan.get("winner_count"),
                "top_candidates": scan.get("top_candidates", [])[:15],
                "winners": scan.get("winners", [])[:15],
            }
        )
    _store_study(scan, study)
    return study


def _sector_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sectors: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sectors.setdefault(str(row.get("sector") or "UNKNOWN"), []).append(row)
    summary = []
    for sector, items in sectors.items():
        summary.append({
            "sector": sector,
            "winner_count": len(items),
            "avg_open_to_high_pct": round(sum(float(x.get("open_to_high_pct") or 0) for x in items) / max(1, len(items)), 3),
            "avg_open_to_close_pct": round(sum(float(x.get("open_to_close_pct") or 0) for x in items) / max(1, len(items)), 3),
            "avg_volume_ratio": round(sum(float(x.get("volume_ratio") or 0) for x in items) / max(1, len(items)), 3),
            "top_symbols": [x.get("symbol") for x in sorted(items, key=lambda x: x.get("open_to_high_pct", 0), reverse=True)[:8]],
        })
    return sorted(summary, key=lambda x: (x["winner_count"], x["avg_open_to_high_pct"]), reverse=True)


def _numeric_learning(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}

    def avg(key: str) -> float:
        vals = [float(row.get(key) or 0) for row in rows]
        return round(sum(vals) / max(1, len(vals)), 3)

    green = [r for r in rows if float(r.get("open_to_close_pct") or 0) > 0]
    strong_gap = [r for r in rows if float(r.get("gap_pct") or 0) >= 1]
    strong_first_15 = [r for r in rows if float(r.get("first_15m_return_pct") or 0) >= 1]
    volume_surge = [r for r in rows if float(r.get("first_15m_volume_ratio") or 0) >= 2 or float(r.get("volume_ratio") or 0) >= 2]
    prior_week = [r for r in rows if float(r.get("weekly_change_pct") or 0) >= 3]
    return {
        "winner_count": len(rows),
        "green_close_count": len(green),
        "strong_gap_count": len(strong_gap),
        "strong_first_15m_count": len(strong_first_15),
        "volume_surge_count": len(volume_surge),
        "prior_week_momentum_count": len(prior_week),
        "avg_open_to_high_pct": avg("open_to_high_pct"),
        "avg_open_to_close_pct": avg("open_to_close_pct"),
        "avg_gap_pct": avg("gap_pct"),
        "avg_first_15m_return_pct": avg("first_15m_return_pct"),
        "avg_first_15m_volume_ratio": avg("first_15m_volume_ratio"),
        "avg_volume_ratio": avg("volume_ratio"),
    }


def _load_winners_for_date(date: str, min_return_pct: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _connect() as conn:
        fetched = conn.execute(
            """SELECT symbol, return_pct, open_to_high_pct, open_to_close_pct, gap_pct,
                      first_15m_return_pct, first_15m_volume_ratio, volume_ratio,
                      prev_day_change_pct, weekly_change_pct, sector, score, features_json
               FROM ollama_intraday_candidates
               WHERE date=? AND open_to_high_pct>=?
               ORDER BY open_to_high_pct DESC""",
            (date, min_return_pct),
        ).fetchall()
    seen = set()
    for row in fetched:
        symbol = str(row["symbol"] or "").upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        try:
            payload = json.loads(row["features_json"] or "{}")
        except Exception:
            payload = {}
        item = {**dict(row), **payload}
        item.pop("features_json", None)
        rows.append(item)
    return rows


def daily_winner_learning(min_return_pct: float | None = None, force: bool = False, send_telegram: bool = True) -> dict[str, Any]:
    """Run one GPT-primary daily learning pass over all stored 7%+ NSE movers."""
    from config import OLLAMA_AGENT_MIN_RETURN_PCT

    min_return_pct = float(min_return_pct or OLLAMA_AGENT_MIN_RETURN_PCT)
    date = _today()

    if not force and os.path.exists(DAILY_LEARNING_FILE):
        try:
            with open(DAILY_LEARNING_FILE, "r", encoding="utf-8") as fp:
                previous = json.load(fp)
            if previous.get("date") == date and previous.get("winner_count", 0) > 0:
                return {**previous, "skipped": True, "reason": "already_learned_today"}
        except Exception:
            pass

    winners = _load_winners_for_date(date, min_return_pct)
    if not winners:
        scan = scan_full_universe()
        winners = scan.get("winners", [])
    winners = sorted(winners, key=lambda row: row.get("open_to_high_pct", 0), reverse=True)

    sector_summary = _sector_summary(winners)
    numeric = _numeric_learning(winners)
    payload = {
        "date": date,
        "task": "daily_full_universe_7pct_winner_learning",
        "winner_count": len(winners),
        "top_winners": winners[:30],
        "sector_summary": sector_summary[:25],
        "numeric_common_behavior": numeric,
        "instruction": (
            "Learn what these winners looked like before and during the move. "
            "Extract reusable filters for future morning scoring across red, flat, and bull markets."
        ),
    }
    ai = _call_openrouter_learning(payload) if winners else {"ok": False, "error": "No winners found"}

    result = {
        "date": date,
        "updated_at": _now(),
        "winner_count": len(winners),
        "top_symbols": [row.get("symbol") for row in winners[:15]],
        "sector_summary": sector_summary,
        "numeric_common_behavior": numeric,
        "ai": ai,
    }
    os.makedirs(os.path.dirname(DAILY_LEARNING_FILE), exist_ok=True)
    with open(DAILY_LEARNING_FILE, "w", encoding="utf-8") as fp:
        json.dump(result, fp, indent=2, ensure_ascii=False, default=str)

    study = {
        "ok": ai.get("ok", False),
        "model": ai.get("model"),
        "summary": ai.get("summary", ""),
        "winner_profile": "; ".join(ai.get("common_pre_move_behaviors", [])[:5]) if isinstance(ai.get("common_pre_move_behaviors"), list) else "",
        "force_filters": ai.get("next_day_filters", []),
        "avoid_filters": ai.get("avoid_filters", []),
        "top_symbols": result["top_symbols"],
        "daily_learning": result,
    }
    _store_study({"date": date, "scan_time": "AFTER_CLOSE", "top_candidates": winners[:40]}, study)

    if send_telegram:
        _notify_daily_learning(result)
    return result


def _notify_daily_learning(result: dict[str, Any]) -> None:
    try:
        from modules.alerts import send_raw_alert

        ai = result.get("ai") or {}
        sectors = ", ".join(row.get("sector", "") for row in result.get("sector_summary", [])[:5]) or "None"
        top = ", ".join(result.get("top_symbols", [])[:8]) or "None"
        summary = str(ai.get("summary") or "Daily winner learning stored.")[:700]
        send_raw_alert(
            "<b>GPT PRIMARY DAILY WINNER LEARNING</b>\n"
            f"Date: {result.get('date')}\n"
            f"7%+ winners studied: {result.get('winner_count', 0)}\n"
            f"Hot sectors: {sectors}\n"
            f"Top movers: {top}\n"
            f"Brain: {ai.get('model', 'numeric-only')}\n\n"
            f"{summary}\n\n"
            "<i>Research only. Lessons feed future scoring.</i>",
            review_with_grok=False,
        )
    except Exception as exc:
        logger.debug("Daily winner learning Telegram notify failed: %s", exc)


def _store_study(scan: dict[str, Any], study: dict[str, Any]) -> None:
    symbols = [row.get("symbol") for row in scan.get("top_candidates", [])[:40]]
    compact = json.dumps({"scan": scan, "study": study}, sort_keys=True, default=str)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO ollama_winner_studies
               (date, scan_time, model, symbols_json, patterns_json, summary, prompt_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                scan.get("date") or _today(),
                scan.get("scan_time"),
                study.get("model"),
                json.dumps(symbols, ensure_ascii=False),
                json.dumps(study, ensure_ascii=False, default=str),
                str(study.get("summary", ""))[:1200],
                hashlib.sha256(compact.encode("utf-8", errors="ignore")).hexdigest(),
            ),
        )
        conn.commit()


def _save_state(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fp:
        json.dump(state, fp, indent=2, ensure_ascii=False, default=str)


def _notify(scan: dict[str, Any], study: dict[str, Any]) -> None:
    from config import OLLAMA_AGENT_NOTIFY_TELEGRAM

    if not OLLAMA_AGENT_NOTIFY_TELEGRAM:
        return
    try:
        from modules.alerts import send_raw_alert

        top = ", ".join(row.get("symbol", "") for row in scan.get("top_candidates", [])[:5])
        summary = str(study.get("summary") or study.get("winner_profile") or "Study stored.")[:500]
        send_raw_alert(
            "<b>Ollama NSE Agent Update</b>\n"
            f"Scanned: {scan.get('symbols_scanned', 0)} | Winners: {scan.get('winner_count', 0)}\n"
            f"Top: {top or 'None'}\n"
            f"{summary}",
            review_with_grok=False,
        )
    except Exception as exc:
        logger.debug("Ollama agent Telegram notify failed: %s", exc)


def run_ollama_cycle(send_telegram: bool = False, study: bool = False) -> dict[str, Any]:
    scan = scan_full_universe()
    study_result = study_scan(scan) if study else {
        "ok": True,
        "model": "numeric_scan_only",
        "summary": "Intraday scan stored. GPT-primary learning runs once after market close.",
        "top_symbols": [row.get("symbol") for row in scan.get("top_candidates", [])[:10]],
    }
    state = {
        "updated_at": _now(),
        "scan": scan,
        "study": study_result,
        "status": "ok" if study_result.get("ok") else "partial",
    }
    _save_state(state)
    if send_telegram:
        _notify(scan, study_result)
    logger.info(
        "Ollama intraday agent cycle complete: scanned=%s candidates=%s winners=%s study=%s",
        scan.get("symbols_scanned"),
        scan.get("candidates_found"),
        scan.get("winner_count"),
        "ok" if study_result.get("ok") else study_result.get("error", "partial"),
    )
    return state


def get_ollama_agent_state(max_age_seconds: int = 1800) -> dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fp:
                state = json.load(fp)
            updated = dt.datetime.fromisoformat(state.get("updated_at"))
            if (dt.datetime.now() - updated).total_seconds() <= max_age_seconds:
                return state
        except Exception:
            pass
    return run_ollama_cycle(send_telegram=False, study=False)


def ollama_intraday_boost(row: dict[str, Any]) -> int:
    """Return a bounded score boost from the latest Ollama winner profile."""
    try:
        state = get_ollama_agent_state(max_age_seconds=3600)
    except Exception:
        return 0
    study = state.get("study") or {}
    scan = state.get("scan") or {}
    top_symbols = set(str(sym).upper() for sym in study.get("top_symbols", []) if sym)
    top_symbols.update(str(item.get("symbol", "")).upper() for item in scan.get("winners", [])[:10])

    symbol = str(row.get("symbol", "")).upper()
    boost = 0
    if symbol in top_symbols:
        boost += 8
    if float(row.get("open_to_high_pct") or 0) >= 5:
        boost += 8
    if float(row.get("open_to_close_pct") or 0) >= 3:
        boost += 7
    if float(row.get("volume_15_ratio") or row.get("first_15m_volume_ratio") or 0) >= 2:
        boost += 6
    if float(row.get("volume_ratio") or 0) >= 2:
        boost += 5
    if float(row.get("gap_pct") or 0) < -5:
        boost -= 5
    return max(0, min(20, boost))


def start_ollama_intraday_agent(interval_minutes: int | None = None) -> dict[str, Any]:
    global _agent_running, _agent_thread

    if _agent_running:
        return {"ok": False, "error": "Ollama intraday agent already running"}

    from config import OLLAMA_AGENT_INTERVAL_MINUTES

    interval_minutes = interval_minutes or OLLAMA_AGENT_INTERVAL_MINUTES
    _agent_running = True

    def _loop() -> None:
        while _agent_running:
            try:
                run_ollama_cycle(send_telegram=False, study=False)
            except Exception as exc:
                logger.error("Ollama intraday agent cycle failed: %s", exc)
            time.sleep(max(300, interval_minutes * 60))

    _agent_thread = threading.Thread(target=_loop, name="ollama-intraday-agent", daemon=True)
    _agent_thread.start()
    logger.info("Ollama intraday agent started (every %s min)", interval_minutes)
    return {"ok": True, "interval_minutes": interval_minutes}


def stop_ollama_intraday_agent() -> dict[str, Any]:
    global _agent_running
    _agent_running = False
    return {"ok": True}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_ollama_cycle(send_telegram=False), indent=2, default=str))
