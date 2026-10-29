import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.accounting import AAFirmSettings
from app.models.user import User, UserRole
from app.routers import accounting_work as r
from app.schemas.accounting_work import FirmSettingsIn


def test_owner_can_rename_firm_and_change_is_audited(monkeypatch):
    owner = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email='e2e@example.test', organization_name='E2E Old')
    row = AAFirmSettings(enterprise_id=owner.id, approve_before_close=False, deadline_days=7, auto_assign=True)
    monkeypatch.setattr(r, 'lock_firm', AsyncMock())
    responses = [None, row, owner]
    async def execute(stmt):
        result = responses.pop(0)
        return SimpleNamespace(scalar_one=lambda: result)
    events = []
    db = SimpleNamespace(execute=execute, commit=AsyncMock(), add=events.append)
    out = asyncio.run(r.put_firm_settings(FirmSettingsIn(organization_name=' E2E New '), user=owner, db=db))
    assert owner.organization_name == out.organization_name == 'E2E New'
    assert events[0].before == {'organization_name': 'E2E Old'}
    assert events[0].after == {'organization_name': 'E2E New'}
    assert events[0].enterprise_id == owner.id


def test_manager_cannot_rename_firm():
    user = User(id=uuid.uuid4(), role=UserRole.MANAGER, enterprise_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.put_firm_settings(FirmSettingsIn(organization_name='E2E Forbidden'), user=user, db=None))
    assert exc.value.status_code == 403
