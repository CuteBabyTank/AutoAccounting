"""Firm scoping shared by the AutoAccounting routers."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AACompany
from app.models.user import User, UserRole

MANAGER_ROLES = (UserRole.ADMIN, UserRole.ENTERPRISE, UserRole.MANAGER)
MEMBER_ROLES = MANAGER_ROLES + (UserRole.EMPLOYEE,)


def scope_for(user: User) -> uuid.UUID:
    """The firm (enterprise owner id) every AutoAccounting row is scoped to."""
    if user.role not in MEMBER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account cannot use AutoAccounting")
    if user.role in (UserRole.ADMIN, UserRole.ENTERPRISE):
        return user.id
    if user.enterprise_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not part of a firm")
    return user.enterprise_id


async def company_or_404(db: AsyncSession, ent: uuid.UUID, company_id: uuid.UUID) -> AACompany:
    company = (await db.execute(
        select(AACompany).where(AACompany.id == company_id, AACompany.enterprise_id == ent)
    )).scalar_one_or_none()
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return company


FILING_GUARD_MESSAGE = ("Your firm has managers approve filings: ask a manager or the firm owner to mark this "
                        "return filed.")


def may_file(role: UserRole, approve_before_close: bool) -> bool:
    """Whether this person may mark returns filed (with the firm setting on, only owners and managers)."""
    return not approve_before_close or role in MANAGER_ROLES


async def firm_settings(db: AsyncSession, ent: uuid.UUID):
    """The firm's settings row, or an unsaved one with the defaults."""
    from app.models.accounting import AAFirmSettings

    row = (await db.execute(select(AAFirmSettings).where(AAFirmSettings.enterprise_id == ent))).scalar_one_or_none()
    return row or AAFirmSettings(enterprise_id=ent, approve_before_close=False, deadline_days=7, auto_assign=True)


async def require_filing_rights(db: AsyncSession, user: User, ent: uuid.UUID) -> None:
    from app.services.accounting.assignment import lock_firm

    await lock_firm(db, ent)  # serialize real filing marks with board auto-assignment
    settings = await firm_settings(db, ent)
    if not may_file(user.role, settings.approve_before_close):
        raise HTTPException(status.HTTP_403_FORBIDDEN, FILING_GUARD_MESSAGE)
