"""
Crude Oil (WTI & Brent) Chronological News & Predictive Analytics Service.
Gathers chronological energy news across ForexFactory, Google News, and Investing.com,
extracts live market technicals for WTI (CL=F) and Brent (BZ=F),
and leverages multi-tier AI to deliver comprehensive Short-Term and Long-Term movement predictions.
"""

import logging
import datetime
import zoneinfo
import re
import html as html_lib
import requests
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Dict, Any, List, Optional, Tuple

from config import DEFAULT_TIMEZONE
import technical_analysis_service as ta_service
import forex_news_monitor
from llm_manager import MultiTierLLMManager

logger = logging.getLogger(__name__)
_llm_instance: Optional[MultiTierLLMManager] = None

def get_llm():
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = MultiTierLLMManager()
    return _llm_instance

def fetch_oil_market_metrics() -> Dict[str, Any]:
    """
    Fetches real-time price, 24h change, day high/low, and technical indicators
    for WTI Crude Oil (CL=F) and Brent Crude Oil (BZ=F).
    """
    results = {}
    tickers = [
        ("wti", "CL=F", "WTI Crude Oil"),
        ("brent", "BZ=F", "Brent Crude Oil")
    ]

    for key, ticker, name in tickers:
        try:
            candles = ta_service.fetch_candles(ticker, interval="1h", range_str="5d")
            if not candles or len(candles) < 2:
                # Fallback to 15m
                candles = ta_service.fetch_candles(ticker, interval="15m", range_str="2d")

            if candles and len(candles) >= 2:
                latest = candles[-1]
                prev = candles[-2]
                curr_price = latest["close"]
                prev_price = prev["close"]
                diff = curr_price - prev_price
                pct_change = (diff / prev_price) * 100 if prev_price else 0.0

                # Compute high and low over the last 24 candles (~24h)
                last_24 = candles[-24:] if len(candles) >= 24 else candles
                high_24h = max(c["high"] for c in last_24)
                low_24h = min(c["low"] for c in last_24)

                # Compute RSI and EMA
                closes = [c["close"] for c in candles]
                rsi_val = ta_service.calculate_rsi(closes)
                ema20 = ta_service.calculate_ema(closes, 20)
                atr_val = ta_service.calculate_atr(candles)

                results[key] = {
                    "ticker": ticker,
                    "name": name,
                    "current_price": round(curr_price, 2),
                    "change": round(diff, 2),
                    "change_pct": round(pct_change, 2),
                    "high_24h": round(high_24h, 2),
                    "low_24h": round(low_24h, 2),
                    "rsi": round(rsi_val, 1) if rsi_val is not None else "N/A",
                    "ema20": round(ema20, 2) if ema20 is not None else "N/A",
                    "atr": round(atr_val, 2) if atr_val is not None else "N/A",
                }
            else:
                results[key] = {"name": name, "ticker": ticker, "current_price": "N/A"}
        except Exception as e:
            logger.warning(f"Error fetching oil technical metrics for {ticker}: {e}")
            results[key] = {"name": name, "ticker": ticker, "current_price": "N/A"}

    return results

