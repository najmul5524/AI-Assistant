"""
Forex Factory Economic News Parser Service
Fetches official Fair Economy / Forex Factory CDN calendar feeds,
converts to user's local timezone (e.g. Asia/Dhaka), and filters by impact and currency.
"""

import sys
import datetime
import zoneinfo
import logging
import requests
from typing import List, Dict, Optional, Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import DEFAULT_TIMEZONE, BASE_DIR

logger = logging.getLogger(__name__)

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_FILE = BASE_DIR / "ff_calendar_cache.json"
CACHE_TTL_SECONDS = 900  # 15 minutes

_MEMORY_CACHE = {
    "data": [],
    "last_fetched": None
}

IMPACT_LEVELS = {
    "High": 3,
    "Medium": 2,
    "Low": 1,
    "Holiday": 0
}

IMPACT_EMOJIS = {
    "High": "🔴",
    "Medium": "🟠",
    "Low": "🟡",
    "Holiday": "⚪"
}

def fetch_raw_calendar(timeout: int = 15, force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Fetch raw calendar list from Forex Factory CDN with smart caching."""
    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Check in-memory cache
    if not force_refresh and _MEMORY_CACHE["data"] and _MEMORY_CACHE["last_fetched"]:
        elapsed = (now - _MEMORY_CACHE["last_fetched"]).total_seconds()
        if elapsed < CACHE_TTL_SECONDS:
            return _MEMORY_CACHE["data"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    import json
    try:
        resp = requests.get(FF_CALENDAR_URL, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            _MEMORY_CACHE["data"] = data
            _MEMORY_CACHE["last_fetched"] = now
            # Save to disk cache
            try:
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f)
            except Exception as fe:
                logger.debug(f"Could not write disk cache: {fe}")
            return data
    except Exception as e:
        logger.warning(f"Failed to fetch Forex Factory calendar feed ({e}), attempting cache fallback...")

    # 2. Fallback to memory cache if available
    if _MEMORY_CACHE["data"]:
        return _MEMORY_CACHE["data"]

    # 3. Fallback to disk cache if available
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
                if isinstance(disk_data, list) and disk_data:
                    _MEMORY_CACHE["data"] = disk_data
                    _MEMORY_CACHE["last_fetched"] = now
                    logger.info("Loaded Forex calendar data from disk cache.")
                    return disk_data
        except Exception as fe:
            logger.error(f"Failed to read disk cache: {fe}")

    return []

def get_forex_events(
    target_date: Optional[datetime.date] = None,
    min_impact: str = "Medium",
    currencies: Optional[List[str]] = None,
    tz_name: str = DEFAULT_TIMEZONE
) -> List[Dict[str, Any]]:
    """
    Fetch and parse Forex Factory news events.
    """
    raw_events = fetch_raw_calendar()
    if not raw_events:
        return []

    try:
        local_tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        local_tz = zoneinfo.ZoneInfo("Asia/Dhaka")

    if target_date is None:
        today_local = datetime.datetime.now(local_tz).date()
        target_date = today_local

    min_impact_rank = IMPACT_LEVELS.get(min_impact.capitalize(), 2)

    if currencies:
        currencies_set = {c.upper().strip() for c in currencies}
    else:
        currencies_set = None

    parsed_events = []

    for item in raw_events:
        title = item.get("title", "").strip()
        country = item.get("country", "").strip().upper()
        raw_date = item.get("date", "")
        impact = item.get("impact", "").capitalize()
        forecast = item.get("forecast", "").strip()
        previous = item.get("previous", "").strip()

        # Check impact filter
        item_rank = IMPACT_LEVELS.get(impact, 0)
        if item_rank < min_impact_rank:
            continue

        # Check currency filter
        if currencies_set and country not in currencies_set:
            continue

        if not raw_date:
            continue

        try:
            # Parse ISO date with offset (e.g. 2026-09-18T10:00:00-04:00)
            event_dt = datetime.datetime.fromisoformat(raw_date)
            # Convert to user's local timezone
            local_dt = event_dt.astimezone(local_tz)
        except Exception as e:
            logger.warning(f"Could not parse date '{raw_date}': {e}")
            continue

        # Check date filter (unless target_date == 'all')
        if target_date != "all" and local_dt.date() != target_date:
            continue

        # Duration is typically 30 minutes for calendar event representation
        end_dt = local_dt + datetime.timedelta(minutes=30)
        impact_emoji = IMPACT_EMOJIS.get(impact, "📌")

        unique_id = f"FF_{country}_{title.replace(' ', '_')}_{event_dt.strftime('%Y%m%d%H%M')}"

        parsed_events.append({
            "title": title,
            "country": country,
            "impact": impact,
            "impact_emoji": impact_emoji,
            "forecast": forecast,
            "previous": previous,
            "raw_date": raw_date,
            "start_dt": local_dt,
            "end_dt": end_dt,
            "unique_id": unique_id,
            "time_str": local_dt.strftime("%I:%M %p"),
            "date_str": local_dt.strftime("%Y-%m-%d"),
        })

    # Sort events chronologically by start_dt
    parsed_events.sort(key=lambda x: x["start_dt"])
    return parsed_events

def format_forex_telegram_message(events: List[Dict[str, Any]], header_title: Optional[str] = None) -> str:
    """Format parsed Forex events into a Telegram Markdown message."""
    if not events:
        return "📅 *কোনো গুরুত্বপূর্ণ ফরেক্স নিউজ পাওয়া যায়নি।* (আজ কোনো High বা Medium Impact ইভেন্ট নেই)।"

    lines = []
    if header_title:
        lines.append(f"📊 *{header_title}*\n")
    else:
        first_date = events[0]["date_str"]
        lines.append(f"📊 *Forex Factory ইকোনমিক ক্যালেন্ডার ({first_date})*\n")

    for ev in events:
        time_part = f"⏰ `{ev['time_str']}`"
        curr_part = f"*{ev['country']}*"
        impact_part = f"{ev['impact_emoji']} {ev['impact']}"
        title_part = f"*{ev['title']}*"
        
        info_parts = []
        if ev['forecast']:
            info_parts.append(f"Forecast: `{ev['forecast']}`")
        if ev['previous']:
            info_parts.append(f"Prev: `{ev['previous']}`")
        data_str = f" ({', '.join(info_parts)})" if info_parts else ""

        lines.append(f"• {time_part} | {ev['impact_emoji']} {curr_part}: {title_part}{data_str}")

    lines.append("\n_🔴 High Impact | 🟠 Medium Impact_")
    lines.append("🔔 _Google Calendar-এ স্বয়ংক্রিয় রিমাইন্ডার সেট করা হয়েছে।_")
    return "\n".join(lines)

if __name__ == "__main__":
    print("Fetching today's forex news...")
    today_events = get_forex_events(min_impact="Medium")
    print(f"Found {len(today_events)} events today.")
    print(format_forex_telegram_message(today_events))
