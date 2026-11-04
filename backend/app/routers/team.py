"""Firm staff management: the firm owner (and managers) add, deactivate and remove members."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import EnterpriseContext, get_db, get_enterprise_context, require_enterprise_owner
from app.models.user import User, UserRole
from app.schemas.auth import AddMemberRequest, FirmUsageResponse, MemberAccess, MemberResponse, UpdateMemberRequest
from app.services import access as access_rules
from app.services import features
from app.services.usage_service import get_effective_rate_config, get_usage_stats
from app.services.accounting import audit

router = APIRouter()

# Roles that belong to a firm as members (the firm owner manages them).
_MEMBER_ROLES = (UserRole.EMPLOYEE, UserRole.MANAGER)
_AUDIT_FIELDS = ("email", "role", "enterprise_id", "is_active")


def _member_response(member: User, caller: User | None = None) -> MemberResponse:
    access = access_rules.clean(member.access)
    return MemberResponse(
        id=str(member.id),
        email=member.email,
        nickname=member.nickname,
        role=member.role.value,
        is_active=member.is_active,
        created_at=member.created_at,
        access=MemberAccess(**access),
        access_summary=access_rules.summary(access, features.LABELS),
        can_edit_access=caller is not None and access_rules.can_manage(caller.role.value, member.role.value),
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
    return [_member_response(m, ctx.caller) for m in members]


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


@router.get("/access-catalog")
async def access_catalog(ctx: EnterpriseContext = Depends(get_enterprise_context)) -> list[dict]:
    """The areas a person can be given or refused, grouped as on the Platform admin's switches."""
    return [{"key": k, "label": label, "group": group, "description": _ACCESS_HELP.get(k, desc)}
            for k, label, group, desc in features.FEATURES if k in access_rules.PERSONAL_KEYS]


# Plainer wording for firm owners than the platform admin's maintenance descriptions.
_ACCESS_HELP = {
    "documents": "See and edit client documents in company folders",
    "upload": "Drop new receipts, invoices and statements to be read",
    "search": "Search everything with / or Ctrl K",
    "notifications": "The notification bell",
    "work": "The work board, tasks and checklists",
    "companies": "Add and edit client companies",
    "team": "See the Team page (only managers can change it)",
    "filing": "Generate, edit and download quarterly returns, and mark them filed",
    "annual": "Annual income tax returns",
    "employees": "Client employees, alphalist and 2316s",
    "books": "Journals, ledgers and the chart of accounts",
    "close": "Close and reopen months",
    "recurring": "Recurring journal entries",
    "bank": "Bank statements, matching and reconciliation",
    "subledgers": "Customers, suppliers, A/R and A/P, write-offs and 2307s",
    "reports": "P&L, balance sheet and other live reports",
    "reclassify": "Move many postings to another account at once",
    "imports": "Import opening balances, open items and journals",
    "atc": "Supplier and account ATC defaults",
    "audit": "The audit log of who changed what",
}


@router.put("/members/{member_id}/access", response_model=MemberResponse)
async def set_member_access(
    member_id: uuid.UUID,
    req: MemberAccess,
    db: AsyncSession = Depends(get_db),
    ctx: EnterpriseContext = Depends(get_enterprise_context),
):
    """What one person can use. The owner sets anyone's; a manager sets employees' only. Audited."""
    member = await _member_or_404(db, ctx.enterprise.id, member_id)
    if not access_rules.can_manage(ctx.caller.role.value, member.role.value):
        raise HTTPException(status_code=403, detail="Only the firm owner can change a manager's access")
    unknown = set(req.off) - set(access_rules.PERSONAL_KEYS)
    if unknown:
        raise HTTPException(status_code=400, detail="Unknown area: " + ", ".join(sorted(unknown)))
    before = access_rules.clean(member.access)
    after = access_rules.clean(req.model_dump())
    if before != after:
        member.access = after
        audit.record(db, ent=ctx.enterprise.id, company_id=None, user=ctx.caller, entity="team_member",
                     entity_id=member.id, action="access", before={"access": before}, after={"access": after},
                     label=member.email)
        await db.commit()
        await db.refresh(member)
    return _member_response(member, ctx.caller)


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
