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
from pathlib import Path
import zoneinfo
import requests

from config import DEFAULT_TIMEZONE, REPORTS_DIR
from llm_manager import MultiTierLLMManager

# Ensure headless Agg backend for matplotlib
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except Exception as _mpl_err:
    HAS_MATPLOTLIB = False

logger = logging.getLogger(__name__)

# Yahoo Finance Chart API headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Symbol aliases mapping
SYMBOL_MAP = {
    # Commodities - Precious Metals
    "gold": ("GC=F", "Gold (XAU/USD)"),
    "xau": ("GC=F", "Gold (XAU/USD)"),
    "xauusd": ("GC=F", "Gold (XAU/USD)"),
    "gc": ("GC=F", "Gold (XAU/USD)"),
    "silver": ("SI=F", "Silver (XAG/USD)"),
    "xag": ("SI=F", "Silver (XAG/USD)"),
    "xagusd": ("SI=F", "Silver (XAG/USD)"),
    "si": ("SI=F", "Silver (XAG/USD)"),

    # US Indices - S&P 500
    "sp500": ("ES=F", "S&P 500 Futures"),
    "spx": ("ES=F", "S&P 500 Futures"),
    "sp": ("ES=F", "S&P 500 Futures"),
    "us500": ("ES=F", "S&P 500 (US500)"),
    "es": ("ES=F", "S&P 500 Futures"),
    "spy": ("SPY", "SPDR S&P 500 ETF"),
    "sandp": ("ES=F", "S&P 500 Futures"),
    "sandp500": ("ES=F", "S&P 500 Futures"),
    "snp500": ("ES=F", "S&P 500 Futures"),

    # US Indices - Nasdaq 100
    "nasdaq": ("NQ=F", "Nasdaq 100 Futures"),
    "nasdaq100": ("NQ=F", "Nasdaq 100 Futures"),
    "us100": ("NQ=F", "Nasdaq 100 (US100)"),
    "nq": ("NQ=F", "Nasdaq 100 Futures"),
    "ndx": ("NQ=F", "Nasdaq 100 Futures"),
    "qqq": ("QQQ", "Invesco QQQ Trust"),

    # US Indices - Dow Jones 30
    "dow": ("YM=F", "Dow Jones Futures"),
    "dowjones": ("YM=F", "Dow Jones Futures"),
    "dowjonson": ("YM=F", "Dow Jones Futures"),
    "dowjohnson": ("YM=F", "Dow Jones Futures"),
    "us30": ("YM=F", "Dow Jones (US30)"),
    "ym": ("YM=F", "Dow Jones Futures"),
    "dji": ("YM=F", "Dow Jones Futures"),
    "dia": ("DIA", "SPDR Dow Jones ETF"),

    # US Dollar Index (DXY)
    "dxy": ("DX-Y.NYB", "US Dollar Index (DXY)"),
    "dx": ("DX-Y.NYB", "US Dollar Index (DXY)"),
    "dollar": ("DX-Y.NYB", "US Dollar Index (DXY)"),
    "usdindex": ("DX-Y.NYB", "US Dollar Index (DXY)"),

    # Commodities - Energy
    "oil": ("CL=F", "Crude Oil (WTI)"),
    "crude": ("CL=F", "Crude Oil (WTI)"),
    "crudeoil": ("CL=F", "Crude Oil (WTI)"),
    "wti": ("CL=F", "Crude Oil (WTI)"),
    "cl": ("CL=F", "Crude Oil (WTI)"),
    "brent": ("BZ=F", "Brent Crude Oil"),

    # Major Forex Pairs
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
    "nzd": ("NZDUSD=X", "NZD/USD"),
    "nzdusd": ("NZDUSD=X", "NZD/USD"),
    "eurgbp": ("EURGBP=X", "EUR/GBP"),
    "eurjpy": ("EURJPY=X", "EUR/JPY"),
    "gbpjpy": ("GBPJPY=X", "GBP/JPY"),

    # Crypto
    "btc": ("BTC-USD", "Bitcoin (BTC/USD)"),
    "bitcoin": ("BTC-USD", "Bitcoin (BTC/USD)"),
    "btcusd": ("BTC-USD", "Bitcoin (BTC/USD)"),
    "eth": ("ETH-USD", "Ethereum (ETH/USD)"),
    "ethereum": ("ETH-USD", "Ethereum (ETH/USD)"),
    "etherium": ("ETH-USD", "Ethereum (ETH/USD)"),
    "ethusd": ("ETH-USD", "Ethereum (ETH/USD)"),
    "sol": ("SOL-USD", "Solana (SOL/USD)"),
    "solana": ("SOL-USD", "Solana (SOL/USD)"),
    "solusd": ("SOL-USD", "Solana (SOL/USD)"),
    "xrp": ("XRP-USD", "Ripple (XRP/USD)"),
    "ripple": ("XRP-USD", "Ripple (XRP/USD)")
}

