import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Telegram Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Allowed users list (empty means open to all, but strongly advised to set)
_allowed_raw = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = [int(uid.strip()) for uid in _allowed_raw.split(",") if uid.strip().isdigit()]

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()

# Model preferences
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-2.5-flash",
    "gemini-1.5-flash"
]

GITHUB_MODELS = [
    "Meta-Llama-3.3-70B-Instruct",
    "gpt-4o-mini"
]

OPENROUTER_MODELS = [
    "deepseek/deepseek-r1:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-7b-instruct:free"
]

CLOUDFLARE_MODELS = [
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
    "@cf/meta/llama-3.1-8b-instruct"
]

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant"
]

BOT_NAME = os.getenv("BOT_NAME", "Nova AI")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Dhaka")

# System Prompt given to the assistant
SYSTEM_PROMPT = f"""You are {BOT_NAME}, an exceptionally capable, intelligent, and reliable 24/7 personal AI assistant.
Your goal is to assist the user with everyday tasks, planning, research, coding, writing, reminders, calculations, and problem solving.

Key guidelines:
1. Always respond in the same language the user speaks (natural, polite, fluent Bengali when addressed in Bengali; natural English when addressed in English).
2. Be concise, actionable, and structured with bullet points and bold text where helpful.
3. If search results or tool data are provided in the context, integrate them accurately and naturally.
4. You are autonomous and helpful. When asked to organize or plan, provide realistic and direct steps.
5. If you do not know something or need web verification, you can clearly indicate it.
"""
