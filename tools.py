import datetime
import zoneinfo
import logging
import warnings
from typing import Optional, List, Dict

# Suppress DDGS rename notice
warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")
from duckduckgo_search import DDGS
from config import DEFAULT_TIMEZONE

logger = logging.getLogger(__name__)

def get_current_time(timezone_str: str = DEFAULT_TIMEZONE) -> str:
    """Returns the current date and time formatted nicely."""
    try:
        tz = zoneinfo.ZoneInfo(timezone_str)
        now = datetime.datetime.now(tz)
    except Exception:
        now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y, %I:%M %p (%Z)")

def perform_web_search(query: str, max_results: int = 5) -> str:
    """
    Search DuckDuckGo for the query and format top results.
    100% free, no API key required.
    """
    if not query or not query.strip():
        return "Search query is empty."
        
    try:
        ddgs = DDGS()
        results = list(ddgs.text(query.strip(), max_results=max_results))
        if not results:
            return f"No web results found for query: '{query}'."
            
        formatted = [f"### Web Search Results for: '{query}'\n"]
        for i, res in enumerate(results, 1):
            title = res.get("title", "No Title")
            href = res.get("href", "")
            body = res.get("body", "")
            formatted.append(f"{i}. **{title}**\n   {body}\n   *Source:* {href}")
            
        return "\n\n".join(formatted)
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return f"Could not complete web search: {str(e)}"

def calculate_expression(expr: str) -> str:
    """Safe calculation for basic mathematical expressions."""
    allowed_chars = set("0123456789+-*/(). %^")
    clean_expr = expr.replace("^", "**")
    if not all(c in allowed_chars for c in clean_expr):
        return "Invalid characters in mathematical expression."
    try:
        # Evaluate safely in restricted namespace
        result = eval(clean_expr, {"__builtins__": None}, {})
        return f"Calculation: {expr} = {result}"
    except Exception as e:
        return f"Calculation error: {e}"
