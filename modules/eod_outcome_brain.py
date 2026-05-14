"""End-of-day outcome reconciliation for tracked research picks.

This module is deliberately deterministic first: it updates TP/SL/EOD records
from the tracker state and daily OHLC data. The AI brain only reviews the final
summary; it does not invent prices or decide outcomes from text.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)
STATE_FILE = "data/eod_outcome_brain_state.json"


def _load_tracking() -> dict[str, dict[str, Any]]:
    path = "data/pick_tracking.json"
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Could not load tracking file: %s", exc)
        return {}


def _latest_tracking_date(tracking: dict[str, dict[str, Any]]) -> str | None:
    dates = sorted({str(v.get("date")) for v in tracking.values() if v.get("date")})
    return dates[-1] if dates else None


def _latest_db_pick_date() -> str | None:
    try:
        from config import DB_PATH
        from modules.db_migrations import ensure_research_tables

        ensure_research_tables()
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT MAX(date) FROM picks").fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception as exc:
        logger.debug("Could not read latest DB pick date: %s", exc)
        return None


def _load_state() -> dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fp:
        json.dump(state, fp, indent=2, sort_keys=True, default=str)


def _alert_fingerprint(updates: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    compact_updates = [
        {
            "symbol": u.get("symbol"),
            "status": u.get("status"),
            "result_return": round(float(u.get("result_return") or 0), 2),
        }
        for u in sorted(updates, key=lambda x: str(x.get("symbol") or ""))
    ]
    payload = {
        "updates": compact_updates,
        "tp": stats.get("tp_count"),
        "sl": stats.get("sl_count"),
        "accuracy": stats.get("accuracy"),
        "avg_return": stats.get("avg_return"),
    }
    return json.dumps(payload, sort_keys=True)


def _fetch_daily_ohlc(symbol: str) -> dict[str, float] | None:
    """Fetch latest daily OHLC for NSE symbol."""
    try:
        import yfinance as yf

        df = yf.Ticker(f"{symbol}.NS").history(period="5d", interval="1d")
        if df is None or df.empty:
            return None
        row = df.iloc[-1]
        return {
            "open": float(row.get("Open", 0) or 0),
            "high": float(row.get("High", 0) or 0),
            "low": float(row.get("Low", 0) or 0),
            "close": float(row.get("Close", 0) or 0),
        }
    except Exception as exc:
        logger.debug("Daily OHLC fetch failed for %s: %s", symbol, exc)
        return None


def _return_pct(exit_price: float, entry_price: float) -> float:
    return round((exit_price - entry_price) / entry_price * 100, 2) if entry_price else 0.0


def _classify_from_ohlc(pick: dict[str, Any], ohlc: dict[str, float] | None) -> dict[str, Any]:
    symbol = str(pick.get("symbol") or "").upper()
    entry = float(pick.get("entry_price") or 0)
    target = float(pick.get("target_price") or pick.get("tp_price") or 0)
    sl = float(pick.get("sl_price") or 0)

    if not ohlc or entry <= 0:
        return {
            "symbol": symbol,
            "status": "eod_closed",
            "exit_price": entry,
            "result_return": 0.0,
            "reason": "no_ohlc_fallback",
        }

    high = float(ohlc.get("high") or 0)
    low = float(ohlc.get("low") or 0)
    close = float(ohlc.get("close") or 0)

    hit_tp = bool(target and high >= target)
    hit_sl = bool(sl and low <= sl)

    if hit_tp and hit_sl:
        # With daily candles the order is unknowable; keep accuracy conservative.
        exit_price = sl
        status = "sl_hit"
        reason = "daily_high_and_low_crossed_target_and_sl"
    elif hit_tp:
        exit_price = target
        status = "tp_hit"
        reason = "daily_high_crossed_target"
    elif hit_sl:
        exit_price = sl
        status = "sl_hit"
        reason = "daily_low_crossed_sl"
    else:
        exit_price = close or entry
        status = "eod_closed"
        reason = "closed_without_tp_sl"

    return {
        "symbol": symbol,
        "status": status,
        "exit_price": round(exit_price, 2),
        "result_return": _return_pct(exit_price, entry),
        "reason": reason,
        "ohlc": ohlc,
    }


def _db_picks_for_date(date_s: str) -> list[dict[str, Any]]:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, date, rank, symbol, entry_price, sl_price, target_price, status, result_return
            FROM picks
            WHERE date=?
            ORDER BY rank, id
            """,
            (date_s,),
        ).fetchall()
    return [dict(r) for r in rows]


def _update_pick_row(pick_id: int, status: str, result_return: float) -> None:
    from config import DB_PATH

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE picks SET status=?, result_return=? WHERE id=?",
            (status, round(float(result_return), 2), pick_id),
        )
        conn.commit()


