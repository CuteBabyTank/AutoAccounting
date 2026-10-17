"""Live reports glue (async): load the books' entries once, then reshape them with ``compute.reports``.

A failure of the books engine (an unbalanced computed entry, a chart missing a system account) is caught here and
kept as ``Books.error``: the Invalid Journal Transactions report shows it and the other reports answer 409.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AACompany, AAJournalEntry
from app.services.accounting.books.chart import Chart
from app.services.accounting.books.loader import ensure_chart
from app.services.accounting.compute.books import Entry
from app.services.accounting.compute.reports import check_entries, check_manual
from app.services.accounting.report_export import engine_error_rows


@dataclass
class Books:
    company: AACompany
    chart: Chart
    entries: list[Entry] | None      # None when the engine couldn't build them (see ``error``)
    error: str
    adjusting: set[str]              # entry ids of journal entries flagged adjusting
    fye: int
    closing: str                     # retained earnings (corporation) or capital


def closing_account(company: AACompany, chart: Chart) -> str:
    return chart.code("retained_earnings") if company.taxpayer_type == "corporation" else chart.code("capital")


async def manual_rows(db: AsyncSession, company: AACompany) -> list[AAJournalEntry]:
    return list((await db.execute(select(AAJournalEntry).where(
        AAJournalEntry.enterprise_id == company.enterprise_id, AAJournalEntry.company_id == company.id,
        AAJournalEntry.deleted_at.is_(None)).order_by(AAJournalEntry.entry_date, AAJournalEntry.created_at)
    )).scalars().all())


async def load_books(db: AsyncSession, company: AACompany, through: date) -> Books:
    """Every entry through ``through`` (books must be on: ``company.books_start`` set)."""
    from app.services.accounting.books.bank import book_entries

    if company.books_start is None:
        raise ValueError("Books are off for this company: set Books start on the company first.")
    chart = await ensure_chart(db, company)
    entries: list[Entry] | None
    error = ""
    try:
        entries = await book_entries(db, company, through) or []
    except (ValueError, KeyError) as exc:
        entries, error = None, str(exc).strip("'\"")
    adjusting = {f"je:{r.id}" for r in await manual_rows(db, company) if r.is_adjusting}
    return Books(company, chart, entries, error, adjusting, company.fiscal_year_end_month,
                 closing_account(company, chart))


async def invalid_rows(db: AsyncSession, books: Books) -> list[dict]:
    """Typed entries checked as stored, posted entries' accounts and balance, and an engine failure if any."""
    typed = [{"id": str(r.id), "entry_date": r.entry_date, "reference": r.reference, "lines": r.lines or []}
             for r in await manual_rows(db, books.company)]
    rows = check_manual(typed, books.chart)
    seen = {(r["entry_id"], r["problem"]) for r in rows}
    if books.entries is not None:
        rows += [r for r in check_entries(books.entries, books.chart) if (r["entry_id"], r["problem"]) not in seen
                 and not (r["entry_id"].startswith("je:") and r["entry_id"] in {x["entry_id"] for x in rows})]
    else:
        rows += engine_error_rows(books.error)
    return rows


def parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None
