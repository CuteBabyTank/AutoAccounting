"""Firm work board: filing cards per client, assignees, board filing marks, firm settings, people."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AACompany, AAFirmSettings, AATask, AAWorkItem
from app.models.user import User, UserRole
from app.routers.accounting_scope import (
    MANAGER_ROLES, company_or_404, firm_settings, may_file, require_filing_rights, scope_for,
)
from app.schemas.accounting import manila_today
from app.schemas.accounting_work import (
    AssignmentOut, BoardOut, CompanySummaryOut, FirmSettingsIn, FirmSettingsOut, HandlerIn, HealthBalanceOut,
    HealthBankAccountOut, HealthOut, HistoryOut,
    HealthRecoveryOut, NotificationKeysIn, NotificationOut, NotificationsOut, PersonOut, WorkCardOut, WorkItemIn,
)
from app.services.accounting import audit
from app.services.accounting.assignment import assign_open_items, lock_firm, open_tasks_query
from app.services.accounting.compute.specs import PDF_FORMS
from app.routers.accounting_periods import company_facts
from app.services.accounting.compute.work import (
    ALPHALIST, Obligation, board_window, filter_cards, form_label, obligations, period_text,
)
from app.services.accounting.work import company_summaries, firm_people, load_cards, person_name

router = APIRouter()

BOARD_FORMS = frozenset(PDF_FORMS) | {ALPHALIST}
OWNER_ROLES = (UserRole.ADMIN, UserRole.ENTERPRISE)
async def assignee_or_400(db: AsyncSession, ent: uuid.UUID, assignee_id: uuid.UUID | None) -> User | None:
    if assignee_id is None:
        return None
    person = next((p for p in await firm_people(db, ent) if p.id == assignee_id), None)
    if person is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That person isn't an active member of your firm")
    return person


def _person_out(u: User) -> PersonOut:
    return PersonOut(id=u.id, name=person_name(u), email=u.email, role=u.role.value)


@router.get("/work/people", response_model=list[PersonOut])
async def work_people(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return [_person_out(p) for p in await firm_people(db, scope_for(user))]


def _settings_out(row: AAFirmSettings, user: User) -> FirmSettingsOut:
    return FirmSettingsOut(
        auto_assign=row.auto_assign, can_auto_assign=user.role in MANAGER_ROLES,
        approve_before_close=row.approve_before_close, deadline_days=row.deadline_days,
        can_edit=user.role in OWNER_ROLES, can_file=may_file(user.role, row.approve_before_close))


@router.get("/work/settings", response_model=FirmSettingsOut)
async def get_firm_settings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return _settings_out(await firm_settings(db, scope_for(user)), user)


@router.put("/work/settings", response_model=FirmSettingsOut)
async def put_firm_settings(body: FirmSettingsIn, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only managers and the firm owner can change firm settings")
    sent = body.model_fields_set
    if user.role not in OWNER_ROLES and sent - {"auto_assign"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the firm owner can change approval and deadline settings")
    await lock_firm(db, ent)
    fields = ("approve_before_close", "deadline_days", "auto_assign")
    await db.execute(pg_insert(AAFirmSettings).values(id=uuid.uuid4(), enterprise_id=ent).on_conflict_do_nothing(
        index_elements=["enterprise_id"]))
    row = (await db.execute(select(AAFirmSettings).where(AAFirmSettings.enterprise_id == ent))).scalar_one()
    before = audit.snapshot(row, fields)
    for field in sent:
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    audit.record(db, ent=ent, company_id=None, user=user, entity="firm_settings", entity_id=ent, action="update",
                 label="Firm settings", before=before, after=audit.snapshot(row, fields))
    await db.commit()
    return _settings_out(row, user)


async def firm_companies(db: AsyncSession, ent: uuid.UUID) -> list[AACompany]:
    return list((await db.execute(select(AACompany).where(AACompany.enterprise_id == ent)
                                  .order_by(AACompany.registered_name))).scalars().all())


async def board_data(db: AsyncSession, ent: uuid.UUID, start: date, end: date, today: date):
    companies = await firm_companies(db, ent)
    people = await firm_people(db, ent)
    names = {str(p.id): person_name(p) for p in people}
    cards = await load_cards(db, ent, start, end, today, companies)
    for c in cards:
        c["assignee_name"] = names.get(c["assignee_id"] or "", "")
    return companies, people, cards


@router.get("/work/board", response_model=BoardOut)
async def work_board(
    start: date | None = None, end: date | None = None, company_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status", max_length=15),
    assignee: str | None = Query(default=None, max_length=40),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    today = manila_today()
    start, end = checked_window(start, end, today)
    if company_id:
        await company_or_404(db, ent, company_id)
    companies, people, cards = await board_data(db, ent, start, end, today)
    summaries = await company_summaries(db, ent, companies, today)
    for (cid,) in (await db.execute(select(AATask.company_id).where(
            AATask.enterprise_id == ent, AATask.status != "done", AATask.company_id.is_not(None)))).all():
        if str(cid) in summaries:
            summaries[str(cid)]["open_tasks"] = summaries[str(cid)].get("open_tasks", 0) + 1
    for task in (await db.execute(open_tasks_query(ent, start, end).where(AATask.assignee_id.is_(None)))).scalars():
        if task.company_id and str(task.company_id) in summaries:
            summary = summaries[str(task.company_id)]
            summary["unassigned_open_items"] = summary.get("unassigned_open_items", 0) + 1
    for c in cards:
        if not c["assignee_id"] and c["status"] != "filed":
            summary = summaries[c["company_id"]]
            summary["unassigned_open_items"] = summary.get("unassigned_open_items", 0) + 1
    for c in cards:
        if c["overdue"]:
            summaries[c["company_id"]]["overdue_filings"] = summaries[c["company_id"]].get("overdue_filings", 0) + 1
    shown = filter_cards(cards, company_id=str(company_id) if company_id else None, status=status_filter,
                         assignee=str(user.id) if assignee == "me" else assignee)
    return BoardOut(start=start, end=end, today=today, cards=[WorkCardOut(**c) for c in shown],
                    companies=[CompanySummaryOut(**s) for s in summaries.values()],
                    people=[_person_out(p) for p in people])


def _item_snapshot(row: AAWorkItem | None) -> dict:
    if row is None:
        return {}
    return audit.snapshot(row, ("assignee_id", "assigned_auto", "status_override", "filed_on", "filed_by"))


@router.put("/work/items", response_model=WorkCardOut)
async def put_work_item(body: WorkItemIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    await lock_firm(db, ent)
    company = await company_or_404(db, ent, body.company_id)
    if body.form not in BOARD_FORMS or (body.quarter == 0) != (body.form in ("1702RT", "1701", "1701A", ALPHALIST)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{body.form} isn't a filing on the board")
    owed = obligations(company_facts(company), date(body.year - 1, 1, 1), date(body.year + 2, 12, 31),
                       {(body.year, body.quarter)}, {body.year})
    if not any((o.form, o.year, o.quarter) == (body.form, body.year, body.quarter) for o in owed):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{form_label(body.form)} isn't filed for this period")
    sent = body.model_fields_set
    if "filed_on" in sent:
        await require_filing_rights(db, user, ent)
    if "assignee_id" in sent:
        await assignee_or_400(db, ent, body.assignee_id)
    await db.execute(pg_insert(AAWorkItem).values(
        id=uuid.uuid4(), enterprise_id=ent, company_id=company.id, year=body.year, quarter=body.quarter, form=body.form,
        status_override="").on_conflict_do_nothing(index_elements=["company_id", "year", "quarter", "form"]))
    row = (await db.execute(select(AAWorkItem).where(
        AAWorkItem.enterprise_id == ent, AAWorkItem.company_id == company.id, AAWorkItem.year == body.year,
        AAWorkItem.quarter == body.quarter, AAWorkItem.form == body.form))).scalar_one()
    before = _item_snapshot(row)
    if "assignee_id" in sent:
        if row.assignee_id != body.assignee_id:
            row.assigned_auto = False
        row.assignee_id = body.assignee_id
    if "status_override" in sent:
        row.status_override = body.status_override
    if "filed_on" in sent:
        row.filed_on = body.filed_on
        row.filed_by = user.id if body.filed_on else None
    ob = Obligation(body.form, body.year, body.quarter, date.today())
    after = _item_snapshot(row)
    action = ("board_filed" if after.get("filed_on") else "board_unfiled") if "filed_on" in sent and \
        before.get("filed_on") != after.get("filed_on") else (
            "assign" if before.get("assignee_id") != after.get("assignee_id") else "update")
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="work_item",
                 entity_id=f"{body.year}:{body.quarter}:{body.form}", action=action,
                 label=f"{form_label(body.form)} {period_text(ob, company.fiscal_year_end_month)}",
                 before=before, after=after)
    await db.flush()
    today = manila_today()
    _, _, cards = await board_data(db, ent, date(body.year - 1, 1, 1), date(body.year + 2, 12, 31), today)
    key = f"{company.id}:{body.year}:{body.quarter}:{body.form}"
    found = next((c for c in cards if c["key"] == key), None)
    if found is None:  # e.g. a 1601-C for a quarter without payroll: not owed, so nothing is stored
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{form_label(body.form)} isn't filed for this period")
    await db.commit()
    return WorkCardOut(**found)


def checked_window(start: date | None, end: date | None, today: date) -> tuple[date, date]:
    try:
        return board_window(start, end, today)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


def require_manager(user: User) -> None:
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only managers and the firm owner can assign the board")


@router.put("/work/companies/{company_id}/handler", response_model=HandlerIn)
async def set_company_handler(company_id: uuid.UUID, body: HandlerIn, user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    require_manager(user)
    await lock_firm(db, ent)
    company = await company_or_404(db, ent, company_id)
    await assignee_or_400(db, ent, body.handler_id)
    before = {"handler": company.handler_id}
    company.handler_id = body.handler_id
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="company", entity_id=company.id,
                 action="update", label=company.registered_name, before=before, after={"handler": company.handler_id})
    await db.commit()
    return HandlerIn(handler_id=company.handler_id)


@router.post("/work/auto-assign", response_model=AssignmentOut)
async def auto_assign_work(start: date | None = None, end: date | None = None, company_id: uuid.UUID | None = None,
                           user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    require_manager(user)
    today = manila_today()
    start, end = checked_window(start, end, today)
    await lock_firm(db, ent)
    if company_id:
        await company_or_404(db, ent, company_id)
    if not (await firm_settings(db, ent)).auto_assign:
        return AssignmentOut(total=0, people=[])
    result = await assign_open_items(db, ent, user, start, end, today, company_id)
    await db.commit()
    return AssignmentOut(**result)


@router.get("/work/history", response_model=HistoryOut)
async def work_history(
    start: date = Query(alias="from"), end: date = Query(alias="to"), person: uuid.UUID | None = None,
    company: uuid.UUID | None = None, kind: str | None = Query(default=None, pattern="^(task|filing)$"),
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.accounting.compute.work_history import validate_window
    from app.services.accounting.work_history import load_history

    ent = scope_for(user)
    try:
        validate_window(start, end)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    if company:
        await company_or_404(db, ent, company)
    person = user.id if user.role == UserRole.EMPLOYEE else person
    result = await load_history(db, ent, start, end, manila_today(), person=person, company=company,
                                kind=kind, limit=limit, offset=offset)
    return HistoryOut(**result)


# --- client health (QBO Client overview → Common issues) -----------------------------------------------------------

@router.get("/companies/{company_id}/health", response_model=HealthOut)
async def company_health(company_id: uuid.UUID, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    from app.models.accounting import AABankLine, AABankReconciliation, AABankStatement, AABookClose, AADocument
    from app.routers.accounting_bank import _reconciled_through
    from app.services.accounting.books import bank
    from app.services.accounting.books.loader import ensure_chart
    from app.services.accounting.books.subledger import load_subledger
    from app.services.accounting.compute import writeoff
    from app.services.accounting.compute.book_ledgers import balances
    from app.services.accounting.compute.health import (
        months_not_closed, negative_balances, over_90, review_balances, unreconciled_months,
    )

    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    today = manila_today()
    notes: list[str] = []

    reasons: dict[str, int] = {}
    flagged = (await db.execute(select(AADocument.review_reasons).where(
        AADocument.enterprise_id == ent, AADocument.company_id == company.id, AADocument.deleted_at.is_(None),
        AADocument.excluded.is_(False), AADocument.needs_review.is_(True), AADocument.reviewed.is_(False)))).scalars().all()
    for reasons_list in flagged:
        for r in reasons_list or ["other"]:
            reasons[r] = reasons.get(r, 0) + 1

    await ensure_chart(db, company)
    accounts = []
    month = func.date_trunc("month", AABankLine.line_date)
    lines = (await db.execute(select(AABankLine.account_code, month, AABankLine.match_status).where(
        AABankLine.enterprise_id == ent, AABankLine.company_id == company.id, bank.live_line()))).all()
    recs = {(c, m) for c, m in (await db.execute(select(AABankReconciliation.account_code,
                                                        AABankReconciliation.month_start).where(
        AABankReconciliation.enterprise_id == ent, AABankReconciliation.company_id == company.id,
        AABankReconciliation.voided_at.is_(None)))).all()}
    line_months = {(c, m.date() if hasattr(m, "date") else m) for c, m, _ in lines if c}
    unrec = unreconciled_months(line_months, recs, today)
    for a in await bank.bank_accounts(db, company.id):
        accounts.append(HealthBankAccountOut(
            code=a.code, name=a.name, reconciled_through=await _reconciled_through(db, company.id, a.code),
            unreconciled_months=[m for c, m in unrec if c == a.code],
            unmatched_lines=sum(1 for c, _, s in lines if c == a.code and s in bank.OPEN_STATUSES)))
    unassigned = (await db.execute(select(func.count(AABankStatement.id)).where(
        AABankStatement.enterprise_id == ent, AABankStatement.company_id == company.id,
        AABankStatement.account_code == "", bank.live_statement()))).scalar() or 0
    unmatched = sum(1 for _, _, s in lines if s in bank.OPEN_STATUSES)

    closed = set((await db.execute(select(AABookClose.month_start).where(
        AABookClose.enterprise_id == ent, AABookClose.company_id == company.id, AABookClose.kind == "month",
        AABookClose.voided_at.is_(None)))).scalars().all())
    not_closed = months_not_closed(company.books_start, closed, today)

    sub = await load_subledger(db, company, today)
    ar90 = over_90([i for i in sub.items if i.doc.kind == "ar"])
    ap90 = over_90([i for i in sub.items if i.doc.kind == "ap"])
    pending = [i for i in sub.cwt if i.status == "pending"]
    by_id = {d.id: d for d in sub.docs}
    recoveries = [HealthRecoveryOut(document_id=i, doc_number=by_id[i].doc_number, contact_name=by_id[i].contact_name,
                                    amount=a, opening=by_id[i].opening)
                  for i, a in writeoff.recovered([p for p in sub.payments if p.on <= today]).items() if i in by_id]

    negative: list[dict] = []
    parked: list[dict] = []
    if company.books_start is not None and company.books_start <= today:
        try:
            entries = await bank.book_entries(db, company, today)
        except (ValueError, KeyError) as exc:
            entries = None
            notes.append(f"The books couldn't be built to check balances: {exc}")
        if entries is not None:
            chart = await ensure_chart(db, company)
            bal = balances(entries, today)
            negative, parked = negative_balances(bal, chart), review_balances(bal, chart)
    elif company.books_start is None:
        notes.append("Books are off for this company, so balances and months not closed aren't checked.")
    else:
        notes.append(f"The books start on {company.books_start:%d %B %Y}, so balances aren't checked yet.")
    await db.commit()  # load_subledger may have synced contacts

    issues = sum(1 for n in (sum(reasons.values()), unmatched, len(unrec), unassigned, len(pending), len(not_closed),
                             ar90[0], ap90[0], len(negative), len(parked), len(recoveries)) if n)
    return HealthOut(
        company_id=company.id, company_name=company.registered_name, as_of=today, reviews_by_reason=reasons,
        open_reviews=len(flagged), bank_accounts=accounts, unassigned_statements=unassigned,
        unmatched_bank_lines=unmatched, cwt_pending_count=len(pending),
        cwt_pending_amount=sum((i.amount for i in pending), Decimal("0.00")), months_not_closed=not_closed,
        books_on=company.books_start is not None, ar_over_90_count=ar90[0], ar_over_90_amount=ar90[1],
        ap_over_90_count=ap90[0], ap_over_90_amount=ap90[1],
        negative_balances=[HealthBalanceOut(**r) for r in negative],
        review_balances=[HealthBalanceOut(**r) for r in parked], writeoff_recoveries=recoveries, issues=issues,
        notes=notes,
    )


# --- notifications (derived on read; read / dismissed persisted per person) -----------------------------------------

async def _recurring_due(db: AsyncSession, ent: uuid.UUID, names: dict[str, str], fyes: dict[str, int],
                         today: date) -> list[dict]:
    """Per company of the board: how many recurring entries are due to post by today, the earliest date and the
    fiscal year it falls in (the notification opens that year's books)."""
    from app.models.accounting import AARecurringEntry
    from app.services.accounting.periods import period_for
    from app.routers.accounting_recurring import MAX_DUE
    from app.services.accounting.compute.recurring import due_dates

    by_company: dict[str, list[date]] = {}
    for row in (await db.execute(select(AARecurringEntry).where(
            AARecurringEntry.enterprise_id == ent, AARecurringEntry.active.is_(True),
            AARecurringEntry.next_date <= today))).scalars():
        cid = str(row.company_id)
        if cid not in names:
            continue
        due = due_dates(row.next_date, row.frequency, row.day_of_month, today, row.end_date, MAX_DUE)
        by_company.setdefault(cid, []).extend(due)
    return [{"company_id": cid, "company_name": names[cid], "count": len(d), "oldest": min(d),
             "fiscal_year": period_for(min(d), fyes.get(cid, 12)).fiscal_year}
            for cid, d in by_company.items() if d]


async def _notifications(db: AsyncSession, user: User, ent: uuid.UUID):
    from app.models.accounting import AANotificationState
    from app.services.accounting.compute.notifications import build
    from app.services.accounting.work import cwt_pending

    today = manila_today()
    settings_row = await firm_settings(db, ent)
    days = settings_row.deadline_days
    companies, _, cards = await board_data(db, ent, today - timedelta(days=60), today + timedelta(days=days), today)
    summaries = await company_summaries(db, ent, companies, today)
    cwt = await cwt_pending(db, ent, companies, today)
    names = {str(c.id): c.registered_name for c in companies}
    tasks = [{"id": str(t.id), "title": t.title, "assignee_id": str(t.assignee_id) if t.assignee_id else None,
              "due_date": t.due_date, "status": t.status, "company_id": str(t.company_id) if t.company_id else None,
              "company_name": names.get(str(t.company_id), "")}
             for t in (await db.execute(select(AATask).where(
                 AATask.enterprise_id == ent, AATask.assignee_id == user.id, AATask.status != "done"))).scalars()]
    fyes = {str(c.id): c.fiscal_year_end_month for c in companies}
    recurring = await _recurring_due(db, ent, names, fyes, today)
    items = build(user_id=str(user.id), cards=cards, summaries=summaries, cwt=cwt, tasks=tasks, today=today, days=days,
                  recurring=recurring)
    states = {s.key: s for s in (await db.execute(select(AANotificationState).where(
        AANotificationState.enterprise_id == ent, AANotificationState.user_id == user.id)
        .execution_options(populate_existing=True))).scalars()}
    return items, states


@router.get("/notifications", response_model=NotificationsOut)
async def list_notifications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    items, states = await _notifications(db, user, ent)
    out = []
    for n in items:
        state = states.get(n.key)
        if state is not None and state.dismissed_at is not None:
            continue
        out.append(NotificationOut(key=n.key, kind=n.kind, title=n.title, detail=n.detail,
                                   company_id=uuid.UUID(n.company_id) if n.company_id else None, due_date=n.due_date,
                                   severity=n.severity, read=state is not None and state.read_at is not None,
                                   fiscal_year=n.fiscal_year))
    return NotificationsOut(items=out, unread=sum(1 for n in out if not n.read))


async def _mark(db: AsyncSession, user: User, body: NotificationKeysIn, dismiss: bool) -> NotificationsOut:
    from datetime import datetime, timezone

    from app.models.accounting import AANotificationState

    ent = scope_for(user)
    keys = set(body.keys)
    if body.all:
        items, _ = await _notifications(db, user, ent)
        keys |= {n.key for n in items}
    now = datetime.now(timezone.utc)
    for key in sorted(k[:200] for k in keys if k):
        values = {"read_at": now, **({"dismissed_at": now} if dismiss else {})}
        await db.execute(pg_insert(AANotificationState).values(
            id=uuid.uuid4(), enterprise_id=ent, user_id=user.id, key=key, **values,
        ).on_conflict_do_update(index_elements=["user_id", "key"], set_=values))
    await db.commit()
    return await list_notifications(user, db)


@router.post("/notifications/read", response_model=NotificationsOut)
async def read_notifications(body: NotificationKeysIn, user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    return await _mark(db, user, body, dismiss=False)


@router.post("/notifications/dismiss", response_model=NotificationsOut)
async def dismiss_notifications(body: NotificationKeysIn, user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    return await _mark(db, user, body, dismiss=True)
