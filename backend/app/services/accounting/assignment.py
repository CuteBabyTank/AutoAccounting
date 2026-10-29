"""Firm-scoped assignment loader/writer. Call lock_firm before any assignment mutation.

A row lock on the firm owner serializes auto assignment with task creation, manual assignment,
handler changes and settings changes, including filings whose AAWorkItem does not exist yet.
No session/advisory locks (works with transaction pooling).
"""
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AAAuditEvent, AACompany, AATask, AAWorkItem
from app.models.user import User
from app.services.accounting import audit
from app.services.accounting.compute.assign import Member, plan_assignments
from app.services.accounting.compute.work import year_bounds
from app.services.accounting.work import firm_people, load_cards, person_name


async def lock_firm(db: AsyncSession, ent: uuid.UUID) -> None:
    await db.execute(select(User.id).where(User.id == ent).with_for_update())


def open_tasks_query(ent: uuid.UUID, start: date, end: date):
    return select(AATask).where(AATask.enterprise_id == ent, AATask.status != "done",
                                or_(AATask.due_date.is_(None), AATask.due_date.between(start, end)))


async def assignment_facts(db: AsyncSession, ent: uuid.UUID, start: date, end: date, today: date):
    companies = list((await db.execute(select(AACompany).where(AACompany.enterprise_id == ent, AACompany.archived_at.is_(None))
                                      .order_by(AACompany.id))).scalars())
    people = await firm_people(db, ent, lock=True)
    tasks = list((await db.execute(open_tasks_query(ent, start, end).order_by(AATask.created_at, AATask.id))).scalars())
    cards = await load_cards(db, ent, start, end, today, companies)
    items = [{"key": f"task:{t.id}", "company_id": str(t.company_id) if t.company_id else None,
              "assignee_id": str(t.assignee_id) if t.assignee_id else None, "status": t.status} for t in tasks]
    items += [c for c in cards if c["status"] != "filed"]
    loads = Counter(i["assignee_id"] for i in items if i.get("assignee_id"))
    # Audit diffs contain assignee_id only when it changed. This covers manual and automatic changes,
    # including older task create/update events. Auto create events are recorded before assignment.
    events = (await db.execute(select(AAAuditEvent.after).where(
        AAAuditEvent.enterprise_id == ent, AAAuditEvent.entity.in_(("task", "work_item")),
        AAAuditEvent.at >= datetime.now(timezone.utc) - timedelta(days=30),
        AAAuditEvent.after.op("?")("assignee_id"),
    ))).scalars()
    recent = Counter(str(e["assignee_id"]) for e in events if e.get("assignee_id"))
    members = [Member(str(p.id), person_name(p), str(p.enterprise_id) if p.enterprise_id else None,
                      p.role.value, p.is_active) for p in people]
    handlers = {str(c.id): str(c.handler_id) if c.handler_id else None for c in companies}
    return companies, people, tasks, cards, items, members, handlers, loads, recent


async def choose_for_task(db: AsyncSession, ent: uuid.UUID, start: date, end: date, today: date,
                          company_id: uuid.UUID | None) -> uuid.UUID | None:
    _, _, _, _, _, members, handlers, loads, recent = await assignment_facts(db, ent, start, end, today)
    chosen = plan_assignments([{"key": "new", "company_id": str(company_id) if company_id else None}],
                              members, str(ent), handlers, loads, recent)
    return uuid.UUID(chosen["new"]) if chosen else None


def assign_auto(db: AsyncSession, ent: uuid.UUID, user: User, row: AATask | AAWorkItem,
                assignee_id: uuid.UUID, *, filing: dict | None = None) -> None:
    before = audit.snapshot(row, ("assignee_id", "assigned_auto"))
    row.assignee_id, row.assigned_auto = assignee_id, True
    audit.record(db, ent=ent, company_id=row.company_id, user=user, entity="work_item" if filing else "task",
                 entity_id=f'{row.year}:{row.quarter}:{row.form}' if filing else row.id,
                 action="assign", label=f'{filing["form_label"]} {filing["period_label"]}' if filing else row.title,
                 before=before, after=audit.snapshot(row, ("assignee_id", "assigned_auto")), reason="auto-assign")


async def assign_open_items(db: AsyncSession, ent: uuid.UUID, user: User, start: date, end: date, today: date,
                            company_id: uuid.UUID | None = None) -> dict:
    """Caller holds the firm lock; returns per-person counts. Repeat calls produce no writes."""
    _, people, tasks, cards, items, members, handlers, loads, recent = await assignment_facts(
        db, ent, start, end, today)
    selected = [i for i in items if not company_id or i["company_id"] == str(company_id)]
    chosen = plan_assignments(selected, members, str(ent), handlers, loads, recent)
    counts = Counter()
    for task in tasks:
        pid = chosen.get(f"task:{task.id}")
        if pid:
            assign_auto(db, ent, user, task, uuid.UUID(pid))
            counts[pid] += 1
    lo, hi = year_bounds(start, end)
    for card in cards:
        pid = chosen.get(card["key"])
        if not pid:
            continue
        await db.execute(pg_insert(AAWorkItem).values(
            id=uuid.uuid4(), enterprise_id=ent, company_id=uuid.UUID(card["company_id"]),
            year=card["year"], quarter=card["quarter"], form=card["form"], status_override="",
        ).on_conflict_do_nothing(index_elements=["company_id", "year", "quarter", "form"]))
        row = (await db.execute(select(AAWorkItem).where(
            AAWorkItem.enterprise_id == ent, AAWorkItem.company_id == uuid.UUID(card["company_id"]),
            AAWorkItem.year.between(lo, hi), AAWorkItem.year == card["year"],
            AAWorkItem.quarter == card["quarter"], AAWorkItem.form == card["form"]).with_for_update())).scalar_one()
        if row.assignee_id is not None or row.filed_on is not None:
            continue
        assign_auto(db, ent, user, row, uuid.UUID(pid), filing=card)
        counts[pid] += 1
    return {"total": sum(counts.values()), "people": [{"id": p.id, "name": person_name(p), "count": counts[str(p.id)]}
                                                     for p in people if counts[str(p.id)]]}
