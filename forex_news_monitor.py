"""
Forex Factory & Institutional Breaking News Monitor & Real-Time AI Analyst
Continuously monitors high-speed institutional Forex & Macro news feeds (FXStreet, Investing.com, Forex Factory),
detects breaking market headlines in real time with zero crawl lag,
analyzes which instruments will go UP (Bullish) and DOWN (Bearish),
determines the exact next catalyst/event timeline in Bangladesh Time (BST),
and dispatches real-time Telegram alerts within seconds.
"""

import sys
import hashlib
import logging
import datetime
import zoneinfo
import requests
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import (
    TELEGRAM_BOT_TOKEN,
    ALLOWED_USER_IDS,
    DEFAULT_TIMEZONE,
)
import database
from llm_manager import MultiTierLLMManager

logger = logging.getLogger(__name__)

# Direct, zero-latency institutional real-time RSS feeds (no slow search indexers)
REALTIME_FEEDS = [
    ("FXStreet Breaking", "https://www.fxstreet.com/rss/news"),
    ("Investing.com Forex", "https://www.investing.com/rss/news_25.rss"),
    ("Investing.com Economy", "https://www.investing.com/rss/news_14.rss"),
    ("Investing.com Gold & Commodities", "https://www.investing.com/rss/news_301.rss"),
]

# Maximum age for an article to be eligible for instant breaking news alerts (30 minutes)
MAX_BREAKING_NEWS_AGE_MINUTES = 30.0

_llm_instance: Optional[MultiTierLLMManager] = None
_ALERTED_CALENDAR_EVENTS = set()

def get_llm():
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = MultiTierLLMManager()
    return _llm_instance

def generate_news_id(title: str) -> str:
    """Generate deterministic hash ID for news article."""
    clean_str = title.strip().lower()
    return hashlib.sha256(clean_str.encode("utf-8")).hexdigest()[:24]

def parse_article_date(date_str: str) -> Optional[datetime.datetime]:
    """Parse various RSS date formats (RFC 2822, SQL timestamp, ISO) into timezone-aware UTC datetime."""
    if not date_str:
        return None
    raw = date_str.strip()

    # 1. Try RFC 2822 (FXStreet, standard RSS)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        pass

    # 2. Try Investing.com format (%Y-%m-%d %H:%M:%S)
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%a, %d %b %Y %H:%M:%S"
    ]:
        try:
            dt = datetime.datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(datetime.timezone.utc)
        except Exception:
            continue

    return None

def fetch_latest_forex_news(limit: int = 15) -> List[Dict[str, Any]]:
    """
    Fetch breaking news articles from zero-latency institutional feeds.
    Parses timestamps, dedupes titles, and sorts strictly newest first.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"
    }

    articles = []
    seen_titles = set()
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")

    for source_name, url in REALTIME_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=7)
            if resp.status_code == 200 and resp.text:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item"):
                    title_el = item.find("title")
                    link_el = item.find("link")
                    pub_date_el = item.find("pubDate")
                    desc_el = item.find("description")

                    if title_el is None or not title_el.text:
                        continue

                    raw_title = title_el.text.strip()
                    clean_title = raw_title.replace(" - Forex Factory", "").strip()

                    # Deduplicate headlines
                    lower_title = clean_title.lower()
                    if lower_title in seen_titles:
                        continue
                    seen_titles.add(lower_title)

                    link = link_el.text.strip() if link_el is not None and link_el.text else ""
                    pub_date = pub_date_el.text.strip() if pub_date_el is not None and pub_date_el.text else ""
                    desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

                    news_id = generate_news_id(clean_title)
                    dt_obj = parse_article_date(pub_date)

                    if dt_obj:
                        dhaka_dt = dt_obj.astimezone(dhaka_tz)
                        pub_date_dhaka = dhaka_dt.strftime("%I:%M %p, %d %b %Y")
                    else:
                        pub_date_dhaka = pub_date

                    articles.append({
                        "news_id": news_id,
                        "title": clean_title,
                        "link": link,
                        "pub_date": pub_date,
                        "pub_date_dhaka": pub_date_dhaka,
                        "published_dt": dt_obj,
                        "description": desc,
                        "source": source_name
                    })
        except Exception as e:
            logger.warning(f"Error fetching/parsing news RSS from {source_name} ({url}): {e}")

    # Sort strictly by publication date, newest first
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    articles.sort(
        key=lambda a: a["published_dt"] or (now_utc - datetime.timedelta(days=365)),
        reverse=True
    )

    return articles[:limit]

def analyze_forex_news_with_ai(headline: str, snippet: str = "") -> str:
    """
    Leverages multi-tier LLM to analyze the breaking Forex news headline.
    Guarantees explicit separation of which instruments will go UP and DOWN,
    and calculates the exact timeline of the next catalyst/meeting in Bangladesh Time.
    """
    llm = get_llm()
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    dhaka_now = datetime.datetime.now(dhaka_tz).strftime("%I:%M %p, %d %B %Y (%A)")

    prompt = f"""You are a Senior Wall Street Institutional Forex & Macroeconomic Analyst.
