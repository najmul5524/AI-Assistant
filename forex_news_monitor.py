"""
Forex Factory & Institutional Breaking News Monitor & Real-Time AI Analyst
Continuously monitors Forex Factory directly via high-speed anti-bot HTTP/2 scraper (Priority #1)
alongside secondary institutional wire feeds (FXStreet, Investing.com).
Detects breaking market headlines in real time with zero crawl lag,
filters strictly for High and Medium impact news with direct/long-term market impact,
analyzes which instruments will go UP (Bullish) and DOWN (Bearish),
determines the exact next catalyst/event timeline in Bangladesh Time (BST),
and dispatches real-time Telegram alerts within seconds.
"""

import sys
import json
import html as html_lib
import re
import hashlib
import logging
import datetime
import zoneinfo
import requests
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any, Optional

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None

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

# Maximum age for an article to be eligible for instant breaking news alerts (60 minutes)
MAX_BREAKING_NEWS_AGE_MINUTES = 60.0
MAX_BREAKING_NEWS_AGE_HOURS = MAX_BREAKING_NEWS_AGE_MINUTES / 60.0

# Secondary institutional RSS fallback feeds
SECONDARY_REALTIME_FEEDS = [
    ("FXStreet Breaking", "https://www.fxstreet.com/rss/news"),
    ("Investing.com Forex", "https://www.investing.com/rss/news_25.rss"),
    ("Investing.com Economy", "https://www.investing.com/rss/news_14.rss"),
    ("Investing.com Gold & Commodities", "https://www.investing.com/rss/news_301.rss"),
]

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

def is_duplicate_story(title_candidate: str, reference_titles: List[str]) -> bool:
    """
    Checks if title_candidate refers to the same underlying event as any title in reference_titles.
    Uses normalized keyword set intersection.
    """
    stop_words = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
        "is", "are", "was", "were", "as", "by", "with", "after", "amid",
        "says", "said", "over", "from", "into", "that", "this", "will", "would",
        "could", "should", "not", "new", "news", "report", "reports", "today"
    }
    cand_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', title_candidate.lower())) - stop_words
    if not cand_words:
        return False

    for ref in reference_titles:
        ref_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', ref.lower())) - stop_words
        if not ref_words:
            continue
        common = cand_words.intersection(ref_words)
        if len(common) >= 3 or (len(common) >= 2 and len(common) / min(len(cand_words), len(ref_words)) >= 0.5):
            return True
    return False

