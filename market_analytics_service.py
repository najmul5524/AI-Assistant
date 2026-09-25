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

def fetch_asset_forexfactory_news(category: str, currency: str = "USD", limit: int = 35) -> List[Dict[str, Any]]:
    """
    Filters ForexFactory direct breaking news matching the target asset category or currency.
    Guarantees retention of ALL news from last 48 hours (today & yesterday) and all High/Med impact items.
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

    # Tier 2: Multi-Feed Institutional Feeds (FXStreet, Investing.com)
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

        is_match = any(k in t_lower or k in d_lower for k in keywords)
        if is_match:
            norm = t_lower.strip()
            if norm not in seen:
                seen.add(norm)
                impact = s.get("impact", "").strip().lower()
                impact_label = "🔴 HIGH" if impact == "high" else ("🟠 MEDIUM" if impact == "medium" else ("🟡 LOW" if impact == "low" else "NORMAL"))
                item_dict = {
                    "title": s["title"],
                    "impact_label": impact_label,
                    "pub_date_dhaka": s.get("pub_date_dhaka", ""),
                    "published_dt": s.get("published_dt"),
                    "source": s.get("source", "Forex Factory")
                }

                # Priority: Any news within last 48 hours (today & yesterday) or High/Medium impact
                dt = s.get("published_dt")
                if (dt and dt >= cutoff_48h) or impact in ["high", "medium"]:
                    prioritized.append(item_dict)
                else:
                    others.append(item_dict)

    # Sort each group chronologically
    prioritized.sort(key=lambda x: x["published_dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
    others.sort(key=lambda x: x["published_dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))

    # Retain ALL prioritized items, and fill any remaining quota with older items
    remaining_slots = max(0, limit - len(prioritized))
    combined = others[-remaining_slots:] + prioritized if remaining_slots > 0 else prioritized
    combined.sort(key=lambda x: x["published_dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
    return combined

def fetch_asset_calendar_events(currency: str, category: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Filters ForexFactory economic calendar events relevant to the asset,
    separating into recent past releases (with actuals) and upcoming scheduled catalysts (with exact BST time).
    """
    recent = []
    upcoming = []
    try:
        raw_events = forex_service.fetch_raw_calendar()
        dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        target_currencies = {currency, "USD"}
        for e in raw_events:
            c_curr = e.get("country", "")
            title = e.get("title", "")
            impact = e.get("impact", "")

            # If oil, include energy events
            is_energy_event = category == "oil" and any(k in title.lower() for k in ["oil", "crude", "inventor", "natural gas", "petroleum", "api"])
            is_relevant_curr = c_curr in target_currencies and impact in ["High", "Medium"]

            if is_energy_event or is_relevant_curr:
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
                    "country": c_curr,
                    "impact": impact,
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
        logger.warning(f"Error fetching calendar events for {currency}: {e}")

    # Sort upcoming ascending (nearest first)
    upcoming.sort(key=lambda x: x["dt"] or datetime.datetime.max.replace(tzinfo=datetime.timezone.utc))
    # Sort recent descending (freshest first)
    recent.sort(key=lambda x: x["dt"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc), reverse=True)

    return {
        "recent": recent[:8],
        "upcoming": upcoming[:8]
    }

