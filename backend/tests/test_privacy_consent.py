"""First Google sign-in only creates an account once the person accepts the privacy policy."""

import asyncio
import uuid

import pytest
from fastapi import HTTPException

from app.models.user import User, UserRole
from app.services import auth_service


class _Result:
    def __init__(self, user):
        self._user = user

    def scalar_one_or_none(self):
        return self._user

    def first(self):
        return None


class _Session:
    """Just enough AsyncSession for google_login: one email lookup, then add / commit / refresh."""

    def __init__(self, existing: User | None = None):
        self.existing = existing
        self.added: list[User] = []
        self.commits = 0

    async def execute(self, _statement):
        return _Result(self.existing)

    def add(self, obj):
        obj.id = obj.id or uuid.uuid4()
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _obj, *_args):
        return None


@pytest.fixture(autouse=True)
def google_says(monkeypatch):
    monkeypatch.setattr(
        auth_service.id_token, "verify_oauth2_token",
        lambda *a, **k: {"email": "new.person@example.com", "email_verified": True},
    )
    monkeypatch.setattr(auth_service.settings, "bootstrap_admin_email", "")


def _login(db, accept: bool):
    return asyncio.run(auth_service.google_login(db, "token", "client-id", accept))


def test_new_person_without_consent_is_not_registered():
    db = _Session()
    with pytest.raises(HTTPException) as exc:
        _login(db, accept=False)
    assert exc.value.status_code == 428
    assert exc.value.detail == auth_service.CONSENT_REQUIRED
    assert db.added == [] and db.commits == 0


def test_new_person_who_agrees_is_registered_with_the_policy_version():
    db = _Session()
    user, token = _login(db, accept=True)
    assert db.added == [user] and token
    assert user.role == UserRole.UNVERIFIED
    assert user.privacy_accepted_at is not None
    assert user.privacy_policy_version == auth_service.PRIVACY_POLICY_VERSION


def test_existing_account_signs_in_without_being_asked_again():
    existing = User(id=uuid.uuid4(), email="new.person@example.com", role=UserRole.EMPLOYEE, is_active=True)
    db = _Session(existing)
    user, token = _login(db, accept=False)
    assert user is existing and token
    assert db.added == []
