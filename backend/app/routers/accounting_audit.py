"""Read-only firm audit history. Writes are part of the modifying router's transaction."""
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AAAuditEvent
from app.models.user import User
from app.routers.accounting_scope import scope_for

router = APIRouter()
_MANILA = ZoneInfo("Asia/Manila")


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID | None
    user_id: uuid.UUID | None
    user_name: str
    at: datetime
    entity: str
    entity_id: str
    action: str
    before: dict
    after: dict
    reason: str


class AuditPageOut(BaseModel):
    events: list[AuditEventOut]
    users: list[dict] = Field(default_factory=list)
    has_more: bool


@router.get("/audit-events", response_model=AuditPageOut)
async def list_audit_events(
    company_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None,
    date_from: date | None = None, date_to: date | None = None,
    entity: str | None = Query(None, max_length=40), entity_id: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "Start date must be on or before end date")
    scope = [AAAuditEvent.enterprise_id == ent]
    if company_id:
        scope.append(AAAuditEvent.company_id == company_id)
    filters = list(scope)
    if user_id:
        filters.append(AAAuditEvent.user_id == user_id)
    if date_from:
        filters.append(AAAuditEvent.at >= datetime.combine(date_from, time.min, _MANILA))
    if date_to:
        filters.append(AAAuditEvent.at < datetime.combine(date_to + timedelta(days=1), time.min, _MANILA))
    if entity:
        filters.append(AAAuditEvent.entity == entity)
    if entity_id:
        filters.append(AAAuditEvent.entity_id == entity_id)
    # Actors come only from this firm's/company's history, including former staff.
    actors = (await db.execute(select(AAAuditEvent.user_id, AAAuditEvent.user_name).where(*scope)
                               .distinct())).all()
    rows = (await db.execute(select(AAAuditEvent).where(*filters)
                            .order_by(AAAuditEvent.at.desc(), AAAuditEvent.id.desc())
                            .offset(offset).limit(limit + 1))).scalars().all()
    users = {str(uid): name for uid, name in actors if uid is not None}
    return AuditPageOut(events=[AuditEventOut.model_validate(r) for r in rows[:limit]],
                        users=[{"id": uid, "name": name} for uid, name in sorted(users.items(), key=lambda x: x[1])],
                        has_more=len(rows) > limit)
