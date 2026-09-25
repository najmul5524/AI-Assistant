"""
Universal Multi-Asset Market Intelligence & Predictive Analytics Service.
Provides comprehensive, institutional-grade market snapshots, sequential news trajectories,
and short/long-term movement predictions across:
- Precious Metals: Gold (XAU/USD), Silver (XAG/USD)
- Indices & Futures: Nasdaq 100, S&P 500, Dow Jones
- Cryptocurrencies: Bitcoin (BTC), Ethereum (ETH), Solana (SOL)
- Forex Majors: EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, USD/CHF, DXY
- Energy: Crude Oil (WTI), Brent Crude
"""

import logging
import datetime
import zoneinfo
import re
import html as html_lib
import requests
import xml.etree.ElementTree as ET
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

def get_asset_profile(query: str) -> Dict[str, Any]:
    """
    Resolves asset query to ticker, display name, currency, and category.
    """
    raw_ticker, full_name = ta_service.resolve_symbol(query)
    q_lower = query.lower().strip()

    # Determine category
    category = "general"
    currency = "USD"

    if any(k in q_lower for k in ["gold", "xau", "সোনার", "সোনা", "গোল্ড"]):
        category = "gold"
        currency = "USD"
    elif any(k in q_lower for k in ["silver", "xag", "রূপা", "সিলভার"]):
        category = "silver"
        currency = "USD"
    elif any(k in q_lower for k in ["nasdaq", "us100", "nq", "ndx", "ন্যাশডাক"]):
        category = "indices"
        currency = "USD"
    elif any(k in q_lower for k in ["sp500", "spx", "us500", "es", "s&p"]):
        category = "indices"
        currency = "USD"
    elif any(k in q_lower for k in ["dow", "us30", "ym", "dji", "ডাউ"]):
        category = "indices"
        currency = "USD"
    elif any(k in q_lower for k in ["btc", "bitcoin", "বিটকয়েন"]):
        category = "crypto"
        currency = "USD"
    elif any(k in q_lower for k in ["eth", "ethereum", "etherium", "ইথেরিয়াম"]):
        category = "crypto"
        currency = "USD"
    elif any(k in q_lower for k in ["oil", "crude", "wti", "brent", "তেল", "পেট্রোলিয়াম"]):
        category = "oil"
        currency = "USD"
    elif "eur" in q_lower:
        category = "forex"
        currency = "EUR"
    elif "gbp" in q_lower:
        category = "forex"
        currency = "GBP"
    elif "jpy" in q_lower or "yen" in q_lower or "ইয়েন" in q_lower:
        category = "forex"
        currency = "JPY"
    elif "aud" in q_lower:
        category = "forex"
        currency = "AUD"
    elif "cad" in q_lower:
        category = "forex"
        currency = "CAD"
    elif "chf" in q_lower:
        category = "forex"
        currency = "CHF"
    elif "dxy" in q_lower or "dollar" in q_lower or "ডলার" in q_lower:
        category = "forex"
        currency = "USD"

    return {
        "ticker": raw_ticker,
        "name": full_name,
        "category": category,
        "currency": currency,
        "query": query
    }

