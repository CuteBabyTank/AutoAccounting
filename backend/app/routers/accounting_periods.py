"""AutoAccounting phase 2: quarter inputs, generating output versions, workbook and PDF downloads."""

import asyncio
import copy
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import Path as PathParam
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.accounting import AAAsset, AAAtcDefault, AACompany, AADocument, AAOutput, AAPeriod, AASupplierRule
from app.models.user import User
from app.routers.accounting_scope import company_or_404, require_filing_rights, scope_for
from app.schemas.accounting import (
    CertificateOut, CertificatePreviewIn, CertificatesIn, CompanyBrief, FiledFormOut, FiledIn, FormEditIn,
    FormFiledIn, FormOut, ItemOut, OutputBrief, OutputOut, PdfFieldOut, PdfsIn,
    PeriodInputsModel, PeriodOut, PrepareFormOut, PrepareOut, manila_today,
)
from app.schemas.form_filler import FilledForm
from app.services.accounting import audit
from app.services.accounting.compute.annual import annual_form
from app.services.accounting.certificate_edits import apply_2307, fields_2307
from app.services.accounting.compute.due_dates import annual_due_date, due_dates, quarter_end, quarter_start
from app.services.accounting.compute.engine import AMENDED_WARNING, build_quarter, expected_forms
from app.services.accounting.compute.ewt import effective_atc
from app.services.accounting.compute.inputs import (
    CompanyFacts, DocLine, PeriodData, PeriodInputs, inputs_from_json, inputs_to_json,
)
from app.services.accounting.compute.specs import FORM_ORDER, FORM_TITLES, PAYABLE_ITEM, PDF_FORMS, form_items
from app.services.accounting.assets import active_assets
from app.services.accounting.atc_prefs import account_key, remembered_atc
from app.services.accounting.books.loader import quarter_books, touch_books
from app.services.accounting.classify import document_description, document_nature
from app.services.accounting.diff import count_changes, diff_snapshots, snapshot
from app.services.accounting.filing import (
    amended_forms, amends_payment, backfill, derive, file_all, form_amended, set_form, unfile_all, unset_form,
)
from app.services.accounting.filing_guide import guide, scope_forms, scope_label, scope_note, source_line
from app.services.accounting.form_edits import apply_edits, dropped_edits_warning, edits_warning, merge_edited
from app.services.accounting.outgoing_2307 import payee_forms, zip_forms
from app.services.accounting.pdf_2550q import Header2550Q, render_2550q
from app.services.accounting.pdf_bundle import validate_requested, zip_pdfs
from app.services.accounting.pdf_returns import header_from_snapshot, render_return
from app.services.accounting.periods import quarter_label
from app.services.accounting.render_xlsx import write_workbook
from app.services.accounting.required_fields import missing_fields
from app.services.accounting.storage import is_stored_path_safe
from app.services.form_filler_service import generate_merged_pdf

router = APIRouter()

_MANILA = ZoneInfo("Asia/Manila")
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def company_facts(c: AACompany) -> CompanyFacts:
    return CompanyFacts(c.registered_name, c.tin, c.branch_code, c.rdo_code, c.address, c.zip_code,
                        c.taxpayer_type, c.vat_status == "vat", c.income_tax_option, c.deduction_method,
                        c.business_type, c.fiscal_year_end_month, is_withholding_agent=c.is_withholding_agent,
                        is_top_withholding_agent=c.is_top_withholding_agent, has_employees=c.has_employees,
                        has_compensation_income=c.has_compensation_income,
                        operations_start_year=c.operations_start_year, contact_number=c.contact_number or "",
                        email=c.email or "", taxpayer_classification=c.taxpayer_classification or "")


def doc_line(doc: AADocument, atc_rules: dict[str, str] | None = None,
             gl_rules: dict[str, str] | None = None) -> DocLine:
    """A document as the engine sees it; the company's remembered ATC (supplier, then expense account) and the
    supplier's GL account fill in when the document has none."""
    seller = doc.client_role == "seller"
    counterparty_tin = doc.buyer_tin if seller else doc.seller_tin
    remembered = "" if seller else remembered_atc(atc_rules or {}, counterparty_tin, doc.account)[0]
    gl = doc.gl_account_code or ("" if seller else (gl_rules or {}).get(counterparty_tin, ""))
    return DocLine(
        id=str(doc.id), category=doc.category, account=doc.account, doc_type=doc.doc_type,
        client_role=doc.client_role, doc_date=doc.doc_date, doc_number=doc.doc_number,
        counterparty_tin=counterparty_tin,
        counterparty_name=doc.buyer_name if seller else doc.seller_name,
        counterparty_address=doc.buyer_address if seller else doc.seller_address,
        gross=doc.gross_amount, vatable=doc.vatable_amount, vat=doc.vat_amount, exempt=doc.exempt_amount,
        zero_rated=doc.zero_rated_amount, withholding=doc.withholding_amount,
        input_vat_valid=doc.input_vat_valid, open_review=doc.needs_review and not doc.reviewed,
        ewt_atc=doc.ewt_atc or remembered,
        counterparty_vat_registered=None if seller else doc.seller_vat_registered,
        gl_account=gl, nature=document_nature(doc.raw), description=document_description(doc.raw),
    )


