"""Mutation regressions: lock before reading facts and retain dependent opening items."""

import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.models.accounting import AABankReconciliation
from app.models.user import User, UserRole
from app.routers import accounting_imports as imports, accounting_writeoff as writeoffs
from app.services.accounting import deletion


def test_writeoff_locks_firm_before_loading_company(monkeypatch):
    user = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email="owner@example.test")
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=user.id, books_start=None)
    statements = []

    async def execute(stmt):
        statements.append(str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})))

    async def load_company(*args):
        assert statements and "FROM users" in statements[0] and "FOR UPDATE" in statements[0]
        assert str(user.id) in statements[0]
        return company

    monkeypatch.setattr(writeoffs, "company_or_404", load_company)
    body = writeoffs.WriteOffIn(entry_date=date(2026, 1, 1), item_ids=["invoice"], account="6140", reason="Bad debt")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(writeoffs.write_off(company.id, body, user, SimpleNamespace(execute=execute)))
    assert exc.value.status_code == 400


@pytest.mark.parametrize("operation", ["confirm", "undo"])
def test_import_locks_firm_before_loading_company(monkeypatch, operation):
    user = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email="owner@example.test")
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=user.id)
    statements = []

    async def execute(stmt):
        statements.append(str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})))

    async def load_company(*args):
        assert statements and "FROM users" in statements[0] and "FOR UPDATE" in statements[0]
        assert str(user.id) in statements[0]
        raise HTTPException(404, "Company not found")

    monkeypatch.setattr(imports, "company_or_404", load_company)
    monkeypatch.setattr(imports, "_batch_or_404", AsyncMock(return_value=SimpleNamespace(company_id=company.id)))
    db = SimpleNamespace(execute=execute)
    call = (imports.confirm_import(company.id, "open-items", SimpleNamespace(), "", user, db)
            if operation == "confirm" else imports.undo_import(uuid.uuid4(), user, db))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(call)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("cause", ["history", "bank", "writeoff"])
def test_opening_item_guard_rejects_dependencies(monkeypatch, cause):
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=uuid.uuid4())
    item = SimpleNamespace(id=uuid.uuid4(), paid_on=date(2026, 2, 1), paid_account="", paid_via="cash")
    line = SimpleNamespace(id=uuid.uuid4(), line_date=date(2026, 3, 1), match_status="matched",
                           match_kind="document", matched_ref=str(item.id), account_code="1020")
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [line]), first=lambda: None)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    history = AsyncMock(side_effect=HTTPException(409, "Closed history") if cause == "history" else None)
    bank = AsyncMock(side_effect=HTTPException(409, "Reconciled payment") if cause == "bank" else None)
    monkeypatch.setattr(deletion, "protect_history", history)
    monkeypatch.setattr(deletion, "protect_bank_links", bank)
    from app.services.accounting.books import subledger
    off = [("je", date(2026, 4, 1), [{"id": str(item.id), "amount": "100"}])] if cause == "writeoff" else []
    monkeypatch.setattr(subledger, "writeoff_rows", AsyncMock(return_value=off))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(deletion.protect_opening_item(db, company, item))
    assert exc.value.status_code == 409
    assert history.await_args.args[2] == [item.paid_on, line.line_date]


@pytest.mark.parametrize("paid_account,via", [("1020", "bank"), ("", "bank")])
@pytest.mark.parametrize("alternate_candidate", [False, True])
def test_opening_item_manual_payment_cannot_change_reconciled_balance(paid_account, via, alternate_candidate):
    from app.models.accounting import AABankLine

    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=uuid.uuid4(), fiscal_year_end_month=12)
    item = SimpleNamespace(id=uuid.uuid4(), paid_on=date(2026, 2, 1), paid_account=paid_account, paid_via=via)
    line = SimpleNamespace(id=uuid.uuid4(), line_date=date(2026, 2, 1), match_status="matched",
                           match_kind="document", matched_ref=str(uuid.uuid4()), account_code="1030")
    rec = SimpleNamespace(id=uuid.uuid4(), account_code="1020", month_end=date(2026, 3, 31))
    statements = []

    class Result:
        def __init__(self, rows): self.rows = rows
        def all(self): return self.rows
        def scalars(self): return self
        def first(self): return self.rows[0] if self.rows else None

    async def execute(stmt):
        statements.append(stmt)
        entity = stmt.column_descriptions[0]["entity"]
        return Result([rec] if entity is AABankReconciliation else
                      [line] if entity is AABankLine and alternate_candidate else [])

    with pytest.raises(HTTPException) as exc:
        asyncio.run(deletion.protect_opening_item(SimpleNamespace(execute=execute), company, item))
    assert exc.value.status_code == 409
    stmt = next(s for s in statements if "FROM aa_bank_reconciliations" in str(s) and "FROM aa_accounts" in str(s))
    query = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "2026-02-01" in query and "voided_at IS NULL" in query
    assert str(company.enterprise_id) in query and str(company.id) in query
    assert ("aa_accounts.code = '1020'" if paid_account else "aa_accounts.system_key = 'bank'") in query


def test_opening_item_refusal_does_not_delete_or_commit(monkeypatch):
    user = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email="owner@example.test")
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=user.id)
    item = SimpleNamespace(id=uuid.uuid4(), company_id=company.id, deleted_at=None)
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    monkeypatch.setattr(imports, "_item_or_404", AsyncMock(return_value=item))
    monkeypatch.setattr(imports, "company_or_404", AsyncMock(return_value=company))
    monkeypatch.setattr(deletion, "protect_opening_item", AsyncMock(side_effect=HTTPException(409, "Written off")))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(imports.delete_opening_item(item.id, user, db))
    assert exc.value.status_code == 409 and item.deleted_at is None
    db.commit.assert_not_awaited()


def test_unpaid_opening_item_without_dependencies_can_be_deleted():
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=uuid.uuid4(), fiscal_year_end_month=12)
    item = SimpleNamespace(id=uuid.uuid4(), paid_on=None)
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []), all=lambda: [])
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    assert asyncio.run(deletion.protect_opening_item(db, company, item)) == []
