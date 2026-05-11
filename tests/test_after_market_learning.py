import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.after_market_learning import extract_winner_features, learn_similarities, run_after_market_learning
import modules.fetch
import modules.news


def _sample_df(open_last=100, high_last=108, close_last=106):
    rows = 60
    data = {
        "open": [90 + i * 0.1 for i in range(rows - 1)] + [open_last],
        "high": [91 + i * 0.1 for i in range(rows - 1)] + [high_last],
        "low": [89 + i * 0.1 for i in range(rows - 1)] + [99],
        "close": [90.5 + i * 0.1 for i in range(rows - 1)] + [close_last],
        "volume": [100000 for _ in range(rows - 1)] + [250000],
    }
    return pd.DataFrame(data)


class TestAfterMarketLearning(unittest.TestCase):
    def test_extract_winner_features_detects_7pct_open_to_high(self):
        with patch("modules.fetch.fetch_ohlcv", return_value=_sample_df()), \
             patch("modules.news.get_stock_sentiment", return_value=0.25):
            feature = extract_winner_features("TCS", min_return_pct=7.0)
        self.assertIsNotNone(feature)
        self.assertEqual(feature["symbol"], "TCS")
        self.assertGreaterEqual(feature["return_pct"], 7.0)
        self.assertIn("pattern_key", feature)
        self.assertIn("volume_ratio", feature)

    def test_extract_winner_features_rejects_small_moves(self):
        with patch("modules.fetch.fetch_ohlcv", return_value=_sample_df(high_last=103, close_last=102)), \
             patch("modules.news.get_stock_sentiment", return_value=0):
            feature = extract_winner_features("TCS", min_return_pct=7.0)
        self.assertIsNone(feature)

    def test_learn_similarities_finds_common_rules(self):
        features = [
            {"symbol": "A", "return_pct": 8, "volume_ratio": 2.2, "gap_pct": 2.1, "rsi": 58, "adx": 28, "ema_alignment": "EMA_full_bull", "sector": "IT", "pattern_key": "K1"},
            {"symbol": "B", "return_pct": 9, "volume_ratio": 2.5, "gap_pct": 2.4, "rsi": 60, "adx": 30, "ema_alignment": "EMA_full_bull", "sector": "IT", "pattern_key": "K1"},
            {"symbol": "C", "return_pct": 7.5, "volume_ratio": 1.1, "gap_pct": 0.2, "rsi": 45, "adx": 18, "ema_alignment": "EMA_bear", "sector": "Auto", "pattern_key": "K2"},
        ]
        patterns = learn_similarities(features, min_support=2)
        keys = {p["pattern_key"] for p in patterns}
        self.assertIn("pattern_key:K1", keys)
        self.assertIn("sector:IT", keys)
        self.assertIn("volume_ratio:>=2.0", keys)

    def test_run_after_market_learning_stores_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "history.db")
            json_path = os.path.join(tmp, "patterns.json")
            with patch("config.DB_PATH", db_path), \
                 patch("modules.after_market_learning.LEARNED_PATTERNS_JSON", json_path), \
                 patch("modules.after_market_learning.extract_winner_features", side_effect=[
                     {"symbol": "A", "return_pct": 8, "open_to_high_pct": 8, "open_to_close_pct": 6, "volume_ratio": 2.2, "gap_pct": 2, "rsi": 58, "adx": 28, "ema_alignment": "EMA_full_bull", "sector": "IT", "pattern_key": "K1"},
                     {"symbol": "B", "return_pct": 9, "open_to_high_pct": 9, "open_to_close_pct": 7, "volume_ratio": 2.4, "gap_pct": 2.3, "rsi": 60, "adx": 30, "ema_alignment": "EMA_full_bull", "sector": "IT", "pattern_key": "K1"},
                 ]):
                result = run_after_market_learning(symbols=["A", "B"], min_return_pct=7.0)
            self.assertTrue(result["success"])
            self.assertEqual(result["winner_count"], 2)
            conn = sqlite3.connect(db_path)
            try:
                count = conn.execute("SELECT COUNT(*) FROM after_market_winner_features").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 2)
            self.assertTrue(os.path.exists(json_path))


if __name__ == "__main__":
    unittest.main()
