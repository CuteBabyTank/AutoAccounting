"""Rematching must invalidate reconciliations in the same transaction as changed inputs."""
import asyncio
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.accounting import AABankLine, AABankReconciliation
from app.models.user import User
from app.services.accounting.bank_match import Candidate, Match
from app.services.accounting.books import bank, loader


class Result:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    def scalars(self) -> "Result":
        return self

    def all(self) -> list:
        return self.rows


class BankDb:
    def __init__(self, lines: list) -> None:
        self.lines = lines
        self.reads: list = []
        self.recs = [SimpleNamespace(account_code=code, month_end=end, voided_at=None)
                     for code in ("1020", "1021")
                     for end in (date(2025, 12, 31), date(2026, 1, 31), date(2026, 2, 28))]
        self.flush = AsyncMock()

    async def execute(self, stmt) -> Result:
        entity = stmt.column_descriptions[0]["entity"]
        self.reads.append(entity)
        if entity is User:
            return Result([])
        if entity is AABankLine:
            return Result(self.lines)
        assert entity is AABankReconciliation
        values = list(stmt.compile().params.values())
        on = next(v for v in values if isinstance(v, date))
        return Result([r for r in self.recs if r.account_code in values and r.month_end >= on
                       and r.voided_at is None])


def line(**changes) -> SimpleNamespace:
    return SimpleNamespace(**(dict(id=uuid.uuid4(), account_code="1020", line_date=date(2026, 1, 31),
                                  amount=Decimal("100"), narration="Acme payment", check_no="", rejected=[],
                                  match_status="matched", match_kind="document", matched_ref="invoice-a",
                                  match_amount=Decimal("100"), posting={}, candidates=[], review_reason="") | changes))


def setup(monkeypatch, lines: list) -> tuple:
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=uuid.uuid4(), books_updated_at=None)
    db = BankDb(lines)
    monkeypatch.setattr(bank, "_documents", AsyncMock(return_value=[]))
    monkeypatch.setattr(bank, "_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(loader, "ensure_chart", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(bank, "bank_accounts", AsyncMock(return_value=[]))
    monkeypatch.setattr(bank, "company_rules", AsyncMock(return_value=[]))
    monkeypatch.setattr(bank, "_flushed_paid_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(bank, "refresh_opening_flag", AsyncMock())
    return company, db


def test_competing_invoice_voids_saved_reconciliation(monkeypatch) -> None:
    row = line()
    company, db = setup(monkeypatch, [row])
    candidates = [Candidate("document", ref, on, Decimal("100"), "in", "Acme Widgets")
                  for ref, on in [("invoice-a", date(2026, 1, 30)), ("invoice-b", date(2026, 2, 2))]]
    monkeypatch.setattr(bank, "_candidates", AsyncMock(return_value=candidates))
    assert asyncio.run(bank.rematch(db, company)) == 0
    assert db.reads[:2] == [User, AABankLine]
    assert row.match_status == "ambiguous" and row.matched_ref == ""
    assert all(r.voided_at is not None for r in db.recs
               if r.account_code == "1020" and r.month_end >= row.line_date)
    assert all(r.voided_at is None for r in db.recs
               if r.account_code == "1021" or r.month_end < row.line_date)
    assert company.books_updated_at is not None


@pytest.mark.parametrize("change", ["reference", "amount", "kind", "posting-account"])
def test_posting_input_changes_void_reconciliation_even_when_still_matched(monkeypatch, change: str) -> None:
    row = line()
    if change == "posting-account":
        row.match_kind, row.matched_ref, row.posting = "posting", "", {"account": "6000"}
    company, db = setup(monkeypatch, [row])
    result = Match("matched", row.match_kind, row.matched_ref, row.match_amount, posting=dict(row.posting))
    if change == "reference":
        result = Match("matched", "document", "invoice-b", Decimal("100"))
    elif change == "amount":
        result = Match("matched", "document", "invoice-a", Decimal("50"))
    elif change == "kind":
        result = Match("matched", "journal", "invoice-a", Decimal("100"))
    else:
        result = Match("matched", "posting", "", Decimal("100"), posting={"account": "6100"})
    monkeypatch.setattr(bank, "match_all", lambda *a: {str(row.id): result})
    assert asyncio.run(bank.rematch(db, company)) == 1
    assert all(r.voided_at is not None for r in db.recs
               if r.account_code == "1020" and r.month_end >= row.line_date)
    assert company.books_updated_at is not None


def test_changed_lines_invalidate_each_account_from_earliest_changed_date(monkeypatch) -> None:
    rows = [line(line_date=date(2026, 2, 10)), line(line_date=date(2026, 1, 10)),
            line(account_code="1021", line_date=date(2026, 2, 10)), line(match_status="confirmed"),
            line(match_status="excluded")]
    company, db = setup(monkeypatch, rows)
    assert asyncio.run(bank.rematch(db, company)) == 0
    assert all(r.voided_at is not None for r in db.recs if
               (r.account_code == "1020" and r.month_end >= date(2026, 1, 10)) or
               (r.account_code == "1021" and r.month_end >= date(2026, 2, 10)))
    assert rows[-2].match_status == "confirmed" and rows[-1].match_status == "excluded"
    assert company.books_updated_at is not None


def test_guarded_subset_leaves_other_accounts_reconciled(monkeypatch) -> None:
    chosen, unchanged = line(), line(account_code="1021")
    company, db = setup(monkeypatch, [chosen, unchanged])
    asyncio.run(bank.rematch(db, company, line_ids={chosen.id}))
    assert any(r.voided_at is not None for r in db.recs if r.account_code == "1020")
    assert all(r.voided_at is None for r in db.recs if r.account_code == "1021")
    assert unchanged.match_status == "matched"


def test_noop_rematch_keeps_reconciliation_and_books_timestamp(monkeypatch) -> None:
    row = line()
    company, db = setup(monkeypatch, [row])
    monkeypatch.setattr(bank, "match_all", lambda *a: {
        str(row.id): Match("matched", "document", "invoice-a", Decimal("100"))})
    # First prove a real change invalidates; then a repeated identical match is a no-op.
    row.matched_ref = "old-invoice"
    asyncio.run(bank.rematch(db, company))
    assert company.books_updated_at is not None
    assert any(r.voided_at is not None for r in db.recs)
    stamp = company.books_updated_at
    for rec in db.recs:
        rec.voided_at = None
    asyncio.run(bank.rematch(db, company))
    assert company.books_updated_at == stamp
    assert all(r.voided_at is None for r in db.recs)
