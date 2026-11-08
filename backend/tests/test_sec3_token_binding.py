"""Credential changes revoke even sessions issued earlier in the same second."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jose import jwt as jose_jwt

from app.auth.jwt import create_access_token, create_sse_token, verify_token
from app.config import settings
from app.dependencies import _get_active_user
from app.models.user import User, UserRole
from app.services import auth_service, password_auth


class Session:
    def __init__(self, user: User):
        self.user = user

    async def execute(self, statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.user)

    async def commit(self):
        pass

    async def refresh(self, user):
        pass


def account() -> User:
    return User(id=uuid.uuid4(), email="binding@example.test", role=UserRole.EMPLOYEE,
                is_active=True, password_hash="old", failed_logins=0,
                email_verified_at=datetime.now(timezone.utc),
                password_changed_at=datetime.now(timezone.utc).replace(microsecond=100),
                privacy_policy_version=auth_service.PRIVACY_POLICY_VERSION,
                terms_version=auth_service.TERMS_VERSION)


async def test_login_then_reset_in_the_same_second_revokes_only_the_old_token(monkeypatch):
    user = account()
    db = Session(user)

    async def verify(hashed, supplied):
        return True

    async def hash_password(supplied):
        return "new"

    async def use_link(*args):
        return user, SimpleNamespace()

    monkeypatch.setattr(password_auth.passwords, "verify_password", verify)
    monkeypatch.setattr(password_auth.passwords, "needs_rehash", lambda value: False)
    monkeypatch.setattr(password_auth.passwords, "hash_password", hash_password)
    monkeypatch.setattr(password_auth.passwords, "problem", lambda *args: None)
    monkeypatch.setattr(password_auth, "_use_link", use_link)
    _, old = await password_auth.login(db, user.email, "old password")
    old_payload = verify_token(old)
    # Freeze the reset at a later microsecond of the login's iat second.
    reset_at = datetime.fromtimestamp(old_payload["iat"], timezone.utc).replace(microsecond=900000)

    class Clock:
        @staticmethod
        def now(tz):
            return reset_at

    monkeypatch.setattr(password_auth, "datetime", Clock)
    _, new = await password_auth.reset_password(db, "dummy", "new password")
    with pytest.raises(HTTPException) as exc:
        await _get_active_user(db, old_payload)
    assert exc.value.status_code == 401
    assert await _get_active_user(db, verify_token(new)) is user


@pytest.mark.parametrize("claim", [None, True, "0", 0.0])
async def test_legacy_or_malformed_credential_claims_are_rejected(claim):
    user = account()
    user.password_changed_at = None
    payload = {"sub": str(user.id), "iat": int(datetime.now(timezone.utc).timestamp())}
    if claim is not None:
        payload["pwd"] = claim
    with pytest.raises(HTTPException) as exc:
        await _get_active_user(Session(user), payload)
    assert exc.value.status_code == 401


@pytest.mark.parametrize("issuer", ["verify", "google", "dev"])
async def test_other_login_paths_mint_a_credential_bound_token(monkeypatch, issuer):
    user = account()
    db = Session(user)
    if issuer == "verify":
        user.email_verified_at = None

    async def use_link(*args):
        return user, SimpleNamespace(pending_password_hash="verified-password")

    monkeypatch.setattr(password_auth, "_use_link", use_link)
    monkeypatch.setattr(auth_service.id_token, "verify_oauth2_token",
                        lambda *args, **kwargs: {"email": user.email, "email_verified": True})
    monkeypatch.setattr(auth_service, "dev_login_enabled", lambda: True)
    if issuer == "verify":
        _, token = await password_auth.verify_email(db, "dummy")
    elif issuer == "google":
        _, token = await auth_service.google_login(db, "dummy", "client")
    else:
        _, token = await auth_service.dev_login(db, user.email)
    payload = verify_token(token)
    assert type(payload.get("pwd")) is int
    assert await _get_active_user(db, payload) is user
    user.password_changed_at += timedelta(microseconds=1)
    with pytest.raises(HTTPException) as exc:
        await _get_active_user(db, payload)
    assert exc.value.status_code == 401


async def test_sse_and_rotated_key_tokens_keep_the_same_binding(monkeypatch):
    user = account()
    token = create_sse_token(str(user.id), password_changed_at=user.password_changed_at)
    payload = verify_token(token)
    assert payload["scope"] == "sse"
    assert await _get_active_user(Session(user), payload) is user
    previous = "previous-test-secret-" * 3
    monkeypatch.setattr(settings, "jwt_secret_previous", previous)
    rotated = jose_jwt.encode(payload, previous, algorithm="HS256", headers={"kid": "previous"})
    assert await _get_active_user(Session(user), verify_token(rotated)) is user
    user.password_changed_at += timedelta(microseconds=1)
    with pytest.raises(HTTPException):
        await _get_active_user(Session(user), verify_token(rotated))


def test_access_tokens_always_carry_the_null_credential_version():
    assert verify_token(create_access_token(str(uuid.uuid4())))["pwd"] == 0
