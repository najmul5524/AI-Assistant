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

from config import DEFAULT_TIMEZONE, FOREX_CURRENCIES
import forex_service
import forex_news_monitor
import report_generator
from llm_manager import MultiTierLLMManager

logger = logging.getLogger(__name__)

_llm_instance: Optional[MultiTierLLMManager] = None

def get_llm():
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = MultiTierLLMManager()
    return _llm_instance

def generate_daily_digest(target_date: Optional[datetime.date] = None, tz_name: str = DEFAULT_TIMEZONE) -> str:
    """
    Generates an executive single-message daily macroeconomic summary (Wrap-up),
    compiling all news, currency strength, winning/losing pairs, and tomorrow's outlook.
    """
    llm = get_llm()

    try:
        local_tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        local_tz = zoneinfo.ZoneInfo("Asia/Dhaka")

    if target_date is None:
        target_date = datetime.datetime.now(local_tz).date()

    events = forex_service.get_forex_events(
        target_date=target_date,
        min_impact="Low",
        currencies=FOREX_CURRENCIES,
        tz_name=tz_name
    )

    recent_news = forex_news_monitor.fetch_latest_forex_news(limit=6)

    # Build context for LLM
    event_lines = []
    for ev in events:
        forecast_str = f", Forecast: {ev['forecast']}" if ev['forecast'] else ""
        prev_str = f", Prev: {ev['previous']}" if ev['previous'] else ""
        event_lines.append(f"- [{ev['impact']}] {ev['country']} {ev['title']} at {ev['time_str']}{forecast_str}{prev_str}")

    news_lines = [f"- {n['title']}" for n in recent_news]

    events_context = "\n".join(event_lines) if event_lines else "No major economic releases."
    news_context = "\n".join(news_lines) if news_lines else "No breaking headlines."

    prompt = f"""You are a Chief Currency Strategist at a top global investment fund.
Compile a high-impact, beautifully structured Daily Forex Evening Wrap-up for: {target_date.strftime('%A, %B %d, %Y')}.

Economic Releases Today:
{events_context}

Breaking News / Catalysts Today:
{news_context}

Write a clean, executive summary in fluent Bengali formatted with markdown bullet points and emojis:

📋 **দৈনিক ফরেক্স এক্সিকিউটিভ ডাইজেস্ট ({target_date.strftime('%d %B %Y')})**

1. 📊 **কারেন্সি স্ট্রেংথ ও বায়াস (Currency Strength & Bias):**
   - 🟢/🔴/🟡 প্রতিটি প্রধান কারেন্সির (USD, EUR, GBP, JPY) এবং গোল্ডের (Gold/XAUUSD) আজকের অবস্থা ও কারণ।
2. 🎯 **টপ মুভার্স ও পেয়ার ট্রেন্ড (Top Movers):**
   - EUR/USD, GBP/USD, USD/JPY, Gold এর আজকের ডিরেকশন ও মূল মুভমেন্ট।
3. 🔑 **সারাদিনের মূল চালিকাশক্তি (Key Drivers & Macro Theme):**
   - কোন খবর বা ডেটার কারণে বাজারে প্রধান মুভ হয়েছে (১-২ বাক্যে)।
4. 🌅 **আগামীকালের জন্য সেশন প্রস্তুতি (Tomorrow's Session Watch):**
   - আগামীকাল কোন সেশনে (লন্ডন/নিউইয়র্ক) কোন পেয়ারে বড় মুভমেন্ট আসার সম্ভাবনা বেশি।

Keep it concise, actionable, and structured for a professional trader. Avoid fluff."""

    try:
        digest_text, provider, _ = llm.generate_response(prompt=prompt)
        return digest_text
    except Exception as e:
        logger.error(f"Failed to generate daily digest: {e}")
        return f"❌ দৈনিক ডাইজেস্ট তৈরি করা যায়নি: {str(e)}"

