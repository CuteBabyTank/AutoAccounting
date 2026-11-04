"""Email + password accounts: sign up, verify the email, sign in, forgot / reset password.

Rules (OWASP authentication, password storage and forgot-password cheat sheets):
* Answers never reveal whether an email has an account: sign-up and "forgot password" always say "check your
  email", and a wrong email and a wrong password get the same message (and the same hashing work).
* An account can't sign in, or be added to a firm, until its email is verified (a link we send, or Google).
* Email links carry a random 256-bit token; only its SHA-256 is stored. Verify links last 24 hours, reset links
  30 minutes; each works once, and a new one cancels the old ones.
* Ten wrong passwords lock the account for 15 minutes (on top of the per-IP limit); a correct password resets it.
* A reset or password change ends every session issued before it (``password_changed_at``).
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.config import settings
from app.models.auth_token import AuthToken
from app.models.user import User, UserRole
from app.services import email_service, passwords

logger = logging.getLogger("auth.audit")

VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(minutes=30)
MAX_FAILS = 10
LOCK_FOR = timedelta(minutes=15)

WRONG = "That email and password don't match. Check them, or reset your password."
CHECK_EMAIL = "If that email can be used, we've sent it a link. Check your inbox (and spam folder)."


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _app_url() -> str:
    origins = settings.allowed_origins
    return origins[0] if origins else "http://localhost:3001"


async def _user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none()


async def _new_link(db: AsyncSession, user: User, purpose: str, ttl: timedelta,
                    pending_password_hash: str | None = None) -> str:
    """A fresh one-time token for ``purpose``; earlier unused ones for the same purpose stop working."""
    now = datetime.now(timezone.utc)
    await db.execute(update(AuthToken).where(AuthToken.user_id == user.id, AuthToken.purpose == purpose,
                                             AuthToken.used_at.is_(None)).values(used_at=now))
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(user_id=user.id, purpose=purpose, token_hash=_hash_token(token), expires_at=now + ttl,
                     pending_password_hash=pending_password_hash))
    return token


async def _use_link(db: AsyncSession, token: str, purpose: str) -> tuple[User, AuthToken]:
    """The user a valid, unused, unexpired link belongs to (and marks it used); 400 otherwise."""
    now = datetime.now(timezone.utc)
    row = (await db.execute(select(AuthToken).where(
        AuthToken.token_hash == _hash_token(token or ""), AuthToken.purpose == purpose).with_for_update())
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise HTTPException(400, "This link has expired or was already used. Ask for a new one.")
    row.used_at = now
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(400, "This link has expired or was already used. Ask for a new one.")
    return user, row


async def _send_link(email: str, subject: str, intro: str, path: str, token: str, ttl_words: str) -> None:
    link = f"{_app_url()}{path}={quote(token)}"
    text = (f"{intro}\n\n{link}\n\nThe link works once and expires in {ttl_words}. If you didn't ask for this, "
            "you can ignore this email; nothing changes.\n\nAutoAccounting")
    try:
        await email_service.send(email, subject, text)
    except Exception:
        logger.exception("auth_email_failed subject=%s", subject)


def require_email() -> None:
    if not email_service.ready():
        raise HTTPException(503, "Signing up with email isn't available yet. Sign in with Google for now.")


async def register(db: AsyncSession, email: str, password: str, accept_privacy: bool,
                   record_consent) -> None:
    """Create an unverified account and email a verification link. Same answer whether or not the email exists."""
    require_email()
    email = normalize_email(email)
    if not accept_privacy:
        raise HTTPException(400, "Please accept the terms of service and privacy policy to continue.")
    reason = passwords.problem(password, email)
    if reason:
        raise HTTPException(400, reason)
    hashed = await passwords.hash_password(password)  # same work either way
    user = await _user_by_email(db, email)
    if user is None:
        # The password isn't the account's until the link is opened: it waits on the link itself.
        user = User(email=email, role=UserRole.UNVERIFIED)
        record_consent(user)
        db.add(user)
        await db.flush()
        token = await _new_link(db, user, "verify", VERIFY_TTL, pending_password_hash=hashed)
        await db.commit()
        logger.info("password_registration user_id=%s", user.id)
        await _send_link(email, "Confirm your email for AutoAccounting", "Confirm your email to finish signing up:",
                         "/login?verify", token, "24 hours")
        return
    if not user.is_active:
        return
    # Signed up before but never confirmed, or already an account: nothing changes here (a stranger must never be
    # able to set this account's password). The inbox gets a link to choose a password, which also confirms it.
    token = await _new_link(db, user, "reset", RESET_TTL)
    await db.commit()
    if user.email_verified_at is None:
        await _send_link(email, "Finish signing up for AutoAccounting",
                         "Someone (hopefully you) asked to sign up with this email again. Choose your password here "
                         "to finish:", "/login?reset", token, "30 minutes")
    else:
        await _send_link(email, "You already have an AutoAccounting account",
                         "Someone (hopefully you) tried to sign up with this email, but it already has an account. "
                         "Sign in with Google or your password, or set a new password here:",
                         "/login?reset", token, "30 minutes")


async def verify_email(db: AsyncSession, token: str) -> tuple[User, str]:
    user, link = await _use_link(db, token, "verify")
    if user.email_verified_at is None:
        # Only a still-unconfirmed account takes the password chosen at sign-up; a confirmed one (or one its owner
        # claimed through Google) keeps its own.
        now = datetime.now(timezone.utc)
        user.email_verified_at = now
        if link.pending_password_hash:
            user.password_hash = link.pending_password_hash
            user.password_changed_at = now
    link.pending_password_hash = None
    await db.commit()
    await db.refresh(user)
    logger.info("email_verified user_id=%s", user.id)
    return user, create_access_token(str(user.id))


async def login(db: AsyncSession, email: str, password: str) -> tuple[User, str]:
    email = normalize_email(email)
    user = await _user_by_email(db, email)
    now = datetime.now(timezone.utc)
    if user is not None and user.locked_until and user.locked_until > now:
        await passwords.verify_password(None, password)  # same work as a real attempt
        raise HTTPException(429, "Too many wrong passwords. Try again in 15 minutes, or reset your password.",
                            headers={"Retry-After": str(int((user.locked_until - now).total_seconds()) + 1)})
    ok = await passwords.verify_password(user.password_hash if user else None, password)
    if user is not None and not ok and user.email_verified_at is None and user.is_active:
        pending = await _latest_pending(db, user)
        if pending is not None and await passwords.verify_password(pending.pending_password_hash, password):
            raise HTTPException(403, "Confirm your email first. We sent you a link when you signed up; you can ask "
                                     "for a new one below.")
    if user is None or not ok:
        if user is not None:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= MAX_FAILS:
                user.locked_until, user.failed_logins = now + LOCK_FOR, 0
                logger.warning("password_login_locked user_id=%s", user.id)
            await db.commit()
        logger.info("password_login_failed")
        raise HTTPException(401, WRONG)
    if not user.is_active:
        raise HTTPException(403, "Account is deactivated")
    if user.email_verified_at is None:
        raise HTTPException(403, "Confirm your email first. We sent you a link when you signed up; you can ask "
                                 "for a new one below.")
    user.failed_logins, user.locked_until = 0, None
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = await passwords.hash_password(password)
    await db.commit()
    await db.refresh(user)
    logger.info("password_login_success user_id=%s", user.id)
    return user, create_access_token(str(user.id))


async def _latest_pending(db: AsyncSession, user: User) -> AuthToken | None:
    """The newest sign-up link still holding a password (used or not: resending keeps the same password)."""
    return (await db.execute(select(AuthToken).where(
        AuthToken.user_id == user.id, AuthToken.purpose == "verify", AuthToken.pending_password_hash.is_not(None))
        .order_by(AuthToken.created_at.desc()).limit(1))).scalar_one_or_none()


async def resend_verification(db: AsyncSession, email: str) -> None:
    require_email()
    user = await _user_by_email(db, normalize_email(email))
    pending = await _latest_pending(db, user) if user is not None and user.email_verified_at is None else None
    if user is not None and user.is_active and pending is not None:
        token = await _new_link(db, user, "verify", VERIFY_TTL, pending_password_hash=pending.pending_password_hash)
        await db.commit()
        await _send_link(user.email, "Confirm your email for AutoAccounting", "Confirm your email to finish signing "
                         "up:", "/login?verify", token, "24 hours")


async def forgot_password(db: AsyncSession, email: str) -> None:
    """Email a reset link if the account exists (Google-only accounts can set a password this way too)."""
    require_email()
    user = await _user_by_email(db, normalize_email(email))
    if user is None or not user.is_active:
        return
    token = await _new_link(db, user, "reset", RESET_TTL)
    await db.commit()
    logger.info("password_reset_requested user_id=%s", user.id)
    await _send_link(user.email, "Reset your AutoAccounting password", "Set a new password here:", "/login?reset",
                     token, "30 minutes")


async def reset_password(db: AsyncSession, token: str, password: str) -> tuple[User, str]:
    user, _ = await _use_link(db, token, "reset")
    reason = passwords.problem(password, user.email)
    if reason:
        await db.rollback()  # keep the link usable so they can try another password
        raise HTTPException(400, reason)
    now = datetime.now(timezone.utc)
    user.password_hash = await passwords.hash_password(password)
    user.password_changed_at = now
    user.email_verified_at = user.email_verified_at or now  # opening the emailed link proves the inbox
    user.failed_logins, user.locked_until = 0, None
    await db.execute(update(AuthToken).where(AuthToken.user_id == user.id)
                     .values(used_at=func.coalesce(AuthToken.used_at, now), pending_password_hash=None))
    await db.commit()
    await db.refresh(user)
    logger.info("password_reset_done user_id=%s", user.id)
    # Issued after the change, so this session survives the "signed out everywhere" check.
    return user, create_access_token(str(user.id))