Current Bangladesh Time: {dhaka_now} (BST / GMT+6).
A breaking financial news headline has just been published on Forex Factory / Wire Feeds:
Headline: "{headline}"
Additional Context: "{snippet[:300] if snippet else 'N/A'}"

Provide a crisp, actionable, institutional analysis in professional Bengali with these exact sections:

1. 🚨 **গুরুত্ব (Importance):** [High 🔴 / Medium 🟠 / Low 🟡] — এবং ১ বাক্যে সারসংক্ষেপ
2. 🟢 **কোন কোন ইন্সট্রুমেন্ট উপরে যাবে (Bullish / Upward Bias):**
   - 📈 [ইন্সট্রুমেন্টের নাম, যেমন: Gold (XAU/USD), EUR/USD, GBP/USD, USD Index ইত্যাদি] — কেন উপরে যাবে তার কারণ
3. 🔴 **কোন কোন ইন্সট্রুমেন্ট নিচের দিকে যাবে (Bearish / Downward Bias):**
   - 📉 [ইন্সট্রুমেন্টের নাম, যেমন: USD/JPY, US Dollar (DXY), ক্রুড অয়েল ইত্যাদি] — কেন নিচে নামবে তার কারণ
4. ⏱️ **পরবর্তী ঘটনা ও সময়সূচি (Next Catalyst - বাংলাদেশ সময়):**
   - [এই নিউজের ধারাবাহিকতায় পরবর্তী ঘটনা কখন ঘটবে — যেমন: সেন্ট্রাল ব্যাংক মিটিং, প্রেস কনফারেন্স, স্পিচ বা পরবর্তী গুরুত্বপূর্ণ ডেটা রিলিজ। **অবশ্যই বাংলাদেশ সময় (BST) অনুযায়ী সুনির্দিষ্ট সময় ও ঘণ্টা-মিনিট উল্লেখ করুন**]
5. ⏳ **মুভমেন্টের স্থায়িত্ব (Duration) ও রেঞ্জ:** [যেমন: তাৎক্ষণিক ১৫-৩০ মিনিটের স্পাইক / পুরো সেশনের ট্রেন্ড / ৫০-৮০ পিপস বা $১৫-$২৫ মুভ]
6. 💡 **ট্রেডারদের করণীয় ও সতর্কতা (Actionable Trader Note):** [ট্রেডারদের জন্য সংক্ষিপ্ত ও সুনির্দিষ্ট সতর্কবার্তা]

