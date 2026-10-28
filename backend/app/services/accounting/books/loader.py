# backend/app/services/accounting/books/loader.py
"""Gather what the books need for one quarter and build the book tabs (async loader + pure helpers)."""

import calendar
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import (
    AAAccount, AABookClose, AACompany, AADocument, AAJournalEntry, AAOpeningItem, AAOutput, AAPeriod,
)
from app.services.accounting.books.chart import (
    JOURNAL_BOOKS, Chart, ChartAccount, default_books, missing_standard, standard_chart,
)
from app.services.accounting.compute.book_ledgers import build_books, trial_balance_totals
from app.services.accounting.compute.annual_inputs import annual_inputs_from_json
from app.services.accounting.compute.bank_books import apply_bank_lines
from app.services.accounting.compute.books import (
    AnnualTaxes, BooksInput, Entry, FiledPayment, Line, ManualEntry, Payment, QuarterTaxes, post_all,
)
from app.services.accounting.compute.due_dates import month_start, quarter_end, quarter_start
from app.services.accounting.compute.engine import QuarterResult, build_quarter
from app.services.accounting.compute.ewt import compute_ewt
from app.services.accounting.compute.inputs import CompanyFacts, PeriodData, PeriodInputs
from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.compute.book_close import ClosedMonth, apply_closes, entry_from_json
from app.services.accounting.compute.statements import build_statements, closing_entries, is_closing
from app.services.accounting.compute.specs import ANNUAL_FORMS, PAYABLE_ITEM
from app.services.accounting.filing import credited_output_id
from app.services.accounting.opening_items import opening_doc_line, opening_payments
from app.services.accounting.periods import period_for

_MANILA = ZoneInfo("Asia/Manila")
_VAT_TOLERANCE = Decimal("1.00")
_PAYABLE = ("sales", "purchases", "expenses", "payroll")


def touch_books(company: AACompany) -> None:
    """Book tabs generated before now are stale (chart, journal entries or filed returns changed)."""
    company.books_updated_at = datetime.now(timezone.utc)


def books_window(start: date, year: int, quarter: int, fye: int) -> tuple[date, date] | None:
    first, last = quarter_start(year, quarter, fye), quarter_end(year, quarter, fye)
    if last < start:
        return None
    return max(first, start), last


def tax_periods(periods: list[PeriodData], books_start: date, fye: int) -> list[int]:
    """Indexes of the periods whose taxes the books post: the fiscal year of books_start onward."""
    first = period_for(books_start, fye).fiscal_year
    return [i for i, p in enumerate(periods) if p.year >= first]


# What an amended return subtracts as paid on the original: the payment of a filed version is payable + this.
_PAID_BEFORE_ITEM = (("2550Q", "18"), ("2551Q", "16"), ("1701Q", "59"), ("1702Q", "S4_6"), ("1601EQ", "22"),
                     ("1601C-M", "28"), ("1702RT", "51"), ("1701A", "61"), ("1701", "P7_6"))


def _paid_before(values: dict, form: str) -> Decimal:
    item = next((i for prefix, i in _PAID_BEFORE_ITEM if form.startswith(prefix)), None)
    value = values.get(item) if item else None
    return c2(value) if value not in (None, "") else ZERO


def filed_payments(periods: list[tuple[int, int, dict]], outputs: dict[str, dict]) -> tuple[FiledPayment, ...]:
    out: list[FiledPayment] = []
    for year, quarter, filed in periods:
        for form, entry in (filed or {}).items():
            item = PAYABLE_ITEM.get(form)
            snap = outputs.get(str(entry.get("output_id")))
            values = (snap or {}).get("forms", {}).get(form, {})
            value = values.get(item) if item else None
            if value is None:  # the filed version's snapshot is gone, or the form has no payable line
                continue
            try:
                amount = c2(c2(value) + _paid_before(values, form))  # an amendment's total, not just the top-up
                on = (date.fromisoformat(entry["paid_on"]) if entry.get("paid_on")
                      else datetime.fromisoformat(entry["filed_at"]).astimezone(_MANILA).date())
            except (InvalidOperation, TypeError, ValueError, KeyError):
                continue
            out.append(FiledPayment(form, year, quarter, on, amount))
    return tuple(out)


