"""Isolated mutation handlers must retain their original accounting-history facts."""
import asyncio
import uuid
from contextlib import nullcontext
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.models.accounting import (
    AABankLine, AABookClose, AADocument, AAJournalEntry, AAPeriod, AAWorkItem,
)
from app.models.user import User, UserRole
from app.routers import accounting, accounting_books, accounting_imports
from app.schemas.accounting import DocumentPatch
from app.schemas.accounting_books import JournalEntryIn
from app.services.accounting import audit
from app.services.accounting.import_undo import entry_state, fingerprint


class Result:
    def __init__(self, rows: list):
        self.rows = rows

    def all(self) -> list:
        return self.rows

    def scalars(self) -> "Result":
        return self


class FactsDb:
    """Only persistence is replaced; actual shared history and bank guards run."""
    def __init__(self) -> None:
        self.filed: list = []
        self.board: list = []
        self.closes: list = []
        self.lines: list = []
        self.entries: list = []
        self.commit = AsyncMock()
        self.flush = AsyncMock()
        self.add = Mock()

    async def execute(self, stmt) -> Result:
        entity = stmt.column_descriptions[0]["entity"]
        return Result({AAPeriod: self.filed, AAWorkItem: self.board, AABookClose: self.closes,
                       AABankLine: self.lines, AAJournalEntry: self.entries}.get(entity, []))


def fixtures() -> tuple:
    user = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email="sec3@example.test")
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=user.id, fiscal_year_end_month=12,
                              books_start=date(2026, 1, 1), books_updated_at=None, review_flags={})
    return user, company, FactsDb()


def entry(company, **changes) -> AAJournalEntry:
    values = dict(id=uuid.uuid4(), enterprise_id=company.enterprise_id, company_id=company.id, kind="manual",
                  book="GJ", entry_date=date(2026, 2, 10), reference="JV-1", particulars="Fixture",
                  is_adjusting=False, writeoff_items=[], deleted_at=None, import_batch_id=None,
                  lines=[{"account_code": "1010", "debit": "100", "credit": "0", "party_name": "", "party_tin": ""},
                         {"account_code": "3000", "debit": "0", "credit": "100", "party_name": "", "party_tin": ""}])
    return AAJournalEntry(**(values | changes))


@pytest.mark.parametrize("casper", [False, True])
@pytest.mark.parametrize("history", ["filed", "board", "closed", "stored-period"])
def test_document_cannot_clear_stored_retained_dates(monkeypatch, casper: bool, history: str) -> None:
    user, company, db = fixtures()
    doc = AADocument(id=uuid.uuid4(), company_id=company.id, enterprise_id=user.id,
                     doc_date=date(2026, 2, 10), paid_on=None, period_year=2026, period_quarter=1,
                     period_locked=True, doc_number="INV-1", seller_name="Supplier", review_reasons=[])
    if history == "filed":
        db.filed = [(2026, 1)]
    elif history == "board":
        db.board = [(2026, 1)]
    elif history == "closed":
        db.closes = [(date(2026, 2, 1), date(2026, 2, 28))]
    else:
        doc.doc_date = None
        db.filed = [(2026, 1)]
    original = (doc.doc_date, doc.paid_on, doc.period_year, doc.period_quarter, doc.period_locked)
    monkeypatch.setattr(accounting, "_document_or_404", AsyncMock(return_value=doc))
    monkeypatch.setattr(accounting, "_company_or_404", AsyncMock(return_value=company))
    monkeypatch.setattr(accounting, "sync_receipt_flag", Mock())
    monkeypatch.setattr(accounting, "relink_receipts", AsyncMock())
    monkeypatch.setattr(accounting, "_bank_after_document_change", AsyncMock())
    monkeypatch.setattr(accounting.duplicates, "refresh_flags", AsyncMock())
    monkeypatch.setattr(accounting, "_document_out", AsyncMock(return_value=SimpleNamespace()))
    body = DocumentPatch(doc_date=None, period_year=None, period_quarter=None)
    with audit.casper_context("Fixture") if casper else nullcontext():
        with pytest.raises(HTTPException) as exc:
            asyncio.run(accounting.patch_document(doc.id, body, user=user, db=db))
    assert exc.value.status_code == 409
    assert (doc.doc_date, doc.paid_on, doc.period_year, doc.period_quarter, doc.period_locked) == original
    db.commit.assert_not_awaited()
    db.add.assert_not_called()
    db.filed, db.board, db.closes = [], [], []
    asyncio.run(accounting.patch_document(doc.id, body, user=user, db=db))
    assert (doc.doc_date, doc.period_year, doc.period_quarter) == (None, None, None)
    db.commit.assert_awaited_once()
    assert db.add.call_count == 1  # the allowed edit still records its audit event


