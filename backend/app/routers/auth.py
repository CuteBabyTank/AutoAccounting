"""Auth routes: Google SSO + profile."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.auth import DevLoginRequest, GoogleAuthRequest, TokenResponse, UpdateMeRequest, UserResponse
from app.services.auth_service import dev_login, dev_login_enabled, google_login, user_to_response
from app.services.usage_service import get_enterprise_for_user, get_usage_stats

router = APIRouter()


def _clean_nickname(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


@router.post("/google", response_model=TokenResponse)
async def auth_google(request: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    user, token = await google_login(db, request.credential, settings.google_client_id)
    return TokenResponse(token=token, user=UserResponse(**user_to_response(user)))


@router.get("/config")
async def auth_config():
    """Tells the login page which sign-in to show."""
    return {"dev_login": dev_login_enabled()}


@router.post("/dev-login", response_model=TokenResponse)
async def auth_dev_login(request: DevLoginRequest, db: AsyncSession = Depends(get_db)):
    # dev_login itself refuses (404) unless ENABLE_DEV_LOGIN=true in development.
    user, token = await dev_login(db, request.email)
    return TokenResponse(token=token, user=UserResponse(**user_to_response(user)))


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = user_to_response(user)
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
    """Self-service profile update. Currently only the nickname is editable."""
    user.nickname = _clean_nickname(payload.nickname)
    await db.commit()
    await db.refresh(user)
    return UserResponse(**user_to_response(user))
