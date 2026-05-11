import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.research.intraday_pattern_scan import _compute_labels, _build_pattern_lift
from modules import dual_brain


class TestRecentFixes(unittest.TestCase):
    def test_compute_labels_respects_custom_threshold(self):
        df = pd.DataFrame({
            "open": [100.0, 100.0, 100.0],
            "high": [101.0, 106.0, 104.0],
        })
        out = _compute_labels(df.copy(), threshold=4.0)
        self.assertIn("label_threshold", out.columns)
        # Day 0 label checks next day's open-to-high: (106 - 100) / 100 = 6%.
        self.assertTrue(bool(out.loc[0, "label_threshold"]))
        self.assertTrue(bool(out.loc[0, "label_5pct"]))
        # Day 1 label checks next day's open-to-high: 4%, custom threshold true, 5pct false.
        self.assertTrue(bool(out.loc[1, "label_threshold"]))
        self.assertFalse(bool(out.loc[1, "label_5pct"]))

    def test_pattern_lift_uses_custom_threshold_when_present(self):
        data = pd.DataFrame({
            "gap_up_2pct": [True, True, False, False],
            "label_5pct": [False, False, False, False],
            "label_threshold": [True, True, False, False],
        })
        lift = _build_pattern_lift(data)
        row = lift[lift["pattern"] == "gap_up_2pct"].iloc[0]
        self.assertEqual(row["n_hits"], 2)
        self.assertEqual(row["hit_rate"], 1.0)

    def test_execute_command_does_not_auto_vote_other_brain(self):
        with patch("modules.brain_commands.issue_command", return_value={
            "ok": True,
            "id": "grok_test_ADD_WATCH",
            "status": "pending",
            "votes": {"grok": "YES"},
        }) as issue:
            result = dual_brain._execute_command("ADD_WATCH", {"symbol": "TCS"}, "reason", "grok")
        issue.assert_called_once()
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["votes"], {"grok": "YES"})

    def test_openrouter_uses_passed_base_url(self):
        with patch("modules.dual_brain.requests.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
            dual_brain._call_openrouter([], "key", "model", base_url="https://example.invalid/chat")
        self.assertEqual(post.call_args.args[0], "https://example.invalid/chat")


if __name__ == "__main__":
    unittest.main()
