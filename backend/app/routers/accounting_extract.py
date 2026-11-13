"""Extract tab: the firm's formats, and building one from a dropped sample (a draft).

Anyone in the firm with the `extract` area lists formats; owners and managers build, edit, delete and reset them.
A draft belongs to the person who dropped the sample and lives 24 hours. Saving takes only keys, labels, required
flags and check ids from the browser; definitions come from the stored draft (and the current format on edit).
"""

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import export_limiter, extract_ask_limiter, extract_draft_limiter, upload_limiter
from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.accounting import AAExtractDraft, AAExtractFile, AAExtractFormat, AAExtractRecord, AAExtractRun
from app.models.user import User, UserRole
from app.routers.accounting_scope import MANAGER_ROLES, scope_for
from app.services.accounting import audit, gemini
from app.services.accounting.assignment import lock_firm
from app.services.accounting.extract import builder, checks, export, formats, guard, runner, spec
from app.services.accounting.pipeline import READER_DOWN_MESSAGE
from app.services.accounting.xlsx_preview import workbook_preview
from app.services.accounting.storage import (
    UploadRejected, extract_draft_dir, extract_run_dir, read_page_bytes, stream_upload,
)
from app.services.usage_service import (
    assert_pending_page_budget, charge_for_pages, get_enterprise_for_user, increment_usage, upload_budget_refusal,
)

router = APIRouter(prefix="/extract")
logger = logging.getLogger(__name__)

UNREADABLE_MESSAGE = "We couldn't read this sample. Try a clearer copy."
DRAFT_GONE_MESSAGE = "This sample is no longer available. Drop it again."
NAME_TAKEN_MESSAGE = "A format with this name already exists"


class PickIn(BaseModel):
    key: str = Field(max_length=spec.MAX_KEY)
    label: str = Field(default="", max_length=200)
    required: bool = False


class FormatIn(BaseModel):
    draft_id: uuid.UUID | None = None
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=1000)
    picks: list[PickIn] = Field(max_length=2 * spec.MAX_FIELDS)
    check_ids: list[str] = Field(default_factory=list, max_length=200)


class MissingIn(BaseModel):
    note: str = Field(max_length=1000)  # guard.field_names refuses anything over NOTE_MAX with its own message


def _require_manager(user: User) -> None:
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners and managers can change Extract formats")


async def _precheck_budget(db: AsyncSession, user: User) -> None:
    """Refuse a sample at once when billing is on and no page could be paid for (as uploads do)."""
    if user.role == UserRole.ADMIN:
        return
    enterprise = await get_enterprise_for_user(db, user)
    if enterprise is None:
        return
    refusal = await upload_budget_refusal(db, enterprise)
    if refusal:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, refusal)


async def _charge(db: AsyncSession, ent: uuid.UUID, pages: int) -> None:
    """Bill the sample's pages to the firm like upload pages (a platform-admin scope is never billed)."""
    owner = await db.get(User, ent)  # users is outside accounting RLS
    if owner is None or owner.role != UserRole.ENTERPRISE:
        return
    await charge_for_pages(db, owner, pages)  # locks the owner row first, then the month's usage row
    await increment_usage(db, ent, pages)


