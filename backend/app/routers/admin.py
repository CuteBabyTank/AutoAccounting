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
from app.services.accounting import audit
from app.services.budget_service import compute_new_budget

router = APIRouter()

_MEMBER_ROLES = (UserRole.EMPLOYEE, UserRole.MANAGER)
_ACCOUNT_FIELDS = ("email", "role", "enterprise_id", "organization_name", "is_active")


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
    before = audit.snapshot(target, _ACCOUNT_FIELDS)
    target.role = UserRole.ENTERPRISE
    if req.organization_name is not None:
        target.organization_name = req.organization_name.strip() or None
    # Platform operations live in the acting admin's ledger: inserting into another firm's audit ledger
    # would violate FORCE RLS for a NOBYPASSRLS admin. The target identity is preserved in the event.
    audit.record(db, ent=_admin.id, company_id=None, user=_admin, entity="platform_account", entity_id=target.id,
                 action="update", before=before, after=audit.snapshot(target, _ACCOUNT_FIELDS), label=target.email)
    await db.commit()
    return {"id": str(target.id), "role": target.role.value}


@router.put("/users/{user_id}/role")
async def set_user_role(
    user_id: uuid.UUID,
    req: SetUserRoleRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Set a user's role tier. Firm owners keep their identity so retained tax data never becomes orphaned."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    target = await _user_or_404(db, user_id)
    if target.role == UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Cannot change role of an admin")

    new_role = UserRole(req.role)
    if target.role == UserRole.ENTERPRISE and new_role != UserRole.ENTERPRISE:
        raise HTTPException(status_code=409, detail="A firm owner's role must stay intact to retain access to tax "
                            "records. Deactivate the firm instead.")
    before = audit.snapshot(target, _ACCOUNT_FIELDS)
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

    target.role = new_role
    if new_role not in _MEMBER_ROLES:
        target.enterprise_id = None
    audit.record(db, ent=admin.id, company_id=None, user=admin, entity="platform_account", entity_id=target.id,
                 action="update", before=before, after=audit.snapshot(target, _ACCOUNT_FIELDS), label=target.email)
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
    before = audit.snapshot(target, _ACCOUNT_FIELDS)
    target.is_active = not target.is_active
    members_updated = 0
    if target.role == UserRole.ENTERPRISE:
        result = await db.execute(
            update(User)
            .where(User.enterprise_id == target.id, User.role.in_(_MEMBER_ROLES))
            .values(is_active=target.is_active)
        )
        members_updated = result.rowcount
    audit.record(db, ent=admin.id, company_id=None, user=admin, entity="platform_account", entity_id=target.id,
                 action="update", before=before, after=audit.snapshot(target, _ACCOUNT_FIELDS),
                 label=target.email, reason=f"Firm members updated: {members_updated}")
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
    before = {"page_rate": admin.page_rate, "page_rate_tiers": admin.page_rate_tiers}
    await db.execute(
        update(User).where(User.role == UserRole.ADMIN).values(page_rate=req.page_rate, page_rate_tiers=None)
    )
    audit.record(db, ent=admin.id, company_id=None, user=admin, entity="platform_settings", entity_id="page-rate",
                 action="update", before=before, after={"page_rate": req.page_rate, "page_rate_tiers": None},
                 label="Billing rate")
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
    await db.refresh(firm, with_for_update=True)
    before = {"budget": firm.budget}
    firm.budget = compute_new_budget(firm.budget, req.operation, req.amount)
    audit.record(db, ent=_admin.id, company_id=None, user=_admin, entity="platform_account", entity_id=firm.id,
                 action="update", before=before, after={"budget": firm.budget}, label=firm.email,
                 reason=f"Budget {req.operation}: {req.amount}")
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
        # {firm id: {key: bool}}, only firms with at least one override.
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
    old = (await db.execute(select(FeatureToggle.enabled).where(FeatureToggle.key == key))).scalar_one_or_none()
    await db.execute(
        pg_insert(FeatureToggle.__table__).values(key=key, enabled=req.enabled)
        .on_conflict_do_update(index_elements=["key"], set_={"enabled": req.enabled})
    )
    audit.record(db, ent=admin.id, company_id=None, user=admin, entity="platform_settings", entity_id=key,
                 action="update", before={"enabled": True if old is None else old}, after={"enabled": req.enabled},
                 label=f"Feature: {key}")
    await db.commit()
    features.logger.info("feature_switch key=%s enabled=%s admin=%s", key, req.enabled, admin.id)
    return await _features_out(db)


@router.post("/features/all-on")
async def all_features_on(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Back to normal: every global switch on and every firm override cleared."""
    old_global = dict((await db.execute(select(FeatureToggle.key, FeatureToggle.enabled))).all())
    old_firms = (await db.execute(select(FirmFeatureOverride))).scalars().all()
    before = {"global": old_global, "overrides": [
        {"firm_id": str(r.enterprise_id), "feature": r.key, "enabled": r.enabled} for r in old_firms]}
    await db.execute(delete(FeatureToggle))
    await db.execute(delete(FirmFeatureOverride))
    audit.record(db, ent=admin.id, company_id=None, user=admin, entity="platform_settings", entity_id="all-features",
                 action="update", before=before, after={"global": {}, "overrides": []}, label="Reset feature switches")
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
    old = (await db.execute(select(FirmFeatureOverride.enabled).where(
        FirmFeatureOverride.enterprise_id == firm_id, FirmFeatureOverride.key == key))).scalar_one_or_none()
    if req.enabled is None:
        await db.execute(delete(FirmFeatureOverride).where(
            FirmFeatureOverride.enterprise_id == firm_id, FirmFeatureOverride.key == key))
    else:
        await db.execute(
            pg_insert(FirmFeatureOverride.__table__).values(enterprise_id=firm_id, key=key, enabled=req.enabled)
            .on_conflict_do_update(index_elements=["enterprise_id", "key"], set_={"enabled": req.enabled})
        )
    audit.record(db, ent=admin.id, company_id=None, user=admin, entity="platform_settings", entity_id=f"{firm_id}:{key}",
                 action="update", before={"enabled": old}, after={"enabled": req.enabled},
                 label=f"Firm {firm_id} feature: {key}")
    await db.commit()
    features.logger.info("feature_switch firm=%s key=%s enabled=%s admin=%s", firm_id, key, req.enabled, admin.id)
    return await _features_out(db)
