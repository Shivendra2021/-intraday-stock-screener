"""
modules/cost_model.py — Unified NSE Statutory Cost & Fee Calculator.

Calculates exact statutory transaction costs for NSE Intraday Equity:
- Brokerage: Default discount broker min(₹20, 0.03% turnover per order leg)
- STT (Securities Transaction Tax): 0.025% on SELL turnover only
- Exchange Turnover Fees: 0.00297% on both BUY and SELL turnover
- SEBI Charges: ₹10 per crore (0.0001%) on both BUY and SELL turnover
- Stamp Duty: 0.003% on BUY turnover only
- GST: 18% on (Brokerage + Exchange Turnover Fees + SEBI Charges)
"""
from __future__ import annotations

import math
from typing import Any, Dict

COST_MODEL_VERSION = "cost_v2_statutory_nse"


def calculate_intraday_costs(
    entry_price: float,
    exit_price: float,
    quantity: int,
    brokerage_per_order: float = 20.0,
    brokerage_pct: float = 0.03,  # 0.03% max
) -> Dict[str, Any]:
    """
    Compute itemized statutory transaction costs for an intraday round-trip.
    """
    if entry_price <= 0 or exit_price <= 0 or quantity <= 0:
        return {
            "version": COST_MODEL_VERSION,
            "entry_turnover": 0.0,
            "exit_turnover": 0.0,
            "total_turnover": 0.0,
            "brokerage": 0.0,
            "stt": 0.0,
            "turnover_fee": 0.0,
            "sebi_fee": 0.0,
            "stamp_duty": 0.0,
            "gst": 0.0,
            "total_charges": 0.0,
            "cost_bps": 0.0,
            "cost_pct": 0.0,
            "gross_pnl": 0.0,
            "net_pnl": 0.0,
            "net_return_pct": 0.0,
        }

    buy_turnover = entry_price * quantity
    sell_turnover = exit_price * quantity
    total_turnover = buy_turnover + sell_turnover

    # Brokerage: min(flat 20, 0.03%) on each leg
    buy_brokerage = min(brokerage_per_order, buy_turnover * (brokerage_pct / 100.0))
    sell_brokerage = min(brokerage_per_order, sell_turnover * (brokerage_pct / 100.0))
    brokerage = round(buy_brokerage + sell_brokerage, 2)

    # STT: 0.025% on sell leg for intraday equity
    stt = round(sell_turnover * 0.00025, 2)

    # Exchange turnover charge (NSE): 0.00297% on both legs
    turnover_fee = round(total_turnover * 0.0000297, 2)

    # SEBI turnover charges: ₹10 per crore (0.0001%)
    sebi_fee = round(total_turnover * 0.000001, 2)

    # Stamp duty: 0.003% on buy leg
    stamp_duty = round(buy_turnover * 0.00003, 2)

    # GST: 18% on (brokerage + turnover_fee + sebi_fee)
    gst = round((brokerage + turnover_fee + sebi_fee) * 0.18, 2)

    total_charges = round(brokerage + stt + turnover_fee + sebi_fee + stamp_duty + gst, 2)
    cost_bps = round((total_charges / buy_turnover) * 10000.0, 2)
    cost_pct = round(total_charges / buy_turnover * 100.0, 4)

    gross_pnl = round(sell_turnover - buy_turnover, 2)
    net_pnl = round(gross_pnl - total_charges, 2)
    net_return_pct = round((net_pnl / buy_turnover) * 100.0, 4)

    return {
        "version": COST_MODEL_VERSION,
        "entry_turnover": round(buy_turnover, 2),
        "exit_turnover": round(sell_turnover, 2),
        "total_turnover": round(total_turnover, 2),
        "brokerage": brokerage,
        "stt": stt,
        "turnover_fee": turnover_fee,
        "sebi_fee": sebi_fee,
        "stamp_duty": stamp_duty,
        "gst": gst,
        "total_charges": total_charges,
        "cost_bps": cost_bps,
        "cost_pct": cost_pct,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "net_return_pct": net_return_pct,
    }


def get_effective_cost_bps(
    entry_price: float,
    expected_exit_price: float | None = None,
    capital_per_trade: float = 100000.0,
) -> float:
    """
    Calculate effective cost in basis points for standard position sizing.
    """
    if entry_price <= 0:
        return 16.0  # Conservative default ~16 bps

    exit_price = expected_exit_price or entry_price
    qty = max(1, int(capital_per_trade / entry_price))
    costs = calculate_intraday_costs(entry_price, exit_price, qty)
    return costs["cost_bps"]
