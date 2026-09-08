# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
picker.py — Convert analyzer output to final top-5 picks with entry/SL/target.
"""

import sqlite3
import logging
import datetime
import json

from modules.time_utils import now_ist, today_ist_str

logger = logging.getLogger(__name__)


def _calculate_levels(stock: dict) -> dict | None:
    """
    Calculate entry, SL, target, and risk-reward for one stock.
    Returns None if risk-reward < MIN_RISK_REWARD.
    """
    from config import (SL_ATR_MULTIPLIER, MAX_SL_PCT, MIN_RISK_REWARD,
                        MIN_TARGET_MOVE_PCT, MAX_TARGET_MOVE_PCT)

    price = stock["price"]
    atr   = stock["atr"]

    # Stop Loss: ATR-based, capped at MAX_SL_PCT
    sl_atr  = price - (atr * SL_ATR_MULTIPLIER)
    sl_pct  = price * (1 - MAX_SL_PCT / 100)
    sl_price = max(sl_atr, sl_pct)  # tighter of two

    # Target: random in configured range for realistic expectation
    # Deterministic middle of configured range (better than random)
    move_pct     = (MIN_TARGET_MOVE_PCT + MAX_TARGET_MOVE_PCT) / 2
    target_price = price * (1 + move_pct / 100)

    risk   = price - sl_price
    reward = target_price - price

    if risk <= 0:
        return None

    rr = reward / risk
    if rr < MIN_RISK_REWARD:
        return None

    upside_pct = (target_price - price) / price * 100

    return {
        **stock,
        "entry_price":  round(price, 2),
        "sl_price":     round(sl_price, 2),
        "target_price": round(target_price, 2),
        "upside_pct":   round(upside_pct, 2),
        "risk_reward":  round(rr, 2),
    }


def _write_picks_to_db(
    picks: list,
    session_type: str = "morning_final",
    is_official_morning: bool = True,
    source_label: str = "official_morning_pipeline",
):
    """Insert picks into the picks table."""
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    today = today_ist_str()
    now   = now_ist().isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        # Clear today's pending picks first (avoid duplicates on re-run)
        conn.execute(
            "DELETE FROM picks WHERE date=? AND status='pending' AND COALESCE(session_type, 'morning_final')=?",
            (today, session_type),
        )
        for i, p in enumerate(picks, start=1):
            conn.execute(
                """INSERT INTO picks
                   (date, rank, symbol, entry_price, sl_price, target_price,
                    confidence, signal_reasons, status, created_at, pattern_key,
                    validated_price, price_validation_status, edge_status, grok_review,
                    session_type, is_official_morning, source_label, data_quality_score,
                    provider_reliability_score, similarity_score, agreement_score,
                    confidence_delta, quality_reasons)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (today, i, p["symbol"], p["entry_price"], p["sl_price"],
                 p["target_price"], p["score"], p.get("signal_reasons", ""), now,
                 p.get("pattern_key", ""), p.get("validated_price"),
                 p.get("price_validation_status", ""), p.get("edge_status", ""),
                 p.get("grok_review", ""), session_type, 1 if is_official_morning else 0,
                 source_label, p.get("data_quality_score"), p.get("provider_reliability_score"),
                 p.get("similarity_score"), p.get("agreement_score"), p.get("confidence_delta", 0),
                 p.get("quality_reasons", ""))
            )
        conn.commit()
    logger.info("Wrote %s picks to DB for %s session=%s official=%s", len(picks), today, session_type, is_official_morning)


