import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.accounting import AAAccount, AABankLine, AABankRule, AABankStatement, AAOpeningItem, AARecurringEntry
from app.models.user import User, UserRole
from app.routers import accounting_books as r
from app.schemas.accounting_books import AccountPatch


@pytest.mark.parametrize('dependent', [AAAccount, AARecurringEntry, AABankStatement, AABankRule, AABankLine, AAOpeningItem, None])
def test_deactivation_refuses_live_dependencies_but_allows_unused_account(monkeypatch, dependent):
    user = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email='e2e@example.test')
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=user.id)
    account = AAAccount(id=uuid.uuid4(), enterprise_id=user.id, company_id=company.id, code='1999', name='E2E Account',
                        type='asset', parent_code='1000', active=True, locked=False, bank_account_no='', system_key=None)
    monkeypatch.setattr(r, '_account_or_404', AsyncMock(return_value=account))
    monkeypatch.setattr(r, 'company_or_404', AsyncMock(return_value=company))
    monkeypatch.setattr(r, 'ensure_chart', AsyncMock(return_value=None))
    monkeypatch.setattr(r, '_account_out', lambda row, chart: row)
    statements, events = [], []
    async def execute(stmt):
        statements.append(stmt)
        entity = stmt.column_descriptions[0]['entity']
        return SimpleNamespace(first=lambda: (uuid.uuid4(),) if entity is dependent else None)
    db = SimpleNamespace(execute=execute, add=events.append, commit=AsyncMock())
    if dependent:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(r.patch_account(account.id, AccountPatch(active=False), user=user, db=db))
        assert exc.value.status_code == 409 and account.active
        db.commit.assert_not_awaited()
    else:
        asyncio.run(r.patch_account(account.id, AccountPatch(active=False), user=user, db=db))
        assert not account.active and events[0].entity == 'account'
        db.commit.assert_awaited_once()
