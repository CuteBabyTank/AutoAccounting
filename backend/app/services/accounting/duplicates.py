"""The duplicate double-check: pairs of documents that look like the same paper filed twice.

Extraction flags a repeated seller + document number as it files a drop. This check runs over a
company's whole databank instead, so it also finds copies dropped in different uploads or quarters,
and copies whose number was misread (same counterparty, date and amount). A pair a person has
said is not a duplicate is never offered again.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AADocument
from app.services.accounting.classify import needs_review_for
from app.services.accounting.matching import normalize_name

SAME_NUMBER = "same_number"     # same counterparty and document number
SAME_DETAILS = "same_details"   # same counterparty, date and total; the number differs or is missing

FLAG = "possible_duplicate"


@dataclass(frozen=True)
class DupDoc:
    id: uuid.UUID
    role: str
    counterparty: str           # TIN, else the normalized name
    doc_number: str
    doc_date: date | None
    gross: Decimal
    not_duplicate_of: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Pair:
    original: uuid.UUID
    copy: uuid.UUID
    reason: str


def dup_doc(doc: AADocument) -> DupDoc:
    seller = doc.client_role == "seller"
    tin = doc.buyer_tin if seller else doc.seller_tin
    name = doc.buyer_name if seller else doc.seller_name
    return DupDoc(
        id=doc.id, role=doc.client_role, counterparty=tin or normalize_name(name or ""),
        doc_number=(doc.doc_number or "").strip().upper(), doc_date=doc.doc_date,
        gross=Decimal(doc.gross_amount or 0), not_duplicate_of=frozenset(doc.not_duplicate_of or []),
    )


def _cleared(a: DupDoc, b: DupDoc) -> bool:
    return str(b.id) in a.not_duplicate_of or str(a.id) in b.not_duplicate_of


def duplicate_pairs(docs: list[DupDoc]) -> list[Pair]:
    """Each later copy paired with the first document it repeats. ``docs`` come in filing order."""
    by_number: dict[tuple, list[DupDoc]] = {}
    by_details: dict[tuple, list[DupDoc]] = {}
    pairs: list[Pair] = []
    for doc in docs:
        number_key = (doc.role, doc.counterparty, doc.doc_number) if doc.doc_number else None
        details_key = ((doc.role, doc.counterparty, doc.doc_date, doc.gross)
                       if doc.counterparty and doc.doc_date and doc.gross > 0 else None)
        found = None
        for key, index, reason in ((number_key, by_number, SAME_NUMBER), (details_key, by_details, SAME_DETAILS)):
            if key is None or found:
                continue
            for earlier in index.get(key, []):
                # Two numbered documents with different numbers are different papers, and so are two dated
                # ones with different dates (monthly statements repeat the account number).
                if reason == SAME_DETAILS and earlier.doc_number and doc.doc_number:
                    continue
                if reason == SAME_NUMBER and earlier.doc_date and doc.doc_date and earlier.doc_date != doc.doc_date:
                    continue
                if not _cleared(earlier, doc):
                    found = Pair(earlier.id, doc.id, reason)
                    break
        if found:
            pairs.append(found)
        if number_key:
            by_number.setdefault(number_key, []).append(doc)
        if details_key:
            by_details.setdefault(details_key, []).append(doc)
    return pairs


async def company_documents(db: AsyncSession, company_id: uuid.UUID) -> list[AADocument]:
    return list((await db.execute(
        select(AADocument)
        .where(AADocument.company_id == company_id, AADocument.deleted_at.is_(None))
        .order_by(AADocument.created_at, AADocument.page_start)
    )).scalars().all())


async def find_pairs(db: AsyncSession, company_id: uuid.UUID) -> tuple[list[Pair], dict[uuid.UUID, AADocument]]:
    docs = await company_documents(db, company_id)
    return duplicate_pairs([dup_doc(d) for d in docs]), {d.id: d for d in docs}


def sync_flags(pairs: list[Pair], docs: dict[uuid.UUID, AADocument]) -> None:
    """Flag every unreviewed copy for review; drop the flag from documents no longer in any pair."""
    in_pairs = {p.copy for p in pairs} | {p.original for p in pairs}
    copies = {p.copy for p in pairs}
    for doc in docs.values():
        reasons = list(doc.review_reasons or [])
        if doc.id in copies and FLAG not in reasons and not doc.reviewed:
            doc.review_reasons = [*reasons, FLAG]
            doc.needs_review = needs_review_for(doc.review_reasons)
        elif doc.id not in in_pairs and FLAG in reasons:
            doc.review_reasons = [r for r in reasons if r != FLAG]
            doc.needs_review = needs_review_for(doc.review_reasons)


async def refresh_flags(db: AsyncSession, company_id: uuid.UUID) -> None:
    sync_flags(*await find_pairs(db, company_id))
