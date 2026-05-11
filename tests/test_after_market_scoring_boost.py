import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.stock_selector import _after_market_pattern_boost


class TestAfterMarketScoringBoost(unittest.TestCase):
    def test_after_market_pattern_boost_matches_rules(self):
        patterns = [
            {"pattern_key": "volume_ratio:>=2.0", "confidence": 0.8, "rules": {"volume_ratio": ">=2.0"}},
            {"pattern_key": "rsi:55-75", "confidence": 0.75, "rules": {"rsi": "55-75"}},
        ]
        candidate = {"vol_ratio": 2.3, "rsi": 60, "adx": 20, "gap_up": 0}
        with patch("modules.after_market_learning.get_after_market_patterns", return_value=patterns):
            boost, reasons = _after_market_pattern_boost(candidate)
        self.assertGreater(boost, 0)
        self.assertEqual(len(reasons), 2)

    def test_after_market_pattern_boost_ignores_low_confidence(self):
        patterns = [{"pattern_key": "volume_ratio:>=2.0", "confidence": 0.2, "rules": {"volume_ratio": ">=2.0"}}]
        with patch("modules.after_market_learning.get_after_market_patterns", return_value=patterns):
            boost, reasons = _after_market_pattern_boost({"vol_ratio": 3.0})
        self.assertEqual(boost, 0)
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
