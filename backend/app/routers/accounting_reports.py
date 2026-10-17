"""Live reports from the books: P&L, Balance Sheet, GL detail, transaction list, adjusted TB, adjusting entries,
invalid journal transactions, drill-down postings and sources, KPIs, exports (XLSX / PDF)."""

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.config import settings
from app.models.accounting import (
    AAAsset, AABankLine, AABankStatement, AACompany, AADocument, AAJournalEntry, AAPeriod,
)
from app.models.user import User
from app.routers.accounting_periods import _ensure_period, period_label
from app.routers.accounting_scope import company_or_404, scope_for
from app.schemas.accounting import manila_today
from app.services.accounting import audit
from app.services.accounting.books.closing import header_for
from app.services.accounting.compute import reports as r
from app.services.accounting.compute.due_dates import quarter_end, quarter_start
from app.services.accounting.periods import period_for
from app.services.accounting.report_export import jsonable, report_pdf, report_xlsx, table_for
from app.services.accounting.report_pack import Pack, pack_docx, pack_pdf
from app.services.accounting.reports import Books, invalid_rows, load_books, parse_uuid
from app.services.accounting.storage import is_stored_path_safe

router = APIRouter()

Kind = Literal["pnl", "balance-sheet", "gl", "transactions", "adjusted-tb", "adjusting", "invalid"]
TITLES = {"pnl": "Profit and loss", "balance-sheet": "Balance sheet", "gl": "General ledger detail",
          "transactions": "Transaction list by date", "adjusted-tb": "Adjusted trial balance",
          "adjusting": "Adjusting journal entries", "invalid": "Invalid journal transactions"}
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass
class Params:
    start: date | None
    end: date | None
    by: str
    compare: str
    nonzero: bool
    thousands: bool
    account: str | None
    party: str | None


def report_params(
    start: date | None = Query(None), end: date | None = Query(None),
    by: Literal["total", "month", "quarter"] = Query("total"),
    compare: Literal["none", "period", "year"] = Query("none"),
    nonzero: bool = Query(False), thousands: bool = Query(False),
    account: str | None = Query(None, max_length=10), party: str | None = Query(None, max_length=120),
) -> Params:
    return Params(start, end, by, compare, nonzero, thousands, account or None, (party or "").strip() or None)


def _window(p: Params, company: AACompany) -> tuple[date, date]:
    """The report window; by default the current fiscal quarter."""
    today = manila_today()
    fye = company.fiscal_year_end_month
    where = period_for(today, fye)
    start = p.start or quarter_start(where.fiscal_year, where.quarter, fye)
    end = p.end or quarter_end(where.fiscal_year, where.quarter, fye)
    _check(start, end, company)
    return start, end


def _check(start: date | None, end: date, company: AACompany) -> None:
    try:
        r.check_window(start, end, manila_today(), company.fiscal_year_end_month)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


async def _books(db: AsyncSession, company: AACompany, through: date, *, strict: bool = True) -> Books:
    try:
        books = await load_books(db, company, through)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    if strict and books.entries is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The books can't be built: {books.error}. Open Reports → "
                                                      "Invalid journal transactions to see what to fix.")
    return books


def _columns(p: Params, start: date, end: date, fye: int) -> list[r.Column]:
    if p.compare != "none" and p.by != "total":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Compare works with a single total column")
    cols = r.columns_for(start, end, p.by, fye)
    if len(cols) > r.MAX_COLUMNS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"At most {r.MAX_COLUMNS} columns; choose a shorter range "
                                                         "or wider columns")
    if p.compare != "none":
        ps, pe = r.prior_window(start, end, p.compare)
        cols.append(r.Column("prior", ("Prior year " if p.compare == "year" else "Prior period ")
                             + f"({ps:%b %-d, %Y} – {pe:%b %-d, %Y})", ps, pe))
    return cols


