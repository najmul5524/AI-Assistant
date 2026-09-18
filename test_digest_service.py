"""
Unit tests for Forex Digest & Weekly Intelligence PDF Reporting Service.
"""

import unittest
from pathlib import Path
import forex_digest_service

class TestForexDigestService(unittest.TestCase):
    def test_daily_digest_generation(self):
        digest = forex_digest_service.generate_daily_digest()
        self.assertIsInstance(digest, str)
        self.assertGreater(len(digest), 50, "Daily digest should return substantive content")
        # Check key sections exist
        self.assertTrue("ডাইজেস্ট" in digest or "কারেন্সি" in digest or "USD" in digest)

    def test_weekly_report_generation(self):
        pdf_path = forex_digest_service.generate_weekly_intelligence_report(filename_prefix="test_weekly_intel")
        self.assertIsInstance(pdf_path, Path)
        self.assertTrue(pdf_path.exists())
        self.assertGreater(pdf_path.stat().st_size, 1000, "PDF should be generated and non-empty")
        # Cleanup test file
        try:
            pdf_path.unlink(missing_ok=True)
        except Exception:
            pass

if __name__ == "__main__":
    unittest.main()