def _gl_activity(tabs: dict, code: str) -> bool:
    return any(r.get("code") == code and (r.get("debit") or r.get("credit")) for r in tabs.get("GL", []))


def books_warnings(tabs: dict, inputs: PeriodInputs, has_employees: bool, chart: Chart, quarter: int) -> list[str]:
    warnings: list[str] = []
    debit, credit = trial_balance_totals(tabs.get("TB", []))
    if debit != credit:
        warnings.append(f"The trial balance doesn't balance (debits ₱{debit:,.2f}, credits ₱{credit:,.2f}). "
                        "This is a bug: report it before relying on these books.")
    output_vat = next((a.code for a in chart.accounts if a.system_key == "output_vat"), None)
    row = next((r for r in tabs.get("TB", []) if output_vat and r.get("code") == output_vat), None)
    off = abs(c2((row or {}).get("credit") or 0) - c2((row or {}).get("debit") or 0))
    if off > _VAT_TOLERANCE:  # the quarter's VAT close clears what the 2550-Q carries; the rest stays
        warnings.append(f"Output VAT in the books differs from the 2550-Q by ₱{off:,.2f}. Check the sales documents "
                        "whose VAT isn't 12% of the VATable amount.")
    if inputs.non_operating_income > 0 and not _gl_activity(tabs, chart.code("other_income")):
        warnings.append(f"Other income of ₱{inputs.non_operating_income:,.2f} is in the quarter inputs but not in "
                        "the books. Post it as a journal entry in Books.")
    return warnings


def _chart_account(row: AAAccount) -> ChartAccount:
    return ChartAccount(row.code, row.name, row.type, row.contra, row.system_key, row.parent_code, row.active,
                        bool(row.locked))


