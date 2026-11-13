"""Extract runs: the pure decisions behind reading, editing and recovering a run, and its background job.

A run snapshots the formats it may use when it is created (`{key: {"name", "fields", "checks", "detect_hint"}}`);
reading, re-flagging after a hand edit and export always use that snapshot, never the live format.

The job follows the upload pipeline's rules: its own session bound to the firm owner for RLS, one job slot per firm
(the pipeline's own `JobSlots`, so uploads and Extract runs share the instance), a commit before every reader call,
chunks built one at a time inside the reader gate (`pipeline.read_chunks`), resumable after a restart (files left in
`detecting` / `reading` are requeued on the next read of the run, with interrupts counted), and pages charged once
per file, only when it was read. One file's failure never stops the others.
"""

import asyncio
import copy
import logging
import shutil
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.accounting import AAExtractFile, AAExtractRecord, AAExtractRun
from app.models.user import User, UserRole
from app.services.accounting import gemini, pipeline
from app.services.accounting.extract import checks, prompts, spec
from app.services.accounting.jobs import (
    INTERRUPTED_MESSAGE, MAX_INTERRUPTS, STALE_AFTER, after_interrupt, stale_action,
)
from app.services.accounting.storage import extract_run_dir, is_stored_path_safe
from app.services.usage_service import charge_for_pages, increment_usage

logger = logging.getLogger(__name__)

AUTO = "auto"
AUTO_NAME = "Auto detect"
MAX_RECORDS = 2000          # records kept per file
MAX_EDITS = 200             # cells per PATCH
MAX_EDIT_CHARS = 500        # characters per edited value
RUNS_LISTED = 50

RUNNING = frozenset({"queued", "detecting", "reading"})
# Unread files whose pages are reserved against the budget ("choose" waits on a person, so it holds nothing).
PENDING = tuple(sorted(RUNNING))
UNREADABLE_FILE = "We couldn't read this file. Try a clearer copy."
FAILED_FILE = "Reading failed. Drop the file again."
INTERRUPTED_FAIL = "Reading was interrupted. Drop the file again."

_MANILA = ZoneInfo("Asia/Manila")


def manila_today() -> date:
    return datetime.now(_MANILA).date()


# ── pure ──────────────────────────────────────────────────────────────────

def run_status(file_statuses: list[str]) -> str:
    """`reading` while any file is still queued or being read; `failed` when every file is `error`; else `done`
    (files waiting on a format pick or in error don't hold a run open)."""
    if any(s in RUNNING for s in file_statuses):
        return "reading"
    if file_statuses and all(s == "error" for s in file_statuses):
        return "failed"
    return "done"


def snapshot(fmt: dict) -> dict:
    """What a run keeps of a format: enough to read, detect, flag and export without the live format."""
    return {"name": fmt["name"], "fields": copy.deepcopy(fmt["fields"]), "checks": copy.deepcopy(fmt["checks"]),
            "detect_hint": fmt.get("detect_hint", "")}


def snapshots_for(listing: list[dict], key: str) -> dict[str, dict]:
    """`{format key: snapshot}`: every format in the firm's listing for `auto`, else the one asked for (a built-in
    key reaches the firm's copy of it). Raises ValueError for an unknown key."""
    if key == AUTO:
        return {fmt["key"]: snapshot(fmt) for fmt in listing}
    from app.services.accounting.extract import formats

    fmt = formats.find(listing, key) if isinstance(key, str) else None
    if fmt is None:
        raise ValueError("Unknown format")
    return {fmt["key"]: snapshot(fmt)}


def detect_choice(index: int | None, confidence: float, keys: list[str]) -> str | None:
    """The detected format's key, or None (the person picks) under the threshold or for no match."""
    if index is None or not 0 <= index < len(keys) or confidence < prompts.DETECT_THRESHOLD:
        return None
    return keys[index]


def chargeable(read: bool, pages_charged: bool, owner_is_firm: bool) -> bool:
    """A file's pages are billed once, only after it was actually read, and never to a platform-admin scope."""
    return read and not pages_charged and owner_is_firm


def capped_records(chunks: list[list[dict]]) -> list[dict]:
    """A file's records from its chunks in page order, at most MAX_RECORDS."""
    out: list[dict] = []
    for found in chunks:
        out.extend(found[: MAX_RECORDS - len(out)])
        if len(out) >= MAX_RECORDS:
            break
    return out