def fetch_chronological_oil_news(max_items: int = 15) -> List[Dict[str, Any]]:
    """
    Fetches oil, OPEC, energy, and supply/demand news in chronological order
    from ForexFactory live scraper and Google News commodities RSS feed.
    """
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    collected = []
    seen_titles = set()

    keywords = [
        "oil", "crude", "wti", "brent", "opec", "petroleum", "energy",
        "eia", "refiner", "diesel", "gasoline", "barrel", "tanker", "hormuz", "aramco"
    ]

    # 1. Check ForexFactory Direct News
    try:
        ff_news = forex_news_monitor.fetch_forexfactory_direct_news(limit=50)
        for it in ff_news:
            title = it.get("title", "")
            desc = it.get("description", "")
            title_lower = title.lower()
            desc_lower = desc.lower()

            if any(k in title_lower or k in desc_lower for k in keywords):
                norm = title_lower.strip()
                if norm not in seen_titles:
                    seen_titles.add(norm)
                    collected.append({
                        "title": title,
                        "source": it.get("source", "Forex Factory"),
                        "published_dt": it.get("published_dt"),
                        "pub_date_dhaka": it.get("pub_date_dhaka", ""),
                        "snippet": desc[:250]
                    })
    except Exception as e:
        logger.warning(f"Error checking ForexFactory for oil news: {e}")

    # 2. Check Google News Commodity Wire
    try:
        url = "https://news.google.com/rss/search?q=crude+oil+WTI+Brent+OPEC+inventory+price&hl=en-US&gl=US&ceid=US:en"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code == 200 and resp.text:
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                title_el = item.find("title")
                pub_date_el = item.find("pubDate")
                desc_el = item.find("description")

                if title_el is None or not title_el.text:
                    continue

                raw_title = html_lib.unescape(title_el.text).strip()
                norm = raw_title.lower().strip()
                if norm in seen_titles:
                    continue
                seen_titles.add(norm)

                pub_date_str = pub_date_el.text.strip() if pub_date_el is not None and pub_date_el.text else ""
                dt_obj = forex_news_monitor.parse_article_date(pub_date_str)
                if dt_obj:
                    dhaka_dt = dt_obj.astimezone(dhaka_tz)
                    pub_dhaka = dhaka_dt.strftime("%I:%M %p, %d %b %Y")
                else:
                    pub_dhaka = pub_date_str

                # Clean source from title if format "Headline - Source"
                source_name = "Commodity Wire"
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    clean_head = parts[0].strip()
                    source_name = parts[1].strip()
                else:
                    clean_head = raw_title

                collected.append({
                    "title": clean_head,
                    "source": source_name,
                    "published_dt": dt_obj,
                    "pub_date_dhaka": pub_dhaka,
                    "snippet": ""
                })
    except Exception as e:
        logger.warning(f"Error fetching Google News oil feed: {e}")

    # 3. Sort chronologically: oldest of recent to newest (chronological trajectory)
    collected.sort(
        key=lambda x: x["published_dt"] or (now_utc - datetime.timedelta(days=30)),
        reverse=False # chronological progression: catalyst -> escalation -> current trigger
    )

    return collected[-max_items:]

