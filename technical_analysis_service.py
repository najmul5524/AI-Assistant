"""
Technical Analysis & Candlestick Dissection (ক্যান্ডেলের ব্যবচ্ছেদ) Service.

Provides real-time intraday candlestick microstructure analysis, intra-candle formation
tracking over time (early manipulation vs mid expansion vs late rejection wicks), sequential
High/Low break vs liquidity sweep detection, and institutional-grade trading signals.
"""

import datetime
import logging
import math
from typing import Dict, Any, List, Optional, Tuple
import requests

from config import DEFAULT_TIMEZONE
from llm_manager import MultiTierLLMManager

logger = logging.getLogger(__name__)

# Yahoo Finance Chart API headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Symbol aliases mapping
SYMBOL_MAP = {
    "gold": ("GC=F", "Gold (XAU/USD)"),
    "xau": ("GC=F", "Gold (XAU/USD)"),
    "xauusd": ("GC=F", "Gold (XAU/USD)"),
    "silver": ("SI=F", "Silver (XAG/USD)"),
    "xag": ("SI=F", "Silver (XAG/USD)"),
    "xagusd": ("SI=F", "Silver (XAG/USD)"),
    "btc": ("BTC-USD", "Bitcoin (BTC/USD)"),
    "bitcoin": ("BTC-USD", "Bitcoin (BTC/USD)"),
    "btcusd": ("BTC-USD", "Bitcoin (BTC/USD)"),
    "eth": ("ETH-USD", "Ethereum (ETH/USD)"),
    "ethereum": ("ETH-USD", "Ethereum (ETH/USD)"),
    "ethusd": ("ETH-USD", "Ethereum (ETH/USD)"),
    "eur": ("EURUSD=X", "EUR/USD"),
    "eurusd": ("EURUSD=X", "EUR/USD"),
    "gbp": ("GBPUSD=X", "GBP/USD"),
    "gbpusd": ("GBPUSD=X", "GBP/USD"),
    "jpy": ("JPY=X", "USD/JPY"),
    "usdjpy": ("JPY=X", "USD/JPY"),
    "aud": ("AUDUSD=X", "AUD/USD"),
    "audusd": ("AUDUSD=X", "AUD/USD"),
    "cad": ("CAD=X", "USD/CAD"),
    "usdcad": ("CAD=X", "USD/CAD"),
    "chf": ("CHF=X", "USD/CHF"),
    "usdchf": ("CHF=X", "USD/CHF"),
    "nasdaq": ("NQ=F", "Nasdaq 100 Futures"),
    "nq": ("NQ=F", "Nasdaq 100 Futures"),
    "ndx": ("NQ=F", "Nasdaq 100 Futures"),
    "sp500": ("ES=F", "S&P 500 Futures"),
    "spx": ("ES=F", "S&P 500 Futures"),
    "es": ("ES=F", "S&P 500 Futures"),
    "oil": ("CL=F", "Crude Oil (WTI)"),
    "crude": ("CL=F", "Crude Oil (WTI)"),
    "wti": ("CL=F", "Crude Oil (WTI)"),
    "cl": ("CL=F", "Crude Oil (WTI)")
}

_llm_instance = None

def get_llm() -> MultiTierLLMManager:
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = MultiTierLLMManager()
    return _llm_instance

def resolve_symbol(query: str) -> Tuple[str, str]:
    """Resolves user query to Yahoo Finance ticker and human readable name."""
    clean = query.strip().lower().replace("/", "").replace("-", "")
    if clean in SYMBOL_MAP:
        return SYMBOL_MAP[clean]
    
    # Try partial matching
    for key, val in SYMBOL_MAP.items():
        if key in clean or clean in key:
            return val

    # Default fallback: treat as raw symbol
    raw = query.strip().upper()
    return (raw, raw)

