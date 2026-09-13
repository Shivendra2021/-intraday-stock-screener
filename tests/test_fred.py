import unittest
from unittest.mock import patch, MagicMock

from modules.fred_provider import (
    is_fred_configured,
    get_macro_indicator,
    get_macro_snapshot,
)


class TestFredProvider(unittest.TestCase):
    def test_fred_configured(self):
        self.assertTrue(is_fred_configured())

    def test_brent_crude_indicator(self):
        res = get_macro_indicator('DCOILBRENTEU')
        if res:
            self.assertIsInstance(res, dict)
            self.assertIn('series_id', res)
            self.assertIn('value', res)
            self.assertIn('date', res)
            self.assertGreater(res['value'], 0.0)

    def test_macro_snapshot_keys(self):
        snap = get_macro_snapshot()
        self.assertIsInstance(snap, dict)
        self.assertIn('crude_pressure', snap)
        self.assertIn('fii_yield_pressure', snap)

    @patch('modules.fred_provider.requests.get')
    def test_fred_fail_open(self, mock_get):
        mock_get.side_effect = Exception('FRED unreachable')
        res = get_macro_indicator('NONEXISTENT_SERIES')
        self.assertIsNone(res)


if __name__ == '__main__':
    unittest.main()
