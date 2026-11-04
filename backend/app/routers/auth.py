"""Auth routes: Google SSO + profile."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import email_send_limiter, login_limiter
from app.config import settings
from app.dependencies import get_db, get_current_user
from app.edge import client_ip
from app.models.user import User
from app.schemas.auth import (DevLoginRequest, EmailRequest, GoogleAuthRequest, PasswordLoginRequest, RegisterRequest,
                              ResetPasswordRequest, TokenRequest, TokenResponse, UpdateMeRequest, UserResponse)
from app.services import email_service, password_auth
from app.services.avatar_service import MAX_UPLOAD_BYTES, make_avatar
from app.services.auth_service import _record_consent, dev_login, dev_login_enabled, google_login, user_to_response
from app.services.usage_service import get_enterprise_for_user, get_usage_stats

router = APIRouter()


async def _response(db: AsyncSession, user: User) -> dict:
    await db.refresh(user, ["avatar"])
    return user_to_response(user)


def _clean_nickname(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _throttle_login(http: Request) -> None:
    ip = client_ip(http.headers, http.client.host if http.client else None, settings.origin_secret)
    if not login_limiter.check_and_record(ip):
        raise HTTPException(429, "Too many sign-in attempts. Please wait a few minutes.", headers={"Retry-After": "300"})


@router.post("/google", response_model=TokenResponse)
async def auth_google(request: GoogleAuthRequest, http: Request, db: AsyncSession = Depends(get_db)):
    _throttle_login(http)
    user, token = await google_login(db, request.credential, settings.google_client_id, request.accept_privacy)
    return TokenResponse(token=token, user=UserResponse(**await _response(db, user)))


@router.get("/config")
async def auth_config(db: AsyncSession = Depends(get_db)):
    """Tells the login page which sign-in to show."""
    signup = email_service.ready()
    # The email + password form only shows once someone could have a password (email set up, or one exists).
    has_passwords = signup or (await db.execute(select(User.id).where(User.password_hash.is_not(None)).limit(1))
                               ).first() is not None
    return {"dev_login": dev_login_enabled(), "password_login": has_passwords,
            # Sign-up and "forgot password" need email to prove the inbox; hidden until a provider is set.
            "password_signup": signup}


def _throttle_email(email: str) -> bool:
    """False once this address has had its emails for the hour (the answer stays the same; nothing is sent)."""
    return email_send_limiter.check_and_record(password_auth.normalize_email(email))


@router.post("/password/login", response_model=TokenResponse)
async def auth_password_login(request: PasswordLoginRequest, http: Request, db: AsyncSession = Depends(get_db)):
    _throttle_login(http)
    user, token = await password_auth.login(db, request.email, request.password)
    return TokenResponse(token=token, user=UserResponse(**await _response(db, user)))


@router.post("/password/register", status_code=202)
async def auth_password_register(request: RegisterRequest, http: Request, db: AsyncSession = Depends(get_db)):
    password_auth.require_email()
    _throttle_login(http)
    if _throttle_email(request.email):
        await password_auth.register(db, request.email, request.password, request.accept_privacy, _record_consent)
    return {"detail": password_auth.CHECK_EMAIL}


@router.post("/password/verify", response_model=TokenResponse)
async def auth_password_verify(request: TokenRequest, http: Request, db: AsyncSession = Depends(get_db)):
    _throttle_login(http)
    user, token = await password_auth.verify_email(db, request.token)
    return TokenResponse(token=token, user=UserResponse(**await _response(db, user)))


@router.post("/password/resend", status_code=202)
async def auth_password_resend(request: EmailRequest, http: Request, db: AsyncSession = Depends(get_db)):
    password_auth.require_email()
    _throttle_login(http)
    if _throttle_email(request.email):
        await password_auth.resend_verification(db, request.email)
    return {"detail": password_auth.CHECK_EMAIL}


@router.post("/password/forgot", status_code=202)
async def auth_password_forgot(request: EmailRequest, http: Request, db: AsyncSession = Depends(get_db)):
    password_auth.require_email()
    _throttle_login(http)
    if _throttle_email(request.email):
        await password_auth.forgot_password(db, request.email)
    return {"detail": password_auth.CHECK_EMAIL}


@router.post("/password/reset", response_model=TokenResponse)
async def auth_password_reset(request: ResetPasswordRequest, http: Request, db: AsyncSession = Depends(get_db)):
    _throttle_login(http)
    user, token = await password_auth.reset_password(db, request.token, request.password)
    return TokenResponse(token=token, user=UserResponse(**await _response(db, user)))


@router.post("/dev-login", response_model=TokenResponse)
async def auth_dev_login(request: DevLoginRequest, db: AsyncSession = Depends(get_db)):
    # dev_login itself refuses (404) unless ENABLE_DEV_LOGIN=true in development.
    user, token = await dev_login(db, request.email)
    return TokenResponse(token=token, user=UserResponse(**await _response(db, user)))


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _response(db, user)
    enterprise = await get_enterprise_for_user(db, user)
    if enterprise:
        stats = await get_usage_stats(db, enterprise.id)
        data["pages_used"] = stats.get("pages_used")
        data["budget"] = enterprise.budget
    return UserResponse(**data)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UpdateMeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Self-service profile update: the nickname (the picture has its own route)."""
    user.nickname = _clean_nickname(payload.nickname)
    await db.commit()
    return UserResponse(**await _response(db, user))


@router.put("/me/avatar", response_model=UserResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set your own profile picture (JPG / PNG under 5 MB, stored as a ~10 KB WebP)."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        user.avatar = make_avatar(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return UserResponse(**await _response(db, user))
