"""Close a month of the books, reopen the latest one, and bind a fiscal year (async; PDFs via books_pdf).

Files live under ``<accounting root>/accounting/books/<company>/FY<year>/`` and are never deleted: a reopened
month's PDFs move to ``void/`` (5-year retention, NIRC Sec. 235).
"""

import asyncio
import calendar
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import fitz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.accounting import AABookClose, AACompany, AADocument
from app.services.accounting.books.loader import active_closes, quarter_entries
from app.services.accounting.books_pdf import Header, cover_page, month_pdf, sworn_declaration
from app.services.accounting.compute.book_close import entry_to_json, final_numbers
from app.services.accounting.compute.book_ledgers import build_books, trial_balance_totals
from app.services.accounting.compute.depreciation import fiscal_year_window
from app.services.accounting.compute.due_dates import quarter_end
from app.services.accounting.periods import period_for

BOOK_ORDER = ("SJ", "PJ", "CRJ", "CDJ", "GJ", "GL")


class CloseError(ValueError):
    pass


def open_review_query(company_id: uuid.UUID, start: date, end: date):
    """Documents dated in the month that still block its close: flagged and not yet reviewed (a reviewed
    document keeps its reasons for the record)."""
    return select(AADocument.id).where(
        AADocument.company_id == company_id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
        AADocument.needs_review.is_(True), AADocument.reviewed.is_(False),
        AADocument.doc_date >= start, AADocument.doc_date <= end,
    )


BANK_BLOCK = "bank_unreconciled"


def bank_block_message(accounts: list[str], month_start: date, override_reason: str) -> str | None:
    """The soft block on closing a month whose bank statement isn't reconciled (None = may close)."""
    if not accounts or len(override_reason.strip()) >= 5:
        return None
    return (f"{BANK_BLOCK}: bank account {', '.join(accounts)} has statement lines in {month_start:%B %Y} that "
            "aren't reconciled. Reconcile it under Bank first, or close anyway with a reason.")


@dataclass(frozen=True)
class MonthStatus:
    start: date
    end: date
    status: str                  # closed | open | before_books
    pages: dict
    files: dict
    closed_at: datetime | None


def _root() -> Path:
    return Path(settings.accounting_root)


def _fy_dir(company: AACompany, fiscal_year: int) -> Path:
    return Path("accounting") / "books" / str(company.id) / f"FY{fiscal_year}"


def header_for(company: AACompany) -> Header:
    tin = company.tin
    return Header(company.registered_name, f"{tin[:3]}-{tin[3:6]}-{tin[6:9]}-{company.branch_code}",
                  " ".join(x for x in (company.address, company.zip_code) if x), company.rdo_code)