def fetch_candles(ticker: str, interval: str = "15m", range_str: str = "1d") -> Optional[List[Dict[str, Any]]]:
    """
    Fetches raw OHLCV candle records from Yahoo Finance chart API.
    Returns list of dicts: [{'time': dt, 'open': float, 'high': float, 'low': float, 'close': float, 'volume': int}]
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_str}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            logger.warning(f"Yahoo chart fetch status {resp.status_code} for {ticker}")
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        res0 = result[0]
        timestamps = res0.get("timestamp", [])
        quote = res0.get("indicators", {}).get("quote", [{}])[0]
        
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])

        candles = []
        for i in range(len(timestamps)):
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            l = lows[i] if i < len(lows) else None
            c = closes[i] if i < len(closes) else None
            v = volumes[i] if i < len(volumes) else 0

            # Filter out None/null points (sometimes Yahoo returns null on halts)
            if o is not None and h is not None and l is not None and c is not None:
                candles.append({
                    "timestamp": timestamps[i],
                    "time": datetime.datetime.fromtimestamp(timestamps[i], datetime.timezone.utc),
                    "open": float(o),
                    "high": float(h),
                    "low": float(l),
                    "close": float(c),
                    "volume": float(v) if v is not None else 0.0
                })
        return candles
    except Exception as e:
        logger.error(f"Error fetching candles for {ticker} ({interval}): {e}")
        return None

# ----------------- Pure Python Technical Indicators ----------------- #

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)

def calculate_ema(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = (p * k) + (ema * (1.0 - k))
    return round(ema, 4)

def calculate_atr(candles: List[Dict[str, Any]], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        prev_c = candles[i-1]["close"]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 4)

# ----------------- Candlestick Microstructure Dissection ----------------- #

def dissect_candle(candle: Dict[str, Any]) -> Dict[str, Any]:
    """Performs deep anatomical breakdown of a single candlestick."""
    o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]
    total_range = max(h - l, 0.00001)
    body = abs(c - o)
    is_bullish = c >= o
    upper_wick = h - (c if is_bullish else o)
    lower_wick = (o if is_bullish else c) - l

    body_pct = round((body / total_range) * 100, 1)
    upper_wick_pct = round((upper_wick / total_range) * 100, 1)
    lower_wick_pct = round((lower_wick / total_range) * 100, 1)

    # Classification
    classification = "Normal"
    if body_pct >= 70:
        classification = "Bullish Expansion (Marubozu)" if is_bullish else "Bearish Expansion (Marubozu)"
    elif lower_wick_pct >= 50 and body_pct <= 35:
        classification = "Bullish Rejection (Hammer / Pin Bar)"
    elif upper_wick_pct >= 50 and body_pct <= 35:
        classification = "Bearish Rejection (Shooting Star / Pin Bar)"
    elif body_pct <= 15:
        classification = "Indecision / Doji"
    elif upper_wick_pct >= 30 and lower_wick_pct >= 30:
        classification = "High Volatility Spinning Top (Two-way Absorption)"

    return {
        "open": round(o, 4),
        "high": round(h, 4),
        "low": round(l, 4),
        "close": round(c, 4),
        "volume": candle["volume"],
        "range": round(total_range, 4),
        "body": round(body, 4),
        "upper_wick": round(upper_wick, 4),
        "lower_wick": round(lower_wick, 4),
        "body_pct": body_pct,
        "upper_wick_pct": upper_wick_pct,
        "lower_wick_pct": lower_wick_pct,
        "is_bullish": is_bullish,
        "classification": classification
    }

def analyze_candle_sequence(candles: List[Dict[str, Any]], sub_candles_5m: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Forensic analysis of the sequence:
    1. Previous candle anatomy
    2. Current candle anatomy
    3. Interaction (Did current break previous High/Low? True Breakout vs Liquidity Sweep?)
    4. Intra-candle progression (Early manipulation -> Mid expansion -> Late closing)
    5. Technical indicators (RSI, EMAs, ATR, RVOL)
    """
    if len(candles) < 2:
        return {}

    curr = candles[-1]
    prev = candles[-2]
    prev_prev = candles[-3] if len(candles) >= 3 else None

    curr_anat = dissect_candle(curr)
    prev_anat = dissect_candle(prev)

    # High / Low Interaction
    broke_prev_high = curr["high"] > prev["high"]
    broke_prev_low = curr["low"] < prev["low"]
    
    sweep_prev_high = (curr["high"] > prev["high"]) and (curr["close"] < prev["high"])
    sweep_prev_low = (curr["low"] < prev["low"]) and (curr["close"] > prev["low"])

    true_break_high = (curr["close"] > prev["high"]) and (curr_anat["body_pct"] >= 50)
    true_break_low = (curr["close"] < prev["low"]) and (curr_anat["body_pct"] >= 50)

    inside_bar = (curr["high"] <= prev["high"]) and (curr["low"] >= prev["low"])
    outside_engulfing = (curr["high"] > prev["high"]) and (curr["low"] < prev["low"])

    interaction_type = "Inside Consolidation"
    interaction_desc_bn = "ক্যান্ডেলটি পূর্ববর্তী ক্যান্ডেলের রেঞ্জের ভেতর সীমাবদ্ধ (ভলাটিলিটি কম্প্রেশন)।"
    if sweep_prev_high:
        interaction_type = "Bearish Liquidity Grab (Turtle Soup / Trap)"
        interaction_desc_bn = "পূর্ববর্তী ক্যান্ডেলের High ব্রেক করে রিটেইল বায়ারদের ট্র্যাপ করা হয়েছে, কিন্তু ক্লোজ হয়েছে নিচে (বড় বেয়ারিশ সুইপ উইক)।"
    elif sweep_prev_low:
        interaction_type = "Bullish Liquidity Grab (Stop Hunt / Trap)"
        interaction_desc_bn = "পূর্ববর্তী ক্যান্ডেলের Low ভেঙে রিটেইল সেলারদের স্টপ লস হান্ট করা হয়েছে, কিন্তু ক্লোজ হয়েছে উপরে (বুলিশ রিজেকশন উইক)।"
    elif true_break_high:
        interaction_type = "True Bullish Expansion"
        interaction_desc_bn = "পূর্ববর্তী ক্যান্ডেলের High এর উপরে শক্তিশালী বডি নিয়ে ক্লোজ হয়েছে (স্ট্রং ইনস্টিটিউশনাল বুলিশ মোমেন্টাম)।"
    elif true_break_low:
        interaction_type = "True Bearish Breakdown"
        interaction_desc_bn = "পূর্ববর্তী ক্যান্ডেলের Low এর নিচে শক্তিশালী বডি নিয়ে ক্লোজ হয়েছে (স্ট্রং ইনস্টিটিউশনাল বেয়ারিশ মোমেন্টাম)।"
    elif outside_engulfing:
        interaction_type = "Outside Engulfing / Range Expansion"
        interaction_desc_bn = "পূর্ববর্তী ক্যান্ডেলের High ও Low উভয়ই ভেঙে বিশাল রেঞ্জ তৈরি করেছে (অস্থির ভলিউম প্রসারন)।"

    # Intra-candle decomposition (using 5m sub-candles if available)
    intra_phases = []
    if sub_candles_5m and len(sub_candles_5m) >= 3:
        last_3 = sub_candles_5m[-3:]
        # Phase 1: Early (0-5m)
        c1 = dissect_candle(last_3[0])
        p1_dir = "বুলিশ" if c1["is_bullish"] else "বেয়ারিশ"
        intra_phases.append(f"১. প্রারম্ভিক পর্যায় (Early 0-5m): ওপেনিংয়ে {p1_dir} পুশ (বডি {c1['body_pct']}%, উইক {c1['upper_wick_pct']}%/{c1['lower_wick_pct']}%) - প্রাথমিক ম্যানিপুলেশন/মুভ।")
        
        # Phase 2: Mid (5-10m)
        c2 = dissect_candle(last_3[1])
        p2_dir = "বুলিশ" if c2["is_bullish"] else "বেয়ারিশ"
        intra_phases.append(f"২. মধ্যবর্তী পর্যায় (Mid 5-10m): ভলিউম ও বডির রূপান্তর ({p2_dir}, বডি {c2['body_pct']}%) - মোমেন্টাম বিস্তার।")

        # Phase 3: Late (10-15m)
        c3 = dissect_candle(last_3[2])
        p3_dir = "বুলিশ" if c3["is_bullish"] else "বেয়ারিশ"
        intra_phases.append(f"৩. সমাপনী পর্যায় (Late 10-15m): সমাপ্তি ও ক্লোজিং ({p3_dir}, বডি {c3['body_pct']}%, রিজেকশন উইক {c3['upper_wick_pct'] if not c3['is_bullish'] else c3['lower_wick_pct']}%) - ফাইনাল রিজেকশন/অ্যাবসর্পশন।")
    else:
        # Reconstruct intra-candle progression from single candle anatomy
        if curr_anat["is_bullish"]:
            intra_phases.append(f"১. প্রারম্ভিক পর্যায়: ওপেন হওয়ার পর প্রথমে লো তৈরি ({curr_anat['lower_wick_pct']}% লোয়ার উইক) যা রিটেইল সেলারদের ফাঁদে ফেলে।")
            intra_phases.append(f"২. মধ্যবর্তী পর্যায়: স্ট্রং বাইয়ার্স প্রবেশ করে হাই লেভেলে পুশ করে (বডি {curr_anat['body_pct']}%)।")
            intra_phases.append(f"৩. সমাপনী পর্যায়: সামান্য প্রফিট টেকিং রিজেকশন ({curr_anat['upper_wick_pct']}% আপার উইক) শেষে বুলিশ ক্লোজ।")
        else:
            intra_phases.append(f"১. প্রারম্ভিক পর্যায়: ওপেন হওয়ার পর প্রথমে হাই তৈরি ({curr_anat['upper_wick_pct']}% আপার উইক) যা রিটেইল বায়ারদের ফাঁদে ফেলে।")
            intra_phases.append(f"২. মধ্যবর্তী পর্যায়: এগ্রেসিভ সেলিং প্রেশারে রেঞ্জ নিচে বিস্তার লাভ করে (বডি {curr_anat['body_pct']}%)।")
            intra_phases.append(f"৩. সমাপনী পর্যায়: নিচের লেভেলে সামান্য অ্যাবসর্পশন ({curr_anat['lower_wick_pct']}% লোয়ার উইক) শেষে বেয়ারিশ ক্লোজ।")

    # Technical Indicators
    closes = [c["close"] for c in candles]
    rsi_14 = calculate_rsi(closes, period=14)
    ema_9 = calculate_ema(closes, period=9)
    ema_21 = calculate_ema(closes, period=21)
    ema_50 = calculate_ema(closes, period=50)
    atr_14 = calculate_atr(candles, period=14)

    # Volume comparison
    vols = [c["volume"] for c in candles if c["volume"] > 0]
    avg_vol = (sum(vols[-20:]) / min(len(vols), 20)) if vols else 1.0
    curr_vol = curr["volume"]
    rvol = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 1.0

    return {
        "current": curr_anat,
        "previous": prev_anat,
        "interaction": {
            "type": interaction_type,
            "desc_bn": interaction_desc_bn,
            "broke_prev_high": broke_prev_high,
            "broke_prev_low": broke_prev_low,
            "sweep_prev_high": sweep_prev_high,
            "sweep_prev_low": sweep_prev_low,
            "true_break_high": true_break_high,
            "true_break_low": true_break_low,
            "inside_bar": inside_bar
        },
        "intra_phases": intra_phases,
        "indicators": {
            "rsi_14": rsi_14,
            "ema_9": ema_9,
            "ema_21": ema_21,
            "ema_50": ema_50,
            "atr_14": atr_14,
            "rvol": rvol
        }
    }