async def build(db: AsyncSession, company: AACompany, kind: str, p: Params) -> tuple[dict, str]:
    """(report data, subtitle) for one report."""
    fye = company.fiscal_year_end_month
    start, end = _window(p, company)
    span = f"{start:%B %-d, %Y} – {end:%B %-d, %Y}"
    if kind == "invalid":
        books = await _books(db, company, max(manila_today(), end), strict=False)  # end is already capped
        return {"rows": await invalid_rows(db, books), "engine_error": books.error}, "Self-check of the books"
    books = await _books(db, company, end)
    entries, chart = books.entries or [], books.chart
    if kind == "pnl":
        cols = _columns(p, start, end, fye)
        data = r.profit_and_loss(entries, chart, cols)
        if p.compare != "none":
            data = r.with_change(data, 0, 1)
        data = r.shape(data, nonzero=p.nonzero, thousands=p.thousands)
        return data, span + ("  (₱ thousands)" if p.thousands else "")
    if kind == "balance-sheet":
        cols = _columns(p, start, end, fye)
        data = r.balance_sheet(entries, chart, [c.end for c in cols], fye, books.closing)
        if p.compare != "none":
            data = r.with_change(data, 0, 1)
        data = r.shape(data, nonzero=p.nonzero, thousands=p.thousands)
        return data, f"As of {end:%B %-d, %Y}" + ("  (₱ thousands)" if p.thousands else "")
    if kind == "adjusted-tb":
        data = r.shape(r.adjusted_tb(entries, chart, end, fye, books.closing, books.adjusting),
                       nonzero=False, thousands=p.thousands)
        return data, f"As of {end:%B %-d, %Y} (fiscal year to date)"
    if kind == "gl":
        return {"accounts": r.gl_detail(entries, chart, start, end, fye, account=p.account, party=p.party)}, span
    if kind == "transactions":
        return {"rows": r.transaction_list(entries, chart, start, end, account=p.account, party=p.party)}, span
    if kind == "adjusting":
        return {"rows": r.adjusting_entries(entries, chart, start, end, books.adjusting)}, span
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report")


def _payload(company: AACompany, kind: str, data: dict, subtitle: str) -> dict:
    return {"kind": kind, "title": TITLES[kind], "subtitle": subtitle, "basis": "accrual",
            "company": company.registered_name, **data}


