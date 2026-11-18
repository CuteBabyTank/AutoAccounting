"""
JWT token creation and verification.

Supports key rotation via JWT_SECRET_PREVIOUS:
  - New tokens are signed with `kid="current"` using settings.jwt_secret.
  - Verification tries the current secret first; if a token's `kid="previous"`
    (or verification fails with current), tries jwt_secret_previous when set.
  - To rotate: copy old secret to JWT_SECRET_PREVIOUS, set JWT_SECRET to new
    value, redeploy, wait until all old tokens expire (jwt_expiry_hours), then
    clear JWT_SECRET_PREVIOUS.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from app.config import settings

# Pin the JWT algorithm at the module level so an env var or compromised
# config object cannot downgrade verification (e.g. to "none" or to an
# RS-style alg that would interpret the HMAC secret as a public key).
_JWT_ALG = "HS256"

_KID_CURRENT = "current"
_KID_PREVIOUS = "previous"


# Short-lived ticket used only for the SSE stream, whose token must travel in
# the request URL (EventSource cannot set headers). Keeping it brief and
# single-scope time-boxes any exposure via access logs / Referer.
_SSE_TOKEN_TTL_MINUTES = 1
_SCOPE_SSE = "sse"


def credential_version(changed_at: datetime | None) -> int:
    """Exact UTC microseconds; avoid both JWT's whole seconds and float rounding."""
    if changed_at is None:
        return 0
    delta = changed_at.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def create_access_token(
    user_id: str,
    *,
    scope: str | None = None,
    expires_minutes: int | None = None,
    password_changed_at: datetime | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    if expires_minutes is not None:
        expire = now + timedelta(minutes=expires_minutes)
    else:
        expire = now + timedelta(hours=settings.jwt_expiry_hours)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),
        "pwd": credential_version(password_changed_at),
    }
    if scope is not None:
        payload["scope"] = scope
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=_JWT_ALG,
        headers={"kid": _KID_CURRENT},
    )


def create_sse_token(user_id: str, *, password_changed_at: datetime | None = None) -> str:
    """Mint a short-lived, SSE-scoped token for the realtime stream URL."""
    return create_access_token(
        user_id, scope=_SCOPE_SSE, expires_minutes=_SSE_TOKEN_TTL_MINUTES,
        password_changed_at=password_changed_at,
    )


def _decode_with(token: str, secret: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[_JWT_ALG],
            options={"require_exp": True, "require_sub": True},
        )
        uuid.UUID(payload["sub"])
        return payload
    except (JWTError, ValueError, KeyError):
        return None


def verify_token(token: str) -> Optional[dict]:
    # Inspect kid header without verifying signature so we can pick the right key.
    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        header = {}
    kid = header.get("kid")

    if kid == _KID_PREVIOUS and settings.jwt_secret_previous:
        return _decode_with(token, settings.jwt_secret_previous)

    payload = _decode_with(token, settings.jwt_secret)
    if payload is not None:
        return payload
    if settings.jwt_secret_previous:
        return _decode_with(token, settings.jwt_secret_previous)
    return None
