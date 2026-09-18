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
    BREVO_API_KEY,
    GOOGLE_SCRIPT_URL,
    BOT_NAME
)

logger = logging.getLogger(__name__)

def is_email_configured() -> bool:
    """Check if Google Script URL, Brevo, Resend API, or SMTP credentials are provided."""
    return bool(GOOGLE_SCRIPT_URL or BREVO_API_KEY or RESEND_API_KEY or (SMTP_EMAIL and SMTP_PASSWORD))

def _send_via_google_script(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: Optional[Path] = None
) -> Tuple[bool, str]:
    """
    Sends email directly through your Gmail account using Google Apps Script Web App (HTTPS).
    - 100% Free (100 emails/day from your own Gmail)
    - Can send to ANY recipient (no domain verification required)
    - Works on Render Free Tier without any port blockades (HTTPS Port 443)
    """
    import base64
    import requests

    payload = {
        "recipient": to_email.strip(),
        "subject": subject.strip(),
        "body": body
    }

    if attachment_path and Path(attachment_path).is_file():
        file_obj = Path(attachment_path)
        with open(file_obj, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
        payload["attachment"] = {
            "name": file_obj.name,
            "type": "application/pdf" if file_obj.suffix.lower() == ".pdf" else "application/octet-stream",
            "base64": b64_data
        }

    try:
        response = requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=30, allow_redirects=False)
        # Google Apps Script always issues 302 Found redirect on POST
        if response.status_code == 302 and "Location" in response.headers:
            redirect_url = response.headers["Location"]
            response = requests.post(redirect_url, json=payload, timeout=30)

        if response.status_code in [200, 302]:
            try:
                res_json = response.json()
                if res_json.get("status") == "success":
                    return True, f"✅ সফলভাবে আপনার জিমেইল থেকে ইমেইল পাঠানো হয়েছে:\n📧 প্রাপক: `{to_email}`\n📌 বিষয়: *{subject}*"
                else:
                    return False, f"❌ Google Script ত্রুটি: {res_json.get('message', 'Unknown error')}"
            except Exception:
                # If Google Script returned HTML confirmation or empty redirect
                return True, f"✅ সফলভাবে আপনার জিমেইল থেকে ইমেইল পাঠানো হয়েছে:\n📧 প্রাপক: `{to_email}`\n📌 বিষয়: *{subject}*"
        else:
            return False, f"❌ Google Script HTTP {response.status_code}: {response.text[:200]}"
    except Exception as e:
        logger.error(f"Failed to send via Google Script: {e}")
        return False, f"❌ Google Script সংযোগ ব্যর্থ: {str(e)}"

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
        err_msg = str(e)
        logger.error(f"Resend API error: {err_msg}")
        if "testing emails" in err_msg.lower() or "verify a domain" in err_msg.lower():
            return (
                False,
                f"⚠️ **Resend Free Tier সীমাবদ্ধতা:**\n"
                f"Resend-এর ফ্রি প্ল্যানে নিজস্ব কাস্টম ডোমেন ছাড়া শুধুমাত্র আপনার নিজের রেজিস্টার্ড ইমেইল `{SMTP_EMAIL or 'najmul.djd@gmail.com'}` এ ইমেইল পাঠানো যায়।\n\n"
                f"👉 আপনি যদি নিজের ইমেইলে (`najmul.djd@gmail.com`) রিপোর্ট পাঠাতে চান, তবে তা সাথে সাথেই যাবে।"
            )
        return False, f"❌ Resend API ত্রুটি: {err_msg}"

def _send_via_brevo(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: Optional[Path] = None
) -> Tuple[bool, str]:
    """
    Sends email via Brevo (formerly Sendinblue) HTTPS API (Port 443).
    - 100% Free (300 emails/day to ANY recipient without domain verification)
    - Works on Render Free Tier without blocked ports
    """
    import base64
    import requests

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }

    sender_email = SMTP_EMAIL or "najmul.djd@gmail.com"
    html_content = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #1e293b; background-color: #f8fafc; padding: 20px; border-radius: 8px;">
        <div style="white-space: pre-wrap; font-size: 14px;">{body}</div>
        <hr style="border: none; border-top: 1px solid #cbd5e1; margin: 20px 0;">
        <p style="font-size: 11px; color: #64748b;">
            Sent automatically via <b>{BOT_NAME} 24/7 AI Assistant</b>
        </p>
    </div>
    """

    payload = {
        "sender": {"name": f"{BOT_NAME} AI Assistant", "email": sender_email},
        "to": [{"email": to_email.strip()}],
        "subject": subject.strip(),
        "htmlContent": html_content
    }

    if attachment_path and Path(attachment_path).is_file():
        file_obj = Path(attachment_path)
        with open(file_obj, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        payload["attachment"] = [{"name": file_obj.name, "content": encoded}]

    try:
        r = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers, timeout=25)
        if r.status_code in [200, 201, 202]:
            return True, f"✅ সফলভাবে ইমেইল পাঠানো হয়েছে:\n📧 প্রাপক: `{to_email}`\n📌 বিষয়: *{subject}*"
        else:
            return False, f"❌ Brevo API ত্রুটি ({r.status_code}): {r.text[:200]}"
    except Exception as e:
        return False, f"❌ Brevo সংযোগ ব্যর্থ: {str(e)}"

def send_email(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: Optional[Path] = None
) -> Tuple[bool, str]:
    """
    Dispatches email via:
    1. Google Script Web App (Sends from your Gmail)
    2. Brevo Cloud API (Sends to ANY recipient for free, 300/day)
    3. Resend HTTPS API (Sends to verified recipient/domain)
    4. Direct SMTP Fallback
    """
    if not is_email_configured():
        return (
            False,
            "⚠️ ইমেইল সার্ভিস এখনো কনফিগার করা হয়নি!\n\n"
            "ইমেইল পাঠাতে Render Environment-এ `GOOGLE_SCRIPT_URL`, `BREVO_API_KEY`, অথবা `RESEND_API_KEY` যোগ করুন।"
        )

    if not to_email or "@" not in to_email:
        return False, "❌ প্রাপকের ইমেইল এড্রেসটি সঠিক নয়।"

    # 1. Google Apps Script Web App (Sends directly from your Gmail to ANY recipient)
    if GOOGLE_SCRIPT_URL:
        success, res = _send_via_google_script(to_email, subject, body, attachment_path)
        if success:
            return True, res
        logger.warning(f"Google Script dispatch failed: {res}. Falling back to Brevo/Resend...")

    # 2. Brevo HTTPS API (Sends to ANY recipient, 300 emails/day completely free)
    if BREVO_API_KEY:
        success, res = _send_via_brevo(to_email, subject, body, attachment_path)
        if success:
            return True, res
        logger.warning(f"Brevo dispatch failed: {res}. Falling back to Resend...")

    # 3. Resend HTTPS API (Sends to verified recipient/domain)
    if RESEND_API_KEY:
        success, res = _send_via_resend(to_email, subject, body, attachment_path)
        if success:
            return True, res
        if "Resend Free Tier" in res or "testing emails" in res or "domain" in res.lower():
            return False, res
        logger.warning(f"Resend dispatch failed: {res}. Falling back to SMTP...")

    # 3. Direct SMTP Fallback (for local machines or unblocked hosts)
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
