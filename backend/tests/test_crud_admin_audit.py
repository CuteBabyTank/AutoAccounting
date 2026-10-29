import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.user import User, UserRole
from app.routers import admin as r
from app.schemas.auth import SetUserRoleRequest


def test_owner_role_cannot_be_removed_or_firm_data_would_be_orphaned(monkeypatch):
    actor = User(id=uuid.uuid4(), role=UserRole.ADMIN)
    firm = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, enterprise_id=None, is_active=True, email='e2e@example.test')
    monkeypatch.setattr(r, '_user_or_404', AsyncMock(return_value=firm))
    db = SimpleNamespace(commit=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.set_user_role(firm.id, SetUserRoleRequest(role='unverified'), db=db, admin=actor))
    assert exc.value.status_code == 409 and firm.role == UserRole.ENTERPRISE
    db.commit.assert_not_awaited()