def fetch_forexfactory_direct_news(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Priority #1: Directly scrape real-time breaking news from https://www.forexfactory.com/news
    using curl_cffi Safari 15.5 impersonation with timestamp cache-buster to prevent any stale cache.
    Extracts exact headline, source, impact level ('high', 'medium', 'low', ''), and timestamp.
    Sorts strictly newest first.
    """
    if cffi_requests is None:
        logger.warning("curl_cffi is not installed; skipping direct ForexFactory scraper.")
        return []

    import time
    url = f"https://www.forexfactory.com/news?_={int(time.time())}"
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    articles = []

    content = ""
    for attempt in range(2):
        try:
            s = cffi_requests.Session()
            resp = s.get(url, impersonate="safari15_5", timeout=12)
            if resp.status_code == 200 and resp.text:
                content = resp.text
                break
            else:
                logger.warning(f"ForexFactory direct scrape returned status {resp.status_code} (attempt {attempt+1})")
        except Exception as e:
            if attempt == 0:
                logger.debug(f"Retrying ForexFactory direct scrape after error: {e}")
                continue
            logger.warning(f"Error scraping direct ForexFactory news: {e}")

    if not content:
        return []

    try:
        matches = re.findall(r'data-items="([^"]+)"', content)
        stories_by_id = {}

        for m in matches:
            try:
                raw_json = html_lib.unescape(m)
                items = json.loads(raw_json)
                for it in items:
                    st = it if "title" in it else it.get("story", {})
                    sid = st.get("id")
                    if sid and sid not in stories_by_id:
                        stories_by_id[sid] = st
            except Exception:
                continue

        for sid, st in stories_by_id.items():
            raw_title = html_lib.unescape(st.get("title", "")).strip()
            if not raw_title or len(raw_title) < 5:
                continue

            ts = st.get("dateline")
            if ts:
                dt_utc = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                dhaka_dt = dt_utc.astimezone(dhaka_tz)
                pub_date_dhaka = dhaka_dt.strftime("%I:%M %p, %d %b %Y")
                pub_date_str = dt_utc.strftime("%a, %d %b %Y %H:%M:%S GMT")
            else:
                dt_utc = None
                pub_date_dhaka = ""
                pub_date_str = ""

            story_url = st.get("url", "")
            if story_url and not story_url.startswith("http"):
                story_url = f"https://www.forexfactory.com{story_url}"

            raw_source = st.get("source", "Forex Factory")
            source_label = f"Forex Factory ({raw_source})"

            impact_val = str(st.get("impact") or "").strip().lower()

            articles.append({
                "news_id": f"ff_{sid}",
                "title": raw_title,
                "link": story_url,
                "pub_date": pub_date_str,
                "pub_date_dhaka": pub_date_dhaka,
                "published_dt": dt_utc,
                "description": html_lib.unescape(st.get("preview", "")).strip(),
                "source": source_label,
                "impact": impact_val, # 'high', 'medium', 'low', or ''
                "is_forexfactory": True
            })

    except Exception as e:
        logger.warning(f"Error scraping direct ForexFactory news: {e}")

    # Sort strictly newest first
    articles.sort(
        key=lambda x: x["published_dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
        reverse=True
    )
    return articles[:limit]

def fetch_forexfactory_indexed_news(keyword: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Scrapes 7-day archived & breaking news published on ForexFactory using Google News RSS indexing with curl_cffi.
    This guarantees that older stories from yesterday and the past 7 days that rolled off the front page
    are NEVER lost, preserving critical breaking news (e.g. US-Iran Hormuz diplomacy, OPEC, Fed).
    """
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    articles = []
    seen = set()

    queries = []
    if keyword:
        clean_kw = keyword.replace(" ", "+")
        queries.append(f"site:forexfactory.com+{clean_kw}+when:7d")
        queries.append(f"site:forexfactory.com+{clean_kw}")
    queries.append("site:forexfactory.com+when:7d")

    session = None
    if cffi_requests is not None:
        try:
            session = cffi_requests.Session()
        except Exception:
            session = None

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for q in queries:
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        content = None
        for attempt in range(2):
            try:
                if session is not None:
                    resp = session.get(url, impersonate="safari15_5", timeout=10)
                else:
                    resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200 and resp.text:
                    content = resp.content
                    break
            except Exception as e:
                logger.debug(f"Attempt {attempt+1} error fetching FF indexed news '{q}': {e}")

        if not content:
            continue

        try:
            root = ET.fromstring(content)
            for item in root.findall(".//item"):
                title_el = item.find("title")
                pub_date_el = item.find("pubDate")
                link_el = item.find("link")
                if title_el is None or not title_el.text:
                    continue

                raw_title = html_lib.unescape(title_el.text).strip()
                clean_title = re.sub(r'\s*-\s*Forex Factory.*$', '', raw_title, flags=re.IGNORECASE).strip()
                clean_title = clean_title.lstrip('*').strip()

                norm = clean_title.lower()
                if norm in seen or len(clean_title) < 5:
                    continue
                seen.add(norm)

                pub_str = pub_date_el.text.strip() if pub_date_el is not None and pub_date_el.text else ""
                dt_obj = parse_article_date(pub_str)
                pub_dhaka = dt_obj.astimezone(dhaka_tz).strftime("%I:%M %p, %d %b %Y") if dt_obj else pub_str
                story_url = link_el.text.strip() if link_el is not None and link_el.text else ""

                # Auto-assign impact level: High for major market moving catalysts, Medium for others
                is_high = any(k in norm for k in [
                    "war", "truce", "ceasefire", "strike", "attack", "missile", "drone",
                    "sanction", "emergency", "crisis", "surge", "plunge", "record high",
                    "record low", "all-time high", "all time high", "crash", "rally", "fed",
                    "powell", "fomc", "rate cut", "rate hike", "interest rate", "inflation",
                    "cpi", "pce", "recession", "tariff", "trade war", "gdp", "nfp", "jobs report",
                    "opec", "hormuz", "blockade", "reopen", "deal", "sec", "liquidation", "bailout",
                    "yield curve", "debt ceiling", "default", "central bank", "stimulus", "diesel export"
                ])
                impact_val = "high" if is_high else "medium"

                articles.append({
                    "news_id": generate_news_id(clean_title),
                    "title": clean_title,
                    "link": story_url,
                    "pub_date": pub_str,
                    "pub_date_dhaka": pub_dhaka,
                    "published_dt": dt_obj,
                    "description": "",
                    "source": "Forex Factory",
                    "impact": impact_val,
                    "is_forexfactory": True
                })
        except Exception as e:
            logger.debug(f"Error parsing XML for '{q}': {e}")

    # Sort strictly newest first
    articles.sort(
        key=lambda x: x["published_dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
        reverse=True
    )
    return articles[:limit]

def fetch_latest_forex_news(limit: int = 35) -> List[Dict[str, Any]]:
    """
    Fetch breaking news articles.
    Priority #1: ForexFactory Direct (Strictly ONLY High and Medium impact news).
    Priority #2: Secondary institutional feeds (Strictly ONLY High impact news that does NOT match/overlap ForexFactory).
    Deduplicates and sorts strictly newest first.
    """
    seen_titles = set()
    articles = []
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")

    # 1. Fetch Priority #1: ForexFactory Direct (Filter strictly for High and Medium impact)
    ff_articles = fetch_forexfactory_direct_news(limit=60)
    for a in ff_articles:
        impact = a.get("impact", "").lower()
        # Strictly High and Medium impact news only
        if impact in ["high", "medium"]:
            clean_norm = a["title"].strip().lower()
            if clean_norm not in seen_titles:
                seen_titles.add(clean_norm)
                articles.append(a)

    ff_reference_titles = [a["title"] for a in articles]

    # 2. Fetch Secondary Feeds (FXStreet, Investing.com)
    # ONLY High impact news that does NOT match ForexFactory
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"
    }

    for source_name, url in SECONDARY_REALTIME_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=6)
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

                    # Deduplication: If already covered by ForexFactory, skip!
                    if is_duplicate_story(clean_title, ff_reference_titles):
                        continue

                    lower_title = clean_title.lower()
                    if lower_title in seen_titles:
                        continue

                    # Filter for High Impact only
                    title_desc = (clean_title + " " + (desc_el.text if desc_el is not None and desc_el.text else "")).lower()
                    is_high = any(k in title_desc for k in [
                        "rate hike", "rate cut", "fomc", "powell", "inflation", "cpi",
                        "war", "truce", "ceasefire", "strike", "missile", "drone",
                        "hormuz", "blockade", "sanction", "emergency", "crisis",
                        "intervention", "surge", "plunge", "record high", "record low"
                    ])
                    if not is_high:
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
                        "source": source_name,
                        "impact": "high",
                        "is_forexfactory": False
                    })
        except Exception as e:
            logger.debug(f"Error in secondary news feed {source_name}: {e}")

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
    Strictly assesses if news is High (🔴) or Medium (🟠) with direct & long-term market influence.
    If Low (🟡), outputs concise Low classification so it can be filtered out from alerts.
    If High/Medium, provides full institutional breakdown of Bullish/Bearish instruments and Next Catalyst in BST.
    """
    llm = get_llm()
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    dhaka_now = datetime.datetime.now(dhaka_tz).strftime("%I:%M %p, %d %B %Y (%A)")

    prompt = f"""You are a Senior Wall Street Institutional Forex & Macroeconomic Analyst.
