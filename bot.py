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
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import (
    TELEGRAM_BOT_TOKEN,
    ALLOWED_USER_IDS,
    BOT_NAME,
    DEFAULT_TIMEZONE,
)
import database
import tools
from llm_manager import MultiTierLLMManager

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"{BOT_NAME} 24/7 Assistant is running healthy!".encode("utf-8"))

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
        f"আমি আপনার দৈনন্দিন যেকোনো কাজ, প্রশ্ন, প্ল্যানিং, কোডিং ও ক্যালকুলেশনে সাহায্য করতে পারি।\n\n"
        f"⚡ **Multi-Tier Fallback:** ফ্রি লিমিট নিয়ে চিন্তা নেই! এক প্রোভাইডারের কোটা শেষ হলে স্বয়ংক্রিয়ভাবে ব্যাকআপে সুইচ করব।\n\n"
        f"📌 *গুরুত্বপূর্ণ কমান্ডসমূহ:*\n"
        f"• `/status` - এআই প্রোভাইডারদের স্ট্যাটাস দেখা\n"
        f"• `/search <প্রশ্ন>` - সরাসরি ইন্টারনেট থেকে লাইভ সার্চ\n"
        f"• `/remind <মিনিট> <বার্তা>` - রিমাইন্ডার সেট করা\n"
        f"• `/reminders` - অপেক্ষমান রিমাইন্ডারের তালিকা\n"
        f"• `/time` - বর্তমান লাইভ সময় ও তারিখ\n"
        f"• `/clear` - আগের চ্যাট মেমোরি রিসেট করা\n"
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
        f"• `/search <বিষয়>`: যেমন `/search আজকের সোনার দাম কত`\n"
        f"• `/remind <মিনিট> <কাজের নাম>`: যেমন `/remind 45 মিটিংয়ে যোগ দিতে হবে`\n"
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
        f"2. **Groq Cloud:** {status_emoji(status['groq']['configured'])}\n"
        f"   └ Model: `{status['groq']['primary_model']}`\n"
        f"3. **OpenRouter:** {status_emoji(status['openrouter']['configured'])}\n"
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

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

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

    # Register Text Message Handler
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # Register Background Reminder Poller (every 15 seconds)
    if app.job_queue:
        app.job_queue.run_repeating(check_scheduled_reminders, interval=15, first=5)
        print("⏰ Reminder scheduler activated (running every 15s).")

    # Start background cloud health-check server (for Render / Hugging Face Spaces)
    threading.Thread(target=start_health_server, daemon=True).start()

    print(f"✅ {BOT_NAME} is active and polling Telegram 24/7. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
