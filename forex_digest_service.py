"""
Forex Digest & Institutional Intelligence Reporting Service
Compiles daily macroeconomic wrap-ups and generates comprehensive weekly PDF intelligence reports.
"""

import sys
import datetime
import zoneinfo
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import DEFAULT_TIMEZONE, FOREX_CURRENCIES, REPORTS_DIR
import forex_service
import forex_news_monitor
import report_generator
import chart_generator
import database
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from llm_manager import MultiTierLLMManager

logger = logging.getLogger(__name__)

_llm_instance: Optional[MultiTierLLMManager] = None

def get_llm():
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = MultiTierLLMManager()
    return _llm_instance

def search_market_intel(query: str, max_items: int = 3) -> List[str]:
    """Search Google News RSS for real-time market analysis, forecasts, and social trader commentary."""
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        items = []
        for i in root.findall(".//item")[:max_items]:
            t = i.find("title")
            if t is not None and t.text:
                items.append(t.text.strip())
        return items
    except Exception as e:
        logger.warning(f"Market search failed for '{query}': {e}")
        return []

def generate_daily_digest(target_date: Optional[datetime.date] = None, tz_name: str = DEFAULT_TIMEZONE) -> str:
    """
    Generates an executive multi-asset evening wrap-up and NEXT-DAY price movement prediction
    across Forex, Metals (Gold/Silver), and Futures/Indices (S&P 500, Crude Oil), enriched with
    real-time Wall Street and X.com / FinTwit trader sentiment.
    """
    llm = get_llm()

    try:
        local_tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        local_tz = zoneinfo.ZoneInfo("Asia/Dhaka")

    if target_date is None:
        target_date = datetime.datetime.now(local_tz).date()

    tomorrow_date = target_date + datetime.timedelta(days=1)

    # 1. Economic events for today & tomorrow
    today_events = forex_service.get_forex_events(
        target_date=target_date,
        min_impact="Low",
        currencies=FOREX_CURRENCIES,
        tz_name=tz_name
    )
    tomorrow_events = forex_service.get_forex_events(
        target_date=tomorrow_date,
        min_impact="Medium",
        currencies=FOREX_CURRENCIES,
        tz_name=tz_name
    )

    # 2. Breaking Forex news from monitor
    recent_news = forex_news_monitor.fetch_latest_forex_news(limit=6)

    # 3. Targeted live market intelligence searches (Metals, Futures, Forex, Social / X.com sentiment)
    metals_intel = search_market_intel("gold price forecast technical levels XAU USD", max_items=3)
    futures_intel = search_market_intel("Nasdaq 100 S&P 500 futures crude oil forecast technical levels", max_items=4)
    forex_intel = search_market_intel("forex EUR USD USD JPY outlook technical levels", max_items=3)
    sentiment_intel = search_market_intel("forex gold technical analysis sentiment x.com", max_items=3)

    # Build context for LLM
    event_lines = []
    for ev in today_events:
        forecast_str = f", Forecast: {ev['forecast']}" if ev['forecast'] else ""
        prev_str = f", Prev: {ev['previous']}" if ev['previous'] else ""
        event_lines.append(f"- [{ev['impact']}] {ev['country']} {ev['title']} at {ev['time_str']}{forecast_str}{prev_str}")

    tomorrow_event_lines = []
    for ev in tomorrow_events:
        forecast_str = f", Forecast: {ev['forecast']}" if ev['forecast'] else ""
        tomorrow_event_lines.append(f"- [{ev['impact']}] {ev['country']} {ev['title']} at {ev['time_str']}{forecast_str}")

    news_lines = [f"- {n['title']}" for n in recent_news]

    events_context = "\n".join(event_lines) if event_lines else "No major economic releases."
    tomorrow_context = "\n".join(tomorrow_event_lines) if tomorrow_event_lines else "No high-impact releases scheduled."
    news_context = "\n".join(news_lines) if news_lines else "No breaking headlines."

    metals_context = "\n".join([f"- {m}" for m in metals_intel]) if metals_intel else "Steady metal trading."
    futures_context = "\n".join([f"- {f}" for f in futures_intel]) if futures_intel else "Moderate futures volatility."
    forex_search_context = "\n".join([f"- {fx}" for fx in forex_intel]) if forex_intel else "Range-bound forex."
    sentiment_context = "\n".join([f"- {s}" for s in sentiment_intel]) if sentiment_intel else "Neutral sentiment on X/socials."

    prompt = f"""You are an elite Institutional Global Macro Strategist and Quantitative Trader at a top Wall Street fund.
Analyze today's macroeconomic developments ({target_date.strftime('%A, %B %d, %Y')}), combine recent news, and produce a high-value, actionable NEXT-DAY PRICE MOVEMENT PREDICTION and Evening Wrap-Up for tomorrow ({tomorrow_date.strftime('%A, %B %d, %Y')}).

Context Data:
=== Economic Releases Today ===
{events_context}

=== High/Medium Releases Tomorrow ===
{tomorrow_context}

=== Today's Breaking News Headlines ===
{news_context}

=== Metals Intelligence (Gold / Silver) ===
{metals_context}

=== Futures & Commodities Intelligence (Nasdaq 100 / S&P 500 / Crude Oil) ===
{futures_context}

=== Forex Intelligence ===
{forex_search_context}

=== Social Media & Trader Sentiment (X.com / Wall Street) ===
{sentiment_context}

CRITICAL INSTITUTIONAL PREDICTION MANDATE:
1. This is a comprehensive, institutional multi-page daily forecast and evening intelligence briefing. DO NOT write short 1-line summaries.
2. Every single asset must be analyzed with full multi-sentence paragraphs (at least 3 to 4 sentences) detailing directional bias, expected ranges with exact support & resistance levels, underlying fundamental catalysts, and institutional execution action plans.
3. Write in natural, fluent, elegant Bengali (বিশুদ্ধ ও প্রাতিষ্ঠানিক বাংলা ভাষা)। কোনো শব্দ বা প্রত্যয়ের মাঝে অপ্রয়োজনীয় হাইফেন ব্যবহার করবেন না (যেমন: 'প্রজেকশনে', 'মুদ্রাস্ফীতি লক্ষ্যমাত্রায়', 'ফেডের' ইত্যাদি স্বাভাবিকভাবে লিখবেন)।
4. Do not use raw emojis in headers.

Strictly structure the report with the following markdown layout:

# দৈনিক মার্কেট পূর্বাভাস ও প্রাইস মুভমেন্ট ডাইজেস্ট

---

## ১. গ্লোবাল ম্যাক্রো চালচিত্র ও ট্রেডার সেন্টিমেন্ট (Macro & Trader Sentiment)
[সারাদিনের প্রধান অর্থনৈতিক ঘটনা, ফেড ও অন্যান্য কেন্দ্রীয় ব্যাংকের নীতিগত প্রতিক্রিয়া এবং আগামীকালের প্রভাব নিয়ে পূর্ণাঙ্গ বিশ্লেষণ।]
- **ম্যাক্রো প্রেক্ষাপট ও সেন্ট্রাল ব্যাংক:** আজকের প্রকাশিত ডেটা, বন্ড মার্কেট ও ফেডের সম্ভাব্য গতিপথ নিয়ে পূর্ণাঙ্গ প্যারাগ্রাফ।
- **ওয়াল স্ট্রিট ও ট্রেডার সেন্টিমেন্ট:** ওয়াল স্ট্রিট ও সোশ্যাল ট্রেডারদের (X.com) সেন্টিমেন্ট, রিস্ক-অন বনাম রিস্ক-অফ প্রবাহ।

---

## ২. মেটালস পূর্বাভাস ও প্রাইস রেঞ্জ (Metals: Gold & Silver)

### Gold (XAU/USD)
- **সম্ভাব্য গতিপথ ও বায়াস:** বুলিশ / বেয়ারিশ / কনসোলিডেশন
- **প্রত্যাশিত রেঞ্জ ও কী লেভেল:** সাপোর্ট ($... - $...) ও রেজিস্ট্যান্স ($... - $...)
- **মূল অনুঘটক (Catalysts):** কেন এই মুভমেন্ট প্রত্যাশিত (ট্রেজারি ইল্ড, ডলার ইনডেক্স, নিরাপদ বিনিয়োগ চাহিদা ও ভূ-রাজনীতি নিয়ে বিস্তারিত আলোচনা)
- **ট্রেডিং অ্যাকশন প্ল্যান:** কোন লেভেল টেস্টে প্রাতিষ্ঠানিক এন্ট্রি ও পুলব্যাক কৌশল

### Silver (XAG/USD)
- **সম্ভাব্য গতিপথ ও বায়াস:** বুলিশ / বেয়ারিশ / রেঞ্জ
- **প্রত্যাশিত রেঞ্জ ও কী লেভেল:** সাপোর্ট ($... - $...) ও রেজিস্ট্যান্স ($... - $...)
- **মূল অনুঘটক ও ট্রেডিং রোডম্যাপ:** ইন্ডাস্ট্রিয়াল চাহিদা, গোল্ড/সিলভার রেশিও এবং ট্রেডিং কৌশল

---

## ৩. ফিউচার্স ও স্টক ইনডেক্স পূর্বাভাস (Nasdaq 100, S&P 500 & Crude Oil)

### Nasdaq 100 (NAS100 / US100)
- **সম্ভাব্য গতিপথ ও বায়াস:** বুলিশ / বেয়ারিশ / কনসোলিডেশন
- **কী পিভট ও টেকনিক্যাল লেভেল:** সাপোর্ট (... - ...) ও রেজিস্ট্যান্স (... - ...)
- **মেগা-ক্যাপ ও এআই ড্রাইভার্স:** Apple, Nvidia, Microsoft ও এআই সেক্টর সেন্টিমেন্ট এবং বন্ড ইল্ড প্রভাব
- **ট্রেডিং দৃষ্টিভঙ্গি:** প্রাতিষ্ঠানিক রোডম্যাপ ও আগামীকালের কি-লেভেল প্ল্যান

### S&P 500 Futures (US500)
- **সম্ভাব্য গতিপথ ও টেকনিক্যাল রেঞ্জ:** সাপোর্ট (... - ...) ও রেজিস্ট্যান্স (... - ...)
- **ইকুইটি সেন্টিমেন্ট ও ক্যাটালাইস্ট:** আর্নিংস ও রিস্ক সেন্টিমেন্ট প্রবাহ

### US Crude Oil Futures (WTI / Brent)
- **সম্ভাব্য গতিপথ ও টেকনিক্যাল রেঞ্জ:** সাপোর্ট ($... - $...) ও রেজিস্ট্যান্স ($... - $...)
- **তেলের ম্যাক্রো অনুঘটক:** ওপেক প্লাস ও ভূ-রাজনৈতিক ঝুঁকির বিশ্লেষণ

### US 10-Year Treasury Yields & DXY
- **বন্ড ইল্ড ও ডলার ইনডেক্স:** ইল্ডের প্রত্যাশিত রেঞ্জ ও গ্লোবাল মার্কেটে এর দিকনির্দেশনা

---

## ৪. প্রধান ফরেক্স পেয়ার পূর্বাভাস (Forex Majors Roadmaps)

### Euro (EUR/USD)
- **আগামীকালের রোডম্যাপ ও টেকনিক্যাল রেঞ্জ:** সাপোর্ট (... - ...) ও রেজিস্ট্যান্স (... - ...)
- **ম্যাক্রো চালচিত্র ও সেশন স্ট্র্যাটেজি:** লন্ডন ও নিউইয়র্ক সেশনের আউটলুক ও ট্রেডিং রোডম্যাপ

### British Pound (GBP/USD)
- **আগামীকালের রোডম্যাপ ও টেকনিক্যাল রেঞ্জ:** সাপোর্ট (... - ...) ও রেজিস্ট্যান্স (... - ...)
- **ম্যাক্রো চালচিত্র ও ট্রেডিং রোডম্যাপ:** ব্যাংক অব ইংল্যান্ড ও যুক্তরাজ্যের ডাটা প্রভাব

### Japanese Yen (USD/JPY)
- **আগামীকালের রোডম্যাপ ও টেকনিক্যাল রেঞ্জ:** সাপোর্ট (... - ...) ও রেজিস্ট্যান্স (... - ...)
- **ম্যাক্রো চালচিত্র ও ইন্টারভেনশন ঝুঁকি:** ক্যারি ট্রেড ও বিওজে ফ্যাক্টর

### Commodity Currencies (USD/CAD & AUD/USD)
- **আগামীকালের রোডম্যাপ ও দিকনির্দেশনা:** কমোডিটি ও সেন্ট্রাল ব্যাংক পলিসি বিশ্লেষণ

---

## ৫. রিস্ক ম্যানেজমেন্ট ও ইনভ্যালিডেশন গাইড (Trading Strategy & Risk)

### কী ইনভ্যালিডেশন লেভেলস:
- কোন কোন টেকনিক্যাল লেভেল ভেঙে গেলে এই পূর্বাভাস বাতিল হবে তার স্পষ্ট তালিকা।

### প্রাতিষ্ঠানিক ঝুঁকি ব্যবস্থাপনা:
- **ক্যাপিটাল প্রিজার্ভেশন (Capital Preservation):** সুদের হারের বর্তমান অস্থিরতায় প্রতি ট্রেডে একাউন্ট ইকুইটির ১% থেকে ১.৫%-এর বেশি ঝুঁকি না নেওয়ার নিয়ম।
- **বন্ড ইল্ড ট্র্যাকিং:** ইল্ডের সাথে কারেন্সির কোরিলেশন মনিটরিং।
- **স্টপ-লস ও টেক-প্রফিট ডিসিপ্লিন:** নিউজ স্পাইকের বিপরীতে স্ট্রিক্ট স্টপ-লস ও আংশিক প্রফিট বুকিং (Partial TP) নির্দেশনা।

গোপনীয় ও নির্ভরযোগ্য তথ্যসমৃদ্ধ — প্রস্তুত করেছে Goodushh পার্সোনাল এআই সহকারী।"""

    try:
        digest_text, provider, _ = llm.generate_response(prompt=prompt)
        return digest_text
    except Exception as e:
        logger.error(f"Failed to generate daily digest: {e}")
        return f"❌ দৈনিক ডাইজেস্ট ও পূর্বাভাস তৈরি করা যায়নি: {str(e)}"