Current Bangladesh Time: {dhaka_now} (BST / GMT+6).
A breaking financial news headline has just appeared on Forex Factory:
Headline: "{headline}"
Context: "{snippet[:300] if snippet else 'N/A'}"

FIRST, evaluate if this headline represents High Impact (🔴) or Medium Impact (🟠) with direct & long-term market influence (e.g. Interest rates, Central banks, Inflation CPI/PCE, NFP, GDP, Geopolitics, Tariffs, Currency intervention).
If this news is Low Impact (🟡), educational, theoretical, gossip, or has NO direct market-moving significance, output ONLY:
🚨 **গুরুত্ব (Importance):** Low 🟡 — [১ বাক্যে কারণ]
(No further sections needed).

IF AND ONLY IF this is High 🔴 or Medium 🟠 impact news, provide a crisp, actionable analysis in professional Bengali with these exact sections:

1. 🚨 **গুরুত্ব ও ইমপ্যাক্ট (Importance):** [High 🔴 / Medium 🟠] — সরাসরি ও দীর্ঘমেয়াদী প্রভাবের ১ বাক্যে সারসংক্ষেপ
2. 🟢 **কোন কোন ইন্সট্রুমেন্ট উপরে যাবে (Bullish / Upward Bias):**
   - 📈 [ইন্সট্রুমেন্ট, যেমন: Gold (XAU/USD), EUR/USD, GBP/USD, USD Index ইত্যাদি] — কেন উপরে যাবে তার কারণ
