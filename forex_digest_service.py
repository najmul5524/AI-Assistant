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

Write a comprehensive, highly professional, and structured report in fluent Bengali (বাংলায় বিস্তারিত ও স্পষ্ট পয়েন্ট আকারে দিন).
Use markdown headers, emojis, and clear price levels:

📊 **দৈনিক মার্কেট ডাইজেস্ট ও আগামীকালের প্রাইস মুভমেন্ট পূর্বাভাস**
📅 **বিশ্লেষণ তারিখ:** {target_date.strftime('%d %B %Y')} | ⏰ **রিলিজ:** রাত ১০:০০ টা (বাংলাদেশ সময়)

🌐 **১. গ্লোবাল ম্যাক্রো থিম ও ট্রেডার সেন্টিমেন্ট (Macro & X.com Sentiment):**
- সারাদিনের মূল ঘটনা, ফেড/সেন্ট্রাল ব্যাংকের পলিসি প্রভাব এবং সোশ্যাল মিডিয়া (X.com) ও ওয়াল স্ট্রিট ট্রেডারদের বর্তমান মানসিকতা (Bullish/Bearish/Cautious)।

🟡 **২. মেটালস পূর্বাভাস ও প্রাইস মুভমেন্ট (Metals: Gold & Silver):**
- 🪙 **Gold (XAU/USD):**
  - **সম্ভাব্য গতিপথ (Bias):** [🟢 Bullish / 🔴 Bearish / 🟡 Sideways Range]
  - **পরবর্তী দিনের প্রত্যাশিত রেঞ্জ ও কী লেভেল:** সাপোর্ট ($... - $...) ও রেজিস্ট্যান্স ($... - $...)
  - **মূল চালিকাশক্তি (Catalysts):** কেন এই মুভমেন্ট প্রত্যাশিত (Yields, Dollar Index, নিরাপদ বিনিয়োগ চাহিদা)
  - **ট্রেডিং অ্যাকশন প্ল্যান:** কোন লেভেল ভাঙলে বাই বা সেল সুযোগ।
- ⚪ **Silver (XAG/USD):** সাপোর্ট, রেজিস্ট্যান্স এবং সামগ্রিক প্রত্যাশিত দিক।

📈 **৩. সিলেক্টেড ফিউচার্স ও স্টক ইনডেক্স পূর্বাভাস (Futures, Equities & Commodities):**
- 💻 **Nasdaq 100 (NAS100 / US100):**
  - **সম্ভাব্য গতিপথ ও বায়াস:** [🟢 বুলিশ / 🔴 বেয়ারিশ / 🟡 কনসোলিডেশন]
  - **কী পিভট ও টেকনিক্যাল লেভেল:** সাপোর্ট ($... - $...) ও রেজিস্ট্যান্স ($... - $...)
  - **ড্রাইভার:** মেগা-ক্যাপ টেক স্টকস (Apple, Nvidia, Microsoft), এআই সেক্টর সেন্টিমেন্ট এবং বন্ড ইল্ড।
- 🇺🇸 **S&P 500 (US500) Futures:**
  - **সম্ভাব্য দিক ও সেন্টিমেন্ট:** [বুলিশ / বেয়ারিশ / কনসোলিডেশন]
  - **কী পিভট ও টেকনিক্যাল লেভেল:** সাপোর্ট ও রেজিস্ট্যান্স লেভেল।
  - **ড্রাইভার:** আর্নিংস, সুদের হারের প্রভাব ও সামগ্রিক মার্কিন মার্কেট রিস্ক সেন্টিমেন্ট।
- 🛢️ **US Crude Oil Futures (WTI / Brent):**
  - তেলের সম্ভাব্য মুভমেন্ট রেঞ্জ ($... - $...) এবং ওপেক/ভূ-রাজনীতি প্রভাব।
- 🏛️ **US 10-Year Treasury Yields & DXY:** বন্ড ইল্ড এবং ডলার ইনডেক্সের ভবিষ্যৎ গতিপথ।

💱 **৪. প্রধান ফরেক্স পেয়ার পূর্বাভাস (Forex Majors Movement):**
- 🇪🇺 **EUR/USD:** আগামীকালের লন্ডন ও নিউইয়র্ক সেশনের পূর্বাভাস, সাপোর্ট ও রেজিস্ট্যান্স।
- 🇬🇧 **GBP/USD:** ব্যাংক অব ইংল্যান্ড ও যুক্তরাজ্যের ডাটাভিত্তিক সম্ভাব্য মুভমেন্ট।
- 🇯🇵 **USD/JPY:** ইয়েনের দুর্বলতা/শক্তি এবং আপসাইড/ডাউনসাইড টার্গেট।
- 🇨🇦 **USD/CAD & 🇦🇺 AUD/USD:** কমোডিটি ও রিস্ক সেন্টিমেন্টভিত্তিক গতিপথ।