def reflag(record_values: checks.Values, snapshot: dict, today: date, confidence: float | None,
           bad_cells: list[dict]) -> list[checks.Flag]:
    """A record's flags from the run's snapshot of its format."""
    return checks.run_checks(record_values, snapshot["fields"], snapshot["checks"], today, confidence, bad_cells)


def edit_problem(edits: list[dict]) -> str | None:
    """Why a PATCH's edits are refused before they are applied, or None."""
    if not edits:
        return "Nothing to save"
    if len(edits) > MAX_EDITS:
        return f"At most {MAX_EDITS} cells can be changed at once"
    if any(len(str(e.get("value", ""))) > MAX_EDIT_CHARS for e in edits):
        return f"A value can be at most {MAX_EDIT_CHARS} characters"
    return None


def _bad_cells(values: checks.Values, fields: list[spec.Field]) -> list[dict]:
    """Cells whose text can't be read as their field's type (stored values are already clean, so this is stable)."""
    bad = []
    for f in fields:
        if f["scope"] == "header":
            if not checks.clean_value(values["header"].get(f["key"], ""), f["type"])[1]:
                bad.append({"key": f["key"], "row": None})
    for i, row in enumerate(values["rows"]):
        for f in fields:
            if f["scope"] == "row" and not checks.clean_value(row.get(f["key"], ""), f["type"])[1]:
                bad.append({"key": f["key"], "row": i})
    return bad


def apply_edit(values: checks.Values, snapshot: dict, edits: list[dict]) -> tuple[checks.Values, list[dict],
                                                                                    list[dict]]:
    """`(new values, bad cells, edited cells)`. Each edit `{"key", "row", "value"}` names a field of the snapshot:
    header fields with row None, row fields with an existing row. Values are cleaned as their type; unknown keys or
    rows raise ValueError. The input is not changed."""
    by_key = {f["key"]: f for f in snapshot["fields"]}
    out = {"header": dict(values.get("header") or {}), "rows": [dict(r) for r in values.get("rows") or []]}
    edited: list[dict] = []
    for e in edits:
        field = by_key.get(e.get("key"))
        if field is None:
            raise ValueError("Unknown field")
        row = e.get("row")
        if field["scope"] == "header":
            if row is not None:
                raise ValueError("This field is not in the table")
            target = out["header"]
        else:
            if isinstance(row, bool) or not isinstance(row, int) or not 0 <= row < len(out["rows"]):
                raise ValueError("Unknown row")
            target = out["rows"][row]
        text, _ = checks.clean_value(str(e.get("value", ""))[:MAX_EDIT_CHARS], field["type"])
        target[field["key"]] = text
        cell = {"key": field["key"], "row": row}
        if cell not in edited:
            edited.append(cell)
    return out, _bad_cells(out, snapshot["fields"]), edited


def merge_edited(before: list[dict], now: list[dict]) -> list[dict]:
    """Edited cells so far plus this edit's, each once, in order."""
    out = [dict(c) for c in before or []]
    for c in now:
        if c not in out:
            out.append(dict(c))
    return out


def stale(status: str, created_at: datetime, progress: list[datetime], now: datetime) -> str | None:
    """"resume" / "fail" for a run whose job died, None while alive or finished. Progress is the latest of the
    run's and its files' `updated_at` (files are touched after every chunk)."""
    if status != "reading" or not progress:
        return None
    return stale_action("extracting", created_at, max(progress), now)


def recovery(action: str, files: list[tuple[Any, str, int]]) -> dict[Any, tuple[str, int, str]]:
    """`{file id: (status, interrupts, error)}` for the files a dead job left behind. `resume` requeues files that
    were being detected or read (counting the interrupt; set aside at MAX_INTERRUPTS); `fail` ends every
    unfinished file."""
    plan: dict[Any, tuple[str, int, str]] = {}
    for file_id, status, interrupts in files:
        if action == "resume" and status in ("detecting", "reading"):
            count, nxt = after_interrupt(interrupts or 0, "queued")
            plan[file_id] = (nxt, count, INTERRUPTED_MESSAGE if nxt == "error" else "")
        elif action == "fail" and status in RUNNING:
            plan[file_id] = ("error", interrupts or 0, INTERRUPTED_FAIL)
    return plan


