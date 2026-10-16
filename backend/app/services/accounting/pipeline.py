"""Background detection + extraction for AutoAccounting uploads.

Each job opens its own session (no request context), binds the uploader for
RLS parity with the rest of the app, and commits before every Gemini call so
no transaction is held open across the network (transaction pooler).
"""

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError

from app.database import async_session
from app.dependencies import bind_session_user
from app.models.accounting import AACompany, AADocument, AAFile, AASupplierRule, AAUpload
from app.models.user import User
from app.services import gemini_service
from app.services.accounting import duplicates, gemini as aa_gemini
from app.services.accounting.classify import (
    CompanyProfile, classify_document, duplicate_key, empty_document_fields, mark_duplicates,
)
from app.services.accounting.books import bank
from app.services.accounting.books.links import relink_receipts
from app.services.accounting.jobs import JobSlots
from app.services.accounting.extraction import (
    DETECT_PROMPT, extract_prompt, parse_detection, parse_extraction,
)
from app.services.accounting.matching import CompanyCandidate, detection_json, match_company
from app.services.usage_service import charge_for_pages, get_enterprise_for_user, increment_usage

logger = logging.getLogger(__name__)

# Accounting jobs per instance (each holds a DB session for its run), one per firm.
_SLOTS = JobSlots(total=4)
_TASKS: set[asyncio.Task] = set()
_IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg"}


def company_candidates(companies) -> list[CompanyCandidate]:
    return [
        CompanyCandidate(str(c.id), c.registered_name, c.tin, tuple(c.aliases or ()))
        for c in companies
    ]


def company_profile(c: AACompany) -> CompanyProfile:
    owners = tuple(n for n in (*(c.owner_names or ()), c.books_signatory or "") if n and n.strip())
    return CompanyProfile(
        c.tin, c.registered_name, tuple(c.aliases or ()), c.vat_status == "vat", c.fiscal_year_end_month,
        is_withholding_agent=bool(c.is_withholding_agent or c.is_top_withholding_agent), owner_names=owners,
    )


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def start_detection(upload_id: uuid.UUID, user_id: str, firm_id: uuid.UUID) -> None:
    _spawn(_guarded(run_detection, upload_id, user_id, firm_id))


def start_extraction(upload_id: uuid.UUID, user_id: str, firm_id: uuid.UUID) -> None:
    _spawn(_guarded(run_extraction, upload_id, user_id, firm_id))


async def _guarded(job, upload_id: uuid.UUID, user_id: str, firm_id: uuid.UUID) -> None:
    try:
        async with _SLOTS.slot(str(firm_id)):
            await job(upload_id, user_id)
    except Exception:
        logger.exception("accounting_job_failed upload_id=%s", upload_id)
        async with async_session() as db:
            await bind_session_user(db, user_id)
            upload = await db.get(AAUpload, upload_id)
            if upload is not None:
                upload.status = "failed"
                await db.commit()


async def _first_page(stored_path: str, file_type: str) -> tuple[bytes, str]:
    loop = asyncio.get_running_loop()
    if file_type == "pdf":
        data = await loop.run_in_executor(None, gemini_service.render_pdf_page_jpeg, stored_path, 0)
        return data, "image/jpeg"
    data = await loop.run_in_executor(None, Path(stored_path).read_bytes)
    return data, _IMAGE_MIME[file_type]


async def _chunks(stored_path: str, file_type: str) -> list[tuple[bytes, str, int, int]]:
    """(bytes, mime, start_page_0, end_page_0) pieces to send to Gemini."""
    loop = asyncio.get_running_loop()
    if file_type == "pdf":
        chunks = await loop.run_in_executor(None, aa_gemini.pdf_chunks_for_gemini, stored_path)
        return [(b, "application/pdf", s, e) for b, s, e in chunks]
    data = await loop.run_in_executor(None, Path(stored_path).read_bytes)
    return [(data, _IMAGE_MIME[file_type], 0, 0)]