_llm_instance = None

def get_llm() -> MultiTierLLMManager:
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = MultiTierLLMManager()
    return _llm_instance

def extract_timeframe_from_text(text: str) -> Optional[str]:
    """
    Scans a free-form natural language query (Bengali or English) and extracts
    the requested timeframe if explicitly mentioned. Returns None if no timeframe is specified.
    """
    if not text:
        return None

    t_lower = text.lower()

    # Check 1 Day (1d)
    if any(k in t_lower for k in [
        "daily", "day", "ডেইলি", "দৈনিক", "1 day", "1day", "১ দিন", "১দিন", "১দিনের",
        "1d", "d1", "একদিন", "এক দিন"
    ]):
        return "1d"

    # Check 4 Hours (4h)
    if any(k in t_lower for k in [
        "4h", "h4", "4 hour", "4 hours", "4 hr", "4hr", "৪ ঘণ্টা", "৪ঘণ্টা", "৪ ঘন্টা", "৪ঘন্টা",
        "৪ ঘণ্টার", "৪ ঘন্টার", "4 ঘণ্টা", "4 ঘন্টা", "চার ঘণ্টা", "চার ঘন্টা"
    ]):
        return "4h"

    # Check 1 Hour (1h)
    if any(k in t_lower for k in [
        "1h", "h1", "1 hour", "1 hours", "1 hr", "1hr", "60m", "m60", "১ ঘণ্টা", "১ঘণ্টা", "১ ঘন্টা", "১ঘন্টা",
        "১ ঘণ্টার", "১ ঘন্টার", "1 ঘণ্টা", "1 ঘন্টা", "এক ঘণ্টা", "এক ঘন্টা", "প্রতি ঘণ্টা"
    ]):
        return "1h"

    # Check 30 Minutes (30m)
    if any(k in t_lower for k in [
        "30m", "m30", "30 min", "30 mins", "30 minute", "30 minutes", "৩০ মিনিট", "৩০মিনিট",
        "৩০ মিনিটের", "30 মিনিট", "30মিনিট", "আধা ঘণ্টা", "আধা ঘন্টা", "আধ ঘণ্টা", "আধ ঘন্টা"
    ]):
        return "30m"

    # Check 15 Minutes (15m)
    if any(k in t_lower for k in [
        "15m", "m15", "15 min", "15 mins", "15 minute", "15 minutes", "১৫ মিনিট", "১৫মিনিট",
        "১৫ মিনিটের", "15 মিনিট", "15মিনিট"
    ]):
        return "15m"

    # Check 5 Minutes (5m)
    if any(k in t_lower for k in [
        "5m", "m5", "5 min", "5 mins", "5 minute", "5 minutes", "৫ মিনিট", "৫মিনিট",
        "৫ মিনিটের", "5 মিনিট", "5মিনিট", "পাঁচ মিনিট"
    ]):
        return "5m"

    # Check 1 Minute (1m)
    if any(k in t_lower for k in [
        "1m", "m1", "1 min", "1 minute", "১ মিনিট", "১মিনিট", "১ মিনিটের", "1 মিনিট", "1মিনিট", "এক মিনিট"
    ]):
        return "1m"

    return None

def normalize_timeframe(tf: Optional[str]) -> str:
    """
    Normalizes various timeframe representations (e.g., M15, 15m, 15min, H1, 1h, D1, daily,
    or Bengali phrases like '১ ঘণ্টা', '৪ ঘণ্টা', '৫ মিনিট') into a standard interval.
    """
    if not tf:
        return "15m"

    # Check Bengali or compound phrase match first
    extracted = extract_timeframe_from_text(str(tf))
    if extracted:
        return extracted

    clean = (
        str(tf).strip()
        .lower()
        .replace(" ", "")
        .replace("min", "m")
        .replace("mins", "m")
        .replace("minute", "m")
        .replace("minutes", "m")
        .replace("hour", "h")
        .replace("hours", "h")
        .replace("day", "d")
        .replace("days", "d")
    )
    tf_map = {
        "1m": "1m", "m1": "1m",
        "5m": "5m", "m5": "5m",
        "15m": "15m", "m15": "15m",
        "30m": "30m", "m30": "30m",
        "1h": "1h", "h1": "1h", "60m": "1h", "m60": "1h",
        "4h": "4h", "h4": "4h",
        "1d": "1d", "d1": "1d", "daily": "1d", "d": "1d"
    }
    return tf_map.get(clean, "15m")

