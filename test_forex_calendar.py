"""
Unit and integration tests for Forex Factory news parser and Google Calendar service.
"""

import unittest
import datetime
import zoneinfo
import forex_service
import google_calendar_service

class TestForexCalendar(unittest.TestCase):
    def test_fetch_raw_calendar(self):
        raw = forex_service.fetch_raw_calendar()
        self.assertIsInstance(raw, list)
        self.assertGreater(len(raw), 0, "Should fetch non-empty calendar from CDN")
        first = raw[0]
        self.assertIn("title", first)
        self.assertIn("country", first)
        self.assertIn("impact", first)
        self.assertIn("date", first)

    def test_get_forex_events_all(self):
        events = forex_service.get_forex_events(target_date="all", min_impact="Low")
        self.assertGreater(len(events), 0, "Should return parsed events for the week")
        
        sample = events[0]
        self.assertIn("title", sample)
        self.assertIn("country", sample)
        self.assertIn("impact", sample)
        self.assertIn("start_dt", sample)
        self.assertIn("end_dt", sample)
        self.assertIn("time_str", sample)
        self.assertIsInstance(sample["start_dt"], datetime.datetime)
        self.assertEqual(sample["start_dt"].tzinfo.key, "Asia/Dhaka")

    def test_impact_filtering(self):
        high_only = forex_service.get_forex_events(target_date="all", min_impact="High")
        for ev in high_only:
            self.assertEqual(ev["impact"], "High")

    def test_currency_filtering(self):
        usd_only = forex_service.get_forex_events(target_date="all", min_impact="Low", currencies=["USD"])
        for ev in usd_only:
            self.assertEqual(ev["country"], "USD")

    def test_format_message(self):
        sample_events = [
            {
                "title": "Core CPI m/m",
                "country": "USD",
                "impact": "High",
                "impact_emoji": "🔴",
                "forecast": "0.3%",
                "previous": "0.2%",
                "time_str": "06:30 PM",
                "date_str": "2026-09-18"
            }
        ]
        msg = forex_service.format_forex_telegram_message(sample_events)
        self.assertIn("Core CPI m/m", msg)
        self.assertIn("USD", msg)
        self.assertIn("06:30 PM", msg)
        self.assertIn("0.3%", msg)

    def test_google_calendar_not_configured_graceful_handling(self):
        # When token.json is not present, should handle gracefully
        events = forex_service.get_forex_events(target_date="all", min_impact="High")[:1]
        res = google_calendar_service.sync_forex_events_to_calendar(events)
        self.assertIn(res["status"], ["not_configured", "success", "empty"])

if __name__ == "__main__":
    unittest.main()

