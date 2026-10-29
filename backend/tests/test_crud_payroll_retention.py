import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.models.accounting import AAEmployee
from app.models.user import User, UserRole
from app.routers import accounting_employees as r


def test_replacement_import_tombstones_previous_rows_instead_of_purging(monkeypatch):
    user = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email='e2e@example.test')
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=user.id, payroll_mapping={})
    monkeypatch.setattr(r, 'company_or_404', AsyncMock(return_value=company))
    monkeypatch.setattr(r, '_read_sheet', AsyncMock(return_value=(['Last'], [['E2E Doe']])))
    monkeypatch.setattr(r, 'apply_mapping', lambda *args: ([{'last_name': 'E2E Doe'}], []))
    monkeypatch.setattr(r, '_protect_payroll', AsyncMock())
    monkeypatch.setattr(r, '_out', AsyncMock(return_value=r.EmployeesOut(
        year=2026, employees=[], warnings=[], checks=[], remittances=[], fields={}, due=date(2027, 1, 31))))
    statements, added = [], []
    async def execute(stmt):
        statements.append(stmt)
        return SimpleNamespace(scalar_one=lambda: 1)
    db = SimpleNamespace(execute=execute, commit=AsyncMock(), add=added.append)
    asyncio.run(r.import_employees(company.id, 2026, SimpleNamespace(filename='E2E.csv'),
        mapping='{"Last":"last_name"}', user=user, db=db))
    assert not any(getattr(s, 'is_delete', False) for s in statements)
    updates = [s for s in statements if getattr(s, 'is_update', False)]
    assert len(updates) == 1
    sql = str(updates[0])
    assert 'deleted_at=' in sql and 'enterprise_id' in sql and 'deleted_at IS NULL' in sql
    assert len([row for row in added if isinstance(row, AAEmployee)]) == 1
    r._protect_payroll.assert_awaited_once_with(db, company, 2026)
