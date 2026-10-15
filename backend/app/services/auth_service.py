"""Authentication service: Google SSO only."""

import logging

from fastapi import HTTPException
from google.oauth2 import id_token
from google.auth.transport import requests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.config import settings
from app.models.user import User, UserRole

logger = logging.getLogger("auth.audit")


class _AccountDeactivated(Exception):
    """Distinct signal so we can surface a friendly message without leaking
    arbitrary text from Google's token-verification ValueError."""


async def google_login(db: AsyncSession, credential: str, client_id: str) -> tuple[User, str]:
    if not client_id:
        raise HTTPException(status_code=500, detail="Google Auth is not configured on the server")

    try:
        try:
            # clock_skew_in_seconds tolerates minor NTP drift between us and Google's
            # token issuer. Without it, a token minted right at a second boundary can be
            # rejected as "used too early" when our clock lags by ~1s (common on the
            # Docker Desktop VM locally, and possible under NTP jitter on Cloud Run).
            idinfo = id_token.verify_oauth2_token(
                credential, requests.Request(), client_id, clock_skew_in_seconds=10
            )
        except ValueError:
            # Token verification failure: do NOT propagate Google's error text —
            # it can vary across SDK versions and may include diagnostic detail.
            logger.warning("google_login_failed reason=invalid_token")
            raise HTTPException(status_code=401, detail="Invalid Google token")

        email = idinfo.get("email")
        if not email or not idinfo.get("email_verified", False):
            logger.warning("google_login_failed reason=missing_or_unverified_email")
            raise HTTPException(status_code=401, detail="Invalid Google token")

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            user = User(email=email, role=UserRole.UNVERIFIED)
            db.add(user)
            await db.commit()
            await db.refresh(user)
            logger.info("google_registration_success user_id=%s email=%s", user.id, email)
        else:
            if not user.is_active:
                logger.warning("google_login_failed reason=deactivated user_id=%s email=%s", user.id, email)
                raise _AccountDeactivated()
            logger.info("google_login_success user_id=%s email=%s", user.id, email)

        if user.role == UserRole.UNVERIFIED:
            await _maybe_bootstrap_admin(db, user)

        token = create_access_token(str(user.id))
        return user, token
    except _AccountDeactivated:
        raise HTTPException(status_code=403, detail="Account is deactivated")


def dev_login_enabled() -> bool:
    """Both an explicit opt-in flag and a development environment are required,
    so neither a forgotten ENVIRONMENT nor a stray flag can expose it alone."""
    return settings.enable_dev_login and settings.environment == "development"


DEV_ADMIN_EMAIL = "dev-admin@example.com"


async def dev_login(db: AsyncSession, email: str | None) -> tuple[User, str]:
    """Development-only sign-in, standing in for Google SSO until a client ID
    is configured. With no email it signs in as the oldest platform admin
    (or BOOTSTRAP_ADMIN_EMAIL / a dev admin on a fresh database). The first
    user on a database with no admin becomes the platform admin."""
    if not dev_login_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    if not email:
        admin_email = (await db.execute(
            select(User.email).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
            .order_by(User.created_at).limit(1)
        )).scalar_one_or_none()
        email = admin_email or settings.bootstrap_admin_email or DEV_ADMIN_EMAIL
    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        user = User(email=email, role=UserRole.UNVERIFIED)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("dev_registration user_id=%s email=%s", user.id, email)
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    if user.role == UserRole.UNVERIFIED:
        has_admin = (await db.execute(
            select(User.id).where(User.role == UserRole.ADMIN).limit(1)
        )).first()
        if not has_admin:
            user.role = UserRole.ADMIN
            await db.commit()
            await db.refresh(user)
            logger.info("dev_bootstrap_admin_granted user_id=%s email=%s", user.id, email)

    logger.info("dev_login_success user_id=%s email=%s", user.id, email)
    return user, create_access_token(str(user.id))


async def _maybe_bootstrap_admin(db: AsyncSession, user: User) -> None:
    """First sign-in of ``BOOTSTRAP_ADMIN_EMAIL`` becomes the platform admin,
    but only while the platform has no admin yet (a fresh database)."""
    wanted = (settings.bootstrap_admin_email or "").strip().lower()
    if not wanted or user.email.lower() != wanted:
        return
    has_admin = (await db.execute(
        select(User.id).where(User.role == UserRole.ADMIN).limit(1)
    )).first()
    if has_admin:
        return
    user.role = UserRole.ADMIN
    await db.commit()
    await db.refresh(user)
    logger.info("bootstrap_admin_granted user_id=%s email=%s", user.id, user.email)


def user_to_response(user: User) -> dict:
    """Convert User model to UserResponse dict."""
    return {
        "id": str(user.id),
        "email": user.email,
        "nickname": user.nickname,
        "role": user.role.value if user.role else "unverified",
        "organization_name": user.organization_name,
        "is_active": user.is_active,
        "enterprise_id": str(user.enterprise_id) if user.enterprise_id else None,
        "created_at": user.created_at,
    }