def generate_oil_prediction_analysis() -> str:
    """
    Synthesizes live technical market prices (WTI & Brent) and chronological energy news
    into a comprehensive Short-Term and Long-Term movement prediction.
    """
    metrics = fetch_oil_market_metrics()
    news_items = fetch_chronological_oil_news(max_items=12)

    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    dhaka_now = datetime.datetime.now(dhaka_tz).strftime("%I:%M %p, %d %B %Y (%A)")

    # Build market data block
    wti = metrics.get("wti", {})
    brent = metrics.get("brent", {})
    wti_line = f"WTI Crude (CL=F): ${wti.get('current_price', 'N/A')} ({wti.get('change_pct', 0):+}% | 24h High: ${wti.get('high_24h', 'N/A')} | 24h Low: ${wti.get('low_24h', 'N/A')} | RSI: {wti.get('rsi', 'N/A')} | EMA20: ${wti.get('ema20', 'N/A')})"
    brent_line = f"Brent Crude (BZ=F): ${brent.get('current_price', 'N/A')} ({brent.get('change_pct', 0):+}% | 24h High: ${brent.get('high_24h', 'N/A')} | 24h Low: ${brent.get('low_24h', 'N/A')})"

    # Build chronological news narrative
    news_lines = []
    for i, it in enumerate(news_items, 1):
        time_str = it.get("pub_date_dhaka") or "Recent"
        news_lines.append(f"{i}. [{time_str}] ({it['source']}) {it['title']}")

    chronological_feed = "\n".join(news_lines) if news_lines else "No breaking oil headlines recorded in the last 24h."

    prompt = f"""You are the Chief Global Commodities Strategist & Senior Energy Macro Analyst at a top Wall Street institutional trading desk.
Current Bangladesh Time: {dhaka_now} (BST / GMT+6).

LIVE OIL MARKET TECHNICAL DATA:
- {wti_line}
- {brent_line}

CHRONOLOGICAL ENERGY & CRUDE OIL HEADLINES (In order of event progression):
{chronological_feed}

TASK:
Provide a robust, institutional, sequential news-driven movement prediction for Crude Oil (WTI & Brent) in professional, fluent Bengali.
Ensure the analysis connects how the chronological news events built up the current market reality, and clearly divides Short-Term and Long-Term outlooks:

### EXACT REPORT STRUCTURE:

1. 🛢️ **তেল বাজারের বর্তমান অবস্থা ও লাইভ স্ন্যাপশট (Live Market Snapshot):**
   - WTI এবং Brent-এর বর্তমান লাইভ প্রাইস, দৈনিক পরিবর্তন (Change %), ডে হাই/লো এবং টেকনিক্যাল মোমেন্টাম (RSI & মুভিং এভারেজ অনুযায়ী)।

2. ⏳ **ঘটনাগুলোর পর্যায়ক্রমিক ও কালানুক্রমিক গতিপথ (Sequential Catalyst Trajectory):**
   - সাম্প্রতিক খবরগুলো কীভাবে একের পর এক এসে তেলের সেন্টিমেন্টকে বর্তমান অবস্থানে নিয়ে এসেছে তার একটি ধারাবাহিক পর্যায়ক্রমিক বিবরণ (যেমন: বৈশ্বিক চাহিদা উদ্বেগ -> ওপেক+ ও ইনভেন্টরি ডেটা -> ভূ-রাজনৈতিক ও শিপিং রিস্ক -> সর্বশেষ ট্রিগার)।

3. ⚡ **স্বল্পমেয়াদী মুভমেন্ট প্রেডিকশন (Short-Term Prediction: ১–৩ দিন / ইন্ট্রাডে):**
   - **ডিরেকশন ও সেন্টিমেন্ট (Bias):** [বুলিশ 🟢 / বেয়ারিশ 🔴 / সাইডওয়েজ বা রেঞ্জ-বাউন্ড 🟡]
   - **প্রত্যাশিত প্রাইস রেঞ্জ (Expected Range):** WTI এবং Brent-এর জন্য সম্ভাব্য ডলার রেঞ্জ (যেমন: $XX.XX - $XX.XX)
   - **মূল টেকনিক্যাল লেভেল:** তাৎক্ষণিক সাপোর্ট (Support) ও রেজিস্ট্যান্স (Resistance) জোন
   - **নিকটবর্তী ক্যাটালাইস্ট:** আগামী ২৪-৭২ ঘণ্টার মধ্যে কোন ইভেন্ট (যেমন: EIA/API ইনভেন্টরি, ডলার সূচক বা বক্তৃতা) সবচেয়ে বড় স্পাইক ঘটাতে পারে

4. 🌐 **দীর্ঘমেয়াদী মুভমেন্ট প্রেডিকশন (Long-Term Prediction: সাপ্তাহিক / মাসিক / Q4):**
   - **কাঠামোগত ম্যাক্রো ট্রেন্ড (Structural Macro Trend):** দীর্ঘমেয়াদে তেলের মূল গতিপথ কোন দিকে
   - **ডিমান্ড-সাপ্লাই ব্যালেন্স (Fundamental Outlook):** ওপেক প্লাস (OPEC+) উৎপাদন নীতি, নন-ওপেক (US) ড্রিলিং, এবং চীন/ইউরোপ/মার্কিন অর্থনৈতিক প্রবৃদ্ধির প্রভাব
   - **টার্গেট প্রাইস জোন (Target Levels):** সম্ভাব্য মধ্যমেয়াদী ও দীর্ঘমেয়াদী টার্গেট জোন

5. ⚖️ **বুলিশ বনাম বেয়ারিশ প্রভাবকের তুলনামূলক মূল্যায়ন (Bullish vs Bearish Forces):**
   - 🟢 **দাম বাড়ানোর চালিকাশক্তি (Bullish Drivers):** [নির্দিষ্ট পয়েন্ট]
   - 🔴 **দাম কমানোর চালিকাশক্তি (Bearish Drivers):** [নির্দিষ্ট পয়েন্ট]

6. 🎯 **ট্রেডারদের স্ট্র্যাটেজি ও ঝুঁকি ব্যবস্থাপনা (Actionable Trading Playbook):**
   - **ইন্ট্রাডে ট্রেডারদের করণীয়:** এন্ট্রি, টেক প্রফিট ও স্টপ লস পরামর্শ
   - **সুইং ও পজিশনাল ট্রেডারদের করণীয়:** ডিপে বাই নাকি রাইজে সেল স্ট্র্যাটেজি
   - **ঝুঁকি সতর্কতা:** অপ্রত্যাশিত স্পাইক বা হেডলাইন ভোল্টিলিটি সামলানোর নিয়ম

Format with clean Markdown, bold headers, and professional bullet points."""

    llm = get_llm()
    try:
        response_text, provider_used, _ = llm.generate_response(prompt=prompt)
        return response_text
    except Exception as e:
        logger.error(f"LLM oil prediction analysis failed: {e}")
        return f"তেলের পর্যায়ক্রমিক বিশ্লেষণ সম্পন্ন করা যায়নি: {str(e)}"

if __name__ == "__main__":
    print("Testing Oil Analytics Service...")
    metrics = fetch_oil_market_metrics()
    print("Metrics:", metrics)
    news = fetch_chronological_oil_news(max_items=5)
    print(f"Fetched {len(news)} chronological oil news items.")
    for n in news:
        print(f" - [{n['pub_date_dhaka']}] {n['title']}")
    
    print("\nGenerating AI Prediction...")
    analysis = generate_oil_prediction_analysis()
    print("\n--- AI ANALYSIS RESULT ---\n")
    print(analysis[:600])
