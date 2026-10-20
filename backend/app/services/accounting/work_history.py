"""Firm-scoped completion facts. Actors of version filings come only from matching audit evidence."""
import uuid
from collections import defaultdict
from datetime import date, datetime, time

from fastapi import HTTPException
from sqlalchemy import Date, DateTime, and_, cast, exists, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AAAuditEvent, AACompany, AAOutput, AAPeriod, AATask, AAWorkItem
from app.models.user import User
from app.routers.accounting_audit import day_bounds
from app.services.accounting.compute.work import board_window, form_label, obligations, period_text
from app.services.accounting.compute.work_history import MANILA, Completion, history_page
from app.services.accounting.work import firm_people, load_cards, person_name


def completed_tasks_query(ent: uuid.UUID, start: date, end: date):
    lo, hi = day_bounds(start, end)
    return select(AATask).where(AATask.enterprise_id == ent, AATask.status == "done",
                                AATask.completed_at >= lo, AATask.completed_at < hi)


def filed_periods_query(ent: uuid.UUID, start: date, end: date):
    lo, hi = day_bounds(start, end)
    entries = func.jsonb_each(AAPeriod.filed_forms).table_valued("key", "value").alias("filing")
    value = entries.c.value
    day = func.coalesce(cast(value.op("->>")("paid_on"), Date),
                        cast(func.timezone("Asia/Manila", cast(value.op("->>")("filed_at"), DateTime(timezone=True))), Date))
    return select(AAPeriod).where(AAPeriod.enterprise_id == ent, or_(
        and_(AAPeriod.filed_at >= lo, AAPeriod.filed_at < hi),
        exists(select(1).select_from(entries).where(day.between(start, end)).correlate(AAPeriod))))


