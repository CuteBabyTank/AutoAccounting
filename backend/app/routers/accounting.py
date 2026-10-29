"""AutoAccounting phase 1: company databank, uploads, folder tree, documents."""

import asyncio
from dataclasses import dataclass
import re
import shutil
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from fastapi import Path as PathParam
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import RateLimiter
from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.accounting import (
    AAAccount, AAAsset, AABankLine, AABankReconciliation, AACompany, AADocument, AAFile, AAJournalEntry, AAOutput,
    AAPeriod, AASupplierRule, AAUpload,
)
from app.models.user import User, UserRole
from app.routers import (
    accounting_annual, accounting_assistant, accounting_atc, accounting_audit, accounting_bank, accounting_books,
    accounting_checklists,
    accounting_contacts,
    accounting_employees, accounting_imports,
    accounting_periods, accounting_reclassify, accounting_reports, accounting_search, accounting_tasks,
    accounting_recurring, accounting_templates, accounting_writeoff,
    accounting_work,
)
from app.routers.accounting_scope import (
    MANAGER_ROLES as _MANAGER_ROLES, company_or_404 as _company_or_404, scope_for as _scope,
)
from app.schemas.accounting import (
    AffectedPeriodOut, CompanyBrief, CompanyCreateIn, CompanyIn, CompanyOut, ConfirmIn, DocumentOut, DocumentPatch, DuplicatePairOut,
    FolderOut, NotDuplicateIn,
    TreeCompanyOut, UploadFileOut, UploadGroupOut, UploadOut,
)
from app.services.accounting import audit, move_company, pipeline
from app.services.accounting.books.links import relink_receipts
from app.services.accounting.books.chart import locked_message
from app.services.accounting.books.loader import ensure_chart, touch_books
from app.services.accounting.books.books_start import default_books_start
from app.services.accounting.compute.reclassify import document_main_account
from app.services.accounting.review_rules import BULK_MAX, LOCKED_REASON, bulk_targets, flag_locked, sync_receipt_flag
from app.services.accounting import duplicates
from app.services.accounting.classify import document_nature, needs_review_for, rule_conflicts
from app.services.accounting.matching import file_detection_from_json, suggest_groups
from app.services.accounting.jobs import stale_action
from app.services.accounting.periods import period_fields, period_for, quarter_label
from app.services.accounting.storage import (
    UploadRejected, filed_hashes, is_stored_path_safe, read_page_bytes, stream_upload, upload_dir,
)
from app.services.accounting.books import bank as bank_service
from app.services.accounting.tree import TreeCompanyInput, bank_nodes, build_tree, folder_counts, stale_periods
from app.services.usage_service import get_effective_rate_config, get_enterprise_for_user

router = APIRouter()

accounting_upload_limiter = RateLimiter(max_attempts=20, window_seconds=600)

def _require_manager(user: User) -> None:
    if user.role not in _MANAGER_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only owners and managers can change the company databank"
        )


async def _assert_budget(db: AsyncSession, user: User) -> None:
    if user.role == UserRole.ADMIN:
        return
    enterprise = await get_enterprise_for_user(db, user)
    if enterprise is None:
        return
    # Billing is opt-in: until the platform owner sets a page rate, uploads are free.
    flat, tiers = await get_effective_rate_config(db, enterprise)
    if not tiers and not flat:
        return
    if (enterprise.budget or 0) <= 0:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Budget depleted. Contact your administrator to top up before uploading again.",
        )


# --- Companies -----------------------------------------------------------------

