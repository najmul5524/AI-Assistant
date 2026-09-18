"""
Institutional Market Chart Generator
Generates high-resolution multi-asset technical range, pivot level, and directional bias charts
using Pillow (PIL), perfectly optimized for embedding inside PyMuPDF Story PDF documents.
"""

from pathlib import Path
import datetime
from typing import Optional, List, Dict, Any
from PIL import Image, ImageDraw, ImageFont
import zoneinfo
from config import REPORTS_DIR, DEFAULT_TIMEZONE

def _get_bd_now() -> datetime.datetime:
    try:
        tz = zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)
    except Exception:
        tz = zoneinfo.ZoneInfo("Asia/Dhaka")
    return datetime.datetime.now(tz)

def get_best_font(size: int, bold: bool = False):
    """Attempts to load a clean sans-serif TrueType font, falling back to default."""
    font_names = ["arialbd.ttf", "calibrib.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]
    for name in font_names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None

def create_market_range_chart(
    output_path: Optional[Path] = None,
    chart_title: str = "MULTI-ASSET TECHNICAL RANGE & DIRECTION MATRIX",
    assets_data: Optional[List[Dict[str, Any]]] = None
) -> Path:
    """
    Creates a high-definition (1030x620 px) institutional multi-asset price range,
    pivot level, and directional bias chart.
    """
    if output_path is None:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORTS_DIR / f"market_chart_{timestamp}.png"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    width = 1030
    height = 620
    img = Image.new("RGB", (width, height), color="#f8fafc")
    draw = ImageDraw.Draw(img)

    # Outer border
    draw.rounded_rectangle([4, 4, width - 4, height - 4], radius=16, outline="#cbd5e1", width=2)

    # Header background
    draw.rounded_rectangle([10, 10, width - 10, 65], radius=10, fill="#0f172a")

    font_title = get_best_font(23, bold=True)
    font_asset = get_best_font(18, bold=True)
    font_badge = get_best_font(14, bold=True)
    font_levels = get_best_font(16, bold=False)
    font_meta = get_best_font(15, bold=False)

    # Header title & BD Time
    draw.text((25, 24), chart_title, fill="#ffffff", font=font_title)
    now_dt = _get_bd_now()
    now_str = now_dt.strftime("%d %b %Y | %I:%M %p (BST)")
    draw.text((width - 330, 26), now_str, fill="#94a3b8", font=font_meta)

    default_assets = [
        {"name": "Gold (XAU/USD)", "bias": "BULLISH", "color": "#10b981", "s": "$2,685", "pivot": "$2,715", "r": "$2,745", "pct": 0.75},
        {"name": "Silver (XAG/USD)", "bias": "RANGE", "color": "#f59e0b", "s": "$31.40", "pivot": "$31.85", "r": "$32.60", "pct": 0.50},
        {"name": "Nasdaq 100 (NAS100)", "bias": "BULLISH", "color": "#10b981", "s": "19,850", "pivot": "20,100", "r": "20,350", "pct": 0.72},
        {"name": "S&P 500 Futures", "bias": "BULLISH", "color": "#10b981", "s": "5,690", "pivot": "5,740", "r": "5,785", "pct": 0.70},
        {"name": "Crude Oil (WTI)", "bias": "BEARISH", "color": "#ef4444", "s": "$68.20", "pivot": "$70.10", "r": "$72.10", "pct": 0.35},
        {"name": "EUR/USD", "bias": "BEARISH", "color": "#ef4444", "s": "1.1070", "pivot": "1.1140", "r": "1.1210", "pct": 0.38},
        {"name": "GBP/USD", "bias": "BULLISH", "color": "#10b981", "s": "1.3210", "pivot": "1.3290", "r": "1.3365", "pct": 0.68},
        {"name": "USD/JPY", "bias": "RANGE", "color": "#f59e0b", "s": "141.50", "pivot": "142.80", "r": "143.90", "pct": 0.52},
    ]

    assets = assets_data if assets_data else default_assets

    y = 80
    for a in assets:
        # Asset Name
        draw.text((25, y + 6), a["name"], fill="#0f172a", font=font_asset)

        # Direction Badge
        draw.rounded_rectangle([250, y + 4, 370, y + 32], radius=6, fill=a["color"])
        draw.text((268, y + 8), a["bias"], fill="#ffffff", font=font_badge)

        # Range Bar (Background)
        bar_x1 = 395
        bar_x2 = 720
        draw.rounded_rectangle([bar_x1, y + 9, bar_x2, y + 27], radius=8, fill="#e2e8f0")

        # Range Bar (Fill)
        pct = max(0.1, min(0.95, a.get("pct", 0.5)))
        fill_width = int((bar_x2 - bar_x1) * pct)
        draw.rounded_rectangle([bar_x1, y + 9, bar_x1 + fill_width, y + 27], radius=8, fill=a["color"])

        # Pivot point marker
        pivot_x = bar_x1 + fill_width
        draw.line([pivot_x, y + 4, pivot_x, y + 32], fill="#0f172a", width=3)

        # Support & Resistance values
        draw.text((740, y + 8), f"S: {a['s']}", fill="#64748b", font=font_levels)
        draw.text((865, y + 8), f"R: {a['r']}", fill="#0f172a", font=font_levels)

        # Separator line
        draw.line([20, y + 45, width - 20, y + 45], fill="#f1f5f9", width=1)
        y += 55

    # Currency Strength Footer
    draw.rounded_rectangle([15, height - 52, width - 15, height - 12], radius=8, fill="#f1f5f9")
    draw.text((25, height - 39), "Currency Strength Index:", fill="#334155", font=font_meta)
    strengths = [
        ("USD", "Bullish", "#10b981"),
        ("GBP", "Strong", "#10b981"),
        ("EUR", "Weak", "#ef4444"),
        ("JPY", "Neutral", "#d97706"),
        ("CAD", "Soft", "#ef4444")
    ]
    cx = 240
    for curr, status, col in strengths:
        draw.ellipse([cx, height - 37, cx + 9, height - 28], fill=col)
        draw.text((cx + 14, height - 42), f"{curr}: {status}", fill=col, font=font_meta)
        cx += 150

    img.save(output_path, "PNG", optimize=True)
    return output_path