async def _claim_file(db, file_id: uuid.UUID, company_id: uuid.UUID, sha256: str, stored_path: str) -> bool:
    """Mark a file as extracting, or as a duplicate if the same file is already filed for the company.

    A partial unique index on (company_id, sha256) for extracting/extracted files makes
    the claim atomic, so the same file dropped in two tabs is only read and billed once.
    Earlier copies whose documents were all deleted are superseded first.
    """
    has_live_docs = exists().where(AADocument.file_id == AAFile.id, AADocument.deleted_at.is_(None))
    await db.execute(
        update(AAFile)
        .where(
            AAFile.company_id == company_id, AAFile.sha256 == sha256, AAFile.id != file_id,
            AAFile.status == "extracted", ~has_live_docs,
        )
        .values(status="superseded")
    )
    f = await db.get(AAFile, file_id)
    f.status = "extracting"
    try:
        await db.commit()
        return True
    except IntegrityError:
        await db.rollback()
        f = await db.get(AAFile, file_id)
        f.status = "duplicate"
        await db.commit()
        await asyncio.get_running_loop().run_in_executor(None, lambda: Path(stored_path).unlink(missing_ok=True))
        return False


async def _store_statement(db, doc: AADocument) -> None:
    """Save a bank statement's lines; a bad statement never fails the file (its document is still filed)."""
    try:
        async with db.begin_nested():
            await bank.store_statement(db, doc)
    except Exception:
        logger.exception("accounting_statement_failed document_id=%s", doc.id)


async def run_detection(upload_id: uuid.UUID, user_id: str) -> None:
    async with async_session() as db:
        await bind_session_user(db, user_id)
        upload = await db.get(AAUpload, upload_id)
        if upload is None:
            return
        companies = (await db.execute(
            select(AACompany).where(AACompany.enterprise_id == upload.enterprise_id)
        )).scalars().all()
        candidates = company_candidates(companies)
        files = (await db.execute(
            select(AAFile)
            .where(AAFile.upload_id == upload_id, AAFile.status == "uploaded")
            .order_by(AAFile.created_at)
        )).scalars().all()
        jobs = [(f.id, f.stored_path, f.file_type) for f in files]
        await db.commit()

        for file_id, stored_path, file_type in jobs:
            try:
                image, mime = await _first_page(stored_path, file_type)
                raw = await aa_gemini.call_gemini_raw(image, mime, DETECT_PROMPT, user_id)
                detection = parse_detection(raw)
                result = detection_json(detection, match_company(detection.seller, detection.buyer, candidates))
            except Exception as e:  # one bad file never blocks the rest
                logger.warning("accounting_detect_failed file_id=%s error=%s", file_id, str(e)[:200])
                result = {"error": str(e)[:200]}
            f = await db.get(AAFile, file_id)
            f.detection = result
            f.status = "detected"
            upload = await db.get(AAUpload, upload_id)
            upload.processed_files += 1
            await db.commit()

        upload = await db.get(AAUpload, upload_id)
        upload.status = "awaiting_confirmation"
        await db.commit()


