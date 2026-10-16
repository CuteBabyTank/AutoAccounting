"""Audit log: firm-scoped list of who changed what (written by ``services/accounting/audit.record``)."""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AAAuditEvent
from app.models.user import User
from app.routers.accounting_scope import scope_for
from app.schemas.accounting_audit import AuditEventOut, AuditPageOut, AuditUserOut

router = APIRouter()

_MANILA = ZoneInfo("Asia/Manila")


def day_bounds(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    """Manila midnight of ``start`` and the midnight after ``end`` (both inclusive calendar days)."""
    lo = datetime.combine(start, time(), tzinfo=_MANILA) if start else None
    hi = datetime.combine(end + timedelta(days=1), time(), tzinfo=_MANILA) if end else None
    return lo, hi


def _filters(ent: uuid.UUID, company_id: uuid.UUID | None, entity: str | None, entity_id: str | None) -> list:
    conds = [AAAuditEvent.enterprise_id == ent]
    if company_id is not None:
        conds.append(AAAuditEvent.company_id == company_id)
    if entity:
        conds.append(AAAuditEvent.entity == entity)
    if entity_id:
        conds.append(AAAuditEvent.entity_id == entity_id)
    return conds


def events_query(ent: uuid.UUID, *, company_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None,
                 start: date | None = None, end: date | None = None, entity: str | None = None,
                 entity_id: str | None = None) -> Select:
    """The firm's events, newest first, narrowed by whichever filters are given."""
    conds = _filters(ent, company_id, entity, entity_id)
    if user_id is not None:
        conds.append(AAAuditEvent.user_id == user_id)
    lo, hi = day_bounds(start, end)
    if lo is not None:
        conds.append(AAAuditEvent.at >= lo)
    if hi is not None:
        conds.append(AAAuditEvent.at < hi)
    return select(AAAuditEvent).where(*conds).order_by(AAAuditEvent.at.desc(), AAAuditEvent.id.desc())


def _name(user: User | None, label: str) -> str:
    if user is None:
        return label or "Removed user"
    return user.nickname or user.email


@router.get("/audit-events", response_model=AuditPageOut)
async def list_audit_events(
    company_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    start: date | None = None,
    end: date | None = None,
    entity: str | None = Query(default=None, max_length=30),
    entity_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    stmt = events_query(ent, company_id=company_id, user_id=user_id, start=start, end=end, entity=entity,
                        entity_id=entity_id)
    total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    people_ids = (await db.execute(select(AAAuditEvent.user_id).where(
        *_filters(ent, company_id, entity, entity_id), AAAuditEvent.user_id.is_not(None)).distinct())).scalars().all()
    wanted = set(people_ids) | {r.user_id for r in rows if r.user_id}
    people = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(wanted)))).scalars()} if wanted else {}
    return AuditPageOut(
        events=[AuditEventOut(id=r.id, at=r.at, company_id=r.company_id, user_id=r.user_id,
                              user_name=_name(people.get(r.user_id), r.user_label), entity=r.entity,
                              entity_id=r.entity_id, action=r.action, before=r.before or {}, after=r.after or {},
                              reason=r.reason) for r in rows],
        total=total,
        users=sorted((AuditUserOut(id=p.id, name=_name(p, "")) for p in people.values() if p.id in set(people_ids)),
                     key=lambda u: u.name.lower()),
    )
