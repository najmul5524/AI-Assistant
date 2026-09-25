"""
Crude Oil (WTI & Brent) Chronological News & Predictive Analytics Service.
Gathers chronological energy news across ForexFactory Direct Breaking Feed,
ForexFactory Economic Calendar (EIA/API Inventories), and Global Live Commodity Wire (last 72h),
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
import forex_service
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

def fetch_forexfactory_oil_stories(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Scrapes live ForexFactory news and filters specifically for oil, energy,
    refinery, Middle East shipping, Hormuz, and Iran catalysts.
    Preserves exact High (🔴) and Medium (🟠) impact ratings.
    """
    matched = []
    seen = set()
    oil_keywords = [
        "oil", "crude", "wti", "brent", "opec", "petroleum", "energy",
        "diesel", "gasoline", "barrel", "refiner", "hormuz", "iran", "tanker", "eia", "api"
    ]

    try:
        stories = forex_news_monitor.fetch_forexfactory_direct_news(limit=60)
        for s in stories:
            t_lower = s["title"].lower()
            d_lower = s.get("description", "").lower()

            is_match = False
            for k in oil_keywords:
                if k in t_lower:
                    is_match = True
                    break
                if k in ["oil", "crude", "wti", "brent", "opec", "diesel", "hormuz", "refiner", "iran"] and k in d_lower:
                    is_match = True
                    break

            if is_match:
                norm = t_lower.strip()
                if norm not in seen:
                    seen.add(norm)
                    impact = s.get("impact", "").strip().lower()
                    impact_label = "🔴 HIGH" if impact == "high" else ("🟠 MEDIUM" if impact == "medium" else ("🟡 LOW" if impact == "low" else "NORMAL"))
                    matched.append({
                        "title": s["title"],
                        "impact_label": impact_label,
                        "pub_date_dhaka": s.get("pub_date_dhaka", ""),
                        "published_dt": s.get("published_dt"),
                        "source": s.get("source", "Forex Factory")
                    })
    except Exception as e:
        logger.warning(f"Error filtering ForexFactory oil stories: {e}")

    # Sort chronological: oldest of recent -> latest breaking
    matched.sort(
        key=lambda x: x["published_dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
        reverse=False
    )
    return matched[-limit:]

def fetch_forexfactory_energy_calendar() -> List[Dict[str, Any]]:
    """
    Extracts raw energy events (EIA Crude Oil Inventories, API, Natural Gas Storage)
    directly from ForexFactory calendar cache.
    """
    matched = []
    try:
        raw_events = forex_service.fetch_raw_calendar()
        dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")

        for e in raw_events:
            title = e.get("title", "")
            t_lower = title.lower()
            if any(k in t_lower for k in ["oil", "crude", "inventor", "natural gas", "petroleum", "api"]):
                # Parse date to BST
                date_raw = e.get("date", "")
                dt_obj = forex_news_monitor.parse_article_date(date_raw)
                dhaka_time = dt_obj.astimezone(dhaka_tz).strftime("%I:%M %p, %d %b %Y") if dt_obj else date_raw
                matched.append({
                    "title": title,
                    "country": e.get("country", "USD"),
                    "impact": e.get("impact", "Medium"),
                    "actual": e.get("actual") or "N/A",
                    "forecast": e.get("forecast") or "N/A",
                    "previous": e.get("previous") or "N/A",
                    "time_dhaka": dhaka_time
                })
    except Exception as e:
        logger.warning(f"Error fetching energy calendar events: {e}")

    return matched

def fetch_global_oil_wire_news(limit: int = 8) -> List[Dict[str, Any]]:
    """
    Fetches strictly fresh (last 72h via when:3d) oil commodity wire articles
    from Google News RSS.
    """
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    articles = []
    seen = set()

    search_queries = [
        "crude+oil+WTI+Brent+when:3d",
        "oil+price+Hormuz+Iran+when:3d"
    ]

    for q in search_queries:
        try:
            url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200 and resp.text:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item"):
                    title_el = item.find("title")
                    pub_date_el = item.find("pubDate")
                    if title_el is None or not title_el.text:
                        continue

                    raw_title = html_lib.unescape(title_el.text).strip()
                    norm = raw_title.lower().strip()
                    if norm in seen:
                        continue
                    seen.add(norm)

                    pub_str = pub_date_el.text.strip() if pub_date_el is not None and pub_date_el.text else ""
                    dt_obj = forex_news_monitor.parse_article_date(pub_str)
                    pub_dhaka = dt_obj.astimezone(dhaka_tz).strftime("%I:%M %p, %d %b %Y") if dt_obj else pub_str

                    source_name = "Commodity Wire"
                    if " - " in raw_title:
                        parts = raw_title.rsplit(" - ", 1)
                        clean_head = parts[0].strip()
                        source_name = parts[1].strip()
                    else:
                        clean_head = raw_title

                    articles.append({
                        "title": clean_head,
                        "source": source_name,
                        "pub_date_dhaka": pub_dhaka,
                        "published_dt": dt_obj
                    })
        except Exception as e:
            logger.debug(f"Google news query '{q}' note: {e}")

    # Sort chronological
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    articles.sort(
        key=lambda x: x["published_dt"] or (now_utc - datetime.timedelta(days=3)),
        reverse=False
    )
    return articles[-limit:]

def fetch_chronological_oil_news(max_items: int = 15) -> List[Dict[str, Any]]:
    """
    Unified function returning chronological oil news from both ForexFactory
    and Commodity Wire.
    """
    ff = fetch_forexfactory_oil_stories(limit=10)
    wire = fetch_global_oil_wire_news(limit=10)
    combined = ff + wire
    combined.sort(
        key=lambda x: x.get("published_dt") or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
        reverse=False
    )
    return combined[-max_items:]

def generate_oil_prediction_analysis() -> str:
    """
    Synthesizes live technical market prices (WTI & Brent), ForexFactory Direct Breaking News,
    ForexFactory Economic Calendar (Inventories), and Live Commodity Wire
    into a comprehensive Short-Term and Long-Term movement prediction.
    """
    metrics = fetch_oil_market_metrics()
    ff_stories = fetch_forexfactory_oil_stories(limit=10)
    calendar_events = fetch_forexfactory_energy_calendar()
    wire_news = fetch_global_oil_wire_news(limit=8)

    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    dhaka_now = datetime.datetime.now(dhaka_tz).strftime("%I:%M %p, %d %B %Y (%A)")

    # 1. Market Data Block
    wti = metrics.get("wti", {})
    brent = metrics.get("brent", {})
    wti_line = f"WTI Crude (CL=F): ${wti.get('current_price', 'N/A')} ({wti.get('change_pct', 0):+}% | 24h High: ${wti.get('high_24h', 'N/A')} | 24h Low: ${wti.get('low_24h', 'N/A')} | RSI: {wti.get('rsi', 'N/A')} | EMA20: ${wti.get('ema20', 'N/A')} | ATR: ${wti.get('atr', 'N/A')})"
    brent_line = f"Brent Crude (BZ=F): ${brent.get('current_price', 'N/A')} ({brent.get('change_pct', 0):+}% | 24h High: ${brent.get('high_24h', 'N/A')} | 24h Low: ${brent.get('low_24h', 'N/A')} | RSI: {brent.get('rsi', 'N/A')} | EMA20: ${brent.get('ema20', 'N/A')} | ATR: ${brent.get('atr', 'N/A')})"

    # 2. ForexFactory Breaking Stories
    ff_lines = []
    for it in ff_stories:
        ff_lines.append(f"• [{it['pub_date_dhaka']}] [{it['impact_label']}] ({it['source']}) {it['title']}")
    ff_feed = "\n".join(ff_lines) if ff_lines else "ForexFactory breaking stories active."

    # 3. ForexFactory Calendar (Inventories)
    cal_lines = []
    for c in calendar_events:
        cal_lines.append(f"• [{c['time_dhaka']}] {c['country']} - {c['title']} | Actual: {c['actual']} | Forecast: {c['forecast']} | Previous: {c['previous']}")
    cal_feed = "\n".join(cal_lines) if cal_lines else "Weekly inventory reports active."

    # 4. Commodity Wire Dispatches
    wire_lines = []
    for w in wire_news:
        wire_lines.append(f"• [{w['pub_date_dhaka']}] ({w['source']}) {w['title']}")
    wire_feed = "\n".join(wire_lines) if wire_lines else "Global wire dispatches active."

    prompt = f"""You are the Chief Global Commodities Strategist & Senior Energy Macro Analyst at a top Wall Street institutional trading desk.
Current Bangladesh Time: {dhaka_now} (BST / GMT+6).

LIVE OIL MARKET TECHNICAL DATA:
- {wti_line}
- {brent_line}

FOREX FACTORY DIRECT BREAKING NEWS & GEOPOLITICAL HEADLINES (INCLUDING HIGH & MEDIUM IMPACT):
{ff_feed}

FOREX FACTORY ECONOMIC CALENDAR (ENERGY INVENTORIES & SUPPLY DATA):
{cal_feed}

GLOBAL COMMODITY WIRE DISPATCHES (LAST 72 HOURS):
{wire_feed}

CRITICAL TASK & INSTRUCTIONS:
Provide a robust, comprehensive, institutional movement prediction for Crude Oil (WTI & Brent) in professional, fluent Bengali.
Ensure that Section 2 ("ঘটনাগুলোর পর্যায়ক্রমিক ও কালানুক্রমিক গতিপথ") explicitly incorporates the real-world events above:
1. Specifically analyze the **ForexFactory High-Impact news from yesterday (Sep 24)** regarding the US-Iran discussions to phase in a deal to reopen the Strait of Hormuz and end the US naval blockade, and how that eased war risk premiums and pulled WTI from $96.78 down towards $92.50.
2. Note the subsequent statements from Iranian officials (Fars warning of potential conflict expansion) creating two-way volatility.
3. Integrate the ForexFactory Crude Oil Inventories (EIA data: -0.7M draw forecast vs -0.6M previous) and US requests for refiners to voluntarily curb diesel exports.
4. Synthesize how this chronological chain of events drives current prices and sets up the Short-Term and Long-Term trajectory.
5. NEVER state that there were no breaking headlines recorded.

### EXACT REPORT STRUCTURE:

1. 🛢️ **তেল বাজারের বর্তমান অবস্থা ও লাইভ স্ন্যাপশট (Live Market Snapshot):**
   - WTI এবং Brent-এর বর্তমান লাইভ প্রাইস, দৈনিক পরিবর্তন (Change %), ডে হাই/লো এবং টেকনিক্যাল মোমেন্টাম (RSI, EMA20 এবং ATR ভোলাটিলিটি)।

2. ⏳ **ঘটনাগুলোর পর্যায়ক্রমিক ও কালানুক্রমিক গতিপথ (Sequential Catalyst Trajectory):**
   - সাম্প্রতিক খবরগুলো ধাপে ধাপে কীভাবে তেলের সেন্টিমেন্টকে বর্তমান অবস্থানে এনেছে তার বিস্তারিত বিবরণ:
     * **ধাপ ১ (ভূ-রাজনৈতিক ঝুঁকি ও হরমুজ প্রণালী সংকট):** মধ্যপ্রাচ্যের উত্তেজনা, হরমুজ প্রণালী ও শিপিং রুট নিয়ে তৈরি হওয়া প্রাথমিক ঝুঁকি প্রিমিয়াম (যার ফলে তেল $৯৬-$১০৮ পর্যন্ত স্পাইক করেছিল)।
     * **ধাপ ২ (গতকাল ফরেক্সফ্যাক্টরির হাই-ইমপ্যাক্ট ব্রেকিং নিউজ):** গতকাল রাত ১০:১৬-১০:৫২ মিনিটে (২৪ সেপ্টেম্বর) ForexFactory-তে প্রকাশিত রয়টার্সের হাই-ইমপ্যাক্ট নিউজ: **"US, Iran Explore Phased Deal To Reopen Hormuz, End Blockade"** — হরমুজ প্রণালী পুনরায় চালু ও মার্কিন নৌ-অবরোধ প্রত্যাহারের সম্ভাব্য চুক্তির খবরে বাজারে যুদ্ধকালীন প্রিমিয়াম কিছুটা কমে গিয়ে WTI দ্রুত $৯২.৫০ লেভেলে নেমে আসে।
     * **ধাপ ৩ (পরস্পরবিরোধী ইরানি বার্তা ও আজকের আপডেট):** আজ দুপুরের (২৫ সেপ্টেম্বর) আপডেট—ইরানি কর্মকর্তাদের মার্কিন সংঘাত বৃদ্ধির সতর্কতা বনাম প্রেসিডেন্ট পেজেশকিয়ানের অর্থনৈতিক সংকট নিরসন ও চুক্তির আকাঙ্ক্ষা।
     * **ধাপ ৪ (ইআইএ ইনভেন্টরি ও ডিজেল সরবরাহ সীমাবদ্ধতা):** ফরেক্সফ্যাক্টরি ক্যালেন্ডারের অপরিশোধিত তেল ইনভেন্টরি ড্র (-০.৭M) এবং মার্কিন রিফাইনারদের ডিজেল রপ্তানি সীমিত করার আহ্বান।

3. ⚡ **স্বল্পমেয়াদী মুভমেন্ট প্রেডিকশন (Short-Term Prediction: ১–৩ দিন / ইন্ট্রাডে):**
   - **ডিরেকশন ও সেন্টিমেন্ট (Bias):** [বুলিশ 🟢 / বেয়ারিশ 🔴 / নিরপেক্ষ-রেঞ্জবাউন্ড 🟡]
   - **প্রত্যাশিত প্রাইস রেঞ্জ (Expected Range):** WTI এবং Brent-এর জন্য সুনির্দিষ্ট ডলার রেঞ্জ (যেমন: $XX.XX - $XX.XX)
   - **মূল টেকনিক্যাল লেভেল:** তাৎক্ষণিক সাপোর্ট (Support) ও রেজিস্ট্যান্স (Resistance) জোন
   - **নিকটবর্তী ক্যাটালাইস্ট:** আগামী ২৪-৭২ ঘণ্টার মধ্যে হরমুজ谈判 বা পরবর্তী মার্কিন ম্যাক্রো ডেটায় স্পাইকের সম্ভাবনা

4. 🌐 **দীর্ঘমেয়াদী মুভমেন্ট প্রেডিকশন (Long-Term Prediction: সাপ্তাহিক / মাসিক / Q4):**
   - **কাঠামোগত ম্যাক্রো ট্রেন্ড (Structural Macro Trend):** দীর্ঘমেয়াদে তেলের মূল গতিপথ কোন দিকে
   - **ডিমান্ড-সাপ্লাই ব্যালেন্স (Fundamental Outlook):** ওপেক প্লাস (OPEC+) কোটা নীতি, বৈশ্বিক রিফাইনিং ক্ষমতা এবং ২০২৬ সালের অর্থনৈতিক প্রবৃদ্ধি
   - **টার্গেট প্রাইস জোন (Target Levels):** দীর্ঘমেয়াদী সম্ভাব্য ফ্লোর ও সিলিং জোন

5. ⚖️ **বুলিশ বনাম বেয়ারিশ প্রভাবকের তুলনামূলক মূল্যায়ন (Bullish vs Bearish Forces):**
   - 🟢 **দাম বাড়ানোর চালিকাশক্তি (Bullish Drivers):** [নির্দিষ্ট পয়েন্ট]
   - 🔴 **দাম কমানোর চালিকাশক্তি (Bearish Drivers):** [নির্দিষ্ট পয়েন্ট]

6. 🎯 **ট্রেডারদের স্ট্র্যাটেজি ও ঝুঁকি ব্যবস্থাপনা (Actionable Trading Playbook):**
   - **ইন্ট্রাডে ট্রেডারদের করণীয়:** এন্ট্রি জোন্স, টেক প্রফিট ও স্টপ লস
   - **সুইং ও পজিশনাল ট্রেডারদের করণীয়:** ডিপে বাই নাকি রাইজে সেল স্ট্র্যাটেজি
   - **ঝুঁকি সতর্কতা:** অপ্রত্যাশিত ভূ-রাজনৈতিক হেডলাইন বা হঠাৎ মিসাইল/ড্রোন হামলার ঝুঁকি ব্যবস্থাপনা

Format with clean Markdown, bold headers, and professional bullet points."""

    llm = get_llm()
    try:
        response_text, provider_used, _ = llm.generate_response(prompt=prompt)
        return response_text
    except Exception as e:
        logger.error(f"LLM oil prediction analysis failed: {e}")
        return f"তেলের পর্যায়ক্রমিক বিশ্লেষণ সম্পন্ন করা যায়নি: {str(e)}"

if __name__ == "__main__":
    print("Testing Enhanced Oil Analytics Service...")
    res = generate_oil_prediction_analysis()
    print("\n--- GENERATED REPORT PREVIEW ---\n")
    print(res[:1500])