@router.get("/companies", response_model=list[CompanyOut])
async def list_companies(
    q: str = Query(default="", max_length=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    stmt = select(AACompany).where(AACompany.enterprise_id == ent)
    term = q.strip()
    if term:
        conds = [AACompany.registered_name.ilike(f"%{term}%")]
        digits = re.sub(r"\D", "", term)
        if digits:
            conds.append(AACompany.tin.like(f"{digits}%"))
        stmt = stmt.where(or_(*conds))
    stmt = stmt.order_by(AACompany.pinned.desc(), AACompany.registered_name).limit(500)
    return (await db.execute(stmt)).scalars().all()


@router.post("/companies", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
async def create_company(
    body: CompanyCreateIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    ent = _scope(user)
    _require_manager(user)
    template = body.coa_template.strip()
    fields = body.model_dump(exclude={"coa_template"})
    if "books_start" not in body.model_fields_set:  # books are on unless the request turns them off (null)
        fields["books_start"] = default_books_start(body.fiscal_year_end_month, None, date.today())
    company = AACompany(id=uuid.uuid4(), enterprise_id=ent, created_by=user.id, **fields)
    db.add(company)
    try:
        await db.flush()  # the TIN clash surfaces here, before the event is added
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A company with this TIN and branch code is already in your databank"
        )
    after = audit.snapshot(company, CompanyIn.model_fields)
    if template:
        await accounting_templates.apply_template(db, company, template)
        after["coa_template"] = template
    audit.record(db, label=company.registered_name,
                 ent=ent, company_id=company.id, user=user, entity="company", entity_id=company.id,
                 action="create", after=after)
    await db.commit()
    return company


_BOOKS_SETTINGS = frozenset({"books_start", "books_kept", "books_signatory", "books_signatory_title"})
_NOT_TAX_FACTS = frozenset({"pinned", "aliases", "owner_names"}) | _BOOKS_SETTINGS


def tax_facts_changed(changed: dict) -> bool:
    """Whether an edit changes what the returns say (anything but pinning, aliases and books settings)."""
    return any(name not in _NOT_TAX_FACTS for name in changed)


def books_settings_changed(changed: dict) -> bool:
    """Whether an edit changes what the book tabs say."""
    return any(name in _BOOKS_SETTINGS for name in changed)


@router.put("/companies/{company_id}", response_model=CompanyOut)
async def update_company(
    company_id: uuid.UUID,
    body: CompanyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    _require_manager(user)
    company = await _company_or_404(db, ent, company_id)
    fiscal_year_changed = body.fiscal_year_end_month != company.fiscal_year_end_month
    changed = {name: value for name, value in body.model_dump().items() if getattr(company, name) != value}
    before = audit.snapshot(company, changed)
    for name, value in changed.items():
        setattr(company, name, value)
    audit.record(db, label=company.registered_name,
                 ent=ent, company_id=company.id, user=user, entity="company", entity_id=company.id,
                 action="update", before=before, after=audit.snapshot(company, changed))
    if tax_facts_changed(changed):
        company.facts_updated_at = datetime.now(timezone.utc)
    if books_settings_changed(changed):
        touch_books(company)
    if "books_start" in changed and company.books_start is not None:  # opening balances sit on the start date
        await db.execute(update(AAJournalEntry).where(
            AAJournalEntry.company_id == company.id, AAJournalEntry.kind == "opening",
        ).values(entry_date=company.books_start))
    if fiscal_year_changed:
        # Stored periods were computed with the old year end; re-file unlocked documents.
        docs = (await db.execute(
            select(AADocument).where(AADocument.company_id == company.id, AADocument.period_locked.is_(False))
        )).scalars().all()
        for doc in docs:
            doc.period_year, doc.period_quarter, doc.period_month = period_fields(
                doc.doc_date, company.fiscal_year_end_month
            )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A company with this TIN and branch code is already in your databank"
        )
    return company


# --- Uploads -------------------------------------------------------------------

async def _upload_out(db: AsyncSession, ent: uuid.UUID, upload_id: uuid.UUID) -> UploadOut:
    upload = (await db.execute(
        select(AAUpload).where(AAUpload.id == upload_id, AAUpload.enterprise_id == ent)
    )).scalar_one_or_none()
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    files = (await db.execute(
        select(AAFile).where(AAFile.upload_id == upload_id).order_by(AAFile.created_at)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    action = None if pipeline.is_running(upload.id) else stale_action(
        upload.status, upload.created_at, upload.updated_at, now)
    if action:
        # The background job died (deploy, restart, scale-in). Claim it so only one reader acts, then resume it
        # where it stopped, or fail it once it is too old so the files can be re-dropped.
        claimed = await db.execute(
            update(AAUpload)
            .where(AAUpload.id == upload.id, AAUpload.status == upload.status, AAUpload.updated_at == upload.updated_at)
            .values(updated_at=now)
        )
        if claimed.rowcount == 1:
            job_status = upload.status
            if action == "resume":
                for f in files:
                    if f.status == "extracting":  # claimed by the dead job; none of its work was committed
                        f.status = "detected"
            else:
                upload.status = "failed"
                for f in files:
                    if f.status in ("uploaded", "detected", "extracting"):
                        f.status = "error"
                        f.error_message = "Processing was interrupted. Drop the file again."
            await db.commit()
            if action == "resume":
                pipeline.resume(upload.id, str(upload.uploaded_by), upload.enterprise_id, job_status)

    groups: list[UploadGroupOut] = []
    if upload.status == "awaiting_confirmation":
        detected = [f for f in files if f.status == "detected"]
        raw_groups = suggest_groups([file_detection_from_json(str(f.id), f.detection or {}) for f in detected])
        ids = {uuid.UUID(g.company_id) for g in raw_groups if g.company_id}
        companies = {
            str(c.id): c
            for c in (await db.execute(
                select(AACompany).where(AACompany.id.in_(list(ids)), AACompany.enterprise_id == ent)
            )).scalars().all()
        } if ids else {}
        names = {str(f.id): f.original_filename for f in files}
        for g in raw_groups:
            company = companies.get(g.company_id) if g.company_id else None
            groups.append(UploadGroupOut(
                key=g.key,
                company=CompanyBrief.model_validate(company) if company else None,
                level=g.level if company or g.level == "unreadable" else "unknown",
                detected_name=g.detected.name,
                detected_tin=g.detected.tin,
                detected_address=g.detected.address,
                file_ids=[uuid.UUID(fid) for fid in g.file_ids],
                file_names=[names[fid] for fid in g.file_ids],
            ))
    affected: list[AffectedPeriodOut] = []
    if upload.status == "done":
        landed = (await db.execute(
            select(AADocument.company_id, AADocument.period_year, AADocument.period_quarter, func.count(AADocument.id))
            .join(AAFile, AAFile.id == AADocument.file_id)
            .where(AAFile.upload_id == upload_id, AADocument.deleted_at.is_(None),
                   AADocument.period_year.is_not(None))
            .group_by(AADocument.company_id, AADocument.period_year, AADocument.period_quarter)
        )).all()
        for company_id, year, quarter, count in landed:
            period = (await db.execute(select(AAPeriod).where(
                AAPeriod.company_id == company_id, AAPeriod.year == year, AAPeriod.quarter == quarter
            ))).scalar_one_or_none()
            if period is None:
                continue
            latest = (await db.execute(select(func.max(AAOutput.version))
                                       .where(AAOutput.period_id == period.id))).scalar()
            if latest is None:
                continue
            company = await db.get(AACompany, company_id)
            affected.append(AffectedPeriodOut(
                company_id=company_id, company_name=company.registered_name, year=year, quarter=quarter,
                label=f"{year} · {quarter_label(quarter, company.fiscal_year_end_month)}",
                latest_version=latest, filed=period.filed_at is not None, new_documents=count,
            ))
    return UploadOut(
        id=upload.id,
        status=upload.status,
        total_files=upload.total_files,
        processed_files=upload.processed_files,
        preselected_company_id=upload.preselected_company_id,
        files=[UploadFileOut.model_validate(f) for f in files],
        groups=groups,
        affected_periods=affected,
    )


@router.post("/uploads", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def create_upload(
    files: list[UploadFile],
    company_id: uuid.UUID | None = Form(default=None),
    # One per file, in order: the browser's hash of a photo it shrank ("" for files sent as they were).
    original_sha256: list[str] = Form(default=[]),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    if settings.environment == "production" and not settings.accounting_dir:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AutoAccounting storage is not configured yet")
    if not accounting_upload_limiter.check_and_record(str(user.id)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many uploads. Please try again later.",
            headers={"Retry-After": "60"},
        )
    await _assert_budget(db, user)
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No files were uploaded")
    if len(files) > settings.max_batch_size:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Upload exceeds the maximum of {settings.max_batch_size} files")
    company = await _company_or_404(db, ent, company_id) if company_id else None

    upload_id = uuid.uuid4()
    dest = upload_dir(upload_id)
    stored = []
    try:
        claims = original_sha256 if len(original_sha256) == len(files) else []
        for i, f in enumerate(files):
            stored.append(await stream_upload(f, dest, claims[i] if claims else None))

        # Dedupe is per company, so it can only happen up front when the company is known;
        # auto-detected drops are deduped atomically when extraction claims each file.
        known: set[str] = set()
        if company:
            live_docs = (
                select(func.count(AADocument.id))
                .where(AADocument.file_id == AAFile.id, AADocument.deleted_at.is_(None))
                .scalar_subquery()
            )
            rows = (await db.execute(
                select(AAFile.sha256, AAFile.company_id, AAFile.status, live_docs).where(
                    AAFile.enterprise_id == ent,
                    AAFile.sha256.in_(list({s.sha256 for s in stored})),
                )
            )).all()
            known = filed_hashes(rows, company.id)

        db.add(AAUpload(
            id=upload_id, enterprise_id=ent, uploaded_by=user.id,
            preselected_company_id=company.id if company else None,
            status="extracting" if company else "detecting",
        ))
        await db.flush()
        fresh = 0
        duplicates: list[str] = []
        for s in stored:
            duplicate = s.sha256 in known
            known.add(s.sha256)
            if duplicate:
                duplicates.append(s.stored_path)
            else:
                fresh += 1
            db.add(AAFile(
                enterprise_id=ent, upload_id=upload_id,
                company_id=company.id if company and not duplicate else None,
                original_filename=s.filename, stored_path=s.stored_path, file_type=s.file_type,
                file_size=s.size, sha256=s.sha256, page_count=s.page_count,
                status="duplicate" if duplicate else "uploaded",
            ))
        upload = await db.get(AAUpload, upload_id)
        upload.total_files = fresh
        if fresh == 0:
            upload.status = "done"
        await db.commit()
    except UploadRejected as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except BaseException:
        # Nothing was recorded (or the commit failed): don't leave unowned files on disk.
        await db.rollback()
        shutil.rmtree(dest, ignore_errors=True)
        raise

    # Duplicate copies are never read, so they aren't kept.
    for path in duplicates:
        Path(path).unlink(missing_ok=True)

    if fresh:
        if company:
            pipeline.start_extraction(upload_id, str(user.id), ent)
        else:
            pipeline.start_detection(upload_id, str(user.id), ent)
    return await _upload_out(db, ent, upload_id)


@router.get("/uploads/pending", response_model=UploadOut | None)
async def get_pending_upload(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The caller's latest upload still waiting for company confirmation, so a reload can resume it."""
    ent = _scope(user)
    upload_id = (await db.execute(
        select(AAUpload.id)
        .where(
            AAUpload.enterprise_id == ent,
            AAUpload.uploaded_by == user.id,
            AAUpload.status == "awaiting_confirmation",
        )
        .order_by(AAUpload.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return await _upload_out(db, ent, upload_id) if upload_id else None


class RecentUploadFileOut(BaseModel):
    id: uuid.UUID
    original_filename: str
    documents: int
    companies: list[CompanyBrief]


class RecentUploadOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    files: list[RecentUploadFileOut]


class UploadMoveIn(BaseModel):
    company_id: uuid.UUID
    file_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class MoveRefusalOut(BaseModel):
    document: str
    reason: str


class UploadMoveOut(BaseModel):
    moved: int
    refused: list[MoveRefusalOut]
    upload: RecentUploadOut | None


async def _recent_upload_out(db: AsyncSession, upload: AAUpload) -> RecentUploadOut | None:
    """The upload's filed files with where their documents are now (None when nothing of it is left)."""
    files = (await db.execute(select(AAFile).where(
        AAFile.upload_id == upload.id, AAFile.status == "extracted").order_by(AAFile.created_at))).scalars().all()
    rows = (await db.execute(
        select(AADocument.file_id, AACompany.id, AACompany.registered_name, AACompany.tin, func.count(AADocument.id))
        .join(AACompany, AACompany.id == AADocument.company_id)
        .where(AADocument.file_id.in_([f.id for f in files]), AADocument.deleted_at.is_(None))
        .group_by(AADocument.file_id, AACompany.id, AACompany.registered_name, AACompany.tin)
    )).all() if files else []
    by_file: dict[uuid.UUID, tuple[int, list[CompanyBrief]]] = {}
    for file_id, company_id, name, tin, count in rows:
        total, companies = by_file.get(file_id, (0, []))
        by_file[file_id] = (total + count, [*companies, CompanyBrief(id=company_id, registered_name=name, tin=tin)])
    out = [RecentUploadFileOut(id=f.id, original_filename=f.original_filename, documents=by_file[f.id][0],
                               companies=by_file[f.id][1]) for f in files if f.id in by_file]
    return RecentUploadOut(id=upload.id, created_at=upload.created_at, files=out) if out else None


@router.get("/uploads/latest", response_model=RecentUploadOut | None)
async def get_latest_upload(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The caller's latest finished upload and where its documents went, so a drop filed under the wrong company
    can be moved in one go."""
    ent = _scope(user)
    upload = (await db.execute(
        select(AAUpload)
        .where(AAUpload.enterprise_id == ent, AAUpload.uploaded_by == user.id, AAUpload.status == "done")
        .order_by(AAUpload.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return await _recent_upload_out(db, upload) if upload else None


@router.post("/uploads/{upload_id}/move-company", response_model=UploadMoveOut)
async def move_upload_to_company(
    upload_id: uuid.UUID, body: UploadMoveIn, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move every document of the chosen files of an upload to another company (each re-sorted for it, as a single
    document move). Documents that can't move yet are listed with the reason; the rest move. A file whose documents
    all moved is filed under the new company too, so dropping it there again is caught as a duplicate."""
    ent = _scope(user)
    upload = (await db.execute(select(AAUpload).where(
        AAUpload.id == upload_id, AAUpload.enterprise_id == ent))).scalar_one_or_none()
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    target = await _company_or_404(db, ent, body.company_id)
    files = {f.id: f for f in (await db.execute(select(AAFile).where(
        AAFile.upload_id == upload.id, AAFile.id.in_(body.file_ids)))).scalars().all()}
    if set(body.file_ids) - set(files):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown file in this upload")

    to = await _move_target(db, ent, target)
    sources: dict[uuid.UUID, AACompany] = {}
    moved, refused = 0, []
    docs = (await db.execute(select(AADocument).where(
        AADocument.file_id.in_(list(files)), AADocument.deleted_at.is_(None), AADocument.company_id != target.id,
    ).order_by(AADocument.file_id, AADocument.page_start))).scalars().all()
    for doc in docs:
        source = sources.get(doc.company_id) or await _company_or_404(db, ent, doc.company_id)
        sources[source.id] = source
        problem = await _move_document(db, ent, user, doc, source, to)
        if problem:
            refused.append(MoveRefusalOut(document=audit.document_label(doc), reason=problem))
        else:
            moved += 1

    await db.flush()
    for f in files.values():
        left = (await db.execute(select(func.count(AADocument.id)).where(
            AADocument.file_id == f.id, AADocument.deleted_at.is_(None), AADocument.company_id != target.id,
        ))).scalar_one()
        if left or f.company_id == target.id:
            continue
        # One active copy of a file per company: if the target already has this file, keep the record where it is.
        clash = (await db.execute(select(AAFile.id).where(
            AAFile.company_id == target.id, AAFile.sha256 == f.sha256, AAFile.id != f.id,
            AAFile.status.in_(("extracting", "extracted"))).limit(1))).first()
        if clash is None:
            f.company_id = target.id
    await _refresh_after_move(db, [*sources.values(), target])
    await db.commit()
    return UploadMoveOut(moved=moved, refused=refused, upload=await _recent_upload_out(db, upload))


@router.get("/uploads/{upload_id}", response_model=UploadOut)
async def get_upload(
    upload_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await _upload_out(db, _scope(user), upload_id)


@router.post("/uploads/{upload_id}/confirm", response_model=UploadOut)
async def confirm_upload(
    upload_id: uuid.UUID,
    body: ConfirmIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    # Claim the upload atomically so a double-click can't start two extractions.
    claimed = await db.execute(
        update(AAUpload)
        .where(AAUpload.id == upload_id, AAUpload.enterprise_id == ent,
               AAUpload.status == "awaiting_confirmation")
        .values(status="confirming")
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload is not waiting for confirmation")

    files = {f.id: f for f in (await db.execute(
        select(AAFile).where(AAFile.upload_id == upload_id, AAFile.status == "detected")
    )).scalars().all()}
    company_ids = {a.company_id for a in body.assignments if a.company_id}
    valid = set((await db.execute(
        select(AACompany.id).where(AACompany.id.in_(list(company_ids)), AACompany.enterprise_id == ent)
    )).scalars()) if company_ids else set()
    if company_ids - valid:
        await db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")

    assigned: set[uuid.UUID] = set()
    for a in body.assignments:
        for fid in a.file_ids:
            if fid not in files or fid in assigned:
                await db.rollback()
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or repeated file in assignments")
            assigned.add(fid)
            if a.skip:
                files[fid].status = "skipped"
            else:
                files[fid].company_id = a.company_id
    if assigned != set(files):
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Every file must be assigned to a company or skipped")

    has_work = any(not a.skip for a in body.assignments)
    for a in body.assignments:
        if a.company_id and not a.skip and a.file_ids:
            audit.record(db, label="Upload",
                         ent=ent, company_id=a.company_id, user=user, entity="upload", entity_id=upload_id,
                         action="confirm", after={"files": [files[fid].original_filename for fid in a.file_ids]})
    upload = await db.get(AAUpload, upload_id)
    upload.status = "extracting" if has_work else "done"
    await db.commit()
    if has_work:
        pipeline.start_extraction(upload_id, str(user.id), ent)
    return await _upload_out(db, ent, upload_id)


@router.post("/uploads/{upload_id}/retry", response_model=UploadOut)
async def retry_upload(
    upload_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read again the files of a finished upload that failed (e.g. the AI service was busy or out of quota)."""
    ent = _scope(user)
    await _assert_budget(db, user)
    failed = (await db.execute(
        select(AAFile).join(AAUpload, AAUpload.id == AAFile.upload_id)
        .where(AAFile.upload_id == upload_id, AAUpload.enterprise_id == ent,
               AAFile.status == "error", AAFile.company_id.is_not(None))
    )).scalars().all()
    if not failed:
        raise HTTPException(status.HTTP_409_CONFLICT, "There are no failed files to retry in this upload")
    claimed = await db.execute(
        update(AAUpload)
        .where(AAUpload.id == upload_id, AAUpload.enterprise_id == ent, AAUpload.status.in_(("done", "failed")))
        .values(status="extracting")
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload is still being processed")
    for f in failed:
        f.status = "uploaded"
        f.error_message = None
    await db.commit()
    pipeline.start_extraction(upload_id, str(user.id), ent)
    return await _upload_out(db, ent, upload_id)


# --- Tree, folders, documents --------------------------------------------------

_PLAIN_FIELDS = (
    "category", "account", "doc_number", "doc_date", "seller_name", "seller_tin", "seller_branch", "seller_address",
    "buyer_name", "buyer_tin", "buyer_branch", "gross_amount", "vatable_amount", "vat_amount", "exempt_amount",
    "zero_rated_amount", "withholding_amount", "vat_treatment", "reviewed", "excluded", "ewt_atc",
    "paid_on", "paid_via", "payment_ref",
)
_NULLABLE_FIELDS = {"doc_date", "paid_on"}
# What a person can change on a document (the audit log diffs these).
_AUDIT_DOC_FIELDS = _PLAIN_FIELDS + ("gl_account_code", "settles_document_id", "period_year", "period_quarter",
                                     "period_month", "period_locked")


def _by_company(rows) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for company_id, year, quarter, at in rows:
        if at is None:
            continue
        per_company = out.setdefault(str(company_id), {})
        per_company[(year, quarter)] = max(per_company.get((year, quarter), at), at)
    return out


def _quarter_status(outputs, filed, doc_changes, input_changes, asset_changes=(), annual_changes=(),
                    facts: dict | None = None) -> dict:
    """(company_id, year, quarter) -> latest_version / stale / filed for the folder tree (quarter 0 = annual)."""
    changes = _by_company([*doc_changes, *input_changes, *asset_changes])
    annual = _by_company(annual_changes)
    generated: dict[str, dict] = {}
    versions: dict[tuple[str, int, int], int] = {}
    for company_id, year, quarter, version, at in outputs:
        generated.setdefault(str(company_id), {})[(year, quarter)] = at
        versions[(str(company_id), year, quarter)] = version
    status_map: dict[tuple[str, int, int], dict] = {}
    for company_id, periods in generated.items():
        stale = stale_periods(changes.get(company_id, {}), periods, always=(facts or {}).get(company_id),
                              annual_changes=annual.get(company_id, {}))
        for year, quarter in periods:
            key = (company_id, year, quarter)
            status_map[key] = {"latest_version": versions[key], "stale": (year, quarter) in stale,
                               "filed": key in filed}
    for key in filed:
        status_map.setdefault(key, {"latest_version": None, "stale": False, "filed": True})
    return status_map


@router.get("/tree", response_model=list[TreeCompanyOut])
async def get_tree(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = _scope(user)
    companies = (await db.execute(
        select(AACompany).where(AACompany.enterprise_id == ent)
        .order_by(AACompany.pinned.desc(), AACompany.registered_name)
    )).scalars().all()
    open_review = case(
        (AADocument.needs_review & ~AADocument.reviewed & ~AADocument.excluded, 1), else_=0
    )
    rows = (await db.execute(
        select(
            AADocument.company_id, AADocument.period_year, AADocument.period_quarter,
            func.count(), func.sum(open_review),
        )
        .where(AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None))
        .group_by(AADocument.company_id, AADocument.period_year, AADocument.period_quarter)
    )).all()
    inputs = [
        TreeCompanyInput(str(c.id), c.registered_name, c.tin, c.pinned, c.fiscal_year_end_month, c.books_start,
                          c.has_employees)
        for c in companies
    ]
    outputs = (await db.execute(
        select(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter, func.max(AAOutput.version),
               func.max(AAOutput.created_at))
        .join(AAOutput, AAOutput.period_id == AAPeriod.id)
        .where(AAPeriod.enterprise_id == ent)
        .group_by(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter)
    )).all()
    filed = {(str(c), y, q) for c, y, q in (await db.execute(
        select(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter)
        .where(AAPeriod.enterprise_id == ent, AAPeriod.filed_at.is_not(None))
    )).all()}
    doc_changes = (await db.execute(
        select(AADocument.company_id, AADocument.period_year, AADocument.period_quarter,
               func.max(func.greatest(AADocument.created_at, AADocument.updated_at,
                                      func.coalesce(AADocument.deleted_at, AADocument.created_at))))
        .where(AADocument.enterprise_id == ent, AADocument.period_year.is_not(None))
        .group_by(AADocument.company_id, AADocument.period_year, AADocument.period_quarter)
    )).all()
    input_changes = (await db.execute(
        select(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter, AAPeriod.inputs_updated_at)
        .where(AAPeriod.enterprise_id == ent, AAPeriod.inputs_updated_at.is_not(None))
    )).all()
    assets = (await db.execute(
        select(AAAsset.company_id, AAAsset.in_service, AAAsset.updated_at).where(AAAsset.enterprise_id == ent)
    )).all()
    fye = {str(c.id): c.fiscal_year_end_month for c in companies}
    asset_changes = []
    for company_id, in_service, at in assets:  # an asset edit feeds its in-service period and every later one
        p = period_for(in_service, fye.get(str(company_id), 12))
        asset_changes.append((company_id, p.fiscal_year, p.quarter, at))
    annual_changes = (await db.execute(
        select(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter, func.max(AAOutput.created_at))
        .join(AAOutput, AAOutput.period_id == AAPeriod.id)
        .where(AAPeriod.enterprise_id == ent)
        .group_by(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter)
    )).all() + (await db.execute(
        select(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter, AAPeriod.filed_at)
        .where(AAPeriod.enterprise_id == ent, AAPeriod.filed_at.is_not(None))
    )).all()
    facts = {str(c.id): c.facts_updated_at for c in companies if c.facts_updated_at is not None}
    status_map = _quarter_status(outputs, filed, doc_changes, input_changes, asset_changes, annual_changes, facts)
    return build_tree(inputs, [tuple(r) for r in rows], status_map, await _bank_tree(db, ent, fye))


async def _bank_tree(db: AsyncSession, ent: uuid.UUID, fye: dict[str, int]) -> dict:
    month = func.date_trunc("month", AABankLine.line_date)
    open_line = case((AABankLine.match_status.in_(("unmatched", "ambiguous", "suggested")), 1), else_=0)
    rows = (await db.execute(
        select(AABankLine.company_id, AABankLine.account_code, month, func.count(), func.sum(open_line))
        .where(AABankLine.enterprise_id == ent, bank_service.live_line()).group_by(AABankLine.company_id, AABankLine.account_code, month)
    )).all()
    if not rows:
        return {}
    reconciled = {(str(c), code, m) for c, code, m in (await db.execute(
        select(AABankReconciliation.company_id, AABankReconciliation.account_code, AABankReconciliation.month_start)
        .where(AABankReconciliation.enterprise_id == ent, AABankReconciliation.voided_at.is_(None)))).all()}
    accounts = {(str(c), code): (name, number or "") for c, code, name, number in (await db.execute(
        select(AAAccount.company_id, AAAccount.code, AAAccount.name, AAAccount.bank_account_no)
        .where(AAAccount.enterprise_id == ent, AAAccount.code.in_({r[1] for r in rows if r[1]})))).all()}
    return bank_nodes([tuple(r) for r in rows], reconciled, accounts, fye)


@router.get("/folders", response_model=FolderOut)
async def get_folder(
    company_id: uuid.UUID,
    year: int | None = Query(default=None, ge=2000, le=2100),
    quarter: int | None = Query(default=None, ge=1, le=4),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    company = await _company_or_404(db, ent, company_id)
    if (year is None) != (quarter is None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pass both year and quarter, or neither for undated")
    stmt = select(AADocument).where(AADocument.company_id == company.id, AADocument.deleted_at.is_(None))
    if year is None:
        stmt = stmt.where(AADocument.period_year.is_(None))
        label = "Undated"
    else:
        stmt = stmt.where(AADocument.period_year == year, AADocument.period_quarter == quarter)
        label = f"{year} · {quarter_label(quarter, company.fiscal_year_end_month)}"
    docs = (await db.execute(
        stmt.order_by(AADocument.doc_date.asc().nulls_last(), AADocument.created_at)
    )).scalars().all()
    return FolderOut(
        company=CompanyBrief.model_validate(company),
        year=year,
        quarter=quarter,
        label=label,
        counts=folder_counts([(d.category, d.needs_review, d.reviewed, d.excluded) for d in docs]),
        documents=_documents_out(docs, company, await accounting_periods.supplier_atc_rules(db, company.id)),
    )


async def _document_or_404(db: AsyncSession, ent: uuid.UUID, doc_id: uuid.UUID) -> AADocument:
    doc = (await db.execute(
        select(AADocument).where(
            AADocument.id == doc_id, AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None)
        )
    )).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


def _apply_period_from_date(doc: AADocument, company: AACompany) -> None:
    doc.period_year, doc.period_quarter, doc.period_month = period_fields(
        doc.doc_date, company.fiscal_year_end_month
    )


async def _learn_supplier_rule(db: AsyncSession, doc: AADocument, learn_atc: bool = False,
                               learn_gl: bool = False) -> None:
    tin = doc.buyer_tin if doc.client_role == "seller" else doc.seller_tin
    if not tin or doc.category not in ("purchases", "expenses"):
        return
    # Atomic upsert: two people correcting the same supplier at once must not 500.
    stmt = pg_insert(AASupplierRule).values(
        id=uuid.uuid4(), company_id=doc.company_id, counterparty_tin=tin, category=doc.category,
        account=doc.account, ewt_atc=doc.ewt_atc if learn_atc else "",
        gl_account_code=doc.gl_account_code if learn_gl else "",
        counterparty_name=(doc.buyer_name if doc.client_role == "seller" else doc.seller_name)[:255],
        updated_at=datetime.now(timezone.utc),
    )
    learned = {"category": stmt.excluded.category, "account": stmt.excluded.account,
               "counterparty_name": stmt.excluded.counterparty_name, "updated_at": stmt.excluded.updated_at}
    if learn_atc:
        learned["ewt_atc"] = stmt.excluded.ewt_atc
    if learn_gl:
        learned["gl_account_code"] = stmt.excluded.gl_account_code
    await db.execute(stmt.on_conflict_do_update(constraint="uq_aa_supplier_rule", set_=learned))


async def _apply_rule_to_supplier_documents(db: AsyncSession, doc: AADocument, user: User) -> int:
    """A corrected category/account also reaches the supplier's documents nobody has reviewed yet (uploaded
    before the rule existed). One the rule doesn't fit (goods vs services) is flagged instead of changed."""
    seller = doc.client_role == "seller"
    tin = doc.buyer_tin if seller else doc.seller_tin
    if not tin or doc.category not in ("purchases", "expenses"):
        return 0
    others = (await db.execute(select(AADocument).where(
        AADocument.company_id == doc.company_id, AADocument.id != doc.id, AADocument.deleted_at.is_(None),
        AADocument.reviewed.is_(False), AADocument.client_role == doc.client_role,
        AADocument.category.in_(("purchases", "expenses")),
        (AADocument.buyer_tin if seller else AADocument.seller_tin) == tin,
    ))).scalars().all()
    changed = 0
    for other in others:
        if (other.category, other.account) == (doc.category, doc.account):
            continue
        if rule_conflicts(document_nature(other.raw), other.account, doc.account):
            if "supplier_rule_mismatch" not in (other.review_reasons or []):
                other.review_reasons = [*(other.review_reasons or []), "supplier_rule_mismatch"]
                other.needs_review = needs_review_for(other.review_reasons)
            continue
        before = audit.snapshot(other, ("category", "account"))
        other.category, other.account = doc.category, doc.account
        audit.record(db, label=audit.document_label(other),
                     ent=other.enterprise_id, company_id=other.company_id, user=user, entity="document",
                     entity_id=other.id, action="supplier_rule", before=before,
                     after=audit.snapshot(other, ("category", "account")),
                     reason=f"Same supplier as document {doc.doc_number or doc.id}, corrected by hand")
        changed += 1
    return changed


def _documents_out(docs, company: AACompany, rules: dict[str, str]) -> list[DocumentOut]:
    out = []
    for doc in docs:
        item = DocumentOut.model_validate(doc)
        item.ewt_atc_effective = accounting_periods.effective_document_atc(doc, company, rules)
        item.ewt_atc_source = accounting_periods.document_atc_source(doc, rules)
        best = accounting_periods.best_document_atc(doc, company)
        item.ewt_atc_best, item.ewt_atc_best_reason = best.atc, best.reason if best.atc else ""
        out.append(item)
    return out


async def _document_out(db: AsyncSession, doc: AADocument, company: AACompany) -> DocumentOut:
    item = _documents_out([doc], company, await accounting_periods.supplier_atc_rules(db, company.id))[0]
    if (item.ewt_atc_source not in ("document", "supplier") and doc.client_role == "buyer" and doc.seller_tin
            and doc.category in ("purchases", "expenses")):
        found = await accounting_atc.suggestions_from_other_companies(db, company, {doc.seller_tin})
        item.ewt_atc_suggestion, item.ewt_atc_suggestion_company = found.get(doc.seller_tin, ("", ""))
    return item


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    ent = _scope(user)
    doc = await _document_or_404(db, ent, doc_id)
    return await _document_out(db, doc, await _company_or_404(db, ent, doc.company_id))


@router.patch("/documents/{doc_id}", response_model=DocumentOut)
async def patch_document(
    doc_id: uuid.UUID,
    body: DocumentPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    doc = await _document_or_404(db, ent, doc_id)
    company = await _company_or_404(db, ent, doc.company_id)
    sent = body.model_fields_set
    before = audit.snapshot(doc, _AUDIT_DOC_FIELDS)
    classifying = bool(sent & {"category", "account", "gl_account_code", "client_role"})
    if classifying:
        chart = await ensure_chart(db, company)
        gl_rules = await accounting_periods.supplier_gl_rules(db, company.id)
        old_main = document_main_account(accounting_periods.doc_line(doc, None, gl_rules), chart)

    for name in _PLAIN_FIELDS:
        if name not in sent:
            continue
        value = getattr(body, name)
        if value is None and name not in _NULLABLE_FIELDS:
            continue
        setattr(doc, name, value)

    if "gl_account_code" in sent:
        code = (body.gl_account_code or "").strip()
        if code:
            account = (await db.execute(select(AAAccount).where(
                AAAccount.company_id == company.id, AAAccount.code == code, AAAccount.active.is_(True),
            ))).scalar_one_or_none()
            if account is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Account {code} isn't an active account in the chart")
            if account.locked and code != doc.gl_account_code:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, locked_message(chart, [code]))
        doc.gl_account_code = code

    if classifying:  # a person can't classify a document into a locked account; moving it out clears the flag
        new_main = document_main_account(accounting_periods.doc_line(doc, None, gl_rules), chart)
        if new_main and chart.locked(new_main) and new_main != old_main:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, locked_message(chart, [new_main]))
        if LOCKED_REASON in (doc.review_reasons or []) and not (new_main and chart.locked(new_main)):
            doc.review_reasons = [r for r in doc.review_reasons if r != LOCKED_REASON]
            doc.needs_review = needs_review_for(doc.review_reasons)

    if "settles_document_id" in sent:
        target_id = body.settles_document_id
        if target_id is not None:
            target = await _document_or_404(db, ent, target_id)
            if (target.id == doc.id or target.company_id != doc.company_id
                    or target.category not in ("sales", "purchases", "expenses", "payroll")
                    or target.client_role != doc.client_role or target.settles_document_id is not None):
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "A receipt can only pay a sale, purchase, expense or payroll document of the "
                                    "same company and side")
        doc.settles_document_id = target_id
        doc.settles_source = "user"   # never re-linked automatically after a person decides
        if "possible_payment" in (doc.review_reasons or []):
            doc.review_reasons = [r for r in doc.review_reasons if r != "possible_payment"]
            doc.needs_review = needs_review_for(doc.review_reasons)

    sync_receipt_flag(doc)   # a seller TIN / number typed in clears the flag; reclassifying may raise it

    if "period_year" in sent:
        if body.period_year is None:
            doc.period_locked = False
            _apply_period_from_date(doc, company)
        else:
            doc.period_year, doc.period_quarter, doc.period_month = body.period_year, body.period_quarter, None
            doc.period_locked = True
    elif "doc_date" in sent and not doc.period_locked:
        _apply_period_from_date(doc, company)

    after = audit.snapshot(doc, _AUDIT_DOC_FIELDS)
    old, new = audit.diff(before, after)
    if new.get("reviewed") is True:  # accepting the flags anyway: record which ones
        new["overridden_reasons"] = list(doc.review_reasons or [])
    audit.record(db, label=audit.document_label(doc),
                 ent=ent, company_id=doc.company_id, user=user, entity="document", entity_id=doc.id,
                 action=audit.document_action(old, new), before=old, after=new, reason=body.reason)

    applied = 0
    if sent & {"category", "account", "ewt_atc", "gl_account_code"}:
        await _learn_supplier_rule(db, doc, learn_atc="ewt_atc" in sent, learn_gl="gl_account_code" in sent)
    if sent & {"category", "account"}:
        applied = await _apply_rule_to_supplier_documents(db, doc, user)

    if sent & {"doc_date", "gross_amount", "withholding_amount", "seller_tin", "buyer_tin", "seller_name",
               "buyer_name", "category", "excluded", "settles_document_id", "paid_on"}:
        await db.flush()
        await relink_receipts(db, doc.company_id)
        await _bank_after_document_change(db, doc, company)
    if sent & {"doc_number", "doc_date", "gross_amount", "seller_tin", "buyer_tin", "seller_name", "buyer_name"}:
        await db.flush()
        await duplicates.refresh_flags(db, doc.company_id)

    await db.commit()
    out = await _document_out(db, doc, company)
    out.rule_applied_to = applied
    return out


class BulkResolveIn(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=BULK_MAX)
    reason_code: str = Field(min_length=1, max_length=40)
    action: Literal["reviewed", "exclude"]
    reason: str = Field(min_length=3, max_length=500)


@router.post("/documents/bulk-resolve")
async def bulk_resolve(body: BulkResolveIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Resolve many documents flagged for the same reason in one go (mark reviewed or exclude), one audit event
    per document; documents that are already resolved or don't carry the reason are skipped and listed."""
    ent = _scope(user)
    ids = list(dict.fromkeys(body.document_ids))
    docs = list((await db.execute(select(AADocument).where(
        AADocument.enterprise_id == ent, AADocument.id.in_(ids)))).scalars().all())
    found = {d.id for d in docs}
    ok, skipped = bulk_targets(docs, body.reason_code)
    reason = body.reason.strip()
    for doc in ok:
        before = audit.snapshot(doc, ("reviewed", "excluded"))
        if body.action == "reviewed":
            doc.reviewed = True
        else:
            doc.excluded = True
        old, new = audit.diff(before, audit.snapshot(doc, ("reviewed", "excluded")))
        if body.action == "reviewed":
            new["overridden_reasons"] = list(doc.review_reasons or [])
        audit.record(db, label=audit.document_label(doc), ent=ent, company_id=doc.company_id, user=user,
                     entity="document", entity_id=doc.id, action=audit.document_action(old, new), before=old,
                     after=new, reason=f"Bulk: {reason}")
    if ok and body.action == "exclude":
        await db.flush()
        for doc in ok:
            if doc.doc_type == "statement":
                await bank_service.statement_document_changed(db, doc)
        for company_id in {d.company_id for d in ok}:
            company = await db.get(AACompany, company_id)
            await relink_receipts(db, company_id)
            if company is not None:
                await bank_service.rematch(db, company)
            await duplicates.refresh_flags(db, company_id)
    await db.commit()
    return {"resolved": [str(d.id) for d in ok],
            "skipped": [{"id": str(i), "why": why} for i, why in skipped]
            + [{"id": str(i), "why": "not found"} for i in ids if i not in found]}


async def _bank_after_document_change(db: AsyncSession, doc: AADocument, company: AACompany | None) -> None:
    """A deleted / excluded statement's lines stop counting; any other document a bank line pays (or could pay)
    changed, so the lines are matched again."""
    if doc.doc_type == "statement":
        await bank_service.statement_document_changed(db, doc)
    elif company is not None:
        await bank_service.rematch(db, company)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    ent = _scope(user)
    doc = await _document_or_404(db, ent, doc_id)
    doc.deleted_at = datetime.now(timezone.utc)
    audit.record(db, label=audit.document_label(doc),
                 ent=ent, company_id=doc.company_id, user=user, entity="document", entity_id=doc.id,
                 action="delete", before=audit.snapshot(doc, ("doc_number", "doc_date", "seller_name", "buyer_name",
                                                              "gross_amount", "category")), after=None)
    await db.flush()
    await relink_receipts(db, doc.company_id)
    await _bank_after_document_change(db, doc, await db.get(AACompany, doc.company_id))
    await duplicates.refresh_flags(db, doc.company_id)  # the copy left behind is no longer a duplicate
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class MoveCompanyIn(BaseModel):
    company_id: uuid.UUID


@dataclass
class _MoveTarget:
    """What re-sorting documents for the target company needs, loaded once per move."""
    company: AACompany
    rules: dict[str, tuple[str, str]]
    other_tins: frozenset[str]
    lock: tuple | None


async def _move_target(db: AsyncSession, ent: uuid.UUID, target: AACompany) -> _MoveTarget:
    rules = {r.counterparty_tin: (r.category, r.account) for r in (await db.execute(
        select(AASupplierRule).where(AASupplierRule.company_id == target.id))).scalars().all()}
    others = frozenset((await db.execute(select(AACompany.tin).where(
        AACompany.enterprise_id == ent, AACompany.id != target.id, AACompany.tin != ""))).scalars().all())
    locks = await pipeline._locked_charts(db, [target.id])
    return _MoveTarget(target, rules, others, locks.get(target.id))


async def _move_document(db: AsyncSession, ent: uuid.UUID, user: User, doc: AADocument, source: AACompany,
                         to: _MoveTarget) -> str | None:
    """Move one document to ``to.company`` (re-sorted, audited, not committed); the reason it can't, else None.
    The caller relinks / rematches / refreshes duplicates of both companies afterwards."""
    target = to.company
    doc_ref = str(doc.id)
    facts = move_company.MoveFacts(
        is_statement=doc.doc_type == "statement",
        has_asset=(await db.execute(select(AAAsset.id).where(AAAsset.document_id == doc.id).limit(1))).first()
        is not None,
        confirmed_bank_match=(await db.execute(select(AABankLine.id).where(
            AABankLine.company_id == source.id, AABankLine.match_status == "confirmed",
            AABankLine.match_kind == "document", AABankLine.matched_ref == doc_ref,
        ).limit(1))).first() is not None,
        written_off=(await db.execute(select(AAJournalEntry.id).where(
            AAJournalEntry.company_id == source.id, AAJournalEntry.deleted_at.is_(None),
            AAJournalEntry.writeoff_items.contains([{"id": doc_ref}]),
        ).limit(1))).first() is not None,
        is_2307_for_a_sale=(await db.execute(select(AADocument.id).where(
            AADocument.company_id == source.id, AADocument.deleted_at.is_(None),
            AADocument.cwt_2307["document_id"].astext == doc_ref,
        ).limit(1))).first() is not None,
    )
    problem = move_company.move_problem(facts)
    if problem:
        return problem

    fields = move_company.resorted_fields(doc, pipeline.company_profile(target), to.rules, to.other_tins)
    if to.lock is not None:  # classified into a locked account: queue it, as extraction does
        checked = {**fields, "seller_tin": doc.seller_tin, "buyer_tin": doc.buyer_tin}
        flag_locked(checked, *to.lock)
        fields["review_reasons"], fields["needs_review"] = checked["review_reasons"], checked["needs_review"]

    before = {"company": source.registered_name, **audit.snapshot(doc, ("category", "period_year", "period_quarter"))}
    # Receipts in the old company that a person linked to this one as the invoice they pay.
    for receipt in (await db.execute(select(AADocument).where(
        AADocument.company_id == source.id, AADocument.settles_document_id == doc.id))).scalars().all():
        receipt.settles_document_id, receipt.settles_source = None, ""
    for name, value in fields.items():
        setattr(doc, name, value)
    doc.company_id = target.id
    after = {"company": target.registered_name, **audit.snapshot(doc, ("category", "period_year", "period_quarter"))}
    for company, action in ((source, "move_out"), (target, "move_in")):
        audit.record(db, label=audit.document_label(doc), ent=ent, company_id=company.id, user=user,
                     entity="document", entity_id=doc.id, action=action, before=before, after=after)
    return None


async def _refresh_after_move(db: AsyncSession, companies: list[AACompany]) -> None:
    await db.flush()
    for company in companies:
        await relink_receipts(db, company.id)
        await bank_service.rematch(db, company)
        await duplicates.refresh_flags(db, company.id)


@router.post("/documents/{doc_id}/move-company", response_model=DocumentOut)
async def move_document_to_company(
    doc_id: uuid.UUID, body: MoveCompanyIn, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move a document to another company of the firm, re-sorted for it (side, folder, account, review flags and
    quarter by its fiscal year). The file stays where it is; only the document moves. Refused (409) while something
    in the old company still depends on it."""
    ent = _scope(user)
    doc = await _document_or_404(db, ent, doc_id)
    source = await _company_or_404(db, ent, doc.company_id)
    target = await _company_or_404(db, ent, body.company_id)
    if target.id == source.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The document is already in this company")
    problem = await _move_document(db, ent, user, doc, source, await _move_target(db, ent, target))
    if problem:
        raise HTTPException(status.HTTP_409_CONFLICT, problem)
    await _refresh_after_move(db, [source, target])
    await db.commit()
    return await _document_out(db, doc, target)


@router.get("/duplicates", response_model=list[DuplicatePairOut])
async def list_duplicates(
    company_id: uuid.UUID,
    year: int | None = Query(default=None, ge=2000, le=2100),
    quarter: int | None = Query(default=None, ge=1, le=4),
    undated: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Possible duplicates across the company, narrowed to pairs touching one folder when one is given."""
    ent = _scope(user)
    company = await _company_or_404(db, ent, company_id)
    pairs, docs = await duplicates.find_pairs(db, company.id)

    def in_folder(d: AADocument) -> bool:
        if undated:
            return d.period_year is None
        if year is not None and quarter is not None:
            return (d.period_year, d.period_quarter) == (year, quarter)
        return True

    pairs = [p for p in pairs if in_folder(docs[p.original]) or in_folder(docs[p.copy])]
    if not pairs:
        return []
    file_ids = {docs[p.original].file_id for p in pairs} | {docs[p.copy].file_id for p in pairs}
    names = dict((await db.execute(
        select(AAFile.id, AAFile.original_filename).where(AAFile.id.in_(file_ids))
    )).all())
    rules = await accounting_periods.supplier_atc_rules(db, company.id)
    out = []
    for p in pairs:
        original, duplicate = _documents_out([docs[p.original], docs[p.copy]], company, rules)
        out.append(DuplicatePairOut(
            original=original, duplicate=duplicate, reason=p.reason,
            original_file=names.get(docs[p.original].file_id, ""),
            duplicate_file=names.get(docs[p.copy].file_id, ""),
        ))
    return out


@router.post("/documents/{doc_id}/not-duplicate", status_code=status.HTTP_204_NO_CONTENT)
async def mark_not_duplicate(
    doc_id: uuid.UUID, body: NotDuplicateIn, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Keep both: this pair is never offered as a duplicate again."""
    ent = _scope(user)
    doc = await _document_or_404(db, ent, doc_id)
    other = await _document_or_404(db, ent, body.other_id)
    if other.company_id != doc.company_id or other.id == doc.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick two different documents of the same company")
    for a, b in ((doc, other), (other, doc)):
        if str(b.id) not in (a.not_duplicate_of or []):
            a.not_duplicate_of = [*(a.not_duplicate_of or []), str(b.id)]
            audit.record(db, label=audit.document_label(a),
                         ent=ent, company_id=a.company_id, user=user, entity="document", entity_id=a.id,
                         action="not_duplicate", after={"kept_with": b.doc_number or str(b.id),
                                                        "kept_with_id": str(b.id)},
                         reason=body.reason, always=True)
    await db.flush()
    await duplicates.refresh_flags(db, doc.company_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/files/{file_id}/pages/{page}")
async def file_page(
    file_id: uuid.UUID,
    page: int = PathParam(ge=1, le=10000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    f = (await db.execute(
        select(AAFile).where(AAFile.id == file_id, AAFile.enterprise_id == ent)
    )).scalar_one_or_none()
    if f is None or page > f.page_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    if not is_stored_path_safe(f.stored_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    result = await asyncio.get_running_loop().run_in_executor(
        None, read_page_bytes, f.stored_path, f.file_type, page
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    data, media_type = result
    return Response(content=data, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


router.include_router(accounting_work.router)
router.include_router(accounting_tasks.router)
router.include_router(accounting_books.router)
router.include_router(accounting_imports.router)
router.include_router(accounting_bank.router)
router.include_router(accounting_contacts.router)
router.include_router(accounting_audit.router)
router.include_router(accounting_employees.router)
router.include_router(accounting_reports.router)
router.include_router(accounting_reclassify.router)
router.include_router(accounting_templates.router)
router.include_router(accounting_recurring.router)
router.include_router(accounting_writeoff.router)
router.include_router(accounting_checklists.router)
router.include_router(accounting_atc.router)
router.include_router(accounting_search.router)
router.include_router(accounting_assistant.router)
# Annual routes first: "/periods/{company}/{year}/annual" would otherwise match the quarter route's {quarter}.
router.include_router(accounting_annual.router)
router.include_router(accounting_periods.router)
