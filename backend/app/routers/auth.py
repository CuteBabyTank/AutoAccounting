"""Auth routes: Google SSO + profile."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import login_limiter
from app.config import settings
from app.dependencies import get_db, get_current_user
from app.edge import client_ip
from app.models.user import User
from app.schemas.auth import DevLoginRequest, GoogleAuthRequest, TokenResponse, UpdateMeRequest, UserResponse
from app.services.avatar_service import MAX_UPLOAD_BYTES, make_avatar
from app.services.auth_service import dev_login, dev_login_enabled, google_login, user_to_response
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
async def auth_config():
    """Tells the login page which sign-in to show."""
    return {"dev_login": dev_login_enabled()}


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
