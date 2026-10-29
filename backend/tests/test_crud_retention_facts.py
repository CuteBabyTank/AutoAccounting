"""Exercise actual deletion fact loaders with isolated DB results (no database needed)."""
import asyncio
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.accounting import (
    AAAsset, AABankLine, AABankReconciliation, AABookClose, AADocument, AAJournalEntry, AAPeriod, AAWorkItem,
)
from app.services.accounting import deletion
from app.routers.accounting_bank import _rule_change_lines


class Result:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows
    def scalars(self): return self


class FactsDb:
    def __init__(self):
        self.docs, self.lines, self.assets, self.closes, self.filed, self.board, self.recs = [], [], [], [], [], [], []
        self.writeoffs, self.marks, self.statements = [], [], []

    async def execute(self, stmt):
        self.statements.append(stmt)
        entity = stmt.column_descriptions[0]['entity']
        expr = stmt.column_descriptions[0]['expr']
        if entity is AADocument:
            rows = self.marks if str(expr).endswith('.cwt_2307') else self.docs
        else:
            rows = {AAAsset: self.assets, AABankLine: self.lines, AABankReconciliation: self.recs,
                    AABookClose: self.closes, AAPeriod: self.filed, AAWorkItem: self.board,
                    AAJournalEntry: self.writeoffs}.get(entity, [])
        return Result(rows)


def fixtures():
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=uuid.uuid4(), fiscal_year_end_month=12)
    doc = SimpleNamespace(id=uuid.uuid4(), doc_date=date(2026, 1, 10), paid_on=None, period_year=2026,
                          period_quarter=1, settles_document_id=None, cwt_2307={}, deleted_at=None)
    db = FactsDb()
    db.docs = [doc]
    return company, doc, db


def line(**kw):
    values = dict(id=uuid.uuid4(), line_date=date(2026, 1, 10), account_code='1020', match_status='matched',
                  amount=Decimal('-100'), narration='E2E RENT')
    return SimpleNamespace(**(values | kw))


@pytest.mark.parametrize('dependency', ['bank', 'writeoff', 'certificate', 'asset', 'receipt', 'board', 'ytd'])
def test_actual_document_guard_refuses_retained_dependencies(dependency):
    company, doc, db = fixtures()
    if dependency == 'bank': db.lines = [line(match_status='confirmed')]
    if dependency == 'writeoff': db.writeoffs = [[{'id': str(doc.id), 'amount': '100'}]]
    if dependency == 'certificate': db.marks = [{'status': 'received', 'document_id': str(doc.id)}]
    if dependency == 'asset':
        db.assets = [date(2026, 1, 1)]
        db.closes = [(date(2026, 8, 1), date(2026, 8, 31))]
    if dependency == 'receipt':
        db.docs.append(SimpleNamespace(id=uuid.uuid4(), doc_date=date(2026, 4, 2), paid_on=date(2026, 4, 2),
                                       period_year=2026, period_quarter=2))
        db.closes = [(date(2026, 4, 1), date(2026, 4, 30))]
    if dependency == 'board': db.board = [(2026, 1)]
    if dependency == 'ytd': db.filed = [(2026, 2)]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(deletion.protect_document(db, company, doc))
    assert exc.value.status_code == 409 and doc.deleted_at is None


def test_a_later_reconciliation_protects_earlier_payment_source():
    company, _, db = fixtures()
    db.recs = [SimpleNamespace(account_code='1020', month_start=date(2026, 3, 1), month_end=date(2026, 3, 31))]
    with pytest.raises(HTTPException):
        asyncio.run(deletion.protect_bank_links(db, company, [line()]))


def test_noop_bank_rule_change_does_not_touch_reconciliations():
    company, _, db = fixtures()
    rule = {'pattern': 'e2e rent', 'direction': 'out'}
    assert asyncio.run(_rule_change_lines(db, company, rule, dict(rule))) == []
    assert db.statements == []


def test_future_unrelated_rule_does_not_touch_historical_reconciliations():
    company, _, db = fixtures()
    db.lines = [line()]
    db.recs = [SimpleNamespace(account_code='1020', month_end=date(2026, 1, 31))]
    assert asyncio.run(_rule_change_lines(db, company, None, {'pattern': 'new vendor', 'direction': 'out'})) == []


def test_bank_rule_change_cannot_rematch_finalized_lines():
    company, _, db = fixtures()
    db.lines = [line()]
    db.filed = [(2026, 2)]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_rule_change_lines(db, company, None, {'pattern': 'e2e rent', 'direction': 'out'}))
    assert exc.value.status_code == 409
