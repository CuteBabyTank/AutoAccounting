"""The duplicate double-check: pairs of documents that look like the same paper filed twice.

Extraction flags a repeated seller + document number as it files a drop. This check runs over a
company's whole databank instead, so it also finds copies dropped in different uploads or quarters,
and copies whose number was misread (same counterparty, date and amount). A pair a person has
said is not a duplicate is never offered again.
"""

import heapq
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
NUMBER_REUSED = "number_reused"  # a supplier's invoice number seen before on another date: not a copy, but odd

FLAG = "possible_duplicate"
NUMBER_FLAG = "duplicate_invoice_number"
_FLAG_FOR = {SAME_NUMBER: FLAG, SAME_DETAILS: FLAG, NUMBER_REUSED: NUMBER_FLAG}
_BILLS = frozenset({"purchases", "expenses"})


@dataclass(frozen=True)
class DupDoc:
    id: uuid.UUID
    role: str
    counterparty: str           # TIN, else the normalized name
    doc_number: str
    doc_date: date | None
    gross: Decimal
    not_duplicate_of: frozenset[str] = frozenset()
    category: str = ""


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
        category=doc.category or "",
    )


def _cleared(a: DupDoc, b: DupDoc) -> bool:
    return str(b.id) in a.not_duplicate_of or str(a.id) in b.not_duplicate_of


def _is_bill(doc: DupDoc) -> bool:
    return doc.role == "buyer" and doc.category in _BILLS


def _first_uncleared(candidates, doc: DupDoc) -> DupDoc | None:
    """The first candidate (in filing order) a person hasn't cleared against ``doc``. Cleared pairs are rare, so
    this stops almost at once."""
    for earlier in candidates:
        if not _cleared(earlier, doc):
            return earlier
    return None


@dataclass
class _NumberBucket:
    """Earlier documents sharing (role, counterparty, number), indexed so a lookup never rescans the bucket."""
    all: list[DupDoc]
    dated: dict[date, list[tuple[int, DupDoc]]]
    undated: list[tuple[int, DupDoc]]
    bills: list[DupDoc]          # dated supplier bills, for number_reused


@dataclass
class _DetailsBucket:
    all: list[DupDoc]
    unnumbered: list[DupDoc]


def duplicate_pairs(docs: list[DupDoc]) -> list[Pair]:
    """Each later copy paired with the first document it repeats. ``docs`` come in filing order.

    Two numbered documents with different numbers are different papers, and so are two dated ones with
    different dates (monthly statements repeat the account number). A supplier bill whose number the same
    supplier already used on another date pairs as ``number_reused``.

    Buckets are indexed by the fields that decide a match, so the work stays near-linear even when a company has
    thousands of documents with one number or one date and amount.
    """
    by_number: dict[tuple, _NumberBucket] = {}
    by_details: dict[tuple, _DetailsBucket] = {}
    pairs: list[Pair] = []
    for seq, doc in enumerate(docs):
        number_key = (doc.role, doc.counterparty, doc.doc_number) if doc.doc_number else None
        details_key = ((doc.role, doc.counterparty, doc.doc_date, doc.gross)
                       if doc.counterparty and doc.doc_date and doc.gross > 0 else None)
        found = None
        nb = by_number.get(number_key) if number_key else None
        if nb is not None:
            if doc.doc_date:  # same date or undated, in filing order
                same = (d for _, d in heapq.merge(nb.dated.get(doc.doc_date, []), nb.undated, key=lambda t: t[0]))
            else:  # an undated document matches every earlier one
                same = iter(nb.all)
            earlier = _first_uncleared(same, doc)
            if earlier is not None:
                found = Pair(earlier.id, doc.id, SAME_NUMBER)
        if found is None and details_key and details_key in by_details:
            db_ = by_details[details_key]
            earlier = _first_uncleared(db_.unnumbered if doc.doc_number else db_.all, doc)
            if earlier is not None:
                found = Pair(earlier.id, doc.id, SAME_DETAILS)
        if found is None and nb is not None and doc.doc_date and _is_bill(doc):
            earlier = _first_uncleared((b for b in nb.bills if b.doc_date != doc.doc_date), doc)
            if earlier is not None:
                found = Pair(earlier.id, doc.id, NUMBER_REUSED)
        if found:
            pairs.append(found)
        if number_key:
            nb = by_number.setdefault(number_key, _NumberBucket([], {}, [], []))
            nb.all.append(doc)
            if doc.doc_date:
                nb.dated.setdefault(doc.doc_date, []).append((seq, doc))
                if _is_bill(doc):
                    nb.bills.append(doc)
            else:
                nb.undated.append((seq, doc))
        if details_key:
            dbk = by_details.setdefault(details_key, _DetailsBucket([], []))
            dbk.all.append(doc)
            if not doc.doc_number:
                dbk.unnumbered.append(doc)
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
    """Flag every unreviewed copy for review; drop a flag from documents no longer in a pair of its kind."""
    for flag in (FLAG, NUMBER_FLAG):
        kind = [p for p in pairs if _FLAG_FOR[p.reason] == flag]
        in_pairs = {p.copy for p in kind} | {p.original for p in kind}
        copies = {p.copy for p in kind}
        for doc in docs.values():
            reasons = list(doc.review_reasons or [])
            if doc.id in copies and flag not in reasons and not doc.reviewed:
                doc.review_reasons = [*reasons, flag]
                doc.needs_review = needs_review_for(doc.review_reasons)
            elif doc.id not in in_pairs and flag in reasons:
                doc.review_reasons = [r for r in reasons if r != flag]
                doc.needs_review = needs_review_for(doc.review_reasons)


async def refresh_flags(db: AsyncSession, company_id: uuid.UUID) -> None:
    sync_flags(*await find_pairs(db, company_id))
