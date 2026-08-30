"""SMTP email sending.

If SMTP is not configured, emails are written to the log and to
backend/cache/sent_emails/ instead of being sent. That keeps the password
reset flow fully testable in development without credentials, and makes it
obvious in the log that nothing actually left the machine.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def _write_to_disk(to: str, subject: str, body: str) -> None:
    outbox = settings.cache_dir / "sent_emails"
    outbox.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() else "_" for c in to)[:40]
    path = outbox / f"{stamp}-{safe}.txt"
    path.write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
    log.warning("SMTP not configured — email written to %s instead of sending", path)


def send(to: str, subject: str, body: str, html: str | None = None) -> bool:
    """Returns True if the message was actually handed to an SMTP server."""
    if not is_configured():
        log.warning("---- EMAIL (not sent, SMTP unconfigured) ----\nTo: %s\n%s\n%s",
                    to, subject, body)
        _write_to_disk(to, subject, body)
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")

    try:
        if settings.smtp_use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                  context=context, timeout=20) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
                server.ehlo()
                if settings.smtp_use_tls:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(message)
    except smtplib.SMTPAuthenticationError:
        # The most common misconfiguration by far: a normal Gmail password
        # instead of an app password.
        log.exception("SMTP authentication failed — check SMTP_USER / SMTP_PASSWORD")
        raise
    except Exception:
        log.exception("Could not send email to %s", to)
        raise

    log.info("Sent %r to %s", subject, to)
    return True


def send_password_reset(to: str, username: str, reset_url: str, minutes: int) -> bool:
    subject = "Reset your MoodLens password"
    body = (
        f"Hi {username},\n\n"
        "Someone asked to reset the password for your MoodLens account.\n"
        f"Open this link within {minutes} minutes to choose a new one:\n\n"
        f"{reset_url}\n\n"
        "If that wasn't you, ignore this email — your password stays as it is.\n\n"
        "— MoodLens"
    )
    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:480px;
            margin:0 auto;padding:24px;color:#16142a">
  <h2 style="margin:0 0 4px">Mood<span style="color:#6c5ce7">Lens</span></h2>
  <p style="color:#6b6880;margin:0 0 24px">Password reset</p>
  <p>Hi {username},</p>
  <p>Someone asked to reset the password for your MoodLens account.
     This link works for {minutes} minutes:</p>
  <p style="margin:28px 0">
    <a href="{reset_url}"
       style="background:#6c5ce7;color:#fff;text-decoration:none;padding:13px 24px;
              border-radius:9px;font-weight:600;display:inline-block">
      Choose a new password
    </a>
  </p>
  <p style="color:#6b6880;font-size:14px">
    If that wasn't you, ignore this email — your password stays as it is.
  </p>
  <p style="color:#6b6880;font-size:12px;word-break:break-all">{reset_url}</p>
</div>"""
    return send(to, subject, body, html)