@pytest.mark.parametrize("history", ["original", "opening-to-manual", "manual-to-opening", "proposed", "bank"])
def test_journal_edit_checks_original_and_proposed_effect(monkeypatch, history: str) -> None:
    user, company, db = fixtures()
    row = entry(company)
    kind, proposed = "manual", date(2026, 4, 2)
    if history == "original":
        db.filed = [(2026, 1)]
    elif history == "opening-to-manual":
        row.kind, row.entry_date = "opening", company.books_start
        db.closes = [(date(2026, 3, 1), date(2026, 3, 31))]
    elif history == "manual-to-opening":
        row.entry_date = date(2026, 4, 2)
        kind = "opening"
        db.closes = [(date(2026, 3, 1), date(2026, 3, 31))]
    elif history == "proposed":
        row.entry_date, proposed = date(2026, 4, 2), date(2026, 2, 10)
        db.board = [(2026, 1)]
    else:
        db.lines = [SimpleNamespace(match_status="confirmed", line_date=date(2026, 2, 11))]
    original = entry_state(row)
    monkeypatch.setattr(accounting_books, "_entry_or_404", AsyncMock(return_value=row))
    monkeypatch.setattr(accounting_books, "company_or_404", AsyncMock(return_value=company))
    monkeypatch.setattr(accounting_books, "_check_entry", AsyncMock())
    monkeypatch.setattr(accounting_books, "_entry_out", lambda r: r)
    body = JournalEntryIn(kind=kind, book="GJ", entry_date=proposed, lines=row.lines)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(accounting_books.update_journal_entry(row.id, body, user=user, db=db))
    assert exc.value.status_code == 409
    assert entry_state(row) == original
    assert company.books_updated_at is None
    db.commit.assert_not_awaited()
    db.add.assert_not_called()
    db.filed, db.board, db.closes, db.lines = [], [], [], []
    asyncio.run(accounting_books.update_journal_entry(row.id, body, user=user, db=db))
    assert row.entry_date == (company.books_start if kind == "opening" else proposed)
    assert row.kind == kind and company.books_updated_at is not None
    db.commit.assert_awaited_once()
    assert db.add.call_count == 1


@pytest.mark.parametrize("history", ["later-quarter", "cross-year", "board", "opening-close", "opening-filed",
                                     "restore-close", "second-entry", "opening-start-close"])