def counts_on_returns(doc: AADocument) -> bool:
    """A receipt linked to the invoice it pays is payment evidence, not a second sale or expense."""
    return doc.settles_document_id is None


async def supplier_gl_rules(db: AsyncSession, company_id: uuid.UUID) -> dict[str, str]:
    return dict((await db.execute(select(AASupplierRule.counterparty_tin, AASupplierRule.gl_account_code).where(
        AASupplierRule.company_id == company_id, AASupplierRule.gl_account_code != "",
    ))).all())


def effective_document_atc(doc: AADocument, company: AACompany, atc_rules: dict[str, str]) -> str:
    """The ATC the next generation will use for this document ("" = no withholding)."""
    return effective_atc(doc_line(doc, atc_rules), company_facts(company))


def document_atc_source(doc: AADocument, atc_rules: dict[str, str]) -> str:
    """Where the document's ATC comes from: document, supplier, account, or "" (built-in suggestion)."""
    if doc.ewt_atc:
        return "document"
    if doc.client_role == "seller":
        return ""
    return remembered_atc(atc_rules, doc.seller_tin, doc.account)[1]


async def supplier_atc_rules(db: AsyncSession, company_id: uuid.UUID) -> dict[str, str]:
    """The company's ATC databank: supplier TIN -> ATC, plus account_key(expense account) -> ATC."""
    rules = dict((await db.execute(select(AASupplierRule.counterparty_tin, AASupplierRule.ewt_atc).where(
        AASupplierRule.company_id == company_id, AASupplierRule.ewt_atc != "",
    ))).all())
    for account, atc in (await db.execute(select(AAAtcDefault.account, AAAtcDefault.ewt_atc).where(
        AAAtcDefault.company_id == company_id))).all():
        rules[account_key(account)] = atc
    return rules


def period_label(year: int, quarter: int, company: AACompany) -> str:
    if quarter == 0:
        return f"{year} · Annual"
    return f"{year} · {quarter_label(quarter, company.fiscal_year_end_month)}"


def _docs_up_to(year: int, quarter: int):
    return or_(AADocument.period_year < year, and_(AADocument.period_year == year, AADocument.period_quarter <= quarter))


async def _get_period(db: AsyncSession, company_id: uuid.UUID, year: int, quarter: int) -> AAPeriod | None:
    return (await db.execute(select(AAPeriod).where(
        AAPeriod.company_id == company_id, AAPeriod.year == year, AAPeriod.quarter == quarter
    ))).scalar_one_or_none()


async def _ensure_period(db: AsyncSession, ent: uuid.UUID, company: AACompany, year: int, quarter: int) -> AAPeriod:
    period = await _get_period(db, company.id, year, quarter)
    if period is not None:
        return period
    db.add(AAPeriod(enterprise_id=ent, company_id=company.id, year=year, quarter=quarter, inputs={}))
    try:
        await db.commit()
    except IntegrityError:  # created by a concurrent request
        await db.rollback()
    return await _get_period(db, company.id, year, quarter)


async def load_periods(db: AsyncSession, company: AACompany, year: int, quarter: int) -> list[PeriodData]:
    from app.services.accounting.books.vat_backfill import backfill_vat_difference

    await backfill_vat_difference(db, company)   # older VAT-mismatch purchases get QBO 01's VAT-difference rule
    docs = (await db.execute(select(AADocument).where(
        AADocument.company_id == company.id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
        AADocument.period_year.is_not(None), AADocument.settles_document_id.is_(None), _docs_up_to(year, quarter),
    ))).scalars().all()
    rows = (await db.execute(select(AAPeriod).where(AAPeriod.company_id == company.id,
                                                    AAPeriod.quarter >= 1))).scalars().all()  # not the annual period
    atc_rules = await supplier_atc_rules(db, company.id)
    lines: dict[tuple[int, int], list[DocLine]] = {}
    for doc in docs:
        lines.setdefault((doc.period_year, doc.period_quarter), []).append(doc_line(doc, atc_rules))
    inputs = {(p.year, p.quarter): inputs_from_json(p.inputs) for p in rows}
    keys = sorted({k for k in set(lines) | set(inputs) if k <= (year, quarter)} | {(year, quarter)})
    return [
        PeriodData(y, q, tuple(sorted(lines.get((y, q), []), key=lambda l: (l.doc_date or date.min, l.id))),
                   inputs.get((y, q), PeriodInputs()))
        for y, q in keys
    ]


async def _expected(db: AsyncSession, company: AACompany, year: int, quarter: int) -> list[str]:
    payroll = (await db.execute(select(func.count(AADocument.id)).where(
        AADocument.company_id == company.id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
        AADocument.period_year == year, AADocument.period_quarter == quarter, AADocument.category == "payroll",
    ))).scalar()
    return expected_forms(company_facts(company), quarter, has_payroll=payroll > 0)


