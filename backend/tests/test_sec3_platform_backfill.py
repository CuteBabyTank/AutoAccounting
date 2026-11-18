"""Legacy provenance is read through real RLS binding and enforced by real team/admin handlers."""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.sql.elements import TextClause

from app.models.accounting import AAAuditEvent
from app.models.user import User, UserRole
from app.routers import admin, team
from app.schemas.auth import UpdateMemberRequest
from app.services import platform_disabled_backfill as migration


class Rows:
    def __init__(self, rows: list):
        self.rows = rows

    def scalars(self) -> "Rows":
        return self

    def all(self) -> list:
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class Db:
    def __init__(self, user: User, events: list[AAAuditEvent]):
        self.user, self.events = user, events
        self.sync_session = SimpleNamespace(info={})
        self.bound: uuid.UUID | None = None
        self.added: list[AAAuditEvent] = []
        self.commits = 0

    async def execute(self, stmt, params=None) -> Rows:
        if isinstance(stmt, TextClause):
            self.bound = uuid.UUID(params["uid"])
            return Rows([])
        entity = stmt.column_descriptions[0]["entity"]
        if entity is AAAuditEvent:
            # No bound principal can read another ledger. Unbound queries see nothing.
            return Rows([e for e in self.events if e.enterprise_id == self.bound])
        return Rows([self.user])

    def add(self, event: AAAuditEvent) -> None:
        assert event.enterprise_id == self.bound, "system event violated the RLS INSERT boundary"
        self.added.append(event)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, user: User) -> None:
        pass


def fixtures() -> tuple:
    firm, platform = uuid.uuid4(), uuid.uuid4()
    user = User(id=uuid.uuid4(), enterprise_id=firm, role=UserRole.EMPLOYEE, email="legacy@example.test",
                nickname=None, is_active=False, platform_disabled_at=None, suspended_with_firm=False,
                created_at=datetime.now(timezone.utc))
    return user, firm, platform


def event(user: User, ledger: uuid.UUID, active: bool, days: int = 2, *, platform: bool = False) -> AAAuditEvent:
    return AAAuditEvent(id=uuid.uuid4(), enterprise_id=ledger, entity="platform_account" if platform else "team_member",
                        entity_id=str(user.id), action="update", before={"is_active": not active},
                        after={"is_active": active}, at=datetime.now(timezone.utc) - timedelta(days=days))


@pytest.mark.parametrize("history", ["platform", "ambiguous", "platform-then-firm", "firm-then-platform"])
async def test_backfill_restricts_legacy_disables_and_team_cannot_undo_them(history: str) -> None:
    user, firm, platform = fixtures()
    events = [] if history == "ambiguous" else [event(user, platform, False, platform=True)]
    if history == "platform-then-firm":
        events.append(event(user, firm, False, days=1))
    if history == "firm-then-platform":
        events.append(event(user, firm, False, days=3))
    db = Db(user, events)
    changed = await migration.reconcile_account(db, user.id, [firm, platform], platform)
    assert changed and user.platform_disabled_at is not None and not user.is_active
    if history != "ambiguous":
        assert user.platform_disabled_at == events[0].at
    assert len(db.added) == 1 and db.added[0].user_id is None
    assert db.added[0].entity == "platform_account" and db.added[0].reason
    assert not await migration.reconcile_account(db, user.id, [firm, platform], platform)
    assert len(db.added) == 1
    # Firm-side activation uses the marker just written; no mocked guard or identity binding.
    ctx = SimpleNamespace(enterprise=SimpleNamespace(id=firm), caller=SimpleNamespace(role=UserRole.ENTERPRISE))
    with pytest.raises(HTTPException) as exc:
        await team.update_member(user.id, UpdateMemberRequest(is_active=True), db=db, ctx=ctx)
    assert exc.value.status_code == 403 and db.commits == 0
    await admin.toggle_active(user.id, db=db, admin=SimpleNamespace(id=platform))
    assert user.is_active and user.platform_disabled_at is None and db.commits == 1


@pytest.mark.parametrize("history", ["firm", "cascade", "platform-reviewed-then-firm"])
async def test_backfill_preserves_proven_firm_only_suspensions(history: str) -> None:
    user, firm, platform = fixtures()
    events = [event(user, firm, False, days=1)] if history != "cascade" else []
    user.suspended_with_firm = history == "cascade"
    if history == "platform-reviewed-then-firm":
        events += [event(user, platform, False, days=4, platform=True),
                   event(user, platform, True, days=2, platform=True)]
    db = Db(user, events)
    assert not await migration.reconcile_account(db, user.id, [firm, platform], platform)
    assert user.platform_disabled_at is None and not db.added
    # Backfill leaves genuine firm suspensions manageable through the same handler.
    db.bound = firm
    ctx = SimpleNamespace(enterprise=SimpleNamespace(id=firm), caller=SimpleNamespace(role=UserRole.ENTERPRISE))
    await team.update_member(user.id, UpdateMemberRequest(is_active=True), db=db, ctx=ctx)
    assert user.is_active and db.commits == 1


async def test_cascade_marker_does_not_override_proven_individual_platform_disable() -> None:
    user, firm, platform = fixtures()
    user.suspended_with_firm = True
    db = Db(user, [event(user, platform, False, platform=True)])
    assert await migration.reconcile_account(db, user.id, [firm, platform], platform)
    assert user.platform_disabled_at is not None


async def test_dry_run_prints_proposed_restriction_without_mutating_or_auditing(capsys) -> None:
    user, firm, platform = fixtures()
    db = Db(user, [])
    assert await migration.reconcile_account(db, user.id, [firm, platform], platform, dry_run=True)
    assert user.platform_disabled_at is None and not db.added and not db.commits
    assert "ambiguous" in capsys.readouterr().out
