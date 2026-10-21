"""Platform-admin routes: accounts, firm onboarding, page rate, firm budgets and maintenance switches."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.models.api_usage import ApiUsage
from app.models.feature_toggle import FeatureToggle, FirmFeatureOverride
from app.models.user import User, UserRole
from app.schemas.auth import (
    AccountOverview, AdjustBudgetRequest, BudgetResponse, PageRateResponse, PromoteFirmRequest,
    SetPageRateRequest, SetUserRoleRequest,
)
from app.services import features
from app.services.budget_service import compute_new_budget

router = APIRouter()

_MEMBER_ROLES = (UserRole.EMPLOYEE, UserRole.MANAGER)


async def _user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _firm_or_404(db: AsyncSession, firm_id: uuid.UUID) -> User:
    firm = (await db.execute(
        select(User).where(User.id == firm_id, User.role == UserRole.ENTERPRISE)
    )).scalar_one_or_none()
    if firm is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    return firm


@router.get("/accounts", response_model=list[AccountOverview])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Every user on the platform, with this month's page count for firms."""
    users = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    emails = {u.id: u.email for u in users}
    now = datetime.now(timezone.utc)
    pages = dict((await db.execute(
        select(ApiUsage.enterprise_id, func.coalesce(func.sum(ApiUsage.pages_used), 0))
        .where(ApiUsage.year == now.year, ApiUsage.month == now.month)
        .group_by(ApiUsage.enterprise_id)
    )).all())
    return [
        AccountOverview(
            id=str(u.id),
            email=u.email,
            nickname=u.nickname,
            role=u.role.value,
            is_active=u.is_active,
            organization_name=u.organization_name,
            enterprise_id=str(u.enterprise_id) if u.enterprise_id else None,
            enterprise_email=emails.get(u.enterprise_id) if u.enterprise_id else None,
            pages_used=pages.get(u.id, 0),
            budget=u.budget or 0.0,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/users/{user_id}/promote-firm")
async def promote_to_firm(
    user_id: uuid.UUID,
    req: PromoteFirmRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Make an UNVERIFIED signup the owner of a new accounting firm."""
    target = await _user_or_404(db, user_id)
    if target.role != UserRole.UNVERIFIED:
        raise HTTPException(
            status_code=400,
            detail=f"Only unverified users can be promoted. User is currently {target.role.value}.",
        )
    target.role = UserRole.ENTERPRISE
    if req.organization_name is not None:
        target.organization_name = req.organization_name.strip() or None
    await db.commit()
    return {"id": str(target.id), "role": target.role.value}


@router.put("/users/{user_id}/role")
async def set_user_role(
    user_id: uuid.UUID,
    req: SetUserRoleRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Set a user's role tier. Employee/manager need a firm; a firm with members can't be demoted."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    target = await _user_or_404(db, user_id)
    if target.role == UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Cannot change role of an admin")

    new_role = UserRole(req.role)
    if new_role == target.role and not req.enterprise_id:
        return {"id": str(target.id), "role": target.role.value}

    if new_role in _MEMBER_ROLES:
        if req.enterprise_id:
            try:
                firm_id = uuid.UUID(req.enterprise_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid enterprise_id")
            target.enterprise_id = (await _firm_or_404(db, firm_id)).id
        elif target.enterprise_id is None:
            raise HTTPException(status_code=400, detail="Pick the firm this user belongs to.")

    if target.role == UserRole.ENTERPRISE and new_role != UserRole.ENTERPRISE:
        members = (await db.execute(
            select(func.count()).select_from(User).where(User.enterprise_id == target.id)
        )).scalar() or 0
        if members:
            raise HTTPException(
                status_code=400,
                detail="Firm has members. Remove or reassign them before changing its role.",
            )

    target.role = new_role
    if new_role not in _MEMBER_ROLES:
        target.enterprise_id = None
    await db.commit()
    return {"id": str(target.id), "role": target.role.value}


@router.put("/users/{user_id}/toggle-active")
async def toggle_active(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Activate/deactivate an account. Deactivating a firm deactivates its members too."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    target = await _user_or_404(db, user_id)
    target.is_active = not target.is_active
    members_updated = 0
    if target.role == UserRole.ENTERPRISE:
        result = await db.execute(
            update(User)
            .where(User.enterprise_id == target.id, User.role.in_(_MEMBER_ROLES))
            .values(is_active=target.is_active)
        )
        members_updated = result.rowcount
    await db.commit()
    return {"id": str(target.id), "is_active": target.is_active, "members_updated": members_updated}


@router.get("/page-rate", response_model=PageRateResponse)
async def get_page_rate(admin: User = Depends(require_admin)):
    return PageRateResponse(page_rate=admin.page_rate)


@router.put("/page-rate", response_model=PageRateResponse)
async def set_page_rate(
    req: SetPageRateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Platform-wide flat rate per extracted page. Null = billing off (uploads never blocked on budget).

    Written to every admin row: billing reads the rate from whichever admin it finds first."""
    await db.execute(
        update(User).where(User.role == UserRole.ADMIN).values(page_rate=req.page_rate, page_rate_tiers=None)
    )
    await db.commit()
    await db.refresh(admin)
    return PageRateResponse(page_rate=admin.page_rate)


@router.post("/firms/{firm_id}/budget", response_model=BudgetResponse)
async def adjust_firm_budget(
    firm_id: uuid.UUID,
    req: AdjustBudgetRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Top up, deduct or set a firm's prepaid budget."""
    firm = await _firm_or_404(db, firm_id)
    firm.budget = compute_new_budget(firm.budget, req.operation, req.amount)
    await db.commit()
    return BudgetResponse(budget=firm.budget)


# ---- maintenance switches -----------------------------------------------------------------------

class FeatureSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class FirmFeatureSwitch(BaseModel):
    """None clears the firm's override (it follows the global switch again)."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None


def _known(key: str) -> str:
    if key not in features.KEYS:
        raise HTTPException(status_code=404, detail="Unknown feature")
    return key


async def _features_out(db: AsyncSession) -> dict:
    features.invalidate()
    toggles, overrides = await features.load_state(db)
    return {
        "features": [
            {"key": k, "label": label, "group": group, "description": desc, "enabled": toggles.get(k, True)}
            for k, label, group, desc in features.FEATURES
        ],
        # {firm id: {key: bool}} — only firms with at least one override.
        "overrides": {str(firm): o for firm, o in overrides.items() if o},
    }


@router.get("/features")
async def list_features(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)):
    """Every switch with its global state, and each firm's overrides."""
    return await _features_out(db)


@router.put("/features/{key}")
async def set_feature(
    key: str, req: FeatureSwitch, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin),
):
    """Turn a feature on or off for every firm (firm overrides still win)."""
    _known(key)
    await db.execute(
        pg_insert(FeatureToggle.__table__).values(key=key, enabled=req.enabled)
        .on_conflict_do_update(index_elements=["key"], set_={"enabled": req.enabled})
    )
    await db.commit()
    features.logger.info("feature_switch key=%s enabled=%s admin=%s", key, req.enabled, admin.id)
    return await _features_out(db)


@router.post("/features/all-on")
async def all_features_on(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Back to normal: every global switch on and every firm override cleared."""
    await db.execute(delete(FeatureToggle))
    await db.execute(delete(FirmFeatureOverride))
    await db.commit()
    features.logger.info("feature_switch all_on admin=%s", admin.id)
    return await _features_out(db)


@router.put("/firms/{firm_id}/features/{key}")
async def set_firm_feature(
    firm_id: uuid.UUID, key: str, req: FirmFeatureSwitch,
    db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin),
):
    """Pin a feature on or off for one firm, or clear the pin."""
    _known(key)
    await _firm_or_404(db, firm_id)
    if req.enabled is None:
        await db.execute(delete(FirmFeatureOverride).where(
            FirmFeatureOverride.enterprise_id == firm_id, FirmFeatureOverride.key == key))
    else:
        await db.execute(
            pg_insert(FirmFeatureOverride.__table__).values(enterprise_id=firm_id, key=key, enabled=req.enabled)
            .on_conflict_do_update(index_elements=["enterprise_id", "key"], set_={"enabled": req.enabled})
        )
    await db.commit()
    features.logger.info("feature_switch firm=%s key=%s enabled=%s admin=%s", firm_id, key, req.enabled, admin.id)
    return await _features_out(db)
