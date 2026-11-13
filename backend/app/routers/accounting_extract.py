"""Extract tab: the firm's formats, and building one from a dropped sample (a draft).

Anyone in the firm with the `extract` area lists formats; owners and managers build, edit, delete and reset them.
A draft belongs to the person who dropped the sample and lives 24 hours. Saving takes only keys, labels, required
flags and check ids from the browser; definitions come from the stored draft (and the current format on edit).
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import extract_ask_limiter, extract_draft_limiter
from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.accounting import AAExtractDraft, AAExtractFormat
from app.models.user import User, UserRole
from app.routers.accounting_scope import MANAGER_ROLES, scope_for
from app.services.accounting import audit, gemini
from app.services.accounting.extract import builder, formats, guard, spec
from app.services.accounting.pipeline import READER_DOWN_MESSAGE
from app.services.accounting.storage import UploadRejected, extract_draft_dir, stream_upload
from app.services.usage_service import (
    charge_for_pages, get_enterprise_for_user, increment_usage, upload_budget_refusal,
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
