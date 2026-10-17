"""Reclassify: move the postings behind an account (documents, typed journal entries) to another account or ATC.

Only the classification changes (a document's account override / ATC, a journal entry's line accounts); the books
engine recomputes, so a change to a closed month posts as a correcting entry on the first open day.
"""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AACompany, AADocument, AAJournalEntry
from app.models.user import User
from app.routers import accounting_periods
from app.routers.accounting_scope import company_or_404, scope_for
from app.schemas.accounting import _atc_code, manila_today
from app.services.accounting import audit
from app.services.accounting.books.loader import active_closes, touch_books
from app.services.accounting.compute import reclassify as rc
from app.services.accounting.compute.reports import check_window
from app.services.accounting.report_export import jsonable
from app.services.accounting.reports import Books, load_books

router = APIRouter()

_CODE = r"^\d{4,10}$"
_DOC_FIELDS = ("gl_account_code", "ewt_atc")


class ReclassifyIn(BaseModel):
    start: date
    end: date
    account: str = Field(pattern=_CODE)
    atc: str = Field(default="", max_length=10)
    keys: list[str] = Field(min_length=1, max_length=rc.MAX_ITEMS)
    to_account: str = Field(default="", pattern=r"^(\d{4,10})?$")
    to_atc: str = Field(default="", max_length=10)
    reason: str = Field(default="", max_length=500)

    @field_validator("to_atc")
    @classmethod
    def _atc(cls, v: str) -> str:
        return _atc_code(v)

    @field_validator("keys")
    @classmethod
    def _keys(cls, v: list[str]) -> list[str]:
        return [k[:120] for k in v]


async def _books(db: AsyncSession, company: AACompany, start: date, end: date) -> Books:
    try:
        check_window(start, end, manila_today(), company.fiscal_year_end_month)
        books = await load_books(db, company, end)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    if books.entries is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The books can't be built: {books.error}. Open Reports → "
                                                      "Invalid journal transactions to see what to fix.")
    return books


def _uuids(values) -> list[uuid.UUID]:
    out = []
    for v in values:
        try:
            out.append(uuid.UUID(v))
        except (ValueError, TypeError):
            continue
    return out


async def _candidates(db: AsyncSession, company: AACompany, books: Books, account: str, start: date, end: date,
                      atc: str) -> tuple[list[rc.Candidate], dict, dict, date | None]:
    """The rows plus the documents / journal entries behind them (by id) and the last closed day."""
    doc_ids, je_ids = set(), set()
    for e in books.entries or []:
        if start <= e.date <= end and any(l.account == account for l in e.lines):
            parts = e.id.removeprefix("fix:").split(":")
            if parts[0] == "doc" and len(parts) >= 2:
                doc_ids.add(parts[1])
            elif parts[0] == "je" and len(parts) >= 2:
                je_ids.add(parts[1])
    docs = list((await db.execute(select(AADocument).where(
        AADocument.enterprise_id == company.enterprise_id, AADocument.company_id == company.id,
        AADocument.id.in_(_uuids(doc_ids)), AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
    ))).scalars().all()) if doc_ids else []
    jes = list((await db.execute(select(AAJournalEntry).where(
        AAJournalEntry.enterprise_id == company.enterprise_id, AAJournalEntry.company_id == company.id,
        AAJournalEntry.id.in_(_uuids(je_ids)), AAJournalEntry.deleted_at.is_(None),
    ))).scalars().all()) if je_ids else []
    atc_rules = await accounting_periods.supplier_atc_rules(db, company.id)
    gl_rules = await accounting_periods.supplier_gl_rules(db, company.id)
    doc_info = {str(d.id): (rc.document_main_account(accounting_periods.doc_line(d, atc_rules, gl_rules), books.chart),
                            accounting_periods.effective_document_atc(d, company, atc_rules)) for d in docs}
    closes = await active_closes(db, company.id)
    last_closed = closes[-1].month_end if closes else None
    rows = rc.candidates(books.entries or [], books.chart, account, start, end, doc_info,
                         {str(j.id): j.kind for j in jes}, last_closed, atc)
    return rows, {str(d.id): d for d in docs}, {str(j.id): j for j in jes}, last_closed