3. 🔴 **কোন কোন ইন্সট্রুমেন্ট নিচের দিকে যাবে (Bearish / Downward Bias):**
   - 📉 [ইন্সট্রুমেন্ট, যেমন: USD/JPY, US Dollar (DXY), Crude Oil ইত্যাদি] — কেন নিচে নামবে তার কারণ
4. ⏱️ **পরবর্তী ফলো-আপ ও সময়সূচি (Next Follow-up - Date & Time in BST):**
   - [এই নিউজের ধারাবাহিকতায় পরবর্তী ফলো-আপ আপডেট কখন আসবে — যেমন: সেন্ট্রাল ব্যাংক পলিসি মিটিং, স্পিচ, প্রেস কনফারেন্স বা পরবর্তী গুরুত্বপূর্ণ ডেটা। **অবশ্যই বাংলাদেশ সময় (BST) অনুযায়ী সুনির্দিষ্ট তারিখ, দিন এবং সময় (ঘণ্টা-মিনিট) উল্লেখ করুন (যেমন: ২৯ সেপ্টেম্বর ২০২৬, মঙ্গলবার রাত ০৮:৩০ PM BST)**]
5. ⏳ **সরাসরি ও দীর্ঘমেয়াদী প্রভাব (Direct & Long-term Impact):**
   - [মার্কেটে সরাসরি তাৎক্ষণিক কী প্রভাব পড়বে এবং আগামী দিন বা সপ্তাহে দীর্ঘমেয়াদী প্রভাব কী হবে, মুভমেন্ট রেঞ্জ ও পিপস]
