"""
Google Calendar Service
Manages authentication and syncing of Forex Factory news reminders into Google Calendar.
Supports both OAuth 2.0 (credentials.json / token.json) and Service Account (service_account.json).
"""

import sys
import os
import logging
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2 import service_account

from config import BASE_DIR, DEFAULT_TIMEZONE

logger = logging.getLogger(__name__)

# Scopes required to view and manage calendar events
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"
SERVICE_ACCOUNT_FILE = BASE_DIR / "service_account.json"

def is_calendar_configured() -> bool:
    """Check if Google Calendar credentials, token, or token env exist."""
    return (
        bool(os.getenv("GOOGLE_TOKEN_JSON", "").strip())
        or TOKEN_FILE.exists()
        or CREDENTIALS_FILE.exists()
        or SERVICE_ACCOUNT_FILE.exists()
    )

def get_calendar_credentials() -> Optional[Any]:
    """Retrieve valid credentials for Google Calendar API."""
    creds = None

    # Option A: Service Account File
    if SERVICE_ACCOUNT_FILE.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
            )
            return creds
        except Exception as e:
            logger.error(f"Error loading service account: {e}")

    # Option B1: Environment Variable GOOGLE_TOKEN_JSON (for GitHub Actions / Cloud)
    token_env = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
    if token_env:
        try:
            import json
            token_data = json.loads(token_env)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception as e:
            logger.warning(f"Error parsing GOOGLE_TOKEN_JSON env variable: {e}")

    # Option B2: OAuth token.json file
    if not creds and TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as e:
            logger.warning(f"Error reading token.json: {e}")

    # If credentials exist and are expired, refresh them
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w", encoding="utf-8") as token:
                token.write(creds.to_json())
            logger.info("Refreshed expired Google Calendar OAuth token.")
        except Exception as e:
            logger.error(f"Could not refresh token: {e}")
            creds = None

    return creds

def get_calendar_service():
    """Build and return an authorized Google Calendar API service instance."""
    creds = get_calendar_credentials()
    if not creds or not creds.valid:
        return None
    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        logger.error(f"Failed to build Google Calendar service: {e}")
        return None

def sync_forex_events_to_calendar(
    events: List[Dict[str, Any]],
    reminder_minutes: int = 15,
    calendar_id: str = "primary",
    tz_name: str = DEFAULT_TIMEZONE
) -> Dict[str, Any]:
    """
    Inserts Forex events into Google Calendar with reminder notifications.
    Prevents duplicate entries.
    """
    if not events:
        return {
            "status": "empty",
            "added": 0,
            "skipped": 0,
            "total": 0,
            "message": "সিঙ্ক করার মতো কোনো নিউজ ইভেন্ট পাওয়া যায়নি।"
        }

    service = get_calendar_service()
    if not service:
        return {
            "status": "not_configured",
            "added": 0,
            "skipped": 0,
            "total": len(events),
            "message": "Google Calendar অথেনটিকেশন পাওয়া যায়নি। প্রথমে 'python setup_google_calendar.py' রান করুন।"
        }

    # Find time range of events for duplicate checking
    min_time = min(ev["start_dt"] for ev in events) - datetime.timedelta(hours=2)
    max_time = max(ev["end_dt"] for ev in events) + datetime.timedelta(hours=2)

    try:
        # Fetch existing events in that time window to prevent duplicates
        existing_events_res = service.events().list(
            calendarId=calendar_id,
            timeMin=min_time.isoformat(),
            timeMax=max_time.isoformat(),
            singleEvents=True
        ).execute()
        existing_items = existing_events_res.get("items", [])
        
        # Build set of existing titles & unique ids
        existing_signatures = set()
        for item in existing_items:
            summary = item.get("summary", "")
            private_props = item.get("extendedProperties", {}).get("private", {})
            news_id = private_props.get("news_id", "")
            if news_id:
                existing_signatures.add(news_id)
            if summary:
                existing_signatures.add(summary.strip())
    except Exception as e:
        logger.warning(f"Could not check existing calendar events: {e}")
        existing_signatures = set()

    added_count = 0
    skipped_count = 0

    for ev in events:
        summary = f"{ev['impact_emoji']} [{ev['country']} {ev['impact']}] {ev['title']}"
        unique_id = ev["unique_id"]

        # If already exists in calendar, skip
        if unique_id in existing_signatures or summary.strip() in existing_signatures:
            skipped_count += 1
            continue

        desc_lines = [
            f"📈 Forex Factory Economic News Alert",
            f"Currency: {ev['country']}",
            f"Impact Level: {ev['impact']}",
            f"Forecast: {ev['forecast'] or 'N/A'}",
            f"Previous: {ev['previous'] or 'N/A'}",
            f"Date & Time: {ev['time_str']} ({tz_name})",
            f"Source: Forex Factory / Fair Economy Feed"
        ]

        # Configure reminders (popup alert e.g. 15 mins before & 30 mins before)
        overrides = [{"method": "popup", "minutes": reminder_minutes}]
        if reminder_minutes != 30:
            overrides.append({"method": "popup", "minutes": 30})

        event_body = {
            "summary": summary,
            "description": "\n".join(desc_lines),
            "start": {
                "dateTime": ev["start_dt"].isoformat(),
                "timeZone": tz_name,
            },
            "end": {
                "dateTime": ev["end_dt"].isoformat(),
                "timeZone": tz_name,
            },
            "reminders": {
                "useDefault": False,
                "overrides": overrides,
            },
            "extendedProperties": {
                "private": {
                    "news_id": unique_id,
                    "source": "forexfactory_ai_assistant",
                    "impact": ev["impact"],
                    "country": ev["country"]
                }
            }
        }

        try:
            service.events().insert(calendarId=calendar_id, body=event_body).execute()
            added_count += 1
            existing_signatures.add(unique_id)
            existing_signatures.add(summary.strip())
        except Exception as e:
            logger.error(f"Failed to insert event '{summary}': {e}")

    return {
        "status": "success",
        "added": added_count,
        "skipped": skipped_count,
        "total": len(events),
        "message": f"সফলভাবে {added_count}টি নতুন নিউজ ইভেন্ট Google Calendar-এ যুক্ত করা হয়েছে (পূর্বে যুক্ত থাকা {skipped_count}টি স্কিপ করা হয়েছে)।"
    }

if __name__ == "__main__":
    from forex_service import get_forex_events
    print("Google Calendar Configured:", is_calendar_configured())
    today_events = get_forex_events(min_impact="Medium")
    print(f"Syncing {len(today_events)} events...")
    res = sync_forex_events_to_calendar(today_events)
    print("Sync Result:", res)

