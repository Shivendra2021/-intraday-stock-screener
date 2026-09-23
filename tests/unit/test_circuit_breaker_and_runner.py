import unittest
from unittest.mock import patch, MagicMock
import os
import json

from config import (
    MAX_DAILY_SL_HITS,
    RUNNER_TP1_PCT,
    RUNNER_TP2_PCT,
    RUNNER_TRAIL_LOCKED_PCT,
)
from modules.circuit_breaker import (
    record_sl_hit,
    is_circuit_breaker_active,
    get_circuit_breaker_status,
    reset_daily_circuit_breaker,
)
from modules.alerts import send_circuit_breaker_alert, send_tp1_hit, send_morning_final_picks
from modules.picker import _calculate_levels
from modules.stock_tracker import init_tracking, update_tracking


class TestCircuitBreakerAndRunner(unittest.TestCase):
    def setUp(self):
        reset_daily_circuit_breaker()

    def tearDown(self):
        reset_daily_circuit_breaker()

    def test_circuit_breaker_lifecycle(self):
        """Test that circuit breaker does not trigger on 1st SL hit, but engages on 2nd hit."""
        # Clean start
        self.assertFalse(is_circuit_breaker_active())
        status = get_circuit_breaker_status()
        self.assertEqual(status["sl_count"], 0)
        self.assertFalse(status["active"])

        # 1st SL hit
        state1 = record_sl_hit("ABC", -1.5)
        self.assertEqual(state1["sl_count"], 1)
        self.assertFalse(state1["active"])
        self.assertFalse(is_circuit_breaker_active())

        # 2nd SL hit -> should trigger lockdown
        with patch("modules.alerts.send_circuit_breaker_alert") as mock_alert:
            state2 = record_sl_hit("XYZ", -1.8)
            self.assertEqual(state2["sl_count"], 2)
            self.assertTrue(state2["active"])
            self.assertTrue(is_circuit_breaker_active())
            mock_alert.assert_called_once()

        # Status check
        status = get_circuit_breaker_status()
        self.assertTrue(status["active"])
        self.assertEqual(status["sl_count"], 2)
        self.assertEqual(len(status["sl_hits"]), 2)

    def test_2_stage_runner_target_math(self):
        """Test candidate calculation of TP1 (+3.8%) and TP2 (+7.5%)."""
        stock = {
            "symbol": "TESTSTOCK",
            "price": 1000.0,
            "atr": 15.0,
            "first_15m_volume": 100000,
            "avg_volume_15m": 20000,
        }
        cand = _calculate_levels(stock)
        self.assertIsNotNone(cand)
        self.assertEqual(cand["entry_price"], 1000.0)
        expected_tp1 = 1000.0 * (1 + RUNNER_TP1_PCT / 100.0)
        self.assertAlmostEqual(cand["tp1_price"], expected_tp1, delta=0.1)
        expected_tp2 = 1000.0 * (1 + cand["tp2_pct"] / 100.0)
        self.assertAlmostEqual(cand["tp2_price"], expected_tp2, delta=0.1)
        self.assertEqual(cand["target_price"], cand["tp2_price"])

    def test_alerts_formatting(self):
        """Test alert functions format correctly without crashing."""
        with patch("modules.alerts._send", return_value=True) as mock_send:
            ok1 = send_circuit_breaker_alert(sl_count=2, max_sl=2, loss_pct=-3.2)
            self.assertTrue(ok1)
            mock_send.assert_called()
            sent_text = mock_send.call_args[0][0]
            self.assertIn("CIRCUIT BREAKER", sent_text)

            mock_send.reset_mock()
            ok2 = send_tp1_hit("TATACHEM", 3.82, new_sl=1018.0)
            self.assertTrue(ok2)
            mock_send.assert_called()
            tp1_text = mock_send.call_args[0][0]
            self.assertIn("TARGET 1 HIT", tp1_text)
            self.assertIn("50% Quantity", tp1_text)

    def test_morning_final_picks_displays_both_targets(self):
        """Test that send_morning_final_picks includes TP1 and TP2 in the text."""
        picks = [{
            "symbol": "RUNNER1",
            "rank": 1,
            "entry_price": 500.0,
            "sl_price": 492.0,
            "target_price": 537.5,
            "tp1_price": 519.0,
            "tp2_price": 537.5,
            "tp1_pct": 3.8,
            "tp2_pct": 7.5,
            "score": 85,
            "upside_pct": 7.5,
            "risk_reward": 4.69,
            "rsi": 62.0,
            "adx": 28.0,
            "vol_ratio": 2.5,
        }]
        with patch("modules.alerts._send", return_value=True) as mock_send:
            ok = send_morning_final_picks(picks, review_with_grok=False)
            self.assertTrue(ok)
            mock_send.assert_called()
            msg = mock_send.call_args[0][0]
            self.assertIn("TP1 (50% Book)", msg)
            self.assertIn("TP2 (Runner)", msg)
            self.assertIn("RUNNER1", msg)


if __name__ == "__main__":
    unittest.main()
