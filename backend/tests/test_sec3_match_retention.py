"""A preparatory document edit must not erase the history used by the delete guard."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.accounting import (
    AAAccount, AAAsset, AAAtcDefault, AAAuditEvent, AABankLine, AABankReconciliation, AABankRule,
    AABankStatement, AABookClose, AACompany, AADocument, AAJournalEntry, AAOpeningItem, AAPeriod,
    AASupplierRule, AAWorkItem,
)
from app.models.user import User, UserRole
from app.routers import accounting
from app.schemas.accounting import DocumentPatch
from app.services.accounting.books import bank
from app.services.accounting.books.chart import standard_chart


def stored(model, **values):
    """Apply insert defaults as the persistence layer would, without replacing service code."""
    row = model(**values)
    for col in model.__table__.columns:
        if col.name not in values and col.default is not None:
            default = col.default.arg
            setattr(row, col.name, default(None) if callable(default) else default)
    return row


class Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None


class MatchDB:
    """One document and bank line; honor live-document and stored-reference queries."""

    def __init__(self):
        self.user = stored(User, id=uuid.uuid4(), role=UserRole.ENTERPRISE, email="retention@example.test")
        self.company = stored(AACompany, id=uuid.uuid4(), enterprise_id=self.user.id, registered_name="Client",
                              vat_status="non-vat", books_start=None)
        self.doc = stored(AADocument, id=uuid.uuid4(), enterprise_id=self.user.id, company_id=self.company.id,
                          file_id=uuid.uuid4(), doc_type="invoice", document_title="Invoice", category="expenses",
                          seller_name="Acme Widgets", doc_number="INV-123", doc_date=date(2026, 4, 2),
                          period_year=2026, period_quarter=2, gross_amount=Decimal("100"),
                          created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        self.line = stored(AABankLine, id=uuid.uuid4(), enterprise_id=self.user.id, company_id=self.company.id,
                           statement_id=uuid.uuid4(), account_code="1020", line_date=date(2026, 3, 31),
                           line_no=1, amount=Decimal("-100"), narration="Acme Widgets INV-123")
        self.accounts = [stored(AAAccount, company_id=self.company.id, enterprise_id=self.user.id,
                                code=a.code, name=a.name, type=a.type, contra=a.contra, system_key=a.system_key)
                         for a in standard_chart("corporation")]
        self.closes = [(date(2026, 3, 1), date(2026, 3, 31))]
        self.locked = False
        self.commits = 0
        self.audits = []

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        name = stmt.column_descriptions[0]["name"]
        where = str(stmt.whereclause)
        if entity is User:
            assert stmt._for_update_arg is not None
            self.locked = True
            return Result([])
        assert self.locked, "mutation facts must be loaded under the firm lock"
        if entity is AACompany:
            return Result([self.company.id if name == "id" else self.company])
        if entity is AADocument:
            if name == "cwt_2307":
                return Result([])
            if name == "id":
                return Result([(self.doc.id, self.doc.settles_document_id)])
            if "aa_documents.id !=" in where:  # supplier propagation excludes the edited document
                return Result([])
            live = self.doc.deleted_at is None
            if "aa_documents.excluded IS false" in where:
                live = live and not self.doc.excluded and self.doc.doc_date is not None
            return Result([self.doc] if live else [])
        if entity is AABankLine:
            if name == "matched_ref":
                return Result([self.line.matched_ref] if self.line.match_status in ("matched", "confirmed") else [])
            if "aa_bank_lines.candidates" in where:  # protect_document's dependency query
                linked = self.line.matched_ref == str(self.doc.id) or any(
                    c.get("ref") == str(self.doc.id) for c in self.line.candidates)
                return Result([self.line] if linked else [])
            return Result([self.line])
        if entity is AAAccount:
            code = stmt.compile().params.get("code_1")
            return Result([a for a in self.accounts if code is None or a.code == code])
        if entity is AABookClose:
            return Result(self.closes)
        assert entity in (AAAsset, AAAtcDefault, AABankReconciliation, AABankRule, AABankStatement,
                          AAJournalEntry, AAOpeningItem, AAPeriod, AASupplierRule, AAWorkItem)
        return Result([])

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    def add(self, row):
        assert isinstance(row, AAAuditEvent)
        self.audits.append(row)


@pytest.mark.parametrize("edit", [
    {"excluded": True}, {"doc_date": "2026-04-05"}, {"paid_on": "2026-04-03"},
    {"period_year": 2026, "period_quarter": 3},
])
async def test_edit_removing_retained_history_is_refused(edit):
    db = MatchDB()
    # Establish the actual match through the candidate builder and matcher, not a mocked rematch.
    assert await bank.rematch(db, db.company) == 1
    assert db.line.matched_ref == str(db.doc.id)
    original = accounting.audit.snapshot(db.doc, accounting._AUDIT_DOC_FIELDS)
    with pytest.raises(HTTPException) as error:
        await accounting.patch_document(db.doc.id, DocumentPatch(**edit), user=db.user, db=db)
    assert error.value.status_code == 409
    assert "deleting" not in error.value.detail and "Reopen the month" in error.value.detail
    assert accounting.audit.snapshot(db.doc, accounting._AUDIT_DOC_FIELDS) == original
    assert db.line.match_status == "matched" and db.line.matched_ref == str(db.doc.id)
    assert db.commits == 0 and not db.audits

    # Opening March makes the same edit legal; the real post-edit rematch still runs.
    db.closes = []
    out = await accounting.patch_document(db.doc.id, DocumentPatch(**edit), user=db.user, db=db)
    assert out.id == db.doc.id and db.commits == 1
    if edit == {"excluded": True}:
        assert db.doc.excluded and db.line.matched_ref == "" and not db.line.candidates
        await accounting.patch_document(db.doc.id, DocumentPatch(doc_date=None, period_year=None,
                                                                period_quarter=None), user=db.user, db=db)
        await accounting.delete_document(db.doc.id, user=db.user, db=db)
        assert db.doc.deleted_at is not None  # the entire sequence is permitted only without retained history


@pytest.mark.parametrize("edit", [
    {"gross_amount": "1000"}, {"withholding_amount": "99"},
    {"seller_name": "Other vendor"}, {"buyer_name": "Other buyer"},
    {"seller_tin": "987654321"}, {"buyer_tin": "987654321"},
    {"account": "rent"}, {"doc_number": "OTHER-456"}, {"ewt_atc": "NONE"},
    {"vat_amount": "10"}, {"gl_account_code": "6900"}, {"paid_via": "cash"},
    {"payment_ref": "OTHER-456"}, {"settles_document_id": None}, {"doc_date": "2026-04-02"},
])
async def test_ordinary_correction_is_allowed_and_keeps_closed_bank_match(edit):
    # A category change with this held line is refused instead (tests/test_sec3_held_line_edits.py).
    db = MatchDB()
    assert await bank.rematch(db, db.company) == 1
    out = await accounting.patch_document(db.doc.id, DocumentPatch(**edit), user=db.user, db=db)
    assert out.id == db.doc.id and db.commits == 1
    # The rematch after the edit leaves the line in closed March alone, so history can't be unmatched.
    assert db.line.match_status == "matched" and db.line.matched_ref == str(db.doc.id)


async def test_review_metadata_remains_editable_with_closed_bank_history():
    db = MatchDB()
    await bank.rematch(db, db.company)
    out = await accounting.patch_document(db.doc.id, DocumentPatch(notes="Checked", reviewed=True),
                                          user=db.user, db=db)
    assert out.notes == "Checked" and out.reviewed
    assert db.line.matched_ref == str(db.doc.id) and db.commits == 1
