"""Firm work board: filing cards per client, assignees, board filing marks, firm settings, people."""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AACompany, AAFirmSettings, AATask, AAWorkItem
from app.models.user import User, UserRole
from app.routers.accounting_scope import (
    company_or_404, firm_settings, may_file, require_filing_rights, scope_for,
)
from app.schemas.accounting import manila_today
from app.schemas.accounting_work import (
    BoardOut, CompanySummaryOut, FirmSettingsIn, FirmSettingsOut, PersonOut, WorkCardOut, WorkItemIn,
)
from app.services.accounting import audit
from app.services.accounting.compute.specs import PDF_FORMS
from app.routers.accounting_periods import company_facts
from app.services.accounting.compute.work import (
    ALPHALIST, Obligation, filter_cards, form_label, obligations, period_text,
)
from app.services.accounting.work import company_summaries, firm_people, load_cards, person_name

router = APIRouter()

BOARD_FORMS = frozenset(PDF_FORMS) | {ALPHALIST}
OWNER_ROLES = (UserRole.ADMIN, UserRole.ENTERPRISE)
_MAX_WINDOW = timedelta(days=800)


def default_window(today: date) -> tuple[date, date]:
    return today - timedelta(days=90), today + timedelta(days=45)


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
    return FirmSettingsOut(approve_before_close=row.approve_before_close, deadline_days=row.deadline_days,
                           can_edit=user.role in OWNER_ROLES, can_file=may_file(user.role, row.approve_before_close))


@router.get("/work/settings", response_model=FirmSettingsOut)
async def get_firm_settings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return _settings_out(await firm_settings(db, scope_for(user)), user)


@router.put("/work/settings", response_model=FirmSettingsOut)
async def put_firm_settings(body: FirmSettingsIn, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    if user.role not in OWNER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the firm owner can change firm settings")
    fields = ("approve_before_close", "deadline_days")
    await db.execute(pg_insert(AAFirmSettings).values(id=uuid.uuid4(), enterprise_id=ent).on_conflict_do_nothing(
        index_elements=["enterprise_id"]))
    row = (await db.execute(select(AAFirmSettings).where(AAFirmSettings.enterprise_id == ent))).scalar_one()
    before = audit.snapshot(row, fields)
    row.approve_before_close, row.deadline_days = body.approve_before_close, body.deadline_days
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
    lo, hi = default_window(today)
    start, end = start or lo, end or hi
    if end < start or end - start > _MAX_WINDOW:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick a due window of up to two years")
    companies, people, cards = await board_data(db, ent, start, end, today)
    summaries = await company_summaries(db, ent, companies, today)
    for (cid,) in (await db.execute(select(AATask.company_id).where(
            AATask.enterprise_id == ent, AATask.status != "done", AATask.company_id.is_not(None)))).all():
        if str(cid) in summaries:
            summaries[str(cid)]["open_tasks"] = summaries[str(cid)].get("open_tasks", 0) + 1
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
    return audit.snapshot(row, ("assignee_id", "status_override", "filed_on"))


@router.put("/work/items", response_model=WorkCardOut)
async def put_work_item(body: WorkItemIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
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
        row.assignee_id = body.assignee_id
    if "status_override" in sent:
        row.status_override = body.status_override
    if "filed_on" in sent:
        row.filed_on = body.filed_on
        row.filed_by = user.id if body.filed_on else None
    ob = Obligation(body.form, body.year, body.quarter, date.today())
    after = _item_snapshot(row)
    action = ("board_filed" if after.get("filed_on") else "board_unfiled") if "filed_on" in sent and \
        before.get("filed_on") != after.get("filed_on") else "update"
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="work_item",
                 entity_id=f"{body.year}:{body.quarter}:{body.form}", action=action,
                 label=f"{form_label(body.form)} {period_text(ob, company.fiscal_year_end_month)}",
                 before=before, after=after)
    await db.commit()
    today = manila_today()
    _, _, cards = await board_data(db, ent, date(body.year - 1, 1, 1), date(body.year + 2, 12, 31), today)
    key = f"{company.id}:{body.year}:{body.quarter}:{body.form}"
    return WorkCardOut(**next(c for c in cards if c["key"] == key))
