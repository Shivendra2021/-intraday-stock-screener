"""Research quality gates for official morning picks.

The gates do not place trades. They make the tracker more disciplined by
scoring data quality, provider reliability, setup agreement, historical
similarity, and rejection reasons before picks are stored.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import time
from typing import Any


def _today() -> str:
    try:
        from modules.time_utils import today_ist_str

        return today_ist_str()
    except Exception:
        return dt.date.today().isoformat()


def _now() -> str:
    try:
        from modules.time_utils import now_ist

        return now_ist().isoformat(timespec="seconds")
    except Exception:
        return dt.datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _file_age_score(path: str, fresh_seconds: int = 900) -> float:
    if not os.path.exists(path):
        return 0.0
    try:
        age = time.time() - os.path.getmtime(path)
        if age <= fresh_seconds:
            return 100.0
        if age <= fresh_seconds * 4:
            return 65.0
        return 25.0
    except Exception:
        return 0.0


def provider_reliability_score() -> tuple[float, dict[str, Any]]:
    """Infer provider reliability from latest validation/delivery records."""
    today = _today()
    details: dict[str, Any] = {}
    scores: list[float] = []
    provider_rollup: dict[str, tuple[int, int, str]] = {}
    with _connect() as conn:
        rows = conn.execute(
            """SELECT yahoo_price, nse_price, broker_price, status, created_at
                 FROM price_validations
                WHERE date=?
                ORDER BY id DESC LIMIT 50""",
            (today,),
        ).fetchall()
        if rows:
            yahoo_ok = sum(1 for r in rows if r["yahoo_price"])
            nse_ok = sum(1 for r in rows if r["nse_price"])
            broker_seen = sum(1 for r in rows if r["broker_price"])
            passed = sum(1 for r in rows if r["status"] == "passed")
            total = len(rows)
            details["price_validations"] = total
            details["yahoo_ok"] = yahoo_ok
            details["nse_ok"] = nse_ok
            details["broker_seen"] = broker_seen
            details["passed"] = passed
            provider_rollup["yahoo"] = (yahoo_ok, total - yahoo_ok, "")
            provider_rollup["nse"] = (nse_ok, total - nse_ok, "")
            provider_rollup["price_validation"] = (passed, total - passed, "")
            scores.append(100.0 * yahoo_ok / total)
            scores.append(100.0 * nse_ok / total)
            scores.append(100.0 * passed / total)
        else:
            details["price_validations"] = 0
            scores.append(55.0)

    telegram_path = os.path.join("data", "telegram_delivery.jsonl")
    telegram_ok = 0
    telegram_total = 0
    if os.path.exists(telegram_path):
        try:
            with open(telegram_path, "r", encoding="utf-8") as fp:
                for line in fp.readlines()[-40:]:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    telegram_total += 1
                    if rec.get("ok"):
                        telegram_ok += 1
        except Exception:
            pass
    if telegram_total:
        scores.append(100.0 * telegram_ok / telegram_total)
    details["telegram_ok"] = telegram_ok
    details["telegram_total"] = telegram_total
    if telegram_total:
        provider_rollup["telegram"] = (telegram_ok, telegram_total - telegram_ok, "")

    score = round(sum(scores) / max(len(scores), 1), 2)
    _record_provider_reliability(provider_rollup)
    return _clamp(score), details


def _record_provider_reliability(rollup: dict[str, tuple[int, int, str]]) -> None:
    if not rollup:
        return
    today = _today()
    now = _now()
    with _connect() as conn:
        for provider, (ok_count, fail_count, last_error) in rollup.items():
            total = ok_count + fail_count
            score = round((ok_count / total * 100.0) if total else 0.0, 2)
            conn.execute(
                """INSERT INTO provider_reliability
                   (date, provider, ok_count, fail_count, score, last_error, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(date, provider) DO UPDATE SET
                     ok_count=excluded.ok_count,
                     fail_count=excluded.fail_count,
                     score=excluded.score,
                     last_error=excluded.last_error,
                     updated_at=excluded.updated_at""",
                (today, provider, ok_count, fail_count, score, last_error, now),
            )
        conn.commit()


def data_quality_snapshot(stage: str = "pre_pick") -> dict[str, Any]:
    """Store a compact data readiness score for dashboard/audit use."""
    today = _today()
    provider_score, provider_details = provider_reliability_score()
    with _connect() as conn:
        universe_count = conn.execute("SELECT COUNT(*) FROM stock_universe").fetchone()[0]
        active_symbols = conn.execute(
            "SELECT COUNT(*) FROM stock_universe WHERE is_active=1"
        ).fetchone()[0]
        validations = conn.execute(
            "SELECT COUNT(*) FROM price_validations WHERE date=? AND status='passed'",
            (today,),
        ).fetchone()[0]

        universe_score = 100.0 if active_symbols >= 1000 else (60.0 if active_symbols >= 300 else 20.0)
        price_validation_score = 100.0 if validations >= 5 else (70.0 if validations >= 2 else 45.0)
        terminal_score = _file_age_score(os.path.join("data", "live_terminal_state.json"), 300)
        overall = round(
            universe_score * 0.35
            + price_validation_score * 0.25
            + provider_score * 0.25
            + terminal_score * 0.15,
            2,
        )
        status = "ok" if overall >= 70 else ("warn" if overall >= 50 else "bad")
        details = {
            "universe_score": universe_score,
            "provider": provider_details,
        }
        conn.execute(
            """INSERT INTO data_quality_snapshots
               (date, stage, universe_count, active_symbols, price_validation_score,
                provider_reliability_score, terminal_freshness_score, overall_score,
                status, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                today,
                stage,
                universe_count,
                active_symbols,
                round(price_validation_score, 2),
                provider_score,
                round(terminal_score, 2),
                overall,
                status,
                _json(details),
                _now(),
            ),
        )
        conn.commit()
    return {
        "date": today,
        "stage": stage,
        "universe_count": universe_count,
        "active_symbols": active_symbols,
        "price_validation_score": round(price_validation_score, 2),
        "provider_reliability_score": provider_score,
        "terminal_freshness_score": round(terminal_score, 2),
        "overall_score": overall,
        "status": status,
        "details": details,
    }


