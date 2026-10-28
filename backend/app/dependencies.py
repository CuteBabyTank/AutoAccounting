"""
FastAPI dependency injectors.
"""

import uuid
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.auth.jwt import verify_token
from app.models.user import User, UserRole
from app.auth.security import global_user_limiter

security = HTTPBearer()

# Key under which the bound user id lives on ``Session.info``. The
# ``after_begin`` event handler re-applies the GUC at the start of every
# transaction so a request that commits-and-keeps-querying still has RLS
# context (``SET LOCAL`` is transaction-scoped and would otherwise vanish
# after the first commit).
_SESSION_USER_KEY = "rls_user_id"


@event.listens_for(AsyncSession.sync_session_class, "after_begin")
def _reapply_rls_guc(session, transaction, connection):
    user_id = session.info.get(_SESSION_USER_KEY)
    if user_id is None:
        # No bound user → policies see NULL → access denied. This is the
        # intended behaviour for anonymous / startup contexts.
        return
    # Re-validate as UUID before interpolating; ``set_config`` requires a
    # string literal (parameter binds aren't honoured at this hook depth on
    # all drivers), so validation is the safety net against any hypothetical
    # injection vector that mutates ``Session.info``.
    try:
        uuid.UUID(str(user_id))
    except ValueError:
        return
    connection.exec_driver_sql(
        f"SELECT set_config('app.current_user_id', '{user_id}', true)"
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def bind_session_user(db: AsyncSession, user_id: str) -> None:
    """Bind the request's user id to the SQLAlchemy session so RLS sees it.

    Stored in ``Session.info`` and re-applied via ``SET LOCAL`` on every
    transaction begin (see ``_reapply_rls_guc``). ``is_local=true`` keeps
    the GUC scoped to the current transaction, so it cannot leak across
    pooled connections. Anonymous sessions (no bind) leave the GUC unset,
    ``current_setting('app.current_user_id', true)`` returns NULL and every
    RLS USING/WITH CHECK clause evaluates false, denying all access.
    """
    db.sync_session.info[_SESSION_USER_KEY] = str(user_id)
    # Apply immediately for the in-flight transaction.
    await db.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(user_id)},
    )


async def _get_active_user(db: AsyncSession, payload: dict) -> User:
    """Load the token's user; 401 if missing, 403 if deactivated."""
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user = await _get_active_user(db, payload)

    # Per-user global rate limit (prevents scraping / excessive polling)
    if not global_user_limiter.check_and_record(str(user.id)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": "60"},
        )

    # Bind identity to the DB session so RLS policies on the aa_* tables
    # can filter to the current user's firm. Done after the user lookup
    # because we need ``user.id`` first; the users table itself is not under
    # RLS, so the lookup above is unaffected.
    await bind_session_user(db, str(user.id))

    return user


def require_role(*roles: UserRole):
    """Dependency factory: restrict to specific roles."""
    async def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(r.value for r in roles)}",
            )
        return user
    return _guard


# Convenience dependencies
require_admin = require_role(UserRole.ADMIN)
# Enterprise panel access: org owner + managers + platform admin
require_enterprise = require_role(UserRole.ADMIN, UserRole.ENTERPRISE, UserRole.MANAGER)
# Strict "org owner" gate for actions managers must not perform (promote-to-manager, etc).
require_enterprise_owner = require_role(UserRole.ADMIN, UserRole.ENTERPRISE)
require_employee = require_role(UserRole.ADMIN, UserRole.ENTERPRISE, UserRole.MANAGER, UserRole.EMPLOYEE)


class EnterpriseContext:
    """Resolved enterprise scope for a request.

    `caller` is the authenticated user; `enterprise` is the org owner (the
    User row with role=ENTERPRISE). For an ENTERPRISE caller they are the
    same row; for a MANAGER caller `enterprise` is the parent. For an ADMIN
    caller without an enterprise_id they coincide (admin acts as its own
    enterprise for the rare cases this dep is hit).
    """
    __slots__ = ("caller", "enterprise")

    def __init__(self, caller: User, enterprise: User):
        self.caller = caller
        self.enterprise = enterprise


async def get_enterprise_context(
    user: User = Depends(require_enterprise),
    db: AsyncSession = Depends(get_db),
) -> EnterpriseContext:
    if user.role == UserRole.MANAGER:
        if not user.enterprise_id:
            raise HTTPException(status_code=403, detail="Manager has no enterprise assigned")
        result = await db.execute(select(User).where(User.id == user.enterprise_id))
        parent = result.scalar_one_or_none()
        if not parent or parent.role != UserRole.ENTERPRISE:
            raise HTTPException(status_code=403, detail="Manager's enterprise not found")
        return EnterpriseContext(caller=user, enterprise=parent)
    return EnterpriseContext(caller=user, enterprise=user)