# ----------------- LLM Forensic Synthesis & Signal Generation ----------------- #

def generate_candle_dissection_report(symbol_query: str, timeframe: str = "15m") -> str:
    """
    Main entry point: fetches live OHLCV, calculates microscopic candle anatomy,
    reconstructs temporal formation, detects liquidity traps, and generates an institutional
    forensic dissection and high-probability trading signal in bilingual Bengali-English.
    """
    ticker, display_name = resolve_symbol(symbol_query)
    
    # 1. Fetch target timeframe candles
    candles = fetch_candles(ticker, interval=timeframe, range_str="1d")
    if not candles or len(candles) < 5:
        # Fallback to 5d range if market just opened
        candles = fetch_candles(ticker, interval=timeframe, range_str="5d")

    if not candles or len(candles) < 5:
        return f"❌ দুঃখিত, *{display_name}* ({ticker})-এর লাইভ ক্যান্ডেল ডেটা এই মুহূর্তে পাওয়া যাচ্ছে না। অনুগ্রহ করে একটু পর আবার চেষ্টা করুন বা অন্য সিম্বল দিন।"

    # 2. If timeframe is 15m, fetch 5m sub-candles for intra-candle reconstruction
    sub_5m = None
    if timeframe == "15m":
        sub_5m = fetch_candles(ticker, interval="5m", range_str="1d")

    # 3. Microstructure analysis
    analysis = analyze_candle_sequence(candles, sub_candles_5m=sub_5m)
    if not analysis:
        return f"❌ *{display_name}* এর ক্যান্ডেল ব্যবচ্ছেদ গণনায় ত্রুটি ঘটেছে।"

    curr = analysis["current"]
    prev = analysis["previous"]
    inter = analysis["interaction"]
    phases = analysis["intra_phases"]
    inds = analysis["indicators"]

    # Format factual context for Gemini
    context_text = f"""
ASSET: {display_name} ({ticker})
TIMEFRAME: {timeframe}
CURRENT PRICE: {curr['close']}

1. CURRENT CANDLE ANATOMY:
- Open: {curr['open']}, High: {curr['high']}, Low: {curr['low']}, Close: {curr['close']}
- Total Range: {curr['range']}
- Real Body: {curr['body']} ({curr['body_pct']}% of range)
- Upper Wick: {curr['upper_wick']} ({curr['upper_wick_pct']}% of range)
- Lower Wick: {curr['lower_wick']} ({curr['lower_wick_pct']}% of range)
- Direction: {'BULLISH (Green)' if curr['is_bullish'] else 'BEARISH (Red)'}
- Pattern Type: {curr['classification']}

2. PREVIOUS CANDLE ANATOMY:
- Open: {prev['open']}, High: {prev['high']}, Low: {prev['low']}, Close: {prev['close']}
- Body: {prev['body_pct']}%, Upper Wick: {prev['upper_wick_pct']}%, Lower Wick: {prev['lower_wick_pct']}%
- Pattern: {prev['classification']}

3. SEQUENTIAL HIGH/LOW INTERACTION:
- Current High vs Prev High: Broke Prev High = {inter['broke_prev_high']}
- Current Low vs Prev Low: Broke Prev Low = {inter['broke_prev_low']}
- Liquidity Sweep High (Turtle Soup Bearish Trap): {inter['sweep_prev_high']}
- Liquidity Sweep Low (Stop Hunt Bullish Trap): {inter['sweep_prev_low']}
- True Expansion Breakout High: {inter['true_break_high']}
- True Expansion Breakdown Low: {inter['true_break_low']}
- Inside Bar: {inter['inside_bar']}
- Core Sequence Dynamic: {inter['type']} ({inter['desc_bn']})

4. INTRA-CANDLE LIFECYCLE (সময়ের সাথে ক্যান্ডেলের গঠন):
{chr(10).join(phases)}

5. CONFLUENCE INDICATORS:
- RSI (14): {inds['rsi_14']}
- EMA 9: {inds['ema_9']} | EMA 21: {inds['ema_21']} | EMA 50: {inds['ema_50']}
- Trend Alignment: {'Bullish Stack (9>21>50)' if inds['ema_9'] > inds['ema_21'] > inds['ema_50'] else ('Bearish Stack (9<21<50)' if inds['ema_9'] < inds['ema_21'] < inds['ema_50'] else 'Consolidation / Mixed')}
- ATR (14): {inds['atr_14']} (volatility buffer)
- Relative Volume (RVOL): {inds['rvol']}x
"""

    prompt = f"""You are an elite Institutional Price Action Specialist, ICT (Inner Circle Trader), and Forensic Candlestick Quantitative Analyst.
The trader requested an in-depth forensic candlestick dissection ("ক্যান্ডেলের ব্যবচ্ছেদ") and actionable intraday trading setup for {display_name} on the {timeframe} chart.

Here is the exact mathematical microstructure and intra-candle formation data:
{context_text}

Task:
Write a comprehensive, forensic, institutional candlestick dissection and actionable trading signal in professional, fluent Bengali, enriched with institutional English trading terms in parentheses.

Structure your response using these exact sections:

🔬 *১. ক্যান্ডেলের ব্যবচ্ছেদ (Candle Forensic Breakdown)*
- Explain the current candle's exact anatomy: Open, High, Low, Close, Range.
- Detail the exact mathematical distribution: Real Body % vs Upper Wick % vs Lower Wick %.
- Identify what this anatomy proves about buyer vs seller dominance (e.g., strong expansion vs absorption vs exhaustion).

⏱️ *২. সময়ের সাথে ক্যান্ডেলের গঠন (Intra-Candle Lifecycle)*
- Dissect how the candle formed chronologically over time (প্রারম্ভিক পর্যায় Early Judas/Fakeout -> মধ্যবর্তী বিস্তার Mid Expansion -> সমাপনী রিজেকশন/ক্লোজিং Late Absorption).
- Explain how institutional smart money engineered liquidity throughout this candle's duration.

🎯 *৩. পূর্ববর্তী ক্যান্ডেল ব্রেক ও লিকুইডিটি এনালাইসিস (Sequential High/Low Dynamics)*
- Explicitly analyze whether this candle broke the previous candle's High or Low.
- Distinguish whether it is a **True Breakout** (বডি দিয়ে ক্লোজ) or a **Liquidity Sweep / Stop Hunt Trap** (উইক দিয়ে হাই/লো পার করে ভেতরে ক্লোজ—ফাঁদে ফেলা হয়েছে)।
- Detail the structural shift (MSS / CHoCH / Market Structure Shift / Inside Bar).

🧠 *৪. ট্রেডার সাইকোলজি ও রিটেইল ট্র্যাপ (Retail vs Smart Money Psychology)*
- Where did retail breakout/breakdown traders enter, and where are their stop losses clustered?
- How did Smart Money (Banks / Market Makers) manipulate this candle?

🚀 *৫. হাই-কনভিকশন ট্রেডিং সেটআপ (Precision Actionable Trade Setup)*
Based on the forensic anatomy and ATR ({inds['atr_14']}), provide precise trading parameters:
- ⚡ **Action/Bias:** 🟢 BUY (Long) / 🔴 SELL (Short) / ⏳ WAIT (Neutral)
- 🎯 **Entry Price Zone (OTE):** (e.g., specific price range or pull-back level)
- 🛑 **Stop Loss (SL):** (Precise invalidation price, taking wick sweep + buffer into account)
- 🏁 **Take Profit 1 (TP1):** (Immediate liquidity target / 1:1.5 RR)
- 🏆 **Take Profit 2 (TP2):** (Major swing target / 1:2.5+ RR)
- ⚖️ **Risk-to-Reward Ratio (RRR):** (e.g. 1:2.5)
- 📊 **Institutional Confluence Score:** (e.g. 88% Confluence)

Write directly and clearly. Use bolding and bullet points for readability on Telegram. Do not include markdown code block quotes around the entire text.
"""

    llm = get_llm()
    try:
        report_text, provider_used, _ = llm.generate_response(prompt=prompt)
        # Append footer with provider info and asset badge
        footer = f"\n\n───────────────\n📊 *Asset:* {display_name} | *Timeframe:* {timeframe}\n🤖 *Engine:* {provider_used} (Institutional Microstructure)"
        return report_text + footer
    except Exception as e:
        logger.error(f"Error generating candle dissection with LLM: {e}")
        # Fallback manual formatted report if LLM fails
        return f"""
🔬 *{display_name} ({timeframe}) ক্যান্ডেল ব্যবচ্ছেদ*

• বর্তমান প্রাইস: *{curr['close']}*
• ক্যান্ডেল রেঞ্জ: *{curr['range']}* (বডি: *{curr['body_pct']}%*, আপার উইক: *{curr['upper_wick_pct']}%*, লোয়ার উইক: *{curr['lower_wick_pct']}%*)
• ক্যান্ডেল প্যাটার্ন: *{curr['classification']}*
• আগের ক্যান্ডেল ব্রেক: *{inter['desc_bn']}*
• আরএসআই (RSI 14): *{inds['rsi_14']}*
• ভলিউম অনুপাত (RVOL): *{inds['rvol']}x*

🎯 *সম্ভাব্য ডিরেকশন:* {'🟢 বুলিশ রিভার্সাল' if inter['sweep_prev_low'] or curr['is_bullish'] else '🔴 বেয়ারিশ রিভার্সাল'}
"""