async def ensure_chart(db: AsyncSession, company: AACompany) -> Chart:
    """The company's chart, seeding the standard accounts that are missing (first use or newer keys)."""
    rows = (await db.execute(select(AAAccount).where(AAAccount.company_id == company.id))).scalars().all()
    standard = {a.code: a for a in standard_chart(company.taxpayer_type)}
    keys = {r.system_key for r in rows if r.system_key}
    for r in rows:  # a standard account seeded before it had a system key gets the key now
        std = standard.get(r.code)
        if r.system_key is None and std and std.system_key and std.system_key not in keys and r.type == std.type:
            r.system_key = std.system_key
            keys.add(std.system_key)
    missing = (standard_chart(company.taxpayer_type) if not rows
               else missing_standard([_chart_account(r) for r in rows], company.taxpayer_type))
    if missing:
        await db.execute(pg_insert(AAAccount).values([
            dict(id=uuid.uuid4(), enterprise_id=company.enterprise_id, company_id=company.id, code=a.code,
                 name=a.name, type=a.type, contra=a.contra, parent_code=a.parent_code, system_key=a.system_key,
                 active=True, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
            for a in missing
        ]).on_conflict_do_nothing())
        rows = (await db.execute(select(AAAccount).where(AAAccount.company_id == company.id))).scalars().all()
    return Chart(_chart_account(r) for r in rows)


def _manual(row: AAJournalEntry, books_start: date) -> ManualEntry:
    """A typed journal entry; the opening balances always sit on the books' start date."""
    lines = tuple(Line(str(x.get("account_code", "")), c2(x.get("debit") or 0), c2(x.get("credit") or 0),
                       str(x.get("party_name", "")), str(x.get("party_tin", ""))) for x in row.lines or [])
    on = books_start if row.kind == "opening" else row.entry_date
    return ManualEntry(str(row.id), row.kind, row.book, on, row.reference, row.particulars, lines)


def opening_ppe_warning(manual: list[ManualEntry], chart: Chart, assets) -> str | None:
    """The opening balances carry property and equipment the asset register doesn't (so it never depreciates)."""
    ppe, accum = chart.code("ppe"), chart.code("accum_dep")
    net = sum((l.debit - l.credit for m in manual if m.kind == "opening" for l in m.lines
               if l.account in (ppe, accum)), ZERO)
    registered = sum((a.cost for a in assets if not a.document_id), ZERO)
    if net <= 0 or abs(net - registered) <= _VAT_TOLERANCE:
        return None
    return (f"The opening balances carry ₱{net:,.2f} of property and equipment (net), but the asset register's "
            f"opening assets total ₱{registered:,.2f}. Add them under Books → Opening balances → Opening assets so they depreciate.")


def document_payments(receipts, posted) -> list[Payment]:
    """Payments from linked receipts (cash = amount due less tax withheld, like the invoice), then the
    paid-on fields of documents no receipt pays."""
    paid_by_receipt = {str(r.settles_document_id) for r in receipts}
    payments = [Payment(f"rcpt:{r.id}", str(r.settles_document_id), r.doc_date,
                        c2(r.gross_amount - (r.withholding_amount or ZERO)), r.paid_via or "cash", r.doc_number)
                for r in receipts]
    payments += [Payment(f"paid:{d.id}", str(d.id), d.paid_on, None, d.paid_via or "cash", d.payment_ref)
                 for d in posted if d.paid_on is not None and d.category in _PAYABLE and str(d.id) not in paid_by_receipt]
    return payments


def month_contributions(p: PeriodData, fye: int) -> tuple[tuple[date, Decimal, Decimal], ...]:
    """(month end, employee share, employer share) for each month of the quarter with contributions entered."""
    out = []
    for m, month in enumerate(p.inputs.payroll, start=1):
        if month.contributions > 0 or month.employer_contributions > 0:
            first = month_start(p.year, p.quarter, fye, m)
            end = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
            out.append((end, month.contributions, month.employer_contributions))
    return tuple(out)


async def annual_taxes(db: AsyncSession, company: AACompany, year: int,
                       quarter: int) -> tuple[tuple[AnnualTaxes, ...], str | None]:
    """Every earlier fiscal year's annual return (filed version, else latest), and this one's at Q4."""
    fye = company.fiscal_year_end_month
    last = year if quarter == 4 else year - 1
    periods = (await db.execute(select(AAPeriod).where(
        AAPeriod.company_id == company.id, AAPeriod.quarter == 0, AAPeriod.year <= last,
    ))).scalars().all()
    out: list[AnnualTaxes] = []
    for period in periods:
        latest = (await db.execute(select(AAOutput).where(AAOutput.period_id == period.id)
                                   .order_by(AAOutput.version.desc()).limit(1))).scalars().first()
        form = next((f for f in ANNUAL_FORMS if latest and f in latest.snapshot.get("forms", {})), None)
        if form is None:
            continue
        legacy = str(period.filed_output_id) if period.filed_output_id else None
        filed_id = credited_output_id(period.filed_forms or {}, form, legacy)
        chosen = (await db.get(AAOutput, uuid.UUID(filed_id))) if filed_id else None
        snap = (chosen or latest).snapshot
        out.append(AnnualTaxes(period.year, quarter_end(period.year, 4, fye), form, snap.get("forms", {})))
    note = None
    if quarter == 4 and not any(a.year == year for a in out):
        note = (f"Q4 income tax isn't in the books yet: it comes from FY {year}'s annual return. Generate the annual "
                "return, then regenerate this quarter.")
    return tuple(out), note


@dataclass
class QuarterEntries:
    entries: list[Entry]                 # closed months frozen, corrections posted, year-end closing at Q4
    adjusted: list[Entry] | None         # Q4: the entries before closing (adjusted trial balance)
    warnings: list[str]
    chart: Chart
    closing: str                         # retained earnings / capital
    kept: frozenset[str]
    window: tuple[date, date]
    final: dict[str, str]                # closed months' entry numbers
    notes: list[str]


async def active_closes(db: AsyncSession, company_id: uuid.UUID, upto: date | None = None) -> list[AABookClose]:
    query = select(AABookClose).where(AABookClose.company_id == company_id, AABookClose.kind == "month",
                                      AABookClose.voided_at.is_(None))
    if upto is not None:
        query = query.where(AABookClose.month_end <= upto)
    return list((await db.execute(query.order_by(AABookClose.month_start))).scalars().all())


def _closed_months(rows: list[AABookClose]) -> list[ClosedMonth]:
    return [ClosedMonth(r.month_start, r.month_end, tuple(entry_from_json(e) for e in r.entries),
                        tuple((r.numbers or {}).items())) for r in rows]


async def opening_items(db: AsyncSession, company: AACompany) -> list[AAOpeningItem]:
    """The company's live opening open items (A/R / A/P outstanding when the books start)."""
    return list((await db.execute(select(AAOpeningItem).where(
        AAOpeningItem.enterprise_id == company.enterprise_id, AAOpeningItem.company_id == company.id,
        AAOpeningItem.deleted_at.is_(None)).order_by(AAOpeningItem.doc_date, AAOpeningItem.doc_number)
    )).scalars().all())


async def quarter_books(db: AsyncSession, company: AACompany, facts: CompanyFacts, year: int, quarter: int,
                        result: QuarterResult, assets, periods: list[PeriodData]) -> tuple[dict, list[str]]:
    """Book tabs for the quarter being generated ({} when books are off or start after this quarter)."""
    q = await quarter_entries(db, company, facts, year, quarter, result, assets, periods)
    if q is None:
        return {}, []
    fye = company.fiscal_year_end_month
    tabs = build_books(q.entries, q.chart, q.window[0], q.window[1], fye, q.kept, q.closing, tb_entries=q.adjusted,
                       final=q.final)
    warnings = list(q.warnings)
    if quarter == 4:
        statements, statement_warnings = build_statements(q.entries, q.chart, year, fye, q.closing,
                                                          company.taxpayer_type, company.books_start)
        tabs.update(statements)
        warnings += statement_warnings
    target_inputs = periods[-1].inputs if periods else PeriodInputs()
    return tabs, (warnings + books_warnings(tabs, target_inputs, company.has_employees, q.chart, quarter) + q.notes)


async def quarter_entries(db: AsyncSession, company: AACompany, facts: CompanyFacts, year: int, quarter: int,
                          result: QuarterResult, assets, periods: list[PeriodData]) -> QuarterEntries | None:
    """Every book entry through the quarter's end (None when books are off or start after this quarter)."""
    from app.routers.accounting_periods import doc_line, supplier_atc_rules, supplier_gl_rules  # router imports us

    fye = company.fiscal_year_end_month
    if company.books_start is None:
        return None
    window = books_window(company.books_start, year, quarter, fye)
    if window is None:
        return None
    through = window[1]
    chart = await ensure_chart(db, company)

    docs = (await db.execute(select(AADocument).where(
        AADocument.company_id == company.id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
        AADocument.doc_date.is_not(None), AADocument.doc_date <= through,
    ))).scalars().all()
    atc_rules, gl_rules = await supplier_atc_rules(db, company.id), await supplier_gl_rules(db, company.id)
    receipts = [d for d in docs if d.settles_document_id is not None]
    posted = [d for d in docs if d.settles_document_id is None]
    opening = await opening_items(db, company)
    lines = tuple(doc_line(d, atc_rules, gl_rules) for d in posted) + tuple(
        opening_doc_line(i, company.books_start) for i in opening)
    payments = document_payments(receipts, posted) + opening_payments(opening)
    ewt = {line_id: tax for line_id, (_, tax) in compute_ewt(lines, facts, year, quarter).by_line().items()}

    # Q4 without a count takes the ending inventory typed in the annual inputs (the 1702-RT / 1701 figure)
    annual_counts = {row.year: annual_inputs_from_json(row.inputs).ending_inventory for row in (await db.execute(
        select(AAPeriod).where(AAPeriod.company_id == company.id, AAPeriod.quarter == 0))).scalars().all()}
    quarters = []
    for i in tax_periods(periods, company.books_start, fye):
        p = periods[i]
        count = p.inputs.ending_inventory
        if count is None and p.quarter == 4:
            count = annual_counts.get(p.year)
        forms = result.forms if (p.year, p.quarter) == (year, quarter) else build_quarter(
            facts, periods[: i + 1], assets=assets).forms
        quarters.append(QuarterTaxes(p.year, p.quarter, quarter_end(p.year, p.quarter, fye), forms,
                                     ending_inventory=count,
                                     contributions=month_contributions(p, fye)))

    rows = (await db.execute(select(AAPeriod.year, AAPeriod.quarter, AAPeriod.filed_forms).where(
        AAPeriod.company_id == company.id,
        or_(AAPeriod.year < year, and_(AAPeriod.year == year, AAPeriod.quarter <= quarter)),
    ))).all()  # quarter 0 is the annual return
    annual, annual_note = await annual_taxes(db, company, year, quarter)
    ids = {uuid.UUID(str(e["output_id"])) for _, _, f in rows for e in (f or {}).values() if e.get("output_id")}
    outputs = {str(o.id): o.snapshot for o in (await db.execute(
        select(AAOutput).where(AAOutput.id.in_(ids)))).scalars().all()} if ids else {}
    manual = (await db.execute(select(AAJournalEntry).where(
        AAJournalEntry.company_id == company.id, AAJournalEntry.deleted_at.is_(None),
        or_(AAJournalEntry.kind == "opening", AAJournalEntry.entry_date <= through),
    ))).scalars().all()

    kept = frozenset(company.books_kept or default_books(facts.vat_registered)) | {"GJ"}
    typed = [_manual(m, company.books_start) for m in manual]
    # Matched statement lines: a document's bank payment, a receipt moved into the bank, charges / transfers
    from app.services.accounting.books.bank import matched_lines  # bank imports this module

    payments, filed, bank_postings = apply_bank_lines(
        payments, filed_payments([tuple(r) for r in rows], outputs), await matched_lines(db, company.id, through))
    inp = BooksInput(facts, chart, kept, company.books_start, through, lines=lines, ewt=ewt,
                     payments=tuple(payments), manual=tuple(typed),
                     quarters=tuple(quarters), filed=filed, assets=tuple(assets),
                     annual=annual, bank=tuple(bank_postings))
    entries, warnings = post_all(inp)
    closing = chart.code("retained_earnings") if company.taxpayer_type == "corporation" else chart.code("capital")
    if quarter == 4:  # fiscal year end: closing entries, post-closing TB and the financial statements
        entries = entries + closing_entries(entries, chart, year, fye, closing, company.taxpayer_type)
    closes = await active_closes(db, company.id, through)
    entries, correction_warnings = apply_closes(entries, _closed_months(closes))
    entries.sort(key=lambda e: (e.date, JOURNAL_BOOKS.index(e.book) if e.book in JOURNAL_BOOKS else 9, e.id))
    adjusted = [e for e in entries if not is_closing(e)] if quarter == 4 else None
    final = {k: v for c in closes for k, v in (c.numbers or {}).items()}
    ppe_note = opening_ppe_warning(typed, chart, assets)
    return QuarterEntries(entries, adjusted, warnings + correction_warnings, chart, closing, kept, window, final,
                          [note for note in (ppe_note, annual_note) if note])
