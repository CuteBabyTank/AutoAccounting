"""Books of accounts: chart of accounts, typed journal entries and document payment links."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AAAccount, AACompany, AADocument, AAJournalEntry
from app.models.user import User
from app.routers.accounting_scope import MANAGER_ROLES, company_or_404, scope_for
from app.schemas.accounting_books import (
    AccountIn, AccountOut, AccountPatch, BookMonthOut, BooksYearOut, CloseMonthIn, DocRefOut, JournalEntryIn,
    JournalEntryOut, PaymentLinksOut, ReopenMonthIn,
)
from app.services.accounting import audit
from app.services.accounting.books import bank
from app.services.accounting.books.closing import (
    CloseError, bank_block_message, bind_deadline, bind_year, close_month, reopen_month, stored_file, year_status,
)
from app.services.accounting.books.links import doc_ref, invoice_docs, receipt_docs
from app.services.accounting.books.loader import ensure_chart, touch_books
from app.services.accounting.books.receipts import candidates_for
from app.services.accounting.compute.depreciation import fiscal_year_window

router = APIRouter()

_ACCOUNT_FIELDS = ("code", "name", "type", "parent_code", "active", "bank_account_no")
_ENTRY_FIELDS = ("kind", "book", "entry_date", "reference", "particulars", "lines", "is_adjusting")


def _require_manager(user: User) -> None:
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners and managers can change the chart of accounts")


async def _account_or_404(db: AsyncSession, ent: uuid.UUID, account_id: uuid.UUID) -> AAAccount:
    row = (await db.execute(select(AAAccount).where(AAAccount.id == account_id, AAAccount.enterprise_id == ent))
           ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return row


@router.get("/companies/{company_id}/accounts", response_model=list[AccountOut])
async def list_accounts(company_id: uuid.UUID, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    company = await company_or_404(db, scope_for(user), company_id)
    await ensure_chart(db, company)
    await db.commit()
    return (await db.execute(select(AAAccount).where(AAAccount.company_id == company.id)
                             .order_by(AAAccount.code))).scalars().all()


@router.post("/companies/{company_id}/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def add_account(company_id: uuid.UUID, body: AccountIn, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    _require_manager(user)
    company = await company_or_404(db, ent, company_id)
    await ensure_chart(db, company)
    parent = (await db.execute(select(AAAccount).where(
        AAAccount.company_id == company.id, AAAccount.code == body.parent_code))).scalar_one_or_none()
    if parent is None or not parent.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Account {body.parent_code} isn't an active account")
    row = AAAccount(id=uuid.uuid4(), enterprise_id=ent, company_id=company.id, code=body.code,
                    name=body.name.strip(), type=parent.type, contra=parent.contra, parent_code=parent.code,
                    active=True)
    db.add(row)
    touch_books(company)
    try:
        await db.flush()  # a code clash surfaces here, before the event is added
        audit.record(db, label=f"{row.code} {row.name}",
                     ent=ent, company_id=company.id, user=user, entity="account", entity_id=row.id,
                     action="create", after=audit.snapshot(row, _ACCOUNT_FIELDS))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Account code {body.code} is already in the chart")
    return row


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def patch_account(account_id: uuid.UUID, body: AccountPatch, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    _require_manager(user)
    row = await _account_or_404(db, ent, account_id)
    company = await company_or_404(db, ent, row.company_id)
    before = audit.snapshot(row, _ACCOUNT_FIELDS)
    if body.name is not None:
        row.name = body.name.strip()
    if body.active is False and row.active:
        if row.system_key:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Posting uses this account; it can be renamed but not "
                                                             "deactivated")
        used = (await db.execute(select(AAJournalEntry.id).where(
            AAJournalEntry.company_id == company.id, AAJournalEntry.deleted_at.is_(None),
            AAJournalEntry.lines.contains([{"account_code": row.code}])).limit(1))).first() or \
            (await db.execute(select(AADocument.id).where(
                AADocument.company_id == company.id, AADocument.deleted_at.is_(None),
                AADocument.gl_account_code == row.code).limit(1))).first()
        if used:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account is used by journal entries or documents; "
                                                             "move them to another account first")
    if body.active is not None:
        row.active = body.active
    if body.bank_account_no is not None:
        if row.type != "asset":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only asset accounts can carry a bank account number")
        row.bank_account_no = body.bank_account_no.strip()
    audit.record(db, label=f"{row.code} {row.name}",
                 ent=ent, company_id=company.id, user=user, entity="account", entity_id=row.id,
                 action="update", before=before, after=audit.snapshot(row, _ACCOUNT_FIELDS))
    touch_books(company)
    await db.commit()
    return row


def _entry_label(row: AAJournalEntry) -> str:
    return " · ".join(p for p in (row.entry_date.isoformat() if row.entry_date else "", row.reference,
                                  row.particulars) if p)


def _entry_out(row: AAJournalEntry) -> JournalEntryOut:
    return JournalEntryOut(id=row.id, kind=row.kind, book=row.book, entry_date=row.entry_date,
                           reference=row.reference, particulars=row.particulars, lines=row.lines,
                           is_adjusting=bool(row.is_adjusting), created_at=row.created_at)


async def _check_entry(db: AsyncSession, company: AACompany, body: JournalEntryIn,
                       entry_id: uuid.UUID | None = None) -> None:
    if company.books_start is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set the books start date on the company first")
    if body.kind == "opening":
        clash = (await db.execute(select(AAJournalEntry.id).where(
            AAJournalEntry.company_id == company.id, AAJournalEntry.kind == "opening",
            AAJournalEntry.deleted_at.is_(None), AAJournalEntry.id != (entry_id or uuid.uuid4())))).first()
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, "This company already has opening balances; edit them")
    elif body.entry_date < company.books_start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"The books start on {company.books_start:%b %d, %Y}; date the entry on or after it")
    chart = await ensure_chart(db, company)
    bad = sorted({l.account_code for l in body.lines
                  if chart.get(l.account_code) is None or not chart.get(l.account_code).active})
    if bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Not active accounts in the chart: {', '.join(bad)}")


def _lines_json(body: JournalEntryIn) -> list[dict]:
    return [{"account_code": l.account_code, "debit": str(l.debit), "credit": str(l.credit),
             "party_name": l.party_name.strip(), "party_tin": l.party_tin.strip()} for l in body.lines]


@router.get("/companies/{company_id}/journal-entries", response_model=list[JournalEntryOut])
async def list_journal_entries(company_id: uuid.UUID, year: int = Query(ge=2000, le=2100),
                               user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    company = await company_or_404(db, scope_for(user), company_id)
    start, end = fiscal_year_window(year, company.fiscal_year_end_month)
    rows = (await db.execute(select(AAJournalEntry).where(
        AAJournalEntry.company_id == company.id, AAJournalEntry.deleted_at.is_(None),
        AAJournalEntry.entry_date >= start, AAJournalEntry.entry_date <= end,
    ).order_by(AAJournalEntry.entry_date, AAJournalEntry.created_at))).scalars().all()
    return [_entry_out(r) for r in rows]


@router.post("/companies/{company_id}/journal-entries", response_model=JournalEntryOut,
             status_code=status.HTTP_201_CREATED)
async def create_journal_entry(company_id: uuid.UUID, body: JournalEntryIn, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    await _check_entry(db, company, body)
    row = AAJournalEntry(id=uuid.uuid4(), enterprise_id=ent, company_id=company.id, kind=body.kind, book=body.book,
                         entry_date=company.books_start if body.kind == "opening" else body.entry_date,
                         reference=body.reference, particulars=body.particulars or (
                             "Opening balances" if body.kind == "opening" else ""),
                         lines=_lines_json(body), is_adjusting=body.is_adjusting, created_by=user.id)
    db.add(row)
    audit.record(db, label=_entry_label(row),
                 ent=ent, company_id=company.id, user=user, entity="journal_entry", entity_id=row.id,
                 action="create", after=audit.snapshot(row, _ENTRY_FIELDS))
    touch_books(company)
    await db.commit()
    return _entry_out(row)


async def _entry_or_404(db: AsyncSession, ent: uuid.UUID, entry_id: uuid.UUID) -> AAJournalEntry:
    row = (await db.execute(select(AAJournalEntry).where(
        AAJournalEntry.id == entry_id, AAJournalEntry.enterprise_id == ent, AAJournalEntry.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    return row


@router.put("/journal-entries/{entry_id}", response_model=JournalEntryOut)
async def update_journal_entry(entry_id: uuid.UUID, body: JournalEntryIn, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    row = await _entry_or_404(db, ent, entry_id)
    company = await company_or_404(db, ent, row.company_id)
    await _check_entry(db, company, body, entry_id=row.id)
    before = audit.snapshot(row, _ENTRY_FIELDS)
    row.kind, row.book, row.reference, row.particulars = body.kind, body.book, body.reference, body.particulars
    row.entry_date = company.books_start if body.kind == "opening" else body.entry_date
    row.lines = _lines_json(body)
    row.is_adjusting = body.is_adjusting
    audit.record(db, label=_entry_label(row),
                 ent=ent, company_id=company.id, user=user, entity="journal_entry", entity_id=row.id,
                 action="update", before=before, after=audit.snapshot(row, _ENTRY_FIELDS))
    touch_books(company)
    await db.commit()
    return _entry_out(row)


@router.delete("/journal-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_journal_entry(entry_id: uuid.UUID, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    row = await _entry_or_404(db, ent, entry_id)
    company = await company_or_404(db, ent, row.company_id)
    row.deleted_at = datetime.now(timezone.utc)
    audit.record(db, label=_entry_label(row),
                 ent=ent, company_id=company.id, user=user, entity="journal_entry", entity_id=row.id,
                 action="delete", before=audit.snapshot(row, _ENTRY_FIELDS), after=None)
    touch_books(company)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _ref(doc: AADocument) -> DocRefOut:
    name = doc.buyer_name if doc.client_role == "seller" else doc.seller_name
    return DocRefOut(id=doc.id, doc_number=doc.doc_number, doc_date=doc.doc_date, counterparty=name,
                     gross_amount=doc.gross_amount)


@router.get("/documents/{doc_id}/payments", response_model=PaymentLinksOut)
async def document_payments(doc_id: uuid.UUID, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    doc = (await db.execute(select(AADocument).where(
        AADocument.id == doc_id, AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None)))
           ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    docs = (await db.execute(select(AADocument).where(
        AADocument.company_id == doc.company_id, AADocument.deleted_at.is_(None)))).scalars().all()
    by_id = {d.id: d for d in docs}
    linked = by_id.get(doc.settles_document_id) if doc.settles_document_id else None
    candidates: list[AADocument] = []
    if doc in receipt_docs(docs):
        taken = {str(d.settles_document_id) for d in docs if d.settles_document_id and d.id != doc.id}
        ids = set(candidates_for(doc_ref(doc), [doc_ref(i) for i in invoice_docs(docs)], taken))
        candidates = [d for d in docs if str(d.id) in ids]
    paid_by = [d for d in docs if d.settles_document_id == doc.id]
    return PaymentLinksOut(linked_invoice=_ref(linked) if linked else None,
                           candidates=[_ref(d) for d in candidates], paid_by=[_ref(d) for d in paid_by])


# --- Closing months, loose-leaf PDFs and binding -------------------------------------------------------------------

def _month(row) -> dict:
    return {"fiscal_year": row.fiscal_year, "month_start": row.month_start.isoformat(),
            "month_end": row.month_end.isoformat()}


async def _books_year(db: AsyncSession, company: AACompany, fiscal_year: int) -> BooksYearOut:
    months, bound = await year_status(db, company, fiscal_year)
    return BooksYearOut(
        fiscal_year=fiscal_year,
        months=[BookMonthOut(start=m.start, end=m.end, status=m.status, pages=m.pages, books=list(m.files),
                             closed_at=m.closed_at) for m in months],
        bound=bound is not None, bound_books=list(bound.files) if bound else [],
        bind_by=bind_deadline(fiscal_year, company.fiscal_year_end_month),
    )


@router.get("/companies/{company_id}/books/{fiscal_year}", response_model=BooksYearOut)
async def books_year(company_id: uuid.UUID, fiscal_year: int, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    company = await company_or_404(db, scope_for(user), company_id)
    return await _books_year(db, company, fiscal_year)


@router.post("/companies/{company_id}/books/close", response_model=BooksYearOut)
async def close_books_month(body: CloseMonthIn, company_id: uuid.UUID, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    _require_manager(user)
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    month_start, month_end = bank.month_bounds(body.month_start)
    unreconciled = await bank.unreconciled_accounts(db, company.id, month_start, month_end)
    blocked = bank_block_message(unreconciled, month_start, body.override_reason)
    if blocked:
        raise HTTPException(status.HTTP_409_CONFLICT, blocked)
    try:
        row = await close_month(db, company, user.id, ent, body.month_start)
    except CloseError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    touch_books(company)  # entry numbers are final now
    await db.flush()
    audit.record(db, label=audit.month_label(row.month_start),
                 ent=ent, company_id=company.id, user=user, entity="books_month", entity_id=row.id,
                 action="close", after={**_month(row), **({"unreconciled_bank": unreconciled} if unreconciled else {})},
                 reason=body.override_reason.strip() if unreconciled else "")
    await db.commit()
    return await _books_year(db, company, row.fiscal_year)


@router.post("/companies/{company_id}/books/reopen", response_model=BooksYearOut)
async def reopen_books_month(company_id: uuid.UUID, body: ReopenMonthIn | None = None,
                             user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_manager(user)
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    try:
        row = await reopen_month(db, company)
    except CloseError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    audit.record(db, label=audit.month_label(row.month_start),
                 ent=ent, company_id=company.id, user=user, entity="books_month", entity_id=row.id,
                 action="reopen", before={"status": "closed"}, after={"status": "open"},
                 reason=body.reason if body else "")
    touch_books(company)
    await db.commit()
    return await _books_year(db, company, row.fiscal_year)


@router.post("/companies/{company_id}/books/{fiscal_year}/bind", response_model=BooksYearOut)
async def bind_books_year(company_id: uuid.UUID, fiscal_year: int, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    _require_manager(user)
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    try:
        row = await bind_year(db, company, user.id, ent, fiscal_year)
    except CloseError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await db.flush()
    audit.record(db, label=f"FY {fiscal_year}",
                 ent=ent, company_id=company.id, user=user, entity="books_month", entity_id=row.id,
                 action="bind", after={"fiscal_year": fiscal_year, "books": sorted(row.files or {})})
    await db.commit()
    return await _books_year(db, company, fiscal_year)


@router.get("/companies/{company_id}/books/{fiscal_year}/file")
async def books_file(company_id: uuid.UUID, fiscal_year: int, book: str = Query(..., max_length=20),
                     month_start: str | None = Query(None), user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    """A month's PDF of one book (``month_start`` given) or the bound year's."""
    company = await company_or_404(db, scope_for(user), company_id)
    months, bound = await year_status(db, company, fiscal_year)
    if month_start:
        month = next((m for m in months if m.start.isoformat() == month_start and m.status == "closed"), None)
        path = (month.files or {}).get(book) if month else None
        name = f"{book}-{month_start[:7]}.pdf"
    else:
        path = (bound.files or {}).get(book) if bound else None
        name = f"{book}-FY{fiscal_year}.pdf"
    target = stored_file(path) if path else None
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(target, media_type="application/pdf", filename=name)