async def run_extraction(upload_id: uuid.UUID, user_id: str) -> None:
    async with async_session() as db:
        await bind_session_user(db, user_id)
        upload = await db.get(AAUpload, upload_id)
        if upload is None:
            return
        enterprise_scope = upload.enterprise_id
        uploader = await db.get(User, upload.uploaded_by)
        enterprise = await get_enterprise_for_user(db, uploader) if uploader else None
        enterprise_id = enterprise.id if enterprise else None

        files = (await db.execute(
            select(AAFile)
            .where(
                AAFile.upload_id == upload_id,
                AAFile.company_id.is_not(None),
                AAFile.status.in_(("uploaded", "detected")),
            )
            .order_by(AAFile.created_at)
        )).scalars().all()
        jobs = [(f.id, f.company_id, f.stored_path, f.file_type, f.page_count, f.sha256) for f in files]
        company_ids = list({company_id for _, company_id, *_ in jobs})

        companies = (await db.execute(
            select(AACompany).where(AACompany.id.in_(company_ids))
        )).scalars().all() if company_ids else []
        profiles = {c.id: company_profile(c) for c in companies}
        prompts = {c.id: extract_prompt(c.registered_name, c.tin, c.business_type) for c in companies}
        all_tins = (await db.execute(
            select(AACompany.id, AACompany.tin)
            .where(AACompany.enterprise_id == enterprise_scope, AACompany.tin != "")
        )).all()
        rules: dict[uuid.UUID, dict[str, tuple[str, str]]] = {}
        for r in (await db.execute(
            select(AASupplierRule).where(AASupplierRule.company_id.in_(company_ids))
        )).scalars().all() if company_ids else []:
            rules.setdefault(r.company_id, {})[r.counterparty_tin] = (r.category, r.account)
        seen: dict[uuid.UUID, set[tuple[str, str]]] = {cid: set() for cid in company_ids}
        for company_id, seller_tin, seller_name, doc_number in (await db.execute(
            select(AADocument.company_id, AADocument.seller_tin, AADocument.seller_name, AADocument.doc_number)
            .where(
                AADocument.company_id.in_(company_ids),
                AADocument.doc_number != "",
                AADocument.deleted_at.is_(None),
            )
        )).all() if company_ids else []:
            key = duplicate_key({"seller_tin": seller_tin, "seller_name": seller_name, "doc_number": doc_number})
            if key:
                seen[company_id].add(key)

        upload.status = "extracting"
        upload.total_files = len(jobs)
        upload.processed_files = 0
        await db.commit()

        for file_id, company_id, stored_path, file_type, page_count, sha256 in jobs:
            profile = profiles.get(company_id)
            others = frozenset(t for cid, t in all_tins if cid != company_id)
            if not await _claim_file(db, file_id, company_id, sha256, stored_path):
                upload = await db.get(AAUpload, upload_id)
                upload.processed_files += 1
                await db.commit()
                continue
            new_seen = seen[company_id]
            try:
                if profile is None:
                    raise ValueError("company no longer exists")
                rows = []
                for data, mime, start0, end0 in await _chunks(stored_path, file_type):
                    pages = end0 - start0 + 1
                    # Gemini occasionally replies with valid JSON but no documents for a whole
                    # chunk; retry once, then file a placeholder so those pages land in review.
                    for attempt in (1, 2):
                        raw = await aa_gemini.call_gemini_raw(data, mime, prompts[company_id], user_id)
                        extracted = parse_extraction(raw, page_offset=start0, chunk_pages=pages)
                        if extracted:
                            break
                        logger.warning(
                            "accounting_empty_chunk file_id=%s pages=%d-%d attempt=%d",
                            file_id, start0 + 1, end0 + 1, attempt,
                        )
                    if extracted:
                        rows += [classify_document(ext, profile, rules.get(company_id, {}), others) for ext in extracted]
                    else:
                        rows.append(empty_document_fields(pages, page_start=start0 + 1))
                if not rows:
                    rows = [empty_document_fields(page_count)]
                new_seen = mark_duplicates(rows, seen[company_id])
                added = [AADocument(enterprise_id=enterprise_scope, company_id=company_id, file_id=file_id, **fields)
                         for fields in rows]
                db.add_all(added)

                await db.flush()  # surface bad rows (e.g. out-of-range amounts) inside this file's try
                for doc in added:
                    if doc.doc_type == "statement":
                        await _store_statement(db, doc)
                f = await db.get(AAFile, file_id)
                if not f.pages_charged and enterprise_id is not None:
                    ent = await db.get(User, enterprise_id)
                    await charge_for_pages(db, ent, page_count)
                    await increment_usage(db, enterprise_id, page_count)
                    f.pages_charged = True
                f.status = "extracted"
                f.error_message = None
            except Exception as e:  # file-level isolation: one bad file never fails the upload
                logger.exception("accounting_extract_failed file_id=%s", file_id)
                await db.rollback()
                f = await db.get(AAFile, file_id)
                f.status = "error"
                f.error_message = str(e)[:500]
            upload = await db.get(AAUpload, upload_id)
            upload.processed_files += 1
            await db.commit()
            f = await db.get(AAFile, file_id)
            if f.status == "extracted":
                seen[company_id] = new_seen  # adopt keys only once this file's rows are committed

        for company_id in company_ids:
            try:
                await relink_receipts(db, company_id)
                await duplicates.refresh_flags(db, company_id)  # copies dropped in earlier uploads too
                company = await db.get(AACompany, company_id)
                if company is not None:
                    await bank.rematch(db, company)  # new statement lines, or new documents they pay
                await db.commit()
            except Exception:  # linking is a convenience; never fail the upload over it
                logger.exception("accounting_relink_failed company_id=%s", company_id)
                await db.rollback()

        upload = await db.get(AAUpload, upload_id)
        upload.status = "done"
        await db.commit()