def generate_weekly_intelligence_report(filename_prefix: str = "Weekly_Forex_Report") -> Path:
    """
    Generates a full institutional multi-page weekly intelligence PDF report,
    synthesizing all weekly economic calendar outcomes, all breaking news across the week,
    and embedding illustrated technical range and currency strength charts.
    """
    llm = get_llm()

    # 1. Weekly Economic Calendar
    weekly_events = forex_service.get_forex_events(
        target_date="all",
        min_impact="Medium",
        currencies=FOREX_CURRENCIES,
        tz_name=DEFAULT_TIMEZONE
    )

    event_bullets = []
    for ev in weekly_events:
        event_bullets.append(f"- {ev['date_str']} {ev['time_str']} | [{ev['impact']}] {ev['country']} - {ev['title']} (Forecast: {ev['forecast'] or 'N/A'}, Prev: {ev['previous'] or 'N/A'})")

    events_summary = "\n".join(event_bullets) if event_bullets else "No major events recorded."

    # 2. All News Recorded and Analyzed Across the Entire Week
    seen_articles = database.get_recent_seen_news(limit=25)
    db_news_bullets = [f"- {a['title']} ({a.get('published_at', '')})" for a in seen_articles if a.get('title')]
    db_news_summary = "\n".join(db_news_bullets) if db_news_bullets else "No seen news in archive."

    # 3. Targeted Weekly Macro Search Summaries
    weekly_macro_news = search_market_intel("forex market weekly wrap up review Fed FOMC", max_items=4)
    weekly_metals_news = search_market_intel("gold Nasdaq 100 S&P 500 oil weekly market performance review", max_items=4)

    search_macro_summary = "\n".join([f"- {m}" for m in weekly_macro_news]) if weekly_macro_news else "Steady global trade."
    search_metals_summary = "\n".join([f"- {m}" for m in weekly_metals_news]) if weekly_metals_news else "Precious metals steady."

    prompt = f"""You are an Institutional Global Macro & Forex Portfolio Manager.
Compile an authoritative, comprehensive Weekly Forex & Multi-Asset Intelligence Report for the trading week.
Analyze all economic events, breaking news headlines recorded across the entire week, and market catalysts.

Data Sources:
=== High & Medium Economic Releases This Week ===
{events_summary}

=== Breaking News Headlines Recorded This Week ===
{db_news_summary}

=== Global Macro & Central Bank Review ===
{search_macro_summary}

=== Metals, Commodities & Indices (Gold/Silver, Crude Oil, Nasdaq 100, S&P 500) Review ===
{search_metals_summary}

CRITICAL INSTITUTIONAL REPORT MANDATE:
1. This is a comprehensive 4-page executive intelligence report. DO NOT shorten, summarize, or produce shallow 1-line bullet points.
2. Every asset and every section MUST contain rich, detailed multi-sentence analytical paragraphs (at least 3 to 5 sentences each) with institutional numbers, policy nuances, price levels, and market implications.
3. Write in natural, fluent, elegant Bengali (বিশুদ্ধ ও প্রাতিষ্ঠানিক বাংলা ভাষা)। কোনো শব্দ বা প্রত্যয়ের মাঝে অপ্রয়োজনীয় হাইফেন ব্যবহার করবেন না (যেমন: 'প্রজেকশনে', 'মুদ্রাস্ফীতি লক্ষ্যমাত্রায়', 'ফেডের' ইত্যাদি স্বাভাবিকভাবে লিখবেন)।
4. Do not use raw emojis in headers.

Strictly structure the report with the following markdown layout and headings:

# সাপ্তাহিক ফরেক্স ও মাল্টি-অ্যাসেট ইন্টেলিজেন্স রিপোর্ট

---

## ১. নির্বাহী সারসংক্ষেপ ও পুরো সপ্তাহের ম্যাক্রো চালচিত্র (Weekly Executive Summary)
[একটি সামগ্রিক নির্বাহী ভূমিকা অনুচ্ছেদ যা পুরো সপ্তাহের বৈশ্বিক অর্থনৈতিক গতিপ্রবাহ, কেন্দ্রীয় ব্যাংকগুলোর নীতিগত অবস্থান, ভূ-রাজনৈতিক উত্তাপ এবং ট্রেড পলিসির সামগ্রিক প্রভাব বিশ্লেষণ করবে।]

- **ফেড পলিসি (Federal Reserve):** ফেডের সুদের হার সিদ্ধান্ত, ডট প্লট, জেরোম পাওয়েল ও অন্যান্য গভর্নরদের হকিশ/ডোভিশ অবস্থান, মূল্যস্ফীতি ৩%-এর ওপরে আটকে থাকার ঝুঁকি এবং রাজনৈতিক চাপ নিয়ে বিস্তারিত ৪-৫ লাইনের প্রাতিষ্ঠানিক বিশ্লেষণ।
- **ব্যাংক অব জাপান (BoJ) ও ব্যাংক অব ইংল্যান্ড (BoE):** বিওজে-এর সুদের হার সমন্বয়, যুক্তরাজ্যের সিপিআই মূল্যস্ফীতি ও ব্যাংক অব ইংল্যান্ডের পলিসি ভোট/সিদ্ধান্ত এবং পলিসি ডাইভারজেন্স নিয়ে বিস্তারিত ৪-৫ লাইনের বিশ্লেষণ।
- **ভূ-রাজনীতি ও ট্রেড ওয়ার:** মধ্যপ্রাচ্য সংকট, আন্তর্জাতিক বাণিজ্য শুল্ক ও ট্যারিফ উত্তেজনা, শীর্ষ সম্মেলন ও ভূ-রাজনৈতিক ঝুঁকির পূর্ণাঙ্গ ৪-৫ লাইনের প্রভাব বিশ্লেষণ।

---

## ২. প্রধান কারেন্সি পেয়ার পর্যালোচনা ও আগামী সপ্তাহের বায়াস (Forex Majors Roadmaps)

### US Dollar Index (DXY)
- **ম্যাক্রো চালচিত্র:** ফেডের পলিসি সিদ্ধান্ত, খুচরা বিক্রয় (Retail Sales) ডাটা, ট্রেজারি বন্ড ইল্ড এবং ডলার ইনডেক্সের ফান্ডামেন্টাল গতিপ্রবাহ নিয়ে বিস্তারিত ৩-৪ লাইনের বিশ্লেষণ।
- **প্রযুক্তিগত বায়াস:** বুলিশ (Bullish)। সাপোর্ট ও রেজিস্ট্যান্স লেভেল, চার্ট স্ট্রাকচার এবং আগামী সপ্তাহের টেকনিক্যাল লক্ষ্যমাত্রা নিয়ে পূর্ণাঙ্গ বিশ্লেষণ।

### Euro (EUR/USD)
- **ম্যাক্রো চালচিত্র:** ইউরোজোনের অর্থনৈতিক ডাটা, প্রবৃদ্ধি আউটলুক, ইসিবি প্রেসিডেন্ট ও নীতিনির্ধারকদের অবস্থান এবং সম্ভাব্য শুল্ক ঝুঁকির প্রভাব নিয়ে বিস্তারিত বিশ্লেষণ।
- **প্রযুক্তিগত বায়াস:** বিয়ারিশ (Bearish)। মূল সাপোর্ট ও রেজিস্ট্যান্স লেভেল, কী ব্রেকডাউন পয়েন্ট এবং রেঞ্জ নিয়ে বিস্তারিত টেকনিক্যাল বিশ্লেষণ।

### British Pound (GBP/USD)
- **ম্যাক্রো চালচিত্র:** যুক্তরাজ্যের মুদ্রাস্ফীতি ডাটা, ব্যাংক অব ইংল্যান্ডের অবস্থান, রিটেইল সেলস ও সম্ভাব্য স্ট্যাগফ্লেশন ঝুঁকি নিয়ে বিস্তারিত বিশ্লেষণ।
- **প্রযুক্তিগত বায়াস:** নিউট্রাল থেকে বিয়ারিশ (Neutral to Bearish)। ফেড ও বিওই পলিসি বৈষম্যের প্রভাব এবং আগামী সপ্তাহের টেকনিক্যাল গতিপথ।

### Japanese Yen (USD/JPY)
- **ম্যাক্রো চালচিত্র:** ব্যাংক অব জাপানের পলিসি রেট, মার্কিন বন্ড ইল্ডের প্রভাব ও ডলার/ইয়েনের ক্যারি ট্রেড সুবিধা নিয়ে বিস্তারিত বিশ্লেষণ।
- **প্রযুক্তিগত বায়াস:** উচ্চ অস্থিরতা (High Volatility)। ঊর্ধ্বমুখী টার্গেট ও ব্যাংক অব জাপানের সরাসরি মার্কেট ইন্টারভেনশন ঝুঁকি নিয়ে প্রাতিষ্ঠানিক টেকনিক্যাল রোডম্যাপ।

---

## ৩. মেটালস ও কমোডিটিস সাপ্তাহিক বিশ্লেষণ (Metals & Energy)

### Gold (XAU/USD)
- **ম্যাক্রো ড্রাইভার:** ফেডের সুদের হার ও বন্ড ইল্ড বনাম বৈশ্বিক সেফ-হেভেন হিসেবে সোনার চাহিদা এবং নিরাপদ বিনিয়োগ প্রবাহ নিয়ে বিস্তারিত বিশ্লেষণ।
- **প্রযুক্তিগত দৃষ্টিভঙ্গি:** মূল সাপোর্ট রেঞ্জ, প্রাতিষ্ঠানিক "Buy on Dips" কৌশল ও আগামী সপ্তাহের কী প্রাইস লেভেল নিয়ে স্পষ্ট টেকনিক্যাল দৃষ্টিভঙ্গি।

### Silver (XAG/USD)
- **ম্যাক্রো ড্রাইভার:** ইন্ডাস্ট্রিয়াল ডিমান্ড (Industrial Demand) বনাম উচ্চ সুদের হারের প্রভাব এবং সোনার তুলনায় ভোলাটিলিটি গতিপ্রকৃতি বিশ্লেষণ।
- **প্রযুক্তিগত দৃষ্টিভঙ্গি:** সাইডওয়েজ টু বিয়ারিশ মোমেন্টাম ও বড় পজিশন গ্রহণের ক্ষেত্রে ঝুঁকি নিয়ে টেকনিক্যাল দৃষ্টিভঙ্গি।

### Crude Oil (WTI/Brent)
- **ম্যাক্রো ড্রাইভার:** মধ্যপ্রাচ্যের ভূ-রাজনীতি, সরবরাহ ঝুঁকি এবং ওপেক প্লাসের সরবরাহ নীতির প্রভাব নিয়ে বিস্তারিত বিশ্লেষণ।
- **প্রযুক্তিগত দৃষ্টিভঙ্গি:** রিবাউন্ড সম্ভাবনা, স্পাইক রিস্ক ও প্রাতিষ্ঠানিক সাপোর্ট-রেজিস্ট্যান্স লেভেল নিয়ে টেকনিক্যাল রোডম্যাপ।

---

## ৪. ফিউচার্স ও বৈশ্বিক স্টক ইনডেক্স (Equities & Yields)

### Nasdaq 100 (NAS100) & S&P 500 (US500)
- **আর্নিংস ও রিস্ক সেন্টিমেন্ট:** মেগা-ক্যাপ টেক জায়ান্টস (Apple, Microsoft, Nvidia), সেমিকন্ডাক্টর ও এআই খাতের পারফরম্যান্স, ডিসকাউন্ট রেট ও ইকুইটি মার্কেট ভ্যালুয়েশনের বিস্তারিত বিশ্লেষণ।
- **দৃষ্টিভঙ্গি:** শর্ট-টার্ম কারেকশন ও কনসোলিডেশন রেঞ্জ, আসন্ন ইভেন্টের আগে সতর্কতা ও ইনডেক্স গতিপথ।

### US 10-Year Treasury Yield
- **বন্ড মার্কেট সিগন্যাল:** ট্রেজারি ইল্ডের ঊর্ধ্বমুখী গতি, ফেডের কঠোর অবস্থান, মার্কিন বাজেট ঘাটতি ও সামগ্রিক গ্লোবাল ফাইন্যান্সিয়াল মার্কেটে লিকুইডিটি সংকেত নিয়ে বিস্তারিত বিশ্লেষণ।

---

## ৫. আগামী সপ্তাহের হাই-ইমপ্যাক্ট ক্যালেন্ডার ও রিস্ক ম্যানেজমেন্ট গাইড (Trading Strategy & Risk)

### আসন্ন সপ্তাহের প্রধান ইভেন্টসমূহ:
১. নির্দিষ্ট তারিখ ও হাই-ইমপ্যাক্ট ইভেন্ট/শীর্ষ সম্মেলন ও সম্ভাব্য মার্কেট ইমপ্যাক্ট।
২. গ্লোবাল পিএমআই (PMI) ও ম্যানুফ্যাকচারিং ডাটা আউটলুক।
৩. সেন্ট্রাল ব্যাংক স্পিচ ও মিটিং মিনিটস আউটলুক।

### ইনস্টিটিউশনাল রিস্ক ম্যানেজমেন্ট ও ট্রেডিং স্ট্র্যাটেজি:
- **ক্যাপিটাল প্রিজার্ভেশন (Capital Preservation):** সুদের হারের অস্থিরতায় অতিরিক্ত লিভারেজ (Over-leveraging) সম্পূর্ণ এড়িয়ে চলা এবং প্রতিটি ট্রেডে একাউন্ট ইকুইটির ১% থেকে ১.৫%-এর বেশি ঝুঁকি না নেওয়ার প্রাতিষ্ঠানিক কৌশল।
- **বন্ড ইল্ড ট্র্যাকিং:** ফরেক্স ও কমোডিটি ট্রেডারদের জন্য ইউএস ১০-বছরের বন্ড ইল্ড ৫% থ্রেশহোল্ড মনিটরিং ও কোরিলেশন গাইড।
- **স্টপ-লস ও টেক-প্রফিট ডিসিপ্লিন:** ভূ-রাজনৈতিক হেডলাইনে ৫০-১০০ পিপসের আকস্মিক স্পাইকের বিপরীতে স্ট্রিক্ট স্টপ-লস ও আংশিক প্রফিট বুকিং (Partial TP) নিশ্চিত করার প্রাতিষ্ঠানিক নির্দেশিকা।

গোপনীয় ও নির্ভরযোগ্য তথ্যসমৃদ্ধ — প্রস্তুত করেছে Goodushh পার্সোনাল এআই সহকারী।"""

    logger.info("Generating comprehensive weekly forex report text via Multi-Tier LLM...")
    report_text, provider_used, _ = llm.generate_response(prompt=prompt)

    # Generate high-resolution institutional chart PNG for embedding into PyMuPDF Story
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    chart_file = REPORTS_DIR / f"weekly_chart_{timestamp}.png"
    chart_generator.create_market_range_chart(
        output_path=chart_file,
        chart_title="WEEKLY ASSET RANGE & MACRO DIRECTION MATRIX"
    )
    chart_html = f'<div style="text-align: center; margin: 10px 0;"><img src="{chart_file.name}" width="515" /></div>'
    combined_content = f"{chart_html}\n\n{report_text}"

    title = "সাপ্তাহিক ফরেক্স ও মাল্টি-অ্যাসেট ইন্টেলিজেন্স রিপোর্ট"
    pdf_path = report_generator.generate_pdf_report(
        title=title,
        text_content=combined_content,
        filename_prefix=filename_prefix
    )
    logger.info(f"Weekly Forex illustrated PDF report generated at: {pdf_path}")
    return pdf_path