async def _draft_or_404(db: AsyncSession, ent: uuid.UUID, user: User, draft_id: uuid.UUID) -> AAExtractDraft:
    """The person's own live draft, locked; anyone else's, another firm's or an expired one is the same 404."""
    row = (await db.execute(select(AAExtractDraft).where(
        AAExtractDraft.id == draft_id, AAExtractDraft.enterprise_id == ent, AAExtractDraft.created_by == user.id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None or formats.draft_expired(row.created_at, datetime.now(timezone.utc)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, DRAFT_GONE_MESSAGE)
    return row


async def _format_or_404(db: AsyncSession, ent: uuid.UUID, format_id: str) -> AAExtractFormat:
    try:
        fid = uuid.UUID(format_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Format not found") from None
    row = (await db.execute(select(AAExtractFormat).where(
        AAExtractFormat.id == fid, AAExtractFormat.enterprise_id == ent, AAExtractFormat.deleted_at.is_(None),
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Format not found")
    return row


def _reader_error(exc: Exception) -> HTTPException:
    if isinstance(exc, gemini.ReaderUnavailable):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, READER_DOWN_MESSAGE)
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, UNREADABLE_MESSAGE)


def _name(body: FormatIn, base_key: str | None) -> str:
    name = spec.clean_text(body.name, spec.MAX_LABEL)
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A format needs a name")
    if formats.builtin_name_clash(name, base_key):
        raise HTTPException(status.HTTP_409_CONFLICT, NAME_TAKEN_MESSAGE)
    return name


def _picked(known: dict, body: FormatIn) -> tuple[list[dict], list[dict]]:
    try:
        return formats.build_save(known, [p.model_dump() for p in body.picks], body.check_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


async def _flush_or_409(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_aa_extract_format_base" in str(exc.orig):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This built-in format already has a firm copy; edit that instead") from None
        raise HTTPException(status.HTTP_409_CONFLICT, NAME_TAKEN_MESSAGE) from None


def _audit_view(row: AAExtractFormat) -> dict:
    return formats.audit_view(row.name, row.description, row.version, row.fields or [], row.checks or [])


# ── formats ───────────────────────────────────────────────────────────────

@router.get("/formats")
async def list_formats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return [formats.out(f) for f in await formats.firm_formats(db, scope_for(user))]


@router.post("/formats", status_code=status.HTTP_201_CREATED)
async def create_format(body: FormatIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Save a new format from a draft. A draft started from a built-in makes the firm's copy of it."""
    _require_manager(user)
    ent = scope_for(user)
    if body.draft_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Drop a sample first")
    draft = await _draft_or_404(db, ent, user, body.draft_id)
    name = _name(body, draft.base_key)
    known = draft.proposal
    fields, checks = _picked(known, body)
    row = AAExtractFormat(id=uuid.uuid4(), enterprise_id=ent, name=name,
                          description=spec.clean_text(body.description, spec.MAX_DESCRIPTION),
                          base_key=draft.base_key, fields=fields, checks=checks,
                          detect_hint=spec.clean_text(known.get("detect_hint"), spec.MAX_DESCRIPTION), version=1,
                          created_by=user.id, updated_by=user.id)
    db.add(row)
    await _flush_or_409(db)
    audit.record(db, ent=ent, company_id=None, user=user, entity="extract_format", entity_id=row.id,
                 action="create", before=None, after=_audit_view(row), label=row.name)
    draft_id, stored_path = draft.id, draft.stored_path
    await db.delete(draft)
    await db.commit()
    await builder.remove_sample(draft_id, stored_path)
    logger.info("extract_format_created format_id=%s base_key=%s fields=%d checks=%d",
                row.id, row.base_key, len(fields), len(checks))
    return formats.out(formats.from_row(row))


@router.put("/formats/{format_id}")
async def update_format(format_id: str, body: FormatIn, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Edit a firm format (a built-in key is not a firm format: copy it with `POST /formats` instead)."""
    _require_manager(user)
    ent = scope_for(user)
    row = await _format_or_404(db, ent, format_id)
    draft = None
    if body.draft_id is not None:
        draft = await _draft_or_404(db, ent, user, body.draft_id)
        if draft.format_id != row.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sample was dropped for another format")
    name = _name(body, row.base_key)
    known = formats.known_for_save(formats.from_row(row), draft.proposal if draft else None)
    fields, checks = _picked(known, body)
    before = _audit_view(row)
    row.name = name
    row.description = spec.clean_text(body.description, spec.MAX_DESCRIPTION)
    row.fields, row.checks = fields, checks
    row.detect_hint = spec.clean_text(known.get("detect_hint"), spec.MAX_DESCRIPTION) or row.detect_hint
    row.version += 1
    row.updated_by = user.id
    await _flush_or_409(db)
    audit.record(db, ent=ent, company_id=None, user=user, entity="extract_format", entity_id=row.id,
                 action="update", before=before, after=_audit_view(row), label=row.name)
    sample = (draft.id, draft.stored_path) if draft else None
    if draft is not None:
        await db.delete(draft)
    await db.commit()
    if sample:
        await builder.remove_sample(*sample)
    return formats.out(formats.from_row(row))


@router.delete("/formats/{format_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_format(format_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Delete a firm format; for a firm copy of a built-in this is "Reset to original"."""
    _require_manager(user)
    ent = scope_for(user)
    row = await _format_or_404(db, ent, format_id)
    row.deleted_at = datetime.now(timezone.utc)
    row.updated_by = user.id
    audit.record(db, ent=ent, company_id=None, user=user, entity="extract_format", entity_id=row.id,
                 action="reset" if row.base_key else "delete", before=_audit_view(row), after=None, label=row.name)
    await db.commit()


# ── drafts ────────────────────────────────────────────────────────────────

@router.post("/drafts", status_code=status.HTTP_201_CREATED)
async def create_draft(file: UploadFile = File(...), format_key: str | None = Form(default=None),
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Read a sample and propose a format (merged onto `format_key`'s fields when editing one)."""
    _require_manager(user)
    ent = scope_for(user)
    if settings.environment == "production" and not settings.accounting_dir:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AutoAccounting storage is not configured yet")
    if not extract_draft_limiter.check_and_record(str(user.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many samples. Please try again later.",
                            headers={"Retry-After": "60"})
    current = None
    if format_key:
        current = formats.find(await formats.firm_formats(db, ent), format_key)
        if current is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Format not found")
    await _precheck_budget(db, user)
    await builder.purge_drafts(db, ent)
    await db.commit()  # nothing stays open while the sample is stored and read

    draft_id = uuid.uuid4()
    try:
        try:
            stored = await stream_upload(file, extract_draft_dir(draft_id))
        except UploadRejected as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        try:
            proposal = await builder.propose(stored.stored_path, stored.file_type, str(user.id))
        except (gemini.ReaderUnavailable, ValueError) as exc:
            logger.warning("extract_draft_unread draft_id=%s error=%s", draft_id, type(exc).__name__)
            raise _reader_error(exc) from None
        proposal = formats.merge_for_edit(current, proposal) if current else formats.fresh_proposal(proposal)
        db.add(AAExtractDraft(
            id=draft_id, enterprise_id=ent, created_by=user.id,
            format_id=None if current is None or current["builtin"] else uuid.UUID(current["key"]),
            base_key=current["key"] if current is not None and current["builtin"] else None,
            stored_path=stored.stored_path, file_type=stored.file_type, page_count=stored.page_count,
            proposal=proposal, asks=0, added=0,
        ))
        await db.flush()
        await _charge(db, ent, min(stored.page_count, builder.SAMPLE_PAGES))
        await db.commit()
    except BaseException:
        await db.rollback()
        await builder.remove_sample(draft_id)
        raise
    logger.info("extract_draft_created draft_id=%s pages=%d fields=%d checks=%d",
                draft_id, stored.page_count, len(proposal["fields"]), len(proposal["checks"]))
    return formats.draft_out(draft_id, proposal, 0, stored.page_count)


@router.post("/drafts/{draft_id}/missing")
async def ask_missing(draft_id: uuid.UUID, body: MissingIn, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """Look on the sample for fields the person names; found ones join the draft switched on."""
    _require_manager(user)
    ent = scope_for(user)
    draft = await _draft_or_404(db, ent, user, draft_id)
    try:
        names = guard.field_names(body.note)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    problem = formats.ask_problem(draft.asks, draft.added)
    if problem:
        raise HTTPException(status.HTTP_409_CONFLICT, problem)
    if not extract_ask_limiter.check_and_record(str(user.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many tries. Please try again later.",
                            headers={"Retry-After": "60"})
    draft.asks += 1  # taken before the read, so overlapping asks can't pass the per-draft limit
    stored_path, file_type = draft.stored_path, draft.file_type
    await db.commit()  # the draft is not locked while the reader works

    try:
        found = await builder.find_missing(stored_path, file_type, names, str(user.id))
    except (gemini.ReaderUnavailable, ValueError) as exc:
        logger.warning("extract_missing_unread draft_id=%s error=%s", draft_id, type(exc).__name__)
        draft = await _draft_or_404(db, ent, user, draft_id)
        draft.asks = max(0, draft.asks - 1)  # the reader failed: the try is given back
        await db.commit()
        raise _reader_error(exc) from None

    draft = await _draft_or_404(db, ent, user, draft_id)
    proposal, added = formats.append_found(draft.proposal, found, guard.ADDED_PER_DRAFT - draft.added)
    draft.proposal = proposal
    draft.added += len(added)
    asks_left = max(0, guard.ASKS_PER_DRAFT - draft.asks)
    await db.commit()
    return {"added": added, "not_found": formats.not_found(names, found), "asks_left": asks_left,
            "checks": formats.draft_out(draft.id, proposal, draft.asks, draft.page_count)["checks"]}


# ── runs ──────────────────────────────────────────────────────────────────

RUN_NOT_FOUND = "Run not found"


class EditIn(BaseModel):
    key: str = Field(max_length=spec.MAX_KEY)
    row: int | None = Field(default=None, ge=0, le=checks.MAX_ROWS)
    value: str = Field(default="", max_length=runner.MAX_EDIT_CHARS)


class EditsIn(BaseModel):
    edits: list[EditIn] = Field(max_length=runner.MAX_EDITS)


class FileFormatIn(BaseModel):
    format_key: str = Field(max_length=40)


def _uuid_or_404(value: str, message: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, message) from None


async def _run_or_404(db: AsyncSession, ent: uuid.UUID, run_id: str, lock: bool = False) -> AAExtractRun:
    """The firm's live run; another firm's, a deleted or a missing one is the same 404."""
    q = select(AAExtractRun).where(AAExtractRun.id == _uuid_or_404(run_id, RUN_NOT_FOUND),
                                   AAExtractRun.enterprise_id == ent, AAExtractRun.deleted_at.is_(None))
    if lock:
        q = q.with_for_update()
    row = (await db.execute(q.execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, RUN_NOT_FOUND)
    return row


async def _file_or_404(db: AsyncSession, ent: uuid.UUID, file_id: str, lock: bool = False,
                       message: str = "File not found") -> tuple[AAExtractFile, AAExtractRun]:
    q = select(AAExtractFile, AAExtractRun).join(AAExtractRun, AAExtractRun.id == AAExtractFile.run_id).where(
        AAExtractFile.id == _uuid_or_404(file_id, message), AAExtractFile.enterprise_id == ent,
        AAExtractRun.enterprise_id == ent, AAExtractRun.deleted_at.is_(None))
    if lock:
        q = q.with_for_update(of=AAExtractFile)
    row = (await db.execute(q.execution_options(populate_existing=True))).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, message)
    return row[0], row[1]


async def _reserve_pages(db: AsyncSession, user: User) -> None:
    """The upload pipeline's admission check; the firm's unread Extract files (this run's, flushed, included) are
    pending pages there, under the firm row lock."""
    if user.role == UserRole.ADMIN:
        return
    enterprise = await get_enterprise_for_user(db, user)
    if enterprise is None:
        return
    try:
        await assert_pending_page_budget(db, enterprise)
    except ValueError as exc:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(exc)) from None


def _person(u: User | None) -> str:
    return (u.nickname or u.email) if u is not None else ""


def _file_out(f: AAExtractFile) -> dict:
    return {"id": str(f.id), "name": f.original_name, "file_type": f.file_type, "page_count": f.page_count,
            "status": f.status, "format_key": f.format_key, "detect_confidence": f.detect_confidence,
            "error": f.error or "", "interrupts": f.interrupts or 0}


def _record_out(r: AAExtractRecord) -> dict:
    return {"id": str(r.id), "file_id": str(r.file_id), "position": r.position, "page_start": r.page_start,
            "page_end": r.page_end, "confidence": r.confidence, "values": r.values, "edited": r.edited or [],
            "bad_cells": r.bad_cells or [], "flags": r.flags or []}


async def _recover(db: AsyncSession, ent: uuid.UUID, run: AAExtractRun, files: list[AAExtractFile]) -> None:
    """A run whose job died (deploy, restart): claim it so one reader acts, then resume or fail it."""
    now = datetime.now(timezone.utc)
    action = None if runner.is_running(run.id) else runner.stale(
        run.status, run.created_at, [run.updated_at, *(f.updated_at for f in files)], now)
    if action is None:
        return
    claimed = await db.execute(update(AAExtractRun).where(
        AAExtractRun.id == run.id, AAExtractRun.enterprise_id == ent, AAExtractRun.status == "reading",
        AAExtractRun.updated_at == run.updated_at).values(updated_at=now))
    if claimed.rowcount != 1:
        await db.rollback()
        return
    plan = runner.recovery(action, [(f.id, f.status, f.interrupts or 0) for f in files])
    for f in files:
        if f.id in plan:
            f.status, f.interrupts, f.error = plan[f.id]
            if f.status == "error":
                logger.warning("extract_file_set_aside file_id=%s interrupts=%d action=%s",
                               f.id, f.interrupts, action)
    run.status = runner.run_status([f.status for f in files])
    run.updated_at = now
    run_id, still_reading, creator, firm = run.id, run.status == "reading", run.created_by, run.enterprise_id
    await db.commit()
    logger.info("extract_run_recovered run_id=%s action=%s", run_id, action)
    if still_reading:
        runner.resume(run_id, str(creator or firm), firm)


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_run(files: list[UploadFile] = File(...), format_key: str = Form(..., max_length=40),
                     user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Drop files against a format (or `auto`); they are read in the background."""
    ent = scope_for(user)
    if settings.environment == "production" and not settings.accounting_dir:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AutoAccounting storage is not configured yet")
    if not upload_limiter.check_and_record(str(user.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many uploads. Please try again later.",
                            headers={"Retry-After": "60"})
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No files were uploaded")
    if len(files) > settings.max_batch_size:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Upload exceeds the maximum of {settings.max_batch_size} files")
    try:
        snapshots = runner.snapshots_for(await formats.firm_formats(db, ent), format_key)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Format not found") from None
    if not snapshots:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There are no formats to detect")
    await _precheck_budget(db, user)
    await db.commit()  # nothing stays open while the files are stored

    auto = format_key == runner.AUTO
    single = None if auto else next(iter(snapshots))
    run_id = uuid.uuid4()
    try:
        stored = []
        try:
            for f in files:
                stored.append(await stream_upload(f, extract_run_dir(run_id)))
        except UploadRejected as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        db.add(AAExtractRun(id=run_id, enterprise_id=ent, format_key=runner.AUTO if auto else single,
                            format_name=runner.AUTO_NAME if auto else snapshots[single]["name"],
                            snapshots=snapshots, status="reading", created_by=user.id))
        await db.flush()
        db.add_all([AAExtractFile(enterprise_id=ent, run_id=run_id, original_name=s.filename,
                                  stored_path=s.stored_path, file_type=s.file_type, sha256=s.sha256,
                                  page_count=s.page_count, status="queued", format_key=single) for s in stored])
        await db.flush()
        await _reserve_pages(db, user)
        await db.commit()
    except BaseException:
        await db.rollback()
        await runner.remove_files(run_id)
        raise
    logger.info("extract_run_created run_id=%s format_key=%s files=%d pages=%d", run_id,
                runner.AUTO if auto else single, len(stored), sum(s.page_count for s in stored))
    runner.start(run_id, str(user.id), ent)
    return {"id": str(run_id)}


@router.get("/runs")
async def list_runs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The firm's latest runs ("Past extracts"), newest first."""
    ent = scope_for(user)
    rows = (await db.execute(
        select(AAExtractRun, User).outerjoin(User, User.id == AAExtractRun.created_by)
        .where(AAExtractRun.enterprise_id == ent, AAExtractRun.deleted_at.is_(None))
        .order_by(AAExtractRun.created_at.desc(), AAExtractRun.id).limit(runner.RUNS_LISTED)
    )).all()
    ids = [run.id for run, _ in rows]
    files: dict[uuid.UUID, int] = {}
    counts: dict[uuid.UUID, tuple[int, int, int]] = {}
    if ids:
        files = dict((await db.execute(
            select(AAExtractFile.run_id, func.count(AAExtractFile.id))
            .where(AAExtractFile.enterprise_id == ent, AAExtractFile.run_id.in_(ids))
            .group_by(AAExtractFile.run_id))).all())
        red = AAExtractRecord.flags.contains([{"level": "red"}])
        yellow = and_(AAExtractRecord.flags.contains([{"level": "yellow"}]), ~red)
        counts = {run_id: (n, r, y) for run_id, n, r, y in (await db.execute(
            select(AAExtractRecord.run_id, func.count(AAExtractRecord.id),
                   func.count(AAExtractRecord.id).filter(red), func.count(AAExtractRecord.id).filter(yellow))
            .where(AAExtractRecord.enterprise_id == ent, AAExtractRecord.run_id.in_(ids))
            .group_by(AAExtractRecord.run_id))).all()}
    out = []
    for run, creator in rows:
        n, r, y = counts.get(run.id, (0, 0, 0))
        out.append({"id": str(run.id), "format_key": run.format_key, "format_name": run.format_name,
                    "status": run.status, "created_at": run.created_at.isoformat(),
                    "created_by": str(run.created_by) if run.created_by else None, "created_by_name": _person(creator),
                    "file_count": files.get(run.id, 0), "record_count": n, "red_count": r, "yellow_count": y})
    return out


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """A run with its files, format snapshots and per-format record counts (records are paged by
    `GET /runs/{id}/records`); resumes a run whose job died."""
    ent = scope_for(user)
    run = await _run_or_404(db, ent, run_id)
    files = list((await db.execute(select(AAExtractFile).where(
        AAExtractFile.run_id == run.id, AAExtractFile.enterprise_id == ent,
    ).order_by(AAExtractFile.created_at, AAExtractFile.id))).scalars())
    await _recover(db, ent, run, files)
    run = await _run_or_404(db, ent, run_id)
    files = list((await db.execute(select(AAExtractFile).where(
        AAExtractFile.run_id == run.id, AAExtractFile.enterprise_id == ent,
    ).order_by(AAExtractFile.created_at, AAExtractFile.id).execution_options(populate_existing=True))).scalars())
    red = AAExtractRecord.flags.contains([{"level": "red"}])
    yellow = and_(AAExtractRecord.flags.contains([{"level": "yellow"}]), ~red)
    counts = {key: (n, r, y) for key, n, r, y in (await db.execute(
        select(AAExtractFile.format_key, func.count(AAExtractRecord.id), func.count(AAExtractRecord.id).filter(red),
               func.count(AAExtractRecord.id).filter(yellow))
        .join(AAExtractFile, AAExtractFile.id == AAExtractRecord.file_id)
        .where(AAExtractRecord.run_id == run.id, AAExtractRecord.enterprise_id == ent,
               AAExtractFile.enterprise_id == ent)
        .group_by(AAExtractFile.format_key))).all()}
    creator = await db.get(User, run.created_by) if run.created_by else None
    may_delete = user.role in MANAGER_ROLES or run.created_by == user.id
    snapshots = run.snapshots or {}
    return {"id": str(run.id), "format_key": run.format_key, "format_name": run.format_name, "status": run.status,
            "created_at": run.created_at.isoformat(), "created_by": str(run.created_by) if run.created_by else None,
            "created_by_name": _person(creator), "can_delete": may_delete,
            "snapshots": {k: formats.out({**v, "key": k}) for k, v in snapshots.items()},
            "files": [_file_out(f) for f in files],
            "formats": runner.format_summary(snapshots, [f.format_key for f in files], counts)}


@router.get("/runs/{run_id}/records")
async def run_records(run_id: str, format_key: str | None = Query(default=None, max_length=40),
                      offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=200),
                      review_only: bool = False, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """One page of a run's records for one format, in file then position order; `review_only` keeps flagged ones.
    `format_key` is needed when records were read with more than one format."""
    ent = scope_for(user)
    run = await _run_or_404(db, ent, run_id)
    with_records = list((await db.execute(
        select(AAExtractFile.format_key).join(AAExtractRecord, AAExtractRecord.file_id == AAExtractFile.id)
        .where(AAExtractFile.run_id == run.id, AAExtractFile.enterprise_id == ent,
               AAExtractRecord.enterprise_id == ent).distinct())).scalars())
    try:
        key = runner.records_format(format_key, with_records, run.snapshots or {})
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    where = [AAExtractRecord.run_id == run.id, AAExtractRecord.enterprise_id == ent,
             AAExtractFile.enterprise_id == ent]
    if key is not None:
        where.append(AAExtractFile.format_key == key)
    if review_only:
        where.append(func.jsonb_array_length(AAExtractRecord.flags) > 0)
    joined = select(AAExtractRecord).join(AAExtractFile, AAExtractFile.id == AAExtractRecord.file_id).where(*where)
    total = (await db.execute(select(func.count()).select_from(joined.subquery()))).scalar_one()
    rows = (await db.execute(joined.order_by(AAExtractFile.created_at, AAExtractFile.id, AAExtractRecord.position,
                                             AAExtractRecord.id).offset(offset).limit(limit))).scalars().all()
    return {"format_key": key, "total": total, "offset": offset, "records": [_record_out(r) for r in rows]}


@router.patch("/records/{record_id}")
async def edit_record(record_id: str, body: EditsIn, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """Hand edits: values, edited cells, unreadable cells and flags are all recomputed here from the run's
    snapshot."""
    ent = scope_for(user)
    edits = [e.model_dump() for e in body.edits]
    problem = runner.edit_problem(edits)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    row = (await db.execute(
        select(AAExtractRecord, AAExtractFile, AAExtractRun)
        .join(AAExtractFile, AAExtractFile.id == AAExtractRecord.file_id)
        .join(AAExtractRun, AAExtractRun.id == AAExtractRecord.run_id)
        .where(AAExtractRecord.id == _uuid_or_404(record_id, "Record not found"),
               AAExtractRecord.enterprise_id == ent, AAExtractFile.enterprise_id == ent,
               AAExtractRun.enterprise_id == ent, AAExtractRun.deleted_at.is_(None))
        .with_for_update(of=AAExtractRecord).execution_options(populate_existing=True)
    )).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    record, f, run = row
    snap = (run.snapshots or {}).get(f.format_key or "")
    if snap is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This record's format is no longer available")
    try:
        values, bad, edited = runner.apply_edit(record.values or {"header": {}, "rows": []}, snap, edits)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    record.values = values
    record.bad_cells = bad
    record.edited = runner.merge_edited(record.edited or [], edited)
    record.flags = runner.reflag(values, snap, runner.manila_today(), record.confidence, bad)
    await db.commit()
    return _record_out(record)


@router.put("/files/{file_id}/format")
async def pick_file_format(file_id: str, body: FileFormatIn, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    """Pick the format for a file auto detect wasn't sure about; it is queued and read. Locks follow Extract's one
    order (see runner.py): the run row, then the firm owner row, then the file row."""
    ent = scope_for(user)
    _, found = await _file_or_404(db, ent, file_id)              # no lock yet: only to find the run
    run = await _run_or_404(db, ent, str(found.id), lock=True)   # 1. run
    if body.format_key not in (run.snapshots or {}):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick one of this run's formats")
    await _precheck_budget(db, user)
    enterprise = await get_enterprise_for_user(db, user)
    if enterprise is not None:
        await lock_firm(db, enterprise.id)                       # 2. firm owner (the reservation's own lock)
    f, _ = await _file_or_404(db, ent, file_id, lock=True)      # 3. file
    if f.status != "choose":
        raise HTTPException(status.HTTP_409_CONFLICT, "This file already has a format")
    f.format_key, f.status, f.error = body.format_key, "queued", ""
    await db.flush()
    await _reserve_pages(db, user)                               # re-takes the owner lock it already holds
    run.status = "reading"
    await db.commit()
    runner.start(run.id, str(user.id), ent)
    return _file_out(f)


@router.get("/files/{file_id}/pages/{page}")
async def extract_file_page(file_id: str, page: int = PathParam(ge=1, le=10000),
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    f, run = await _file_or_404(db, ent, file_id, message="Page not found")
    if page > f.page_count or not runner.own_file(run.id, f.stored_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    stored_path, file_type = f.stored_path, f.file_type
    await db.commit()  # nothing stays open while the page renders
    from app.services.accounting.render_pool import RenderBusy, run_pdf_work

    try:
        result = await run_pdf_work(read_page_bytes, stored_path, file_type, page, owner=str(user.id))
    except RenderBusy as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Page unavailable: renderer is busy") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Page unavailable: PDF could not be rendered") \
            from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    data, media_type = result
    return Response(content=data, media_type=media_type,
                    headers={"Cache-Control": "private, max-age=3600", "Vary": "Authorization"})


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Delete a run (its creator, an owner or a manager): kept as a tombstone, its stored files removed."""
    ent = scope_for(user)
    run = await _run_or_404(db, ent, run_id, lock=True)
    if run.created_by != user.id and user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the person who ran this extract or a manager can delete it")
    counts = (await db.execute(select(func.count(AAExtractFile.id)).where(
        AAExtractFile.run_id == run.id, AAExtractFile.enterprise_id == ent))).scalar_one()
    records = (await db.execute(select(func.count(AAExtractRecord.id)).where(
        AAExtractRecord.run_id == run.id, AAExtractRecord.enterprise_id == ent))).scalar_one()
    before = {"format_name": run.format_name, "status": run.status, "files": counts, "records": records}
    run.deleted_at = datetime.now(timezone.utc)
    audit.record(db, ent=ent, company_id=None, user=user, entity="extract_run", entity_id=run.id, action="delete",
                 before=before, after=None, label=run.format_name)
    await db.commit()
    await runner.remove_files(run.id)


EXPORT_MAX_RECORDS = 20000
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/runs/{run_id}/xlsx")
async def run_xlsx(run_id: str, format_key: str | None = Query(default=None, max_length=40), preview: bool = False,
                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """One format's records of a run as a workbook (`preview=true`: the sheets as cells for the in-app preview).
    `format_key` is needed when the run has records from more than one format."""
    ent = scope_for(user)
    if not export_limiter.check_and_record(str(user.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many exports. Please wait a few minutes.")
    run = await _run_or_404(db, ent, run_id)
    with_records = list((await db.execute(
        select(AAExtractFile.format_key).join(AAExtractRecord, AAExtractRecord.file_id == AAExtractFile.id)
        .where(AAExtractFile.run_id == run.id, AAExtractFile.enterprise_id == ent,
               AAExtractRecord.enterprise_id == ent).distinct())).scalars())
    snapshots = run.snapshots or {}
    try:
        key = runner.records_format(format_key, with_records, snapshots)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    snapshot = snapshots.get(key) if key is not None else None
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing to export yet")
    where = [AAExtractRecord.run_id == run.id, AAExtractRecord.enterprise_id == ent,
             AAExtractFile.enterprise_id == ent, AAExtractFile.format_key == key]
    joined = select(AAExtractRecord, AAExtractFile.original_name).join(
        AAExtractFile, AAExtractFile.id == AAExtractRecord.file_id).where(*where)
    total = (await db.execute(select(func.count()).select_from(joined.subquery()))).scalar_one()
    if total == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing to export yet")
    if total > EXPORT_MAX_RECORDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"This run has {total} records; export at most {EXPORT_MAX_RECORDS} at a time")
    lines = (await db.execute(select(func.coalesce(func.sum(case(
        (func.jsonb_typeof(AAExtractRecord.values["rows"]) == "array",
         func.jsonb_array_length(AAExtractRecord.values["rows"])), else_=0)), 0)).select_from(AAExtractRecord).join(
        AAExtractFile, AAExtractFile.id == AAExtractRecord.file_id).where(*where))).scalar_one()
    fields = snapshot.get("fields") or []
    if export.cell_count(sum(f.get("scope") == "header" for f in fields), sum(f.get("scope") == "row" for f in fields),
                         total, lines) > export.MAX_CELLS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "This run is too large to export in one file. Filter it by format or split the drop.")
    found = (await db.execute(joined.order_by(AAExtractFile.created_at, AAExtractFile.id, AAExtractRecord.position,
                                              AAExtractRecord.id))).all()
    records = [{"position": r.position, "file": name, "page_start": r.page_start, "page_end": r.page_end,
                "values": r.values or {}, "flags": r.flags or []} for r, name in found]
    del found
    name = snapshot.get("name") or run.format_name or "Extract"
    data = await asyncio.to_thread(export.workbook, name, snapshot, records)
    del records  # the workbook bytes exist: let the rows go
    if preview:
        return JSONResponse({"sheets": await asyncio.to_thread(workbook_preview, data)})
    safe = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip() or "Extract"
    day = datetime.now(ZoneInfo("Asia/Manila")).date().isoformat()
    return Response(content=data, media_type=_XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{safe} extract {day}.xlsx"'})
