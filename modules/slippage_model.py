"""
modules/slippage_model.py — Dynamic Point-in-Time Slippage Model.

Calculates realistic execution slippage based on:
- Bid-ask spread percentage (primary driver: half-spread)
- Relative Volume (RVOL) market surge impact
- Stock turnover / liquidity tier
- Intraday volatility (ATR %)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

SLIPPAGE_MODEL_VERSION = "slip_v2_dynamic"


def calculate_dynamic_slippage(
    spread_pct: Optional[float] = None,
    rvol: Optional[float] = None,
    atr_pct: Optional[float] = None,
    turnover: Optional[float] = None,
    base_fallback_bps: float = 5.0,
) -> Dict[str, Any]:
    """
    Calculate dynamic slippage in basis points.
    Conservative bounds: [3.0 bps, 30.0 bps].
    """
    if spread_pct is not None and spread_pct > 0:
        # Half the bid-ask spread expressed in basis points (1% = 100 bps)
        base_bps = (spread_pct / 2.0) * 100.0
    else:
        base_bps = base_fallback_bps

    impact_bps = 0.0

    # High RVOL surge (surging market orders consuming top-of-book depth)
    if rvol is not None and rvol > 2.5:
        impact_bps += min(2.5, (rvol - 2.5) * 0.8)

    # Low turnover liquidity penalty (turnover < ₹5 Crore)
    if turnover is not None and 0 < turnover < 50_000_000:
        impact_bps += 2.0

    # High volatility expansion penalty (ATR > 4%)
    if atr_pct is not None and atr_pct > 4.0:
        impact_bps += 1.0

    total_bps = base_bps + impact_bps
    # Cap between 3.0 bps (extremely liquid) and 30.0 bps (worst case)
    final_bps = round(max(3.0, min(30.0, total_bps)), 2)

    return {
        "version": SLIPPAGE_MODEL_VERSION,
        "slippage_bps": final_bps,
        "spread_component_bps": round(base_bps, 2),
        "impact_component_bps": round(impact_bps, 2),
        "slip_multiplier": round(final_bps / 10000.0, 6),
    }