def file_error(exc: BaseException) -> str:
    """What the firm is told about a file that failed (provider and internal errors stay in the log)."""
    if isinstance(exc, gemini.ReaderUnavailable):
        return pipeline.READER_DOWN_MESSAGE
    if isinstance(exc, ValueError):
        return UNREADABLE_FILE
    return FAILED_FILE


# ── stored files ──────────────────────────────────────────────────────────

def _remove_dir(run_id: uuid.UUID) -> None:
    folder = extract_run_dir(run_id)
    if is_stored_path_safe(str(folder)):
        shutil.rmtree(folder, ignore_errors=True)
    else:
        logger.warning("extract_run_path_unsafe run_id=%s", run_id)


async def remove_files(run_id: uuid.UUID) -> None:
    """Delete a run's own folder under the accounting root."""
    await asyncio.to_thread(_remove_dir, run_id)


def own_file(run_id: uuid.UUID, stored_path: str) -> bool:
    """The stored path is inside the accounting root and in this run's folder."""
    return is_stored_path_safe(stored_path) and \
        Path(stored_path).resolve().parent == extract_run_dir(run_id).resolve()


# ── jobs ──────────────────────────────────────────────────────────────────

_TASKS: set[asyncio.Task] = set()
_ACTIVE: dict[uuid.UUID, uuid.UUID] = {}      # run -> firm, while queued for a slot or running
_AGAIN: set[uuid.UUID] = set()                 # runs given more work while their job was running


def is_running(run_id: uuid.UUID) -> bool:
    return run_id in _ACTIVE


def start(run_id: uuid.UUID, user_id: str, firm_id: uuid.UUID) -> None:
    """Read the run's queued files in the background. A run whose job is already going picks new work up in it."""
    if run_id in _ACTIVE:
        _AGAIN.add(run_id)
        return
    _spawn(run_id, firm_id, _loop(run_id, user_id, firm_id))


def resume(run_id: uuid.UUID, user_id: str, firm_id: uuid.UUID) -> None:
    """Restart a dead run's job: it only picks up files still queued."""
    start(run_id, user_id, firm_id)


def _spawn(run_id: uuid.UUID, firm_id: uuid.UUID, coro: Coroutine[Any, Any, None]) -> None:
    _ACTIVE[run_id] = firm_id
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def _loop(run_id: uuid.UUID, user_id: str, firm_id: uuid.UUID) -> None:
    try:
        while True:
            _AGAIN.discard(run_id)
            await _guarded(run_id, user_id, firm_id)
            if run_id not in _AGAIN:
                break  # no await between this check and leaving _ACTIVE: a later start() spawns a new job
    finally:
        _ACTIVE.pop(run_id, None)
        _AGAIN.discard(run_id)


async def release_running() -> None:
    """Shutdown: stop this instance's runs and date them (and their files) back past ``STALE_AFTER``, so the next
    read resumes them at once."""
    if not _ACTIVE:
        return
    active = dict(_ACTIVE)
    tasks = list(_TASKS)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=3)
    back = datetime.now(timezone.utc) - STALE_AFTER - timedelta(minutes=1)
    for run_id, firm_id in active.items():
        try:
            async with async_session() as db:
                await pipeline._bind_job_firm(db, firm_id)
                await db.execute(update(AAExtractRun).where(
                    AAExtractRun.id == run_id, AAExtractRun.enterprise_id == firm_id,
                    AAExtractRun.status == "reading").values(updated_at=back))
                await db.execute(update(AAExtractFile).where(
                    AAExtractFile.run_id == run_id, AAExtractFile.enterprise_id == firm_id).values(updated_at=back))
                await db.commit()
        except Exception:
            logger.exception("extract_job_release_failed run_id=%s", run_id)


async def _guarded(run_id: uuid.UUID, user_id: str, firm_id: uuid.UUID) -> None:
    try:
        async with pipeline._SLOTS.slot(str(firm_id)):
            await _job(run_id, user_id, firm_id)
    except Exception:
        logger.exception("extract_job_failed run_id=%s", run_id)
        await _fail_run(run_id, firm_id)