def test_import_undo_checks_shared_retention_before_any_mutation(monkeypatch, history: str) -> None:
    user, company, db = fixtures()
    batch_id = uuid.uuid4()
    opening = history in {"opening-close", "opening-filed", "restore-close", "opening-start-close"}
    row = entry(company, import_batch_id=batch_id, kind="opening" if opening else "manual",
                entry_date=company.books_start if opening else date(2026, 2, 10))
    if history == "opening-start-close":
        # books_start remains protected even when the saved opening row has a later date.
        row.entry_date = date(2026, 4, 1)
    prior = entry_state(entry(company, id=row.id, kind="opening", entry_date=company.books_start))
    batch = SimpleNamespace(id=batch_id, company_id=company.id, kind="opening-tb" if opening else "journal-entries",
                            restore={"opening": prior if history == "restore-close" else None},
                            written={str(row.id): fingerprint(entry_state(row))}, undone_at=None, undone_by=None,
                            filename="fixture.xlsx", created_by=user.id, row_count=1,
                            created_at=datetime.now(timezone.utc))
    if history in {"opening-close", "restore-close", "opening-start-close"}:
        db.closes = [(date(2026, 3, 1), date(2026, 3, 31))]
    elif history == "board":
        db.board = [(2026, 1)]
    elif history == "cross-year":
        row.entry_date = date(2025, 11, 10)
        batch.written = {str(row.id): fingerprint(entry_state(row))}
        db.filed = [(2026, 1)]
    else:
        db.filed = [(2026, 2)]
    db.entries = [row]
    if history == "second-entry":
        # The first entry is clear; refusal of the second must not tombstone the first.
        clear = entry(company, import_batch_id=batch_id, entry_date=date(2026, 10, 1))
        db.entries.insert(0, clear)
        batch.written[str(clear.id)] = fingerprint(entry_state(clear))
    originals = [entry_state(e) for e in db.entries]
    monkeypatch.setattr(accounting_imports, "_batch_or_404", AsyncMock(return_value=batch))
    monkeypatch.setattr(accounting_imports, "company_or_404", AsyncMock(return_value=company))
    monkeypatch.setattr(accounting_imports, "_lock_company", AsyncMock())
    # These facts have no hit under the old point-date checks; shared retention must still refuse.
    monkeypatch.setattr(accounting_imports, "_common_facts",
                        AsyncMock(return_value=(db.closes, set(db.filed), [], set())))
    monkeypatch.setattr(accounting_imports, "_lines_matched_to", AsyncMock(return_value=[]))
    monkeypatch.setattr(accounting_imports, "_opening_entry", AsyncMock(return_value=row))
    monkeypatch.setattr(accounting_imports.bank, "rematch", AsyncMock())
    monkeypatch.setattr(accounting_imports.bank, "refresh_opening_flag", AsyncMock())
    monkeypatch.setattr(accounting_imports, "_emails", AsyncMock(return_value={}))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(accounting_imports.undo_import(batch.id, user=user, db=db))
    assert exc.value.status_code == 409
    assert [entry_state(e) for e in db.entries] == originals
    assert all(e.deleted_at is None for e in db.entries)
    assert batch.undone_at is None and batch.undone_by is None
    assert company.books_updated_at is None
    db.commit.assert_not_awaited()
    db.add.assert_not_called()


def test_opening_import_cannot_replace_retained_opening(monkeypatch) -> None:
    user, company, db = fixtures()
    row = entry(company, kind="opening", entry_date=company.books_start)
    original = entry_state(row)
    db.closes = [(date(2026, 3, 1), date(2026, 3, 31))]
    built = SimpleNamespace(preview=SimpleNamespace(ready=True, filename="tb.xlsx", warnings=[]), chart=None,
                            result=SimpleNamespace(lines=[("1010", "200", "0"), ("3000", "0", "200")]))
    monkeypatch.setattr(accounting_imports, "company_or_404", AsyncMock(return_value=company))
    monkeypatch.setattr(accounting_imports, "_lock_company", AsyncMock())
    monkeypatch.setattr(accounting_imports, "_build", AsyncMock(return_value=built))
    monkeypatch.setattr(accounting_imports, "_opening_entry", AsyncMock(return_value=row))
    monkeypatch.setattr(accounting_imports, "entry_problem", lambda *a: "")
    monkeypatch.setattr(accounting_imports.bank, "refresh_opening_flag", AsyncMock())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(accounting_imports.confirm_import(company.id, "opening-tb", file=None, options="",
                                                     user=user, db=db))
    assert exc.value.status_code == 409
    assert entry_state(row) == original
    db.commit.assert_not_awaited()
