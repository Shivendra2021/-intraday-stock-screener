import pandas as pd
import pytest
from modules.cost_model import calculate_intraday_costs, get_effective_cost_bps, COST_MODEL_VERSION
from modules.slippage_model import calculate_dynamic_slippage, SLIPPAGE_MODEL_VERSION
from modules.quant_outcomes import evaluate


def test_statutory_cost_model_calculation():
    # Buy ₹1,00,000 worth of stock at ₹500 (200 shares) and sell at ₹510
    entry_px = 500.0
    exit_px = 510.0
    qty = 200

    costs = calculate_intraday_costs(entry_px, exit_px, qty)
    assert costs["version"] == COST_MODEL_VERSION
    assert costs["entry_turnover"] == 100000.0
    assert costs["exit_turnover"] == 102000.0

    # STT: 0.025% on sell leg = 102000 * 0.00025 = ₹25.50
    assert costs["stt"] == 25.50

    # Stamp duty: 0.003% on buy leg = 100000 * 0.00003 = ₹3.00
    assert costs["stamp_duty"] == 3.00

    # Brokerage: min(20, 100000 * 0.0003 = 30) = 20 on buy, min(20, 102000 * 0.0003 = 30.6) = 20 on sell -> 40.0
    assert costs["brokerage"] == 40.0

    # GST on (brokerage + turnover_fee + sebi_fee)
    assert costs["gst"] > 0
    assert costs["total_charges"] > 68.50
    assert costs["cost_bps"] > 0
    assert costs["gross_pnl"] == 2000.0
    assert costs["net_pnl"] < 2000.0


def test_dynamic_slippage_model():
    # Liquid stock with 0.04% spread
    res = calculate_dynamic_slippage(spread_pct=0.04, rvol=1.5, atr_pct=2.0, turnover=100_000_000)
    assert res["version"] == SLIPPAGE_MODEL_VERSION
    # 0.04% spread -> half is 0.02% = 2.0 bps, bounded by min 3.0 bps
    assert res["slippage_bps"] == 3.0

    # High RVOL breakout with lower turnover
    res2 = calculate_dynamic_slippage(spread_pct=0.10, rvol=3.5, atr_pct=4.5, turnover=30_000_000)
    # base = 5.0 bps (0.10% / 2 * 100)
    # rvol impact = (3.5 - 2.5) * 0.8 = 0.8 bps
    # turnover impact = 2.0 bps
    # atr impact = 1.0 bps
    # total = 8.8 bps
    assert res2["slippage_bps"] == 8.8


def candles_1m(start_str, data):
    start = pd.Timestamp(start_str, tz="Asia/Kolkata")
    idx = pd.date_range(start, periods=len(data), freq="1min")
    return pd.DataFrame(data, index=idx, columns=["open", "high", "low", "close", "volume"])


def test_outcomes_1m_resolution():
    row = {
        "symbol": "TEST",
        "date": "2026-08-31",
        "ts": int(pd.Timestamp("2026-08-31 09:34", tz="Asia/Kolkata").timestamp()),
        "entry_ts": int(pd.Timestamp("2026-08-31 09:35", tz="Asia/Kolkata").timestamp()),
        "price": 100.0,
        "stop": 98.0,
        "spread_pct": 0.04,
        "rvol": 2.0,
    }

    # 10 bars of 1-minute data:
    # 09:35: open 100, high 101, low 99.5, close 100.5
    # 09:36: open 100.5, high 108.0 (hits TP1 at 107!), low 100.0, close 107.5
    bars = candles_1m("2026-08-31 09:35", [
        [100, 101, 99.5, 100.5, 1000],
        [100.5, 108.0, 100.0, 107.5, 2000],
        [107.5, 111.0, 107.0, 110.5, 3000],  # hits TP2 at 110!
    ])

    out = evaluate(row, bars, cutoff="15:20", interval="1m")
    assert out["resolved"] is True
    assert out["execution_resolution"] == "1m"
    assert out["hit7"] == 1
    assert out["hit10"] == 1
    assert out["status"] == "target_exit"
    assert out["cost_model_version"] == COST_MODEL_VERSION
    assert out["slippage_model_version"] == SLIPPAGE_MODEL_VERSION
