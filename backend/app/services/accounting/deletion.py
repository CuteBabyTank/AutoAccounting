"""Firm-scoped facts used before deleting accounting sources. Never commits or mutates records."""
import uuid
from datetime import date
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import (
    AAAccount, AAAsset, AABankLine, AABankReconciliation, AABankStatement, AABookClose, AACompany, AADocument,
    AAJournalEntry, AAOpeningItem, AAPeriod, AAWorkItem,
)
from app.services.accounting.compute.retention import deletion_problem
from app.services.accounting.assignment import lock_firm


def refuse(message: str) -> None:
    raise HTTPException(status.HTTP_409_CONFLICT, message)


async def _history(db: AsyncSession, company: AACompany) -> tuple[list, set[tuple[int, int]]]:
    """(closed months, filed quarters) under the firm + company locks."""
    ent, cid = company.enterprise_id, company.id
    # Filing/closing take this same firm lock, so finalization cannot pass a deletion guard concurrently.
    await lock_firm(db, ent)
    await db.execute(select(AACompany.id).where(AACompany.id == cid, AACompany.enterprise_id == ent).with_for_update())
    closes = (await db.execute(select(AABookClose.month_start, AABookClose.month_end).where(
        AABookClose.enterprise_id == ent, AABookClose.company_id == cid, AABookClose.voided_at.is_(None)))).all()
    filed = set((await db.execute(select(AAPeriod.year, AAPeriod.quarter).where(
        AAPeriod.enterprise_id == ent, AAPeriod.company_id == cid,
        or_(AAPeriod.filed_at.is_not(None), AAPeriod.filed_forms != {})))).all())
    filed.update((await db.execute(select(AAWorkItem.year, AAWorkItem.quarter).where(
        AAWorkItem.enterprise_id == ent, AAWorkItem.company_id == cid, AAWorkItem.filed_on.is_not(None)))).all())
    return list(closes), filed


async def protect_history(db: AsyncSession, company: AACompany, dates: Iterable[date | None] = (),
                          periods: Iterable[tuple[int, int]] = (), *, from_date: date | None = None,
                          doing: str = "deleting it") -> None:
    closes, filed = await _history(db, company)
    problem = deletion_problem([d for d in dates if d is not None], periods, closes, filed,
                               company.fiscal_year_end_month, from_date=from_date, doing=doing)
    if problem:
        refuse(problem)


async def _live_reconciliations(db: AsyncSession, company: AACompany) -> list[AABankReconciliation]:
    return list((await db.execute(select(AABankReconciliation).where(
        AABankReconciliation.enterprise_id == company.enterprise_id,
        AABankReconciliation.company_id == company.id, AABankReconciliation.voided_at.is_(None)))).scalars().all())


async def protect_bank_links(db: AsyncSession, company: AACompany, lines: list[AABankLine],
                             *, doing: str = "deleting it") -> None:
    if not lines:
        return
    if any(l.match_status == "confirmed" for l in lines):
        refuse(f"A bank line is confirmed against this record. Undo the match on Bank before {doing}.")
    recs = await _live_reconciliations(db, company)
    if any(r.account_code == l.account_code and l.line_date <= r.month_end
           for r in recs for l in lines):
        refuse(f"This record supports a bank reconciliation. Undo its bank match/reconciliation before {doing}.")


async def _retained_lines(db: AsyncSession, company: AACompany) -> tuple[list, set, list[AABankLine], set[uuid.UUID]]:
    """(closed months, filed quarters, the company's live bank lines, the ids of those a rematch may change)."""
    from app.services.accounting.books.bank import live_line

    closes, filed = await _history(db, company)
    lines = list((await db.execute(select(AABankLine).where(
        AABankLine.enterprise_id == company.enterprise_id, AABankLine.company_id == company.id,
        AABankLine.account_code != "", live_line()))).scalars().all())
    if not lines:
        return closes, filed, lines, set()
    recs = await _live_reconciliations(db, company)
    fye = company.fiscal_year_end_month
    safe = {l.id for l in lines
            if l.match_status != "confirmed"
            and not any(r.account_code == l.account_code and l.line_date <= r.month_end for r in recs)
            and deletion_problem([l.line_date], (), closes, filed, fye) is None}
    return closes, filed, lines, safe


