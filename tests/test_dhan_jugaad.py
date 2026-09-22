import unittest
from unittest.mock import patch, MagicMock
import pandas as pd

from modules.dhan_provider import is_dhan_configured, get_security_id, get_dhan_price, get_dhan_quote
from modules.jugaad_provider import is_jugaad_enabled, get_jugaad_price, get_jugaad_ohlcv, get_jugaad_delivery_metrics
from modules.price_validation import validate_price, broker_price, nse_price


class TestDhanHQProvider(unittest.TestCase):
    def test_dhan_configuration(self):
        # By default DHAN_ENABLED is True and token is set
        self.assertTrue(is_dhan_configured())

    def test_dhan_scrip_resolution(self):
        # Pre-seeded test symbols
        self.assertEqual(get_security_id('RELIANCE'), 2885)
        self.assertEqual(get_security_id('reliance.ns'), 2885)
        self.assertEqual(get_security_id('TCS.NS'), 11536)
        self.assertEqual(get_security_id('INFY'), 1594)

    def test_dhan_fail_open(self):
        # Non-existent symbol fails open with None, no exception
        val = get_dhan_price('NONEXISTENT_SYMBOL_XYZ')
        self.assertIsNone(val)

        quote = get_dhan_quote('NONEXISTENT_SYMBOL_XYZ')
        self.assertIsNone(quote)


class TestJugaadProvider(unittest.TestCase):
    def test_jugaad_enabled(self):
        self.assertTrue(is_jugaad_enabled())

    def test_jugaad_ohlcv_structure(self):
        # Test real or mock bhavcopy OHLCV structure
        df = get_jugaad_ohlcv('TCS', lookback_days=10)
        if df is not None:
            self.assertIsInstance(df, pd.DataFrame)
            self.assertFalse(df.empty)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                self.assertIn(col, df.columns)

    def test_jugaad_delivery_metrics(self):
        metrics = get_jugaad_delivery_metrics('TCS')
        if metrics is not None:
            self.assertIsInstance(metrics, dict)
            self.assertIn('delivery_pct', metrics)
            self.assertIn('is_accumulation', metrics)
            self.assertGreaterEqual(metrics['delivery_pct'], 0.0)


class TestPriceValidationIntegration(unittest.TestCase):
    def test_price_validation_runs_cleanly(self):
        # Test that validate_price functions without error
        res = validate_price('RELIANCE', expected_price=2800.0)
        self.assertIsInstance(res, dict)
        self.assertIn('status', res)
        self.assertIn('consensus_price', res)
        self.assertIn('spread_pct', res)


if __name__ == '__main__':
    unittest.main()
