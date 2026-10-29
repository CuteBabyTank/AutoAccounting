import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.accounting import AAAuditEvent
from app.models.user import User, UserRole
from app.routers import accounting_templates as t


def test_whitespace_template_names_are_invalid():
    with pytest.raises(ValidationError):
        t.TemplateIn(name='  ')
    assert t.TemplateIn(name=' E2E Chart ').name == 'E2E Chart'


def test_template_metadata_update_retains_snapshot_and_is_audited(monkeypatch):
    user = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email='e2e@example.test')
    row = SimpleNamespace(id=uuid.uuid4(), enterprise_id=user.id, name='E2E Chart', description='', accounts=[{'code': '1000'}])
    monkeypatch.setattr(t, '_firm_template', AsyncMock(return_value=row))
    added = []
    db = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock(), add=added.append)
    out = asyncio.run(t.update_template(str(row.id), t.TemplateUpdateIn(name='E2E Renamed', description='updated'), user=user, db=db))
    assert out['name'] == 'E2E Renamed' and row.accounts == [{'code': '1000'}]
    assert len(added) == 1 and isinstance(added[0], AAAuditEvent)
    assert added[0].enterprise_id == user.id and added[0].action == 'update'


def test_builtin_template_cannot_be_edited():
    user = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(t.update_template(next(iter(t.BUILTIN_TEMPLATES)), t.TemplateUpdateIn(name='E2E'), user=user, db=SimpleNamespace()))
    assert exc.value.status_code == 400