async def _company(db: AsyncSession, user: User, company_id: uuid.UUID) -> AACompany:
    company = await company_or_404(db, scope_for(user), company_id)
    if company.books_start is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set a Books start on the company to reclassify postings")
    return company


@router.get("/companies/{company_id}/reclassify")
async def reclassify_candidates(company_id: uuid.UUID, start: date = Query(...), end: date = Query(...),
                                account: str = Query(..., pattern=_CODE), atc: str = Query("", max_length=10),
                                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The postings on ``account`` dated in [start, end], each with whether it can move and why not."""
    company = await _company(db, user, company_id)
    books = await _books(db, company, start, end)
    rows, _, _, last_closed = await _candidates(db, company, books, account, start, end, atc)
    await db.commit()
    return JSONResponse(jsonable({
        "account": account, "account_name": books.chart.name(account), "last_closed": last_closed,
        "candidates": [vars(r) for r in rows],
    }))


async def _plan(db: AsyncSession, company: AACompany, body: ReclassifyIn):
    if not body.to_account and not body.to_atc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose an account or an ATC to move to")
    books = await _books(db, company, body.start, body.end)
    rows, docs, jes, last_closed = await _candidates(db, company, books, body.account, body.start, body.end, body.atc)
    chosen, skipped = rc.apply_selection(rows, body.keys)
    if not chosen:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "None of the selected items can be moved")
    if body.to_atc and not body.to_account and not any(c.kind == "document" for c in chosen):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only documents carry an ATC; choose an account to move to")
    problem = rc.check_target(books.chart, body.account, body.to_account, {c.kind for c in chosen})
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    first_open = last_closed + timedelta(days=1) if last_closed else None
    out = rc.preview(chosen, books.chart, body.to_account, body.to_atc, first_open)
    out["skipped"] = skipped
    return chosen, docs, jes, out


@router.post("/companies/{company_id}/reclassify/preview")
async def reclassify_preview(company_id: uuid.UUID, body: ReclassifyIn, user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    company = await _company(db, user, company_id)
    _, _, _, out = await _plan(db, company, body)
    await db.commit()
    return JSONResponse(jsonable(out))


@router.post("/companies/{company_id}/reclassify")
async def reclassify_apply(company_id: uuid.UUID, body: ReclassifyIn, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    """Move the selected items; each one is audited with the reason."""
    if len(body.reason.strip()) < 3:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Say why these are being reclassified")
    company = await _company(db, user, company_id)
    chosen, docs, jes, out = await _plan(db, company, body)
    ent = company.enterprise_id
    reason = body.reason.strip()
    for c in chosen:
        if c.kind == "document":
            doc = docs[c.source_id]
            before = audit.snapshot(doc, _DOC_FIELDS)
            if body.to_account:
                doc.gl_account_code = body.to_account
            if body.to_atc and doc.category in ("purchases", "expenses"):
                doc.ewt_atc = body.to_atc
            audit.record(db, label=audit.document_label(doc), ent=ent, company_id=company.id, user=user,
                         entity="document", entity_id=doc.id, action="reclassify", before=before,
                         after=audit.snapshot(doc, _DOC_FIELDS), reason=reason)
        elif c.kind == "journal_entry" and body.to_account:
            je = jes[c.source_id]
            before = audit.snapshot(je, ("lines",))
            je.lines = [dict(x, account_code=body.to_account) if str(x.get("account_code")) == body.account else x
                        for x in je.lines or []]
            audit.record(db, label=" · ".join(p for p in (je.entry_date.isoformat(), je.reference, je.particulars)
                                              if p),
                         ent=ent, company_id=company.id, user=user, entity="journal_entry", entity_id=je.id,
                         action="reclassify", before=before, after=audit.snapshot(je, ("lines",)), reason=reason)
    touch_books(company)
    await db.commit()
    out["moved"] = len(chosen)
    return JSONResponse(jsonable(out))
