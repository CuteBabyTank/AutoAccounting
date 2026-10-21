"""``GET /api/features``: which features the signed-in user's firm has on (the frontend hides the rest)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User, UserRole
from app.services import features

router = APIRouter()


@router.get("")
async def my_features(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """``{enabled: {key: bool}, off: [keys]}``. The admin gets everything on, and ``off`` lists the keys switched
    off for everyone, so their own screens can mark what firms can't see."""
    if user.role == UserRole.ADMIN:
        toggles, _ = await features.load_state(db)
        return {"enabled": {k: True for k in features.KEYS},
                "off": [k for k in features.KEYS if not toggles.get(k, True)]}
    enabled = await features.effective_for(db, user)
    return {"enabled": enabled, "off": [k for k, on in enabled.items() if not on]}
