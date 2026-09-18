"""
Standalone Weekly Forex & Multi-Asset Intelligence Report Dispatcher
Generates the comprehensive institutional weekly report with embedded SVG vector charts,
and uploads the PDF document directly to Telegram.
Can run in zero-cost CI environments like GitHub Actions.
"""

import sys
import datetime
import zoneinfo
import requests
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import (
    TELEGRAM_BOT_TOKEN,
    ALLOWED_USER_IDS,
    DEFAULT_TIMEZONE,
)
import forex_digest_service

def send_telegram_document(pdf_path: Path, caption: str = ""):
    """Dispatches PDF document attachment to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not ALLOWED_USER_IDS:
        print("Warning: TELEGRAM_BOT_TOKEN or ALLOWED_USER_IDS missing.")
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"

    for uid in ALLOWED_USER_IDS:
        try:
            with open(pdf_path, "rb") as doc_file:
                files = {"document": (pdf_path.name, doc_file, "application/pdf")}
                data = {"chat_id": uid, "caption": caption, "parse_mode": "Markdown"}
                resp = requests.post(api_url, data=data, files=files, timeout=45)
                if resp.status_code == 200:
                    print(f"Successfully uploaded Weekly PDF to {uid}")
                else:
                    print(f"Telegram upload failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"Error sending Weekly PDF to {uid}: {e}")

def main():
    print("=" * 60)
    print("🚀 Starting Weekly Forex & Multi-Asset Intelligence PDF Dispatcher...")
    print(f"Timezone: {DEFAULT_TIMEZONE}")
    now_local = datetime.datetime.now(zoneinfo.ZoneInfo(DEFAULT_TIMEZONE))
    print(f"Local Time: {now_local.strftime('%A, %B %d, %Y %I:%M %p')}")
    print("=" * 60)

    print("\n[1/2] Generating comprehensive institutional weekly report with SVG charts...")
    pdf_path = forex_digest_service.generate_weekly_intelligence_report()
    size_kb = pdf_path.stat().st_size / 1024.0
    print(f"✓ Weekly Illustrated PDF generated: {pdf_path.name} ({size_kb:.1f} KB)")

    print("\n[2/2] Sending Weekly PDF report to Telegram...")
    caption = (
        "📊 *সাপ্তাহিক ফরেক্স ও মাল্টি-অ্যাসেট ইন্টেলিজেন্স রিপোর্ট*\n\n"
        "✅ গত সপ্তাহের সমস্ত নিউজ বিশ্লেষণ, গোল্ড, ফিউচার্স ও কারেন্সির চার্ট এবং আগামী সপ্তাহের রোডম্যাপ প্রস্তুত!"
    )
    send_telegram_document(pdf_path, caption=caption)

    print("\n" + "=" * 60)
    print("✅ Weekly report dispatched successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()