def _attach_price_validation(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    from modules.price_validation import validate_price

    accepted = []
    rejected = []
    for stock in candidates:
        validation = validate_price(stock["symbol"], stock.get("entry_price") or stock.get("price"))
        enriched = {
            **stock,
            "price_validation": validation,
            "validated_price": validation.get("consensus_price"),
            "price_validation_status": validation.get("status"),
        }
        if validation.get("status") == "passed":
            if validation.get("consensus_price"):
                enriched["entry_price"] = round(validation["consensus_price"], 2)
            accepted.append(enriched)
        else:
            enriched["reject_reason"] = f"price validation: {validation.get('details')}"
            rejected.append(enriched)
    return accepted, rejected


def _grok_review_evidence_pack(candidates: list[dict], rejected: list[dict]) -> str:
    try:
        from modules.grok_brain import review_event
    except Exception:
        return ""

    evidence = []
    for c in candidates[:20]:
        edge = c.get("edge", {})
        validation = c.get("price_validation", {})
        evidence.append({
            "symbol": c.get("symbol"),
            "score": c.get("score"),
            "pattern_key": c.get("pattern_key"),
            "edge_status": c.get("edge_status"),
            "hit_rate": edge.get("hit_rate"),
            "backtest_trades": edge.get("total_trades"),
            "avg_return": edge.get("avg_return"),
            "price_validation": validation.get("status"),
            "sources_ok": validation.get("sources_ok"),
            "spread_pct": validation.get("spread_pct"),
            "rsi": c.get("rsi"),
            "ema_alignment": c.get("ema_alignment"),
            "vol_ratio": c.get("vol_ratio"),
            "signal_reasons": c.get("signal_reasons"),
        })

    review = review_event(
        "top20_candidate_evidence_before_final_picks",
        {
            "candidate_count": len(candidates),
            "rejected_count": len(rejected),
            "evidence": evidence,
            "rejected_summary": [
                {
                    "symbol": r.get("symbol"),
                    "reason": r.get("reject_reason") or r.get("edge_reject_reason"),
                    "pattern_key": r.get("pattern_key"),
                }
                for r in rejected[:20]
            ],
        },
    )
    if not review.get("ok"):
        return ""

    summary = (
        f"Verdict={review.get('verdict', 'reviewed')}; "
        f"Risk={review.get('risk_level', 'unknown')}; "
        f"Review={review.get('brief_review', '')}; "
        f"Next={review.get('next_action', '')}"
    )[:900]

    try:
        from config import DB_PATH
        from modules.db_migrations import ensure_research_tables

        ensure_research_tables()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """INSERT INTO grok_evidence_reviews
                   (date, event_type, candidate_count, verdict, risk_level,
                    brief_review, next_action, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    today_ist_str(),
                    "top20_candidate_evidence_before_final_picks",
                    len(candidates),
                    str(review.get("verdict", ""))[:80],
                    str(review.get("risk_level", ""))[:40],
                    str(review.get("brief_review", ""))[:500],
                    str(review.get("next_action", ""))[:300],
                    now_ist().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
    except Exception as e:
        logger.debug("Could not persist Grok evidence review: %s", e)

    return summary


def run_picker(analyzed: list = None) -> list:
    """
    Main picker pipeline.
    1. Takes analyzer output (or runs analyzer if not provided)
    2. Filters by risk-reward
    3. Returns top-5 picks
    4. Writes to DB
    """
    from config import TOP_N_PICKS
    from modules.db_migrations import ensure_research_tables
    from modules.quality_gates import audit_candidate, data_quality_snapshot, enrich_candidate

    ensure_research_tables()
    data_quality = data_quality_snapshot("picker_start")

    if analyzed is None:
        from modules.analyzer import analyze_all
        analyzed = analyze_all()

    if not analyzed:
        logger.warning("No analyzed stocks available for picker")
        return []

    # Take top 20 by score
    candidates = analyzed[:20]
    logger.info(f"Picker evaluating {len(candidates)} candidates")
    for stock in candidates:
        audit_candidate("candidate_pool", stock, True, "entered_top20_picker_pool")

    # Apply risk-reward filter
    valid = []
    for stock in candidates:
        result = _calculate_levels(stock)
        if result:
            valid.append(result)
            audit_candidate("risk_reward", result, True, "rr_passed")
        else:
            audit_candidate("risk_reward", stock, False, "rr_below_minimum_or_invalid_levels")

    if not valid:
        logger.warning("No picks passed risk-reward filter")
        return []

    # Cross-check price from Yahoo + NSE + broker if configured.
    valid, price_rejected = _attach_price_validation(valid)
    for item in valid:
        audit_candidate("price_validation", item, True, "price_validation_passed")
    for item in price_rejected:
        audit_candidate("price_validation", item, False, item.get("reject_reason", "price_validation_failed"))
    if not valid:
        logger.warning("No picks passed cross-source price validation: %s", len(price_rejected))
        return []

    # Only allow patterns with proven edge in the backtest table.
    from modules.pattern_backtester import filter_candidates_by_edge
    valid, edge_rejected = filter_candidates_by_edge(valid)
    rejected = price_rejected + edge_rejected
    for item in valid:
        audit_candidate("pattern_edge", item, True, "proven_edge_passed")
    for item in edge_rejected:
        audit_candidate("pattern_edge", item, False, item.get("edge_reject_reason", "proven_edge_failed"))
    if not valid:
        logger.warning("No picks passed proven-edge pattern gate: %s rejected", len(rejected))
        return []

    grok_review = _grok_review_evidence_pack(valid, rejected)
    if grok_review:
        for item in valid:
            item["grok_review"] = grok_review

    try:
        from modules.market_terminal import rank_candidates

        valid = rank_candidates(valid)
        for item in valid:
            item["score"] = item.get("terminal_score", item.get("score", 0))
    except Exception as exc:
        logger.debug("Terminal ranking skipped in picker: %s", exc)
        valid.sort(key=lambda x: x["score"], reverse=True)

    enriched_valid = []
    for item in valid:
        enriched = enrich_candidate(item, data_quality=data_quality)
        enriched_valid.append(enriched)
        audit_candidate("quality_scoring", enriched, True, enriched.get("quality_reasons", "quality_scored"))
    valid = sorted(enriched_valid, key=lambda x: x.get("score", 0), reverse=True)

    # Take top N
    top_picks = valid[:TOP_N_PICKS]
    selected_symbols = {p.get("symbol") for p in top_picks}
    for item in valid[TOP_N_PICKS:]:
        audit_candidate("final_selection", item, False, "ranked_below_top5_after_quality_scoring")

    for i, pick in enumerate(top_picks, start=1):
        pick["rank"] = i
        audit_candidate("final_selection", pick, True, f"selected_rank_{i}")

    # Write to DB
    _write_picks_to_db(top_picks)

    logger.info(f"Final picks: {[p['symbol'] for p in top_picks]}")
    return top_picks


def get_todays_picks() -> list:
    """Fetch today's picks from DB."""
    from config import DB_PATH
    today = today_ist_str()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM picks WHERE date=? AND COALESCE(session_type, 'morning_final')='morning_final' "
            "AND COALESCE(is_official_morning, 1)=1 ORDER BY rank",
            (today,),
        ).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    picks = run_picker()
    for p in picks:
        print(f"#{p['rank']} {p['symbol']:12} Entry={p['entry_price']:.2f}  "
              f"SL={p['sl_price']:.2f}  Target={p['target_price']:.2f}  "
              f"RR={p['risk_reward']:.1f}  Score={p['score']:.1f}")