def fiscal_months(fiscal_year: int, fye: int) -> list[tuple[date, date]]:
    start, _ = fiscal_year_window(fiscal_year, fye)
    out = []
    year, month = start.year, start.month
    for _ in range(12):
        out.append((date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def bind_deadline(fiscal_year: int, fye: int) -> date:
    """Loose-leaf books are bound within 15 days after the fiscal year ends (RR 9-2009)."""
    return quarter_end(fiscal_year, 4, fye) + timedelta(days=15)


async def year_status(db: AsyncSession, company: AACompany, fiscal_year: int) -> tuple[list[MonthStatus], AABookClose | None]:
    fye = company.fiscal_year_end_month
    rows = [r for r in await active_closes(db, company.id) if r.fiscal_year == fiscal_year]
    by_start = {r.month_start: r for r in rows}
    months = []
    for start, end in fiscal_months(fiscal_year, fye):
        r = by_start.get(start)
        if company.books_start is None or end < company.books_start:
            status = "before_books"
        else:
            status = "closed" if r else "open"
        months.append(MonthStatus(start, end, status, r.pages if r else {}, r.files if r else {},
                                  r.closed_at if r else None))
    bound = (await db.execute(select(AABookClose).where(
        AABookClose.company_id == company.id, AABookClose.kind == "bound", AABookClose.fiscal_year == fiscal_year,
        AABookClose.voided_at.is_(None)))).scalars().first()
    return months, bound


async def close_month(db: AsyncSession, company: AACompany, user_id: uuid.UUID, ent: uuid.UUID,
                      month_start: date) -> AABookClose:
    from app.routers.accounting_periods import company_facts, load_periods  # router imports the loader
    from app.services.accounting.assets import active_assets
    from app.services.accounting.compute.engine import build_quarter

    if company.books_start is None:
        raise CloseError("The company doesn't keep books on AutoAccounting (set Books start on the company).")
    fye = company.fiscal_year_end_month
    where = period_for(month_start, fye)
    fiscal_year, quarter = where.fiscal_year, where.quarter
    months, bound = await year_status(db, company, fiscal_year)
    if bound is not None:
        raise CloseError(f"FY {fiscal_year} is already bound.")
    month = next((m for m in months if m.start == month_start), None)
    if month is None:
        raise CloseError("That isn't the first day of a month.")
    if month.status == "before_books":
        raise CloseError("That month is before the books start.")
    if month.status == "closed":
        raise CloseError(f"{month_start:%B %Y} is already closed.")
    earlier_open = [m for m in months if m.start < month_start and m.status == "open"]
    if earlier_open:
        raise CloseError(f"Close {earlier_open[0].start:%B %Y} first: months close in order.")
    if fiscal_year > period_for(company.books_start, fye).fiscal_year:
        previous, previous_bound = await year_status(db, company, fiscal_year - 1)
        if any(m.status == "open" for m in previous):
            raise CloseError(f"Close every month of FY {fiscal_year - 1} first.")
    open_reviews = (await db.execute(open_review_query(company.id, month.start, month.end))).scalars().all()
    if open_reviews:
        raise CloseError(f"{len(open_reviews)} document(s) dated in {month_start:%B %Y} still need review.")

    facts = company_facts(company)
    assets = await active_assets(db, company)
    periods = await load_periods(db, company, fiscal_year, quarter)
    result = build_quarter(facts, periods, assets=assets)
    q = await quarter_entries(db, company, facts, fiscal_year, quarter, result, assets, periods)
    if q is None:
        raise CloseError("The books have nothing for that quarter.")
    start = max(month.start, company.books_start)
    month_entries = [e for e in q.entries if month.start <= e.date <= month.end]
    tabs = build_books(q.entries, q.chart, start, month.end, fye, q.kept, q.closing,
                       tb_entries=[e for e in q.entries if not e.id.startswith("close:")], final=q.final)
    debit, credit = trial_balance_totals(tabs.get("TB", []))
    if debit != credit:
        raise CloseError(f"The trial balance doesn't balance (debits ₱{debit:,.2f}, credits ₱{credit:,.2f}).")

    # Final entry numbers continue each book's sequence for the fiscal year.
    used: dict[str, int] = {}
    for number in q.final.values():
        book, fy, n = number.rsplit("-", 2)
        if int(fy) == fiscal_year:
            used[book] = max(used.get(book, 0), int(n))
    numbers = final_numbers(month_entries, fiscal_year, used)
    tabs = build_books(q.entries, q.chart, start, month.end, fye, q.kept, q.closing,
                       final={**q.final, **numbers})

    # Page numbers continue per book through the fiscal year.
    last_pages: dict[str, int] = {}
    for m in months:
        for book, (first, last) in (m.pages or {}).items():
            last_pages[book] = max(last_pages.get(book, 0), last)
    header = header_for(company)
    period = f"For the month of {month_start:%B %Y}"
    folder = _fy_dir(company, fiscal_year) / f"M{months.index(month) + 1:02d}-{month_start:%Y-%m}"
    books = [b for b in BOOK_ORDER if b in q.kept or b in ("GJ", "GL")]

    def _render() -> tuple[dict, dict]:
        (_root() / folder).mkdir(parents=True, exist_ok=True)
        pages, files = {}, {}
        for book in books:
            first = last_pages.get(book, 0) + 1
            data, count = month_pdf(book, tabs.get(book, []), header, period, first)
            path = folder / f"{book}.pdf"
            (_root() / path).write_bytes(data)
            pages[book] = [first, first + count - 1]
            files[book] = str(path)
        return pages, files

    pages, files = await asyncio.get_running_loop().run_in_executor(None, _render)
    row = AABookClose(enterprise_id=ent, company_id=company.id, kind="month", fiscal_year=fiscal_year,
                      month_start=month.start, month_end=month.end,
                      entries=[entry_to_json(e) for e in month_entries], numbers=numbers, pages=pages, files=files,
                      closed_by=user_id)
    db.add(row)
    return row


async def reopen_month(db: AsyncSession, company: AACompany) -> AABookClose:
    rows = await active_closes(db, company.id)
    if not rows:
        raise CloseError("No month is closed.")
    latest = rows[-1]
    bound = (await db.execute(select(AABookClose).where(
        AABookClose.company_id == company.id, AABookClose.kind == "bound",
        AABookClose.fiscal_year == latest.fiscal_year, AABookClose.voided_at.is_(None)))).scalars().first()
    if bound is not None:
        raise CloseError(f"FY {latest.fiscal_year} is bound; its months can't be reopened.")
    now = datetime.now(timezone.utc)
    void = _fy_dir(company, latest.fiscal_year) / "void" / f"{now:%Y%m%dT%H%M%S}-{latest.month_start:%Y-%m}"

    def _move() -> dict:
        moved = {}
        (_root() / void).mkdir(parents=True, exist_ok=True)
        for book, path in (latest.files or {}).items():
            source = _root() / path
            if source.exists():
                shutil.move(str(source), str(_root() / void / Path(path).name))
            moved[book] = str(void / Path(path).name)
        return moved

    latest.files = await asyncio.get_running_loop().run_in_executor(None, _move)
    latest.voided_at = now
    return latest


async def bind_year(db: AsyncSession, company: AACompany, user_id: uuid.UUID, ent: uuid.UUID,
                    fiscal_year: int) -> AABookClose:
    fye = company.fiscal_year_end_month
    months, bound = await year_status(db, company, fiscal_year)
    if bound is not None:
        raise CloseError(f"FY {fiscal_year} is already bound.")
    if any(m.status == "open" for m in months):
        raise CloseError("Close every month of the fiscal year before binding it.")
    closed = [m for m in months if m.status == "closed"]
    if not closed:
        raise CloseError("No month of the fiscal year is closed.")
    header = header_for(company)
    start, end = fiscal_year_window(fiscal_year, fye)
    start = max(start, company.books_start or start)
    folder = _fy_dir(company, fiscal_year) / "bound"
    books = [b for b in BOOK_ORDER if any(b in (m.files or {}) for m in closed)]

    def _render() -> tuple[dict, dict]:
        (_root() / folder).mkdir(parents=True, exist_ok=True)
        pages, files, counts = {}, {}, []
        for book in books:
            doc = fitz.open()
            cover_page(doc, header, book, fiscal_year, start, end)
            for m in closed:
                path = (m.files or {}).get(book)
                if path and (_root() / path).exists():
                    with fitz.open(_root() / path) as part:
                        doc.insert_pdf(part)
            used = doc.page_count - 1
            counts.append((book, used))
            sworn_declaration(doc, header, [(book, used)], fiscal_year, start, end, company.books_signatory,
                              company.books_signatory_title)
            path = folder / f"{book}-FY{fiscal_year}.pdf"
            (_root() / path).write_bytes(doc.tobytes(garbage=3, deflate=True))
            pages[book] = [1, used]
            files[book] = str(path)
        doc = fitz.open()
        sworn_declaration(doc, header, counts, fiscal_year, start, end, company.books_signatory,
                          company.books_signatory_title)
        path = folder / f"Sworn-declaration-FY{fiscal_year}.pdf"
        (_root() / path).write_bytes(doc.tobytes())
        files["declaration"] = str(path)
        return pages, files

    pages, files = await asyncio.get_running_loop().run_in_executor(None, _render)
    row = AABookClose(enterprise_id=ent, company_id=company.id, kind="bound", fiscal_year=fiscal_year,
                      month_start=start, month_end=end, pages=pages, files=files, closed_by=user_id)
    db.add(row)
    return row


def stored_file(path: str) -> Path | None:
    """The absolute file for a stored relative path, refusing anything outside the books folder."""
    root = (_root() / "accounting" / "books").resolve()
    target = (_root() / path).resolve()
    if root not in target.parents or not target.is_file():
        return None
    return target