def resolve_symbol(query: str) -> Tuple[str, str]:
    """
    Resolves user query to Yahoo Finance ticker and human readable name.
    Strips out slashes, dashes, ampersands ('&'), spaces, and underscores.
    """
    if not query:
        return ("GC=F", "Gold (XAU/USD)")

    raw = query.strip()
    clean = (
        raw.lower()
        .replace("/", "")
        .replace("-", "")
        .replace("&", "")
        .replace(" ", "")
        .replace("_", "")
        .replace(".", "")
    )
    
    # Direct match in alias map
    if clean in SYMBOL_MAP:
        return SYMBOL_MAP[clean]

    # Check Bengali phonetic names
    bn_map = {
        "গোল্ড": ("GC=F", "Gold (XAU/USD)"),
        "সোনা": ("GC=F", "Gold (XAU/USD)"),
        "সিলভার": ("SI=F", "Silver (XAG/USD)"),
        "রূপা": ("SI=F", "Silver (XAG/USD)"),
        "তেল": ("CL=F", "Crude Oil (WTI)"),
        "বিটকয়েন": ("BTC-USD", "Bitcoin (BTC/USD)"),
        "ইথেরিয়াম": ("ETH-USD", "Ethereum (ETH/USD)"),
        "ইউরো": ("EURUSD=X", "EUR/USD"),
        "পাউন্ড": ("GBPUSD=X", "GBP/USD"),
        "ইয়েন": ("JPY=X", "USD/JPY"),
        "ডলার": ("DX-Y.NYB", "US Dollar Index (DXY)"),
    }
    for bn_key, val in bn_map.items():
        if bn_key in raw.lower():
            return val

    # Try partial matching
    for key, val in SYMBOL_MAP.items():
        if len(key) >= 3 and (key in clean or clean in key):
            return val

    # Default fallback: treat as raw ticker
    return (raw.upper(), raw.upper())

def parse_ta_args(args: List[str]) -> Tuple[str, str, bool]:
    """
    Parses arbitrary command arguments like ['s&p500', 'M15'], ['s&p', '500', '15m'], or ['gold'].
    Intelligently detects if one of the tokens is a timeframe (M5, M15, 1h, 4h, 1d, etc.)
    and assembles the remaining tokens into the symbol name.
    Returns: (symbol_str, timeframe, is_default_timeframe)
    """
    if not args:
        return ("gold", "15m", True)

    full_query = " ".join(args).strip()

    # Check if last token is a timeframe
    last_token = args[-1].lower().replace(" ", "")
    tf_from_last = extract_timeframe_from_text(last_token)
    if tf_from_last and len(args) > 1:
        symbol_tokens = args[:-1]
        symbol_str = " ".join(symbol_tokens).strip() if symbol_tokens else "gold"
        return (symbol_str, tf_from_last, False)

    # Check if first token is a timeframe (e.g. /signal 15m gold)
    first_token = args[0].lower().replace(" ", "")
    tf_from_first = extract_timeframe_from_text(first_token)
    if tf_from_first and len(args) > 1:
        symbol_tokens = args[1:]
        symbol_str = " ".join(symbol_tokens).strip() if symbol_tokens else "gold"
        return (symbol_str, tf_from_first, False)

    # Check if user passed only a timeframe: e.g. /signal 1h
    if len(args) == 1:
        tf_only = extract_timeframe_from_text(args[0])
        if tf_only:
            return ("gold", tf_only, False)

    # Check anywhere in query
    extracted_tf = extract_timeframe_from_text(full_query)
    if extracted_tf:
        return (full_query, extracted_tf, False)

    # Default: entire arguments are symbol, timeframe defaults to 15m
    symbol_str = " ".join(args).strip()
    return (symbol_str, "15m", True)

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

