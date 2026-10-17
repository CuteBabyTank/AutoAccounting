"""Customer / supplier subledgers for a company (async glue + document mappers).

The decisions are pure: ``contacts`` (master, dedupe, merges) and ``compute.subledger`` (open items, aging, 2307
items). Payments are the books' payments (``loader.document_payments`` + matched bank lines through
``apply_bank_lines``), so the subledger and the books agree on what paid what.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AACompany, AAContact, AADocument, AAOutput, AAPeriod
from app.services.accounting.books.receipts import party_key
from app.services.accounting.compute.bank_books import apply_bank_lines
from app.services.accounting.compute.books import Payment
from app.services.accounting.compute.ewt import compute_ewt
from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.compute.subledger import (
    CwtItem, OpenDoc, OpenItem, Received2307, counter_paid, cwt_items, open_items,
)
from app.services.accounting.contacts import SeenParty, plan_contacts, resolve
from app.services.accounting.extraction import due_fields
from app.services.accounting.parsing import parse_money
from app.services.accounting.periods import period_for

_BILLS = ("purchases", "expenses")


def _live(doc) -> bool:
    return doc.deleted_at is None and not doc.excluded


def counterparty(doc) -> tuple[str, str, str]:
    """(TIN, name, address) of the other party."""
    if doc.client_role == "seller":
        return doc.buyer_tin or "", doc.buyer_name or "", doc.buyer_address or ""
    return doc.seller_tin or "", doc.seller_name or "", doc.seller_address or ""


def doc_kind(doc) -> str | None:
    """ar (a sale), ap (a bill), or None (anything else, or a receipt that pays an invoice)."""
    if doc.settles_document_id is not None:
        return None
    if doc.category == "sales" and doc.client_role == "seller":
        return "ar"
    if doc.category in _BILLS and doc.client_role == "buyer":
        return "ap"
    return None


def seen_party(doc) -> SeenParty | None:
    """The contact a live document shows (sales, bills, receipts and 2307s; not payroll)."""
    if not _live(doc) or doc.category not in ("sales", "purchases", "expenses", "2307"):
        return None
    tin, name, address = counterparty(doc)
    if not tin and not name.strip():
        return None
    role = "customer" if doc.client_role == "seller" else "supplier"
    vat = doc.seller_vat_registered if role == "supplier" else None
    return SeenParty(party_key(tin, name), tin, name, address, role, vat, doc.doc_date)


def open_doc_from(doc, ewt: dict[str, Decimal], key_map: dict[str, str], names: dict[str, tuple[str, str]],
                  fye: int) -> OpenDoc | None:
    """A sale or bill as the subledger sees it (None for anything else)."""
    kind = doc_kind(doc)
    if kind is None or not _live(doc) or doc.doc_date is None:
        return None
    tin, name, _ = counterparty(doc)
    key = key_map.get(party_key(tin, name), party_key(tin, name))
    shown_name, shown_tin = names.get(key, (name, tin))
    raw = doc.raw if isinstance(doc.raw, dict) else {}
    due, days = due_fields(raw)
    where = period_for(doc.doc_date, fye)
    withheld = c2(doc.withholding_amount or ZERO) if kind == "ar" else c2(ewt.get(str(doc.id), ZERO))
    return OpenDoc(
        id=str(doc.id), kind=kind, contact_key=key, contact_name=shown_name or name, contact_tin=shown_tin or tin,
        doc_number=doc.doc_number or "", doc_date=doc.doc_date, total=c2(doc.gross_amount or ZERO),
        withheld=withheld,
        paid_at_counter=doc.paid_on is None and counter_paid(str(raw.get("payment_terms") or ""),
                                                             parse_money(raw.get("cash_tendered"))),
        due_date=due, terms_days=days, payment_unverified="payment_unverified" in (doc.review_reasons or []),
        period=(where.fiscal_year, where.quarter),
    )



@dataclass
class Subledger:
    as_of: date
    contacts: list[AAContact]
    docs: list[OpenDoc]                 # every sale and bill (open or not)
    items: list[OpenItem]               # open as of ``as_of``
    cwt: list[CwtItem]
    payments: list[Payment]
    ewt: dict[str, tuple[str, Decimal]]   # bill id → (ATC, tax)
    received: list[Received2307]
    documents: dict[str, AADocument]


async def sync_contacts(db: AsyncSession, company: AACompany, docs: list[AADocument]) -> list[AAContact]:
    """Create / update the company's contacts from its documents (flushes; the caller commits)."""
    rows = list((await db.execute(select(AAContact).where(
        AAContact.enterprise_id == company.enterprise_id, AAContact.company_id == company.id))).scalars().all())
    seen = [s for s in (seen_party(d) for d in docs) if s is not None]
    creates, updates = plan_contacts(seen, rows)
    by_key = {r.key: r for r in rows}
    for key, change in updates.items():
        for name, value in change.items():
            setattr(by_key[key], name, value)
    for c in creates:
        row = AAContact(id=uuid.uuid4(), enterprise_id=company.enterprise_id, company_id=company.id,
                        key=c["key"][:300], tin=c["tin"], role=c["role"], registered_name=c["registered_name"][:255],
                        aliases=c["aliases"], address=c["address"], vat_status=c["vat_status"], manual=[])
        db.add(row)
        rows.append(row)
    if creates or updates:
        await db.flush()
    return rows