async def _fail_run(run_id: uuid.UUID, firm_id: uuid.UUID) -> None:
    """The job itself failed: end the run's unfinished files with a friendly error. Never raises."""
    try:
        async with async_session() as db:
            await pipeline._bind_job_firm(db, firm_id)
            run = await _run(db, run_id, firm_id)
            if run is None:
                return
            files = await _files(db, run_id, firm_id)
            for f in files:
                if f.status in RUNNING:
                    f.status, f.error = "error", FAILED_FILE
            run.status = run_status([f.status for f in files])
            await db.commit()
    except Exception:
        logger.exception("extract_job_fail_cleanup_failed run_id=%s", run_id)


async def _run(db: AsyncSession, run_id: uuid.UUID, firm_id: uuid.UUID) -> AAExtractRun | None:
    return (await db.execute(select(AAExtractRun).where(
        AAExtractRun.id == run_id, AAExtractRun.enterprise_id == firm_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()


async def _files(db: AsyncSession, run_id: uuid.UUID, firm_id: uuid.UUID) -> list[AAExtractFile]:
    return list((await db.execute(select(AAExtractFile).where(
        AAExtractFile.run_id == run_id, AAExtractFile.enterprise_id == firm_id,
    ).order_by(AAExtractFile.created_at, AAExtractFile.id).execution_options(populate_existing=True))).scalars())


async def _file(db: AsyncSession, file_id: uuid.UUID, firm_id: uuid.UUID) -> AAExtractFile:
    return (await db.execute(select(AAExtractFile).where(
        AAExtractFile.id == file_id, AAExtractFile.enterprise_id == firm_id,
    ).execution_options(populate_existing=True))).scalar_one()


async def _next_queued(db: AsyncSession, run_id: uuid.UUID, firm_id: uuid.UUID) -> AAExtractFile | None:
    return (await db.execute(select(AAExtractFile).where(
        AAExtractFile.run_id == run_id, AAExtractFile.enterprise_id == firm_id, AAExtractFile.status == "queued",
    ).order_by(AAExtractFile.created_at, AAExtractFile.id).limit(1)
        .execution_options(populate_existing=True))).scalar_one_or_none()


async def _job(run_id: uuid.UUID, user_id: str, firm_id: uuid.UUID) -> None:
    async with async_session() as db:
        await pipeline._bind_job_firm(db, firm_id)
        building = asyncio.Lock()  # this job's chunk builds, one at a time across all its files
        while True:
            run = await _run(db, run_id, firm_id)
            if run is None or run.deleted_at is not None:
                await db.commit()
                return
            snapshots = dict(run.snapshots or {})
            f = await _next_queued(db, run_id, firm_id)
            if f is None:
                break
            await _process(db, f, snapshots, user_id, firm_id, building)
        run = await _run(db, run_id, firm_id)
        if run is not None and run.deleted_at is None:
            run.status = run_status([f.status for f in await _files(db, run_id, firm_id)])
        await db.commit()


async def _detect(stored_path: str, file_type: str, snapshots: dict, user_id: str) -> tuple[str | None, float]:
    keys = list(snapshots)
    image, mime = await pipeline._first_page(stored_path, file_type)
    raw = await gemini.call_gemini_raw(image, mime, prompts.detect_prompt([snapshots[k] for k in keys]), user_id)
    index, confidence = prompts.parse_detection(raw, len(keys))
    return detect_choice(index, confidence, keys), confidence


def _chunk_reader(file_id: uuid.UUID, fields: list[spec.Field], prompt: str,
                  user_id: str) -> Callable[[bytes, str, int, int], Awaitable[list[dict]]]:
    async def read(data: bytes, mime: str, start0: int, end0: int) -> list[dict]:
        pages = end0 - start0 + 1
        for attempt in (1, 2):  # an empty reply for a whole chunk is retried once, as uploads do
            raw = await gemini.call_gemini_raw(data, mime, prompt, user_id)
            found = await asyncio.to_thread(prompts.parse_records, raw, fields, start0, pages)
            if found:
                return found
            logger.warning("extract_empty_chunk file_id=%s pages=%d-%d attempt=%d",
                           file_id, start0 + 1, end0 + 1, attempt)
        return []
    return read


async def _read_with_progress(db: AsyncSession, f_id: uuid.UUID, firm_id: uuid.UUID, stored_path: str,
                              file_type: str, read, building: asyncio.Lock) -> list[list[dict]]:
    """Read every chunk; after each one, touch the file's `updated_at` (only this coroutine uses the session)."""
    progress = asyncio.Event()
    reader = asyncio.create_task(pipeline.read_chunks(stored_path, file_type, read, building, progress.set))
    try:
        while not reader.done():
            waiter = asyncio.create_task(progress.wait())
            try:
                await asyncio.wait({reader, waiter}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                waiter.cancel()
            if progress.is_set():
                progress.clear()
                await db.execute(update(AAExtractFile).where(
                    AAExtractFile.id == f_id, AAExtractFile.enterprise_id == firm_id,
                ).values(updated_at=datetime.now(timezone.utc)))
                await db.commit()
        return reader.result()
    finally:
        if not reader.done():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)


def _records(found: list[list[dict]], snap: dict, today: date) -> list[dict]:
    rows = capped_records(found)
    return [{**r, "flags": reflag(r["values"], snap, today, r["confidence"], r["bad_cells"])} for r in rows]


async def _process(db: AsyncSession, f: AAExtractFile, snapshots: dict, user_id: str, firm_id: uuid.UUID,
                   building: asyncio.Lock) -> None:
    file_id, run_id = f.id, f.run_id
    if (f.interrupts or 0) >= MAX_INTERRUPTS:
        f.status, f.error = "error", INTERRUPTED_MESSAGE
        await db.commit()
        return
    stored_path, file_type, page_count, key = f.stored_path, f.file_type, f.page_count or 1, f.format_key
    try:
        if not own_file(run_id, stored_path):
            raise ValueError("stored path outside the run's folder")
        if key is None:
            f.status = "detecting"
            await db.commit()  # durable before the reader is called
            key, confidence = await _detect(stored_path, file_type, snapshots, user_id)
            f = await _file(db, file_id, firm_id)
            f.detect_confidence = confidence
            if key is None:
                f.status = "choose"
                await db.commit()
                logger.info("extract_file_choose file_id=%s confidence=%.0f", file_id, confidence)
                return
            f.format_key = key
        snap = snapshots.get(key)
        if snap is None:
            raise ValueError("format not in the run's snapshot")
        f.status = "reading"
        await db.commit()

        prompt = prompts.extraction_prompt(snap["name"], snap["fields"])
        found = await _read_with_progress(db, file_id, firm_id, stored_path, file_type,
                                          _chunk_reader(file_id, snap["fields"], prompt, user_id), building)
        records = await asyncio.to_thread(_records, found, snap, manila_today())

        f = await _file(db, file_id, firm_id)
        # A resumed file never has committed records (they commit with `done`), but never keep two sets.
        await db.execute(delete(AAExtractRecord).where(
            AAExtractRecord.file_id == file_id, AAExtractRecord.enterprise_id == firm_id))
        db.add_all([AAExtractRecord(
            enterprise_id=firm_id, run_id=run_id, file_id=file_id, position=i, page_start=r["page_start"],
            page_end=r["page_end"], confidence=r["confidence"], values=r["values"], edited=[],
            bad_cells=r["bad_cells"], flags=r["flags"]) for i, r in enumerate(records)])
        await db.flush()
        owner = await db.get(User, firm_id)  # users is outside accounting RLS
        if chargeable(True, f.pages_charged, owner is not None and owner.role == UserRole.ENTERPRISE):
            await charge_for_pages(db, owner, page_count)  # locks the owner row first, then the month's usage row
            await increment_usage(db, firm_id, page_count)
            f.pages_charged = True
        f.status, f.error = "done", ""
        await db.commit()
        logger.info("extract_file_done file_id=%s pages=%d records=%d", file_id, page_count, len(records))
    except Exception as exc:  # one bad file never stops the run
        message = file_error(exc)
        if message == FAILED_FILE:  # unexpected: keep the traceback (reader / unreadable replies need only the kind)
            logger.exception("extract_file_failed file_id=%s error=%s", file_id, type(exc).__name__)
        else:
            logger.warning("extract_file_failed file_id=%s error=%s", file_id, type(exc).__name__)
        await db.rollback()
        f = await _file(db, file_id, firm_id)
        f.status, f.error = "error", message
        await db.commit()
