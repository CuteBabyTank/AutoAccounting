"""Firm management cannot undo a platform account restriction."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.dependencies import _get_active_user
from app.models.user import User, UserRole
from app.routers import admin, team
from app.schemas.auth import AddMemberRequest, UpdateMemberRequest
from app.services import auth_service, password_auth
from app.services.accounting import schema


class Session:
    def __init__(self, user: User):
        self.user, self.statements, self.commits = user, [], 0

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(scalar_one_or_none=lambda: self.user, scalar_one=lambda: 1, rowcount=1)

    async def commit(self):
        self.commits += 1

    async def refresh(self, user):
        pass

    def add(self, row):
        pass


def disabled_user(role=UserRole.EMPLOYEE) -> User:
    user = User(id=uuid.uuid4(), email="disabled@example.com", role=role, is_active=False,
                email_verified_at=datetime.now(timezone.utc), suspended_with_firm=True,
                created_at=datetime.now(timezone.utc),
                privacy_policy_version=auth_service.PRIVACY_POLICY_VERSION,
                terms_version=auth_service.TERMS_VERSION)
    # Setting the attribute also lets the pre-fix model reach the vulnerable decision.
    user.platform_disabled_at = datetime.now(timezone.utc)
    return user


async def test_team_cannot_add_a_platform_disabled_signup():
    user = disabled_user(UserRole.UNVERIFIED)
    db = Session(user)
    ctx = SimpleNamespace(enterprise=SimpleNamespace(id=uuid.uuid4()), caller=SimpleNamespace(role=UserRole.ENTERPRISE))
    with pytest.raises(HTTPException) as exc:
        await team.add_member(AddMemberRequest(email=user.email), db=db, ctx=ctx)
    assert exc.value.status_code == 403
    assert user.role == UserRole.UNVERIFIED and not user.is_active and db.commits == 0


@pytest.mark.parametrize("caller_role", [UserRole.ENTERPRISE, UserRole.MANAGER])
async def test_team_cannot_reactivate_a_platform_disabled_employee(caller_role):
    user = disabled_user()
    db = Session(user)
    ctx = SimpleNamespace(enterprise=SimpleNamespace(id=uuid.uuid4()), caller=SimpleNamespace(role=caller_role))
    with pytest.raises(HTTPException) as exc:
        await team.update_member(user.id, UpdateMemberRequest(is_active=True), db=db, ctx=ctx)
    assert exc.value.status_code == 403 and not user.is_active and db.commits == 0


async def test_platform_restriction_is_enforced_even_if_membership_sets_active():
    user = disabled_user()
    user.is_active = True
    with pytest.raises(HTTPException) as exc:
        await _get_active_user(Session(user), {"sub": str(user.id), "pwd": 0})
    assert exc.value.status_code == 403


async def test_admin_sets_and_audits_then_clears_platform_restriction(monkeypatch):
    user = disabled_user()
    user.is_active, user.platform_disabled_at = True, None
    events = []
    db = Session(user)

    def record(*args, **kwargs):
        assert db.commits == len(events)
        events.append(kwargs)

    monkeypatch.setattr(admin.audit, "record", record)
    actor = SimpleNamespace(id=uuid.uuid4())
    await admin.toggle_active(user.id, db=db, admin=actor)
    assert not user.is_active and user.platform_disabled_at is not None
    assert events[-1]["after"]["platform_disabled_at"] is not None
    await admin.toggle_active(user.id, db=db, admin=actor)
    assert user.is_active and user.platform_disabled_at is None
    assert events[-1]["before"]["platform_disabled_at"] is not None


async def test_firm_reactivation_excludes_individually_disabled_members(monkeypatch):
    owner = disabled_user(UserRole.ENTERPRISE)
    db = Session(owner)
    monkeypatch.setattr(admin.audit, "record", lambda *args, **kwargs: None)
    await admin.toggle_active(owner.id, db=db, admin=SimpleNamespace(id=uuid.uuid4()))
    sql = str(db.statements[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "users.platform_disabled_at IS NULL" in sql


async def test_removing_a_member_preserves_platform_restriction(monkeypatch):
    user = disabled_user()
    stamp = user.platform_disabled_at
    monkeypatch.setattr(team.audit, "record", lambda *args, **kwargs: None)
    ctx = SimpleNamespace(enterprise=SimpleNamespace(id=uuid.uuid4()), caller=SimpleNamespace(role=UserRole.ENTERPRISE))
    await team.remove_member(user.id, db=Session(user), ctx=ctx)
    # Removal must never turn a platform-disabled account into an addable signup.
    with pytest.raises(HTTPException) as exc:
        await team.add_member(AddMemberRequest(email=user.email), db=Session(user), ctx=ctx)
    assert exc.value.status_code == 403 and user.platform_disabled_at == stamp


@pytest.mark.parametrize("issuer", ["password", "google", "dev"])
async def test_login_refuses_the_platform_flag_even_with_active_true(monkeypatch, issuer):
    user = disabled_user()
    user.is_active, user.password_hash, user.failed_logins = True, "hash", 0
    db = Session(user)

    async def verify(*args):
        return True

    monkeypatch.setattr(password_auth.passwords, "verify_password", verify)
    monkeypatch.setattr(password_auth.passwords, "needs_rehash", lambda value: False)
    monkeypatch.setattr(auth_service.id_token, "verify_oauth2_token",
                        lambda *args, **kwargs: {"email": user.email, "email_verified": True})
    monkeypatch.setattr(auth_service, "dev_login_enabled", lambda: True)
    with pytest.raises(HTTPException) as exc:
        if issuer == "password":
            await password_auth.login(db, user.email, "dummy")
        elif issuer == "google":
            await auth_service.google_login(db, "dummy", "client")
        else:
            await auth_service.dev_login(db, user.email)
    assert exc.value.status_code == 403


def test_platform_column_exists_in_model_and_additive_migrations():
    assert "platform_disabled_at" in User.__table__.columns
    assert any("ADD COLUMN IF NOT EXISTS platform_disabled_at TIMESTAMPTZ" in sql
               for sql in schema.column_statements())
