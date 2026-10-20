"""Books are on by default: the start date a company gets when nobody picked one.

    docker compose exec backend python -m app.services.accounting.books.books_start [--dry-run]

A new company starts its books on the first day of its current fiscal year (``create_company``, unless the request
sends ``books_start`` itself; an explicit null keeps it returns-only). The command turns books on for companies
stored before that, from the first quarter with dated documents (else the current fiscal year), with an audit event.
Re-runnable: a company that already has a books start is left alone. Runs firm by firm with RLS bound.
"""

import argparse
import asyncio
import uuid
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.dependencies import bind_session_user
from app.models.accounting import AACompany, AADocument
from app.models.user import User, UserRole
from app.services.accounting import audit
from app.services.accounting.books.loader import touch_books
from app.services.accounting.compute.due_dates import quarter_start
from app.services.accounting.periods import period_for

SYSTEM = SimpleNamespace(id=None, email="AutoAccounting (books on by default)")


def default_books_start(fiscal_year_end_month: int, first_period: tuple[int, int] | None, today: date) -> date:
    """The first day of ``first_period`` (fiscal year, quarter), or of the fiscal year ``today`` is in."""
    if first_period is not None:
        return quarter_start(first_period[0], first_period[1], fiscal_year_end_month)
    return quarter_start(period_for(today, fiscal_year_end_month).fiscal_year, 1, fiscal_year_end_month)


async def turn_on_books(db: AsyncSession, ent: uuid.UUID, today: date) -> list[AACompany]:
    """Give the firm's returns-only companies a books start; returns the companies changed (caller commits)."""
    companies = (await db.execute(select(AACompany).where(
        AACompany.enterprise_id == ent, AACompany.books_start.is_(None),
    ))).scalars().all()
    changed = []
    for company in companies:
        first = (await db.execute(
            select(AADocument.period_year, AADocument.period_quarter)
            .where(AADocument.enterprise_id == ent, AADocument.company_id == company.id,
                   AADocument.deleted_at.is_(None), AADocument.period_year.is_not(None))
            .order_by(AADocument.period_year, AADocument.period_quarter).limit(1)
        )).first()
        before = audit.snapshot(company, ("books_start",))
        company.books_start = default_books_start(company.fiscal_year_end_month, tuple(first) if first else None, today)
        touch_books(company)
        audit.record(db, ent=ent, company_id=company.id, user=SYSTEM, entity="company", entity_id=company.id,
                     action="update", before=before, after=audit.snapshot(company, ("books_start",)),
                     label=company.registered_name, reason="Books are on by default (turned on for a company stored "
                                                           "before that)")
        changed.append(company)
    return changed


async def backfill(dry_run: bool = False, today: date | None = None) -> int:
    today = today or date.today()
    async with async_session() as db:  # users isn't under RLS
        firms = [r[0] for r in await db.execute(
            select(User.id).where(User.role.in_([UserRole.ENTERPRISE, UserRole.ADMIN])))]
    total = 0
    for firm in firms:
        async with async_session() as db:
            await bind_session_user(db, str(firm))
            changed = await turn_on_books(db, firm, today)
            total += len(changed)
            for company in changed:
                print(f"{company.id} {company.registered_name}: books start {company.books_start:%b %d, %Y}")
            if dry_run:
                await db.rollback()
            else:
                await db.commit()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="list what would be turned on without changing anything")
    args = parser.parse_args()
    total = asyncio.run(backfill(args.dry_run))
    print(f"{'Would turn on' if args.dry_run else 'Turned on'} books for {total} compan{'y' if total == 1 else 'ies'}")


if __name__ == "__main__":
    main()
