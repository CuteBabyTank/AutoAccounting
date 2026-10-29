"""Router isolation: a failed deletion guard must leave the row and transaction unmodified."""
import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.user import User, UserRole
from app.routers import accounting, accounting_books, accounting_annual, accounting_employees


@pytest.mark.parametrize('kind', ['document', 'entry', 'asset', 'employee'])
def test_refusal_precedes_delete_and_commit(monkeypatch, kind):
    user = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email='e2e@example.test')
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=user.id)
    row = SimpleNamespace(id=uuid.uuid4(), company_id=company.id, deleted_at=None, document_id=None,
                          writeoff_items=[], entry_date=date(2026, 1, 1), in_service=date(2026, 1, 1), year=2026)
    db = SimpleNamespace(commit=AsyncMock(), execute=AsyncMock(return_value=SimpleNamespace(
        scalar_one_or_none=lambda: row)))
    reject = AsyncMock(side_effect=HTTPException(409, 'Filed history'))
    if kind == 'document':
        monkeypatch.setattr(accounting, '_document_or_404', AsyncMock(return_value=row))
        monkeypatch.setattr(accounting, '_company_or_404', AsyncMock(return_value=company))
        monkeypatch.setattr(accounting.deletion, 'protect_document', reject)
        call = accounting.delete_document
    elif kind == 'entry':
        monkeypatch.setattr(accounting_books, '_entry_or_404', AsyncMock(return_value=row))
        monkeypatch.setattr(accounting_books, 'company_or_404', AsyncMock(return_value=company))
        monkeypatch.setattr(accounting_books.deletion, 'protect_entry', reject)
        call = accounting_books.delete_journal_entry
    elif kind == 'asset':
        monkeypatch.setattr(accounting_annual, 'company_or_404', AsyncMock(return_value=company))
        monkeypatch.setattr(accounting_annual.deletion, 'protect_history', reject)
        call = accounting_annual.delete_opening_asset
    else:
        monkeypatch.setattr(accounting_employees, '_employee_or_404', AsyncMock(return_value=row))
        monkeypatch.setattr(accounting_employees, 'company_or_404', AsyncMock(return_value=company))
        monkeypatch.setattr(accounting_employees, '_protect_payroll', reject)
        call = accounting_employees.delete_employee
    with pytest.raises(HTTPException) as exc:
        asyncio.run(call(row.id, user=user, db=db))
    assert exc.value.status_code == 409 and row.deleted_at is None
    db.commit.assert_not_awaited()