def fetch_asset_technicals(ticker: str, name: str) -> Dict[str, Any]:
    """
    Fetches real-time market price, 24h change, high, low, RSI, EMA20, ATR.
    """
    try:
        candles = ta_service.fetch_candles(ticker, interval="1h", range_str="5d")
        if not candles or len(candles) < 2:
            candles = ta_service.fetch_candles(ticker, interval="15m", range_str="2d")

        if candles and len(candles) >= 2:
            latest = candles[-1]
            prev = candles[-2]
            curr_price = latest["close"]
            prev_price = prev["close"]
            diff = curr_price - prev_price
            pct_change = (diff / prev_price) * 100 if prev_price else 0.0

            last_24 = candles[-24:] if len(candles) >= 24 else candles
            high_24h = max(c["high"] for c in last_24)
            low_24h = min(c["low"] for c in last_24)

            closes = [c["close"] for c in candles]
            rsi_val = ta_service.calculate_rsi(closes)
            ema20 = ta_service.calculate_ema(closes, 20)
            atr_val = ta_service.calculate_atr(candles)

            # Decimal formatting based on asset class
            dec = 4 if "EURUSD" in ticker or "GBPUSD" in ticker else (2 if curr_price > 10 else 3)
            return {
                "name": name,
                "ticker": ticker,
                "current_price": round(curr_price, dec),
                "change": round(diff, dec),
                "change_pct": round(pct_change, 2),
                "high_24h": round(high_24h, dec),
                "low_24h": round(low_24h, dec),
                "rsi": round(rsi_val, 1) if rsi_val is not None else "N/A",
                "ema20": round(ema20, dec) if ema20 is not None else "N/A",
                "atr": round(atr_val, dec) if atr_val is not None else "N/A"
            }
        else:
            return {"name": name, "ticker": ticker, "current_price": "N/A"}
    except Exception as e:
        logger.warning(f"Error fetching technical metrics for {ticker}: {e}")
        return {"name": name, "ticker": ticker, "current_price": "N/A"}