⚠️ **৫. রিস্ক ম্যানেজমেন্ট ও ইনভ্যালিডেশন গাইড (Invalidation & Stop Loss):**
- কোন কী লেভেল ভেঙে গেলে এই পূর্বাভাস ইনভ্যালিড (বাতিল) হবে এবং ট্রেডারদের স্টপ লস ও ক্যাপিটাল সুরক্ষার পরামর্শ।

Make it razor-sharp, actionable, and mathematically logical for a professional day/swing trader."""

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

Write the complete report in high-quality, professional Bengali (বাংলা ভাষায় পূর্ণাঙ্গ ও প্রাতিষ্ঠানিক এক্সিকিউটিভ রিপোর্ট লিখুন)।
Structure with markdown headings (##, ###) and clean bullet points:

# সাপ্তাহিক ফরেক্স ও মাল্টি-অ্যাসেট ইন্টেলিজেন্স রিপোর্ট

## ১. নির্বাহী সারসংক্ষেপ ও পুরো সপ্তাহের ম্যাক্রো চালচিত্র (Weekly Executive Summary)
- চলতি সপ্তাহের কেন্দ্রীয় ব্যাংকগুলোর (Fed, ECB, BoE, BoJ) অবস্থান, সুদের হারের পূর্বাভাস এবং সামগ্রিক বাজারের থিম।

## ২. প্রধান কারেন্সি পেয়ার পর্যালোচনা ও আগামী সপ্তাহের বায়াস (Forex Majors Roadmaps)
- **US Dollar (DXY):** ডলার সূচকের পুরো সপ্তাহের পারফরম্যান্স ও সম্ভাব্য গতিপথ।
- **Euro (EUR/USD):** ইউরোপের ডাটা ও ইসিবি পলিসিভিত্তিক রোডম্যাপ।
- **British Pound (GBP/USD):** ব্যাংক অব ইংল্যান্ড ও মুদ্রাস্ফীতির প্রভাব।
- **Japanese Yen (USD/JPY):** ব্যাংক অব জাপান ও সম্ভাব্য হস্তক্ষেপ (Intervention) ঝুঁকি।

## ৩. মেটালস ও কমোডিটিস সাপ্তাহিক বিশ্লেষণ (Metals & Energy)
- **Gold (XAU/USD):** সোনার সাপ্তাহিক রেঞ্জ, মূল সাপোর্ট, রেজিস্ট্যান্স এবং নিরাপদ বিনিয়োগের প্রভাব।
- **Silver (XAG/USD):** রূপার গতিপথ ও ইন্ডাস্ট্রিয়াল চাহিদা।
- **Crude Oil (WTI/Brent):** ভূ-রাজনীতি ও ওপেক প্লাসের সরবরাহ নীতি।

## ৪. ফিউচার্স ও বৈশ্বিক স্টক ইনডেক্স (Nasdaq 100, S&P 500 & Yields)
- **Nasdaq 100 (NAS100 / US100):** মেগা-ক্যাপ টেক জায়ান্টস (Apple, Microsoft, Nvidia), সেমিকন্ডাক্টর ও এআই খাতের আর্নিংস প্রভাব।
- **S&P 500 (US500):** মার্কিন ইকুইটি মার্কেট সেন্টিমেন্ট, আর্নিংস এবং রিস্ক-অন/রিস্ক-অফ প্রবাহ।
- **US 10-Year Treasury Yield:** বন্ড ইল্ডের গতিপথ ও মার্কেট ভ্যালুয়েশনে এর সংকেত।

## ৫. আগামী সপ্তাহের হাই-ইমপ্যাক্ট ক্যালেন্ডার ও রিস্ক ম্যানেজমেন্ট গাইড (Trading Strategy & Risk)
- আগামী সপ্তাহের কোন কোন দিনে বড় মুভমেন্ট আসবে, টেক-প্রফিট, স্টপ লস ও ক্যাপিটাল সুরক্ষার প্রাতিষ্ঠানিক পরামর্শ।

Use rigorous financial terminology, clean structure, and insightful analysis."""

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

