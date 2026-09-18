import smtplib
import logging
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, Tuple

from config import (
    SMTP_EMAIL,
    SMTP_PASSWORD,
    SMTP_SERVER,
    SMTP_PORT,
    BOT_NAME
)

logger = logging.getLogger(__name__)

def is_email_configured() -> bool:
    """Check if SMTP credentials are fully provided."""
    return bool(SMTP_EMAIL and SMTP_PASSWORD)

def send_email(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: Optional[Path] = None
) -> Tuple[bool, str]:
    """
    Sends an email via SMTP (Gmail App Password).
    Supports optional file attachments (PDF, Excel, etc.).
    Returns: (success_bool, message_str)
    """
    if not is_email_configured():
        return (
            False,
            "⚠️ ইমেইল সার্ভিস এখনো কনফিগার করা হয়নি!\n\n"
            "ইমেইল পাঠাতে আপনার `.env` ফাইলে `SMTP_EMAIL` (আপনার জিমেইল) এবং `SMTP_PASSWORD` "
            "(Google App Password - https://myaccount.google.com/apppasswords থেকে প্রাপ্ত ১৬ অক্ষরের পাসওয়ার্ড) যোগ করুন।"
        )

    if not to_email or "@" not in to_email:
        return False, "❌ প্রাপকের ইমেইল এড্রেসটি সঠিক নয়।"

    try:
        msg = MIMEMultipart()
        msg["From"] = f"{BOT_NAME} Assistant <{SMTP_EMAIL}>"
        msg["To"] = to_email.strip()
        msg["Subject"] = subject.strip()

        # HTML / Plain text body formatting
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #1e293b;">
                <div style="background-color: #f8fafc; padding: 20px; border-radius: 8px; border: 1px solid #e2e8f0;">
                    <div style="white-space: pre-wrap; font-size: 14px;">{body}</div>
                    <hr style="border: none; border-top: 1px solid #cbd5e1; margin: 20px 0;">
                    <p style="font-size: 11px; color: #64748b;">
                        Sent automatically via <b>{BOT_NAME} 24/7 AI Assistant</b>
                    </p>
                </div>
            </body>
        </html>
        """
        msg.attach(MIMEText(html_body, "html"))

        # Add attachment if provided
        if attachment_path and Path(attachment_path).is_file():
            file_obj = Path(attachment_path)
            with open(file_obj, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{file_obj.name}"'
            )
            msg.attach(part)

        # Connect to SMTP server
        logger.info(f"Connecting to SMTP server {SMTP_SERVER}:{SMTP_PORT}...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()

        logger.info(f"Email sent successfully to {to_email}")
        return True, f"✅ সফলভাবে ইমেইল পাঠানো হয়েছে:\n📧 প্রাপক: `{to_email}`\n📌 বিষয়: *{subject}*"

    except smtplib.SMTPAuthenticationError as auth_err:
        logger.error(f"SMTP Auth error: {auth_err}")
        return (
            False,
            "❌ ইমেইল অথেন্টিকেশন ব্যর্থ হয়েছে!\n"
            "অনুগ্রহ করে নিশ্চিত করুন যে আপনার জিমেইলে 2-Step Verification অন করা আছে এবং আপনি আপনার সাধারণ পাসওয়ার্ডের বদলে "
            "[Google App Password](https://myaccount.google.com/apppasswords) ব্যবহার করছেন।"
        )
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False, f"❌ ইমেইল পাঠাতে সমস্যা হয়েছে: {str(e)}"
