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
    RESEND_API_KEY,
    BOT_NAME
)

logger = logging.getLogger(__name__)

def is_email_configured() -> bool:
    """Check if either Resend API or SMTP credentials are provided."""
    return bool(RESEND_API_KEY or (SMTP_EMAIL and SMTP_PASSWORD))

def _send_via_resend(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: Optional[Path] = None
) -> Tuple[bool, str]:
    """Sends email via Resend HTTPS API (Port 443 - never blocked by cloud hosts)."""
    import base64
    import resend

    resend.api_key = RESEND_API_KEY
    html_content = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #1e293b; background-color: #f8fafc; padding: 20px; border-radius: 8px;">
        <div style="white-space: pre-wrap; font-size: 14px;">{body}</div>
        <hr style="border: none; border-top: 1px solid #cbd5e1; margin: 20px 0;">
        <p style="font-size: 11px; color: #64748b;">
            Sent automatically via <b>{BOT_NAME} 24/7 AI Assistant</b>
        </p>
    </div>
    """

    params = {
        "from": f"{BOT_NAME} AI <onboarding@resend.dev>",
        "to": [to_email.strip()],
        "subject": subject.strip(),
        "html": html_content
    }

    if attachment_path and Path(attachment_path).is_file():
        file_obj = Path(attachment_path)
        with open(file_obj, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        params["attachments"] = [
            {
                "filename": file_obj.name,
                "content": encoded
            }
        ]

    try:
        email_resp = resend.Emails.send(params)
        logger.info(f"Resend email dispatched successfully: {email_resp}")
        return True, f"✅ সফলভাবে ইমেইল পাঠানো হয়েছে (via Resend API):\n📧 প্রাপক: `{to_email}`\n📌 বিষয়: *{subject}*"
    except Exception as e:
        logger.error(f"Resend API error: {e}")
        return False, f"❌ Resend API ত্রুটি: {str(e)}"

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

    # 1. Primary Cloud-Safe Dispatcher: Resend HTTPS API (never blocked by Render)
    if RESEND_API_KEY:
        return _send_via_resend(to_email, subject, body, attachment_path)

    # 2. Fallback to Direct SMTP (for local machines or hosts with open SMTP ports)
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

        # Connect to SMTP server (with fallback between STARTTLS 587 and SSL 465)
        logger.info(f"Connecting to SMTP server {SMTP_SERVER}:{SMTP_PORT}...")
        try:
            if SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(SMTP_SERVER, 465, timeout=15)
                server.ehlo()
            else:
                server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
                server.ehlo()
                server.starttls()
                server.ehlo()
        except (OSError, smtplib.SMTPConnectError) as conn_err:
            # If 587 failed, try fallback to SSL 465 (or vice versa)
            alt_port = 465 if SMTP_PORT != 465 else 587
            logger.warning(f"Connection on port {SMTP_PORT} failed ({conn_err}). Attempting fallback to port {alt_port}...")
            if alt_port == 465:
                server = smtplib.SMTP_SSL(SMTP_SERVER, 465, timeout=15)
                server.ehlo()
            else:
                server = smtplib.SMTP(SMTP_SERVER, 587, timeout=15)
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
    except OSError as net_err:
        logger.error(f"SMTP Network error: {net_err}")
        err_str = str(net_err)
        if "101" in err_str or "unreachable" in err_str.lower() or "timeout" in err_str.lower():
            return (
                False,
                "❌ ইমেইল পাঠাতে ব্যর্থ হয়েছে: **Render Cloud-এর Free Tier-এ স্প্যাম প্রতিরোধের জন্য আউটবাউন্ড SMTP পোর্ট (587/465) ব্লক করা থাকে।**\n\n"
                "💡 **বিকল্প সমাধান:**\n"
                "১. ক্লাউড থেকে সরাসরি ফ্রি ইমেইল পাঠাতে **Resend** বা **Brevo (Sendinblue)**-এর ফ্রি HTTPS API ব্যবহার করা যায় (যা রেন্ডারে ব্লক হয় না)।\n"
                "২. অথবা আপনার লোকাল পিসিতে বটটি রান করলে জিমেইল দিয়ে সাথে সাথে কোনো বাধা ছাড়াই ইমেইল চলে যাবে।"
            )
        return False, f"❌ ইমেইল পাঠাতে নেটওয়ার্ক সমস্যা হয়েছে: {err_str}"
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False, f"❌ ইমেইল পাঠাতে সমস্যা হয়েছে: {str(e)}"