def generate_weekly_intelligence_report(filename_prefix: str = "Weekly_Forex_Report") -> Path:
    """
    Generates a full institutional multi-page weekly intelligence PDF report,
    analyzing past week outcomes, upcoming week high-impact catalysts, and instrument roadmaps.
    """
    llm = get_llm()

    weekly_events = forex_service.get_forex_events(
        target_date="all",
        min_impact="Medium",
        currencies=FOREX_CURRENCIES,
        tz_name=DEFAULT_TIMEZONE
    )

    event_bullets = []
    for ev in weekly_events:
        event_bullets.append(f"- {ev['date_str']} {ev['time_str']} | [{ev['impact']}] {ev['country']} - {ev['title']} (Forecast: {ev['forecast'] or 'N/A'}, Prev: {ev['previous'] or 'N/A'})")

    events_summary = "\n".join(event_bullets)

    prompt = f"""You are an Institutional Global Macro & Forex Portfolio Manager.
Generate a comprehensive, authoritative, professional Weekly Forex Intelligence Report.
Write the complete report in high-quality, professional Bengali (বাংলা ভাষায় পূর্ণাঙ্গ ও প্রফেশনাল প্রাতিষ্ঠানিক রিপোর্ট লিখুন)।

Economic Calendar Events for the Period:
{events_summary}

Structure the report with markdown headings (##, ###) and clean bullet points:

# সাপ্তাহিক ফরেক্স ইন্টেলিজেন্স ও মার্কেট আউটলুক রিপোর্ট

## ১. নির্বাহী সারসংক্ষেপ ও ম্যাক্রো ল্যান্ডস্কেপ (Executive Summary)
- বৈশ্বিক মুদ্রাবাজারের সামগ্রিক চিত্র ও সেন্ট্রাল ব্যাংকের নীতিনির্ধারণী প্রভাব।

## ২. প্রধান কারেন্সি ও অ্যাসেট আউটলুক (Major Asset Roadmaps)
- **US Dollar (USD Index / DXY):** ফান্ডামেন্টাল ট্রেন্ড ও দিকনির্দেশনা।
- **Euro (EUR/USD):** ইউরোপীয় কেন্দ্রীয় ব্যাংক ও অর্থনৈতিক প্রবৃদ্ধি।
- **British Pound (GBP/USD):** ব্যাংক অফ ইংল্যান্ড ও ইনফ্লেশন প্রভাব।
- **Japanese Yen (USD/JPY):** ব্যাংক অফ জাপান ও ইন্টারভেনশন ঝুঁকি।
- **Gold (XAU/USD):** নিরাপদ আশ্রয় (Safe Haven) চাহিদা ও সুদের হারের সম্পর্ক।

## ৩. আগামী সপ্তাহের হাই-ইমপ্যাক্ট ইভেন্ট ও ঝুঁকি বিশ্লেষণ (High-Impact Catalysts)
- কোন কোন দিন কোন ইভেন্টগুলোতে সর্বোচ্চ সতর্কতা অবলম্বন করতে হবে।
- প্রত্যাশিত অস্থিরতা (Expected Volatility) বিশ্লেষণ।

## ৪. প্রাতিষ্ঠানিক ট্রেডিং কৌশল ও ঝুঁকি ব্যবস্থাপনা (Trading Strategy & Risk Note)
- পজিশন সাইজিং, টেক-প্রফিট, স্টপ লস ও ক্যাপিটাল সুরক্ষার গাইডলাইন।

Use rigorous financial terminology, clean structure, and insightful analysis."""

    logger.info("Generating weekly forex report text via Multi-Tier LLM...")
    report_text, provider_used, _ = llm.generate_response(prompt=prompt)

    title = "সাপ্তাহিক ফরেক্স ইন্টেলিজেন্স রিপোর্ট"
    pdf_path = report_generator.generate_pdf_report(
        title=title,
        text_content=report_text,
        filename_prefix=filename_prefix
    )
    logger.info(f"Weekly Forex PDF report generated at: {pdf_path}")
    return pdf_path

if __name__ == "__main__":
    print("Testing Daily Digest...")
    digest = generate_daily_digest()
    print("\n--- Daily Digest Output ---\n")
    print(digest)

