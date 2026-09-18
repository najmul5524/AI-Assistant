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
import report_generator
import email_service
from llm_manager import MultiTierLLMManager

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"{BOT_NAME} 24/7 Assistant is running healthy! (v1.4-fixed-script)".encode("utf-8"))

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
        f"Include:\n"
        f"1. Executive Summary\n"
        f"2. Key Insights & Current Landscape\n"
        f"3. In-Depth Analysis & Data Points\n"
        f"4. Actionable Recommendations & Strategic Outlook\n\n"
        f"IMPORTANT: Write the formal PDF document text in clean, professional, publication-grade English so that all formatting, headers, tables, and typography render with 100% perfection without font encoding glitches.\n"
        f"Use markdown headings (##, ###) and clean bullet points (- )."
    )

    ai_report_text, provider_used, notice = llm_manager.generate_response(prompt=prompt)

    try:
        pdf_title = "Executive Analysis Report"
        en_words = [w for w in topic.split() if not any('\u0980' <= c <= '\u09ff' for c in w) and len(w) > 1]
        if en_words:
            pdf_title = f"Report: {' '.join(en_words).upper()}"
        else:
            pdf_title = f"Report: {topic[:30]}"

        pdf_path = report_generator.generate_pdf_report(
            title=pdf_title,
            text_content=ai_report_text,
            filename_prefix=topic
        )
        caption = f"📄 {topic}\n\n✅ আপনার অনুরোধকৃত PDF রিপোর্ট তৈরি সম্পন্ন!\n🤖 জেনারেটর: {provider_used}"
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
            f"Provide a thorough, high-quality, professional report with:\n"
            f"1. Executive Summary\n"
            f"2. Current Market / Topic Overview & Key Highlights\n"
            f"3. In-Depth Analysis & Data Points\n"
            f"4. Actionable Recommendations & Future Strategic Outlook\n\n"
            f"IMPORTANT: Write the formal PDF document text in clean, professional, publication-grade English so that all formatting, headers, tables, and typography render with 100% crisp perfection without font encoding glitches.\n"
            f"Format using clear markdown headers (##, ###) and clean bullet points (- )."
        )
        ai_report_text, provider_used, notice = llm_manager.generate_response(prompt=prompt, context_data=search_data)

        # Clean topic title for PDF header (English friendly for PDF layout)
        report_title = text[:60].replace("\n", " ")
        pdf_title = "Executive Analysis Report"
        en_words = [w for w in text.split() if not any('\u0980' <= c <= '\u09ff' for c in w) and len(w) > 1]
        if en_words:
            pdf_title = f"Report: {' '.join(en_words).upper()}"
        else:
            pdf_title = "Executive Analysis Report"

        try:
            pdf_path = report_generator.generate_pdf_report(
                title=pdf_title,
                text_content=ai_report_text,
                filename_prefix="Executive_Report"
            )
            caption = f"📄 {report_title}\n\n✅ আপনার PDF রিপোর্ট তৈরি সম্পন্ন!\n🤖 এআই ইঞ্জিন: {provider_used}"
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
                email_subject = f"Executive Report: {report_title}"
                email_body = (
                    f"Hello,\n\n"
                    f"Please find attached your requested report regarding: '{report_title}'.\n\n"
                    f"Summary Highlights:\n"
                    f"{ai_report_text[:400]}...\n\n"
                    f"Best regards,\n"
                    f"{BOT_NAME} Personal AI Assistant"
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
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("email", email_command))

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
