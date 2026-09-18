import sys
import asyncio
import logging
import re
import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from typing import Optional
from telegram import Update
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import os
import threading
import zoneinfo
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import (
    TELEGRAM_BOT_TOKEN,
    ALLOWED_USER_IDS,
    BOT_NAME,
    DEFAULT_TIMEZONE,
    BASE_DIR,
    GOOGLE_SCRIPT_URL,
    RESEND_API_KEY,
    BREVO_API_KEY,
    FOREX_MIN_IMPACT,
    FOREX_CURRENCIES,
    FOREX_REMINDER_MINUTES,
    FOREX_DAILY_SYNC_TIME,
    FOREX_NEWS_CHECK_INTERVAL,
)
import database
import tools
import report_generator
import email_service
import forex_service
import google_calendar_service
import forex_news_monitor
import forex_digest_service
from llm_manager import MultiTierLLMManager

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Cron-job.org (and Render's own health checks) hit this route
        # frequently just to keep the service awake. cron-job.org caps how
        # much response body it will read and fails the job as "output too
        # large" if that's exceeded — their own guidance is to return
        # nothing, or a short status like "OK", from any monitored URL.
        # So the default route below is intentionally minimal; the old
        # verbose JSON diagnostics (font checks, uharfbuzz, pdf shaping,
        # exception text) still exist, but only behind /diagnostics for
        # manual debugging, so they never leak into a routine cron ping.
        if self.path.rstrip("/") in ("", "/health", "/ping"):
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.rstrip("/") == "/diagnostics":
            import json, sys
            diag = {
                "bot": BOT_NAME,
                "version": "v1.7-pymupdf-active",
                "python_version": sys.version,
                "has_kalpurush": (BASE_DIR / "fonts" / "kalpurush.ttf").exists(),
                "google_script_configured": bool(GOOGLE_SCRIPT_URL),
                "brevo_configured": bool(BREVO_API_KEY),
                "resend_key_configured": bool(RESEND_API_KEY)
            }
            try:
                import uharfbuzz
                diag["uharfbuzz"] = getattr(uharfbuzz, "__version__", "installed")
            except Exception as e:
                diag["uharfbuzz_error"] = str(e)

            try:
                import fpdf
                from fpdf import FPDF
                pdf = FPDF()
                font_file = BASE_DIR / "fonts" / "kalpurush.ttf"
                if font_file.exists():
                    pdf.add_font("Kalpurush", "", str(font_file))
                    pdf.set_text_shaping(True)
                    diag["shaping_test"] = "SUCCESS"
                else:
                    diag["shaping_test"] = "FONT_NOT_FOUND"
            except Exception as e:
                diag["shaping_error"] = str(e)

            body = json.dumps(diag, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass # Suppress access logs to keep console clean

def start_health_server():
    """Lightweight background HTTP server for Render/Hugging Face cloud health checks."""
    try:
        port = int(os.getenv("PORT", "8080"))
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info(f"Cloud health server listening on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.warning(f"Could not start health server: {e}")

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize LLM Manager
llm_manager = MultiTierLLMManager()

def is_user_allowed(user_id: int) -> bool:
    """Check if the user is authorized to use the assistant."""
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS

async def unauthorized_reply(update: Update):
    """Notify unauthorized users to preserve free quotas."""
    user = update.effective_user
    msg = (
        f"⛔ *Access Restricted*\n\n"
        f"Hello {user.first_name}! This assistant is private to prevent unauthorized API quota consumption.\n\n"
        f"Your Telegram User ID is: `{user.id}`\n\n"
        f"If you are the owner, add this ID to `ALLOWED_USER_IDS` in your `.env` file and restart the bot."
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

# ----------------- Commands ----------------- #

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    welcome_text = (
        f"👋 *স্বাগতম! আমি {BOT_NAME}, আপনার ২৪/৭ পার্সোনাল এআই অ্যাসিস্ট্যান্ট।*\n\n"
        f"আমি আপনার দৈনন্দিন যেকোনো কাজ, ইমেইল, রিপোর্ট তৈরি, ওয়েব সার্চ ও প্ল্যানিংয়ে সাহায্য করতে পারি।\n\n"
        f"⚡ **Multi-Tier Fallback:** ফ্রি লিমিট নিয়ে চিন্তা নেই! এক প্রোভাইডারের কোটা শেষ হলে স্বয়ংক্রিয়ভাবে ব্যাকআপে সুইচ করব।\n\n"
        f"📌 *গুরুত্বপূর্ণ কমান্ডসমূহ:*\n"
        f"• `/forecast` - আগামীকালের গোল্ড, মেটাল, ফিউচার্স ও ফরেক্স প্রাইস মুভমেন্ট পূর্বাভাস\n"
        f"• `/digest` - দৈনিক একীভূত ম্যাক্রো ডাইজেস্ট ও সেন্টিমেন্ট\n"
        f"• `/forex_pdf` - সাপ্তাহিক প্রাতিষ্ঠানিক ফরেক্স ইন্টেলিজেন্স PDF রিপোর্ট\n"
        f"• `/news` - ব্রেকিং ফরেক্স নিউজ ও লাইভ এআই মার্কেট এনালাইসিস\n"
        f"• `/forex` - আজকের গুরুত্বপূর্ণ ফরেক্স ক্যালেন্ডার দেখা\n"
        f"• `/forex_sync` - Google Calendar-এ নিউজ রিমাইন্ডার সিঙ্ক করা\n"
        f"• `/report <বিষয়>` - সরাসরি প্রফেশনাল PDF রিপোর্ট তৈরি\n"
        f"• `/email <প্রাপক> <বিষয়> | <বার্তা>` - আসল ইমেইল পাঠানো\n"
        f"• `/search <প্রশ্ন>` - ইন্টারনেট থেকে লাইভ সার্চ\n"
        f"• `/remind <মিনিট> <বার্তা>` - রিমাইন্ডার সেট করা\n"
        f"• `/reminders` - অপেক্ষমান রিমাইন্ডার তালিকা\n"
        f"• `/status` - এআই প্রোভাইডারদের স্ট্যাটাস দেখা\n"
        f"• `/clear` - চ্যাট মেমোরি রিসেট করা\n"
        f"• `/help` - বিস্তারিত সাহায্য গাইড\n\n"
        f"আমাকে যেকোনো কিছু লিখে মেসেজ পাঠান, আমি কাজ শুরু করছি!"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    help_text = (
        f"📖 *{BOT_NAME} কমান্ড গাইড*\n\n"
        f"• **সাধারণ চ্যাট:** যেকোনো প্রশ্ন বা কাজ সরাসরি মেসেজ হিসেবে লিখুন।\n"
        f"• `/forecast` বা `/prediction` বা `/digest`: সারাদিনের সমস্ত নিউজ, গোল্ড (Gold), সিলভার (Silver), ফিউচার্স (S&P 500, Crude Oil) ও X.com সেন্টিমেন্ট বিশ্লেষণ করে আগামীকালের বিস্তারিত প্রাইস মুভমেন্ট পূর্বাভাস।\n"
        f"• `/forex_pdf`: সরাসরি পূর্ণাঙ্গ প্রাতিষ্ঠানিক সাপ্তাহিক ফরেক্স ইন্টেলিজেন্স PDF রিপোর্ট তৈরি ও ডাউনলোড।\n"
        f"• `/news`: সর্বশেষ ব্রেকিং ফরেক্স নিউজ ও এআই মার্কেট এনালাইসিস (ইমপ্যাক্ট, পেয়ার, সময়, দিক ও পরামর্শ)।\n"
        f"• `/forex`: আজকের High & Medium Impact ফরেক্স ক্যালেন্ডার নিউজ দেখা। (`/forex all` দিয়ে পুরো সপ্তাহেরটা দেখা যাবে)\n"
        f"• `/forex_sync`: আজকের ফরেক্স নিউজ Google Calendar-এ রিমাইন্ডার অ্যালার্টসহ স্বয়ংক্রিয়ভাবে সিঙ্ক করা।\n"
        f"• `/report <বিষয়>`: যেমন `/report এআই ও ভবিষ্যৎ চাকরি বাজার` (পিডিএফ তৈরি হবে)\n"
        f"• `/email <to> <subject> | <body>`: যেমন `/email friend@test.com আপডেট | সালাম, কাজ শেষ হয়েছে।`\n"
        f"• `/search <বিষয়>`: যেমন `/search আজকের সোনার দাম কত`\n"
        f"• `/remind <মিনিট> <কাজ>`: যেমন `/remind 45 মিটিংয়ে যোগ দিতে হবে`\n"
        f"• `/reminders`: আপনার বর্তমান সব পেন্ডিং রিমাইন্ডার দেখাবে।\n"
        f"• `/status`: সক্রিয় এআই মডেল এবং সিস্টেম স্বাস্থ্য পরীক্ষা করবে।\n"
        f"• `/clear`: কথোপকথন ইতিহাস মুছে ফ্রেশ শুরু করবে।"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    status = llm_manager.get_status()
    current_time = tools.get_current_time()
    pending = len(database.get_user_reminders(user.id))

    def status_emoji(is_ok: bool) -> str:
        return "🟢 Active" if is_ok else "⚪ Not Configured"

    status_msg = (
        f"📊 *সিস্টেম ও এআই স্ট্যাটাস রিপোর্ট*\n\n"
        f"🕒 **বর্তমান সময়:** {current_time}\n"
        f"⏰ **পেন্ডিং রিমাইন্ডার:** {pending} টি\n\n"
        f"🤖 **AI Providers (Failover Layers):**\n"
        f"1. **Google Gemini:** {status_emoji(status['gemini']['configured'])}\n"
        f"   └ Model: `{status['gemini']['primary_model']}`\n"
        f"2. **Cloudflare Workers AI:** {status_emoji(status['cloudflare']['configured'])}\n"
        f"   └ Model: `{status['cloudflare']['primary_model']}`\n"
        f"3. **GitHub Models:** {status_emoji(status['github']['configured'])}\n"
        f"   └ Model: `{status['github']['primary_model']}`\n"
        f"4. **Groq Cloud:** {status_emoji(status['groq']['configured'])}\n"
        f"   └ Model: `{status['groq']['primary_model']}`\n"
        f"5. **OpenRouter:** {status_emoji(status['openrouter']['configured'])}\n"
        f"   └ Model: `{status['openrouter']['primary_model']}`\n\n"
        f"🛡️ *স্বয়ংক্রিয় রিডাইরেকশন অন রয়েছে।*"
    )
    await update.message.reply_text(status_msg, parse_mode=ParseMode.MARKDOWN)

async def time_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /time command."""
    current_time = tools.get_current_time()
    await update.message.reply_text(f"🕒 বর্তমান সময়: *{current_time}*", parse_mode=ParseMode.MARKDOWN)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command to reset conversation memory."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    database.clear_history(user.id)
    await update.message.reply_text("🧹 আপনার পূর্ববর্তী চ্যাট মেমোরি পরিষ্কার করা হয়েছে। নতুন আলোচনা শুরু করতে পারেন!")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Explicit /search command."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("অনুগ্রহ করে সার্চ কোয়েরি দিন। উদাহরণ:\n`/search কৃত্রিম বুদ্ধিমত্তার ভবিষ্যৎ`", parse_mode=ParseMode.MARKDOWN)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    search_data = tools.perform_web_search(query)
    
    prompt = f"ইন্টারনেট সার্চ ফলাফল থেকে ব্যবহারকারীর প্রশ্নের সুস্পষ্ট ও তথ্যবহুল উত্তর দিন: {query}"
    answer, provider, notice = llm_manager.generate_response(prompt, context_data=search_data)

    final_msg = answer
    if notice:
        final_msg = f"{notice}\n\n{final_msg}"

    await update.message.reply_text(final_msg, parse_mode=ParseMode.MARKDOWN)

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remind <minutes> <task text>."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "সঠিক ফরম্যাট: `/remind <মিনিট> <কাজের বিবরণ>`\nউদাহরণ: `/remind 30 চা বিরতি`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        minutes = int(context.args[0])
        task_text = " ".join(context.args[1:])
    except ValueError:
        await update.message.reply_text("মিনিট সংখ্যায় হতে হবে। উদাহরণ: `/remind 15 ফাইল পাঠাতে হবে`", parse_mode=ParseMode.MARKDOWN)
        return

    remind_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    remind_at_iso = remind_at.isoformat()

    rem_id = database.add_reminder(user.id, task_text, remind_at_iso)
    await update.message.reply_text(
        f"✅ রিমাইন্ডার সেট করা হয়েছে! (ID: {rem_id})\n"
        f"⏰ সময়: {minutes} মিনিট পর\n"
        f"📝 কাজ: *{task_text}*",
        parse_mode=ParseMode.MARKDOWN
    )

async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reminders to list all pending reminders."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    rems = database.get_user_reminders(user.id)
    if not rems:
        await update.message.reply_text("বর্তমানে কোনো অপেক্ষমান রিমাইন্ডার নেই।")
        return

    lines = ["📋 *আপনার অপেক্ষমান রিমাইন্ডারসমূহ:*\n"]
    for r in rems:
        # Convert ISO UTC to local display
        try:
            dt = datetime.datetime.fromisoformat(r['remind_at'])
            time_str = dt.strftime("%I:%M %p (UTC)")
        except Exception:
            time_str = r['remind_at']
        lines.append(f"• ID {r['id']}: *{r['task_text']}* (Scheduled: {time_str})")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report <topic> to generate an executive PDF report."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text(
            "📌 *রিপোর্ট তৈরির ফরম্যাট:*\n`/report <বিষয়>`\n\nউদাহরণ:\n`/report বাংলাদেশে কৃত্রিম বুদ্ধিমত্তার সম্ভাবনা`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    status_msg = await update.message.reply_text(f"⏳ *'{topic}'* এর উপর সম্পূর্ণ প্রফেশনাল রিপোর্ট তৈরি হচ্ছে, অনুগ্রহ করে একটু অপেক্ষা করুন...", parse_mode=ParseMode.MARKDOWN)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)

    prompt = (
        f"Generate an executive, professional, and comprehensive report on: '{topic}'.\n"
        f"Write the report in high-quality Bengali (বাংলা ভাষায় পূর্ণাঙ্গ এবং প্রফেশনাল রিপোর্ট তৈরি করুন)।\n"
        f"Include:\n"
        f"1. Executive Summary (নির্বাহী সারসংক্ষেপ)\n"
        f"2. Key Insights & Current Landscape (মূল বিষয় ও বর্তমান অবস্থা)\n"
        f"3. In-Depth Analysis & Data Points (বিস্তারিত বিশ্লেষণ ও তথ্যাবলি)\n"
        f"4. Actionable Recommendations & Strategic Outlook (ভবিষ্যৎ সুপারিশ ও করণীয়)\n\n"
        f"Use clean markdown headings (##, ###) and clean bullet points (- )."
    )

    ai_report_text, provider_used, notice = llm_manager.generate_response(prompt=prompt)

    try:
        pdf_title = f"{topic[:60]} — এক্সিকিউটিভ রিপোর্ট"
        pdf_path = report_generator.generate_pdf_report(
            title=pdf_title,
            text_content=ai_report_text,
            filename_prefix=topic[:20]
        )
        caption = f"📄 {topic[:50]}\n\n✅ আপনার অনুরোধকৃত PDF রিপোর্ট তৈরি সম্পন্ন!\n🤖 জেনারেটর: {provider_used}"
        with open(pdf_path, "rb") as doc_file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=doc_file,
                filename=pdf_path.name,
                caption=caption
            )
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Failed to generate report PDF: {e}")
        await update.message.reply_text(f"❌ রিপোর্ট ফাইলে রূপান্তর করতে সমস্যা হয়েছে: {str(e)}")

async def email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /email <to> <subject> | <body>."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    full_text = " ".join(context.args) if context.args else ""
    if not full_text or "|" not in full_text:
        await update.message.reply_text(
            "📌 *ইমেইল কমান্ডের সঠিক ফরম্যাট:*\n"
            "`/email <প্রাপকের ইমেইল> <বিষয়> | <বার্তা>`\n\n"
            "উদাহরণ:\n"
            "`/email friend@example.com মিটিং আপডেট | সালাম, কাল সকাল ১০টায় আমাদের মিটিং হবে।`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    parts = full_text.split("|", 1)
    header_part = parts[0].strip()
    body_part = parts[1].strip()

    tokens = header_part.split(None, 1)
    to_email = tokens[0].strip()
    subject = tokens[1].strip() if len(tokens) > 1 else "Message from Assistant"

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    success, result_msg = email_service.send_email(to_email=to_email, subject=subject, body=body_part)
    await update.message.reply_text(result_msg, parse_mode=ParseMode.MARKDOWN)

async def forex_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /forex [all | currency] - View Forex Factory economic events."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    args = context.args if context.args else []
    target_date = None
    filter_curr = None

    for arg in args:
        arg_clean = arg.strip().upper()
        if arg_clean in ["ALL", "WEEK"]:
            target_date = "all"
        elif arg_clean in ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "NZD", "CNY"]:
            filter_curr = [arg_clean]

    currencies = filter_curr if filter_curr else FOREX_CURRENCIES
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    events = forex_service.get_forex_events(
        target_date=target_date,
        min_impact=FOREX_MIN_IMPACT,
        currencies=currencies,
        tz_name=DEFAULT_TIMEZONE
    )

    header = "সাপ্তাহিক ফরেক্স ক্যালেন্ডার" if target_date == "all" else "আজকের ফরেক্স ইকোনমিক নিউজ"
    msg = forex_service.format_forex_telegram_message(events, header_title=header)
    msg += "\n\n💡 _Google Calendar-এ অ্যালার্ট রিমাইন্ডার সেট করতে লিখুন:_ `/forex_sync`"

    try:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(msg)

async def forex_sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /forex_sync - Sync Forex news into Google Calendar with alerts."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    status_msg = await update.message.reply_text("⏳ Forex Factory থেকে নিউজ সংগ্রহ করে Google Calendar-এ সিঙ্ক করা হচ্ছে...", parse_mode=ParseMode.MARKDOWN)

    events = forex_service.get_forex_events(
        target_date=None,
        min_impact=FOREX_MIN_IMPACT,
        currencies=FOREX_CURRENCIES,
        tz_name=DEFAULT_TIMEZONE
    )

    if not events:
        await status_msg.edit_text("ℹ️ আজ কোনো গুরুত্বপূর্ণ (High/Medium Impact) ফরেক্স নিউজ নেই, তাই ক্যালেন্ডারে কোনো ইভেন্ট যোগ করার প্রয়োজন নেই।")
        return

    sync_res = google_calendar_service.sync_forex_events_to_calendar(
        events=events,
        reminder_minutes=FOREX_REMINDER_MINUTES,
        tz_name=DEFAULT_TIMEZONE
    )

    if sync_res["status"] == "not_configured":
        reply_text = (
            f"⚠️ *Google Calendar এখনও কনফিগার করা হয়নি!*\n\n"
            f"আজকের মোট `{len(events)}` টি নিউজ পাওয়া গেছে, কিন্তু Google Calendar-এ স্বয়ংক্রিয়ভাবে যুক্ত করার জন্য একবার অথেনটিকেশন প্রয়োজন।\n\n"
            f"👉 আপনার টার্মিনালে বা পিসিতে রান করুন:\n`python setup_google_calendar.py`\n\n"
            f"নিচে আজকের গুরুত্বপূর্ণ নিউজের তালিকা দেওয়া হলো:\n\n"
            + forex_service.format_forex_telegram_message(events)
        )
        await status_msg.edit_text(reply_text, parse_mode=ParseMode.MARKDOWN)
        return

    reply_text = (
        f"✅ *Google Calendar Sync সম্পন্ন!*\n\n"
        f"📅 {sync_res['message']}\n"
        f"🔔 রিমাইন্ডার: প্রতি নিউজের `{FOREX_REMINDER_MINUTES}` মিনিট আগে নোটিফিকেশন অ্যালার্ট সেট করা হয়েছে।\n\n"
        + forex_service.format_forex_telegram_message(events)
    )
    try:
        await status_msg.edit_text(reply_text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await status_msg.edit_text(reply_text)

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /news - Fetches latest Forex Factory breaking news & live AI impact analysis."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    status_msg = await update.message.reply_text("⏳ Forex Factory থেকে সর্বশেষ ব্রেকিং নিউজ সংগ্রহ ও এআই এনালাইসিস করা হচ্ছে...", parse_mode=ParseMode.MARKDOWN)

    articles = forex_news_monitor.fetch_latest_forex_news(limit=3)
    if not articles:
        await status_msg.edit_text("❌ এই মুহূর্তে কোনো নতুন ফরেক্স নিউজ পাওয়া যায়নি।")
        return

    latest = articles[0]
    # Run analysis
    analysis = forex_news_monitor.analyze_forex_news_with_ai(latest["title"], latest["description"])
    alert_msg = forex_news_monitor.format_news_telegram_alert(latest, analysis)

    try:
        await status_msg.edit_text(alert_msg, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await status_msg.edit_text(alert_msg)

async def send_split_message(bot, chat_id: int, text: str, parse_mode=ParseMode.MARKDOWN):
    """Safely dispatches long messages, splitting into clean sections if exceeding Telegram limit."""
    if len(text) <= 4000:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        except Exception:
            await bot.send_message(chat_id=chat_id, text=text)
        return

    # Split by double newlines to keep markdown sections intact
    parts = []
    current_chunk = ""
    for block in text.split("\n\n"):
        if len(current_chunk) + len(block) + 2 < 4000:
            current_chunk += ("\n\n" if current_chunk else "") + block
        else:
            if current_chunk:
                parts.append(current_chunk)
            current_chunk = block
    if current_chunk:
        parts.append(current_chunk)

    for p in parts:
        try:
            await bot.send_message(chat_id=chat_id, text=p, parse_mode=parse_mode)
        except Exception:
            await bot.send_message(chat_id=chat_id, text=p)

async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /digest, /forecast, /prediction - Generates next-day price movement prediction & market digest."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    status_msg = await update.message.reply_text("⏳ আজকের সমস্ত নিউজ, গোল্ড, ফরেক্স, ফিউচার্স ও X.com ট্রেডার সেন্টিমেন্ট বিশ্লেষণ করে আগামীকালের পূর্বাভাস তৈরি করা হচ্ছে...", parse_mode=ParseMode.MARKDOWN)

    try:
        loop = asyncio.get_running_loop()
        digest_text = await loop.run_in_executor(None, forex_digest_service.generate_daily_digest)
        try:
            await status_msg.delete()
        except Exception:
            pass
        await send_split_message(context.bot, update.effective_chat.id, digest_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Failed to generate digest/forecast: {e}")
        await update.message.reply_text(f"❌ ডাইজেস্ট ও পূর্বাভাস তৈরিতে সমস্যা হয়েছে: {str(e)}")

async def forex_pdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /forex_pdf - Generates and dispatches a comprehensive weekly Forex intelligence PDF report."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)
    status_msg = await update.message.reply_text("⏳ প্রাতিষ্ঠানিক সাপ্তাহিক ফরেক্স ইন্টেলিজেন্স PDF রিপোর্ট তৈরি হচ্ছে, অনুগ্রহ করে একটু অপেক্ষা করুন...", parse_mode=ParseMode.MARKDOWN)

    try:
        loop = asyncio.get_running_loop()
        pdf_path = await loop.run_in_executor(None, forex_digest_service.generate_weekly_intelligence_report)

        caption = "📊 *সাপ্তাহিক ফরেক্স ইন্টেলিজেন্স রিপোর্ট*\n\n✅ গত সপ্তাহের পর্যালোচনা ও আগামী সপ্তাহের প্রাতিষ্ঠানিক রোডম্যাপ প্রস্তুত সম্পন্ন!"
        with open(pdf_path, "rb") as doc_file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=doc_file,
                filename=pdf_path.name,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        try:
            await status_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ ফরেক্স রিপোর্ট তৈরিতে সমস্যা হয়েছে: {str(e)}")

async def forecast_pdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /forecast_pdf - Generates and dispatches an illustrated Next-Day Market Movement Forecast PDF with charts."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)
    status_msg = await update.message.reply_text("⏳ আগামীকালের মার্কেট পূর্বাভাস ও টেকনিক্যাল চার্টসহ প্রাতিষ্ঠানিক PDF তৈরি হচ্ছে...", parse_mode=ParseMode.MARKDOWN)

    try:
        loop = asyncio.get_running_loop()
        pdf_path = await loop.run_in_executor(None, forex_digest_service.generate_daily_forecast_pdf)

        caption = "📊 *আগামীকালের মার্কেট পূর্বাভাস ও টেকনিক্যাল চার্ট রিপোর্ট*\n\n✅ গোল্ড, সিলভার, ফিউচার্স ও ফরেক্স পেয়ারের প্রাইস রেঞ্জ চিত্রসহ প্রস্তুত!"
        with open(pdf_path, "rb") as doc_file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=doc_file,
                filename=pdf_path.name,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Failed to generate forecast PDF: {e}")
        await update.message.reply_text(f"❌ পূর্বাভাস PDF তৈরিতে সমস্যা হয়েছে: {str(e)}")

# ----------------- Message Handler ----------------- #

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process incoming text messages."""
    user = update.effective_user
    if not is_user_allowed(user.id):
        await unauthorized_reply(update)
        return

    text = update.message.text.strip()
    if not text:
        return

    # Extract any email addresses in the user's message
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    found_emails = re.findall(email_pattern, text)
    target_email = found_emails[0] if found_emails else None

    # Check for report generation triggers
    report_keywords = [
        "রিপোর্ট", "report", "পিডিএফ", "pdf", "ডকুমেন্ট", "document",
        "তৈরি কর", "বানাও", "generate", "create"
    ]
    # If the user mentions report/pdf keywords OR specifically asks to email a report
    is_report_request = any(k in text.lower() for k in ["রিপোর্ট", "report", "পিডিএফ", "pdf"]) and any(k in text.lower() for k in ["তৈরি", "বানাও", "দাও", "কর", "generate", "create", "make", "send", "মেইল", "ইমেইল"])

    # If it's a report request (with or without email)
    if is_report_request:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)
        status_msg = await update.message.reply_text("⏳ আপনার অনুরোধ অনুযায়ী তথ্য সংগ্রহ ও প্রফেশনাল PDF রিপোর্ট তৈরি করা হচ্ছে...", parse_mode=ParseMode.MARKDOWN)

        # 1. Enrich context with web search if topic relates to current events or financial indexes
        search_data = None
        if any(w in text.lower() for w in ["বর্তমান", "current", "latest", "status", "খবর", "দাম", "s&p", "stock", "market", "আজকের"]):
            try:
                search_data = tools.perform_web_search(text, max_results=3)
            except Exception as e:
                logger.warning(f"Web search for report failed: {e}")

        # 2. Generate comprehensive executive report content via LLM
        prompt = (
            f"You are generating a formal executive report requested by the user: '{text}'.\n"
            f"Write the complete report in high-quality, professional Bengali (বাংলা ভাষায় পূর্ণাঙ্গ এবং প্রফেশনাল এক্সিকিউটিভ রিপোর্ট লিখুন)।\n"
            f"Include:\n"
            f"1. Executive Summary (নির্বাহী সারসংক্ষেপ)\n"
            f"2. Current Market / Topic Overview & Key Highlights (বর্তমান অবস্থা ও মূল পর্যালোচনা)\n"
            f"3. In-Depth Analysis & Data Points (বিস্তারিত বিশ্লেষণ ও তথ্যাবলি)\n"
            f"4. Actionable Recommendations & Future Strategic Outlook (কৌশলগত সুপারিশ ও ভবিষ্যৎ সম্ভাবনা)\n\n"
            f"Format using clear markdown headers (##, ###) and clean bullet points (- )."
        )
        ai_report_text, provider_used, notice = llm_manager.generate_response(prompt=prompt, context_data=search_data)

        # Clean topic title for PDF header
        clean_title = re.sub(email_pattern, '', text).strip()
        pdf_title = f"{clean_title[:50]} — এক্সিকিউটিভ রিপোর্ট" if clean_title else "এক্সিকিউটিভ এনালাইসিস রিপোর্ট"

        try:
            pdf_path = report_generator.generate_pdf_report(
                title=pdf_title,
                text_content=ai_report_text,
                filename_prefix="Executive_Report"
            )
            caption = f"📄 {pdf_title[:45]}\n\n✅ আপনার PDF রিপোর্ট তৈরি সম্পন্ন!\n🤖 এআই ইঞ্জিন: {provider_used}"
            try:
                with open(pdf_path, "rb") as doc_file:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=doc_file,
                        filename=pdf_path.name,
                        caption=caption
                    )
            except Exception as send_err:
                logger.warning(f"Send document failed ({send_err}), retrying without caption...")
                with open(pdf_path, "rb") as doc_file:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=doc_file,
                        filename=pdf_path.name
                    )

            # If user also requested to email the report
            if target_email:
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
                email_subject = f"Executive Report: {pdf_title[:40]}"
                email_body = (
                    f"নমস্কার / সালাম,\n\n"
                    f"আপনার অনুরোধকৃত রিপোর্টটি সংযুক্ত করা হলো: '{pdf_title}'.\n\n"
                    f"মূল সারসংক্ষেপ:\n"
                    f"{ai_report_text[:300]}...\n\n"
                    f"ধন্যবাদ,\n"
                    f"{BOT_NAME} 24/7 AI Assistant"
                )
                email_ok, email_res = email_service.send_email(
                    to_email=target_email,
                    subject=email_subject,
                    body=email_body,
                    attachment_path=pdf_path
                )
                try:
                    await update.message.reply_text(email_res, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await update.message.reply_text(email_res)

            try:
                await status_msg.delete()
            except Exception:
                pass

            database.add_message(user.id, "user", text)
            record_msg = f"[PDF Report Dispatched: {pdf_path.name}]"
            if target_email:
                record_msg += f" [Emailed to {target_email}]"
            database.add_message(user.id, "assistant", record_msg, model_used=provider_used)
            return

        except Exception as e:
            logger.error(f"Report generation/dispatch failed: {e}")
            await update.message.reply_text(f"❌ রিপোর্ট তৈরিতে সমস্যা হয়েছে: {str(e)}")

    # Check for standalone email trigger (e.g. "email najmul@test.com subject | body" in chat)
    if target_email and any(w in text.lower() for w in ["মেইল কর", "মেইল পাঠিয়ে দাও", "ইমেইল কর", "send email", "email"]):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        # Ask LLM to draft suitable subject and clean body based on user prompt
        draft_prompt = (
            f"The user wants to send an email to '{target_email}'.\n"
            f"User command: '{text}'\n\n"
            f"Extract or compose a clear Subject and Email Body.\n"
            f"Output format:\n"
            f"SUBJECT: <concise subject>\n"
            f"BODY:\n<professional body text>"
        )
        draft_text, provider_used, _ = llm_manager.generate_response(prompt=draft_prompt)
        
        subject = "Message from Assistant"
        body = text
        if "SUBJECT:" in draft_text and "BODY:" in draft_text:
            try:
                subj_part = draft_text.split("BODY:")[0].replace("SUBJECT:", "").strip()
                body_part = draft_text.split("BODY:")[1].strip()
                if subj_part:
                    subject = subj_part
                if body_part:
                    body = body_part
            except Exception:
                pass

        email_ok, email_res = email_service.send_email(
            to_email=target_email,
            subject=subject,
            body=body
        )
        await update.message.reply_text(email_res, parse_mode=ParseMode.MARKDOWN)
        database.add_message(user.id, "user", text)
        database.add_message(user.id, "assistant", f"[Email sent to {target_email}: {subject}]", model_used=provider_used)
        return

    # Check for natural language breaking news & analysis triggers
    lower_text = text.lower()
    if any(k in lower_text for k in ["ব্রেকিং নিউজ", "breaking news", "news analysis", "নিউজ এনালাইসিস", "মার্কেট নিউজ", "ফরেক্স নিউজ এনালাইসিস", "লেটেস্ট নিউজ"]):
        await news_command(update, context)
        database.add_message(user.id, "user", text)
        database.add_message(user.id, "assistant", "[Forex Breaking News & Analysis displayed]")
        return

    # Check for natural language digest & next-day price movement prediction triggers
    if any(k in lower_text for k in [
        "ডাইজেস্ট", "digest", "সারসংক্ষেপ", "wrapup", "wrap up", "আজকের সারাংশ", "মার্কেট র্যাপ",
        "পূর্বাভাস", "forecast", "prediction", "প্রেডিকশন", "পরের দিন", "আগামীকাল", "পরবর্তী দিন"
    ]) and any(w in lower_text for w in ["ফরেক্স", "মার্কেট", "forex", "gold", "গোল্ড", "দাম", "প্রাইস", "মুভমেন্ট", "বাজার", "future", "ফিউচার", "মেটাল", "তেল", "oil"]):
        await digest_command(update, context)
        database.add_message(user.id, "user", text)
        database.add_message(user.id, "assistant", "[Daily Multi-Asset Prediction displayed]")
        return

    # Check for natural language forex PDF report triggers
    if any(k in lower_text for k in ["forex pdf", "forex report", "ফরেক্স পিডিএফ", "সাপ্তাহিক রিপোর্ট", "ফরেক্স রিপোর্ট"]):
        await forex_pdf_command(update, context)
        database.add_message(user.id, "user", text)
        database.add_message(user.id, "assistant", "[Forex Intelligence PDF Report sent]")
        return

    # Check for natural language Forex calendar triggers
    lower_text = text.lower()
    forex_keywords = ["forex", "ফরেক্স", "forexfactory", "forex factory", "economic calendar", "ইকোনমিক ক্যালেন্ডার"]
    if any(k in lower_text for k in forex_keywords):
        is_sync_request = any(w in lower_text for w in ["সিঙ্ক", "sync", "calendar", "ক্যালেন্ডার", "রিমাইন্ডার", "reminder", "যুক্ত কর", "সেট কর", "add"])
        if is_sync_request:
            await forex_sync_command(update, context)
            database.add_message(user.id, "user", text)
            database.add_message(user.id, "assistant", "[Forex Calendar Sync executed]")
            return
        else:
            await forex_command(update, context)
            database.add_message(user.id, "user", text)
            database.add_message(user.id, "assistant", "[Forex Events displayed]")
            return

    # Check for web search triggers
    context_data = None
    search_keywords = ["search", "আজকের", "খবর", "weather", "আবহাওয়া", "news", "price", "দাম", "latest", "বর্তমান"]
    if any(k in text.lower() for k in search_keywords) or text.lower().startswith("খুঁজো"):
        try:
            context_data = tools.perform_web_search(text, max_results=3)
        except Exception as e:
            logger.warning(f"Auto-search failed: {e}")

    # Fetch recent conversation memory
    history = database.get_recent_history(user.id, limit=8)

    # Generate response with failover
    answer, provider_used, switch_notice = llm_manager.generate_response(
        prompt=text,
        history=history,
        context_data=context_data
    )

    # Persist in database
    database.add_message(user.id, "user", text)
    database.add_message(user.id, "assistant", answer, model_used=provider_used)

    # Format reply
    final_reply = answer
    if switch_notice:
        final_reply = f"{switch_notice}\n\n{final_reply}"

    # Telegram Markdown protection fallback
    try:
        await update.message.reply_text(final_reply, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        # Fallback to plain text if markdown formatting has unmatched characters
        await update.message.reply_text(final_reply)

# ----------------- Background Reminder Checker ----------------- #

async def check_scheduled_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Periodic job running every 15 seconds to dispatch due reminders."""
    due = database.get_due_reminders()
    for rem in due:
        user_id = rem["user_id"]
        task = rem["task_text"]
        rem_id = rem["id"]
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⏰ *রিমাইন্ডার অ্যালার্ট!*\n\n📝 কাজ: *{task}*",
                parse_mode=ParseMode.MARKDOWN
            )
            database.mark_reminder_completed(rem_id)
        except Exception as e:
            logger.error(f"Failed to dispatch reminder {rem_id} to {user_id}: {e}")

async def daily_forex_sync_job(context: ContextTypes.DEFAULT_TYPE):
    """Daily automated job to sync today's forex news to Google Calendar and send alert to users."""
    logger.info("Executing scheduled daily Forex sync job...")
    try:
        events = forex_service.get_forex_events(
            target_date=None,
            min_impact=FOREX_MIN_IMPACT,
            currencies=FOREX_CURRENCIES,
            tz_name=DEFAULT_TIMEZONE
        )

        if not events:
            logger.info("Daily Forex Sync: No high/medium events found today.")
            return

        sync_note = ""
        if google_calendar_service.is_calendar_configured():
            res = google_calendar_service.sync_forex_events_to_calendar(
                events=events,
                reminder_minutes=FOREX_REMINDER_MINUTES,
                tz_name=DEFAULT_TIMEZONE
            )
            logger.info(f"Daily Forex Calendar Sync: {res['message']}")
            sync_note = f"\n\n🔔 *Google Calendar:* {res['message']}"

        briefing_msg = (
            f"☀️ *শুভ সকাল! আজকের গুরুত্বপূর্ণ ফরেক্স নিউজ ব্রিফিং*\n\n"
            + forex_service.format_forex_telegram_message(events)
            + sync_note
        )

        target_uids = ALLOWED_USER_IDS if ALLOWED_USER_IDS else []
        for uid in target_uids:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=briefing_msg,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as send_err:
                logger.warning(f"Could not send daily forex briefing to {uid}: {send_err}")
    except Exception as e:
        logger.error(f"Error in daily_forex_sync_job: {e}")

async def scheduled_news_monitor_job(context: ContextTypes.DEFAULT_TYPE):
    """Background worker running every 5 minutes to fetch breaking Forex news, analyze with AI, and alert user."""
    try:
        loop = asyncio.get_running_loop()
        processed = await loop.run_in_executor(None, forex_news_monitor.check_and_alert_new_stories, context)
        if processed > 0:
            logger.info(f"Forex News Monitor: Dispatched {processed} breaking news alerts.")
    except Exception as e:
        logger.error(f"Error in scheduled_news_monitor_job: {e}")

async def daily_evening_digest_job(context: ContextTypes.DEFAULT_TYPE):
    """Daily evening job at 22:00 (10:00 PM Asia/Dhaka) dispatching consolidated Next-Day Price Movement & Illustrated PDF."""
    enable_render_dispatch = os.getenv("ENABLE_RENDER_EVENING_DISPATCH", "false").lower() == "true"
    if not enable_render_dispatch:
        logger.info("Daily 10:00 PM Evening Forecast is handled via GitHub Actions (Zero Render Bandwidth). Set ENABLE_RENDER_EVENING_DISPATCH=true to run in bot.")
        return

    logger.info("Executing scheduled Daily Evening Forex & Multi-Asset Prediction Wrap-up...")
    try:
        loop = asyncio.get_running_loop()
        digest_text = await loop.run_in_executor(None, forex_digest_service.generate_daily_digest)
        pdf_path = await loop.run_in_executor(None, forex_digest_service.generate_daily_forecast_pdf)

        target_uids = ALLOWED_USER_IDS if ALLOWED_USER_IDS else []
        for uid in target_uids:
            try:
                await send_split_message(context.bot, uid, digest_text, parse_mode=ParseMode.MARKDOWN)
                caption = "📊 *আগামীকালের মার্কেট পূর্বাভাস ও টেকনিক্যাল চার্ট*\n\n✅ গোল্ড, সিলভার, ফিউচার্স ও ফরেক্স পেয়ারের প্রাইস রেঞ্জ চিত্রসহ প্রস্তুত!"
                with open(pdf_path, "rb") as doc_file:
                    await context.bot.send_document(
                        chat_id=uid,
                        document=doc_file,
                        filename=pdf_path.name,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN
                    )
            except Exception as e:
                logger.warning(f"Could not send evening digest/prediction to {uid}: {e}")
    except Exception as e:
        logger.error(f"Error in daily_evening_digest_job: {e}")

async def sunday_weekly_report_job(context: ContextTypes.DEFAULT_TYPE):
    """Weekly job on Sundays at 20:00 (8:00 PM Asia/Dhaka) generating institutional Weekly Intelligence PDF."""
    logger.info("Executing scheduled Sunday Weekly Forex Intelligence Report...")
    try:
        loop = asyncio.get_running_loop()
        pdf_path = await loop.run_in_executor(None, forex_digest_service.generate_weekly_intelligence_report)
        caption = "📊 *সাপ্তাহিক ফরেক্স ইন্টেলিজেন্স রিপোর্ট*\n\n✅ আগামী সপ্তাহের জন্য আপনার পূর্ণাঙ্গ প্রাতিষ্ঠানিক গাইডলাইন ও রোডম্যাপ প্রস্তুত!"
        target_uids = ALLOWED_USER_IDS if ALLOWED_USER_IDS else []
        for uid in target_uids:
            try:
                with open(pdf_path, "rb") as doc_file:
                    await context.bot.send_document(
                        chat_id=uid,
                        document=doc_file,
                        filename=pdf_path.name,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN
                    )
            except Exception as e:
                logger.warning(f"Could not send weekly PDF report to {uid}: {e}")
    except Exception as e:
        logger.error(f"Error in sunday_weekly_report_job: {e}")

# ----------------- Main Launcher ----------------- #

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("\n" + "=" * 60)
        print("❌ ERROR: TELEGRAM_BOT_TOKEN is missing in .env file!")
        print("Please create a bot via https://t.me/BotFather, add the token to .env, and re-run.")
        print("=" * 60 + "\n")
        return

    print("🚀 Initializing 24/7 AI Assistant...")
    database.init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("time", time_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("email", email_command))
    app.add_handler(CommandHandler("forex", forex_command))
    app.add_handler(CommandHandler("forex_sync", forex_sync_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("digest", digest_command))
    app.add_handler(CommandHandler("forecast", digest_command))
    app.add_handler(CommandHandler("prediction", digest_command))
    app.add_handler(CommandHandler("forecast_pdf", forecast_pdf_command))
    app.add_handler(CommandHandler("forex_pdf", forex_pdf_command))

    # Register Text Message Handler
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # Register Background Reminder Poller (every 15 seconds)
    if app.job_queue:
        app.job_queue.run_repeating(check_scheduled_reminders, interval=15, first=5)
        print("⏰ Reminder scheduler activated (running every 15s).")

        # Register 24/7 Forex Factory Breaking News Monitor (runs every FOREX_NEWS_CHECK_INTERVAL seconds)
        app.job_queue.run_repeating(scheduled_news_monitor_job, interval=FOREX_NEWS_CHECK_INTERVAL, first=15)
        print(f"📡 24/7 Forex News Monitor activated (checking every {FOREX_NEWS_CHECK_INTERVAL}s / {FOREX_NEWS_CHECK_INTERVAL // 60}m).")

        # Schedule daily morning Forex Sync (e.g. 06:30 AM)
        try:
            hour_str, min_str = FOREX_DAILY_SYNC_TIME.split(":")
            tz = zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)
            sync_time = datetime.time(hour=int(hour_str), minute=int(min_str), tzinfo=tz)
            app.job_queue.run_daily(daily_forex_sync_job, time=sync_time)
            print(f"📈 Daily morning Forex sync scheduled for {FOREX_DAILY_SYNC_TIME} ({DEFAULT_TIMEZONE}).")
        except Exception as e:
            logger.warning(f"Could not schedule daily forex sync: {e}")

        # Schedule Daily Evening Forex Wrap-up at 22:00 (10:00 PM Asia/Dhaka)
        try:
            tz = zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)
            evening_time = datetime.time(hour=22, minute=0, tzinfo=tz)
            app.job_queue.run_daily(daily_evening_digest_job, time=evening_time)
            print("🌙 Daily Evening Forex Wrap-up scheduled for 22:00 (Asia/Dhaka).")
        except Exception as e:
            logger.warning(f"Could not schedule daily evening digest: {e}")

        # Schedule Sunday Weekly Forex Intelligence PDF Report at 20:00 (8:00 PM Asia/Dhaka)
        # Note: In PTB run_daily, days=(6,) corresponds to Sunday (0=Mon, 1=Tue, ..., 6=Sun)
        try:
            tz = zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)
            sunday_time = datetime.time(hour=20, minute=0, tzinfo=tz)
            app.job_queue.run_daily(sunday_weekly_report_job, time=sunday_time, days=(6,))
            print("📅 Sunday Weekly Intelligence PDF report scheduled for Sunday 20:00 (Asia/Dhaka).")
        except Exception as e:
            logger.warning(f"Could not schedule sunday weekly report: {e}")

    # Start background cloud health-check server (for Render / Hugging Face Spaces)
    threading.Thread(target=start_health_server, daemon=True).start()

    print(f"✅ {BOT_NAME} is active and polling Telegram 24/7. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