# ----------------- Automated Intraday Scanner for High Conviction Setups ----------------- #

# Track already alerted setups to avoid spamming the user on the same candle
_ALERTED_CANDLES = set()

def scan_high_conviction_setups() -> List[Dict[str, Any]]:
    """
    Scans priority assets (Gold, BTC, EUR/USD) for high-probability liquidity sweep reversals
    (Turtle Soup setups: broke previous High/Low, formed >= 40% rejection wick, and closed inside range).
    """
    watch_list = [
        ("gold", "GC=F", "Gold (XAU/USD)"),
        ("btc", "BTC-USD", "Bitcoin (BTC/USD)"),
        ("eurusd", "EURUSD=X", "EUR/USD"),
        ("eth", "ETH-USD", "Ethereum (ETH/USD)")
    ]

    detected_alerts = []

    for alias, ticker, name in watch_list:
        try:
            candles = fetch_candles(ticker, interval="15m", range_str="1d")
            if not candles or len(candles) < 3:
                continue

            # Check the most recently closed candle (candles[-2] or candles[-1])
            # To be safe and avoid repaint, check candles[-2] (the fully completed candle)
            closed_candle = candles[-2]
            prev_candle = candles[-3]
            candle_id = f"{ticker}_15m_{closed_candle['timestamp']}"

            if candle_id in _ALERTED_CANDLES:
                continue

            anat = dissect_candle(closed_candle)
            prev_anat = dissect_candle(prev_candle)

            # Check Bullish Liquidity Sweep (Turtle Soup Long)
            # Broke prev low, but closed above prev low, lower wick >= 40%
            is_bullish_sweep = (
                closed_candle["low"] < prev_candle["low"]
                and closed_candle["close"] > prev_candle["low"]
                and anat["lower_wick_pct"] >= 40.0
            )

            # Check Bearish Liquidity Sweep (Turtle Soup Short)
            # Broke prev high, but closed below prev high, upper wick >= 40%
            is_bearish_sweep = (
                closed_candle["high"] > prev_candle["high"]
                and closed_candle["close"] < prev_candle["high"]
                and anat["upper_wick_pct"] >= 40.0
            )

            if is_bullish_sweep or is_bearish_sweep:
                _ALERTED_CANDLES.add(candle_id)
                direction = "🟢 BULLISH LIQUIDITY SWEEP (Buy Reversal)" if is_bullish_sweep else "🔴 BEARISH LIQUIDITY SWEEP (Sell Reversal)"
                setup_desc = (
                    f"পূর্ববর্তী 15m ক্যান্ডেলের Low ({prev_candle['low']}) ভেঙে রিটেইল স্টপ হান্ট করে {anat['lower_wick_pct']}% লোয়ার উইক নিয়ে ক্লোজ হয়েছে।"
                    if is_bullish_sweep else
                    f"পূর্ববর্তী 15m ক্যান্ডেলের High ({prev_candle['high']}) সুইপ করে রিটেইল বায়ারদের ট্র্যাপ করে {anat['upper_wick_pct']}% আপার উইক নিয়ে ক্লোজ হয়েছে।"
                )
                detected_alerts.append({
                    "ticker": ticker,
                    "name": name,
                    "timeframe": "15m",
                    "price": closed_candle["close"],
                    "direction": direction,
                    "is_bullish": is_bullish_sweep,
                    "setup_desc": setup_desc,
                    "high": closed_candle["high"],
                    "low": closed_candle["low"],
                    "timestamp": closed_candle["time"]
                })
        except Exception as e:
            logger.warning(f"Scanner error for {ticker}: {e}")

    return detected_alerts
