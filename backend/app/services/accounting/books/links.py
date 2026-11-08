"""Keep receipt → invoice links, and the payment review flags they clear, up to date for a company."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AADocument
from app.services.accounting.review_rules import needs_review_for, sync_payment_flags
from app.services.accounting.books.receipts import DocRef, is_invoice, is_payment_receipt, match_receipts, party_key

_PAYABLE = ("sales", "purchases", "expenses", "payroll")


@dataclass(frozen=True)
class LinkChange:
    settles: str | None
    source: str        # "auto" when linked automatically, "" otherwise
    possible: bool     # several invoices fit: a person must choose


def doc_ref(doc) -> DocRef:
    seller = doc.client_role == "seller"
    return DocRef(str(doc.id), party_key(doc.buyer_tin if seller else doc.seller_tin,
                                         doc.buyer_name if seller else doc.seller_name),
                  doc.client_role, doc.doc_date, doc.gross_amount, doc.withholding_amount)


def _live(doc) -> bool:
    return doc.deleted_at is None and not doc.excluded


def receipt_docs(docs) -> list:
    return [d for d in docs if _live(d) and is_payment_receipt(d.document_title, d.doc_type)]


def invoice_docs(docs) -> list:
    return [d for d in docs if _live(d) and d.settles_document_id is None and d.category in _PAYABLE
            and is_invoice(d.document_title, d.doc_type)]


def plan_links(docs, frozen: frozenset[str] | set[str] = frozenset(),
               held_invoices: frozenset[str] | set[str] = frozenset()) -> dict[str, LinkChange]:
    """The link every automatically managed receipt should have. Receipts a person decided are left out, and so
    are `frozen` receipts (retained history keeps their link as it is); their invoices and `held_invoices` (paid
    by a retained bank line) can't be claimed by another receipt."""
    receipts = receipt_docs(docs)
    auto = [r for r in receipts if r.settles_source != "user" and str(r.id) not in frozen]
    taken = {str(r.settles_document_id) for r in receipts
             if (r.settles_source == "user" or str(r.id) in frozen) and r.settles_document_id is not None}
    taken |= set(held_invoices)
    matches = match_receipts([doc_ref(r) for r in auto], [doc_ref(i) for i in invoice_docs(docs)], taken)
    return {m.receipt_id: LinkChange(m.invoice_id, "auto" if m.invoice_id else "", bool(m.candidates))
            for m in matches}


async def relink_receipts(db: AsyncSession, company_id: uuid.UUID) -> None:
    """Apply plan_links to the company's documents (flushes; the caller commits). Automatic links in retained
    history stay as they are (deletion.frozen_receipt_links): receipts dated in a closed month or filed return,
    or tied to a bank line a rematch keeps, and the invoices such a line pays. Every caller gets this; none needs
    links in closed / filed history moved. The caller holds the firm lock (the guard re-takes it, then the company
    row, the order every guard uses)."""
    from app.models.accounting import AACompany
    from app.services.accounting import deletion

    docs = (await db.execute(select(AADocument).where(
        AADocument.company_id == company_id, AADocument.deleted_at.is_(None),
    ))).scalars().all()
    by_id = {str(d.id): d for d in docs}
    auto = [r for r in receipt_docs(docs) if r.settles_source != "user"]
    frozen: set[str] = set()
    held_invoices: set[str] = set()
    if auto:  # nothing to relink (the common case) → no retention queries
        company = (await db.execute(select(AACompany).where(AACompany.id == company_id))).scalar_one_or_none()
        if company is not None:
            frozen, held_invoices = await deletion.frozen_receipt_links(db, company, auto)
    for receipt_id, change in plan_links(docs, frozen, held_invoices).items():
        doc = by_id[receipt_id]
        target = uuid.UUID(change.settles) if change.settles else None
        if doc.settles_document_id != target or doc.settles_source != change.source:
            doc.settles_document_id, doc.settles_source = target, change.source
        reasons = [r for r in (doc.review_reasons or []) if r != "possible_payment"]
        if change.possible:
            reasons.append("possible_payment")
        if reasons != list(doc.review_reasons or []):
            doc.review_reasons = reasons
            doc.needs_review = needs_review_for(reasons)
    from app.services.accounting.books.bank import bank_paid_ids  # bank imports the loader, which imports routers

    # a receipt now linked (or unlinked), or a matched bank line, is payment evidence for its invoice
    sync_payment_flags(docs, await bank_paid_ids(db, company_id))
    await db.flush()
