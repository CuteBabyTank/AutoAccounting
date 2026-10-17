"""Regression tests from the QBO 03 bank code review."""

import asyncio
import uuid
from datetime import date
from decimal import Decimal

from app.services.accounting.books import bank

D = Decimal


class _Result:
    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one_or_none(self):
        return None

    def scalar(self):
        return 0


class _CaptureDb:
    """An AsyncSession stand-in that records the SQL it is asked to run and returns nothing."""

    def __init__(self):
        self.sql: list[str] = []

    async def execute(self, stmt):
        self.sql.append(str(stmt.compile(compile_kwargs={"literal_binds": False})))
        return _Result()

    async def flush(self):
        return None


def _run(coro):
    return asyncio.run(coro)


def _only_live_statements(sql: str) -> bool:
    return "aa_documents.deleted_at IS NULL" in sql and "aa_documents.excluded" in sql


def test_lines_of_a_deleted_or_excluded_statement_document_do_not_post_or_block_the_close():
    company_id = uuid.uuid4()
    for call in (bank.matched_lines(_db := _CaptureDb(), company_id, date(2026, 12, 31)),
                 bank.unreconciled_accounts(_db2 := _CaptureDb(), company_id, date(2026, 12, 1), date(2026, 12, 31))):
        _run(call)
    assert _only_live_statements(_db.sql[0])
    assert _only_live_statements(_db2.sql[0])


def test_statements_of_a_deleted_document_are_not_the_first_statement():
    db = _CaptureDb()
    _run(bank._statements(db, uuid.uuid4(), "1020"))
    assert _only_live_statements(db.sql[0])
