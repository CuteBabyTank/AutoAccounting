"""Recurring journal entries: templates on a monthly / quarterly schedule.

Nothing posts on its own: the list shows what is due, and a person presses "Post due entries", which posts each due
occurrence through the journal-entry checks (books start, inactive / locked accounts) with an audit event each.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AACompany, AAJournalEntry, AARecurringEntry
from app.models.user import User
from app.routers.accounting_books import ENTRY_FIELDS, _entry_out, entry_label, entry_problem, lines_json
from app.routers.accounting_scope import company_or_404, scope_for
from app.schemas.accounting import manila_today
from app.schemas.accounting_books import JournalEntryIn, JournalEntryOut, JournalLineIn
from app.services.accounting import audit
from app.services.accounting.books.loader import ensure_chart, touch_books
from app.services.accounting.compute.recurring import add_period, due_dates

router = APIRouter()

_FIELDS = ("name", "book", "reference", "particulars", "lines", "is_adjusting", "frequency", "day_of_month",
           "next_date", "end_date", "active")
MAX_DUE = 24   # occurrences posted per press (two years of a monthly template)


class RecurringIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    book: Literal["GJ", "CRJ", "CDJ"] = "GJ"
    reference: str = Field(default="", max_length=60)
    particulars: str = Field(default="", max_length=255)
    lines: list[JournalLineIn] = Field(min_length=2, max_length=200)
    is_adjusting: bool = False
    frequency: Literal["monthly", "quarterly"] = "monthly"
    next_date: date
    end_date: date | None = None
    day_of_month: int | None = Field(default=None, ge=1, le=31)   # default: the next date's day
    active: bool = True

    @field_validator("name", "reference", "particulars")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _check(self):
        if not self.name:
            raise ValueError("Name the recurring entry")
        if self.end_date is not None and self.end_date < self.next_date:
            raise ValueError("The end date is before the next date")
        debit = sum((l.debit for l in self.lines), Decimal("0"))
        credit = sum((l.credit for l in self.lines), Decimal("0"))
        if debit != credit:
            raise ValueError(f"Debits ({debit:,.2f}) and credits ({credit:,.2f}) must balance")
        return self


class RecurringOut(BaseModel):
    id: uuid.UUID
    name: str
    book: str
    reference: str
    particulars: str
    lines: list
    is_adjusting: bool
    frequency: str
    day_of_month: int
    next_date: date
    end_date: date | None
    active: bool
    due: list[date]
    amount: str           # total debits, for the list


class PostedOut(BaseModel):
    posted: list[JournalEntryOut]
    template: RecurringOut


def _out(row: AARecurringEntry, today: date) -> RecurringOut:
    due = due_dates(row.next_date, row.frequency, row.day_of_month, today, row.end_date, MAX_DUE) if row.active else []
    total = sum((Decimal(str(l.get("debit") or 0)) for l in row.lines or []), Decimal("0"))
    return RecurringOut(id=row.id, name=row.name, book=row.book, reference=row.reference, particulars=row.particulars,
                        lines=row.lines or [], is_adjusting=row.is_adjusting, frequency=row.frequency,
                        day_of_month=row.day_of_month, next_date=row.next_date, end_date=row.end_date,
                        active=row.active, due=due, amount=f"{total:.2f}")


def _body_entry(row: AARecurringEntry | RecurringIn, on: date) -> JournalEntryIn:
    lines = row.lines if isinstance(row, RecurringIn) else [JournalLineIn(**l) for l in row.lines]
    return JournalEntryIn(kind="manual", book=row.book, entry_date=on, reference=row.reference,
                          particulars=row.particulars or row.name, lines=lines, is_adjusting=row.is_adjusting)


async def _check_lines(db: AsyncSession, company: AACompany, body: RecurringIn, kept: set[str]) -> None:
    if company.books_start is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set the books start date on the company first")
    chart = await ensure_chart(db, company)
    problem = entry_problem(chart, _body_entry(body, max(body.next_date, company.books_start)), company.books_start,
                            kept)
    if not problem and body.next_date < company.books_start:
        problem = f"The books start on {company.books_start:%b %d, %Y}; start the schedule on or after it"
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)


async def _row_or_404(db: AsyncSession, ent: uuid.UUID, row_id: uuid.UUID, lock: bool = False) -> AARecurringEntry:
    q = select(AARecurringEntry).where(AARecurringEntry.id == row_id, AARecurringEntry.enterprise_id == ent)
    row = (await db.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recurring entry not found")
    return row


def _apply(row: AARecurringEntry, body: RecurringIn) -> None:
    row.name, row.book, row.reference, row.particulars = body.name, body.book, body.reference, body.particulars
    row.lines = lines_json(body)  # type: ignore[arg-type]  (same line fields as a JournalEntryIn)
    row.is_adjusting, row.frequency, row.active = body.is_adjusting, body.frequency, body.active
    row.next_date, row.end_date = body.next_date, body.end_date
    row.day_of_month = body.day_of_month or body.next_date.day


@router.get("/companies/{company_id}/recurring-entries", response_model=list[RecurringOut])
async def list_recurring(company_id: uuid.UUID, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    rows = (await db.execute(select(AARecurringEntry).where(
        AARecurringEntry.enterprise_id == ent, AARecurringEntry.company_id == company.id,
    ).order_by(AARecurringEntry.next_date, AARecurringEntry.name))).scalars().all()
    today = manila_today()
    return [_out(r, today) for r in rows]


@router.post("/companies/{company_id}/recurring-entries", response_model=RecurringOut,
             status_code=status.HTTP_201_CREATED)
async def create_recurring(company_id: uuid.UUID, body: RecurringIn, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    await _check_lines(db, company, body, set())
    row = AARecurringEntry(id=uuid.uuid4(), enterprise_id=ent, company_id=company.id, created_by=user.id)
    _apply(row, body)
    db.add(row)
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="recurring_entry", entity_id=row.id,
                 action="create", label=row.name, after=audit.snapshot(row, _FIELDS))
    await db.commit()
    return _out(row, manila_today())


@router.put("/recurring-entries/{entry_id}", response_model=RecurringOut)
async def update_recurring(entry_id: uuid.UUID, body: RecurringIn, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    row = await _row_or_404(db, ent, entry_id, lock=True)
    company = await company_or_404(db, ent, row.company_id)
    await _check_lines(db, company, body, {str(l.get("account_code", "")) for l in row.lines or []})
    before = audit.snapshot(row, _FIELDS)
    _apply(row, body)
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="recurring_entry", entity_id=row.id,
                 action="update", label=row.name, before=before, after=audit.snapshot(row, _FIELDS))
    await db.commit()
    return _out(row, manila_today())


@router.delete("/recurring-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recurring(entry_id: uuid.UUID, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    """Deletes the template only; entries it already posted stay in the books."""
    ent = scope_for(user)
    row = await _row_or_404(db, ent, entry_id, lock=True)
    audit.record(db, ent=ent, company_id=row.company_id, user=user, entity="recurring_entry", entity_id=row.id,
                 action="delete", label=row.name, before=audit.snapshot(row, _FIELDS), after=None)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/recurring-entries/{entry_id}/post", response_model=PostedOut)
async def post_due(entry_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Post every occurrence due by today (Manila), oldest first, then move the next date past them."""
    ent = scope_for(user)
    row = await _row_or_404(db, ent, entry_id, lock=True)   # a second press waits here, then finds nothing due
    company = await company_or_404(db, ent, row.company_id)
    today = manila_today()
    if not row.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This recurring entry is paused")
    due = due_dates(row.next_date, row.frequency, row.day_of_month, today, row.end_date, MAX_DUE)
    if not due:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing is due yet")
    if company.books_start is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set the books start date on the company first")
    chart = await ensure_chart(db, company)
    done = set((await db.execute(select(AAJournalEntry.entry_date).where(
        AAJournalEntry.enterprise_id == ent, AAJournalEntry.recurring_id == row.id,
        AAJournalEntry.deleted_at.is_(None)))).scalars().all())
    posted = []
    for on in due:
        if on in done:
            continue
        body = _body_entry(row, on)
        problem = entry_problem(chart, body, company.books_start)
        if problem:
            await db.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{on:%b %d, %Y}: {problem}")
        je = AAJournalEntry(id=uuid.uuid4(), enterprise_id=ent, company_id=company.id, kind="manual", book=body.book,
                            entry_date=on, reference=body.reference, particulars=body.particulars,
                            lines=lines_json(body), is_adjusting=body.is_adjusting, created_by=user.id,
                            recurring_id=row.id)
        db.add(je)
        audit.record(db, label=entry_label(je), ent=ent, company_id=company.id, user=user, entity="journal_entry",
                     entity_id=je.id, action="create", after=audit.snapshot(je, ENTRY_FIELDS),
                     reason=f"Recurring: {row.name}")
        posted.append(je)
    before = {"next_date": row.next_date}
    row.next_date = add_period(due[-1], row.frequency, row.day_of_month)
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="recurring_entry", entity_id=row.id,
                 action="post_due", label=row.name, before=audit.json_safe(before),
                 after={"next_date": row.next_date.isoformat(), "posted": [d.isoformat() for d in due]})
    touch_books(company)
    await db.commit()
    return PostedOut(posted=[_entry_out(j) for j in posted], template=_out(row, today))
