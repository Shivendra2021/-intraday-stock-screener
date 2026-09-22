import unittest
from unittest.mock import patch, MagicMock

from modules.catalyst_search import _classify_catalyst, get_stock_catalyst


class TestCatalystSearch(unittest.TestCase):
    def test_classify_catalyst_types(self):
        self.assertEqual(_classify_catalyst('Company wins ₹500 Cr railway order', ''), 'order_win')
        self.assertEqual(_classify_catalyst('Q2 net profit surges 45% YoY', 'Revenue up'), 'earnings_beat')
        self.assertEqual(_classify_catalyst('US FDA approval received for key drug', ''), 'regulatory_approval')
        self.assertEqual(_classify_catalyst('New plant capex approved by board', ''), 'capex_expansion')
        self.assertEqual(_classify_catalyst('Shares rally 5% on strong volume', ''), 'general_momentum')

    def test_catalyst_cache_and_live_structure(self):
        res = get_stock_catalyst('RELIANCE')
        if res is not None:
            self.assertIsInstance(res, dict)
            self.assertIn('symbol', res)
            self.assertIn('has_catalyst', res)
            self.assertIn('headline', res)
            self.assertIn('source', res)
            self.assertIn('summary', res)

    @patch('modules.catalyst_search.requests.get')
    def test_catalyst_fail_open(self, mock_get):
        mock_get.side_effect = Exception('Network down')
        res = get_stock_catalyst('NONEXISTENT_MOCK_XYZ')
        self.assertIsNone(res)


if __name__ == '__main__':
    unittest.main()
