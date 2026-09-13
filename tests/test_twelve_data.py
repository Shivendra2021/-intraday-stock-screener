import unittest
from unittest.mock import patch, MagicMock

from modules.twelve_data_provider import (
    is_twelve_data_configured,
    get_usdinr_rate,
    get_twelve_data_price,
)
from modules.api_registry import discover_all_apis


class TestTwelveDataProvider(unittest.TestCase):
    def test_twelve_data_configured(self):
        self.assertTrue(is_twelve_data_configured())

    @patch('modules.twelve_data_provider._load_cache', return_value={})
    @patch('modules.twelve_data_provider.requests.get')
    def test_get_usdinr_rate_mock(self, mock_get, mock_cache):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"price": "86.54"}
        mock_get.return_value = mock_resp

        rate = get_usdinr_rate()
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(rate, 86.54)

    @patch('modules.twelve_data_provider._load_cache', return_value={})
    @patch('modules.twelve_data_provider.requests.get')
    def test_twelve_data_price_fail_open_on_error(self, mock_get, mock_cache):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "code": 404,
            "message": "This symbol is available starting with the Grow or Venture plan",
            "status": "error"
        }
        mock_get.return_value = mock_resp

        price = get_twelve_data_price("RELIANCE:NSE")
        self.assertIsNone(price)

    def test_twelve_data_in_api_registry(self):
        apis = discover_all_apis()
        td_api = next((a for a in apis if a["id"] == "twelve_data"), None)
        self.assertIsNotNone(td_api)
        self.assertEqual(td_api["limit"], 800)
        self.assertEqual(td_api["short_name"], "Twelve Data")
        self.assertEqual(td_api["category"], "Market Data Gateway")


if __name__ == '__main__':
    unittest.main()