def agreement_score(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    """Score whether sector, volume, trend, and price action agree."""
    reasons: list[str] = []
    score = 45.0
    rsi = _safe_float(candidate.get("rsi"), 50)
    adx = _safe_float(candidate.get("adx"), 0)
    vol = _safe_float(candidate.get("vol_ratio", candidate.get("volume_ratio")), 1)
    gap = _safe_float(candidate.get("gap_up", candidate.get("gap_pct")), 0)
    day = _safe_float(candidate.get("daily_change", candidate.get("price_change_pct")), 0)
    ema = str(candidate.get("ema_alignment", "")).lower()
    sector = str(candidate.get("sector") or "Unknown")

    if vol >= 2:
        score += 15
        reasons.append("volume_confirmed")
    elif vol < 1.2:
        score -= 15
        reasons.append("weak_volume")

    if 50 <= rsi <= 72:
        score += 12
        reasons.append("rsi_momentum_zone")
    elif rsi > 80:
        score -= 10
        reasons.append("rsi_overextended")

    if adx >= 22:
        score += 10
        reasons.append("trend_strength")

    if "bull" in ema or ema in {"bullish", "partial"}:
        score += 10
        reasons.append("ema_trend_agrees")
    else:
        score -= 8
        reasons.append("ema_not_confirmed")

    if day >= 0 and gap >= -1:
        score += 8
        reasons.append("price_action_agrees")
    elif day < -2:
        score -= 12
        reasons.append("price_action_weak")

    if sector and sector.lower() != "unknown":
        score += 5
        reasons.append("sector_known")

    return round(_clamp(score), 2), reasons


def historical_similarity_score(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    """Compare a candidate with stored 7%+ winner features."""
    reasons: list[str] = []
    score = 45.0
    rsi = _safe_float(candidate.get("rsi"), 50)
    adx = _safe_float(candidate.get("adx"), 0)
    vol = _safe_float(candidate.get("vol_ratio", candidate.get("volume_ratio")), 1)
    gap = _safe_float(candidate.get("gap_up", candidate.get("gap_pct")), 0)
    sector = str(candidate.get("sector") or "")
    pattern_key = str(candidate.get("pattern_key") or "")

    with _connect() as conn:
        rows = conn.execute(
            """SELECT sector, pattern_key, volume_ratio, gap_pct, rsi, adx, return_pct
                 FROM after_market_winner_features
                ORDER BY date DESC, return_pct DESC
                LIMIT 250"""
        ).fetchall()
    if not rows:
        return 55.0, ["no_7pct_history_yet"]

    matches = 0
    weighted = 0.0
    for row in rows:
        local = 0.0
        if sector and row["sector"] and str(row["sector"]).lower() == sector.lower():
            local += 20
        if pattern_key and row["pattern_key"] and row["pattern_key"] == pattern_key:
            local += 25
        if abs(vol - _safe_float(row["volume_ratio"], vol)) <= 1.5:
            local += 15
        if abs(gap - _safe_float(row["gap_pct"], gap)) <= 1.5:
            local += 10
        if abs(rsi - _safe_float(row["rsi"], rsi)) <= 8:
            local += 10
        if abs(adx - _safe_float(row["adx"], adx)) <= 8:
            local += 10
        if local >= 35:
            matches += 1
            weighted += local * max(1.0, _safe_float(row["return_pct"], 7.0) / 7.0)
    if matches:
        score = _clamp(45.0 + min(45.0, weighted / matches / 2.0))
        reasons.append(f"similar_to_{matches}_past_winners")
    else:
        reasons.append("low_similarity_to_past_winners")
    return round(score, 2), reasons


def enrich_candidate(candidate: dict[str, Any], data_quality: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attach all quality scores and adjust confidence conservatively."""
    enriched = dict(candidate)
    dq = data_quality or data_quality_snapshot("candidate_enrich")
    provider_score = _safe_float(dq.get("provider_reliability_score"), 60)
    data_score = _safe_float(dq.get("overall_score"), 60)
    agree, agree_reasons = agreement_score(enriched)
    sim, sim_reasons = historical_similarity_score(enriched)
    base = _safe_float(enriched.get("score"), 0)

    quality_blend = data_score * 0.25 + provider_score * 0.2 + agree * 0.3 + sim * 0.25
    delta = round((quality_blend - 70.0) * 0.18, 2)
    adjusted = round(_clamp(base + delta), 2)
    reasons = agree_reasons + sim_reasons
    if data_score < 60:
        reasons.append("data_quality_low")
    if provider_score < 60:
        reasons.append("provider_reliability_low")

    enriched.update({
        "score": adjusted,
        "raw_score": base,
        "confidence_delta": delta,
        "data_quality_score": round(data_score, 2),
        "provider_reliability_score": round(provider_score, 2),
        "agreement_score": agree,
        "similarity_score": sim,
        "quality_reasons": "; ".join(reasons[:10]),
    })
    return enriched


def audit_candidate(stage: str, candidate: dict[str, Any], accepted: bool, reasons: list[str] | str | None = None) -> None:
    """Persist why a candidate was accepted/rejected at a decision stage."""
    if isinstance(reasons, str):
        reason_list = [reasons]
    else:
        reason_list = list(reasons or [])
    with _connect() as conn:
        conn.execute(
            """INSERT INTO candidate_audit
               (date, stage, symbol, accepted, score, adjusted_score, confidence_delta,
                data_quality_score, reliability_score, similarity_score, agreement_score,
                reasons_json, snapshot_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _today(),
                stage,
                candidate.get("symbol"),
                1 if accepted else 0,
                candidate.get("raw_score", candidate.get("score")),
                candidate.get("score"),
                candidate.get("confidence_delta", 0),
                candidate.get("data_quality_score"),
                candidate.get("provider_reliability_score"),
                candidate.get("similarity_score"),
                candidate.get("agreement_score"),
                _json(reason_list),
                _json({k: v for k, v in candidate.items() if k not in {"price_validation"}}),
                _now(),
            ),
        )
        conn.commit()


def latest_quality_summary() -> dict[str, Any]:
    with _connect() as conn:
        q = conn.execute(
            "SELECT * FROM data_quality_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        rejects = conn.execute(
            """SELECT stage, symbol, reasons_json, created_at
                 FROM candidate_audit
                WHERE date=? AND accepted=0
                ORDER BY id DESC LIMIT 20""",
            (_today(),),
        ).fetchall()
        providers = conn.execute(
            """SELECT provider, ok_count, fail_count, score, updated_at
                 FROM provider_reliability
                WHERE date=?
                ORDER BY provider""",
            (_today(),),
        ).fetchall()
    return {
        "snapshot": dict(q) if q else {},
        "recent_rejections": [dict(r) for r in rejects],
        "providers": [dict(r) for r in providers],
    }