def generate_daily_forecast_pdf(target_date: Optional[datetime.date] = None, filename_prefix: str = "Market_Forecast") -> Path:
    """
    Generates a full illustrated Next-Day Market Movement Forecast PDF with embedded
    technical price range and sentiment charts.
    """
    forecast_text = generate_daily_digest(target_date)

    # Generate high-resolution institutional chart PNG for embedding into PyMuPDF Story
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    chart_file = REPORTS_DIR / f"daily_chart_{timestamp}.png"
    chart_generator.create_market_range_chart(
        output_path=chart_file,
        chart_title="DAILY TECHNICAL RANGE & DIRECTION MATRIX"
    )
    chart_html = f'<div style="text-align: center; margin: 10px 0;"><img src="{chart_file.name}" width="515" /></div>'
    combined_content = f"{chart_html}\n\n{forecast_text}"

    title = "দৈনিক মার্কেট পূর্বাভাস ও প্রাইস মুভমেন্ট ডাইজেস্ট"
    pdf_path = report_generator.generate_pdf_report(
        title=title,
        text_content=combined_content,
        filename_prefix=filename_prefix
    )
    logger.info(f"Daily illustrated forecast PDF report generated at: {pdf_path}")
    return pdf_path

if __name__ == "__main__":
    print("Testing Daily Digest...")
    digest = generate_daily_digest()
    print("\n--- Daily Digest Output ---\n")
    print(digest)

