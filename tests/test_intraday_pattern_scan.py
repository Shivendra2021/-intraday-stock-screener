# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
tests/test_intraday_pattern_scan.py — Unit tests for intraday_pattern_scan.py
Usage: python -m unittest tests/test_intraday_pattern_scan.py -v
"""

import unittest
import os
import sys
import glob
import shutil
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUTPUT_DIR = "output/"

EXPECTED_PATTERN_NAMES = [
    "gap_up_2pct",
    "gap_down_reversal",
    "breakout_20d",
    "breakout_55d",
    "near_52w_high",
    "ma_stack",
    "rsi_55_75",
    "adx_strong",
    "vol_spike_1_5x",
    "vol_spike_2x",
    "range_expansion",
    "nr7",
    "vol_compression",
]

EXPECTED_TRAINING_COLS = [
    "symbol", "open", "high", "low", "close", "volume",
    "rsi", "adx", "atr14", "vol_20avg", "label_5pct", "label_6pct",
]


class TestIntradayPatternScan(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Run the scanner with 2y period and 5 stocks before all tests."""
        import subprocess
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        cls.ts_before = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        result = subprocess.run(
            [sys.executable, "-m", "app.research.intraday_pattern_scan",
             "--period", "2y", "--top", "5"],
            capture_output=True, text=True, timeout=300
        )
        cls.stdout = result.stdout
        cls.stderr = result.stderr
        cls.returncode = result.returncode

        # Find output files from this run
        ts_now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        all_files = glob.glob(os.path.join(OUTPUT_DIR, "*.csv")) + \
                    glob.glob(os.path.join(OUTPUT_DIR, "*.md")) + \
                    glob.glob(os.path.join(OUTPUT_DIR, "*.json"))
        cls.run_files = [f for f in all_files if os.path.getmtime(f) >
                         (datetime.datetime.now() - datetime.timedelta(minutes=10)).timestamp()]

    def _get_latest_file(self, suffix: str) -> str | None:
        """Find the most recently created output file with given suffix."""
        pattern = os.path.join(OUTPUT_DIR, f"*{suffix}")
        files = glob.glob(pattern)
        if not files:
            return None
        return max(files, key=os.path.getmtime)

    # ── Test 1: Process completed without crash ───────────────────────────────
    def test_01_scan_completed(self):
        self.assertEqual(self.returncode, 0,
                         f"Scanner exited with code {self.returncode}.\n"
                         f"STDERR: {self.stderr[-500:]}")

    # ── Test 2: All 6 output files created ────────────────────────────────────
    def test_02_stocks_csv_created(self):
        f = self._get_latest_file("_stocks.csv")
        self.assertIsNotNone(f, "stocks.csv not found in output/")
        self.assertGreater(os.path.getsize(f), 0, "stocks.csv is empty")

    def test_03_patterns_csv_created(self):
        f = self._get_latest_file("_patterns.csv")
        self.assertIsNotNone(f, "patterns.csv not found in output/")
        self.assertGreater(os.path.getsize(f), 0, "patterns.csv is empty")

    def test_04_training_rows_csv_created(self):
        f = self._get_latest_file("_training_rows.csv")
        self.assertIsNotNone(f, "training_rows.csv not found in output/")
        self.assertGreater(os.path.getsize(f), 0, "training_rows.csv is empty")

    def test_05_events_csv_created(self):
        f = self._get_latest_file("_events.csv")
        self.assertIsNotNone(f, "events.csv not found in output/")
        # events.csv may be small if no events, but file must exist
        self.assertTrue(os.path.exists(f), "events.csv not found")

    def test_06_summary_md_created(self):
        f = self._get_latest_file("_summary.md")
        self.assertIsNotNone(f, "summary.md not found in output/")
        self.assertGreater(os.path.getsize(f), 50, "summary.md is too small")

    def test_07_meta_json_created(self):
        f = self._get_latest_file("_meta.json")
        self.assertIsNotNone(f, "meta.json not found in output/")
        self.assertGreater(os.path.getsize(f), 0, "meta.json is empty")

    # ── Test 3: patterns.csv has all 13 pattern rows ──────────────────────────
    def test_08_patterns_csv_has_all_13_patterns(self):
        import pandas as pd
        f = self._get_latest_file("_patterns.csv")
        if not f:
            self.skipTest("patterns.csv not found")
        df = pd.read_csv(f)
        self.assertIn("pattern", df.columns, "patterns.csv missing 'pattern' column")
        found = set(df["pattern"].tolist())
        for pat in EXPECTED_PATTERN_NAMES:
            self.assertIn(pat, found,
                          f"Pattern '{pat}' missing from patterns.csv")

    def test_09_patterns_csv_has_lift_column(self):
        import pandas as pd
        f = self._get_latest_file("_patterns.csv")
        if not f:
            self.skipTest("patterns.csv not found")
        df = pd.read_csv(f)
        for col in ["pattern", "n_signals", "hit_rate", "base_rate", "lift"]:
            self.assertIn(col, df.columns,
                          f"patterns.csv missing column '{col}'")

    def test_10_patterns_lift_values_are_positive(self):
        import pandas as pd
        f = self._get_latest_file("_patterns.csv")
        if not f:
            self.skipTest("patterns.csv not found")
        df = pd.read_csv(f)
        if "lift" in df.columns and len(df) > 0:
            self.assertTrue((df["lift"] >= 0).all(),
                            "Some lift values are negative")

    # ── Test 4: training_rows.csv has correct columns ─────────────────────────
    def test_11_training_rows_has_required_columns(self):
        import pandas as pd
        f = self._get_latest_file("_training_rows.csv")
        if not f:
            self.skipTest("training_rows.csv not found")
        df = pd.read_csv(f, nrows=5)
        for col in EXPECTED_TRAINING_COLS:
            self.assertIn(col, df.columns,
                          f"training_rows.csv missing column '{col}'")

    def test_12_training_rows_has_pattern_columns(self):
        import pandas as pd
        f = self._get_latest_file("_training_rows.csv")
        if not f:
            self.skipTest("training_rows.csv not found")
        df = pd.read_csv(f, nrows=5)
        for pat in EXPECTED_PATTERN_NAMES:
            self.assertIn(pat, df.columns,
                          f"training_rows.csv missing pattern column '{pat}'")

    def test_13_training_rows_label_columns_are_boolean(self):
        import pandas as pd
        import numpy as np
        f = self._get_latest_file("_training_rows.csv")
        if not f:
            self.skipTest("training_rows.csv not found")
        df = pd.read_csv(f)
        for col in ["label_5pct", "label_6pct"]:
            if col in df.columns:
                unique_vals = set(df[col].dropna().unique())
                self.assertTrue(
                    unique_vals.issubset({True, False, 0, 1, 0.0, 1.0}),
                    f"Column '{col}' has non-boolean values: {unique_vals}"
                )

    # ── Test 5: meta.json is valid and complete ───────────────────────────────
    def test_14_meta_json_is_valid(self):
        import json
        f = self._get_latest_file("_meta.json")
        if not f:
            self.skipTest("meta.json not found")
        with open(f) as fp:
            meta = json.load(fp)
        for key in ["period", "n_stocks", "n_rows", "runtime_s", "threshold_pct", "patterns"]:
            self.assertIn(key, meta, f"meta.json missing key '{key}'")
        self.assertEqual(len(meta["patterns"]), 13,
                         f"Expected 13 patterns in meta, got {len(meta['patterns'])}")
        self.assertGreater(meta["n_rows"], 0, "meta.n_rows should be > 0")

    # ── Test 6: stocks.csv has correct structure ──────────────────────────────
    def test_15_stocks_csv_structure(self):
        import pandas as pd
        f = self._get_latest_file("_stocks.csv")
        if not f:
            self.skipTest("stocks.csv not found")
        df = pd.read_csv(f)
        for col in ["symbol", "n_days", "base_rate_5pct"]:
            self.assertIn(col, df.columns,
                          f"stocks.csv missing column '{col}'")
        self.assertGreater(len(df), 0, "stocks.csv has no rows")

    # ── Test 7: summary.md contains expected sections ────────────────────────
    def test_16_summary_md_has_pattern_table(self):
        f = self._get_latest_file("_summary.md")
        if not f:
            self.skipTest("summary.md not found")
        with open(f, encoding="utf-8") as fp:
            content = fp.read()
        self.assertIn("Pattern", content, "summary.md missing 'Pattern' section")
        self.assertIn("lift", content.lower(), "summary.md missing lift data")
        self.assertIn("Research only", content, "summary.md missing disclaimer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
