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

    def test_fetch_forexfactory_direct_news(self):
        items = forex_news_monitor.fetch_forexfactory_direct_news(limit=5)
        self.assertIsInstance(items, list)
        if items:
            first = items[0]
            self.assertTrue(first.get("is_forexfactory"))
            self.assertTrue(first["news_id"].startswith("ff_"))
            self.assertIn("title", first)
            self.assertIn("published_dt", first)

    def test_is_low_impact_analysis(self):
        low_text = "🚨 **গুরুত্ব (Importance):** Low 🟡 — এটি একটি তাত্ত্বিক আলোচনা যার কোনো তাৎক্ষণিক প্রভাব নেই।"
        high_text = "1. 🚨 **গুরুত্ব ও ইমপ্যাক্ট (Importance):** High 🔴 — ইউএসডি/জেপিওয়াই পেয়ারে বড় পতন ঘটাতে পারে।"
        med_text = "1. 🚨 **গুরুত্ব ও ইমপ্যাক্ট (Importance):** Medium 🟠 — ইউরোপীয় কেন্দ্রীয় ব্যাংকের পলিসিতে প্রভাব।"
        
        self.assertTrue(forex_news_monitor.is_low_impact_analysis(low_text))
        self.assertFalse(forex_news_monitor.is_low_impact_analysis(high_text))
        self.assertFalse(forex_news_monitor.is_low_impact_analysis(med_text))

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
        dummy_analysis = "1. 🚨 **গুরুত্ব ও ইমপ্যাক্ট:** High 🔴\n2. 🟢 **কোন কোন ইন্সট্রুমেন্ট উপরে যাবে:** Gold (XAU/USD)"
        alert = forex_news_monitor.format_news_telegram_alert(dummy_item, dummy_analysis)
        self.assertIn("Fed Powell Signals Cautious Rate Cuts Ahead", alert)
        self.assertIn("High 🔴", alert)
        self.assertIn("Gold (XAU/USD)", alert)

    def test_parse_article_date(self):
        date_str = "Wed, 16 Sep 2026 19:00:36 GMT"
        dt = forex_news_monitor.parse_article_date(date_str)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 9)
        self.assertEqual(dt.day, 16)

    def test_old_news_filtered(self):
        import datetime
        old_date_str = "Wed, 16 Sep 2026 19:00:36 GMT"
        dt = forex_news_monitor.parse_article_date(old_date_str)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        age_hours = (now_utc - dt).total_seconds() / 3600.0
        self.assertGreater(age_hours, forex_news_monitor.MAX_BREAKING_NEWS_AGE_HOURS)

if __name__ == "__main__":
    unittest.main()