async def safe_line_ids(db: AsyncSession, company: AACompany) -> set[uuid.UUID]:
    """The company's live bank lines a rematch may change: not confirmed, not dated in a closed month or in
    filed (or carried-forward) return history, and not covered by a live reconciliation. Everything else keeps
    its match, so a document edit, exclusion or move can't unmatch retained history."""
    return (await _retained_lines(db, company))[3]


def _held(lines: list[AABankLine], safe: set[uuid.UUID]) -> list[AABankLine]:
    """Matched document lines a guarded rematch keeps as they are (outside the safe set)."""
    return [l for l in lines if l.id not in safe and l.account_code and l.match_kind == "document"
            and l.match_status in ("matched", "confirmed") and l.matched_ref]


async def _related_documents(db: AsyncSession, company: AACompany, doc: AADocument) -> list[AADocument]:
    """The document, the receipts that pay it and the invoice it pays (live rows of the same company)."""
    return list((await db.execute(select(AADocument).where(
        AADocument.enterprise_id == company.enterprise_id, AADocument.company_id == company.id,
        AADocument.deleted_at.is_(None),
        or_(AADocument.id == doc.id, AADocument.settles_document_id == doc.id,
            AADocument.id == doc.settles_document_id),
    ))).scalars().all())


async def held_lines(db: AsyncSession, company: AACompany, doc: AADocument) -> list[AABankLine]:
    """Retained bank lines (confirmed, in closed / filed history or under a live reconciliation) still matched to
    this document, a receipt that pays it or the invoice it pays. A rematch never touches them, so an edit that
    changes how they post (the document's side, a receipt's amount) must be refused or void their reconciliation."""
    ids = {str(d.id) for d in await _related_documents(db, company, doc)} | {str(doc.id)}
    _, _, lines, safe = await _retained_lines(db, company)
    return [l for l in _held(lines, safe) if l.matched_ref in ids]


async def frozen_receipt_links(db: AsyncSession, company: AACompany,
                               receipts: Iterable[AADocument]) -> tuple[set[str], set[str]]:
    """(receipt ids, invoice ids) automatic receipt linking must leave alone: of `receipts`, those dated in
    closed / filed history or tied to a retained bank line (directly or through their invoice); and the invoices
    a retained line pays (a receipt newly linked to one would take over that line's payment)."""
    closes, filed, lines, safe = await _retained_lines(db, company)
    fye = company.fiscal_year_end_month
    held = {l.matched_ref for l in _held(lines, safe)}
    frozen = set()
    for r in receipts:
        periods = [(r.period_year, r.period_quarter)] if r.period_year and r.period_quarter else []
        if (str(r.id) in held or (r.settles_document_id is not None and str(r.settles_document_id) in held)
                or deletion_problem([d for d in (r.doc_date, r.paid_on) if d is not None], periods,
                                    closes, filed, fye) is not None):
            frozen.add(str(r.id))
    return frozen, held


async def protect_document(db: AsyncSession, company: AACompany, doc: AADocument,
                           *, doing: str = "deleting it") -> list[AABankLine]:
    ent, cid = company.enterprise_id, company.id
    await lock_firm(db, ent)
    related = list((await db.execute(select(AADocument).where(
        AADocument.enterprise_id == ent, AADocument.company_id == cid, AADocument.deleted_at.is_(None),
        or_(AADocument.id == doc.id, AADocument.settles_document_id == doc.id,
            AADocument.id == doc.settles_document_id),
    ))).scalars().all())
    ids = {str(d.id) for d in related} | {str(doc.id)}
    lines = list((await db.execute(select(AABankLine).where(
        AABankLine.enterprise_id == ent, AABankLine.company_id == cid,
        or_((AABankLine.match_kind == "document") & AABankLine.matched_ref.in_(ids),
            AABankLine.match_status.notin_(("confirmed", "excluded")) & or_(*[
                AABankLine.candidates.contains([{"kind": "document", "ref": i}]) for i in ids]),
            AABankLine.statement_id.in_(select(AABankStatement.id).where(
                AABankStatement.enterprise_id == ent, AABankStatement.document_id == doc.id))),
    ))).scalars().all())
    dates = [d for row in [doc, *related] for d in (row.doc_date, row.paid_on)] + [l.line_date for l in lines]
    periods = [(row.period_year, row.period_quarter) for row in [doc, *related]
               if row.period_year is not None and row.period_quarter is not None]
    assets = (await db.execute(select(AAAsset.in_service).where(
        AAAsset.enterprise_id == ent, AAAsset.company_id == cid, AAAsset.document_id == doc.id,
        AAAsset.deleted_at.is_(None)))).scalars().all()
    await protect_history(db, company, dates, periods, from_date=min(assets) if assets else None, doing=doing)
    await protect_bank_links(db, company, lines, doing=doing)
    writeoffs = (await db.execute(select(AAJournalEntry.writeoff_items).where(
        AAJournalEntry.enterprise_id == ent, AAJournalEntry.company_id == cid,
        AAJournalEntry.deleted_at.is_(None), AAJournalEntry.writeoff_items != []))).scalars().all()
    if any(str(i.get("id")) == str(doc.id) for items in writeoffs for i in items):
        refuse(f"This document is part of a write-off. Undo the write-off before {doing}.")
    marked = (await db.execute(select(AADocument.cwt_2307).where(
        AADocument.enterprise_id == ent, AADocument.company_id == cid, AADocument.deleted_at.is_(None),
        AADocument.cwt_2307 != {}))).scalars().all()
    if (doc.cwt_2307 or {}).get("status") == "received" or any(
        str(m.get("document_id")) == str(doc.id) for m in marked
    ):
        refuse(f"A received 2307 is linked to this document. Clear that mark before {doing}.")
    return lines


