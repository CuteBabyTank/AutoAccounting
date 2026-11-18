"""Reconcile legacy inactive accounts with platform-disable provenance (safe to re-run).

    python -m app.services.platform_disabled_backfill [--dry-run]

Read the durable aa_audit_events ledgers under each owner's/admin's RLS identity. An individual
platform disable survives later firm events; a later platform activation clears that provenance.
Preserve proven firm-only disables and marked firm cascades. Restrict ambiguous inactive accounts
until platform review. No historical admin activation log exists outside aa_audit_events in this app.
Each new restriction is a system event in the selected platform admin's ledger.
"""
import argparse
import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.dependencies import bind_session_user
from app.models.accounting import AAAuditEvent
from app.models.user import User, UserRole
from app.services.accounting import audit


async def reconcile_account(db: AsyncSession, user_id: uuid.UUID, scopes: list[uuid.UUID],
                            audit_scope: uuid.UUID, *, dry_run: bool = False) -> bool:
    """Re-read one account and its activation history under a row lock; caller commits.

    Return whether a restriction was/would be added. Dry-run changes neither the account nor its audit log.
    """
    user = (await db.execute(select(User).where(User.id == user_id).with_for_update()
                             .execution_options(populate_existing=True))).scalar_one_or_none()
    if user is None or user.is_active or user.platform_disabled_at is not None:
        return False
    events: list[AAAuditEvent] = []
    for scope in scopes:
        await bind_session_user(db, str(scope))
        events.extend((await db.execute(select(AAAuditEvent).where(
            AAAuditEvent.enterprise_id == scope, AAAuditEvent.entity_id == str(user.id),
            AAAuditEvent.entity.in_(("platform_account", "team_member")),
        ))).scalars().all())
    # Audit rows are diffs: a role/budget/access edit contains no is_active field and proves nothing.
    changes = sorted((e for e in events if type((e.after or {}).get("is_active")) is bool),
                     key=lambda e: (e.at, str(e.id)))
    platform = [e for e in changes if e.entity == "platform_account"]
    last_platform = platform[-1] if platform else None
    if last_platform is not None and last_platform.after["is_active"] is False:
        stamp, provenance = last_platform.at, "individual platform disable from audit history"
    else:
        firm = [e for e in changes if e.entity == "team_member" and e.enterprise_id == user.enterprise_id
                and (last_platform is None or e.at > last_platform.at)]
        cascade = (user.suspended_with_firm and user.enterprise_id is not None
                   and user.role in (UserRole.EMPLOYEE, UserRole.MANAGER))
        if (firm and firm[-1].after["is_active"] is False) or cascade:
            print(f"{user.id} {user.email}: preserved firm-only suspension")
            return False
        stamp, provenance = datetime.now(timezone.utc), "ambiguous legacy disable; platform review required"
    print(f"{user.id} {user.email}: {'would restrict' if dry_run else 'restricted'} ({provenance})")
    if dry_run:
        return True
    await bind_session_user(db, str(audit_scope))
    before = audit.snapshot(user, ("platform_disabled_at",))
    user.platform_disabled_at = stamp
    audit.record(db, ent=audit_scope, company_id=None, user=None, entity="platform_account", entity_id=user.id,
                 action="update", before=before, after=audit.snapshot(user, ("platform_disabled_at",)),
                 label=user.email, reason=f"System platform-disabled provenance backfill: {provenance}")
    return True


async def backfill(dry_run: bool = False) -> int:
    async with async_session() as db:  # users is not under RLS
        owners = (await db.execute(select(User).where(User.role.in_((UserRole.ADMIN, UserRole.ENTERPRISE)))
                                   .order_by(User.created_at, User.id))).scalars().all()
        admins = [u.id for u in owners if u.role == UserRole.ADMIN]
        if not admins:
            raise ValueError("A platform admin is required for the backfill's system audit ledger")
        scopes = [u.id for u in owners]
        candidates = (await db.execute(select(User.id).where(
            User.is_active.is_(False), User.platform_disabled_at.is_(None)))).scalars().all()
    total = 0
    for user_id in candidates:
        async with async_session() as db:
            total += int(await reconcile_account(db, user_id, scopes, admins[0], dry_run=dry_run))
            if dry_run:
                await db.rollback()
            else:
                await db.commit()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print proposed restrictions without changing anything")
    args = parser.parse_args()
    total = asyncio.run(backfill(args.dry_run))
    print(f"{'Would restrict' if args.dry_run else 'Restricted'} {total} account(s)")


if __name__ == "__main__":
    main()