async def _filed_forms(db: AsyncSession, period: AAPeriod | None, expected: list[str]) -> dict:
    """The period's per-form filing; a quarter filed before per-form filing existed counts every form filed."""
    if period is None:
        return {}
    if not period.filed_forms and period.filed_at is not None and period.filed_output_id is not None:
        output = await db.get(AAOutput, period.filed_output_id)
        if output is not None:
            return backfill(expected, str(output.id), output.version, period.filed_at,
                            available=output.snapshot["forms"])
    return dict(period.filed_forms or {})


async def filed_values(db: AsyncSession, filed: dict) -> dict[str, dict]:
    """Each filed form's figures as they were in the version it was filed from."""
    ids = {entry["output_id"] for entry in filed.values() if entry.get("output_id")}
    rows = (await db.execute(select(AAOutput).where(AAOutput.id.in_([uuid.UUID(i) for i in ids]))
                             )).scalars().all() if ids else []
    snaps = {str(o.id): o.snapshot["forms"] for o in rows}
    return {form: snaps[entry["output_id"]][form] for form, entry in filed.items()
            if form in snaps.get(entry.get("output_id"), {})}


async def _remittances(db: AsyncSession, filed: dict) -> dict[int, tuple[Decimal, int]]:
    out: dict[int, tuple[Decimal, int]] = {}
    for month in (1, 2):
        entry = filed.get(f"0619E-M{month}")
        output = await db.get(AAOutput, uuid.UUID(entry["output_id"])) if entry else None
        value = output.snapshot["forms"].get(f"0619E-M{month}", {}).get("18") if output else None
        if value is not None:
            out[month] = (Decimal(value), output.version)
    return out


async def _is_stale(db: AsyncSession, company: AACompany, year: int, quarter: int, generated_at: datetime) -> bool:
    company_id = company.id
    doc_change = (await db.execute(select(func.max(func.greatest(
        AADocument.created_at, AADocument.updated_at, func.coalesce(AADocument.deleted_at, AADocument.created_at)
    ))).where(AADocument.company_id == company_id, AADocument.period_year.is_not(None),
              _docs_up_to(year, quarter)))).scalar()
    input_change = (await db.execute(select(func.max(AAPeriod.inputs_updated_at)).where(
        AAPeriod.company_id == company_id, AAPeriod.quarter >= 1,
        or_(AAPeriod.year < year, and_(AAPeriod.year == year, AAPeriod.quarter <= quarter)),
    ))).scalar()
    asset_change = (await db.execute(select(func.max(AAAsset.updated_at)).where(
        AAAsset.company_id == company_id,
        AAAsset.in_service <= quarter_end(year, quarter, company.fiscal_year_end_month),
    ))).scalar()
    return any(t is not None and t > generated_at
               for t in (doc_change, input_change, asset_change, company.facts_updated_at))


def books_stale(company: AACompany, generated_at: datetime | None) -> bool:
    """The chart, journal entries, books settings or filed payments changed after the latest version."""
    return (company.books_start is not None and generated_at is not None
            and company.books_updated_at is not None and company.books_updated_at > generated_at)


async def _period_out(db: AsyncSession, company: AACompany, year: int, quarter: int) -> PeriodOut:
    period = await _get_period(db, company.id, year, quarter)
    outputs = (await db.execute(select(AAOutput).where(AAOutput.period_id == period.id)
                                .order_by(AAOutput.version.desc()))).scalars().all() if period else []
    document_count, open_reviews = (await db.execute(select(
        func.count(AADocument.id),
        func.count(AADocument.id).filter(AADocument.needs_review.is_(True), AADocument.reviewed.is_(False)),
    ).where(AADocument.company_id == company.id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
            AADocument.period_year == year, AADocument.period_quarter == quarter))).one()
    latest = outputs[0] if outputs else None
    forms = await _expected(db, company, year, quarter)
    return PeriodOut(
        company=CompanyBrief.model_validate(company), year=year, quarter=quarter,
        label=period_label(year, quarter, company),
        inputs=PeriodInputsModel(**inputs_to_json(inputs_from_json(period.inputs if period else {}))),
        filed_at=period.filed_at if period else None, document_count=document_count, open_reviews=open_reviews,
        filed_forms={form: FiledFormOut(**entry) for form, entry in
                     (await _filed_forms(db, period, forms)).items()},
        latest_version=latest.version if latest else None,
        stale=bool(latest) and await _is_stale(db, company, year, quarter, latest.created_at),
        books_stale=books_stale(company, latest.created_at if latest else None),
        forms_expected=forms, due_dates=due_dates(forms, year, quarter, company.fiscal_year_end_month),
        outputs=[OutputBrief(id=o.id, version=o.version, created_at=o.created_at, review_open=o.review_open,
                             changes=count_changes(o.diff), amended=o.amended) for o in outputs],
    )


