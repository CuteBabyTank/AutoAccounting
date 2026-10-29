"""Firm-scoped facts used before deleting accounting sources. Never commits or mutates records."""
from datetime import date
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import (
    AAAsset, AABankLine, AABankReconciliation, AABankStatement, AABookClose, AACompany, AADocument,
    AAJournalEntry, AAPeriod, AAWorkItem,
)
from app.services.accounting.compute.retention import deletion_problem
from app.services.accounting.assignment import lock_firm


def refuse(message: str) -> None:
    raise HTTPException(status.HTTP_409_CONFLICT, message)


async def protect_history(db: AsyncSession, company: AACompany, dates: Iterable[date | None] = (),
                          periods: Iterable[tuple[int, int]] = (), *, from_date: date | None = None) -> None:
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
    problem = deletion_problem([d for d in dates if d is not None], periods, closes, filed,
                               company.fiscal_year_end_month, from_date=from_date)
    if problem:
        refuse(problem)


async def protect_bank_links(db: AsyncSession, company: AACompany, lines: list[AABankLine]) -> None:
    if not lines:
        return
    if any(l.match_status == "confirmed" for l in lines):
        refuse("A bank line is confirmed against this record. Undo the match on Bank before deleting it.")
    recs = (await db.execute(select(AABankReconciliation).where(
        AABankReconciliation.enterprise_id == company.enterprise_id,
        AABankReconciliation.company_id == company.id, AABankReconciliation.voided_at.is_(None)))).scalars().all()
    if any(r.account_code == l.account_code and l.line_date <= r.month_end
           for r in recs for l in lines):
        refuse("This record supports a bank reconciliation. Undo its bank match/reconciliation before deleting it.")


async def protect_document(db: AsyncSession, company: AACompany, doc: AADocument) -> list[AABankLine]:
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
    await protect_history(db, company, dates, periods, from_date=min(assets) if assets else None)
    await protect_bank_links(db, company, lines)
    writeoffs = (await db.execute(select(AAJournalEntry.writeoff_items).where(
        AAJournalEntry.enterprise_id == ent, AAJournalEntry.company_id == cid,
        AAJournalEntry.deleted_at.is_(None), AAJournalEntry.writeoff_items != []))).scalars().all()
    if any(str(i.get("id")) == str(doc.id) for items in writeoffs for i in items):
        refuse("This document is part of a write-off. Undo the write-off before deleting it.")
    marked = (await db.execute(select(AADocument.cwt_2307).where(
        AADocument.enterprise_id == ent, AADocument.company_id == cid, AADocument.deleted_at.is_(None),
        AADocument.cwt_2307 != {}))).scalars().all()
    if (doc.cwt_2307 or {}).get("status") == "received" or any(
        str(m.get("document_id")) == str(doc.id) for m in marked
    ):
        refuse("A received 2307 is linked to this document. Clear that mark before deleting it.")
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
