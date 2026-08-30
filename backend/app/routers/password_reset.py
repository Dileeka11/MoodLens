"""Password reset: request a link, then use it once to set a new password."""

from __future__ import annotations

import hashlib
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import settings
from app.database import get_db
from app.models import PasswordReset, User
from app.schemas import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    SimpleMessage,
)
from app.services import mailer

log = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

# Deliberately identical whether or not the address exists, so this endpoint
# cannot be used to discover which emails have accounts.
GENERIC_REPLY = "If that email has an account, a reset link is on its way."


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email = payload.email.lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    if user is None:
        log.info("Password reset requested for unknown address %s", email)
        return ForgotPasswordResponse(message=GENERIC_REPLY, email_sent=False)

    # Any earlier link for this account stops working once a new one is issued.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for old in db.execute(
        select(PasswordReset).where(
            PasswordReset.user_id == user.user_id, PasswordReset.used_at.is_(None)
        )
    ).scalars():
        old.used_at = now

    raw_token = secrets.token_urlsafe(32)
    entry = PasswordReset(
        user_id=user.user_id,
        token_hash=_hash_token(raw_token),
        expires_at=now + timedelta(minutes=settings.reset_token_minutes),
    )
    db.add(entry)
    db.commit()

    reset_url = f"{settings.app_base_url.rstrip('/')}/reset-password?token={quote(raw_token)}"

    try:
        sent = mailer.send_password_reset(
            to=user.email,
            username=user.username,
            reset_url=reset_url,
            minutes=settings.reset_token_minutes,
        )
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "The mail server rejected the login. For Gmail, SMTP_PASSWORD must be "
                "a 16-character App Password, not your account password."
            ),
        )
    except (smtplib.SMTPException, OSError) as exc:
        # The token is already saved; surface the real failure rather than
        # pretending an email went out.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach the mail server ({type(exc).__name__}). "
                   "Check SMTP_HOST / SMTP_PORT in backend/.env",
        )

    return ForgotPasswordResponse(message=GENERIC_REPLY, email_sent=sent)


@router.post("/reset-password", response_model=SimpleMessage)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    entry = db.execute(
        select(PasswordReset).where(PasswordReset.token_hash == _hash_token(payload.token))
    ).scalar_one_or_none()

    if entry is None or entry.used_at is not None or entry.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Request a new one.",
        )

    user = db.get(User, entry.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account no longer exists")

    user.password_hash = hash_password(payload.new_password)
    entry.used_at = now
    db.commit()

    log.info("Password reset completed for user %s", user.user_id)
    return SimpleMessage(message="Password updated. You can sign in with it now.")


@router.get("/reset-password/check", response_model=SimpleMessage)
def check_token(token: str, db: Session = Depends(get_db)):
    """Lets the reset page show an expired-link message before the user types."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    entry = db.execute(
        select(PasswordReset).where(PasswordReset.token_hash == _hash_token(token))
    ).scalar_one_or_none()

    if entry is None or entry.used_at is not None or entry.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Request a new one.",
        )
    return SimpleMessage(message="Link is valid.")
