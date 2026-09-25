"""
Unit tests for Crude Oil (WTI & Brent) Chronological News & Predictive Analytics.
"""

import unittest
import oil_analytics_service

class TestOilAnalyticsService(unittest.TestCase):
    def test_fetch_oil_market_metrics(self):
        metrics = oil_analytics_service.fetch_oil_market_metrics()
        self.assertIsInstance(metrics, dict)
        self.assertIn("wti", metrics)
        self.assertIn("brent", metrics)
        wti = metrics["wti"]
        self.assertEqual(wti["ticker"], "CL=F")
        self.assertIn("current_price", wti)

    def test_fetch_chronological_oil_news(self):
        news = oil_analytics_service.fetch_chronological_oil_news(max_items=10)
        self.assertIsInstance(news, list)
        if news:
            first = news[0]
            self.assertIn("title", first)
            self.assertIn("source", first)

    def test_generate_oil_prediction_structure(self):
        # Verify function runs and returns structured markdown output
        report = oil_analytics_service.generate_oil_prediction_analysis()
        self.assertIsInstance(report, str)
        self.assertGreater(len(report), 100)
        # Check presence of key section headers
        self.assertTrue("WTI" in report or "Brent" in report or "তেল" in report)

if __name__ == "__main__":
    unittest.main()
