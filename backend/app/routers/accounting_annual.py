"""AutoAccounting phase 4a: the annual income tax return (a year-level period, quarter 0) and the asset register."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import Path as PathParam
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AAAsset, AACompany, AADocument, AAOutput, AAPeriod
from app.models.user import User
from app.routers import accounting_periods as quarters
from app.routers.accounting_scope import company_or_404, require_filing_rights, scope_for
from app.schemas.accounting import (
    AnnualInputsModel, AnnualPeriodOut, AssetOut, AssetPatch, CompanyBrief, FiledIn, OpeningAssetIn, OutputBrief,
    OutputOut,
)
from app.services.accounting import audit
from app.services.accounting.assets import active_assets, is_asset_document, sync_assets, to_asset
from app.services.accounting.books.loader import touch_books
from app.services.accounting.compute.annual import (
    ANNUAL_AMENDED_WARNING, CarryIn, annual_form, build_annual, carry_in_from_snapshot,
)
from app.services.accounting.compute.annual_inputs import (
    AnnualInputs, QuarterSource, annual_inputs_from_json, annual_inputs_to_json,
)
from app.services.accounting.compute.depreciation import depreciation_between, fiscal_year_window
from app.services.accounting.compute.due_dates import annual_due_date, quarter_end
from app.services.accounting.compute.specs import PAYABLE_ITEM
from app.services.accounting.diff import count_changes, snapshot
from app.services.accounting.filing import amended_forms, credited_output_id
from app.services.accounting.periods import period_for

router = APIRouter()
ANNUAL = 0


def _payable(output: AAOutput, form: str) -> Decimal | None:
    raw = output.snapshot.get("forms", {}).get(form, {}).get(PAYABLE_ITEM[form])
    try:
        return Decimal(raw) if raw not in (None, "") else None
    except InvalidOperation:
        return None


async def _filed_or_latest(db: AsyncSession, period: AAPeriod,
                           form: str | None = None) -> tuple[AAOutput | None, AAOutput | None, bool]:
    """(the version credited — the one ``form`` was filed from if recorded, else latest; the latest; filed?)."""
    latest = await quarters.latest_output(db, period.id)
    legacy = str(period.filed_output_id) if period.filed_output_id else None
    filed_id = credited_output_id(period.filed_forms or {}, form, legacy) if form else legacy
    filed = await db.get(AAOutput, uuid.UUID(filed_id)) if filed_id else None
    return filed or latest, latest, filed is not None


async def quarter_sources(db: AsyncSession, company: AACompany, year: int) -> dict[int, QuarterSource]:
    form = "1701Q" if company.taxpayer_type == "individual" else "1702Q"
    periods = (await db.execute(select(AAPeriod).where(
        AAPeriod.company_id == company.id, AAPeriod.year == year, AAPeriod.quarter.between(1, 3),
    ))).scalars().all()
    sources: dict[int, QuarterSource] = {}
    for p in periods:
        chosen, latest, filed = await _filed_or_latest(db, p, form)
        if chosen is None:
            continue
        sources[p.quarter] = QuarterSource(p.quarter, _payable(chosen, form), chosen.version, filed=filed,
                                           latest_version=latest.version if latest else None)
    return sources


async def carry_in_for(db: AsyncSession, company: AACompany, year: int,
                       inputs: AnnualInputs) -> tuple[CarryIn, str, int | None]:
    """The previous year's closing schedules (its filed, else latest, annual version), else the opening inputs."""
    previous = await quarters._get_period(db, company.id, year - 1, ANNUAL)
    if previous is not None:
        chosen, _, _ = await _filed_or_latest(db, previous)
        if chosen is not None:
            return carry_in_from_snapshot(chosen.snapshot.get("carry")), "previous_year", chosen.version
    return CarryIn(inputs.opening_nolco, inputs.opening_excess_mcit), "opening", None


