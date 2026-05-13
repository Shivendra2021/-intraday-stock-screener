"""Record why morning candidates did not make the final tracker list."""

from __future__ import annotations

import json
import os
from typing import Any

from modules.time_utils import now_ist, today_ist_str

AUDIT_FILE = "data/morning_rejections.jsonl"


def _score(row: dict[str, Any]) -> float:
    try:
        return float(row.get("terminal_score", row.get("score", 0)) or 0)
    except Exception:
        return 0.0


def _reason(row: dict[str, Any]) -> str:
    reasons = row.get("terminal_reasons") or []
    if isinstance(reasons, list) and reasons:
        return "; ".join(str(x) for x in reasons[:4])
    if row.get("edge_reject_reason"):
        return str(row.get("edge_reject_reason"))
    if row.get("reject_reason"):
        return str(row.get("reject_reason"))
    if _score(row) < 50:
        return "lower relative tracker score"
    return "outside final top 5"


def write_rejection_audit(candidates: list[dict[str, Any]], final: list[dict[str, Any]], stage: str = "morning") -> dict[str, Any]:
    final_symbols = {str(row.get("symbol", "")).upper() for row in final}
    rejected = []
    for row in candidates:
        symbol = str(row.get("symbol", "")).upper()
        if not symbol or symbol in final_symbols:
            continue
        rejected.append({
            "symbol": symbol,
            "score": _score(row),
            "confidence_grade": row.get("confidence_grade"),
            "market_regime": row.get("market_regime"),
            "sector": row.get("sector"),
            "reason": _reason(row),
        })

    payload = {
        "timestamp": now_ist().isoformat(timespec="seconds"),
        "date": today_ist_str(),
        "stage": stage,
        "candidate_count": len(candidates),
        "final_count": len(final),
        "rejected_count": len(rejected),
        "rejected": sorted(rejected, key=lambda x: x.get("score", 0), reverse=True)[:50],
    }
    os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
    with open(AUDIT_FILE, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return payload