def calculate_micro_indicators(candles: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculates key micro indicators across candles for dynamic ATR buffers and trend."""
    if not candles:
        return {"rsi_14": 50.0, "ema_9": 0.0, "ema_21": 0.0, "ema_50": 0.0, "atr_14": 1.0}
    closes = [c["close"] for c in candles]
    return {
        "rsi_14": calculate_rsi(closes, period=14),
        "ema_9": calculate_ema(closes, period=9),
        "ema_21": calculate_ema(closes, period=21),
        "ema_50": calculate_ema(closes, period=50),
        "atr_14": calculate_atr(candles, period=14)
    }

def generate_candlestick_chart(
    candles: List[Dict[str, Any]],
    ticker: str,
    display_name: str,
    timeframe: str,
    trade_params: Optional[Dict[str, Any]] = None,
    output_path: Optional[Path] = None
) -> Optional[Path]:
    """
    Renders an institutional dark-mode Candlestick Chart (PNG) with:
    - Multi-period moving averages (EMA 9, 21, 50)
    - Support and Resistance levels
    - Actionable trade parameter overlays (Entry, Stop Loss, Take Profit 1 & 2)
    - RSI (14) momentum oscillator subplot with overbought/oversold bands
    - Local Bangladesh Time (BST) timestamps
    """
    if not HAS_MATPLOTLIB or not candles or len(candles) < 5:
        return None

    try:
        try:
            local_tz = zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)
        except Exception:
            local_tz = zoneinfo.ZoneInfo("Asia/Dhaka")

        charts_dir = REPORTS_DIR / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)

        # Cleanup old charts older than 24h
        now_ts = datetime.datetime.now().timestamp()
        for old_f in charts_dir.glob("*.png"):
            try:
                if now_ts - old_f.stat().st_mtime > 86400:
                    old_f.unlink(missing_ok=True)
            except Exception:
                pass

        if output_path is None:
            clean_ticker = ticker.replace("=", "_").replace("^", "_").replace("-", "_").replace(".", "_")
            ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = charts_dir / f"chart_{clean_ticker}_{timeframe}_{ts_str}.png"

        # Number of candles to plot (keep around 40-52 candles for high clarity)
        N = min(len(candles), 48)
        plot_candles = candles[-N:]

        # Calculate indicators across the full history for stability
        closes_full = [c["close"] for c in candles]
        ema9_full = [calculate_ema(closes_full[:i], 9) for i in range(1, len(candles) + 1)]
        ema21_full = [calculate_ema(closes_full[:i], 21) for i in range(1, len(candles) + 1)]
        ema50_full = [calculate_ema(closes_full[:i], 50) for i in range(1, len(candles) + 1)]
        rsi_full = [calculate_rsi(closes_full[:i], 14) for i in range(1, len(candles) + 1)]

        ema9 = ema9_full[-N:]
        ema21 = ema21_full[-N:]
        ema50 = ema50_full[-N:]
        rsi = rsi_full[-N:]

        # Create Figure & Subplots (Main Price Chart + RSI Subplot)
        fig, (ax_main, ax_rsi) = plt.subplots(
            2, 1, figsize=(13.5, 8.5),
            gridspec_kw={"height_ratios": [3.6, 1.0], "hspace": 0.12},
            facecolor="#0b0f19"
        )
        ax_main.set_facecolor("#111827")
        ax_rsi.set_facecolor("#111827")

        # Plot Candlesticks
        for i, c in enumerate(plot_candles):
            is_bull = c["close"] >= c["open"]
            col = "#10b981" if is_bull else "#ef4444"
            body_bot = min(c["open"], c["close"])
            body_h = max(abs(c["close"] - c["open"]), 0.0001)

            # High-Low Wick
            ax_main.vlines(i, c["low"], c["high"], color=col, linewidth=1.2, alpha=0.9)
            # Candle Real Body
            ax_main.bar(i, body_h, bottom=body_bot, width=0.68, color=col, edgecolor=col, alpha=0.95)

        # Plot Moving Averages
        ax_main.plot(range(N), ema9, color="#38bdf8", linewidth=1.5, label="EMA 9 (Fast)")
        ax_main.plot(range(N), ema21, color="#fbbf24", linewidth=1.5, label="EMA 21 (Pullback)")
        ax_main.plot(range(N), ema50, color="#c084fc", linewidth=1.5, label="EMA 50 (Trend)")

        # Support & Resistance Levels
        highs = [c["high"] for c in plot_candles]
        lows = [c["low"] for c in plot_candles]
        res_level = max(highs)
        sup_level = min(lows)
        ax_main.axhline(res_level, color="#f87171", linestyle="--", linewidth=1.0, alpha=0.4, label=f"Resistance: {res_level}")
        ax_main.axhline(sup_level, color="#34d399", linestyle="--", linewidth=1.0, alpha=0.4, label=f"Support: {sup_level}")

        # Trade Parameters Overlay (Entry, SL, TP1, TP2)
        if trade_params and trade_params.get("entry"):
            entry = trade_params["entry"]
            sl = trade_params.get("sl")
            tp1 = trade_params.get("tp1")
            tp2 = trade_params.get("tp2")

            # Entry Line
            ax_main.axhline(entry, color="#3b82f6", linestyle="-", linewidth=2.0, alpha=0.9)
            ax_main.text(
                N - 0.5, entry, f"  ENTRY: {entry}",
                color="#ffffff", va="center", ha="left", fontsize=9, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", facecolor="#1e3a8a", edgecolor="#3b82f6", alpha=0.95)
            )

            # Stop Loss Line
            if sl:
                ax_main.axhline(sl, color="#f43f5e", linestyle="--", linewidth=2.0, alpha=0.9)
                ax_main.text(
                    N - 0.5, sl, f"  SL: {sl}",
                    color="#ffffff", va="center", ha="left", fontsize=9, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#881337", edgecolor="#f43f5e", alpha=0.95)
                )
                ax_main.axhspan(min(entry, sl), max(entry, sl), color="#ef4444", alpha=0.10)

            # Take Profit 1 Line
            if tp1:
                ax_main.axhline(tp1, color="#10b981", linestyle="--", linewidth=2.0, alpha=0.9)
                ax_main.text(
                    N - 0.5, tp1, f"  TP1: {tp1}",
                    color="#ffffff", va="center", ha="left", fontsize=9, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#064e3b", edgecolor="#10b981", alpha=0.95)
                )
                ax_main.axhspan(min(entry, tp1), max(entry, tp1), color="#10b981", alpha=0.10)

            # Take Profit 2 Line
            if tp2:
                ax_main.axhline(tp2, color="#059669", linestyle=":", linewidth=2.0, alpha=0.9)
                ax_main.text(
                    N - 0.5, tp2, f"  TP2: {tp2}",
                    color="#ffffff", va="center", ha="left", fontsize=9, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#064e3b", edgecolor="#059669", alpha=0.95)
                )

        # Main Plot Formatting
        curr_price = plot_candles[-1]["close"]
        first_open = plot_candles[0]["open"]
        price_diff = curr_price - first_open
        pct_diff = (price_diff / first_open) * 100 if first_open else 0.0
        change_sign = "+" if price_diff >= 0 else ""

        now_local = datetime.datetime.now(local_tz).strftime("%d %b %Y, %I:%M %p BST")
        ax_main.set_title(
            f"{display_name}  •  {timeframe}  |  Price: {curr_price} ({change_sign}{pct_diff:.2f}%)  •  {now_local}",
            color="#f3f4f6", fontsize=13, fontweight="bold", pad=12, loc="left"
        )

        ax_main.grid(True, color="#1f2937", linestyle="--", alpha=0.7)
        ax_main.tick_params(axis="y", colors="#9ca3af", labelsize=9)
        ax_main.tick_params(axis="x", labelbottom=False, bottom=False)
        ax_main.set_xlim(-0.8, N + 5)
        ax_main.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", labelcolor="#e5e7eb", fontsize=8.5)

        # RSI Subplot
        ax_rsi.plot(range(N), rsi, color="#818cf8", linewidth=1.7, label=f"RSI (14): {rsi[-1]:.1f}")
        ax_rsi.axhline(70, color="#ef4444", linestyle="--", linewidth=0.9, alpha=0.7)
        ax_rsi.axhline(50, color="#64748b", linestyle=":", linewidth=0.8, alpha=0.5)
        ax_rsi.axhline(30, color="#10b981", linestyle="--", linewidth=0.9, alpha=0.7)
        ax_rsi.fill_between(range(N), 30, 70, color="#1e293b", alpha=0.35)
        ax_rsi.set_ylim(10, 90)
        ax_rsi.grid(True, color="#1f2937", linestyle="--", alpha=0.7)
        ax_rsi.tick_params(axis="y", colors="#9ca3af", labelsize=8)
        ax_rsi.set_yticks([30, 50, 70])
        ax_rsi.legend(loc="upper left", facecolor="#1f2937", edgecolor="#374151", labelcolor="#e5e7eb", fontsize=8)

        # X-Axis Timestamps (Format in Bangladesh Time)
        step = max(1, N // 7)
        tick_indices = list(range(0, N, step))
        if (N - 1) not in tick_indices:
            tick_indices.append(N - 1)

        tick_labels = []
        for idx in tick_indices:
            c_time = plot_candles[idx]["time"]
            if hasattr(c_time, "astimezone"):
                c_local = c_time.astimezone(local_tz)
            else:
                c_local = c_time
            tick_labels.append(c_local.strftime("%H:%M\n%d %b"))

        ax_rsi.set_xlim(-0.8, N + 5)
        ax_rsi.set_xticks(tick_indices)
        ax_rsi.set_xticklabels(tick_labels, color="#9ca3af", fontsize=8.5)

        # Save and close
        plt.savefig(output_path, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        return output_path
    except Exception as e:
        logger.error(f"Error generating candlestick chart: {e}")
        return None


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

def generate_candle_dissection_report_with_chart(symbol_query: str, timeframe: str = "15m", is_default_tf: bool = False) -> Tuple[str, Optional[Path]]:
    """
    Main entry point: fetches live OHLCV, calculates microscopic candle anatomy,
    reconstructs temporal formation, detects liquidity traps, generates an institutional-grade
    candlestick chart image, and provides high-probability trading signals in bilingual Bengali-English.
    Returns: (report_text, chart_path)
    """
    timeframe = normalize_timeframe(timeframe)
    ticker, display_name = resolve_symbol(symbol_query)
    
    # 1. Fetch target timeframe candles with dynamic range
    if timeframe in ["1m", "5m"]:
        primary_range = "1d"
        fallback_range = "5d"
    elif timeframe in ["15m", "30m", "1h"]:
        primary_range = "5d"
        fallback_range = "1mo"
    else:  # 4h, 1d
        primary_range = "1mo"
        fallback_range = "3mo"

    candles = fetch_candles(ticker, interval=timeframe, range_str=primary_range)
    if not candles or len(candles) < 5:
        candles = fetch_candles(ticker, interval=timeframe, range_str=fallback_range)

    if not candles or len(candles) < 5:
        return (
            f"❌ দুঃখিত, *{display_name}* ({ticker})-এর লাইভ ক্যান্ডেল ডেটা এই মুহূর্তে পাওয়া যাচ্ছে না। অনুগ্রহ করে একটু পর আবার চেষ্টা করুন বা অন্য সিম্বল দিন।",
            None
        )

    # 2. Fetch sub-candles for intra-candle reconstruction
    sub_candles = None
    if timeframe == "15m":
        sub_candles = fetch_candles(ticker, interval="5m", range_str="1d")
    elif timeframe in ["30m", "1h"]:
        sub_candles = fetch_candles(ticker, interval="15m", range_str="5d")
    elif timeframe == "4h":
        sub_candles = fetch_candles(ticker, interval="1h", range_str="1mo")

    # 3. Microstructure analysis
    analysis = analyze_candle_sequence(candles, sub_candles_5m=sub_candles)
    if not analysis:
        return (f"❌ *{display_name}* এর ক্যান্ডেল ব্যবচ্ছেদ গণনায় ত্রুটি ঘটেছে।", None)

    curr = analysis["current"]
    prev = analysis["previous"]
    inter = analysis["interaction"]
    phases = analysis["intra_phases"]
    inds = analysis["indicators"]

    # 4. Calculate Precision Quantitative Trade Parameters (Entry, SL, TP1, TP2)
    entry_val = curr["close"]
    atr_val = inds.get("atr_14", 1.0)
    if atr_val == 0:
        atr_val = max(abs(curr["high"] - curr["low"]), 0.001)
    decimals = 2 if entry_val > 10 else 4

    if inter["sweep_prev_low"] or inter["true_break_high"]:
        action_decision = "🟢 BUY (লং এন্ট্রি কনফার্মড)"
        trade_dir = "BUY"
        is_bull_setup = True
        sl_val = round(curr["low"] - (atr_val * 0.3), decimals)
        risk = max(entry_val - sl_val, 0.0001)
        tp1_val = round(entry_val + (risk * 1.5), decimals)
        tp2_val = round(entry_val + (risk * 2.5), decimals)
    elif inter["sweep_prev_high"] or inter["true_break_low"]:
        action_decision = "🔴 SELL (শর্ট এন্ট্রি কনফার্মড)"
        trade_dir = "SELL"
        is_bull_setup = False
        sl_val = round(curr["high"] + (atr_val * 0.3), decimals)
        risk = max(sl_val - entry_val, 0.0001)
        tp1_val = round(entry_val - (risk * 1.5), decimals)
        tp2_val = round(entry_val - (risk * 2.5), decimals)
    else:
        action_decision = "⏳ WAIT (কনফার্মেশনের জন্য অপেক্ষা করুন)"
        trade_dir = "WAIT"
        is_bull_setup = curr["is_bullish"]
        sl_val = round(curr["low"] - (atr_val * 0.5), decimals) if is_bull_setup else round(curr["high"] + (atr_val * 0.5), decimals)
        tp1_val = round(entry_val + (atr_val * 1.5), decimals) if is_bull_setup else round(entry_val - (atr_val * 1.5), decimals)
        tp2_val = round(entry_val + (atr_val * 2.5), decimals) if is_bull_setup else round(entry_val - (atr_val * 2.5), decimals)

    trade_params = {
        "entry": entry_val,
        "sl": sl_val,
        "tp1": tp1_val,
        "tp2": tp2_val,
        "direction": trade_dir,
        "action": action_decision,
        "is_bullish": is_bull_setup
    }

    # 5. Generate Annotated Candlestick Chart Image (PNG)
    chart_path = generate_candlestick_chart(
        candles=candles,
        ticker=ticker,
        display_name=display_name,
        timeframe=timeframe,
        trade_params=trade_params
    )

    # 6. Format factual context for LLM
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

6. QUANTITATIVE SETUP:
- Action Decision: {action_decision}
- Entry Price: {entry_val}
- Stop Loss: {sl_val}
- Take Profit 1: {tp1_val} (1:1.5 RR)
- Take Profit 2: {tp2_val} (1:2.5 RR)
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
- ⚡ **Action / Decision (সুনির্দিষ্ট সিদ্ধান্ত):** {action_decision}
- 🎯 **Entry Price Zone (OTE):** `{entry_val}`
- 🛑 **Stop Loss (SL):** `{sl_val}` (বাধ্যতামূলক সুনির্দিষ্ট সংখ্যাসূচক ইনভ্যালিডেশন প্রাইস - সুইপ উইক ও বাফারসহ)
- 🏁 **Take Profit 1 (TP1):** `{tp1_val}` (বাধ্যতামূলক সুনির্দিষ্ট টেক প্রফিট - 1:1.5 RR)
- 🏆 **Take Profit 2 (TP2):** `{tp2_val}` (বাধ্যতামূলক সুনির্দিষ্ট টেক প্রফিট - 1:2.5+ RR)
- ⚖️ **Risk-to-Reward Ratio (RRR):** `1:2.5`
- 📊 **Institutional Confluence Score:** (যেমন 85% Confluence)

Write directly and clearly. Provide exact, specific numeric prices for Entry, SL, TP1, and TP2 so the trader can immediately set limit/stop orders without guesswork. Use bolding and bullet points for readability on Telegram. Do not include markdown code block quotes around the entire text.
"""

    llm = get_llm()
    try:
        report_text, provider_used, _ = llm.generate_response(prompt=prompt)
        footer = f"\n\n───────────────\n📊 *Asset:* {display_name} | *Timeframe:* {timeframe}\n🤖 *Engine:* {provider_used} (Institutional Microstructure)"
        if is_default_tf:
            footer += (
                f"\n\n⏱️ *অন্যান্য টাইমফ্রেম সুইচ:* `/chart {symbol_query} 5m` | `/chart {symbol_query} 1h` | `/chart {symbol_query} 4h` | `/chart {symbol_query} 1d`\n"
                f"💡 *টিপ:* ডিফল্ট হিসেবে ইন্ট্রাডে 15m চার্ট ও বিশ্লেষণ দেওয়া হয়েছে। অন্য টাইমফ্রেম চাইলে সরাসরি কমান্ড দিন।"
            )
        return (report_text + footer, chart_path)
    except Exception as e:
        logger.error(f"Error generating candle dissection with LLM: {e}")
        fallback_msg = f"""
🔬 *{display_name} ({timeframe}) ক্যান্ডেল ব্যবচ্ছেদ*

• বর্তমান প্রাইস: *{curr['close']}*
• ক্যান্ডেল রেঞ্জ: *{curr['range']}* (বডি: *{curr['body_pct']}%*, আপার উইক: *{curr['upper_wick_pct']}%*, লোয়ার উইক: *{curr['lower_wick_pct']}%*)
• ক্যান্ডেল প্যাটার্ন: *{curr['classification']}*
• আগের ক্যান্ডেল ব্রেক: *{inter['desc_bn']}*
• আরএসআই (RSI 14): *{inds['rsi_14']}*
• ভলিউম অনুপাত (RVOL): *{inds['rvol']}x*

🎯 *সিদ্ধান্ত (Action):* *{action_decision}*
🎯 *এন্ট্রি জোন (Entry):* `{entry_val}`
🛑 *স্টপ লস (SL):* `{sl_val}`
🏁 *টার্গেট ১ (TP1):* `{tp1_val}` (1:1.5 RR)
🏆 *টার্গেট ২ (TP2):* `{tp2_val}` (1:2.5 RR)
⚖️ *রিস্ক-টু-রিওয়ার্ড (RRR):* `1:2.5`
"""
        if is_default_tf:
            fallback_msg += (
                f"\n───────────────\n"
                f"⏱️ *অন্যান্য টাইমফ্রেম:* `/chart {symbol_query} 5m` | `/chart {symbol_query} 1h` | `/chart {symbol_query} 4h`\n"
                f"💡 *টিপ:* ডিফল্ট হিসেবে 15m বিশ্লেষণ দেওয়া হয়েছে। অন্য টাইমফ্রেম দেখতে সরাসরি কমান্ড দিন।"
            )
        return (fallback_msg, chart_path)

def generate_candle_dissection_report(symbol_query: str, timeframe: str = "15m", is_default_tf: bool = False) -> str:
    """Backwards-compatible wrapper returning report text string."""
    report_text, _ = generate_candle_dissection_report_with_chart(symbol_query, timeframe, is_default_tf)
    return report_text

# ----------------- Automated Intraday Scanner for High Conviction Setups ----------------- #

# Track already alerted setups to avoid spamming the user on the same candle
_ALERTED_CANDLES = set()

def scan_high_conviction_setups() -> List[Dict[str, Any]]:
    """
    Scans major global assets (Metals, Crypto, Indices, Oil, Forex) for high-probability liquidity sweep reversals
    (Turtle Soup setups: broke previous High/Low, formed >= 40% rejection wick, and closed inside range).
    Renders an annotated candlestick chart image for each confirmed alert.
    """
    watch_list = [
        ("gold", "GC=F", "Gold (XAU/USD)"),
        ("silver", "SI=F", "Silver (XAG/USD)"),
        ("btc", "BTC-USD", "Bitcoin (BTC/USD)"),
        ("eth", "ETH-USD", "Ethereum (ETH/USD)"),
        ("nasdaq", "NQ=F", "Nasdaq 100 (US100)"),
        ("sp500", "ES=F", "S&P 500 (US500)"),
        ("oil", "CL=F", "Crude Oil (WTI)"),
        ("eurusd", "EURUSD=X", "EUR/USD"),
        ("gbpusd", "GBPUSD=X", "GBP/USD"),
        ("usdjpy", "JPY=X", "USD/JPY")
    ]

    detected_alerts = []

    for alias, ticker, name in watch_list:
        try:
            candles = fetch_candles(ticker, interval="15m", range_str="1d")
            if not candles or len(candles) < 5:
                continue

            # Check the most recently closed candle (candles[-2]) to avoid repaint
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
                
                entry_val = closed_candle["close"]
                decimals = 2 if entry_val > 10 else 4

                # Micro indicators for dynamic ATR buffer
                inds = calculate_micro_indicators(candles[:-1])
                atr_val = inds.get("atr_14", abs(closed_candle["high"] - closed_candle["low"]))
                if atr_val == 0:
                    atr_val = abs(closed_candle["high"] - closed_candle["low"]) or 1.0

                if is_bullish_sweep:
                    sl_val = round(closed_candle["low"] - (atr_val * 0.25), decimals)
                    risk = max(entry_val - sl_val, 0.0001)
                    tp1_val = round(entry_val + (risk * 1.5), decimals)
                    tp2_val = round(entry_val + (risk * 2.5), decimals)
                else:
                    sl_val = round(closed_candle["high"] + (atr_val * 0.25), decimals)
                    risk = max(sl_val - entry_val, 0.0001)
                    tp1_val = round(entry_val - (risk * 1.5), decimals)
                    tp2_val = round(entry_val - (risk * 2.5), decimals)

                setup_desc = (
                    f"পূর্ববর্তী 15m ক্যান্ডেলের Low ({prev_candle['low']}) ভেঙে রিটেইল স্টপ হান্ট করে {anat['lower_wick_pct']}% লোয়ার উইক নিয়ে ক্লোজ হয়েছে।"
                    if is_bullish_sweep else
                    f"পূর্ববর্তী 15m ক্যান্ডেলের High ({prev_candle['high']}) সুইপ করে রিটেইল বায়ারদের ট্র্যাপ করে {anat['upper_wick_pct']}% আপার উইক নিয়ে ক্লোজ হয়েছে।"
                )

                # Render annotated chart for this setup
                trade_params = {
                    "entry": entry_val,
                    "sl": sl_val,
                    "tp1": tp1_val,
                    "tp2": tp2_val,
                    "direction": "BUY" if is_bullish_sweep else "SELL",
                    "is_bullish": is_bullish_sweep
                }
                chart_path = generate_candlestick_chart(
                    candles=candles,
                    ticker=ticker,
                    display_name=name,
                    timeframe="15m",
                    trade_params=trade_params
                )

                detected_alerts.append({
                    "ticker": ticker,
                    "name": name,
                    "timeframe": "15m",
                    "price": entry_val,
                    "entry": entry_val,
                    "sl": sl_val,
                    "tp1": tp1_val,
                    "tp2": tp2_val,
                    "rrr": "1:2.5",
                    "direction": direction,
                    "is_bullish": is_bullish_sweep,
                    "setup_desc": setup_desc,
                    "high": closed_candle["high"],
                    "low": closed_candle["low"],
                    "timestamp": closed_candle["time"],
                    "chart_path": chart_path
                })
        except Exception as e:
            logger.warning(f"Scanner error for {ticker}: {e}")

    return detected_alerts

