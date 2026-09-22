import unittest
from unittest.mock import patch, MagicMock

from modules.finnhub_provider import (
    is_finnhub_configured,
    get_global_market_news,
    get_high_impact_macro_events,
    get_global_sentiment_score,
)


class TestFinnhubProvider(unittest.TestCase):
    def test_finnhub_configured(self):
        self.assertTrue(is_finnhub_configured())

    def test_global_market_news_structure(self):
        news = get_global_market_news(category='general', limit=3)
        if news:
            self.assertIsInstance(news, list)
            item = news[0]
            self.assertIn('headline', item)
            self.assertIn('source', item)

    def test_global_sentiment_score_range(self):
        score = get_global_sentiment_score()
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, -1.0)
        self.assertLessEqual(score, 1.0)

    @patch('modules.finnhub_provider.requests.get')
    def test_finnhub_fail_open(self, mock_get):
        mock_get.side_effect = Exception('Network error')
        news = get_global_market_news(category='nonexistent')
        self.assertEqual(news, [])


if __name__ == '__main__':
    unittest.main()
