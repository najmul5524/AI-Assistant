"""
Forex Factory Breaking News Monitor & AI Market Analyst
Continuously monitors Forex Factory news headlines, analyzes potential market impact,
currency pairs affected, and duration of price movements using Multi-Tier AI,
and dispatches real-time Telegram alerts.
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

# Primary & Real-time RSS endpoints
FF_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q=site:forexfactory.com/news&hl=en-US&gl=US&ceid=US:en"
FXSTREET_NEWS_RSS = "https://www.fxstreet.com/rss/news"

# Maximum age for an article to be eligible for instant breaking news alerts
MAX_BREAKING_NEWS_AGE_HOURS = 3.0

_llm_instance: Optional[MultiTierLLMManager] = None

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
    """Parse RFC 2822 RSS date string into timezone-aware UTC datetime."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None

def fetch_latest_forex_news(limit: int = 15) -> List[Dict[str, Any]]:
    """
    Fetch breaking news articles from Forex Factory and FXStreet real-time feeds.
    Parses timestamps, dedupes titles, and sorts strictly newest first.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }

    endpoints = [FXSTREET_NEWS_RSS, FF_GOOGLE_NEWS_RSS]
    articles = []
    seen_titles = set()

    for url in endpoints:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
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

                    articles.append({
                        "news_id": news_id,
                        "title": clean_title,
                        "link": link,
                        "pub_date": pub_date,
                        "published_dt": dt_obj,
                        "description": desc
                    })
        except Exception as e:
            logger.warning(f"Error fetching/parsing news RSS from {url}: {e}")

    # Sort strictly by publication date, newest first
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    articles.sort(
        key=lambda a: a["published_dt"] or (now_utc - datetime.timedelta(days=365)),
        reverse=True
    )

    return articles[:limit]

def analyze_forex_news_with_ai(headline: str, snippet: str = "") -> str:
    """
    Leverages multi-tier LLM to analyze the breaking Forex news headline
    and predict market impact, affected instruments, duration, and direction.
    """
    llm = get_llm()
    prompt = f"""You are a Senior Wall Street Institutional Forex & Macroeconomic Analyst.
A breaking economic news headline has just been published on Forex Factory:
Headline: "{headline}"
Additional Context: "{snippet[:300] if snippet else 'N/A'}"

Provide a crisp, actionable, and structured analysis in high-quality Bengali (বাংলা ভাষায় পয়েন্ট আকারে দিন):

1. 🚨 **গুরুত্ব (Importance):** [High 🔴 / Medium 🟠 / Low 🟡] — এবং ১ বাক্যে কেন
2. 🎯 **প্রভাবিত পেয়ার ও ইন্সট্রুমেন্ট:** [যেমন: EUR/USD, GBP/USD, USD/JPY, Gold (XAU/USD), US10Y Bond, Stock Index ইত্যাদি যা যা প্রযোজ্য]
3. 📈 **সম্ভাব্য গতিপথ ও দিক (Market Bias):** [কোন পেয়ার বা কারেন্সি শক্তিশালী (Bullish) এবং কোনটি দুর্বল (Bearish) হতে পারে]
4. ⏳ **কখন ইমপ্যাক্ট পড়বে (Timing):** [তাৎক্ষণিক (Immediate) / পরবর্তী সেশনে (Upcoming Session)]
5. ⏱️ **ইমপ্যাক্টের স্থায়িত্ব (Duration):** [যেমন: ১৫-৩০ মিনিটের স্পাইক / ২-৪ ঘণ্টার সেশন মুভ / একাধিক দিনের ট্রেন্ড]
6. 💡 **ট্রেডারদের করণীয় ও সতর্কতা (Trader Note):** [ট্রেডারদের জন্য সংক্ষিপ্ত গুরুত্বপূর্ণ পরামর্শ]

Keep it direct, professional, and clear with clean markdown bullet points."""

    try:
        response_text, provider_used, _ = llm.generate_response(prompt=prompt)
        return response_text
    except Exception as e:
        logger.error(f"LLM news analysis failed: {e}")
        return f"এআই বিশ্লেষণ সম্পন্ন করা যায়নি: {str(e)}"

def format_news_telegram_alert(news_item: Dict[str, Any], ai_analysis: str) -> str:
    """Format breaking news and AI analysis into a Telegram message."""
    title = news_item["title"]
    pub_date = news_item["pub_date"]

    msg_lines = [
        "🚨 *ব্রেকিং ফরেক্স নিউজ অ্যালার্ট & এআই বিশ্লেষণ*",
        "",
        f"📰 *শিরোনাম:* `{title}`",
        f"🕒 *প্রকাশিত:* _{pub_date}_",
        "",
        "📊 *এআই মার্কেট ইমপ্যাক্ট বিশ্লেষণ:*",
        ai_analysis,
        "",
        "🌐 _উৎস: Forex Factory Breaking News_"
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
                # Retry with plain text if markdown formatting has issues
                payload.pop("parse_mode", None)
                requests.post(api_url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to dispatch Telegram message to {uid}: {e}")

def check_and_alert_new_stories(telegram_context=None) -> int:
    """
    Check for new Forex Factory news stories.
    If new unseen story is found, analyze with AI and send alert.
    Returns the count of new stories processed.
    """
    articles = fetch_latest_forex_news(limit=15)
    if not articles:
        return 0

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Filter unseen articles
    unseen = [a for a in articles if not database.is_news_seen(a["news_id"])]
    if not unseen:
        return 0

    # Separate fresh breaking news (< MAX_BREAKING_NEWS_AGE_HOURS) from past news
    fresh_unseen = []
    for art in unseen:
        art_dt = art.get("published_dt")
        if art_dt:
            age_hours = (now_utc - art_dt).total_seconds() / 3600.0
            if age_hours > MAX_BREAKING_NEWS_AGE_HOURS:
                # Silently mark older news as seen without alerting or spending AI quota
                logger.info(f"Silently marking past news as seen ({age_hours:.1f}h old): {art['title']}")
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
        logger.info(f"Analyzing fresh Forex story: {art['title']}")
        analysis = analyze_forex_news_with_ai(art["title"], art["description"])
        
        # Check severity filter: Only dispatch instant alert if High/Medium Impact or critical market catalyst
        title_lower = art["title"].lower()
        is_critical_keyword = any(k in title_lower for k in [
            "rate", "hike", "cut", "cpi", "fomc", "fed", "ecb", "boj", "boe",
            "inflation", "nfp", "gdp", "war", "tariff", "breaking", "urgent", "sanction"
        ])
        is_high_analysis = "high" in analysis.lower() or "🔴" in analysis or "🟠" in analysis

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
            logger.info(f"Filtered low-impact news from instant alert (saved for Daily Wrap-up): {art['title']}")

        database.mark_news_as_seen(art["news_id"], art["title"], art["link"], art["pub_date"])
        processed_count += 1

    return processed_count

if __name__ == "__main__":
    print("Testing Forex News Monitor...")
    items = fetch_latest_forex_news(limit=5)
    print(f"Fetched {len(items)} items:")
    for i, it in enumerate(items, 1):
        print(f"{i}. {it['title']} (ID: {it['news_id']})")
    
    if items:
        print("\nTesting AI Analysis on latest item:")
        print("Item:", items[0]["title"])
        res = analyze_forex_news_with_ai(items[0]["title"])
        print("\nAnalysis Result:\n", res)

