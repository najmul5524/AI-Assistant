"""
Unit tests for Forex Breaking News Monitor and AI Market Analysis.
"""

import unittest
import database
import forex_news_monitor

class TestForexNewsMonitor(unittest.TestCase):
    def test_fetch_news(self):
        items = forex_news_monitor.fetch_latest_forex_news(limit=5)
        self.assertIsInstance(items, list)
        self.assertGreater(len(items), 0, "Should fetch non-empty list of breaking news")
        first = items[0]
        self.assertIn("title", first)
        self.assertIn("news_id", first)
        self.assertIn("pub_date", first)
        self.assertTrue(len(first["title"]) > 5)

    def test_database_news_deduplication(self):
        dummy_id = "test_dummy_news_id_123"
        dummy_title = "US Core PCE MoM increases 0.3%"
        
        # Ensure clean state
        database.mark_news_as_seen(dummy_id, dummy_title)
        self.assertTrue(database.is_news_seen(dummy_id))
        self.assertFalse(database.is_news_seen("non_existent_news_id_xyz"))

    def test_format_news_telegram_alert(self):
        dummy_item = {
            "title": "Fed Powell Signals Cautious Rate Cuts Ahead",
            "pub_date": "Fri, 18 Sep 2026 14:30:00 GMT"
        }
        dummy_analysis = "1. 🚨 **গুরুত্ব:** High 🔴\n2. 🎯 **প্রভাবিত পেয়ার:** EUR/USD, USD/JPY, Gold"
        alert = forex_news_monitor.format_news_telegram_alert(dummy_item, dummy_analysis)
        self.assertIn("Fed Powell Signals Cautious Rate Cuts Ahead", alert)
        self.assertIn("High 🔴", alert)
        self.assertIn("EUR/USD", alert)

if __name__ == "__main__":
    unittest.main()