async def _annual_stale(db: AsyncSession, company: AACompany, year: int, generated_at: datetime) -> bool:
    cid = company.id
    _, fy_end = fiscal_year_window(year, company.fiscal_year_end_month)
    times = [
        (await db.execute(select(func.max(func.greatest(
            AADocument.created_at, AADocument.updated_at,
            func.coalesce(AADocument.deleted_at, AADocument.created_at),
        ))).where(AADocument.company_id == cid, AADocument.period_year <= year))).scalar(),
        (await db.execute(select(func.max(AAPeriod.inputs_updated_at)).where(
            AAPeriod.company_id == cid, AAPeriod.year <= year))).scalar(),
        (await db.execute(select(func.max(AAAsset.updated_at)).where(
            AAAsset.company_id == cid, AAAsset.in_service <= fy_end))).scalar(),
        (await db.execute(select(func.max(AAOutput.created_at)).join(AAPeriod, AAOutput.period_id == AAPeriod.id)
                          .where(AAPeriod.company_id == cid, AAPeriod.year == year, AAPeriod.quarter >= 1))).scalar(),
        (await db.execute(select(func.max(AAPeriod.filed_at)).where(
            AAPeriod.company_id == cid, AAPeriod.year == year, AAPeriod.quarter >= 1))).scalar(),
        (await db.execute(select(func.max(AAOutput.created_at)).join(AAPeriod, AAOutput.period_id == AAPeriod.id)
                          .where(AAPeriod.company_id == cid, AAPeriod.year == year - 1,
                                 AAPeriod.quarter == ANNUAL))).scalar(),
        (await db.execute(select(AAPeriod.filed_at).where(
            AAPeriod.company_id == cid, AAPeriod.year == year - 1, AAPeriod.quarter == ANNUAL))).scalar(),
        company.facts_updated_at,
    ]
    return any(t is not None and t > generated_at for t in times)


async def _annual_out(db: AsyncSession, company: AACompany, year: int) -> AnnualPeriodOut:
    period = await quarters._get_period(db, company.id, year, ANNUAL)
    outputs = (await db.execute(select(AAOutput).where(AAOutput.period_id == period.id)
                                .order_by(AAOutput.version.desc()))).scalars().all() if period else []
    document_count, open_reviews = (await db.execute(select(
        func.count(AADocument.id),
        func.count(AADocument.id).filter(AADocument.needs_review.is_(True), AADocument.reviewed.is_(False)),
    ).where(AADocument.company_id == company.id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
            AADocument.period_year == year))).one()
    inputs = annual_inputs_from_json(period.inputs if period else {})
    _, source, previous_version = await carry_in_for(db, company, year, inputs)
    form = annual_form(quarters.company_facts(company))
    latest = outputs[0] if outputs else None
    return AnnualPeriodOut(
        company=CompanyBrief.model_validate(company), year=year, label=quarters.period_label(year, ANNUAL, company),
        form=form, inputs=AnnualInputsModel(**annual_inputs_to_json(inputs)),
        filed_at=period.filed_at if period else None, document_count=document_count, open_reviews=open_reviews,
        latest_version=latest.version if latest else None,
        stale=bool(latest) and await _annual_stale(db, company, year, latest.created_at),
        forms_expected=[form], due_dates={form: annual_due_date(form, year, company.fiscal_year_end_month)},
        outputs=[OutputBrief(id=o.id, version=o.version, created_at=o.created_at, review_open=o.review_open,
                             changes=count_changes(o.diff), amended=o.amended) for o in outputs],
        carry_source=source, previous_year_version=previous_version,
        pre_books_quarters=[q for q in range(1, 5) if company.books_start is not None
                            and quarter_end(year, q, company.fiscal_year_end_month) < company.books_start],
        has_compensation_income=company.has_compensation_income,
    )


@router.get("/periods/{company_id}/{year}/annual", response_model=AnnualPeriodOut)
async def get_annual_period(company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100),
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    company = await company_or_404(db, scope_for(user), company_id)
    return await _annual_out(db, company, year)