6. 💡 **ট্রেডারদের করণীয় ও সতর্কতা (Actionable Trader Note):**
   - [ট্রেডারদের জন্য সংক্ষিপ্ত ও সুনির্দিষ্ট সতর্কবার্তা]

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
    source = news_item.get("source", "Forex Factory")
    pub_date = news_item.get("pub_date_dhaka") or news_item.get("pub_date")

    msg_lines = [
        "⚡ *FOREX FACTORY REAL-TIME BREAKING NEWS & AI ANALYSIS*",
        "",
        f"📰 *শিরোনাম:* `{title}`",
        f"🕒 *প্রকাশের সময়:* _{pub_date} (বাংলাদেশ সময়)_",
        "",
        "📊 *মার্কেট ডিরেকশন ও প্রভাব বিশ্লেষণ:*",
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

def is_low_impact_analysis(analysis_text: str) -> bool:
    """
    Determines if the AI analysis classified the news as Low Impact.
    Low-impact news is strictly filtered out and never sent to Telegram.
    """
    text_clean = analysis_text.strip()
    # Check explicit Low impact indicators
    if "Low 🟡" in text_clean or "low 🟡" in text_clean:
        return True
    
    first_two_lines = "\n".join(text_clean.splitlines()[:3]).lower()
    if "গুরুত্ব (importance): low" in first_two_lines or "গুরুত্ব: low" in first_two_lines:
        return True
    if "low 🟡" in first_two_lines:
        return True

    # Must contain High (🔴) or Medium (🟠) marker to qualify as actionable market-moving news
    has_high_or_med = ("🔴" in text_clean or "🟠" in text_clean or "high" in first_two_lines or "medium" in first_two_lines)
    if not has_high_or_med:
        return True

    return False

def check_and_alert_new_stories(telegram_context=None) -> int:
    """
    Check for new Forex Factory & breaking news stories in real time.
    Priority #1 is given to Forex Factory direct feeds.
    Strictly filters for High and Medium impact news with direct, long-term market influence.
    If new unseen High/Medium story is found, analyzes with AI and dispatches instant alert.
    Returns the count of new stories alerted.
    """
    # Check scheduled calendar event milestones
    try:
        check_and_alert_calendar_events(telegram_context)
    except Exception as cal_err:
        logger.debug(f"Calendar milestone check note: {cal_err}")

    articles = fetch_latest_forex_news(limit=25)
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
                database.mark_news_as_seen(art["news_id"], art["title"], art["link"], art["pub_date"], impact=art.get("impact", ""), description=art.get("description", ""))
                continue
        fresh_unseen.append(art)

    # Check if this is the very first initialization of the database table
    with database.get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM seen_news")
        total_seen = c.fetchone()[0]

    # On first run, mark all except the single latest fresh item to prevent initial flood
    if total_seen == 0 and len(fresh_unseen) > 1:
        logger.info(f"First-time news initialization: marking {len(fresh_unseen)-1} articles as seen.")
        for a in fresh_unseen[1:]:
            database.mark_news_as_seen(a["news_id"], a["title"], a["link"], a["pub_date"], impact=a.get("impact", ""), description=a.get("description", ""))
        fresh_unseen = fresh_unseen[:1]

    processed_count = 0
    for art in fresh_unseen:
        # Pre-filter: If ForexFactory explicitly marked impact as 'low', skip silently
        if art.get("impact") == "low":
            logger.info(f"Skipping ForexFactory explicit Low-impact news: {art['title']}")
            database.mark_news_as_seen(art["news_id"], art["title"], art["link"], art["pub_date"], impact=art.get("impact", ""), description=art.get("description", ""))
            continue

        logger.info(f"Analyzing fresh breaking Forex story: {art['title']} (Source: {art['source']})")
        analysis = analyze_forex_news_with_ai(art["title"], art["description"])

        # Strict Filter: ONLY High and Medium impact news are sent to Telegram!
        if is_low_impact_analysis(analysis):
            logger.info(f"Filtered out low-impact / non-direct news from instant alert: {art['title']}")
            database.mark_news_as_seen(art["news_id"], art["title"], art["link"], art["pub_date"], impact=art.get("impact", ""), description=art.get("description", ""))
            continue

        # Format and dispatch High/Medium Impact Alert immediately
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

        logger.info(f"⚡ Instant High/Medium impact Telegram alert dispatched for: {art['title']}")
        database.mark_news_as_seen(art["news_id"], art["title"], art["link"], art["pub_date"], impact=art.get("impact", ""), description=art.get("description", ""))
        processed_count += 1

    return processed_count

if __name__ == "__main__":
    print("Testing Forex News Monitor with Direct ForexFactory Scraper...")
    items = fetch_latest_forex_news(limit=5)
    print(f"Fetched {len(items)} items:")
    for i, it in enumerate(items, 1):
        impact_tag = f"[{it.get('impact').upper()}]" if it.get('impact') else ""
        print(f"{i}. [{it['source']}] {impact_tag} {it['title']} ({it['pub_date_dhaka']})")

    if items:
        # Pick the first non-low item for testing
        test_item = next((it for it in items if it.get("impact") != "low"), items[0])
        print(f"\nTesting AI Analysis on item: {test_item['title']}")
        res = analyze_forex_news_with_ai(test_item["title"], test_item["description"])
        print("\nAnalysis Result:\n", res)
        print("\nIs Low Impact Filtered?:", is_low_impact_analysis(res))
