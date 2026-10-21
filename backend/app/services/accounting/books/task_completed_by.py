"""Backfill done task actors from audit evidence, without guessing from the assignee.

    python -m app.services.accounting.books.task_completed_by [--dry-run]

Runs per firm under RLS, is audited, and leaves completed_by values already present alone.
"""
import argparse
import asyncio
import uuid
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.dependencies import bind_session_user
from app.models.accounting import AAAuditEvent, AATask
from app.models.user import User, UserRole
from app.services.accounting import audit
from app.services.accounting.assignment import lock_firm
from app.services.accounting.compute.work_history import completion_actor

SYSTEM = SimpleNamespace(id=None, email="AutoAccounting (completion history backfill)")


async def backfill_firm(db: AsyncSession, ent: uuid.UUID) -> list[AATask]:
    await lock_firm(db, ent)
    tasks = list((await db.execute(select(AATask).where(
        AATask.enterprise_id == ent, AATask.status == "done", AATask.completed_by.is_(None))
        .with_for_update())).scalars())
    if not tasks:
        return []
    events = (await db.execute(select(AAAuditEvent).where(
        AAAuditEvent.enterprise_id == ent, AAAuditEvent.entity == "task",
        AAAuditEvent.entity_id.in_([str(t.id) for t in tasks]),
    ).order_by(AAAuditEvent.at, AAAuditEvent.id))).scalars()
    grouped = defaultdict(list)
    for event in events:
        grouped[event.entity_id].append({"after": event.after, "user_id": event.user_id})
    changed = []
    for task in tasks:
        actor = completion_actor(grouped[str(task.id)])
        if actor is None:
            continue
        task.completed_by = actor
        audit.record(db, ent=ent, company_id=task.company_id, user=SYSTEM, entity="task", entity_id=task.id,
                     action="update", label=task.title, before={"completed_by": None},
                     after={"completed_by": actor}, reason="Backfilled completion actor from task status audit evidence")
        changed.append(task)
    return changed


async def backfill(dry_run: bool = False) -> int:
    async with async_session() as db:
        firms = list((await db.execute(select(User.id).where(
            User.role.in_((UserRole.ENTERPRISE, UserRole.ADMIN))))).scalars())
    total = 0
    for ent in firms:
        async with async_session() as db:
            await bind_session_user(db, str(ent))
            changed = await backfill_firm(db, ent)
            total += len(changed)
            for task in changed:
                print(f"{task.id}: completed by {task.completed_by}")
            if dry_run:
                await db.rollback()
            else:
                await db.commit()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    total = asyncio.run(backfill(args.dry_run))
    print(f"{'Would backfill' if args.dry_run else 'Backfilled'} {total} tasks")


if __name__ == "__main__":
    main()