Keep it direct, professional, and clear with clean markdown bullet points."""

    try:
        response_text, provider_used, _ = llm.generate_response(prompt=prompt)
        return response_text
    except Exception as e:
        logger.error(f"LLM news analysis failed: {e}")
        return f"এআই বিশ্লেষণ সম্পন্ন করা যায়নি: {str(e)}"

def format_news_telegram_alert(news_item: Dict[str, Any], ai_analysis: str) -> str:
    """Format breaking news and AI analysis into a structured Telegram message."""
    title = news_item["title"]
    source = news_item.get("source", "Forex Factory Wire")
    pub_date = news_item.get("pub_date_dhaka") or news_item.get("pub_date")

    msg_lines = [
        "🚨 *ব্রেকিং মার্কেট নিউজ অ্যালার্ট & রিয়েল-টাইম এআই বিশ্লেষণ*",
        "",
        f"📰 *শিরোনাম:* `{title}`",
        f"🕒 *প্রকাশের সময়:* _{pub_date} (বাংলাদেশ সময়)_",
        "",
        "📊 *মার্কেট ইমপ্যাক্ট, ডিরেকশন ও গতিপথ বিশ্লেষণ:*",
        ai_analysis,
        "",
        f"🌐 _উৎস: {source}_"
    ]
    return "\n".join(msg_lines)

def send_telegram_direct(text: str):
    """Direct HTTP dispatcher for Telegram notifications."""
    if not TELEGRAM_BOT_TOKEN or not ALLOWED_USER_IDS:
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for uid in ALLOWED_USER_IDS:
        try:
            payload = {
                "chat_id": uid,
                "text": text,
                "parse_mode": "Markdown"
            }
            resp = requests.post(api_url, json=payload, timeout=10)
            if resp.status_code != 200:
                payload.pop("parse_mode", None)
                requests.post(api_url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to dispatch Telegram message to {uid}: {e}")

def check_and_alert_calendar_events(telegram_context=None) -> int:
    """
    Checks upcoming high-impact economic calendar events.
    If a High/Medium impact event is within 15 minutes of release, dispatches a pre-news alert with Bangladesh Time.
    """
    import forex_service
    events = forex_service.get_forex_events(target_date="all")
    if not events:
        return 0

    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    now_dhaka = datetime.datetime.now(dhaka_tz)
    dispatched = 0

    for ev in events:
        impact = ev.get("impact", "")
        if impact not in ["High", "Medium"]:
            continue

        start_dt = ev.get("start_dt")
        if not start_dt:
            continue

        diff_seconds = (start_dt - now_dhaka).total_seconds()
        # Check window: 1 to 15 minutes before event
        if 60 <= diff_seconds <= 900:
            event_key = f"{ev['unique_id']}_pre15"
            if event_key in _ALERTED_CALENDAR_EVENTS:
                continue

            _ALERTED_CALENDAR_EVENTS.add(event_key)
            minutes_left = int(diff_seconds // 60)
            msg = (
                f"⏰ *আসন্ন হাই-ইমপ্যাক্ট ইকোনমিক নিউজ অ্যালার্ট ({minutes_left} মিনিট বাকি)!*\n\n"
                f"📊 *ইভেন্ট:* {ev['title']} ({ev['impact_emoji']} {ev['country']})\n"
                f"🕒 *রিলিজের সময়:* `{ev['time_str']}` (বাংলাদেশ সময়)\n"
                f"📈 *পূর্বাভাস (Forecast):* `{ev['forecast'] or 'N/A'}`\n"
                f"📉 *পূর্ববর্তী (Previous):* `{ev['previous'] or 'N/A'}`\n\n"
                f"⚠️ *সতর্কতা:* রিলিজের সময় স্প্রেড বৃদ্ধি ও আকস্মিক লিকুইডিটি স্পাইক হতে পারে। ওপেন পজিশনে স্টপ লস নিশ্চিত করুন।"
            )
            if telegram_context and hasattr(telegram_context, "bot"):
                for uid in ALLOWED_USER_IDS:
                    try:
                        import asyncio
                        asyncio.create_task(
                            telegram_context.bot.send_message(
                                chat_id=uid,
                                text=msg,
                                parse_mode="Markdown"
                            )
                        )
                    except Exception:
                        send_telegram_direct(msg)
            else:
                send_telegram_direct(msg)
            dispatched += 1

    return dispatched

def check_and_alert_new_stories(telegram_context=None) -> int:
    """
    Check for new Forex Factory & breaking news stories in real time.
    If new unseen story is found, analyze with AI and send instant alert.
    Returns the count of new stories processed.
    """
    # Also check scheduled calendar event milestones
    try:
        check_and_alert_calendar_events(telegram_context)
    except Exception as cal_err:
        logger.debug(f"Calendar milestone check note: {cal_err}")

    articles = fetch_latest_forex_news(limit=15)
    if not articles:
        return 0

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Filter unseen articles
    unseen = [a for a in articles if not database.is_news_seen(a["news_id"])]
    if not unseen:
        return 0

    # Separate fresh breaking news (< MAX_BREAKING_NEWS_AGE_MINUTES) from past news
    fresh_unseen = []
    for art in unseen:
        art_dt = art.get("published_dt")
        if art_dt:
            age_minutes = (now_utc - art_dt).total_seconds() / 60.0
            if age_minutes > MAX_BREAKING_NEWS_AGE_MINUTES:
                # Silently mark older news as seen without alerting or causing false delay
                logger.info(f"Silently marking past news as seen ({age_minutes:.1f}m old): {art['title']}")
                database.mark_news_as_seen(art["news_id"], art["title"], art["link"], art["pub_date"])
                continue
        fresh_unseen.append(art)

    # Check if this is the very first initialization of the table
    with database.get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM seen_news")
        total_seen = c.fetchone()[0]

    # On first run, mark all except the single latest fresh item to prevent flooding
    if total_seen == 0 and len(fresh_unseen) > 1:
        logger.info(f"First-time news initialization: marking {len(fresh_unseen)-1} articles as seen.")
        for a in fresh_unseen[1:]:
            database.mark_news_as_seen(a["news_id"], a["title"], a["link"], a["pub_date"])
        fresh_unseen = fresh_unseen[:1]

    processed_count = 0
    for art in fresh_unseen:
        logger.info(f"Analyzing fresh breaking Forex story: {art['title']}")
        analysis = analyze_forex_news_with_ai(art["title"], art["description"])
        
        # Check severity filter: Dispatch instant alert if High/Medium Impact or critical market catalyst
        title_lower = art["title"].lower()
        is_critical_keyword = any(k in title_lower for k in [
            "rate", "hike", "cut", "cpi", "fomc", "fed", "ecb", "boj", "boe",
            "inflation", "nfp", "gdp", "war", "tariff", "breaking", "urgent",
            "gold", "oil", "yield", "dollar", "powell", "lagarde", "recession"
        ])
        is_high_analysis = "high" in analysis.lower() or "🔴" in analysis or "🟠" in analysis or "উৎস" in analysis

        if is_critical_keyword or is_high_analysis:
            alert_msg = format_news_telegram_alert(art, analysis)
            if telegram_context and hasattr(telegram_context, "bot"):
                for uid in ALLOWED_USER_IDS:
                    try:
                        import asyncio
                        asyncio.create_task(
                            telegram_context.bot.send_message(
                                chat_id=uid,
                                text=alert_msg,
                                parse_mode="Markdown"
                            )
                        )
                    except Exception as send_err:
                        logger.warning(f"Error sending via bot context: {send_err}")
                        send_telegram_direct(alert_msg)
            else:
                send_telegram_direct(alert_msg)
            logger.info(f"Dispatched high-impact alert for: {art['title']}")
        else:
            logger.info(f"Filtered low-impact news from instant alert: {art['title']}")

        database.mark_news_as_seen(art["news_id"], art["title"], art["link"], art["pub_date"])
        processed_count += 1

    return processed_count

if __name__ == "__main__":
    print("Testing Forex News Monitor...")
    items = fetch_latest_forex_news(limit=5)
    print(f"Fetched {len(items)} items:")
    for i, it in enumerate(items, 1):
        print(f"{i}. [{it['source']}] {it['title']} ({it['pub_date_dhaka']})")
    
    if items:
        print("\nTesting AI Analysis on latest item:")
        print("Item:", items[0]["title"])
        res = analyze_forex_news_with_ai(items[0]["title"], items[0]["description"])
        print("\nAnalysis Result:\n", res)