def fetch_asset_forexfactory_news(category: str, currency: str, limit: int = 8) -> List[Dict[str, Any]]:
    """
    Filters ForexFactory direct breaking news matching the target asset category or currency.
    """
    keyword_map = {
        "gold": ["gold", "xau", "precious metal", "safe haven", "silver", "yield", "fed", "dollar", "inflation", "rates"],
        "silver": ["silver", "xag", "gold", "precious metal", "industrial metal", "yield", "dollar"],
        "indices": ["nasdaq", "s&p", "dow", "stocks", "wall street", "tech", "earnings", "yields", "fed", "rate", "gdp"],
        "crypto": ["btc", "bitcoin", "crypto", "ethereum", "eth", "sec", "etf", "binance", "stablecoin", "fed"],
        "oil": ["oil", "crude", "wti", "brent", "opec", "diesel", "gasoline", "hormuz", "iran", "refiner", "tanker"],
        "forex": [currency.lower(), "fed", "ecb", "boj", "boe", "rate", "cut", "hike", "cpi", "inflation", "gdp", "dollar"]
    }
    keywords = keyword_map.get(category, [currency.lower(), "rate", "inflation", "dollar"])

    matched = []
    seen = set()
    all_candidates = []

    # Tier 1: ForexFactory Direct Scraper
    try:
        direct = forex_news_monitor.fetch_forexfactory_direct_news(limit=60)
        all_candidates.extend(direct)
    except Exception as e:
        logger.warning(f"Tier 1 FF direct news fetch note: {e}")

    # Tier 2: Multi-Feed Institutional Feeds (FXStreet, Investing.com)
    try:
        secondary = forex_news_monitor.fetch_latest_forex_news(limit=40)
        all_candidates.extend(secondary)
    except Exception as e:
        logger.warning(f"Tier 2 multi-feed news fetch note: {e}")

    # Tier 3: Persistent Database Cache
    try:
        cached = database.get_recent_seen_news(limit=60)
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

    for s in all_candidates:
        t_lower = s.get("title", "").lower()
        d_lower = s.get("description", "").lower()

        is_match = any(k in t_lower or k in d_lower for k in keywords)
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

    # Sort chronological
    matched.sort(
        key=lambda x: x["published_dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
        reverse=False
    )
    return matched[-limit:]

def fetch_asset_calendar_events(currency: str, category: str) -> List[Dict[str, Any]]:
    """
    Filters ForexFactory economic calendar events relevant to the asset.
    """
    matched = []
    try:
        raw_events = forex_service.fetch_raw_calendar()
        dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")

        target_currencies = {currency, "USD"}
        for e in raw_events:
            c_curr = e.get("country", "")
            title = e.get("title", "")
            impact = e.get("impact", "")

            # If oil, include energy events
            is_energy_event = category == "oil" and any(k in title.lower() for k in ["oil", "crude", "inventor", "natural gas"])
            is_relevant_curr = c_curr in target_currencies and impact in ["High", "Medium"]

            if is_energy_event or is_relevant_curr:
                date_raw = e.get("date", "")
                dt_obj = forex_news_monitor.parse_article_date(date_raw)
                dhaka_time = dt_obj.astimezone(dhaka_tz).strftime("%I:%M %p, %d %b %Y") if dt_obj else date_raw
                matched.append({
                    "title": title,
                    "country": c_curr,
                    "impact": impact,
                    "actual": e.get("actual") or "N/A",
                    "forecast": e.get("forecast") or "N/A",
                    "previous": e.get("previous") or "N/A",
                    "time_dhaka": dhaka_time
                })
    except Exception as e:
        logger.warning(f"Error fetching calendar events for {currency}: {e}")

    return matched[:10]

def fetch_asset_wire_news(category: str, asset_name: str, limit: int = 6) -> List[Dict[str, Any]]:
    """
    Searches Google News RSS for fresh (last 72h via when:3d) commodity/macro wire dispatches.
    """
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    articles = []
    seen = set()

    clean_q = asset_name.replace(" ", "+").replace("/", "+")
    query_url = f"https://news.google.com/rss/search?q={clean_q}+price+forecast+when:3d&hl=en-US&gl=US&ceid=US:en"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        resp = requests.get(query_url, headers=headers, timeout=6)
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

                source_name = "Market Wire"
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
        logger.debug(f"Wire news fetch note: {e}")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    articles.sort(
        key=lambda x: x["published_dt"] or (now_utc - datetime.timedelta(days=3)),
        reverse=False
    )
    return articles[-limit:]

def generate_asset_prediction_analysis(query: str) -> str:
    """
    Universal Entry Point:
    Takes any instrument query (e.g. 'gold', 'nasdaq', 'sp500', 'dow', 'btc', 'eth', 'eurusd', 'oil')
    and outputs a comprehensive, institutional-grade market situation & sequential movement prediction report.
    """
    profile = get_asset_profile(query)
    ticker = profile["ticker"]
    name = profile["name"]
    category = profile["category"]
    currency = profile["currency"]

    # 1. Fetch Live Technicals
    metrics = fetch_asset_technicals(ticker, name)

    # 2. Fetch ForexFactory Direct Breaking News
    ff_stories = fetch_asset_forexfactory_news(category, currency, limit=8)

    # 3. Fetch ForexFactory Economic Calendar
    calendar_events = fetch_asset_calendar_events(currency, category)

    # 4. Fetch Commodity / Financial Wire Dispatches (Last 72h)
    wire_news = fetch_asset_wire_news(category, name, limit=6)

    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    dhaka_now = datetime.datetime.now(dhaka_tz).strftime("%I:%M %p, %d %B %Y (%A)")

    # Build prompt blocks
    tech_line = (
        f"{name} ({ticker}): Current Price: ${metrics.get('current_price', 'N/A')} "
        f"({metrics.get('change_pct', 0):+}% | 24h High: ${metrics.get('high_24h', 'N/A')} | "
        f"24h Low: ${metrics.get('low_24h', 'N/A')} | RSI(14): {metrics.get('rsi', 'N/A')} | "
        f"EMA20: ${metrics.get('ema20', 'N/A')} | ATR: ${metrics.get('atr', 'N/A')})"
    )

    ff_lines = []
    for it in ff_stories:
        ff_lines.append(f"• [{it['pub_date_dhaka']}] [{it['impact_label']}] ({it['source']}) {it['title']}")
    ff_feed = "\n".join(ff_lines) if ff_lines else "Active institutional breaking news monitored."

    cal_lines = []
    for c in calendar_events:
        cal_lines.append(f"• [{c['time_dhaka']}] ({c['impact']}) {c['country']} - {c['title']} | Actual: {c['actual']} | Forecast: {c['forecast']} | Previous: {c['previous']}")
    cal_feed = "\n".join(cal_lines) if cal_lines else "Scheduled economic calendar events monitored."

    wire_lines = []
    for w in wire_news:
        wire_lines.append(f"• [{w['pub_date_dhaka']}] ({w['source']}) {w['title']}")
    wire_feed = "\n".join(wire_lines) if wire_lines else "Global wire dispatches active."

    # Asset class contextual guidance
    context_note = ""
    if category == "gold":
        context_note = "Focus on US real bond yields, Federal Reserve interest rate trajectory, geopolitical safe-haven flows, and central bank physical reserves accumulation."
    elif category == "indices":
        context_note = "Focus on US tech sector earnings, Federal Reserve monetary policy, 10-year Treasury yields pressure, inflation metrics, and liquidity sentiment."
    elif category == "crypto":
        context_note = "Focus on Bitcoin ETF net inflows/outflows, global risk-on/risk-off sentiment, regulatory signals, crypto exchange liquidity, and correlation with tech equities."
    elif category == "forex":
        context_note = f"Focus on central bank rate differentials between {currency} and USD, inflation CPI/PCE data, monetary policy speeches, and trade balance dynamics."
    elif category == "oil":
        context_note = "Focus on OPEC+ production quotas, US-Iran geopolitical & Strait of Hormuz naval developments, EIA crude inventory statistics, and global demand dynamics."

    prompt = f"""You are the Chief Global Macro Strategist & Senior Quantitative Portfolio Manager at a Tier-1 Wall Street institutional investment bank.
Current Bangladesh Time: {dhaka_now} (BST / GMT+6).
Asset under analysis: {name} ({ticker}) — Category: {category.upper()}
Analytical Context: {context_note}

LIVE MARKET TECHNICAL METRICS:
{tech_line}

FOREX FACTORY DIRECT BREAKING HEADLINES (HIGH & MEDIUM IMPACT):
{ff_feed}

FOREX FACTORY ECONOMIC CALENDAR (RECENT & UPCOMING CATALYSTS):
{cal_feed}

GLOBAL FINANCIAL & COMMODITY WIRE DISPATCHES (LAST 72 HOURS):
{wire_feed}

CRITICAL TASK:
Provide a robust, institutional-grade market analysis and movement prediction for {name} in fluent, professional Bengali.
Ensure that Section 2 ("ঘটনাগুলোর পর্যায়ক্রমিক ও কালানুক্রমিক গতিপথ") analyzes how real-world chronological events, ForexFactory high/medium impact headlines, and macroeconomic calendar releases built up the current price action. NEVER say that there are no headlines or events.

### MANDATORY REPORT STRUCTURE:

1. 📊 **বর্তমান বাজার পরিস্থিতি ও লাইভ স্ন্যাপশট (Live Market Snapshot):**
   - {name}-এর বর্তমান লাইভ মার্কেট প্রাইস, দৈনিক পরিবর্তন (Change %), ২৪ ঘণ্টার হাই/লো এবং টেকনিক্যাল মোমেন্টাম (RSI, EMA20 এবং ATR ভোলাটিলিটি অবস্থান)।

2. ⏳ **ঘটনাগুলোর পর্যায়ক্রমিক ও কালানুক্রমিক গতিপথ (Sequential Catalyst Trajectory):**
   - সাম্প্রতিক ঘটনাসমূহ কীভাবে ধাপে ধাপে {name}-এর বর্তমান প্রাইস অ্যাকশন ও সেন্টিমেন্ট তৈরি করেছে তার সুস্পষ্ট বিবরণ:
     * **ধাপ ১ (ম্যাক্রো পটভূমি ও কাঠামোগত ভিত্তি):** প্রাথমিক কারণ ও বৈশ্বিক ম্যাক্রো পরিবেশ।
     * **ধাপ ২ (ফরেক্সফ্যাক্টরি হাই/মিডিয়াম ইমপ্যাক্ট ব্রেকিং নিউজ ও ডেটা):** সাম্প্রতিক প্রকাশিত প্রধান অর্থনৈতিক ডেটা বা ভূ-রাজনৈতিক খবরের তাৎক্ষণিক প্রভাব।
     * **ধাপ ৩ (সাম্প্রতিক মার্কেট প্রতিক্রিয়া ও প্রাইস অ্যাকশন):** খবরগুলোর ফলে ঘটে যাওয়া প্রাইস রিঅ্যাকশন বা কারেকশন।
     * **ধাপ ৪ (বর্তমান ট্রিগার ও মোমেন্টাম):** সর্বশেষ খবর বা অনুঘটক যা বর্তমান প্রাইসকে ধরে রেখেছে।

3. ⚡ **স্বল্পমেয়াদী মুভমেন্ট প্রেডিকশন (Short-Term Prediction: ১–৩ দিন / ইন্ট্রাডে):**
   - **ডিরেকশন ও সেন্টিমেন্ট (Bias):** [বুলিশ 🟢 / বেয়ারিশ 🔴 / নিরপেক্ষ-রেঞ্জবাউন্ড 🟡]
   - **প্রত্যাশিত প্রাইস রেঞ্জ (Expected Range):** {name}-এর জন্য নির্দিষ্ট প্রাইস রেঞ্জ
   - **মূল টেকনিক্যাল লেভেল:** তাৎক্ষণিক সাপোর্ট (Support) ও রেজিস্ট্যান্স (Resistance) জোন
   - **নিকটবর্তী ক্যাটালাইস্ট:** আগামী ২৪-৭২ ঘণ্টার মধ্যে কোন ইভেন্ট বা ডেটা বড় স্পাইক ঘটাতে পারে

4. 🌐 **দীর্ঘমেয়াদী মুভমেন্ট প্রেডিকশন (Long-Term Prediction: সাপ্তাহিক / মাসিক / Q4):**
   - **কাঠামোগত ম্যাক্রো ট্রেন্ড (Structural Macro Trend):** দীর্ঘমেয়াদী প্রাইস ডিরেকশন
   - **ফান্ডামেন্টাল ভারসাম্য:** সেন্ট্রাল ব্যাংক পলিসি, বৈশ্বিক লিকুইডিটি ও ফান্ডামেন্টাল দৃষ্টিভঙ্গি
   - **টার্গেট প্রাইস জোন (Target Levels):** দীর্ঘমেয়াদী সম্ভাব্য টার্গেট জোন

5. ⚖️ **বুলিশ বনাম বেয়ারিশ প্রভাবকের তুলনামূলক মূল্যায়ন (Bullish vs Bearish Forces):**
   - 🟢 **দাম বাড়ানোর চালিকাশক্তি (Bullish Drivers):** [নির্দিষ্ট পয়েন্ট]
   - 🔴 **দাম কমানোর চালিকাশক্তি (Bearish Drivers):** [নির্দিষ্ট পয়েন্ট]

6. 🎯 **ট্রেডারদের স্ট্র্যাটেজি ও ঝুঁকি ব্যবস্থাপনা (Actionable Trading Playbook):**
   - **ইন্ট্রাডে ট্রেডারদের করণীয়:** এন্ট্রি জোন, টেক প্রফিট ও স্টপ লস
   - **সুইং ও পজিশনাল ট্রেডারদের করণীয়:** পজিশনিং ও এক্সপোজার ম্যানেজমেন্ট
   - **ঝুঁকি সতর্কতা:** অপ্রত্যাশিত স্পাইক বা সেন্ট্রাল ব্যাংক ভোল্টিলিটি সামলানোর পরামর্শ

Format with clean Markdown, bold headers, and professional bullet points."""

    llm = get_llm()
    try:
        response_text, provider_used, _ = llm.generate_response(prompt=prompt)
        return response_text
    except Exception as e:
        logger.error(f"LLM prediction analysis failed for {name}: {e}")
        return f"{name}-এর বিশ্লেষণ সম্পন্ন করা যায়নি: {str(e)}"
