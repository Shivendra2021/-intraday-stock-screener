import unittest
import sqlite3
import pandas as pd
import numpy as np

from modules.stock_selector import (
    _calc_weekly_trend,
    _calc_close_location_value,
    _calc_spread_to_atr_ratio,
    _calc_macro_alignment_score,
)
from modules.paper_portfolio import allocate_for_date
from modules.picker import _compute_correlation_matrix, run_picker


class TestStockSelectorSignals(unittest.TestCase):
    def test_close_location_value(self):
        # price at high -> 1.0
        self.assertEqual(_calc_close_location_value(100.0, 100.0, 90.0), 1.0)
        # price at low -> 0.0
        self.assertEqual(_calc_close_location_value(90.0, 100.0, 90.0), 0.0)
        # price at midpoint -> 0.5
        self.assertEqual(_calc_close_location_value(95.0, 100.0, 90.0), 0.5)
        # invalid high/low -> fallback 0.5
        self.assertEqual(_calc_close_location_value(100.0, 90.0, 100.0), 0.5)

    def test_spread_to_atr_ratio(self):
        # spread 1.0 on ATR 100.0 -> 0.01 (1%)
        self.assertAlmostEqual(_calc_spread_to_atr_ratio(99.0, 100.0, 100.0), 0.01)
        # invalid values -> 0.0
        self.assertEqual(_calc_spread_to_atr_ratio(0.0, 0.0, 10.0), 0.0)

    def test_weekly_trend(self):
        # Create synthetic daily data with an upward trend over 60 days
        dates = pd.date_range(start="2025-01-01", periods=60, freq="B")
        prices = [100.0 + i * 2.0 for i in range(60)]
        df = pd.DataFrame({"close": prices}, index=dates)
        trend = _calc_weekly_trend(df)
        self.assertEqual(trend, "bull")

        # Downward trend
        prices_down = [200.0 - i * 2.0 for i in range(60)]
        df_down = pd.DataFrame({"close": prices_down}, index=dates)
        trend_down = _calc_weekly_trend(df_down)
        self.assertEqual(trend_down, "bear")

    def test_macro_alignment_with_weekly(self):
        label, score = _calc_macro_alignment_score(price=110, ema200=100, vwap=105, weekly_trend="bull")
        self.assertIn("weekly_bull", label)
        self.assertGreaterEqual(score, 1.0)

        label_bear, score_bear = _calc_macro_alignment_score(price=90, ema200=100, vwap=95, weekly_trend="bear")
        self.assertIn("full_bear", label_bear)
        self.assertEqual(score_bear, 0.0)


