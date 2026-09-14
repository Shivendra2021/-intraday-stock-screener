"""Deterministic candidate review contract for Quant V3.

The review is a ledger of verifiable facts.  It never asks an LLM to select,
approve, or veto an intraday candidate.
"""
from __future__ import annotations


def review(row, *, model_ready, quote_reason=None, loss_count=0, selected=0,
           in_window=False, market_context=None):
    from config import QUANT_MAX_PICKS
    gates = {
        "data": {"pass": quote_reason in (None, "eligible"), "reason": quote_reason or "not_checked"},
        "probability": {"pass": bool(model_ready and row.get("p7") is not None and row.get("expected_net_pct") is not None),
                        "p7": row.get("p7"), "p10": row.get("p10"),
                        "expected_net_pct": row.get("expected_net_pct"), "model_id": row.get("model_id")},
        "context": {"pass": True, "sector": row.get("sector", "Unknown"),
                    "market_snapshot_at": (market_context or {}).get("fetched_at")},
        "risk": {"pass": loss_count < 2 and selected < QUANT_MAX_PICKS,
                 "loss_count": loss_count, "selected": selected, "max_candidates": QUANT_MAX_PICKS},
        "timing": {"pass": bool(in_window), "entry_ts": row.get("entry_ts"), "signal_ts": row.get("ts")},
    }
    failures = [name for name, result in gates.items() if not result["pass"]]
    if not model_ready:
        decision = "watchlist"
        reason = "model_collecting_evidence"
    elif not in_window:
        decision = "watchlist"
        reason = "outside_confirmation_window"
    elif quote_reason != "eligible":
        decision = "rejected"
        reason = quote_reason or "quote_not_checked"
    elif loss_count >= 2:
        decision = "rejected"
        reason = "daily_loss_guard"
    elif selected >= QUANT_MAX_PICKS:
        decision = "watchlist"
        reason = "qualified_slots_full"
    else:
        decision = "qualified"
        reason = "all_deterministic_gates_passed"
    return {"decision": decision, "reason": reason, "gates": gates,
            "failed_gates": failures, "feature_version": row.get("feature_version")}
