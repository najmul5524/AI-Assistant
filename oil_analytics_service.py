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
import database
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

def fetch_forexfactory_oil_stories(limit: int = 35) -> List[Dict[str, Any]]:
    """
    Scrapes live ForexFactory news and filters specifically for oil, energy,
    refinery, Middle East shipping, Hormuz, and Iran catalysts.
    Preserves exact High (🔴) and Medium (🟠) impact ratings.
    Guarantees retention of ALL news from last 48 hours (today & yesterday) and all High/Med impact items.
    Uses 3-tier redundancy:
    1. Direct ForexFactory live scraper
    2. Multi-feed institutional scraper (FXStreet, Investing.com)
    3. Persistent SQLite cache of previously recorded breaking news
    """
    matched = []
    seen = set()
    oil_keywords = [
        "oil", "crude", "wti", "brent", "opec", "petroleum", "energy",
        "diesel", "gasoline", "barrel", "refiner", "hormuz", "iran", "tanker", "eia", "api"
    ]

    all_candidates = []

    # Tier 1: ForexFactory Direct
    try:
        direct = forex_news_monitor.fetch_forexfactory_direct_news(limit=60)
        all_candidates.extend(direct)
        # Auto-persist direct news to database so older items are never lost
        for d in direct:
            try:
                database.mark_news_as_seen(
                    d.get("news_id", forex_news_monitor.generate_news_id(d["title"])),
                    d["title"],
                    d.get("link", ""),
                    d.get("pub_date", ""),
                    impact=d.get("impact", ""),
                    description=d.get("description", "")
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Tier 1 FF direct news fetch note: {e}")

    # Tier 2: Secondary Feeds (FXStreet, Investing.com)
    try:
        secondary = forex_news_monitor.fetch_latest_forex_news(limit=40)
        all_candidates.extend(secondary)
    except Exception as e:
        logger.warning(f"Tier 2 multi-feed news fetch note: {e}")

    # Tier 3: Persistent Database Cache
    try:
        cached = database.get_recent_seen_news(limit=80)
        dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
        for c in cached:
            dt_obj = forex_news_monitor.parse_article_date(c.get("published_at", ""))
            pub_dhaka = dt_obj.astimezone(dhaka_tz).strftime("%I:%M %p, %d %b %Y") if dt_obj else c.get("published_at", "")
            all_candidates.append({
                "title": c.get("title", ""),
                "description": c.get("description", ""),
                "impact": c.get("impact", ""),
                "pub_date_dhaka": pub_dhaka,
                "published_dt": dt_obj,
                "source": "Forex Factory Archive"
            })
    except Exception as e:
        logger.warning(f"Tier 3 cached news fetch note: {e}")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff_48h = now_utc - datetime.timedelta(hours=48)

    prioritized = []
    others = []

    for s in all_candidates:
        t_lower = s.get("title", "").lower()
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

                # STRICT RULE: Exclude explicit LOW impact news!
                if impact == "low":
                    continue

                # Must be High or Medium, OR critical energy/geopolitical catalyst
                is_explicit_high_med = impact in ["high", "medium"]
                is_critical_energy_catalyst = any(k in t_lower for k in [
                    "hormuz", "blockade", "opec", "iran war", "sanction", "emergency",
                    "truce", "missile", "drone", "refiner", "diesel export", "crude oil export losses"
                ])

                if not (is_explicit_high_med or is_critical_energy_catalyst):
                    continue

                if impact == "high" or any(k in t_lower for k in ["hormuz", "blockade", "iran war", "missile", "opec"]):
                    impact_label = "🔴 HIGH"
                else:
                    impact_label = "🟠 MEDIUM"

                item_dict = {
                    "title": s["title"],
                    "impact_label": impact_label,
                    "pub_date_dhaka": s.get("pub_date_dhaka", ""),
                    "published_dt": s.get("published_dt"),
                    "source": s.get("source", "Forex Factory")
                }
                prioritized.append(item_dict)

    # Sort chronologically
    prioritized.sort(key=lambda x: x["published_dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
    return prioritized[-limit:]

def fetch_forexfactory_energy_calendar() -> Dict[str, List[Dict[str, Any]]]:
    """
    Extracts raw energy events (EIA Crude Oil Inventories, API, Natural Gas Storage)
    directly from ForexFactory calendar cache, separating into recent releases and upcoming catalysts in BST.
    """
    recent = []
    upcoming = []
    try:
        raw_events = forex_service.fetch_raw_calendar()
        dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        for e in raw_events:
            title = e.get("title", "")
            t_lower = title.lower()
            if any(k in t_lower for k in ["oil", "crude", "inventor", "natural gas", "petroleum", "api"]):
                date_raw = e.get("date", "")
                dt_obj = None
                if date_raw:
                    try:
                        dt_obj = datetime.datetime.fromisoformat(date_raw)
                    except Exception:
                        dt_obj = forex_news_monitor.parse_article_date(date_raw)

                if dt_obj:
                    dhaka_time = dt_obj.astimezone(dhaka_tz).strftime("%I:%M %p, %d %b %Y (%A)")
                    is_future = dt_obj > now_utc
                else:
                    dhaka_time = date_raw
                    is_future = False

                item_dict = {
                    "title": title,
                    "country": e.get("country", "USD"),
                    "impact": e.get("impact", "Medium"),
                    "actual": e.get("actual") or "N/A",
                    "forecast": e.get("forecast") or "N/A",
                    "previous": e.get("previous") or "N/A",
                    "time_dhaka": dhaka_time,
                    "dt": dt_obj
                }

                if is_future:
                    upcoming.append(item_dict)
                else:
                    recent.append(item_dict)
    except Exception as e:
        logger.warning(f"Error fetching energy calendar events: {e}")

    upcoming.sort(key=lambda x: x["dt"] or datetime.datetime.max.replace(tzinfo=datetime.timezone.utc))
    recent.sort(key=lambda x: x["dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), reverse=True)

    return {
        "recent": recent[:6],
        "upcoming": upcoming[:6]
    }

def fetch_global_oil_wire_news(limit: int = 25, ff_reference_titles: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Fetches oil commodity wire articles across:
    1. Past 7 days (when:7d) for recent market price action and catalysts
    2. Past 30 days (when:30d) for structural supply/demand and geopolitical policies still actively anchoring the trend
    Strictly filters for HIGH IMPACT only, and DEDUPLICATES against ForexFactory titles.
    """
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    articles = []
    seen = set()

    search_queries = [
        "crude+oil+price+news+when:7d",
        "crude+oil+OPEC+Iran+when:30d"
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for q in search_queries:
        try:
            url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200 and resp.text:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item"):
                    title_el = item.find("title")
                    pub_date_el = item.find("pubDate")
                    if title_el is None or not title_el.text:
                        continue

                    raw_title = html_lib.unescape(title_el.text).strip()
                    source_name = "Commodity Wire"
                    if " - " in raw_title:
                        parts = raw_title.rsplit(" - ", 1)
                        clean_head = parts[0].strip()
                        source_name = parts[1].strip()
                    else:
                        clean_head = raw_title

                    norm = clean_head.lower().strip()
                    if norm in seen:
                        continue

                    # Deduplication: Drop if already covered by ForexFactory
                    if ff_reference_titles and forex_news_monitor.is_duplicate_story(clean_head, ff_reference_titles):
                        continue

                    # STRICT FILTER: High Impact only
                    is_high = any(k in norm for k in [
                        "war", "truce", "ceasefire", "strike", "attack", "missile", "drone",
                        "hormuz", "blockade", "sanction", "emergency", "crisis", "surge",
                        "plunge", "record high", "record low", "opec", "quota", "cut forecast",
                        "diesel export", "rates hit record", "tanker", "houthis", "saudi oil supply",
                        "us-iran", "crude stays above", "iran crisis"
                    ])
                    if not is_high:
                        continue

                    seen.add(norm)
                    pub_str = pub_date_el.text.strip() if pub_date_el is not None and pub_date_el.text else ""
                    dt_obj = forex_news_monitor.parse_article_date(pub_str)
                    pub_dhaka = dt_obj.astimezone(dhaka_tz).strftime("%I:%M %p, %d %b %Y (%A)") if dt_obj else pub_str

                    articles.append({
                        "title": clean_head,
                        "source": source_name,
                        "pub_date_dhaka": pub_dhaka,
                        "published_dt": dt_obj,
                        "impact_label": "🔴 HIGH"
                    })
        except Exception as e:
            logger.debug(f"Google news query '{q}' note: {e}")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff_48h = now_utc - datetime.timedelta(hours=48)
    cutoff_7d = now_utc - datetime.timedelta(days=7)

    b_48h = []
    b_7d = []
    b_30d = []

    for a in articles:
        p_dt = a.get("published_dt") or (now_utc - datetime.timedelta(days=15))
        if p_dt >= cutoff_48h:
            b_48h.append(a)
        elif p_dt >= cutoff_7d:
            b_7d.append(a)
        else:
            b_30d.append(a)

    b_48h.sort(key=lambda x: x["published_dt"] or now_utc)
    b_7d.sort(key=lambda x: x["published_dt"] or now_utc)
    b_30d.sort(key=lambda x: x["published_dt"] or now_utc)

    # Multi-horizon representative sampling:
    selected = b_30d[-6:] + b_7d[-8:] + b_48h[-10:]
    selected.sort(key=lambda x: x["published_dt"] or now_utc)
    return selected

def fetch_chronological_oil_news(max_items: int = 25) -> List[Dict[str, Any]]:
    """
    Unified function returning chronological oil news from both ForexFactory
    and Commodity Wire.
    """
    ff = fetch_forexfactory_oil_stories(limit=15)
    ff_titles = [s["title"] for s in ff]
    wire = fetch_global_oil_wire_news(limit=15, ff_reference_titles=ff_titles)
    combined = ff + wire
    combined.sort(
        key=lambda x: x.get("published_dt") or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
        reverse=False
    )
    return combined[-max_items:]

def generate_oil_prediction_analysis() -> str:
    """
    Synthesizes live technical market prices (WTI & Brent), ForexFactory Direct Breaking News,
    ForexFactory Economic Calendar (Inventories - past & upcoming in BST), and Live Commodity Wire (7-30 days)
    into a comprehensive Short-Term and Long-Term movement prediction.
    """
    metrics = fetch_oil_market_metrics()
    ff_stories = fetch_forexfactory_oil_stories(limit=25)
    ff_reference_titles = [s["title"] for s in ff_stories]
    cal_data = fetch_forexfactory_energy_calendar()
    recent_cal = cal_data.get("recent", [])
    upcoming_cal = cal_data.get("upcoming", [])
    wire_news = fetch_global_oil_wire_news(limit=20, ff_reference_titles=ff_reference_titles)

    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    dhaka_now = datetime.datetime.now(dhaka_tz).strftime("%I:%M %p, %d %B %Y (%A)")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff_48h = now_utc - datetime.timedelta(hours=48)

    # 1. Market Data Block
    wti = metrics.get("wti", {})
    brent = metrics.get("brent", {})
    wti_line = f"WTI Crude (CL=F): ${wti.get('current_price', 'N/A')} ({wti.get('change_pct', 0):+}% | 24h High: ${wti.get('high_24h', 'N/A')} | 24h Low: ${wti.get('low_24h', 'N/A')} | RSI: {wti.get('rsi', 'N/A')} | EMA20: ${wti.get('ema20', 'N/A')} | ATR: ${wti.get('atr', 'N/A')})"
    brent_line = f"Brent Crude (BZ=F): ${brent.get('current_price', 'N/A')} ({brent.get('change_pct', 0):+}% | 24h High: ${brent.get('high_24h', 'N/A')} | 24h Low: ${brent.get('low_24h', 'N/A')} | RSI: {brent.get('rsi', 'N/A')} | EMA20: ${brent.get('ema20', 'N/A')} | ATR: ${brent.get('atr', 'N/A')})"

    # 2. ForexFactory Breaking Stories with Period Tags (High & Medium impact only)
    ff_lines = []
    for it in ff_stories:
        dt = it.get("published_dt")
        p_tag = " [গত ২৪-৪৮ ঘণ্টা / আজ-গতকাল]" if dt and dt >= cutoff_48h else " [গত ৩–৭ দিন]"
        ff_lines.append(f"• [{it['pub_date_dhaka']}]{p_tag} [{it['impact_label']}] ({it['source']}) {it['title']}")
    ff_feed = "\n".join(ff_lines) if ff_lines else "ForexFactory breaking stories active."

    # 3. ForexFactory Calendar (Inventories - Recent & Upcoming)
    recent_cal_lines = []
    for c in recent_cal:
        recent_cal_lines.append(f"• [{c['time_dhaka']}] {c['country']} - {c['title']} | Actual: {c['actual']} | Forecast: {c['forecast']} | Previous: {c['previous']}")
    recent_cal_feed = "\n".join(recent_cal_lines) if recent_cal_lines else "Weekly inventory reports active."

    upcoming_cal_lines = []
    for u in upcoming_cal:
        upcoming_cal_lines.append(f"• [{u['time_dhaka']}] [🔴 {u['impact'].upper()}] {u['country']} - {u['title']} | Forecast: {u['forecast']} | Previous: {u['previous']}")
    upcoming_cal_feed = "\n".join(upcoming_cal_lines) if upcoming_cal_lines else "Upcoming scheduled inventory catalysts active."

    # 4. Commodity Wire Dispatches with Period Tags (Unique High-impact only)
    wire_lines = []
    for w in wire_news:
        dt = w.get("published_dt")
        if dt and dt >= cutoff_48h:
            w_tag = " [গত ২৪-৪৮ ঘণ্টা / আজ-গতকাল]"
        elif dt and dt >= (now_utc - datetime.timedelta(days=7)):
            w_tag = " [গত ৩–৭ দিন]"
        else:
            w_tag = " [গত ৮–৩০ দিন ম্যাক্রো ভিত্তি]"
        wire_lines.append(f"• [{w['pub_date_dhaka']}]{w_tag} [{w.get('impact_label', '🔴 HIGH')}] ({w['source']}) {w['title']}")
    wire_feed_30d = "\n".join(wire_lines) if wire_lines else "Global wire dispatches (7–30 days) active."

    prompt = f"""You are the Chief Global Commodities Strategist & Senior Energy Macro Analyst at a top Wall Street institutional trading desk.
Current Bangladesh Time: {dhaka_now} (BST / GMT+6).

LIVE OIL MARKET TECHNICAL DATA:
- {wti_line}
- {brent_line}

FOREX FACTORY DIRECT BREAKING NEWS (STRICTLY HIGH & MEDIUM IMPACT ONLY):
{ff_feed}

FOREX FACTORY ECONOMIC CALENDAR (RECENT INVENTORIES & SUPPLY RELEASES):
{recent_cal_feed}

FOREX FACTORY ECONOMIC CALENDAR (UPCOMING SCHEDULED HIGH-IMPACT ENERGY CATALYSTS - IN BST):
{upcoming_cal_feed}

GLOBAL COMMODITY WIRE DISPATCHES (STRICTLY UNIQUE HIGH-IMPACT NEWS - DEDUPLICATED AGAINST FOREXFACTORY):
{wire_feed_30d}

CRITICAL TASK & INSTRUCTIONS:
Provide a robust, comprehensive, institutional movement prediction for Crude Oil (WTI & Brent) in professional, fluent Bengali.
Ensure that:
1. Strict Impact & Deduplication Filter:
   - ForexFactory থেকে শুধুমাত্র High (🔴) এবং Medium (🟠) ইমপ্যাক্ট নিউজগুলো বিশ্লেষণ করতে হবে (কোনো Low বা কম গুরুত্বপূর্ণ নিউজ রাখা যাবে না)।
   - অন্যান্য সোর্স (Wire / Reuters / WSJ / Bloomberg) থেকে শুধুমাত্র High Impact (🔴) নিউজ দেখাতে হবে, এবং তা কেবল তখনই দেখাবে যদি সেটি ForexFactory-এর সংবাদের সাথে ডুপ্লিকেট বা ওভারল্যাপ না করে (ForexFactory-তে যা এসেছে তা অন্য সোর্স থেকে পুনরায় দেখানো যাবে না)।
2. Data Horizon: Synthesize active macro & market catalysts from the past 7 to 30 days (such as geopolitical premiums, Hormuz naval developments, OPEC+ production policies, and US refining actions) whose impact is still actively anchoring the current trend.
3. Time Horizon Definitions: Clearly define the exact time horizon for Short-Term (১–৩ দিন / সর্বোচ্চ ১ সপ্তাহ) and Long-Term (২ সপ্তাহ থেকে ১–৩ মাস / Q4).
4. Explicit Catalyst Detailing: In Section 2, DO NOT write a single vague narrative paragraph. Every key news item must be EXPLICITLY and SEPARATELY presented with:
   - Specific Headline (খবরের সঠিক শিরোনাম)
   - Publication Date & Time in BST (বাংলাদেশ সময়)
   - Source & Impact level (যেমন: Forex Factory [🔴 HIGH / 🟠 MEDIUM], Reuters [🔴 HIGH], WSJ [🔴 HIGH])
   - Price reaction & immediate market impact
   - ⌛ Impact Expiry Horizon (কখন/কতদিন পর প্রভাব শেষ বা স্তিমিত হবে)
   - 🔄 Next Follow-up / Recurrence Schedule (পরবর্তী আপডেট বা অফিশিয়াল ডেটা বাংলাদেশ সময় কবে আসবে)
5. Do NOT omit any High/Medium news from yesterday (২৪ সেপ্টেম্বর) or today (২৫ সেপ্টেম্বর). All major recent headlines from the feed above must be itemized.
6. Upcoming High-Impact Catalysts: Detail upcoming events that could cause major volatility or trend change, with exact dates and times in বাংলাদেশ সময় (BST / GMT+6).
7. All times must strictly be in Bangladesh Time (BST / GMT+6).

### EXACT REPORT STRUCTURE:

1. 🛢️ **তেল বাজারের বর্তমান অবস্থা ও লাইভ স্ন্যাপশট (Live Market Snapshot):**
   - WTI এবং Brent-এর বর্তমান লাইভ প্রাইস, দৈনিক পরিবর্তন (Change %), ডে হাই/লো এবং টেকনিক্যাল মোমেন্টাম (RSI, EMA20 এবং ATR ভোলাটিলিটি)।

2. ⏳ **ঘটনাগুলোর পর্যায়ক্রমিক ও কালানুক্রমিক গতিপথ (Sequential Catalyst Trajectory - গত ৭ থেকে ৩০ দিনের সক্রিয় প্রভাবক):**
   ⚠️ প্রতিটি গুরুত্বপূর্ণ খবরকে আলাদা আলাদা সাব-এন্ট্রি হিসেবে সুনির্দিষ্ট শিরোনাম, সময়, উৎস এবং ইমপ্যাক্টসহ উপস্থাপন করতে হবে:

   🔹 **ধাপ ১: ম্যাক্রো পটভূমি ও গত ৩০ দিনের কাঠামোগত সরবরাহ-চাহিদা ভিত্তি (দিন ৮–৩০):**
   - বৈশ্বিক তেলের চাহিদা, ওপেক প্লাস কোটা নীতি ও ভূ-রাজনৈতিক ঝুঁকির প্রাথমিক ভিত্তি তৈরি করা খবরের সুনির্দিষ্ট তালিকা ও বিবরণ।
   - প্রতিটি খবরের জন্য: শিরোনাম, ⌛ ইমপ্যাক্ট মেয়াদ ও 🔄 পরবর্তী ফলো-আপ দিনক্ষণ।

   🔹 **ধাপ ২: গত ৩–৭ দিনের প্রধান অনুঘটক ও ভূ-রাজনীতি (দিন ৩–৭):**
   - মধ্যপ্রাচ্যের সংঘাত, মিসাইল আক্রমণ, রিফাইনারি সমস্যা বা আন্তর্জাতিক নীতি ঘোষণার সুনির্দিষ্ট খবরের তালিকা।
   - প্রতিটি খবরের জন্য: শিরোনাম, প্রাইস প্রতিক্রিয়া, ⌛ ইমপ্যাক্ট মেয়াদ ও 🔄 পরবর্তী ফলো-আপ দিনক্ষণ।

   🔹 **ধাপ ৩: গতকাল ও আজকের ব্রেকিং নিউজ ও সরাসরি প্রাইস ইমপ্যাক্ট (গত ২৪–৪৮ ঘণ্টা):**
   (গতকাল এবং আজকের প্রতিটি খবরকে পয়েন্ট আকারে সুনির্দিষ্ট শিরোনাম, তারিখ ও সময়সহ তুলে ধরতে হবে):
   • 📰 **[তারিখ ও সময় - BST] | [উৎস ও ইমপ্যাক্ট: যেমন 🔴 HIGH / Forex Factory / Reuters / WSJ]:**
     - **খবরের শিরোনাম:** "খবরের সুনির্দিষ্ট শিরোনাম"
     - **বাজার পরিস্থিতি ও প্রাইস প্রতিক্রিয়া:** এই সংবাদের ফলে তেলের দামে তাৎক্ষণিক কী প্রভাব পড়েছে এবং বাজার সেন্টিমেন্ট কেমন রূপ নিয়েছে।
     - ⌛ **ইমপ্যাক্ট স্থায়ীত্ব ও মেয়াদ (Impact Duration & Expiry Horizon):** এই প্রভাব কতদিন পর্যন্ত বাজারে থাকবে এবং কোন ইভেন্টের পর শেষ হবে।
     - 🔄 **পরবর্তী ফলো-আপ আপডেট বা পুনরাবৃত্তির দিনক্ষণ (Next Follow-up in BST):** বাংলাদেশ সময়ে পরবর্তী ডেটা বা অফিশিয়াল আপডেট কবে আসবে।

   🔹 **ধাপ ৪: ফরেক্সফ্যাক্টরি ইনভেন্টরি ও সরবরাহ ডেটা (EIA / API Inventories):**
   - প্রকাশিত সাম্প্রতিক ইনভেন্টরি ডেটার (Actual vs Forecast vs Previous) প্রতিফলন ও বর্তমান প্রভাব।

3. ⚡ **স্বল্পমেয়াদী মুভমেন্ট প্রেডিকশন (Short-Term Prediction: ১–৩ দিন / সর্বোচ্চ ১ সপ্তাহ):**
   - **স্বল্পমেয়াদের সুনির্দিষ্ট সময়সীমা:** *১ থেকে ৩ কার্যদিবস (বা সর্বোচ্চ ১ সপ্তাহ / ইন্ট্রাডে থেকে সুইং হরাইজন)*
   - **ডিরেকশন ও সেন্টিমেন্ট (Bias):** [বুলিশ 🟢 / বেয়ারিশ 🔴 / নিরপেক্ষ-রেঞ্জবাউন্ড 🟡]
   - **প্রত্যাশিত প্রাইস রেঞ্জ (Expected Range):** WTI এবং Brent-এর জন্য সুনির্দিষ্ট ডলার রেঞ্জ (যেমন: $XX.XX - $XX.XX)
   - **মূল টেকনিক্যাল লেভেল:** তাৎক্ষণিক সাপোর্ট (Support) ও রেজিস্ট্যান্স (Resistance) জোন
   - **নিকটবর্তী ক্যাটালাইস্ট:** আগামী ২৪-৭২ ঘণ্টার মধ্যে হরমুজ কূটনীতি বা পরবর্তী মার্কিন ম্যাক্রো ডেটায় স্পাইকের সম্ভাবনা

4. 🌐 **দীর্ঘমেয়াদী মুভমেন্ট প্রেডিকশন (Long-Term Prediction: ২ সপ্তাহ থেকে ১–৩ মাস / চলতি কোয়ার্টার Q4):**
   - **দীর্ঘমেয়াদের সুনির্দিষ্ট সময়সীমা:** *২ সপ্তাহ থেকে ১–৩ মাস (বা চলতি ২০২৬ সালের Q4 কোয়ার্টার পর্যন্ত কাঠামোগত ট্রেন্ড)*
   - **কাঠামোগত ম্যাক্রো ট্রেন্ড (Structural Macro Trend):** দীর্ঘমেয়াদে তেলের মূল গতিপথ কোন দিকে
   - **ডিমান্ড-সাপ্লাই ব্যালেন্স (Fundamental Outlook):** ওপেক প্লাস (OPEC+) কোটা নীতি, বৈশ্বিক রিফাইনিং ক্ষমতা এবং ২০২৬ সালের অর্থনৈতিক প্রবৃদ্ধি
   - **টার্গেট প্রাইস জোন (Target Levels):** দীর্ঘমেয়াদী সম্ভাব্য ফ্লোর ও সিলিং জোন

5. 📅 **আসন্ন শীর্ষ ক্যাটালাইস্ট ও সম্ভাব্য বড় পরিবর্তন (Upcoming High-Impact Energy Catalysts):**
   - আগামী দিনগুলোতে কোন কোন আসন্ন ইভেন্টের (যেমন: পরবর্তী EIA ক্রুড ইনভেন্টরি ড্র, OPEC+ মনিটরিং বৈঠক, ইউএস ম্যাক্রো ডেটা) কারণে তেলের দামে বড় পরিবর্তন বা তীব্র স্পাইক আসতে পারে।
   - প্রতিটি ইভেন্ট **বাংলাদেশ সময় (BST / GMT+6)** কোন দিন এবং কয়টার সময় রিলিজ হবে তা সময়সহ উল্লেখ।
   - ডেটা প্রত্যাশার চেয়ে ভিন্ন এলে প্রাইস কোন লেভেলে ব্রেকআউট বা ড্রপ করতে পারে।

6. ⚖️ **বুলিশ বনাম বেয়ারিশ প্রভাবকের তুলনামূলক মূল্যায়ন (Bullish vs Bearish Forces):**
   - 🟢 **দাম বাড়ানোর চালিকাশক্তি (Bullish Drivers):** [নির্দিষ্ট পয়েন্ট]
   - 🔴 **দাম কমানোর চালিকাশক্তি (Bearish Drivers):** [নির্দিষ্ট পয়েন্ট]

7. 🎯 **ট্রেডারদের স্ট্র্যাটেজি ও ঝুঁকি ব্যবস্থাপনা (Actionable Trading Playbook & Risk Controls):**
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
