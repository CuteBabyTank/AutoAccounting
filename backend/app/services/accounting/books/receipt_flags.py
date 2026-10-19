"""The receipt-validity flag on documents stored before it existed (one-off, safe to re-run).

    docker compose exec backend python -m app.services.accounting.books.receipt_flags [--dry-run]

Supplier invoices / receipts still open for review get ``receipt_incomplete`` when the seller's name, TIN, address or
the serial number is missing, or the paper isn't a BIR invoice / receipt (an acknowledgement receipt, an order slip).
Documents a person already reviewed and quarters already filed are left alone. Only the review flag changes, never a
posting, so ``updated_at`` is kept and generated versions don't turn stale. Runs firm by firm with RLS bound.
"""

import argparse
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.dependencies import bind_session_user
from app.models.accounting import AADocument, AAPeriod
from app.models.user import User, UserRole
from app.services.accounting.review_rules import RECEIPT_REASON, sync_receipt_flag


async def flag_receipts(db: AsyncSession, ent: uuid.UUID) -> list[AADocument]:
    """Bring the flag up to date on the firm's unreviewed supplier documents; returns the documents that changed
    (the caller commits)."""
    docs = (await db.execute(select(AADocument).where(
        AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None), AADocument.reviewed.is_(False),
        AADocument.client_role == "buyer", AADocument.category.in_(("purchases", "expenses")),
        AADocument.doc_type.in_(("invoice", "receipt")), ~AADocument.review_reasons.contains([RECEIPT_REASON]),
    ))).scalars().all()
    filed = {(p.company_id, p.year, p.quarter) for p in (await db.execute(select(AAPeriod).where(
        AAPeriod.enterprise_id == ent, AAPeriod.quarter >= 1))).scalars() if p.filed_at is not None or p.filed_forms}
    changed = []
    for doc in docs:
        if (doc.company_id, doc.period_year, doc.period_quarter) in filed or not sync_receipt_flag(doc):
            continue
        doc.updated_at = AADocument.updated_at   # a flag isn't an edit: keep the timestamp
        changed.append(doc)
    return changed


async def backfill(dry_run: bool = False) -> int:
    async with async_session() as db:  # users isn't under RLS
        firms = [r[0] for r in await db.execute(
            select(User.id).where(User.role.in_([UserRole.ENTERPRISE, UserRole.ADMIN])))]
    total = 0
    for firm in firms:
        async with async_session() as db:
            await bind_session_user(db, str(firm))
            changed = await flag_receipts(db, firm)
            total += len(changed)
            for doc in changed:
                print(f"{doc.id} {doc.seller_name or '(no seller)'} #{doc.doc_number or '-'}: "
                      f"{doc.review_notes.get(RECEIPT_REASON)}")
            if dry_run:
                await db.rollback()
            else:
                await db.commit()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="list what would be flagged without changing anything")
    args = parser.parse_args()
    total = asyncio.run(backfill(args.dry_run))
    print(f"{'Would flag' if args.dry_run else 'Flagged'} {total} document(s)")


if __name__ == "__main__":
    main()
