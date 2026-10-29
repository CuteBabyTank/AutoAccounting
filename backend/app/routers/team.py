"""Firm staff management: the firm owner (and managers) add, deactivate and remove members."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import EnterpriseContext, get_db, get_enterprise_context, require_enterprise_owner
from app.models.user import User, UserRole
from app.schemas.auth import AddMemberRequest, FirmUsageResponse, MemberResponse, UpdateMemberRequest
from app.services.usage_service import get_effective_rate_config, get_usage_stats
from app.services.accounting import audit

router = APIRouter()

# Roles that belong to a firm as members (the firm owner manages them).
_MEMBER_ROLES = (UserRole.EMPLOYEE, UserRole.MANAGER)
_AUDIT_FIELDS = ("email", "role", "enterprise_id", "is_active")


def _member_response(member: User) -> MemberResponse:
    return MemberResponse(
        id=str(member.id),
        email=member.email,
        nickname=member.nickname,
        role=member.role.value,
        is_active=member.is_active,
        created_at=member.created_at,
    )


async def _member_or_404(db: AsyncSession, firm_id: uuid.UUID, member_id: uuid.UUID, roles=_MEMBER_ROLES) -> User:
    member = (await db.execute(
        select(User).where(User.id == member_id, User.enterprise_id == firm_id, User.role.in_(roles))
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@router.get("/usage", response_model=FirmUsageResponse)
async def firm_usage(
    db: AsyncSession = Depends(get_db),
    ctx: EnterpriseContext = Depends(get_enterprise_context),
):
    """This month's extracted pages and the firm's remaining budget."""
    firm = ctx.enterprise
    stats = await get_usage_stats(db, firm.id)
    flat, tiers = await get_effective_rate_config(db, firm)
    return FirmUsageResponse(
        organization_name=firm.organization_name,
        pages_used=stats.get("pages_used", 0),
        year=stats["year"],
        month=stats["month"],
        budget=firm.budget or 0.0,
        billing_enabled=bool(flat or tiers),
    )


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    db: AsyncSession = Depends(get_db),
    ctx: EnterpriseContext = Depends(get_enterprise_context),
):
    members = (await db.execute(
        select(User)
        .where(User.enterprise_id == ctx.enterprise.id, User.role.in_(_MEMBER_ROLES))
        .order_by(User.created_at.desc())
    )).scalars().all()
    return [_member_response(m) for m in members]


@router.post("/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def add_member(
    req: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EnterpriseContext = Depends(get_enterprise_context),
):
    """Attach an existing UNVERIFIED signup to this firm as an employee."""
    target = (await db.execute(select(User).where(User.email == req.email))).scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with that email. Ask them to sign in with Google first.",
        )
    if target.role != UserRole.UNVERIFIED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"That user is already a {target.role.value}, not an unverified signup.",
        )
    target.role = UserRole.EMPLOYEE
    target.enterprise_id = ctx.enterprise.id
    target.is_active = True
    audit.record(db, ent=ctx.enterprise.id, company_id=None, user=ctx.caller, entity="team_member",
                 entity_id=target.id, action="create", after=audit.snapshot(target, _AUDIT_FIELDS),
                 label=target.email)
    await db.commit()
    await db.refresh(target)
    return _member_response(target)


@router.put("/members/{member_id}", response_model=MemberResponse)
async def update_member(
    member_id: uuid.UUID,
    req: UpdateMemberRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EnterpriseContext = Depends(get_enterprise_context),
):
    """Activate/deactivate a member. Managers cannot modify other managers."""
    member = await _member_or_404(db, ctx.enterprise.id, member_id)
    if ctx.caller.role == UserRole.MANAGER and member.role == UserRole.MANAGER:
        raise HTTPException(status_code=403, detail="Managers cannot modify other managers")
    if req.is_active is not None:
        before = audit.snapshot(member, _AUDIT_FIELDS)
        member.is_active = req.is_active
        audit.record(db, ent=ctx.enterprise.id, company_id=None, user=ctx.caller, entity="team_member",
                     entity_id=member.id, action="update", before=before, after=audit.snapshot(member, _AUDIT_FIELDS),
                     label=member.email)
    await db.commit()
    await db.refresh(member)
    return _member_response(member)


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EnterpriseContext = Depends(get_enterprise_context),
):
    """Unlink a member from the firm (back to UNVERIFIED). Their account stays, so
    they can be re-added later. Managers cannot remove other managers."""
    member = await _member_or_404(db, ctx.enterprise.id, member_id)
    if ctx.caller.role == UserRole.MANAGER and member.role == UserRole.MANAGER:
        raise HTTPException(status_code=403, detail="Managers cannot remove other managers")
    before = audit.snapshot(member, _AUDIT_FIELDS)
    member.enterprise_id = None
    member.role = UserRole.UNVERIFIED
    audit.record(db, ent=ctx.enterprise.id, company_id=None, user=ctx.caller, entity="team_member",
                 entity_id=member.id, action="delete", before=before, after=audit.snapshot(member, _AUDIT_FIELDS),
                 label=member.email)
    await db.commit()


@router.post("/members/{member_id}/promote-manager", response_model=MemberResponse)
async def promote_to_manager(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner: User = Depends(require_enterprise_owner),
):
    """Firm owner only: employee → manager."""
    member = await _member_or_404(db, owner.id, member_id, roles=(UserRole.EMPLOYEE,))
    before = audit.snapshot(member, _AUDIT_FIELDS)
    member.role = UserRole.MANAGER
    audit.record(db, ent=owner.id, company_id=None, user=owner, entity="team_member", entity_id=member.id,
                 action="update", before=before, after=audit.snapshot(member, _AUDIT_FIELDS), label=member.email)
    await db.commit()
    await db.refresh(member)
    return _member_response(member)


@router.post("/members/{member_id}/demote", response_model=MemberResponse)
async def demote_to_employee(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner: User = Depends(require_enterprise_owner),
):
    """Firm owner only: manager → employee."""
    member = await _member_or_404(db, owner.id, member_id, roles=(UserRole.MANAGER,))
    before = audit.snapshot(member, _AUDIT_FIELDS)
    member.role = UserRole.EMPLOYEE
    audit.record(db, ent=owner.id, company_id=None, user=owner, entity="team_member", entity_id=member.id,
                 action="update", before=before, after=audit.snapshot(member, _AUDIT_FIELDS), label=member.email)
    await db.commit()
    await db.refresh(member)
    return _member_response(member)
