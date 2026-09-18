"""
Daily Forex News & Google Calendar Sync Runner
Designed to run either locally, on a server, or inside GitHub Actions Cron.
Fetches today's Forex events, syncs to Google Calendar, and sends a Telegram notification.
"""

import sys
import os
import requests
import logging

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

from config import (
    TELEGRAM_BOT_TOKEN,
    ALLOWED_USER_IDS,
    DEFAULT_TIMEZONE,
    FOREX_MIN_IMPACT,
    FOREX_CURRENCIES,
    FOREX_REMINDER_MINUTES,
)
import forex_service
import google_calendar_service

def send_telegram_alert(message: str):
    """Dispatch alert via Telegram Bot API directly (HTTP request)."""
    if not TELEGRAM_BOT_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN not provided, skipping Telegram alert.")
        return

    if not ALLOWED_USER_IDS:
        logger.info("ALLOWED_USER_IDS is empty, skipping Telegram alert.")
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for user_id in ALLOWED_USER_IDS:
        try:
            payload = {
                "chat_id": user_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            resp = requests.post(api_url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Telegram notification sent to user {user_id}.")
            else:
                logger.warning(f"Failed to send to {user_id}: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Error sending Telegram notification to {user_id}: {e}")

def main():
    logger.info("==========================================")
    logger.info("🚀 Starting Daily Forex Calendar Sync Job")
    logger.info("==========================================")

    # 1. Fetch today's Forex events
    events = forex_service.get_forex_events(
        target_date=None,  # Today (in DEFAULT_TIMEZONE)
        min_impact=FOREX_MIN_IMPACT,
        currencies=FOREX_CURRENCIES,
        tz_name=DEFAULT_TIMEZONE
    )

    if not events:
        logger.info("No High/Medium impact events found for today.")
        return

    logger.info(f"Found {len(events)} economic events for today.")

    # 2. Sync with Google Calendar
    sync_result = google_calendar_service.sync_forex_events_to_calendar(
        events=events,
        reminder_minutes=FOREX_REMINDER_MINUTES,
        tz_name=DEFAULT_TIMEZONE
    )
    logger.info(f"Google Calendar Sync: {sync_result['message']}")

    # 3. Format message and send via Telegram
    briefing = forex_service.format_forex_telegram_message(
        events=events,
        header_title=f"Forex Factory ইকোনমিক ক্যালেন্ডার"
    )

    telegram_text = (
        f"☀️ *শুভ সকাল! আজকের ফরেক্স ক্যালেন্ডার অ্যালার্ট*\n\n"
        f"{briefing}\n\n"
        f"📅 *Google Calendar:* {sync_result['message']}"
    )

    send_telegram_alert(telegram_text)
    logger.info("✅ Daily sync job completed successfully.")

if __name__ == "__main__":
    main()

