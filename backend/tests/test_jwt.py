"""JWT issue + verify. Critical auth boundary; covers tampering and expiry."""

import time
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt as jose_jwt

from app.auth.jwt import create_access_token, verify_token
from app.config import settings


def test_round_trip():
    user_id = str(uuid.uuid4())
    token = create_access_token(user_id)
    payload = verify_token(token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert "exp" in payload and "iat" in payload and "jti" in payload


def test_invalid_signature_rejected():
    user_id = str(uuid.uuid4())
    token = create_access_token(user_id)
    # Flip the last char of signature
    parts = token.rsplit(".", 1)
    bad = parts[0] + "." + ("A" if parts[1][0] != "A" else "B") + parts[1][1:]
    assert verify_token(bad) is None


def test_garbage_token_rejected():
    assert verify_token("not-a-jwt") is None
    assert verify_token("") is None


def test_expired_token_rejected():
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "iat": now - timedelta(hours=10),
        "exp": now - timedelta(hours=1),
        "jti": str(uuid.uuid4()),
    }
    expired = jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    assert verify_token(expired) is None


def test_non_uuid_sub_rejected():
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "not-a-uuid",
        "iat": now,
        "exp": now + timedelta(hours=1),
        "jti": str(uuid.uuid4()),
    }
    bad = jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    assert verify_token(bad) is None


def test_missing_sub_rejected():
    now = datetime.now(timezone.utc)
    payload = {
        "iat": now,
        "exp": now + timedelta(hours=1),
        "jti": str(uuid.uuid4()),
    }
    bad = jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    assert verify_token(bad) is None