def output_out(output: AAOutput, period: AAPeriod, company: AACompany) -> OutputOut:
    changes = (output.diff or {}).get("forms", {})
    edited_all = output.snapshot.get("edited") or {}
    forms: list[FormOut] = []
    for form in FORM_ORDER:
        values = output.snapshot["forms"].get(form)
        if values is None:
            continue
        changed = changes.get(form, {})
        edited = edited_all.get(form, {})
        items = [ItemOut(key=key, label=label, value=values[key], changed=key in changed,
                         before=changed[key][0] if key in changed else None, engine=edited.get(key))
                 for key, label in form_items(form, values)]
        forms.append(FormOut(form=form, title=FORM_TITLES[form], items=items, pdf=form in PDF_FORMS,
                             payable_item=PAYABLE_ITEM.get(form)))
    return OutputOut(
        id=output.id, company_id=company.id, year=period.year, quarter=period.quarter,
        label=period_label(period.year, period.quarter, company), version=output.version,
        parent_version=output.parent_version, created_at=output.created_at, review_open=output.review_open,
        amended=output.amended, changes=count_changes(output.diff), warnings=list(output.warnings or []),
        forms=forms, ledgers={name: len(rows) for name, rows in output.snapshot["ledgers"].items()},
    )


async def latest_output(db: AsyncSession, period_id: uuid.UUID) -> AAOutput | None:
    return (await db.execute(select(AAOutput).where(AAOutput.period_id == period_id)
                             .order_by(AAOutput.version.desc()).limit(1))).scalar_one_or_none()


async def mark_filed(db: AsyncSession, period: AAPeriod, filed: bool, forms: list[str],
                     filed_on: date | None = None) -> None:
    """Mark every given form filed (and paid on filed_on, default today) from the latest version, or clear them all."""
    latest = await latest_output(db, period.id) if filed else None
    if filed and latest is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Generate a version first")
    before = await _filed_forms(db, period, forms)
    current = (file_all(before, forms, str(latest.id), latest.version, datetime.now(timezone.utc),
                        filed_on or manila_today()) if latest
               else unfile_all(before, forms))
    if any(before.get(f) != current.get(f) for f in ("0619E-M1", "0619E-M2")):  # the 1601-EQ reads them
        period.inputs_updated_at = datetime.now(timezone.utc)
    period.filed_forms = current
    period.filed_at, filed_id = derive(current, forms)
    period.filed_output_id = uuid.UUID(filed_id) if filed_id else None
    company = await db.get(AACompany, period.company_id)
    if company is not None and company.books_start is not None:
        touch_books(company)  # a filed return posts its payment in the books


@router.get("/periods/{company_id}/{year}/{quarter}", response_model=PeriodOut)
async def get_period(
    company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100), quarter: int = PathParam(ge=1, le=4),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    company = await company_or_404(db, scope_for(user), company_id)
    return await _period_out(db, company, year, quarter)


@router.put("/periods/{company_id}/{year}/{quarter}/inputs", response_model=PeriodOut)
async def save_period_inputs(
    body: PeriodInputsModel, company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100),
    quarter: int = PathParam(ge=1, le=4), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    period = await _ensure_period(db, ent, company, year, quarter)
    new_inputs = inputs_to_json(inputs_from_json(body.model_dump(mode="json")))
    audit.record(db, label=f"{year} Q{quarter}",
                 ent=ent, company_id=company.id, user=user, entity="period", entity_id=_audit_period(period),
                 action="inputs", before=period.inputs or {}, after=new_inputs)
    period.inputs = new_inputs
    period.inputs_updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await _period_out(db, company, year, quarter)


@router.put("/periods/{company_id}/{year}/{quarter}/filed", response_model=PeriodOut)
async def set_period_filed(
    body: FiledIn, company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100),
    quarter: int = PathParam(ge=1, le=4), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    await require_filing_rights(db, user, ent)
    company = await company_or_404(db, ent, company_id)
    period = await _ensure_period(db, ent, company, year, quarter)
    before = dict(period.filed_forms or {})
    await mark_filed(db, period, body.filed, await _expected(db, company, year, quarter), body.filed_on)
    audit.record(db, label=f"{year} Q{quarter}",
                 ent=ent, company_id=company.id, user=user, entity="period", entity_id=_audit_period(period),
                 action="filed" if body.filed else "unfiled", before=before, after=dict(period.filed_forms or {}))
    await db.commit()
    return await _period_out(db, company, year, quarter)


@router.put("/periods/{company_id}/{year}/{quarter}/filed-forms/{form}", response_model=PeriodOut)
async def set_form_filed(
    body: FormFiledIn, form: str, company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100),
    quarter: int = PathParam(ge=1, le=4), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    await require_filing_rights(db, user, ent)
    company = await company_or_404(db, ent, company_id)
    period = await _ensure_period(db, ent, company, year, quarter)
    expected = await _expected(db, company, year, quarter)
    if form not in expected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{form} isn't filed for this quarter")
    current = await _filed_forms(db, period, expected)
    before = dict(period.filed_forms or {})
    if body.filed:
        output = (await db.get(AAOutput, body.output_id) if body.output_id
                  else await latest_output(db, period.id))
        if output is None or output.period_id != period.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Generate a version of this quarter first")
        if form not in output.snapshot["forms"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"v{output.version} has no {form}")
        current = set_form(current, form, str(output.id), output.version, datetime.now(timezone.utc),
                           body.filed_on or manila_today())
    else:
        current = unset_form(current, form)
    period.filed_forms = current
    audit.record(db, label=f"{year} Q{quarter} · {form}",
                 ent=ent, company_id=company.id, user=user, entity="period", entity_id=_audit_period(period),
                 action="form_filed" if body.filed else "form_unfiled", before={form: before.get(form)},
                 after={form: current.get(form)})
    period.filed_at, filed_id = derive(current, expected)
    period.filed_output_id = uuid.UUID(filed_id) if filed_id else None
    if form.startswith("0619E-M"):  # the 1601-EQ's items 20–21 read it: the latest version is now stale
        period.inputs_updated_at = datetime.now(timezone.utc)
    if company.books_start is not None:
        touch_books(company)  # a filed return posts its payment in the books
    await db.commit()
    return await _period_out(db, company, year, quarter)