def key_map_for(rows: list[AAContact]) -> dict[str, str]:
    """Every contact key → the key of the contact it counts for (merges followed)."""
    out = {}
    for r in rows:
        target = resolve(r.key, rows)
        out[r.key] = target.key if target is not None else r.key
    return out


async def company_documents(db: AsyncSession, company: AACompany) -> list[AADocument]:
    return list((await db.execute(select(AADocument).where(
        AADocument.enterprise_id == company.enterprise_id, AADocument.company_id == company.id,
        AADocument.deleted_at.is_(None), AADocument.excluded.is_(False), AADocument.doc_date.is_not(None),
    ))).scalars().all())


async def load_subledger(db: AsyncSession, company: AACompany, as_of: date) -> Subledger:
    from app.routers.accounting_periods import company_facts, doc_line, supplier_atc_rules, supplier_gl_rules
    from app.services.accounting.books.bank import matched_lines
    from app.services.accounting.books.loader import document_payments

    docs = await company_documents(db, company)
    contacts = await sync_contacts(db, company, docs)
    key_map = key_map_for(contacts)
    names = {r.key: (r.registered_name, r.tin) for r in contacts}
    receipts = [d for d in docs if d.settles_document_id is not None]
    posted = [d for d in docs if d.settles_document_id is None]
    atc_rules, gl_rules = await supplier_atc_rules(db, company.id), await supplier_gl_rules(db, company.id)
    facts = company_facts(company)
    where = period_for(as_of, company.fiscal_year_end_month)
    lines = [doc_line(d, atc_rules, gl_rules) for d in posted]
    ewt = compute_ewt(lines, facts, where.fiscal_year, where.quarter).by_line()
    taxes = {i: tax for i, (_, tax) in ewt.items()}
    payments = document_payments(receipts, posted)
    payments, _, _ = apply_bank_lines(payments, (), await matched_lines(db, company.id, as_of))
    fye = company.fiscal_year_end_month
    open_docs = [o for o in (open_doc_from(d, taxes, key_map, names, fye) for d in posted) if o is not None]
    terms = {r.key: r.payment_terms_days for r in contacts if r.payment_terms_days is not None}
    items = open_items(open_docs, payments, as_of, terms)
    received = []
    for d in posted:
        if d.category == "2307" and d.client_role == "seller":
            tin, name, _ = counterparty(d)
            p = period_for(d.doc_date, fye)
            received.append(Received2307(str(d.id), key_map.get(party_key(tin, name), party_key(tin, name)),
                                         (p.fiscal_year, p.quarter), c2(d.withholding_amount or ZERO)))
    marks = {str(d.id): d.cwt_2307 or {} for d in posted}
    cwt = cwt_items([o for o in open_docs if o.doc_date <= as_of], marks, received)
    return Subledger(as_of, contacts, open_docs, items, cwt, payments, ewt, received, {str(d.id): d for d in docs})


def payment_rows(docs: list[OpenDoc], payments: list[Payment]) -> list[tuple[Payment, Decimal]]:
    """Each payment of these documents with the amount it paid (a full payment resolves to what was left)."""
    due = {d.id: c2(d.total - d.withheld) for d in docs}
    paid: dict[str, Decimal] = {}
    out = []
    for p in sorted(payments, key=lambda p: (p.on, p.id)):
        if p.settles not in due:
            continue
        left = c2(due[p.settles] - paid.get(p.settles, ZERO))
        amount = c2(p.amount) if p.amount is not None else max(left, ZERO)
        paid[p.settles] = c2(paid.get(p.settles, ZERO) + amount)
        out.append((p, amount))
    return out


async def outgoing_2307_outputs(db: AsyncSession, company: AACompany) -> dict[tuple[int, int], str]:
    """(fiscal year, quarter) → the latest generated version that has 2307s to issue (its QAP rows)."""
    rows = (await db.execute(select(AAPeriod.year, AAPeriod.quarter, AAOutput.id, AAOutput.version, AAOutput.snapshot)
                             .join(AAOutput, AAOutput.period_id == AAPeriod.id).where(
        AAPeriod.company_id == company.id, AAPeriod.enterprise_id == company.enterprise_id, AAPeriod.quarter >= 1,
    ))).all()
    best: dict[tuple[int, int], tuple[int, str, bool]] = {}
    for year, quarter, output_id, version, snap in rows:
        if (year, quarter) not in best or version > best[(year, quarter)][0]:
            has = bool(((snap or {}).get("ledgers") or {}).get("QAP"))
            best[(year, quarter)] = (version, str(output_id), has)
    return {k: v[1] for k, v in best.items() if v[2]}
