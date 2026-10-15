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