def _review_summary(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from modules.grok_brain import review_event

        review = review_event("eod_outcome_reconciliation", payload)
        return review if isinstance(review, dict) else {"ok": False, "reason": "invalid_review"}
    except Exception as exc:
        logger.debug("Outcome brain review skipped: %s", exc)
        return {"ok": False, "reason": str(exc)}


def reconcile_daily_outcomes(
    date_s: str | None = None,
    *,
    send_telegram: bool = True,
    review_with_brain: bool = True,
) -> dict[str, Any]:
    """Update tracked pick outcomes and daily accuracy after market close."""
    from modules.stock_tracker import _persist_pick_outcome, _refresh_daily_accuracy

    tracking = _load_tracking()
    if date_s:
        target_date = date_s
    else:
        candidates = [d for d in (_latest_tracking_date(tracking), _latest_db_pick_date()) if d]
        target_date = sorted(candidates)[-1] if candidates else datetime.date.today().isoformat()
    updates: list[dict[str, Any]] = []

    # First trust real-time tracker hits because it has actual hit prices.
    for item in tracking.values():
        if str(item.get("date")) != target_date:
            continue
        status = str(item.get("status") or "").upper()
        if status == "TP_HIT":
            _persist_pick_outcome(item, "tp_hit")
            updates.append({
                "symbol": item.get("symbol"),
                "status": "tp_hit",
                "result_return": round(float(item.get("pnl_pct") or 0), 2),
                "source": "tracker",
            })
        elif status == "SL_HIT":
            _persist_pick_outcome(item, "sl_hit")
            updates.append({
                "symbol": item.get("symbol"),
                "status": "sl_hit",
                "result_return": round(float(item.get("pnl_pct") or 0), 2),
                "source": "tracker",
            })

    # Then close any DB rows still pending using latest daily OHLC.
    already_done = {str(u.get("symbol")) for u in updates}
    for pick in _db_picks_for_date(target_date):
        symbol = str(pick.get("symbol") or "").upper()
        if symbol in already_done:
            continue
        if str(pick.get("status") or "").lower() in {"tp_hit", "sl_hit", "eod_closed", "open_eod"}:
            continue

        outcome = _classify_from_ohlc(pick, _fetch_daily_ohlc(symbol))
        _update_pick_row(int(pick["id"]), outcome["status"], float(outcome["result_return"]))
        outcome["source"] = "daily_ohlc"
        updates.append(outcome)
        logger.info(
            "[OUTCOME_BRAIN] %s %s return=%.2f%% source=%s",
            symbol,
            outcome["status"],
            float(outcome["result_return"]),
            outcome["reason"],
        )
        print(
            f"[OUTCOME_BRAIN] {symbol} {outcome['status'].upper()} "
            f"return={float(outcome['result_return']):.2f}% source={outcome['reason']}",
            flush=True,
        )

    stats = _refresh_daily_accuracy(target_date)
    payload = {
        "date": target_date,
        "updates": updates,
        "stats": stats,
    }
    review = _review_summary(payload) if review_with_brain else {"ok": False, "skipped": True}
    payload["brain_review"] = review

    if send_telegram:
        try:
            from modules.alerts import send_raw_alert

            state = _load_state()
            fingerprint = _alert_fingerprint(updates, stats)
            if state.get("last_alert_date") == target_date and state.get("last_fingerprint") == fingerprint:
                logger.info("Outcome brain Telegram summary already sent for %s", target_date)
                payload["telegram_skipped"] = "duplicate_summary"
                return payload

            tp = int(stats.get("tp_count") or 0)
            sl = int(stats.get("sl_count") or 0)
            avg = float(stats.get("avg_return") or 0.0)
            acc = float(stats.get("accuracy") or 0.0)
            lines = [
                f"<b>EOD Outcome Brain - {target_date}</b>",
                f"Updated: {len(updates)} picks",
                f"TP: {tp} | SL: {sl} | Accuracy: {acc:.1f}%",
                f"Avg Return: {'+' if avg >= 0 else ''}{avg:.2f}%",
            ]
            verdict = review.get("verdict") or review.get("brief_review")
            if verdict:
                lines.append(f"Brain Review: {verdict}")
            lines.append("<i>Research tracking only. No trades placed.</i>")
            ok = send_raw_alert("\n".join(lines), review_with_grok=False)
            if ok:
                state["last_alert_date"] = target_date
                state["last_fingerprint"] = fingerprint
                state["last_alert_time"] = datetime.datetime.now().isoformat(timespec="seconds")
                _save_state(state)
        except Exception as exc:
            logger.warning("Outcome brain Telegram summary failed: %s", exc)

    logger.info("Outcome brain complete: %s", payload)
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(reconcile_daily_outcomes(), indent=2, default=str))
