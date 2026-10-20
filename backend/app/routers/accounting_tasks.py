"""Tasks: free-form to-dos for the firm, optionally about a company, a document or a period. Audited."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AACompany, AADocument, AATask
from app.models.user import User
from app.routers.accounting_scope import MANAGER_ROLES, company_or_404, firm_settings, scope_for
from app.routers.accounting_work import assignee_or_400
from app.schemas.accounting import manila_today
from app.schemas.accounting_work import TaskIn, TaskOut, TaskPatch
from app.services.accounting import audit
from app.services.accounting.compute.tasks import completion_fields, is_task_overdue, sort_tasks
from app.services.accounting.compute.work import board_window
from app.services.accounting.assignment import assign_auto, choose_for_task, lock_firm
from app.services.accounting.work import firm_people, person_name

router = APIRouter()

_FIELDS = ("title", "notes", "due_date", "assignee_id", "status", "priority", "company_id", "document_id",
           "period_year", "period_quarter")
_AUDIT_FIELDS = _FIELDS + ("assigned_auto", "completed_at", "completed_by")


async def _task_or_404(db: AsyncSession, ent: uuid.UUID, task_id: uuid.UUID) -> AATask:
    row = (await db.execute(select(AATask).where(AATask.id == task_id, AATask.enterprise_id == ent))
           ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return row


_LINKS = ("company_id", "document_id", "assignee_id")


async def _check_links(db: AsyncSession, ent: uuid.UUID, values: dict, changed: set[str] | None = None) -> None:
    """The company and document must be the firm's, and the document the company's (a document alone sets it).

    ``changed`` = the links an edit changes (None = all, a new task): a link the task already has isn't re-checked, so
    a task whose document was since deleted, or whose assignee left the firm, can still be edited or completed."""
    changed = set(_LINKS) if changed is None else changed
    if values.get("company_id") is not None and "company_id" in changed:
        await company_or_404(db, ent, values["company_id"])
    if values.get("document_id") is not None and changed & {"company_id", "document_id"}:
        doc = (await db.execute(select(AADocument).where(
            AADocument.id == values["document_id"], AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None))
        )).scalar_one_or_none()
        if doc is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
        if values.get("company_id") is None:
            values["company_id"] = doc.company_id
        elif values["company_id"] != doc.company_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That document belongs to another company")
    if values.get("period_quarter") is not None and values.get("period_year") is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick the year of the period")
    if values.get("period_year") is not None and values.get("company_id") is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A period belongs to a company: pick the company too")
    if "assignee_id" in changed:
        await assignee_or_400(db, ent, values.get("assignee_id"))


def _label(row: AATask) -> str:
    return row.title[:200]


async def tasks_out(db: AsyncSession, ent: uuid.UUID, rows: list[AATask]) -> list[TaskOut]:
    people = {p.id: person_name(p) for p in await firm_people(db, ent)}
    missing = {i for r in rows for i in (r.assignee_id, r.created_by, r.completed_by) if i and i not in people}
    if missing:
        people.update({u.id: person_name(u) for u in (await db.execute(select(User).where(User.id.in_(missing))))
                       .scalars()})
    cids = {r.company_id for r in rows if r.company_id}
    companies = {c.id: c.registered_name for c in (await db.execute(select(AACompany).where(
        AACompany.enterprise_id == ent, AACompany.id.in_(cids)))).scalars()} if cids else {}
    dids = {r.document_id for r in rows if r.document_id}
    docs = {d.id: audit.document_label(d) for d in (await db.execute(select(AADocument).where(
        AADocument.enterprise_id == ent, AADocument.id.in_(dids)))).scalars()} if dids else {}
    today = manila_today()
    return [TaskOut(
        id=r.id, title=r.title, notes=r.notes, due_date=r.due_date, assignee_id=r.assignee_id,
        assignee_name=people.get(r.assignee_id, "") if r.assignee_id else "", status=r.status, priority=r.priority,
        company_id=r.company_id, company_name=companies.get(r.company_id, "") if r.company_id else "",
        document_id=r.document_id, document_label=docs.get(r.document_id, "") if r.document_id else "",
        period_year=r.period_year, period_quarter=r.period_quarter, created_by=r.created_by,
        created_by_name=people.get(r.created_by, "") if r.created_by else "", created_at=r.created_at,
        completed_at=r.completed_at, completed_by=r.completed_by,
        completed_by_name=people.get(r.completed_by, "Unknown"), assigned_auto=r.assigned_auto, overdue=is_task_overdue(r.status, r.due_date, today),
    ) for r in rows]


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    company_id: uuid.UUID | None = None, document_id: uuid.UUID | None = None,
    assignee: str | None = Query(default=None, max_length=40),
    status_filter: str = Query(default="open", alias="status", pattern="^(open|done|all)$"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    conds = [AATask.enterprise_id == ent]
    if company_id is not None:
        conds.append(AATask.company_id == company_id)
    if document_id is not None:
        conds.append(AATask.document_id == document_id)
    if assignee == "me":
        conds.append(AATask.assignee_id == user.id)
    elif assignee == "unassigned":
        conds.append(AATask.assignee_id.is_(None))
    elif assignee:
        try:
            conds.append(AATask.assignee_id == uuid.UUID(assignee))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown assignee") from None
    if status_filter == "open":
        conds.append(AATask.status != "done")
    elif status_filter == "done":
        conds.append(AATask.status == "done")
    rows = (await db.execute(select(AATask).where(*conds).limit(500))).scalars().all()
    return await tasks_out(db, ent, sort_tasks(list(rows)))


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    await lock_firm(db, ent)
    values = body.model_dump()
    await _check_links(db, ent, values)
    row = AATask(id=uuid.uuid4(), enterprise_id=ent, created_by=user.id, **values,
                 assigned_auto=False,
                 completed_by=user.id if values["status"] == "done" else None,
                 completed_at=datetime.now(timezone.utc) if values["status"] == "done" else None)
    db.add(row)
    audit.record(db, ent=ent, company_id=row.company_id, user=user, entity="task", entity_id=row.id,
                 action="create", label=_label(row), before=None, after=audit.snapshot(row, _AUDIT_FIELDS))
    if row.assignee_id is None and (await firm_settings(db, ent)).auto_assign:
        today = manila_today()
        assignee_id = await choose_for_task(db, ent, *board_window(None, None, today), today, row.company_id)
        if assignee_id:
            assign_auto(db, ent, user, row, assignee_id)
    await db.commit()
    return (await tasks_out(db, ent, [row]))[0]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: uuid.UUID, body: TaskPatch, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    await lock_firm(db, ent)
    row = await _task_or_404(db, ent, task_id)
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    if "title" in changes and not (changes["title"] or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A task needs a title")
    for key in ("title", "notes", "status", "priority"):
        if key in changes and changes[key] is None:
            changes.pop(key)
    merged = {k: changes.get(k, getattr(row, k)) for k in _FIELDS}
    if "company_id" in changes and "document_id" not in changes and row.document_id is not None:
        merged["document_id"] = None  # moving the task to another company drops its document link
    await _check_links(db, ent, merged, {k for k in _LINKS if merged[k] != getattr(row, k)})
    before = audit.snapshot(row, _AUDIT_FIELDS)
    for k in _FIELDS:
        setattr(row, k, merged[k].strip() if k == "title" else merged[k])
    if before["assignee_id"] != (str(row.assignee_id) if row.assignee_id else None):
        row.assigned_auto = False
    row.completed_at, row.completed_by = completion_fields(
        before["status"], row.status, user.id, datetime.now(timezone.utc), row.completed_at, row.completed_by)
    after = audit.snapshot(row, _AUDIT_FIELDS)
    action = "task_done" if before["status"] != "done" and row.status == "done" else (
        "task_reopened" if before["status"] == "done" and row.status != "done" else (
            "assign" if before["assignee_id"] != after["assignee_id"] else "update"))
    audit.record(db, ent=ent, company_id=row.company_id, user=user, entity="task", entity_id=row.id, action=action,
                 label=_label(row), before=before, after=after)
    await db.commit()
    return (await tasks_out(db, ent, [row]))[0]


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    await lock_firm(db, ent)
    row = await _task_or_404(db, ent, task_id)
    if row.created_by != user.id and user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only whoever created the task, a manager or the firm owner "
                                                       "can delete it")
    audit.record(db, ent=ent, company_id=row.company_id, user=user, entity="task", entity_id=row.id,
                 action="delete", label=_label(row), before=audit.snapshot(row, _AUDIT_FIELDS), after=None)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