class TestPaperPortfolioRiskParity(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        # Create minimal tables
        self.conn.execute("""
            CREATE TABLE paper_account (
                id INTEGER PRIMARY KEY,
                initial_cash REAL,
                cash_balance REAL,
                realized_pnl REAL,
                updated_at TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE paper_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pick_id INTEGER UNIQUE,
                date TEXT,
                symbol TEXT,
                entry_price REAL,
                sl_price REAL,
                target_price REAL,
                confidence REAL,
                allocation REAL,
                quantity REAL,
                invested_amount REAL,
                status TEXT DEFAULT 'open',
                exit_price REAL,
                exit_date TEXT,
                realized_pnl REAL DEFAULT 0,
                return_pct REAL DEFAULT 0,
                created_at TEXT,
                closed_at TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE picks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                rank INTEGER,
                symbol TEXT,
                entry_price REAL,
                sl_price REAL,
                target_price REAL,
                confidence REAL,
                status TEXT DEFAULT 'open',
                session_type TEXT,
                is_official_morning INTEGER DEFAULT 1
            )
        """)
        self.conn.execute(
            "INSERT INTO paper_account VALUES (1, 100000.0, 100000.0, 0, '2026-09-14')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_risk_parity_allocation(self):
        from unittest.mock import patch
        # Insert 2 picks
        # Pick 1: entry=100, sl=90 -> risk/sh=10. Cash=100,000, 2% risk = 2,000. Target qty = 200.
        # Cost = 200 * 100 = 20,000 <= 35% cap (35,000).
        self.conn.execute("""
            INSERT INTO picks (date, rank, symbol, entry_price, sl_price, target_price, confidence)
            VALUES ('2026-09-14', 1, 'STOCKA', 100.0, 90.0, 110.0, 0.9)
        """)
        # Pick 2: entry=500, sl=495 -> risk/sh=5. Cash risk = 2,000. Target qty = 400.
        # 400 * 500 = 200,000 > 35% cap (35,000). So capped at 35,000 -> qty = 70 shares.
        self.conn.execute("""
            INSERT INTO picks (date, rank, symbol, entry_price, sl_price, target_price, confidence)
            VALUES ('2026-09-14', 2, 'STOCKB', 500.0, 495.0, 520.0, 0.8)
        """)
        self.conn.commit()

        with patch("modules.paper_portfolio._connect", return_value=self.conn):
            res = allocate_for_date("2026-09-14")
            self.assertEqual(res["positions"], 2)

            positions = self.conn.execute("SELECT * FROM paper_positions ORDER BY id").fetchall()
            self.assertEqual(len(positions), 2)

            # STOCKA: qty=200, invested=20,000
            p1 = positions[0]
            self.assertEqual(p1["symbol"], "STOCKA")
            self.assertEqual(p1["quantity"], 200)
            self.assertEqual(p1["invested_amount"], 20000.0)

            # STOCKB: capped at 35,000 -> qty = 70, invested = 35,000
            p2 = positions[1]
            self.assertEqual(p2["symbol"], "STOCKB")
            self.assertEqual(p2["quantity"], 70)
            self.assertEqual(p2["invested_amount"], 35000.0)


class TestPickerCorrelationGate(unittest.TestCase):
    def test_greedy_correlation_gate(self):
        from unittest.mock import patch

        # 3 candidates:
        # Cand 1: score 90, sector IT, returns series 1
        # Cand 2: score 85, sector IT, returns series identical to 1 (corr = 1.0) -> should be gated out
        # Cand 3: score 80, sector Auto, returns uncorrelated -> should be selected
        series1 = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01, 0.02])
        series2 = pd.Series([0.01, -0.02, 0.03, 0.01, -0.01, 0.02])  # corr=1.0 with series1
        series3 = pd.Series([-0.03, 0.01, -0.02, 0.02, 0.01, -0.01]) # uncorrelated

        cand1 = {"symbol": "INFY", "score": 90, "sector": "IT", "returns": series1, "price": 100.0, "atr": 2.0}
        cand2 = {"symbol": "TCS", "score": 85, "sector": "IT", "returns": series2, "price": 200.0, "atr": 4.0}
        cand3 = {"symbol": "MARUTI", "score": 80, "sector": "Auto", "returns": series3, "price": 300.0, "atr": 6.0}

        candidates = [cand1, cand2, cand3]
        corr_matrix = _compute_correlation_matrix(candidates)
        self.assertIn(("INFY", "TCS"), corr_matrix)
        self.assertAlmostEqual(corr_matrix[("INFY", "TCS")], 1.0, places=2)

        # Mock out external DB writes and validations in run_picker
        with patch("modules.picker._write_picks_to_db"), \
             patch("modules.picker._calculate_levels", side_effect=lambda x: {**x, "entry_price": x["price"], "sl_price": x["price"]-x["atr"], "target_price": x["price"]+x["atr"]*2, "risk_reward": 2.0}), \
             patch("modules.picker._attach_price_validation", side_effect=lambda x: (x, [])), \
             patch("modules.pattern_backtester.filter_candidates_by_edge", side_effect=lambda x: (x, [])), \
             patch("modules.picker._grok_review_evidence_pack", return_value=""), \
             patch("modules.quality_gates.enrich_candidate", side_effect=lambda x, data_quality: x), \
             patch("config.TOP_N_PICKS", 2):

            picks = run_picker(candidates)
            symbols = [p["symbol"] for p in picks]
            # INFY (rank 1) and MARUTI (rank 2) selected; TCS skipped due to corr > 0.70 with INFY!
            self.assertEqual(symbols, ["INFY", "MARUTI"])

    def test_sector_fallback_when_correlation_unavailable(self):
        from unittest.mock import patch
        # Candidates without returns data and batch download failure
        cand1 = {"symbol": "INFY", "score": 90, "sector": "IT", "price": 100.0, "atr": 2.0}
        cand2 = {"symbol": "WIPRO", "score": 85, "sector": "IT", "price": 150.0, "atr": 3.0}
        cand3 = {"symbol": "SUNPHARMA", "score": 80, "sector": "Pharma", "price": 200.0, "atr": 4.0}
        candidates = [cand1, cand2, cand3]

        with patch("modules.picker._compute_correlation_matrix", return_value={}), \
             patch("modules.picker._write_picks_to_db"), \
             patch("modules.picker._calculate_levels", side_effect=lambda x: {**x, "entry_price": x["price"], "sl_price": x["price"]-x["atr"], "target_price": x["price"]+x["atr"]*2, "risk_reward": 2.0}), \
             patch("modules.picker._attach_price_validation", side_effect=lambda x: (x, [])), \
             patch("modules.pattern_backtester.filter_candidates_by_edge", side_effect=lambda x: (x, [])), \
             patch("modules.picker._grok_review_evidence_pack", return_value=""), \
             patch("modules.quality_gates.enrich_candidate", side_effect=lambda x, data_quality: x), \
             patch("config.TOP_N_PICKS", 2):

            picks = run_picker(candidates)
            symbols = [p["symbol"] for p in picks]
            # WIPRO skipped because it's same sector as INFY -> SUNPHARMA picked
            self.assertEqual(symbols, ["INFY", "SUNPHARMA"])

    def test_backfill_when_all_candidates_correlated(self):
        from unittest.mock import patch
        cand1 = {"symbol": "INFY", "score": 90, "sector": "IT", "price": 100.0, "atr": 2.0}
        cand2 = {"symbol": "WIPRO", "score": 85, "sector": "IT", "price": 150.0, "atr": 3.0}
        candidates = [cand1, cand2]

        with patch("modules.picker._compute_correlation_matrix", return_value={}), \
             patch("modules.picker._write_picks_to_db"), \
             patch("modules.picker._calculate_levels", side_effect=lambda x: {**x, "entry_price": x["price"], "sl_price": x["price"]-x["atr"], "target_price": x["price"]+x["atr"]*2, "risk_reward": 2.0}), \
             patch("modules.picker._attach_price_validation", side_effect=lambda x: (x, [])), \
             patch("modules.pattern_backtester.filter_candidates_by_edge", side_effect=lambda x: (x, [])), \
             patch("modules.picker._grok_review_evidence_pack", return_value=""), \
             patch("modules.quality_gates.enrich_candidate", side_effect=lambda x, data_quality: x), \
             patch("config.TOP_N_PICKS", 2):

            picks = run_picker(candidates)
            # Should backfill so we still get 2 picks
            self.assertEqual(len(picks), 2)
            self.assertEqual([p["symbol"] for p in picks], ["INFY", "WIPRO"])


if __name__ == "__main__":
    unittest.main()