@router.get("/companies/{company_id}/reports/{kind}")
async def get_report(company_id: str, kind: Kind, p: Params = Depends(report_params),
                     user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    company = await _company(db, user, company_id)
    data, subtitle = await build(db, company, kind, p)
    return JSONResponse(jsonable(_payload(company, kind, data, subtitle)))


@router.get("/companies/{company_id}/reports/{kind}/export")
async def export_report(company_id: str, kind: Kind, format: Literal["xlsx", "pdf"] = Query("xlsx"),
                        p: Params = Depends(report_params), user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    company = await _company(db, user, company_id)
    data, subtitle = await build(db, company, kind, p)
    heads, rows = table_for(kind, data)
    header = header_for(company)
    title = TITLES[kind]
    render = report_xlsx if format == "xlsx" else report_pdf
    body = await asyncio.get_running_loop().run_in_executor(
        None, lambda: render(header, title, f"{subtitle} · accrual basis", heads, rows))
    name = re.sub(r"[^A-Za-z0-9 ._-]+", "", f"{company.registered_name} {title}").strip() or "report"
    return Response(content=body, media_type=_XLSX if format == "xlsx" else "application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.{format}"'})


async def _company(db: AsyncSession, user: User, company_id: str) -> AACompany:
    cid = parse_uuid(company_id)
    if cid is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return await company_or_404(db, scope_for(user), cid)


@router.get("/companies/{company_id}/report-postings")
async def report_postings(company_id: str, codes: str = Query(..., max_length=11 * r.MAX_DRILL_CODES),
                          start: date | None = Query(None),
                          end: date = Query(...), user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """The posting lines behind a report cell: ``codes`` (comma-separated) in [start, end]."""
    company = await _company(db, user, company_id)
    _check(start, end, company)
    try:
        wanted = r.drill_codes(codes)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    books = await _books(db, company, end)
    return JSONResponse(jsonable(r.postings(books.entries or [], books.chart, wanted, start, end)))


@router.get("/companies/{company_id}/report-source")
async def report_source(company_id: str, entry_id: str = Query(..., max_length=200),
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """What a posting traces back to: the source document (and page), a bank line and its statement, a journal entry,
    an asset, or a tax / system entry."""
    company = await _company(db, user, company_id)
    ent = company.enterprise_id
    ref = r.entry_ref(entry_id)
    out: dict = {"kind": ref["kind"], "entry_id": entry_id}
    rid = parse_uuid(ref["id"])

    async def document(doc_id) -> dict | None:
        doc = (await db.execute(select(AADocument).where(
            AADocument.id == doc_id, AADocument.enterprise_id == ent, AADocument.company_id == company.id,
            AADocument.deleted_at.is_(None)))).scalar_one_or_none()
        if doc is None:
            return None
        return {"document_id": doc.id, "page": doc.page_start, "title": doc.document_title,
                "doc_number": doc.doc_number, "doc_date": doc.doc_date}

    if ref["kind"] == "document" and rid:
        out["document"] = await document(rid)
    elif ref["kind"] == "bank_line" and rid:
        line = (await db.execute(select(AABankLine).where(
            AABankLine.id == rid, AABankLine.enterprise_id == ent, AABankLine.company_id == company.id))
                ).scalar_one_or_none()
        if line is not None:
            out["bank_line"] = {"date": line.line_date, "narration": line.narration, "amount": line.amount,
                                "check_no": line.check_no, "account_code": line.account_code,
                                "line_no": line.line_no}
            statement = await db.get(AABankStatement, line.statement_id)
            if statement is not None and statement.enterprise_id == ent:
                out["document"] = await document(statement.document_id)
    elif ref["kind"] == "journal_entry" and rid:
        je = (await db.execute(select(AAJournalEntry).where(
            AAJournalEntry.id == rid, AAJournalEntry.enterprise_id == ent, AAJournalEntry.company_id == company.id))
              ).scalar_one_or_none()
        if je is not None:
            out["journal_entry"] = {"id": je.id, "kind": je.kind, "book": je.book, "entry_date": je.entry_date,
                                    "reference": je.reference, "particulars": je.particulars, "lines": je.lines,
                                    "is_adjusting": bool(je.is_adjusting), "deleted": je.deleted_at is not None}
    elif ref["kind"] == "asset" and rid:
        asset = (await db.execute(select(AAAsset).where(
            AAAsset.id == rid, AAAsset.enterprise_id == ent, AAAsset.company_id == company.id))).scalar_one_or_none()
        if asset is not None:
            out["asset"] = {"description": asset.description, "cost": asset.cost, "in_service": asset.in_service}
            if asset.document_id:
                out["document"] = await document(asset.document_id)
    return JSONResponse(jsonable(out))


@router.get("/companies/{company_id}/kpis")
async def company_kpis(company_id: str, start: date | None = Query(None), end: date | None = Query(None),
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Margins and liquidity ratios for a window (default: the current fiscal quarter) and A/R / A/P aging buckets."""
    from app.services.accounting.books.subledger import load_subledger
    from app.services.accounting.compute.subledger import BUCKET_LABELS, BUCKETS, aging, aging_totals

    company = await _company(db, user, company_id)
    p = Params(start, end, "total", "none", False, False, None, None)
    start, end = _window(p, company)
    out: dict = {"start": start, "end": end, "books_on": company.books_start is not None, "kpis": None, "note": ""}
    if company.books_start is not None:
        books = await _books(db, company, end, strict=False)
        if books.entries is None:
            out["note"] = f"The books can't be built: {books.error}"
        else:
            cols = r.columns_for(start, end, "total", company.fiscal_year_end_month)
            pnl = r.profit_and_loss(books.entries, books.chart, cols)
            bs = r.balance_sheet(books.entries, books.chart, [end], company.fiscal_year_end_month, books.closing)
            out["kpis"] = r.kpis(pnl, bs, books.chart)
    sub = await load_subledger(db, company, end)
    await db.commit()  # contacts may have been synced
    out["aging"] = {kind: {"labels": BUCKET_LABELS, "buckets": list(BUCKETS),
                           "totals": aging_totals(aging([i for i in sub.items if i.doc.kind == kind]))}
                    for kind in ("ar", "ap")}
    return JSONResponse(jsonable(out))


# --- management report pack (per quarter, saved in the quarter's output folder) -------------------------------------

class PackNotesIn(BaseModel):
    notes: str = Field(default="", max_length=20000)


def _pack_dir(company: AACompany, year: int, quarter: int) -> Path:
    return Path(settings.accounting_root) / "accounting" / "outputs" / str(company.id) / f"{year}Q{quarter}"


def _pack_out(company: AACompany, period: AAPeriod) -> dict:
    files = period.pack_files or {}
    return {"year": period.year, "quarter": period.quarter, "period": period_label(period.year, period.quarter, company),
            "notes": period.pack_notes or "", "books_on": company.books_start is not None,
            "generated_at": files.get("generated_at"), "generated_by": files.get("by", ""),
            "pdf": bool(files.get("pdf")), "docx": bool(files.get("docx"))}


async def _pack_period(db: AsyncSession, user: User, company_id: str, year: int, quarter: int):
    company = await _company(db, user, company_id)
    fye = company.fiscal_year_end_month
    _check(quarter_start(year, quarter, fye), quarter_end(year, quarter, fye), company)
    return company, await _ensure_period(db, company.enterprise_id, company, year, quarter)


@router.get("/companies/{company_id}/pack/{year}/{quarter}")
async def get_pack(company_id: str, year: int = PathParam(ge=2000, le=2100), quarter: int = PathParam(ge=1, le=4),
                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    company, period = await _pack_period(db, user, company_id, year, quarter)
    return JSONResponse(jsonable(_pack_out(company, period)))


@router.put("/companies/{company_id}/pack/{year}/{quarter}/notes")
async def put_pack_notes(body: PackNotesIn, company_id: str, year: int = PathParam(ge=2000, le=2100),
                         quarter: int = PathParam(ge=1, le=4), user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    company, period = await _pack_period(db, user, company_id, year, quarter)
    before = period.pack_notes or ""
    period.pack_notes = body.notes.strip()
    if before != period.pack_notes:
        audit.record(db, label=f"{year} Q{quarter} · management pack", ent=company.enterprise_id,
                     company_id=company.id, user=user, entity="period", entity_id=f"{year}-Q{quarter}",
                     action="pack_notes", before={"pack_notes": before}, after={"pack_notes": period.pack_notes})
    await db.commit()
    return JSONResponse(jsonable(_pack_out(company, period)))


async def build_pack(db: AsyncSession, company: AACompany, year: int, quarter: int, notes: str) -> Pack:
    from app.services.accounting.books.subledger import load_subledger
    from app.services.accounting.compute.subledger import aging, aging_totals

    fye = company.fiscal_year_end_month
    qs, qe = quarter_start(year, quarter, fye), quarter_end(year, quarter, fye)
    books = await _books(db, company, qe)
    entries, chart = books.entries or [], books.chart
    cols = [r.Column("quarter", _quarter_label(year, quarter, fye), qs, qe),
            r.Column("ytd", "Fiscal year to date", r.fy_start(qe, fye), qe)]
    pnl = r.profit_and_loss(entries, chart, cols)
    bs_now = r.balance_sheet(entries, chart, [qe], fye, books.closing)
    bs = r.with_change(r.balance_sheet(entries, chart, [qe, qs - timedelta(days=1)], fye, books.closing), 0, 1)
    sub = await load_subledger(db, company, qe)
    ages = {}
    for kind in ("ar", "ap"):
        rows = aging([i for i in sub.items if i.doc.kind == kind])
        ages[kind] = ([(a.name, a.tin, {**a.buckets, "total": a.total}) for a in rows], aging_totals(rows))
    return Pack(header=header_for(company), period=period_label(year, quarter, company),
                prepared=f"{manila_today():%B %-d, %Y}",
                pnl=r.shape(pnl, nonzero=True, thousands=False), bs=r.shape(bs, nonzero=True, thousands=False),
                cash_flow=r.cash_flow(entries, chart, qs, qe, fye, books.closing), aging=ages,
                kpis=r.kpis(r.profit_and_loss(entries, chart, cols[:1]), bs_now, chart), notes=notes)


def _quarter_label(year: int, quarter: int, fye: int) -> str:
    return f"Q{quarter} {year}" if fye == 12 else f"Q{quarter} FY{year}"


@router.post("/companies/{company_id}/pack/{year}/{quarter}")
async def generate_pack(company_id: str, year: int = PathParam(ge=2000, le=2100), quarter: int = PathParam(ge=1, le=4),
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Build the pack from the books as they are now and save PDF + DOCX in the quarter's output folder."""
    company, period = await _pack_period(db, user, company_id, year, quarter)
    if company.books_start is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Books are off for this company: set Books start first.")
    pack = await build_pack(db, company, year, quarter, period.pack_notes or "")
    folder = _pack_dir(company, year, quarter)
    stamp = uuid.uuid4().hex[:8]
    pdf_path, docx_path = folder / f"pack-{stamp}.pdf", folder / f"pack-{stamp}.docx"

    def write() -> None:
        folder.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(pack_pdf(pack))
        docx_path.write_bytes(pack_docx(pack))

    await asyncio.get_running_loop().run_in_executor(None, write)
    now = datetime.now(timezone.utc).isoformat()
    period.pack_files = {"pdf": str(pdf_path), "docx": str(docx_path), "generated_at": now, "by": user.email}
    audit.record(db, label=f"{year} Q{quarter} · management pack", ent=company.enterprise_id, company_id=company.id,
                 user=user, entity="period", entity_id=f"{year}-Q{quarter}", action="pack_generated",
                 after={"files": [pdf_path.name, docx_path.name]})
    await db.commit()
    return JSONResponse(jsonable(_pack_out(company, period)))


@router.get("/companies/{company_id}/pack/{year}/{quarter}/file")
async def pack_file(company_id: str, year: int = PathParam(ge=2000, le=2100), quarter: int = PathParam(ge=1, le=4),
                    format: Literal["pdf", "docx"] = Query("pdf"), user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    company, period = await _pack_period(db, user, company_id, year, quarter)
    stored = (period.pack_files or {}).get(format)
    folder = _pack_dir(company, year, quarter).resolve()
    path = Path(stored).resolve() if stored else None
    if path is None or not is_stored_path_safe(str(path)) or folder not in path.parents or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generate the pack first")
    name = re.sub(r"[^A-Za-z0-9 ._-]+", "", f"{company.registered_name} {year} Q{quarter} management report").strip()
    media = "application/pdf" if format == "pdf" else _DOCX
    data = await asyncio.get_running_loop().run_in_executor(None, path.read_bytes)
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name or "pack"}.{format}"'})
