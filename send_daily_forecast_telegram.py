"""
Standalone Daily Market Forecast & Illustrated PDF Dispatcher
Executes the comprehensive Next-Day Multi-Asset Prediction, generates the illustrated
vector chart PDF report, and sends both directly to Telegram.
Can be executed locally or in zero-cost CI environments like GitHub Actions.
"""

import sys
import os
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

def send_telegram_split_text(text: str):
    """Dispatches text message to Telegram, splitting cleanly if exceeding 4000 characters."""
    if not TELEGRAM_BOT_TOKEN or not ALLOWED_USER_IDS:
        print("Warning: TELEGRAM_BOT_TOKEN or ALLOWED_USER_IDS missing.")
        return

    # Split into chunks of 4000 chars
    parts = []
    current_chunk = ""
    for block in text.split("\n\n"):
        if len(current_chunk) + len(block) + 2 < 4000:
            current_chunk += ("\n\n" if current_chunk else "") + block
        else:
            if current_chunk:
                parts.append(current_chunk)
            current_chunk = block
    if current_chunk:
        parts.append(current_chunk)

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for uid in ALLOWED_USER_IDS:
        for p in parts:
            try:
                resp = requests.post(
                    api_url,
                    json={"chat_id": uid, "text": p, "parse_mode": "Markdown"},
                    timeout=15
                )
                if resp.status_code != 200:
                    # Fallback plain text if markdown formatting issue
                    requests.post(
                        api_url,
                        json={"chat_id": uid, "text": p},
                        timeout=15
                    )
                print(f"Dispatched forecast message chunk to {uid}")
            except Exception as e:
                print(f"Failed to send forecast text to {uid}: {e}")

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
                resp = requests.post(api_url, data=data, files=files, timeout=30)
                if resp.status_code == 200:
                    print(f"Successfully uploaded illustrated forecast PDF to {uid}")
                else:
                    print(f"Telegram document upload failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"Error sending PDF to {uid}: {e}")

def main():
    print("=" * 60)
    print("🚀 Starting Daily Market Forecast & Illustrated PDF Dispatcher...")
    print(f"Timezone: {DEFAULT_TIMEZONE}")
    now_local = datetime.datetime.now(zoneinfo.ZoneInfo(DEFAULT_TIMEZONE))
    print(f"Local Time: {now_local.strftime('%A, %B %d, %Y %I:%M %p')}")
    print("=" * 60)

    # 1. Generate text forecast
    print("\n[1/3] Generating next-day price movement prediction & market digest...")
    digest_text = forex_digest_service.generate_daily_digest()
    print("✓ Prediction text generated successfully.")

    # 2. Generate illustrated PDF with SVG charts
    print("\n[2/3] Generating illustrated technical range & direction PDF...")
    pdf_path = forex_digest_service.generate_daily_forecast_pdf()
    print(f"✓ Illustrated PDF generated: {pdf_path.name} ({pdf_path.stat().st_size / 1024:.1f} KB)")

    # 3. Send both to Telegram
    print("\n[3/3] Sending forecast text and PDF to Telegram...")
    send_telegram_split_text(digest_text)
    caption = "📊 *আগামীকালের মার্কেট পূর্বাভাস ও টেকনিক্যাল চার্ট*\n\n✅ গোল্ড, সিলভার, Nasdaq 100, S&P 500 ও ফরেক্সের টেকনিক্যাল রেঞ্জ চিত্রসহ প্রস্তুত! (বাংলাদেশ সময়)"
    send_telegram_document(pdf_path, caption=caption)

    print("\n" + "=" * 60)
    print("✅ All forecast messages & illustrated PDF dispatched successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()