def fetch_asset_wire_news(category: str, asset_name: str, limit: int = 12) -> List[Dict[str, Any]]:
    """
    Searches Google News RSS for macro and commodity wire dispatches across:
    1. Past 7 days (when:7d) for recent market price action and catalysts
    2. Past 30 days (when:30d) for structural macro policies still actively anchoring the trend
    """
    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    articles = []
    seen = set()

    clean_q = asset_name.replace(" ", "+").replace("/", "+")
    queries = [
        f"{clean_q}+price+news+when:7d",
        f"{clean_q}+macro+outlook+when:30d"
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for q in queries:
        query_url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        try:
            resp = requests.get(query_url, headers=headers, timeout=8)
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
                    pub_dhaka = dt_obj.astimezone(dhaka_tz).strftime("%I:%M %p, %d %b %Y (%A)") if dt_obj else pub_str

                    source_name = "Global Wire"
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
            logger.debug(f"Wire news fetch note for query '{q}': {e}")

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
    # Up to 12 from last 48h (today & yesterday), up to 8 from days 3-7, up to 8 from days 8-30
    selected = b_30d[-8:] + b_7d[-8:] + b_48h[-12:]
    selected.sort(key=lambda x: x["published_dt"] or now_utc)
    return selected

def generate_asset_prediction_analysis(query: str) -> str:
    """
    Universal Entry Point:
    Takes any instrument query (e.g. 'gold', 'nasdaq', 'sp500', 'dow', 'btc', 'eth', 'eurusd', 'oil')
    and outputs a comprehensive, institutional-grade market situation & sequential movement prediction report.
    Analyzes 7-day to 30-day active catalysts, specifies impact expiry & next update schedules,
    defines exact Short/Long-Term timeframes, and highlights upcoming high-impact catalysts in BST.
    """
    profile = get_asset_profile(query)
    ticker = profile["ticker"]
    name = profile["name"]
    category = profile["category"]
    currency = profile["currency"]

    # 1. Fetch Live Technicals
    metrics = fetch_asset_technicals(ticker, name)

    # 2. Fetch ForexFactory Direct Breaking News
    ff_stories = fetch_asset_forexfactory_news(category, currency, limit=30)

    # 3. Fetch ForexFactory Economic Calendar (Past & Upcoming)
    cal_data = fetch_asset_calendar_events(currency, category)
    recent_cal = cal_data.get("recent", [])
    upcoming_cal = cal_data.get("upcoming", [])

    # 4. Fetch Commodity / Financial Wire Dispatches (Last 7 to 30 Days)
    wire_news = fetch_asset_wire_news(category, name, limit=28)

    dhaka_tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    dhaka_now = datetime.datetime.now(dhaka_tz).strftime("%I:%M %p, %d %B %Y (%A)")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff_48h = now_utc - datetime.timedelta(hours=48)

    # Build prompt blocks
    tech_line = (
        f"{name} ({ticker}): Current Price: ${metrics.get('current_price', 'N/A')} "
        f"({metrics.get('change_pct', 0):+}% | 24h High: ${metrics.get('high_24h', 'N/A')} | "
        f"24h Low: ${metrics.get('low_24h', 'N/A')} | RSI(14): {metrics.get('rsi', 'N/A')} | "
        f"EMA20: ${metrics.get('ema20', 'N/A')} | ATR: ${metrics.get('atr', 'N/A')})"
    )

    ff_lines = []
    for it in ff_stories:
        dt = it.get("published_dt")
        p_tag = " [গত ২৪-৪৮ ঘণ্টা / আজ-গতকাল]" if dt and dt >= cutoff_48h else " [গত ৩–৭ দিন]"
        ff_lines.append(f"• [{it['pub_date_dhaka']}]{p_tag} [{it['impact_label']}] ({it['source']}) {it['title']}")
    ff_feed = "\n".join(ff_lines) if ff_lines else "Active institutional breaking news monitored."

    recent_cal_lines = []
    for c in recent_cal:
        recent_cal_lines.append(f"• [{c['time_dhaka']}] ({c['impact']}) {c['country']} - {c['title']} | Actual: {c['actual']} | Forecast: {c['forecast']} | Previous: {c['previous']}")
    recent_cal_feed = "\n".join(recent_cal_lines) if recent_cal_lines else "Recent economic calendar releases monitored."

    upcoming_cal_lines = []
    for u in upcoming_cal:
        upcoming_cal_lines.append(f"• [{u['time_dhaka']}] [🔴 {u['impact'].upper()}] {u['country']} - {u['title']} | Forecast: {u['forecast']} | Previous: {u['previous']}")
    upcoming_cal_feed = "\n".join(upcoming_cal_lines) if upcoming_cal_lines else "Upcoming scheduled high-impact catalysts active."

    wire_lines = []
    for w in wire_news:
        dt = w.get("published_dt")
        if dt and dt >= cutoff_48h:
            w_tag = " [গত ২৪-৪৮ ঘণ্টা / আজ-গতকাল]"
        elif dt and dt >= (now_utc - datetime.timedelta(days=7)):
            w_tag = " [গত ৩–৭ দিন]"
        else:
            w_tag = " [গত ৮–৩০ দিন ম্যাক্রো ভিত্তি]"
        wire_lines.append(f"• [{w['pub_date_dhaka']}]{w_tag} ({w['source']}) {w['title']}")
    wire_feed_30d = "\n".join(wire_lines) if wire_lines else "Global wire dispatches (7–30 days) active."

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

FOREX FACTORY ECONOMIC CALENDAR (RECENT PAST RELEASES WITH ACTUAL DATA):
{recent_cal_feed}

FOREX FACTORY ECONOMIC CALENDAR (UPCOMING SCHEDULED HIGH-IMPACT CATALYSTS - IN BST):
{upcoming_cal_feed}

GLOBAL FINANCIAL & COMMODITY WIRE DISPATCHES (PAST 7 TO 30 DAYS MACRO SPECTRUM):
{wire_feed_30d}

CRITICAL TASK & INSTRUCTIONS:
Provide a robust, institutional-grade market analysis and movement prediction for {name} in fluent, professional Bengali.
Ensure that:
1. Data Horizon: Synthesize active macro & market catalysts from the past 7 to 30 days whose impact is still actively anchoring the current trend.
2. Time Horizon Definitions: Clearly define the exact time horizon for Short-Term (১–৩ দিন / সর্বোচ্চ ১ সপ্তাহ) and Long-Term (২ সপ্তাহ থেকে ১–৩ মাস / Q4).
3. Explicit Catalyst Detailing: In Section 2, DO NOT write a single vague narrative paragraph. Every key news item must be EXPLICITLY and SEPARATELY presented with:
   - Specific Headline (খবরের সঠিক শিরোনাম)
   - Publication Date & Time in BST (বাংলাদেশ সময়)
   - Source & Impact level (যেমন: Forex Factory [🔴 HIGH], Reuters, Bloomberg, WSJ)
   - Price reaction & immediate market impact
   - ⌛ Impact Expiry Horizon (কখন/কতদিন পর প্রভাব শেষ বা স্তিমিত হবে)
   - 🔄 Next Follow-up / Recurrence Schedule (পরবর্তী আপডেট বা অফিশিয়াল ডেটা বাংলাদেশ সময় কবে আসবে)
4. Do NOT omit any news from yesterday (২৪ সেপ্টেম্বর) or today (২৫ সেপ্টেম্বর). All major recent headlines from the feed above must be itemized.
5. Upcoming High-Impact Catalysts: Detail upcoming events that could cause major volatility or trend change, with exact dates and times in বাংলাদেশ সময় (BST / GMT+6).
6. All times must strictly be in Bangladesh Time (BST / GMT+6).

### MANDATORY REPORT STRUCTURE:

1. 📊 **বর্তমান বাজার পরিস্থিতি ও লাইভ স্ন্যাপশট (Live Market Snapshot):**
   - {name}-এর বর্তমান লাইভ মার্কেট প্রাইস, দৈনিক পরিবর্তন (Change %), ২৪ ঘণ্টার হাই/লো এবং টেকনিক্যাল মোমেন্টাম (RSI, EMA20 এবং ATR ভোলাটিলিটি অবস্থান)।

2. ⏳ **ঘটনাগুলোর পর্যায়ক্রমিক ও কালানুক্রমিক গতিপথ (Sequential Catalyst Trajectory - গত ৭ থেকে ৩০ দিনের সক্রিয় প্রভাবক):**
   ⚠️ প্রতিটি গুরুত্বপূর্ণ খবরকে আলাদা আলাদা সাব-এন্ট্রি হিসেবে সুনির্দিষ্ট শিরোনাম, সময়, উৎস এবং ইমপ্যাক্টসহ উপস্থাপন করতে হবে:

   🔹 **ধাপ ১: ম্যাক্রো পটভূমি ও গত ৩০ দিনের কাঠামোগত ভিত্তি (দিন ৮–৩০):**
   - সেন্ট্রাল ব্যাংক পলিসি, বৈশ্বিক লিকুইডিটি ও দীর্ঘমেয়াদী ফান্ডামেন্টাল ভিত্তি তৈরি করা খবরের তালিকা ও বিবরণ।
   - প্রতিটি খবরের জন্য: শিরোনাম, ⌛ ইমপ্যাক্ট মেয়াদ ও 🔄 পরবর্তী ফলো-আপ দিনক্ষণ।

   🔹 **ধাপ ২: গত ৩–৭ দিনের প্রধান অনুঘটক ও অর্থনৈতিক ডেটা (দিন ৩–৭):**
   - বিগত সপ্তাহে প্রকাশিত প্রধান অর্থনৈতিক বা ভূ-রাজনৈতিক খবরের তালিকা।
   - প্রতিটি খবরের জন্য: শিরোনাম, প্রাইস প্রতিক্রিয়া, ⌛ ইমপ্যাক্ট মেয়াদ ও 🔄 পরবর্তী ফলো-আপ দিনক্ষণ।

   🔹 **ধাপ ৩: গতকাল ও আজকের ব্রেকিং নিউজ ও সরাসরি প্রাইস ইমপ্যাক্ট (গত ২৪–৪৮ ঘণ্টা):**
   (গতকাল এবং আজকের প্রতিটি খবরকে পয়েন্ট আকারে সুনির্দিষ্ট শিরোনাম, তারিখ ও সময়সহ তুলে ধরতে হবে):
   • 📰 **[তারিখ ও সময় - BST] | [উৎস ও ইমপ্যাক্ট: যেমন 🔴 HIGH / Forex Factory / Reuters / Bloomberg]:**
     - **খবরের শিরোনাম:** "খবরের সুনির্দিষ্ট শিরোনাম"
     - **বাজার পরিস্থিতি ও প্রাইস প্রতিক্রিয়া:** এই সংবাদের ফলে তাৎক্ষণিক কী প্রভাব পড়েছে এবং বাজার সেন্টিমেন্ট কেমন রূপ নিয়েছে।
     - ⌛ **ইমপ্যাক্ট স্থায়ীত্ব ও মেয়াদ (Impact Duration & Expiry Horizon):** এই প্রভাব কতদিন পর্যন্ত বাজারে থাকবে এবং কোন ইভেন্টের পর শেষ হবে।
     - 🔄 **পরবর্তী ফলো-আপ আপডেট বা পুনরাবৃত্তির দিনক্ষণ (Next Follow-up in BST):** বাংলাদেশ সময়ে পরবর্তী ডেটা বা অফিশিয়াল আপডেট কবে আসবে।

   🔹 **ধাপ ৪: ফরেক্সফ্যাক্টরি অর্থনৈতিক ক্যালেন্ডার ডেটা বিশ্লেষণ:**
   - প্রকাশিত সাম্প্রতিক ইকোনমিক ডেটার (Actual vs Forecast vs Previous) প্রতিফলন ও বর্তমান প্রভাব।

3. ⚡ **স্বল্পমেয়াদী মুভমেন্ট প্রেডিকশন (Short-Term Prediction: ১–৩ দিন / সর্বোচ্চ ১ সপ্তাহ):**
   - **স্বল্পমেয়াদের সুনির্দিষ্ট সময়সীমা:** *১ থেকে ৩ কার্যদিবস (বা সর্বোচ্চ ১ সপ্তাহ / ইন্ট্রাডে থেকে সুইং হরাইজন)*
   - **ডিরেকশন ও সেন্টিমেন্ট (Bias):** [বুলিশ 🟢 / বেয়ারিশ 🔴 / নিরপেক্ষ-রেঞ্জবাউন্ড 🟡]
   - **প্রত্যাশিত প্রাইস রেঞ্জ (Expected Range):** {name}-এর জন্য নির্দিষ্ট প্রাইস রেঞ্জ
   - **মূল টেকনিক্যাল লেভেল:** তাৎক্ষণিক সাপোর্ট (Support) ও রেজিস্ট্যান্স (Resistance) জোন
   - **নিকটবর্তী ক্যাটালাইস্ট:** আগামী ২৪-৭২ ঘণ্টার মধ্যে কোন ইভেন্ট বা ডেটা বড় স্পাইক ঘটাতে পারে

4. 🌐 **দীর্ঘমেয়াদী মুভমেন্ট প্রেডিকশন (Long-Term Prediction: ২ সপ্তাহ থেকে ১–৩ মাস / চলতি কোয়ার্টার Q4):**
   - **দীর্ঘমেয়াদের সুনির্দিষ্ট সময়সীমা:** *২ সপ্তাহ থেকে ১–৩ মাস (বা চলতি ২০২৬ সালের Q4 কোয়ার্টার পর্যন্ত কাঠামোগত ট্রেন্ড)*
   - **কাঠামোগত ম্যাক্রো ট্রেন্ড (Structural Macro Trend):** দীর্ঘমেয়াদী প্রাইস ডিরেকশন
   - **ফান্ডামেন্টাল ভারসাম্য:** সেন্ট্রাল ব্যাংক পলিসি, বৈশ্বিক লিকুইডিটি ও ফান্ডামেন্টাল দৃষ্টিভঙ্গি
   - **টার্গেট প্রাইস জোন (Target Levels):** দীর্ঘমেয়াদী সম্ভাব্য টার্গেট জোন

5. 📅 **আসন্ন শীর্ষ ক্যাটালাইস্ট ও সম্ভাব্য বড় পরিবর্তন (Upcoming High-Impact Catalysts & Market Impact):**
   - আগামী দিনগুলোতে কোন কোন আসন্ন ইভেন্টের কারণে মার্কেটে বড় পরিবর্তন বা তীব্র ভোলাটিলিটি আসতে পারে।
   - প্রতিটি ইভেন্ট **বাংলাদেশ সময় (BST / GMT+6)** কোন দিন এবং কয়টার সময় রিলিজ হবে তা সময়সহ উল্লেখ।
   - প্রত্যাশিত পরিবর্তন ও মার্কেটের সম্ভাব্য প্রতিক্রিয়া (যেমন: ডেটা অপ্রত্যাশিত এলে কোন লেভেলে ব্রেকআউট হতে পারে)।

6. ⚖️ **বুলিশ বনাম বেয়ারিশ প্রভাবকের তুলনামূলক মূল্যায়ন (Bullish vs Bearish Forces):**
   - 🟢 **দাম বাড়ানোর চালিকাশক্তি (Bullish Drivers):** [নির্দিষ্ট পয়েন্ট]
   - 🔴 **দাম কমানোর চালিকাশক্তি (Bearish Drivers):** [নির্দিষ্ট পয়েন্ট]

7. 🎯 **ট্রেডারদের স্ট্র্যাটেজি ও ঝুঁকি ব্যবস্থাপনা (Actionable Trading Playbook & Risk Controls):**
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
