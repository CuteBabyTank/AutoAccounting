"""Write off customer invoices in bulk: pick old / small open A/R items and post one journal entry for them.

Dr the chosen expense account (bad debts) / Cr A/R per invoice at its open balance. The entry carries
``writeoff_items`` so the subledger closes the invoices; deleting the entry reopens them. Managers and owners only,
the date must be in an open month, and the account must be an active, unlocked expense account.
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AACompany, AAJournalEntry
from app.models.user import User
from app.routers.accounting_books import ENTRY_FIELDS, _entry_out, entry_label
from app.routers.accounting_contacts import _item_out
from app.routers.accounting_scope import MANAGER_ROLES, company_or_404, scope_for
from app.schemas.accounting import manila_today
from app.schemas.accounting_books import JournalEntryOut
from app.schemas.accounting_contacts import OpenItemOut
from app.services.accounting import audit
from app.services.accounting.assignment import lock_firm
from app.services.accounting.books.chart import locked_message
from app.services.accounting.books.loader import active_closes, ensure_chart, touch_books
from app.services.accounting.books.subledger import load_subledger
from app.services.accounting.compute import writeoff as wo
from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.compute.reports import check_window

router = APIRouter()


class CandidatesOut(BaseModel):
    as_of: date
    items: list[OpenItemOut]
    total: Decimal
    last_closed: date | None
    books_start: date | None


class WriteOffIn(BaseModel):
    entry_date: date
    item_ids: list[str] = Field(min_length=1, max_length=wo.MAX_ITEMS)
    account: str = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Say why these invoices are written off")
        return v


class WriteOffOut(BaseModel):
    entry: JournalEntryOut
    count: int
    total: Decimal


def _check_date(company: AACompany, on: date) -> None:
    try:
        check_window(None, on, manila_today(), company.fiscal_year_end_month)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


@router.get("/companies/{company_id}/writeoffs/candidates", response_model=CandidatesOut)
async def writeoff_candidates(company_id: uuid.UUID, as_of: date | None = None,
                              min_days: int = Query(90, ge=0, le=36500),
                              max_balance: Decimal | None = Query(None, ge=0, max_digits=14, decimal_places=2),
                              user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    as_of = as_of or manila_today()
    _check_date(company, as_of)
    sub = await load_subledger(db, company, as_of)
    closes = await active_closes(db, company.id)
    await db.commit()  # contacts may have been synced
    items = wo.candidates(sub.items, min_days, max_balance)
    return CandidatesOut(as_of=as_of, items=[_item_out(i) for i in items],
                         total=c2(sum((i.open for i in items), ZERO)),
                         last_closed=closes[-1].month_end if closes else None, books_start=company.books_start)


@router.post("/companies/{company_id}/writeoffs", response_model=WriteOffOut, status_code=status.HTTP_201_CREATED)
async def write_off(company_id: uuid.UUID, body: WriteOffIn, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners and managers can write off invoices")
    ent = scope_for(user)
    await lock_firm(db, ent)  # payment edits and month close use this lock too
    company = await company_or_404(db, ent, company_id)
    # one write-off per company at a time: two at once would both see the same invoices open
    await db.execute(select(AACompany.id).where(AACompany.id == company.id, AACompany.enterprise_id == ent)
                     .with_for_update())
    if company.books_start is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set the books start date on the company first")
    on = body.entry_date
    if on < company.books_start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"The books start on {company.books_start:%b %d, %Y}; date the write-off on or after it")
    if on > manila_today():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A write-off can't be dated in the future")
    closes = await active_closes(db, company.id)
    if closes and on <= closes[-1].month_end:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{closes[-1].month_end:%B %Y} is closed: date the "
                                                         "write-off in an open month")
    chart = await ensure_chart(db, company)
    account = chart.get(body.account)
    if account is None or not account.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Account {body.account} isn't an active account in the chart")
    if account.type != "expense":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Write invoices off to an expense account (e.g. bad debts)")
    ar_code = chart.code("ar")
    locked = locked_message(chart, [body.account, ar_code])
    if locked:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, locked)
    wanted = list(dict.fromkeys(body.item_ids))
    sub = await load_subledger(db, company, on)
    open_by_id = {i.doc.id: i for i in sub.items if i.doc.kind == "ar" and i.open > 0}
    missing = [i for i in wanted if i not in open_by_id]
    if missing:
        names = {d.id: d.doc_number or d.id for d in sub.docs}
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not open customer invoices on "
                                                         f"{on:%b %d, %Y}: {', '.join(names.get(i, i) for i in missing)}")
    chosen = [open_by_id[i] for i in wanted]
    today = manila_today()
    later_pays = sub.payments if on >= today else (await load_subledger(db, company, today)).payments
    later = wo.paid_after(later_pays, set(wanted), on)
    if later:
        names = {d.id: d.doc_number or d.id for d in sub.docs}
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Paid or written off after {on:%b %d, %Y}: "
                                                         f"{', '.join(names.get(i, i) for i in wanted if i in later)}. "
                                                         "Date the write-off after the last payment")
    total = c2(sum((i.open for i in chosen), ZERO))
    je = AAJournalEntry(
        id=uuid.uuid4(), enterprise_id=ent, company_id=company.id, kind="manual", book="GJ", entry_date=on,
        reference="Write-off", particulars=f"Write-off of {len(chosen)} invoice{'s' if len(chosen) != 1 else ''}",
        lines=wo.entry_lines(chosen, body.account, ar_code), created_by=user.id,
        writeoff_items=[{"id": i.doc.id, "amount": str(c2(i.open)), "doc_number": i.doc.doc_number,
                         "kind": "opening" if i.doc.opening else "document"} for i in chosen],
    )
    db.add(je)
    audit.record(db, label=entry_label(je), ent=ent, company_id=company.id, user=user, entity="journal_entry",
                 entity_id=je.id, action="writeoff", after=audit.snapshot(je, ENTRY_FIELDS + ("writeoff_items",)),
                 reason=body.reason)
    for i in chosen:
        audit.record(db, label=" · ".join(p for p in (i.doc.doc_number, i.doc.contact_name) if p), ent=ent,
                     company_id=company.id, user=user, entity="opening_item" if i.doc.opening else "document",
                     entity_id=i.doc.id, action="written_off",
                     after={"amount": str(c2(i.open)), "account": body.account, "entry_date": on.isoformat()},
                     reason=body.reason)
    touch_books(company)
    await db.commit()
    return WriteOffOut(entry=_entry_out(je), count=len(chosen), total=total)