async def protect_entry(db: AsyncSession, company: AACompany, row: AAJournalEntry) -> list[AABankLine]:
    await lock_firm(db, company.enterprise_id)
    lines = list((await db.execute(select(AABankLine).where(
        AABankLine.enterprise_id == company.enterprise_id, AABankLine.company_id == company.id,
        or_((AABankLine.match_kind == "journal") & (AABankLine.matched_ref == str(row.id)),
            AABankLine.match_status.notin_(("confirmed", "excluded")) &
            AABankLine.candidates.contains([{"kind": "journal", "ref": str(row.id)}]))))).scalars().all())
    await protect_history(db, company, [row.entry_date, *[l.line_date for l in lines]],
                          from_date=row.entry_date if row.kind == "opening" or row.writeoff_items else None)
    await protect_bank_links(db, company, lines)
    return lines


async def protect_opening_item(db: AsyncSession, company: AACompany, row: AAOpeningItem) -> list[AABankLine]:
    from app.services.accounting.books.bank import live_line
    from app.services.accounting.books.subledger import writeoff_rows
    from app.services.accounting.compute.books import CASH_KEYS

    await lock_firm(db, company.enterprise_id)
    ref = str(row.id)
    lines = list((await db.execute(select(AABankLine).where(
        AABankLine.enterprise_id == company.enterprise_id, AABankLine.company_id == company.id, live_line(),
        or_((AABankLine.match_kind == "document") & (AABankLine.matched_ref == ref),
            AABankLine.match_status.notin_(("confirmed", "excluded")) &
            AABankLine.candidates.contains([{"kind": "document", "ref": ref}]))))).scalars().all())
    # Opening items never post themselves; only their payments affect retained books and returns.
    await protect_history(db, company, [row.paid_on, *[l.line_date for l in lines]])
    await protect_bank_links(db, company, lines)
    if row.paid_on is not None:
        matched_dates = [l.line_date for l in lines if l.match_kind == "document" and l.matched_ref == ref
                         and l.account_code and l.match_status in ("matched", "confirmed")]
        accounts = select(AAAccount.code).where(
            AAAccount.enterprise_id == company.enterprise_id, AAAccount.company_id == company.id,
            AAAccount.code == row.paid_account if row.paid_account else
            AAAccount.system_key == CASH_KEYS.get(row.paid_via, "cash"))
        reconciled = (await db.execute(select(AABankReconciliation.id).where(
            AABankReconciliation.enterprise_id == company.enterprise_id,
            AABankReconciliation.company_id == company.id, AABankReconciliation.account_code.in_(accounts),
            AABankReconciliation.month_end >= row.paid_on, AABankReconciliation.voided_at.is_(None),
            # A bank match replaces the manual payment only from its own date onward.
            *([AABankReconciliation.month_end < min(matched_dates)] if matched_dates else []),
        ).limit(1))).first()
        if reconciled:
            refuse("This item's payment supports a bank reconciliation. Clear the reconciliation before deleting it.")
    if any(str(i.get("id")) == ref for _, _, items in await writeoff_rows(db, company) for i in items):
        refuse("This item is part of a write-off. Undo the write-off before deleting it.")
    return lines
