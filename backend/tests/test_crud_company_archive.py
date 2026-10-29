"""Archive retains tax records, checks role/firm and can be undone without changing identity."""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.accounting import AAAuditEvent, AACompany
from app.models.user import User, UserRole
from app.routers import accounting


class Db:
    def __init__(self, company):
        self.company = company
        self.statements, self.added = [], []
        self.commit = AsyncMock()

    async def execute(self, stmt):
        self.statements.append(str(stmt))
        return SimpleNamespace(scalar_one_or_none=lambda: self.company, first=lambda: None)

    def add(self, row):
        self.added.append(row)


def fixture():
    user = User(id=uuid.uuid4(), email="e2e@example.test", role=UserRole.ENTERPRISE)
    row = AACompany(id=uuid.uuid4(), enterprise_id=user.id, registered_name="E2E Archive", archived_at=None)
    return user, row, Db(row)


def test_archive_and_restore_keep_company_identity_and_audit():
    user, row, db = fixture()
    asyncio.run(accounting.archive_company(row.id, user=user, db=db))
    assert row.archived_at is not None
    assert db.commit.await_count == 1
    events = [e for e in db.added if isinstance(e, AAAuditEvent)]
    assert [(e.entity, e.action, e.enterprise_id) for e in events] == [("company", "archive", user.id)]
    assert all('enterprise_id' in s for s in db.statements if 'FROM aa_' in s)
    asyncio.run(accounting.restore_company(row.id, user=user, db=db))
    assert row.archived_at is None and row.registered_name == "E2E Archive"
    assert [e.action for e in db.added] == ["archive", "restore"]


def test_employee_cannot_archive():
    user, row, db = fixture()
    user.role, user.enterprise_id = UserRole.EMPLOYEE, row.enterprise_id
    with pytest.raises(HTTPException) as exc:
        asyncio.run(accounting.archive_company(row.id, user=user, db=db))
    assert exc.value.status_code == 403 and row.archived_at is None
    db.commit.assert_not_awaited()


def test_foreign_or_missing_company_is_404():
    user, row, db = fixture()
    db.company = None
    with pytest.raises(HTTPException) as exc:
        asyncio.run(accounting.archive_company(row.id, user=user, db=db))
    assert exc.value.status_code == 404
    db.commit.assert_not_awaited()


def test_archive_refuses_a_company_with_an_unfinished_drop():
    user, row, db = fixture()
    original = db.execute
    async def execute(stmt):
        if 'aa_uploads' in str(stmt):
            return SimpleNamespace(first=lambda: (uuid.uuid4(),))
        return await original(stmt)
    db.execute = execute
    with pytest.raises(HTTPException) as exc:
        asyncio.run(accounting.archive_company(row.id, user=user, db=db))
    assert exc.value.status_code == 409 and row.archived_at is None
    db.commit.assert_not_awaited()
