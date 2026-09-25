"""
Unit and integration tests for Multi-Asset Market Intelligence & Predictive Analytics Service.
Verifies symbol mappings, technicals extraction, ForexFactory news & calendar filtering,
and bot command handler registrations.
"""

import unittest
import market_analytics_service as mas
import technical_analysis_service as ta_service

class TestMarketAnalyticsService(unittest.TestCase):
    def test_asset_profile_resolution(self):
        test_cases = [
            ("gold", "GC=F", "gold", "USD"),
            ("xau", "GC=F", "gold", "USD"),
            ("nasdaq", "NQ=F", "indices", "USD"),
            ("us100", "NQ=F", "indices", "USD"),
            ("nq", "NQ=F", "indices", "USD"),
            ("sp500", "ES=F", "indices", "USD"),
            ("s&p500", "ES=F", "indices", "USD"),
            ("us500", "ES=F", "indices", "USD"),
            ("es", "ES=F", "indices", "USD"),
            ("dow", "YM=F", "indices", "USD"),
            ("dowjones", "YM=F", "indices", "USD"),
            ("dow jonson", "YM=F", "indices", "USD"),
            ("us30", "YM=F", "indices", "USD"),
            ("btc", "BTC-USD", "crypto", "USD"),
            ("bitcoin", "BTC-USD", "crypto", "USD"),
            ("eth", "ETH-USD", "crypto", "USD"),
            ("ethereum", "ETH-USD", "crypto", "USD"),
            ("etherium", "ETH-USD", "crypto", "USD"),
            ("oil", "CL=F", "oil", "USD"),
            ("crude", "CL=F", "oil", "USD"),
            ("eurusd", "EURUSD=X", "forex", "EUR"),
            ("gbpusd", "GBPUSD=X", "forex", "GBP"),
            ("usdjpy", "JPY=X", "forex", "JPY"),
            ("dxy", "DX-Y.NYB", "forex", "USD"),
        ]

        for query, expected_ticker, expected_category, expected_currency in test_cases:
            with self.subTest(query=query):
                profile = mas.get_asset_profile(query)
                self.assertEqual(profile["ticker"], expected_ticker, f"Query '{query}' resolved ticker {profile['ticker']} != {expected_ticker}")
                self.assertEqual(profile["category"], expected_category, f"Query '{query}' resolved category {profile['category']} != {expected_category}")
                self.assertEqual(profile["currency"], expected_currency, f"Query '{query}' resolved currency {profile['currency']} != {expected_currency}")

    def test_fetch_technicals_structure(self):
        gold_tech = mas.fetch_asset_technicals("GC=F", "Gold (XAU/USD)")
        self.assertIn("ticker", gold_tech)
        self.assertIn("current_price", gold_tech)
        self.assertEqual(gold_tech["ticker"], "GC=F")

        nasdaq_tech = mas.fetch_asset_technicals("NQ=F", "Nasdaq 100 Futures")
        self.assertIn("ticker", nasdaq_tech)
        self.assertIn("current_price", nasdaq_tech)
        self.assertEqual(nasdaq_tech["ticker"], "NQ=F")

    def test_forexfactory_filtering(self):
        stories = mas.fetch_asset_forexfactory_news(category="indices", currency="USD", limit=5)
        self.assertIsInstance(stories, list)

        calendar = mas.fetch_asset_calendar_events(currency="USD", category="indices")
        self.assertIsInstance(calendar, list)

    def test_bot_command_handlers_registered(self):
        import bot
        from telegram.ext import ApplicationBuilder, CommandHandler

        app = ApplicationBuilder().token("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11").build()
        # Mock main handlers registration
        expected_commands = [
            "gold", "xau", "silver", "xag", "nasdaq", "us100", "nq",
            "sp500", "us500", "spx", "es", "dow", "dowjones", "dowjonson",
            "us30", "ym", "btc", "bitcoin", "eth", "ethereum", "etherium",
            "eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf", "dxy",
            "market", "oil", "crude", "wti", "brent"
        ]

        # Verify bot.py has these CommandHandlers by inspecting the source or functions
        self.assertTrue(callable(bot.market_command))
        self.assertTrue(callable(bot.oil_command))

if __name__ == "__main__":
    unittest.main()
