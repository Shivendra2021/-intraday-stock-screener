import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import intraday_pattern_agent as agent


class TestIntradayPatternAgent(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "symbol": "TEST",
            "sector": "General Industrials",
            "theme": "DEFENCE_INFRA",
            "current_price": 110.0,
            "open_price": 104.0,
            "prev_close": 100.0,
            "gap_pct": 4.0,
            "change_pct": 10.0,
            "volume_ratio": 6.0,
            "volume_15_ratio": 4.0,
            "avg_daily_volume_inr": 2_00_00_000,
            "market_cap_cr": 900.0,
            "weekly_change_pct": 6.0,
            "prev_day_upper_circuit": 104.0,
            "price_9_15": 104.0,
            "price_9_30": 108.0,
            "range_high_09_15_10_00": 109.0,
            "range_low_09_15_10_00": 102.0,
            "avg_volume_per_min": 1000.0,
            "current_volume": 8000.0,
            "upper_circuit_price": 120.0,
            "prev_day_change_pct": 3.0,
        }
        row.update(overrides)
        return row

    def test_confidence_score_tier_1_components(self):
        rows = [self._row(symbol="TEST"), self._row(symbol="P1"), self._row(symbol="P2"), self._row(symbol="P3")]
        context = {"nifty_up": True, "smallcap_index_up": True}
        score = agent.confidence_score(rows[0], rows, context)
        self.assertGreaterEqual(score, 80)

    def test_gap_and_go_classifies_in_gap_window(self):
        row = self._row(gap_pct=8.0)
        rows = [row, self._row(symbol="P1", change_pct=2), self._row(symbol="P2", change_pct=1), self._row(symbol="P3", change_pct=1)]
        now = dt.datetime.combine(dt.date.today(), dt.time(9, 35))
        self.assertEqual(agent.classify_pattern(row, rows, now=now), "GAP_AND_GO")

    def test_mandatory_filter_reports_missing_market_tailwind(self):
        rows = [self._row(symbol="TEST"), self._row(symbol="P1"), self._row(symbol="P2"), self._row(symbol="P3")]
        passed, labels, failed = agent.mandatory_filter(rows[0], rows, {"market_tailwind": False})
        self.assertFalse(passed)
        self.assertIn("market_tailwind", failed)
        self.assertIn("micro_small_cap", labels)


if __name__ == "__main__":
    unittest.main()
