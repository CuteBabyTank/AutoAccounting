"""The printed branch code on documents read before it was kept (one-off, safe to re-run).

    docker compose exec backend python -m app.services.accounting.books.tin_branches [--dry-run]

Fills ``seller_branch`` / ``buyer_branch`` from the TIN Gemini read (``raw``), only where the document's TIN still
is that TIN (a person's correction is never overwritten) and no branch is stored yet. Display-only data, so
``updated_at`` is kept and generated versions don't turn stale. Runs firm by firm with RLS bound.
"""

import argparse
import asyncio
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.dependencies import bind_session_user
from app.models.accounting import AADocument
from app.models.user import User, UserRole
from app.services.accounting.parsing import normalize_tin, printed_branch


def branch_from_raw(raw: dict | None, side: str, tin: str) -> str:
    """The branch printed with ``side``'s TIN in what Gemini read, when that TIN is still the document's."""
    party = raw.get(side) if isinstance(raw, dict) else None
    printed = str(party.get("tin") or "") if isinstance(party, dict) else ""
    if not tin or normalize_tin(printed)[0] != tin:
        return ""
    return printed_branch(printed)


async def fill_branches(db: AsyncSession, ent: uuid.UUID) -> list[AADocument]:
    """Set the missing branch codes of the firm's documents; returns the documents that changed (caller commits)."""
    docs = (await db.execute(select(AADocument).where(
        AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None), AADocument.raw.is_not(None),
        or_((AADocument.seller_branch == "") & (AADocument.seller_tin != ""),
            (AADocument.buyer_branch == "") & (AADocument.buyer_tin != "")),
    ))).scalars().all()
    changed = []
    for doc in docs:
        seller = doc.seller_branch or branch_from_raw(doc.raw, "seller", doc.seller_tin)
        buyer = doc.buyer_branch or branch_from_raw(doc.raw, "buyer", doc.buyer_tin)
        if (seller, buyer) == (doc.seller_branch, doc.buyer_branch):
            continue
        doc.seller_branch, doc.buyer_branch = seller, buyer
        doc.updated_at = AADocument.updated_at   # not an edit: keep the timestamp
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
            changed = await fill_branches(db, firm)
            total += len(changed)
            for doc in changed:
                print(f"{doc.id} #{doc.doc_number or '-'}: seller {doc.seller_tin}-{doc.seller_branch or '?'}, "
                      f"buyer {doc.buyer_tin}-{doc.buyer_branch or '?'}")
            if dry_run:
                await db.rollback()
            else:
                await db.commit()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="list what would be filled without changing anything")
    args = parser.parse_args()
    total = asyncio.run(backfill(args.dry_run))
    print(f"{'Would fill' if args.dry_run else 'Filled'} {total} document(s)")


if __name__ == "__main__":
    main()