async def load_history(db: AsyncSession, ent: uuid.UUID, start: date, end: date, today: date, *,
                       person: uuid.UUID | None = None, company: uuid.UUID | None = None,
                       kind: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    from app.routers.accounting_periods import _audit_period, company_facts
    from app.services.accounting.compute.work_history import filing_actor

    companies = {c.id: c for c in (await db.execute(select(AACompany).where(AACompany.enterprise_id == ent))).scalars()}
    active = await firm_people(db, ent)
    people = {str(p.id): person_name(p) for p in active}
    tasks = list((await db.execute(completed_tasks_query(ent, start, end))).scalars())
    board_marks = list((await db.execute(select(AAWorkItem).where(
        AAWorkItem.enterprise_id == ent, AAWorkItem.filed_on.between(start, end)))).scalars())
    periods = list((await db.execute(filed_periods_query(ent, start, end))).scalars())
    # Assignment metadata for a version filing may predate the completion window.
    period_keys = {(p.company_id, p.year, p.quarter) for p in periods}
    assigned = {(r.company_id, r.year, r.quarter, r.form): r.assignee_id for r in (await db.execute(
        select(AAWorkItem).where(AAWorkItem.enterprise_id == ent,
            tuple_(AAWorkItem.company_id, AAWorkItem.year, AAWorkItem.quarter).in_(period_keys))
    )).scalars()} if period_keys else {}
    audit_keys = {(p.company_id, _audit_period(p)) for p in periods}
    events = list((await db.execute(select(AAAuditEvent).where(
        AAAuditEvent.enterprise_id == ent, AAAuditEvent.entity == "period",
        tuple_(AAAuditEvent.company_id, AAAuditEvent.entity_id).in_(audit_keys),
        AAAuditEvent.action.in_(("filed", "form_filed")),
    ).order_by(AAAuditEvent.at, AAAuditEvent.id))).scalars()) if audit_keys else []
    evidence = defaultdict(list)
    for e in events:
        evidence[(str(e.company_id), e.entity_id)].append({
            "company_id": str(e.company_id), "entity_id": e.entity_id, "after": e.after,
            "user_id": str(e.user_id) if e.user_id else None})
    completions = []
    due_cache = {}

    def filing(company_id, year, quarter, form, at, actor, assignee, source, key):
        c = companies.get(company_id)
        if c is None:
            return
        cache_key = (company_id, year)
        if cache_key not in due_cache:
            # Each stored period needs at most its surrounding fiscal years, regardless of how late it was filed.
            due_cache[cache_key] = {(o.year, o.quarter, o.form): o for o in obligations(
                company_facts(c), date(year - 1, 1, 1), date(year + 2, 12, 31),
                {(year, q) for q in (1, 2, 3, 4)}, {year})}
        ob = due_cache[cache_key].get((year, quarter, form))
        label = f"{form_label(form)} {period_text(ob, c.fiscal_year_end_month)}" if ob else f"{form_label(form)} {year}"
        completions.append(Completion(key, "filing", label, str(c.id), c.registered_name, actor, at,
                                      str(assignee) if assignee else None, ob.due if ob else None, source))

    for t in tasks:
        c = companies.get(t.company_id)
        completions.append(Completion(str(t.id), "task", t.title, str(t.company_id) if t.company_id else None,
                                      c.registered_name if c else "", str(t.completed_by) if t.completed_by else None,
                                      t.completed_at, str(t.assignee_id) if t.assignee_id else None, t.due_date, "task"))
    for row in board_marks:
        filing(row.company_id, row.year, row.quarter, row.form,
               datetime.combine(row.filed_on, time(), tzinfo=MANILA), str(row.filed_by) if row.filed_by else None,
               row.assignee_id, "board", f"board:{row.id}")
    legacy_ids = {p.filed_output_id for p in periods if not p.filed_forms and p.filed_output_id}
    outputs = {o.id: o for o in (await db.execute(select(AAOutput).where(
        AAOutput.enterprise_id == ent, AAOutput.id.in_(legacy_ids)))).scalars()} if legacy_ids else {}
    for p in periods:
        forms = p.filed_forms or {}
        if not forms and p.filed_at and p.filed_output_id in outputs:
            o = outputs[p.filed_output_id]
            forms = {f: {"filed_at": p.filed_at.isoformat(), "output_id": str(o.id), "version": o.version}
                     for f in o.snapshot.get("forms", {})}
        for form, entry in forms.items():
            stamp = entry.get("paid_on") or entry.get("filed_at")
            if not stamp:
                continue
            at = datetime.combine(date.fromisoformat(stamp), time(), tzinfo=MANILA) if len(stamp) == 10 \
                else datetime.fromisoformat(stamp)
            if at.tzinfo is None:
                at = at.replace(tzinfo=MANILA)
            actor = filing_actor(evidence[(str(p.company_id), _audit_period(p))],
                                 str(p.company_id), _audit_period(p), form, entry)
            filing(p.company_id, p.year, p.quarter, form, at, actor,
                   assigned.get((p.company_id, p.year, p.quarter, form)), "return", f"return:{p.id}:{form}")

    open_tasks = list((await db.execute(select(AATask).where(
        AATask.enterprise_id == ent, AATask.status != "done"))).scalars())
    open_items = [{"kind": "task", "company_id": str(t.company_id) if t.company_id else None,
                   "assignee_id": str(t.assignee_id) if t.assignee_id else None} for t in open_tasks]
    cards = await load_cards(db, ent, *board_window(None, None, today), today, list(companies.values()))
    open_items += [{**c, "kind": "filing"} for c in cards if c["status"] != "filed"]
    wanted = {i for c in completions for i in (c.completed_by, c.assignee_id) if i}
    wanted |= {i["assignee_id"] for i in open_items if i.get("assignee_id")}
    # A former employee remains a valid history filter when firm records identify them. Random/foreign ids do not.
    if person and str(person) not in people and str(person) not in wanted:
        prior = (await db.execute(select(AAAuditEvent.id).where(
            AAAuditEvent.enterprise_id == ent, AAAuditEvent.user_id == person).limit(1))).first()
        if prior is None:
            raise HTTPException(404, "Person not found")
        wanted.add(str(person))
    if wanted:
        people.update({str(u.id): person_name(u) for u in (await db.execute(
            select(User).where(User.id.in_([uuid.UUID(i) for i in wanted])))).scalars()})
    return history_page(completions, open_items, people, start, end, person=str(person) if person else None,
                        company=str(company) if company else None, kind=kind, limit=limit, offset=offset)