@router.put("/periods/{company_id}/{year}/annual/inputs", response_model=AnnualPeriodOut)
async def save_annual_inputs(body: AnnualInputsModel, company_id: uuid.UUID,
                             year: int = PathParam(ge=2000, le=2100), user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    period = await quarters._ensure_period(db, ent, company, year, ANNUAL)
    new_inputs = annual_inputs_to_json(annual_inputs_from_json(body.model_dump(mode="json")))
    audit.record(db, label=f"FY {year} annual",
                 ent=ent, company_id=company.id, user=user, entity="period", entity_id=quarters._audit_period(period),
                 action="inputs", before=period.inputs or {}, after=new_inputs)
    if annual_inputs_from_json(period.inputs).ending_inventory != annual_inputs_from_json(new_inputs).ending_inventory:
        touch_books(company)  # Q4's books fall back to this count
    period.inputs = new_inputs
    period.inputs_updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await _annual_out(db, company, year)


@router.put("/periods/{company_id}/{year}/annual/filed", response_model=AnnualPeriodOut)
async def set_annual_filed(body: FiledIn, company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100),
                           user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    await require_filing_rights(db, user, ent)
    company = await company_or_404(db, ent, company_id)
    period = await quarters._ensure_period(db, ent, company, year, ANNUAL)
    before = dict(period.filed_forms or {})
    await quarters.mark_filed(db, period, body.filed, [annual_form(quarters.company_facts(company))],
                              body.filed_on)
    audit.record(db, label=f"FY {year} annual",
                 ent=ent, company_id=company.id, user=user, entity="period", entity_id=quarters._audit_period(period),
                 action="filed" if body.filed else "unfiled", before=before, after=dict(period.filed_forms or {}))
    await db.commit()
    return await _annual_out(db, company, year)


@router.post("/periods/{company_id}/{year}/annual/generate", response_model=OutputOut,
             status_code=status.HTTP_201_CREATED)
async def generate_annual(company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100),
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    period = await quarters._ensure_period(db, ent, company, year, ANNUAL)
    facts = quarters.company_facts(company)
    inputs = annual_inputs_from_json(period.inputs)
    assets = await active_assets(db, company)
    carry, source, _ = await carry_in_for(db, company, year, inputs)
    result = build_annual(facts, await quarters.load_periods(db, company, year, 4), year, inputs, assets=assets,
                          quarter_sources=await quarter_sources(db, company, year), carry_in=carry,
                          books_start=company.books_start)
    if source == "opening":
        earlier = (await db.execute(select(func.count(AADocument.id)).where(
            AADocument.company_id == company.id, AADocument.deleted_at.is_(None),
            AADocument.period_year == year - 1))).scalar()
        if earlier:
            result.warnings.append(f"FY {year - 1} has no annual output, so NOLCO and excess MCIT come from the "
                                   "opening schedules in this year's inputs. Generate FY "
                                   f"{year - 1}'s annual return to carry its figures forward.")
    snap = snapshot(result, facts)
    snap["carry"] = result.carry_out
    filed = await quarters._filed_forms(db, period, [result.form])
    changed = amended_forms(filed, snap["forms"], await quarters.filed_values(db, filed))
    if changed and inputs.amended_paid_income_tax == 0:
        result.warnings.append(ANNUAL_AMENDED_WARNING)
    due = {result.form: annual_due_date(result.form, year, company.fiscal_year_end_month).isoformat()}
    touch_books(company)  # Q4's income tax in the books comes from this return (saved with the version)
    output = await quarters.store_output(db, ent, user, company, period, snap, result.warnings, result.review_open,
                                         due, folder=f"{year}A", amended=bool(changed))
    return quarters.output_out(output, period, company)


# --- Asset register ------------------------------------------------------------------------------

_ASSET_FIELDS = ("description", "cost", "in_service", "useful_life_months", "end_date")

def _asset_out(row: AAAsset, doc: AADocument | None, year: int, fye: int) -> AssetOut:
    start, end = fiscal_year_window(year, fye)
    active = doc is None or is_asset_document(doc)
    asset = to_asset(row, doc)
    accumulated = depreciation_between(asset, date(1900, 1, 1), end) if active else Decimal("0.00")
    return AssetOut(
        id=row.id, document_id=row.document_id, doc_number=asset.doc_number, doc_date=doc.doc_date if doc else None,
        description=row.description, cost=row.cost, in_service=row.in_service,
        useful_life_months=row.useful_life_months, end_date=row.end_date, active=active,
        this_year=depreciation_between(asset, start, end) if active else Decimal("0.00"),
        accumulated=accumulated, net_book_value=row.cost - accumulated,
    )


def _current_year(company: AACompany) -> int:
    return period_for(date.today(), company.fiscal_year_end_month).fiscal_year


@router.get("/companies/{company_id}/assets", response_model=list[AssetOut])
async def list_assets(company_id: uuid.UUID, year: int | None = Query(default=None, ge=2000, le=2100),
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    company = await company_or_404(db, scope_for(user), company_id)
    await sync_assets(db, company)  # documents filed since the last generation get their rows now
    await db.commit()
    rows = (await db.execute(
        select(AAAsset, AADocument).outerjoin(AADocument, AADocument.id == AAAsset.document_id)
        .where(AAAsset.company_id == company.id).order_by(AAAsset.in_service, AAAsset.description)
    )).all()
    fy = year or _current_year(company)
    return [_asset_out(row, doc, fy, company.fiscal_year_end_month) for row, doc in rows]


@router.patch("/assets/{asset_id}", response_model=AssetOut)
async def patch_asset(asset_id: uuid.UUID, body: AssetPatch, year: int | None = Query(default=None, ge=2000, le=2100),
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    found = (await db.execute(
        select(AAAsset, AADocument).outerjoin(AADocument, AADocument.id == AAAsset.document_id)
        .where(AAAsset.id == asset_id, AAAsset.enterprise_id == ent)
    )).one_or_none()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    row, doc = found
    company = await company_or_404(db, ent, row.company_id)
    before = audit.snapshot(row, _ASSET_FIELDS)
    for name in body.model_fields_set:
        value = getattr(body, name)
        if value is None and name != "end_date":
            continue
        setattr(row, name, value)
    if row.end_date is not None and row.end_date < row.in_service:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The end date can't be before the in-service date")
    audit.record(db, label=row.description,
                 ent=ent, company_id=company.id, user=user, entity="asset", entity_id=row.id, action="update",
                 before=before, after=audit.snapshot(row, _ASSET_FIELDS))
    await db.commit()
    return _asset_out(row, doc, year or _current_year(company), company.fiscal_year_end_month)


@router.post("/companies/{company_id}/assets", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def add_opening_asset(company_id: uuid.UUID, body: OpeningAssetIn,
                            year: int | None = Query(default=None, ge=2000, le=2100),
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """An asset owned before the books start (e.g. the opening balance's property and equipment)."""
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    in_service = body.in_service or company.books_start
    if in_service is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set the books' start date, or give an in-service date")
    row = AAAsset(id=uuid.uuid4(), enterprise_id=ent, company_id=company.id, document_id=None,
                  description=body.description, cost=body.cost, in_service=in_service,
                  useful_life_months=body.useful_life_months)
    db.add(row)
    audit.record(db, label=row.description,
                 ent=ent, company_id=company.id, user=user, entity="asset", entity_id=row.id, action="create",
                 after=audit.snapshot(row, _ASSET_FIELDS))
    if company.books_start is not None:
        touch_books(company)
    await db.commit()
    return _asset_out(row, None, year or _current_year(company), company.fiscal_year_end_month)


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_opening_asset(asset_id: uuid.UUID, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    row = (await db.execute(select(AAAsset).where(AAAsset.id == asset_id, AAAsset.enterprise_id == ent)
                            )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    if row.document_id is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "This asset comes from a document; move or exclude the document instead")
    company = await company_or_404(db, ent, row.company_id)
    audit.record(db, label=row.description,
                 ent=ent, company_id=company.id, user=user, entity="asset", entity_id=row.id, action="delete",
                 before=audit.snapshot(row, _ASSET_FIELDS), after=None)
    await db.delete(row)
    company.facts_updated_at = datetime.now(timezone.utc)  # no row left to date the change: every version is stale
    if company.books_start is not None:
        touch_books(company)
    await db.commit()
