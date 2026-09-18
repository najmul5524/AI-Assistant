"""
Google Calendar One-Click Setup Script
Runs OAuth 2.0 flow using credentials.json to authorize Google Calendar access
and generate token.json.
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

def print_setup_guide():
    print("=" * 65)
    print("❌ 'credentials.json' ফাইলটি পাওয়া যায়নি!")
    print("=" * 65)
    print("\nGoogle Calendar চালু করতে নিচের সহজ ধাপগুলো অনুসরণ করুন:\n")
    print("১. Google Cloud Console-এ যান: https://console.cloud.google.com/")
    print("২. একটি নতুন Project তৈরি করুন (বা পুরোনো প্রজেক্ট সিলেক্ট করুন)।")
    print("৩. 'APIs & Services' > 'Library' তে গিয়ে 'Google Calendar API' সার্চ করে Enable করুন।")
    print("৪. 'OAuth consent screen' এ গিয়ে User Type 'External' দিন এবং আপনার ইমেইল দিন।")
    print("   (Test Users সেকশনে আপনার নিজের Gmail আইডিটি যোগ করুন)।")
    print("৫. 'Credentials' > 'Create Credentials' > 'OAuth client ID' সিলেক্ট করুন।")
    print("   Application type দিন: 'Desktop app' (বা Desktop application)।")
    print("৬. তৈরি হলে JSON ফাইলটি ডাউনলোড করুন এবং নাম পরিবর্তন করে 'credentials.json' রাখুন।")
    print(f"৭. ফাইলটি এই প্রজেক্ট ফোল্ডারে রাখুন:\n   {BASE_DIR}")
    print("\nএরপর পুনরায় এই স্ক্রিপ্টটি চালান: python setup_google_calendar.py\n")
    print("=" * 65)

def run_setup():
    print("\n" + "=" * 65)
    print("🚀 Google Calendar Integration Setup")
    print("=" * 65 + "\n")

    if not CREDENTIALS_FILE.exists():
        print_setup_guide()
        return False

    print("✅ credentials.json পাওয়া গেছে। ব্রাউজারে লগইন উইন্ডো ওপেন হচ্ছে...")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE), SCOPES
        )
        creds = flow.run_local_server(port=0)

        # Save credentials for future use
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

        print(f"✅ সফলভাবে অথেনটিকেশন সম্পন্ন হয়েছে! 'token.json' সংরক্ষিত হয়েছে।")

        # Test calendar connection
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        cal = service.calendars().get(calendarId="primary").execute()
        cal_summary = cal.get("summary", "Primary Calendar")
        print(f"📅 সংযুক্ত ক্যালেন্ডার: {cal_summary}")
        print("🎉 এখন থেকে আপনার AI Assistant স্বয়ংক্রিয়ভাবে Google Calendar-এ রিমাইন্ডার সেট করতে পারবে!\n")
        return True
    except Exception as e:
        print(f"\n❌ অথেনটিকেশনে সমস্যা হয়েছে: {e}\n")
        return False

if __name__ == "__main__":
    run_setup()