@router.post("/periods/{company_id}/{year}/{quarter}/generate", response_model=OutputOut,
             status_code=status.HTTP_201_CREATED)
async def generate_output(
    company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100), quarter: int = PathParam(ge=1, le=4),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    period = await _ensure_period(db, ent, company, year, quarter)
    facts = company_facts(company)
    assets = await active_assets(db, company)
    filed = await _filed_forms(db, period, await _expected(db, company, year, quarter))
    periods = await load_periods(db, company, year, quarter)
    result = build_quarter(facts, periods, assets=assets, filed_remittances=await _remittances(db, filed))
    book_tabs, book_warnings = await quarter_books(db, company, facts, year, quarter, result, assets, periods)
    result.ledgers.update(book_tabs)
    result.warnings.extend(book_warnings)
    result.ledgers.update(await aging_tabs(db, company, quarter_end(year, quarter, company.fiscal_year_end_month)))
    snap = snapshot(result, facts)
    missing = missing_fields(snap["company"], [f for f in snap["forms"] if f in PDF_FORMS], snap["forms"])
    if missing:
        result.warnings.append("Missing for filing: " + ", ".join(missing) + ". PDFs will be stamped DRAFT until "
                               "the company profile is complete.")
    target = periods[-1].inputs
    changed = amended_forms(filed, snap["forms"], await filed_values(db, filed))
    if (amends_payment(changed) and target.amended_paid_business_tax == 0
            and target.amended_paid_income_tax == 0):
        result.warnings.append(AMENDED_WARNING)
    due = {form: day.isoformat()
           for form, day in due_dates(list(snap["forms"]), year, quarter, company.fiscal_year_end_month).items()}
    output = await store_output(db, ent, user, company, period, snap, result.warnings, result.review_open, due,
                                folder=f"{year}Q{quarter}", amended=bool(changed))
    return output_out(output, period, company)


def _audit_period(period: AAPeriod) -> str:
    """How the audit log names a period: ``2026-Q3`` or ``2026-annual``."""
    return f"{period.year}-annual" if period.quarter == 0 else f"{period.year}-Q{period.quarter}"


async def store_output(db: AsyncSession, ent: uuid.UUID, user: User, company: AACompany, period: AAPeriod,
                       snap: dict, warnings: list[str], review_open: int, due: dict[str, str], *,
                       folder: str, amended: bool, audit_action: str = "generate",
                       audit_extra: dict | None = None) -> AAOutput:
    """Save a new version of a period: diff against the previous one, write both workbooks, insert the row."""
    previous = await latest_output(db, period.id)
    if previous is not None and previous.snapshot.get("edited") and not snap.get("edited"):
        note = dropped_edits_warning(previous.version, previous.snapshot["edited"])
        warnings = [*warnings, note] if note else warnings
    diff = diff_snapshots(previous.snapshot, snap) if previous else None
    version = previous.version + 1 if previous else 1
    parent = previous.version if previous else None

    out_dir = Path(settings.accounting_root) / "accounting" / "outputs" / str(company.id) / folder
    stamp = uuid.uuid4().hex[:8]  # unique names: a losing concurrent request never touches the winner's files
    highlighted, clean = out_dir / f"v{version}-{stamp}.xlsx", out_dir / f"v{version}-{stamp}-clean.xlsx"
    tin = company.tin
    header = {
        "company": company.registered_name,
        "tin": f"{tin[:3]}-{tin[3:6]}-{tin[6:9]}-{company.branch_code}",
        "period": f"FY {period.year} · Annual" if period.quarter == 0 else period_label(period.year, period.quarter,
                                                                                        company),
        "generated": datetime.now(_MANILA).strftime("%Y-%m-%d %H:%M"),
    }

    def _write() -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        common = dict(header=header, snapshot=snap, warnings=warnings, review_open=review_open,
                      due=due, version=version, diff=diff, parent_version=parent)
        write_workbook(highlighted, **common)
        write_workbook(clean, clean=True, **common)

    await asyncio.get_running_loop().run_in_executor(None, _write)
    output = AAOutput(
        id=uuid.uuid4(), enterprise_id=ent, company_id=company.id, period_id=period.id, version=version,
        parent_version=parent,
        snapshot=snap, diff=diff, warnings=warnings, review_open=review_open,
        amended=amended, xlsx_path=str(highlighted), xlsx_clean_path=str(clean),
        created_by=user.id,
    )
    db.add(output)
    audit.record(db, label=f"{_audit_period(period)} v{version}",
                 ent=ent, company_id=company.id, user=user, entity="output", entity_id=output.id,
                 action=audit_action, after={"period": _audit_period(period), "version": version, "amended": amended,
                                             **(audit_extra or {})})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        highlighted.unlink(missing_ok=True)
        clean.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Another version was generated at the same moment. Refresh and try again.")
    return output


