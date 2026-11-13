"""Builds an Extract format from a dropped sample: one high-reasoning reader call, cleaned like anything a person
types. Also looks for fields a person says are missing, and clears away expired drafts' samples.

The sample is the file's first `SAMPLE_PAGES` pages, built as one sub-PDF off the event loop on the upload
pipeline's chunk builders (images are sent as they are). Reader failures raise `gemini.ReaderUnavailable`; a reply
that isn't JSON raises `ValueError("unreadable_reply")`.
"""

import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.accounting import AAExtractDraft
from app.services import gemini_service
from app.services.accounting import gemini, pipeline
from app.services.accounting.extract import formats, prompts, spec
from app.services.accounting.storage import extract_draft_dir, is_stored_path_safe

SAMPLE_PAGES = 5
logger = logging.getLogger(__name__)


def with_defaults(proposal: dict) -> dict:
    """The model's proposal with the server's default checks added first, so the check cap never drops them."""
    fields = proposal["fields"]
    return {**proposal, "checks": spec.clean_checks(spec.default_checks(fields) + proposal["checks"], fields)}


async def _sample(stored_path: str, file_type: str) -> tuple[bytes, str]:
    """The bytes the reader sees: the first SAMPLE_PAGES pages of a PDF as one chunk, or the image itself."""
    if file_type != "pdf":
        return await pipeline._chunk_bytes(stored_path, file_type, 0, 0), pipeline._IMAGE_MIME[file_type]
    count = await asyncio.get_running_loop().run_in_executor(None, gemini_service.get_pdf_page_count_safe,
                                                             stored_path)
    if count < 1:
        raise ValueError("unreadable_reply")
    return await pipeline._chunk_bytes(stored_path, "pdf", 0, min(count, SAMPLE_PAGES) - 1), "application/pdf"


async def _read(stored_path: str, file_type: str, prompt: str, user_id: str) -> str:
    data, mime = await _sample(stored_path, file_type)
    return await gemini.call_gemini_raw(data, mime, prompt, user_id, thinking=settings.extract_builder_thinking,
                                        model=settings.extract_builder_model or None,
                                        timeout=settings.extract_builder_timeout_seconds)


async def propose(stored_path: str, file_type: str, user_id: str) -> dict:
    """`{"name", "detect_hint", "fields" (with "value"), "checks"}` for a sample, default checks included."""
    raw = await _read(stored_path, file_type, prompts.BUILDER_PROMPT, user_id)
    return with_defaults(prompts.parse_proposal(raw))


async def find_missing(stored_path: str, file_type: str, names: list[str], user_id: str) -> list[spec.Field]:
    """Fields printed on the sample for the names a person asked about, each with the value read."""
    raw = await _read(stored_path, file_type, prompts.missing_prompt(names), user_id)
    return prompts.parse_missing(raw)


def _remove_dir(draft_id: uuid.UUID, stored_path: str | None) -> None:
    folder = extract_draft_dir(draft_id)
    own = stored_path is None or (is_stored_path_safe(stored_path)
                                  and Path(stored_path).parent.resolve() == folder.resolve())
    if not own:
        logger.warning("extract_draft_path_unsafe draft_id=%s", draft_id)
        return
    if is_stored_path_safe(str(folder)):
        shutil.rmtree(folder, ignore_errors=True)


async def remove_sample(draft_id: uuid.UUID, stored_path: str | None = None) -> None:
    """Delete a draft's sample folder (only its own folder under the accounting root)."""
    await asyncio.to_thread(_remove_dir, draft_id, stored_path)


async def purge_drafts(db: AsyncSession, ent: uuid.UUID) -> int:
    """Delete the firm's expired drafts and their samples (the caller commits)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=formats.DRAFT_HOURS)
    rows = (await db.execute(select(AAExtractDraft.id, AAExtractDraft.stored_path).where(
        AAExtractDraft.enterprise_id == ent, AAExtractDraft.created_at < cutoff))).all()
    for draft_id, stored_path in rows:
        await remove_sample(draft_id, stored_path)
    if rows:
        await db.execute(delete(AAExtractDraft).where(
            AAExtractDraft.enterprise_id == ent, AAExtractDraft.id.in_([r[0] for r in rows])))
    return len(rows)
