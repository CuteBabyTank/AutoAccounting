"""Close-checklist templates: firm-level lists of close steps that create tasks for a company + period in one click.

Two built-in templates (monthly close, quarter close) are always offered; owners and managers add firm templates.
Applying is open to everyone who can add tasks; each created task is audited like a typed one.
"""

import uuid
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AAChecklistTemplate, AATask
from app.models.user import User
from app.routers.accounting_scope import MANAGER_ROLES, company_or_404, scope_for
from app.routers.accounting_tasks import _FIELDS as TASK_FIELDS, tasks_out
from app.routers.accounting_work import assignee_or_400
from app.schemas.accounting_work import TaskOut
from app.services.accounting import audit
from app.services.accounting.compute.checklists import BUILTIN, clean_items, plan_tasks

router = APIRouter()
_FIELDS = ("name", "cadence", "items")


class ChecklistItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    notes: str = Field(default="", max_length=2000)
    offset_days: int = Field(default=0, ge=-60, le=365)
    priority: Literal["low", "normal", "high"] = "normal"


class ChecklistIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    cadence: Literal["monthly", "quarterly", "annual"] = "monthly"
    items: list[ChecklistItemIn] = Field(min_length=1, max_length=50)


class ChecklistOut(BaseModel):
    id: str                  # a uuid, or builtin:<key>
    name: str
    cadence: str
    items: list[dict]
    builtin: bool


class ApplyIn(BaseModel):
    company_id: uuid.UUID
    period_end: date
    assignee_id: uuid.UUID | None = None


class ApplyOut(BaseModel):
    created: list[TaskOut]
    skipped: int


def _out(row: AAChecklistTemplate) -> ChecklistOut:
    return ChecklistOut(id=str(row.id), name=row.name, cadence=row.cadence, items=row.items or [], builtin=False)


def _manager(user: User) -> None:
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners and managers can change checklist templates")


def _clean(body: ChecklistIn) -> list[dict]:
    try:
        return clean_items([i.model_dump() for i in body.items])
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


async def _row_or_404(db: AsyncSession, ent: uuid.UUID, template_id: str) -> AAChecklistTemplate:
    try:
        tid = uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist template not found") from None
    row = (await db.execute(select(AAChecklistTemplate).where(
        AAChecklistTemplate.id == tid, AAChecklistTemplate.enterprise_id == ent))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist template not found")
    return row


@router.get("/checklist-templates", response_model=list[ChecklistOut])
async def list_checklists(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    rows = (await db.execute(select(AAChecklistTemplate).where(AAChecklistTemplate.enterprise_id == ent)
                             .order_by(AAChecklistTemplate.name))).scalars().all()
    builtin = [ChecklistOut(id=k, name=v["name"], cadence=v["cadence"], items=clean_items(v["items"]), builtin=True)
               for k, v in BUILTIN.items()]
    return builtin + [_out(r) for r in rows]


@router.post("/checklist-templates", response_model=ChecklistOut, status_code=status.HTTP_201_CREATED)
async def create_checklist(body: ChecklistIn, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    _manager(user)
    ent = scope_for(user)
    row = AAChecklistTemplate(id=uuid.uuid4(), enterprise_id=ent, name=body.name.strip(), cadence=body.cadence,
                              items=_clean(body), created_by=user.id)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"There is already a checklist named {body.name.strip()!r}")
    audit.record(db, ent=ent, company_id=None, user=user, entity="checklist_template", entity_id=row.id,
                 action="create", label=row.name, after=audit.snapshot(row, _FIELDS))
    await db.commit()
    return _out(row)


@router.put("/checklist-templates/{template_id}", response_model=ChecklistOut)
async def update_checklist(template_id: str, body: ChecklistIn, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    _manager(user)
    ent = scope_for(user)
    row = await _row_or_404(db, ent, template_id)
    before = audit.snapshot(row, _FIELDS)
    row.name, row.cadence, row.items = body.name.strip(), body.cadence, _clean(body)
    row.updated_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"There is already a checklist named {body.name.strip()!r}")
    audit.record(db, ent=ent, company_id=None, user=user, entity="checklist_template", entity_id=row.id,
                 action="update", label=row.name, before=before, after=audit.snapshot(row, _FIELDS))
    await db.commit()
    return _out(row)


@router.delete("/checklist-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checklist(template_id: str, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    _manager(user)
    ent = scope_for(user)
    row = await _row_or_404(db, ent, template_id)
    audit.record(db, ent=ent, company_id=None, user=user, entity="checklist_template", entity_id=row.id,
                 action="delete", label=row.name, before=audit.snapshot(row, _FIELDS), after=None)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/checklist-templates/{template_id}/apply", response_model=ApplyOut)
async def apply_checklist(template_id: str, body: ApplyIn, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """One task per step for the company and the period ending on ``period_end`` (steps already there are skipped)."""
    ent = scope_for(user)
    if template_id in BUILTIN:
        name, cadence, items = BUILTIN[template_id]["name"], BUILTIN[template_id]["cadence"], BUILTIN[template_id]["items"]
    else:
        row = await _row_or_404(db, ent, template_id)
        name, cadence, items = row.name, row.cadence, row.items or []
    company = await company_or_404(db, ent, body.company_id)
    if not date(2000, 1, 1) <= body.period_end <= date(2100, 12, 31):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick a period end between 2000 and 2100")
    await assignee_or_400(db, ent, body.assignee_id)
    existing = {t.lower() for t in (await db.execute(select(func.lower(AATask.title)).where(
        AATask.enterprise_id == ent, AATask.company_id == company.id))).scalars().all()}
    try:
        planned = plan_tasks(items, cadence, body.period_end, company.fiscal_year_end_month, existing)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    rows = []
    for values in planned:
        task = AATask(id=uuid.uuid4(), enterprise_id=ent, company_id=company.id, assignee_id=body.assignee_id,
                      status="open", created_by=user.id, **values)
        db.add(task)
        audit.record(db, ent=ent, company_id=company.id, user=user, entity="task", entity_id=task.id,
                     action="create", label=task.title[:200], after=audit.snapshot(task, TASK_FIELDS),
                     reason=f"Checklist: {name}")
        rows.append(task)
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="checklist_template", entity_id=template_id,
                 action="apply", label=name, after={"period_end": body.period_end.isoformat(),
                                                    "created": len(rows), "skipped": len(items) - len(rows)})
    await db.commit()
    return ApplyOut(created=await tasks_out(db, ent, rows), skipped=len(items) - len(rows))