async def _output_context(db: AsyncSession, user: User, output_id: uuid.UUID):
    ent = scope_for(user)
    output = (await db.execute(select(AAOutput).where(AAOutput.id == output_id, AAOutput.enterprise_id == ent)
                               )).scalar_one_or_none()
    if output is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Output not found")
    period = await db.get(AAPeriod, output.period_id)
    company = await company_or_404(db, ent, output.company_id)
    return output, period, company


def _file_name(company: AACompany, period: AAPeriod, output: AAOutput, what: str, clean: bool, ext: str) -> str:
    name = re.sub(r"[^A-Za-z0-9 ._-]+", "", company.registered_name).strip() or "company"
    when = "Annual" if period.quarter == 0 else f"Q{period.quarter}"
    return f"{name} {period.year} {when} {what} v{output.version}{' clean' if clean else ''}.{ext}"


@router.get("/outputs/{output_id}", response_model=OutputOut)
async def get_output(output_id: uuid.UUID, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    output, period, company = await _output_context(db, user, output_id)
    return output_out(output, period, company)


@router.get("/outputs/{output_id}/xlsx")
async def download_workbook(output_id: uuid.UUID, clean: bool = Query(default=False),
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    output, period, company = await _output_context(db, user, output_id)
    path = Path(output.xlsx_clean_path if clean else output.xlsx_path)
    if not is_stored_path_safe(str(path)) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook file not found")
    data = await asyncio.get_running_loop().run_in_executor(None, path.read_bytes)
    name = _file_name(company, period, output, "workbook", clean, "xlsx")
    return Response(content=data, media_type=_XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/outputs/{output_id}/xlsx/preview")
async def preview_workbook(output_id: uuid.UUID, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    """The version's workbook (changes highlighted) as sheets of cells, for the in-app preview."""
    from app.services.accounting.xlsx_preview import workbook_preview

    output, _, _ = await _output_context(db, user, output_id)
    path = Path(output.xlsx_path)
    if not is_stored_path_safe(str(path)) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook file not found")
    loop = asyncio.get_running_loop()
    sheets = await loop.run_in_executor(None, lambda: workbook_preview(path.read_bytes()))
    return {"sheets": sheets}


async def _render_pdf(db: AsyncSession, output: AAOutput, period: AAPeriod, company: AACompany, form: str,
                      clean: bool, *, values: dict[str, str] | None = None,
                      highlights: frozenset[str] | None = None) -> bytes:
    """The form's PDF. ``values`` (unsaved hand edits) and ``highlights`` override the version's own."""
    values = output.snapshot["forms"][form] if values is None else values
    c = output.snapshot["company"]
    if highlights is None:
        highlights = frozenset() if clean else frozenset((output.diff or {}).get("forms", {}).get(form, {}))
    expected = ([annual_form(company_facts(company))] if period.quarter == 0
                else await _expected(db, company, period.year, period.quarter))
    filed = await _filed_forms(db, period, expected)
    amended = form_amended(filed, form, output.version, values, (await filed_values(db, filed)).get(form))
    missing = missing_fields(c, [form], {**output.snapshot["forms"], form: values})
    if form == "2550Q":
        fye = c["fiscal_year_end_month"]
        header = Header2550Q(
            tin=c["tin"], rdo_code=c["rdo_code"], name=c["registered_name"], address=c["address"],
            zip_code=c["zip_code"], fiscal_year_end_month=fye, fiscal_year=period.year, quarter=period.quarter,
            period_from=quarter_start(period.year, period.quarter, fye),
            period_to=quarter_end(period.year, period.quarter, fye),
            branch_code=str(c.get("branch_code") or "00000"), contact_number=str(c.get("contact_number") or ""),
            email=str(c.get("email") or ""), classification=str(c.get("taxpayer_classification") or ""),
        )

        def render() -> bytes:
            return render_2550q(values, header, highlights, amended, output.review_open, missing)
    else:
        return_header = header_from_snapshot(c, period.year, period.quarter)

        def render() -> bytes:
            return render_return(form, values, return_header, highlights=highlights, amended=amended,
                                 draft_reviews=output.review_open, missing=missing).pdf
    return await asyncio.get_running_loop().run_in_executor(None, render)


@router.get("/outputs/{output_id}/pdf")
async def download_pdf(output_id: uuid.UUID, form: str = Query(...), clean: bool = Query(default=False),
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    output, period, company = await _output_context(db, user, output_id)
    if form not in PDF_FORMS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There is no PDF for this form")
    if form not in output.snapshot["forms"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"This version has no {form}")
    data = await _render_pdf(db, output, period, company, form, clean)
    name = _file_name(company, period, output, form, clean, "pdf")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/outputs/{output_id}/prepare", response_model=PrepareOut)
async def prepare_returns(output_id: uuid.UUID, scope: Literal["M1", "M2", "M3", "Q"] = Query(...),
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    output, period, company = await _output_context(db, user, output_id)
    if period.quarter == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Annual returns are prepared from the Annual panel")
    expected = await _expected(db, company, period.year, period.quarter)
    filed = await _filed_forms(db, period, expected)
    snap_forms = output.snapshot["forms"]
    forms = [f for f in scope_forms(expected, scope) if f in snap_forms]
    fye = company.fiscal_year_end_month
    due = due_dates(forms, period.year, period.quarter, fye)
    latest = await latest_output(db, period.id)
    was_filed = await filed_values(db, filed)
    stale = latest.id != output.id or await _is_stale(db, company, period.year, period.quarter, output.created_at)
    return PrepareOut(
        scope=scope, label=scope_label(scope, period.year, period.quarter, fye),
        note=scope_note(scope, period.quarter, forms), stale=stale, version=output.version,
        latest_version=latest.version,
        forms=[PrepareFormOut(
            form=f, title=FORM_TITLES[f], guide=guide(f), source=source_line(f, snap_forms[f]), due=due.get(f),
            filed=FiledFormOut(**filed[f]) if f in filed else None, amended=form_amended(filed, f, output.version, snap_forms[f], was_filed.get(f)),
            missing=missing_fields(output.snapshot["company"], [f], snap_forms),
        ) for f in forms],
    )


@router.post("/outputs/{output_id}/pdfs")
async def download_pdfs(output_id: uuid.UUID, body: PdfsIn, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    output, period, company = await _output_context(db, user, output_id)
    expected = ([annual_form(company_facts(company))] if period.quarter == 0
                else await _expected(db, company, period.year, period.quarter))
    try:
        forms = validate_requested(body.forms, expected, output.snapshot["forms"])
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    files = [(_file_name(company, period, output, form, body.clean, "pdf"),
              await _render_pdf(db, output, period, company, form, body.clean)) for form in forms]
    if len(files) == 1:
        name, data = files[0]
        return Response(content=data, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    data = await asyncio.get_running_loop().run_in_executor(None, lambda: zip_pdfs(files))
    name = _file_name(company, period, output, "returns", body.clean, "zip")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


async def aging_tabs(db: AsyncSession, company: AACompany, as_of: date) -> dict[str, list[dict]]:
    """A/R and A/P aging as of the quarter's end, as version ledger tabs (only the ones with open items)."""
    from app.services.accounting.books.subledger import load_subledger
    from app.services.accounting.subledger_report import aging_ledger_rows

    sub = await load_subledger(db, company, as_of)
    tabs = {}
    for kind, name in (("ar", "ARAging"), ("ap", "APAging")):
        rows = aging_ledger_rows([i for i in sub.items if i.doc.kind == kind])
        if rows:
            tabs[name] = rows
    return tabs


@router.get("/outputs/{output_id}/aging")
async def download_aging(output_id: uuid.UUID, kind: Literal["ar", "ap"] = Query(...),
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The version's A/R or A/P aging as of its quarter end, as a PDF (from the stored tab, so it never changes)."""
    from app.services.accounting.books.closing import header_for
    from app.services.accounting.compute.subledger import aging, aging_totals
    from app.services.accounting.subledger_report import aging_pdf, items_from_ledger

    output, period, company = await _output_context(db, user, output_id)
    rows = output.snapshot["ledgers"].get("ARAging" if kind == "ar" else "APAging")
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This version has no open items to age")
    items = items_from_ledger(kind, rows)
    summary = aging(items)
    fye = company.fiscal_year_end_month
    as_of = quarter_end(period.year, period.quarter, fye)
    data = await asyncio.get_running_loop().run_in_executor(
        None, lambda: aging_pdf(header_for(company), kind, as_of, summary, aging_totals(summary), items))
    name = _file_name(company, period, output, "AR aging" if kind == "ar" else "AP aging", False, "pdf")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _certificates_2307(output: AAOutput, period: AAPeriod) -> list[tuple[str, FilledForm]]:
    rows = output.snapshot["ledgers"].get("QAP")
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This version has no payments with expanded withholding")
    c = output.snapshot["company"]
    fye = int(c.get("fiscal_year_end_month") or 12)
    return payee_forms(rows, c, quarter_start(period.year, period.quarter, fye),
                       quarter_end(period.year, period.quarter, fye))


def _cert_or_400(apply, cert, values: dict[str, str]):
    try:
        return apply(cert, values)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


def _inline_pdf(data: bytes, name: str) -> Response:
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/outputs/{output_id}/2307s/certificates", response_model=list[CertificateOut])
async def list_2307s(output_id: uuid.UUID, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    """The version's outgoing 2307s with their editable fields (the preview's list)."""
    output, period, _ = await _output_context(db, user, output_id)
    return [CertificateOut(id=str(i), label=name, fields=[PdfFieldOut(**f) for f in fields_2307(form)])
            for i, (name, form) in enumerate(_certificates_2307(output, period))]


@router.post("/outputs/{output_id}/2307s/preview")
async def preview_2307(output_id: uuid.UUID, body: CertificatePreviewIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    output, period, _ = await _output_context(db, user, output_id)
    certs = _certificates_2307(output, period)
    if not body.id.isdigit() or int(body.id) >= len(certs):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
    name, form = certs[int(body.id)]
    form = _cert_or_400(apply_2307, form, body.values)
    data = await asyncio.get_running_loop().run_in_executor(None, lambda: generate_merged_pdf([form]))
    return _inline_pdf(data, "2307 preview.pdf")


async def _2307_zip(db: AsyncSession, user: User, output_id: uuid.UUID, edits: dict[str, dict[str, str]]):
    output, period, company = await _output_context(db, user, output_id)
    certs = _certificates_2307(output, period)
    unknown = [key for key in edits if not key.isdigit() or int(key) >= len(certs)]
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Some edited certificates are no longer in this version")
    certs = [(name, _cert_or_400(apply_2307, form, edits[str(i)]) if str(i) in edits else form)
             for i, (name, form) in enumerate(certs)]
    data = await asyncio.get_running_loop().run_in_executor(None, lambda: zip_forms(certs))
    name = _file_name(company, period, output, "2307s", False, "zip")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/outputs/{output_id}/2307s")
async def download_2307s(output_id: uuid.UUID, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    return await _2307_zip(db, user, output_id, {})


@router.post("/outputs/{output_id}/2307s")
async def download_edited_2307s(output_id: uuid.UUID, body: CertificatesIn, user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    """The zip with the preview's edits (they only change these files)."""
    return await _2307_zip(db, user, output_id, body.edits)


# --- Hand edits to a return -------------------------------------------------------------------------

def _form_values(output: AAOutput, form: str) -> dict[str, str]:
    if form not in PDF_FORMS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There is no PDF for this form")
    if form not in output.snapshot["forms"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"This version has no {form}")
    return output.snapshot["forms"][form]


def _edits_or_400(values: dict[str, str], edits: dict[str, str]) -> dict[str, str]:
    try:
        return apply_edits(values, edits)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


def _is_edit_warning(text: str) -> bool:
    return text.startswith("Edited by hand in v") or " had hand edits (" in text


@router.post("/outputs/{output_id}/preview")
async def preview_form(output_id: uuid.UUID, body: FormEditIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """The form's PDF with unsaved hand edits; items that differ from the books are highlighted."""
    output, period, company = await _output_context(db, user, output_id)
    values = _form_values(output, body.form)
    changed = _edits_or_400(values, body.values)
    edited = merge_edited((output.snapshot.get("edited") or {}).get(body.form, {}), values, changed)
    data = await _render_pdf(db, output, period, company, body.form, True, values={**values, **changed},
                             highlights=frozenset(edited))
    return _inline_pdf(data, _file_name(company, period, output, body.form, False, "pdf"))


@router.post("/outputs/{output_id}/edits", response_model=OutputOut, status_code=status.HTTP_201_CREATED)
async def save_form_edits(output_id: uuid.UUID, body: FormEditIn, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Save hand edits to a form as the period's next version (so filing, amendments and the books use them).

    Changing a return's figures by hand is gated like filing: with approve-before-close on, managers only."""
    ent = scope_for(user)
    await require_filing_rights(db, user, ent)
    output, period, company = await _output_context(db, user, output_id)
    values = _form_values(output, body.form)
    latest = await latest_output(db, period.id)
    if latest is not None and latest.id != output.id:
        raise HTTPException(status.HTTP_409_CONFLICT, f"v{latest.version} is newer. Edit that version instead.")
    changed = _edits_or_400(values, body.values)
    if not changed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing changed")
    snap = copy.deepcopy(output.snapshot)
    snap["forms"][body.form] = {**values, **changed}
    edited = dict(snap.get("edited") or {})
    edited[body.form] = merge_edited(edited.get(body.form, {}), values, changed)
    snap["edited"] = {form: keys for form, keys in edited.items() if keys}
    warnings = [w for w in output.warnings or [] if not _is_edit_warning(w)]
    note = edits_warning(output.version + 1, snap["edited"])
    if note:
        warnings.append(note)
    fye = company.fiscal_year_end_month
    if period.quarter == 0:
        expected = [annual_form(company_facts(company))]
        due = {form: annual_due_date(form, period.year, fye).isoformat() for form in expected}
        folder = f"{period.year}A"
        touch_books(company)  # Q4's income tax in the books comes from the annual return
    else:
        expected = await _expected(db, company, period.year, period.quarter)
        due = {form: day.isoformat() for form, day in
               due_dates(list(snap["forms"]), period.year, period.quarter, fye).items()}
        folder = f"{period.year}Q{period.quarter}"
    filed = await _filed_forms(db, period, expected)
    amended = amended_forms(filed, snap["forms"], await filed_values(db, filed))
    new = await store_output(
        db, ent, user, company, period, snap, warnings, output.review_open, due, folder=folder,
        amended=bool(amended), audit_action="edit",
        audit_extra={"form": body.form, "edits": {key: {"from": values[key], "to": value}
                                                  for key, value in changed.items()}},
    )
    return output_out(new, period, company)
