"""Router-isolation audit checks: atomic writes, before/after, reasons and firm filtering."""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.accounting import AAAuditEvent, AADocument
from app.services.accounting.audit import record_event, snapshot
from app.services.accounting.rls import rls_statements
from app.services.accounting.schema import column_statements
from app.routers import accounting, accounting_audit, accounting_books
from app.schemas.accounting import DocumentPatch, ReviewOverrideIn


def test_audit_model_migration_and_force_rls():
    assert {"enterprise_id", "company_id", "user_id", "at", "entity", "entity_id", "action", "before", "after", "reason"} <= set(AAAuditEvent.__table__.columns.keys())
    assert "CREATE TABLE IF NOT EXISTS aa_audit_events" in "\n".join(column_statements())
    assert "ALTER TABLE aa_audit_events FORCE ROW LEVEL SECURITY" in "\n".join(rls_statements())


def test_event_copies_money_and_nested_values_without_committing():
    db = MagicMock()
    user = SimpleNamespace(id=uuid.uuid4(), name="Accountant")
    before = {"gross_amount": Decimal("22600.01"), "raw": {"a": [1]}}
    event = record_event(db, enterprise_id=uuid.uuid4(), company_id=uuid.uuid4(), user=user,
                         entity="document", entity_id=uuid.uuid4(), action="update",
                         before=before, after={"gross_amount": Decimal("22601.02")}, reason="Correction")
    before["raw"]["a"].append(2)
    assert event.before["gross_amount"] == "22600.01" and event.before["raw"] == {"a": [1]}
    assert event.after["gross_amount"] == "22601.02"
    db.commit.assert_not_called()


def test_snapshot_is_detached_and_serializes_dates():
    row = AADocument(id=uuid.uuid4(), gross_amount=Decimal("1.01"), doc_date=date(2026, 12, 25), raw={"x": []})
    data = snapshot(row)
    row.raw["x"].append(1)
    assert data["doc_date"] == "2026-12-25" and data["raw"]["x"] == []


@pytest.mark.asyncio
async def test_amount_edit_records_before_and_after(monkeypatch):
    ent, cid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    doc = AADocument(id=uuid.uuid4(), enterprise_id=ent, company_id=cid, gross_amount=Decimal("100"),
                     review_reasons=[], needs_review=False, reviewed=False, review_overrides={},
                     category="expenses", client_role="buyer", seller_tin="", doc_number="A", period_locked=False)
    user = SimpleNamespace(id=uid, role="enterprise", name="Accountant")
    db = MagicMock(); db.flush = AsyncMock(); db.commit = AsyncMock()
    monkeypatch.setattr(accounting, "_document_or_404", AsyncMock(return_value=doc))
    monkeypatch.setattr(accounting, "_company_or_404", AsyncMock(return_value=SimpleNamespace(id=cid)))
    monkeypatch.setattr(accounting, "_document_out", AsyncMock(return_value=SimpleNamespace(rule_applied_to=0)))
    monkeypatch.setattr(accounting, "relink_receipts", AsyncMock())
    monkeypatch.setattr(accounting, "_related_document_states", AsyncMock(return_value=[]))
    monkeypatch.setattr(accounting.duplicates, "refresh_flags", AsyncMock())
    await accounting.patch_document(doc.id, DocumentPatch(gross_amount="200"), user, db)
    events = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], AAAuditEvent)]
    assert len(events) == 1 and events[0].user_id == uid
    assert events[0].before["gross_amount"] == "100" and events[0].after["gross_amount"] == "200"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_override_requires_why_and_records_who(monkeypatch):
    ent, cid, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    doc = AADocument(id=uuid.uuid4(), enterprise_id=ent, company_id=cid, review_reasons=["not_an_invoice"],
                     needs_review=True, reviewed=False, review_overrides={})
    user = SimpleNamespace(id=uid, role="enterprise", name="Accountant")
    db = MagicMock(); db.commit = AsyncMock(); db.flush = AsyncMock()
    monkeypatch.setattr(accounting, "_document_or_404", AsyncMock(return_value=doc))
    monkeypatch.setattr(accounting, "_company_or_404", AsyncMock(return_value=SimpleNamespace(id=cid)))
    monkeypatch.setattr(accounting, "_document_out", AsyncMock(return_value=doc))
    with pytest.raises(HTTPException, match="") as exc:
        await accounting.patch_document(doc.id, DocumentPatch(reviewed=True), user, db)
    assert exc.value.status_code == 400
    db.commit.assert_not_called()
    await accounting.override_review_reason(doc.id, ReviewOverrideIn(review_reason="not_an_invoice", reason="Expense only; no VAT claimed"), user, db)
    event = db.add.call_args.args[0]
    assert event.action == "review_override" and event.user_id == uid and event.reason
    assert event.before["reviewed"] is False and event.after["reviewed"] is True
    assert not doc.needs_review


@pytest.mark.asyncio
async def test_audit_list_always_scopes_firm_and_applies_filters():
    ent, cid, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    user = SimpleNamespace(id=ent, role="enterprise")
    result = MagicMock(); result.all.return_value = []; result.scalars.return_value.all.return_value = []
    db = MagicMock(); db.execute = AsyncMock(return_value=result)
    await accounting_audit.list_audit_events(company_id=cid, user_id=actor,
        date_from=date(2026, 12, 1), date_to=date(2026, 12, 31), entity="document", entity_id="d1",
        limit=50, offset=0, user=user, db=db)
    stmt = db.execute.call_args.args[0]
    params = stmt.compile().params
    assert ent in params.values() and cid in params.values() and actor in params.values()
    assert "d1" in params.values() and "document" in params.values()
    assert "aa_audit_events.enterprise_id" in str(stmt)


@pytest.mark.asyncio
async def test_reopen_records_the_unvoided_state(monkeypatch):
    ent, cid = uuid.uuid4(), uuid.uuid4()
    user = SimpleNamespace(id=ent, role="enterprise", name="Owner")
    row = SimpleNamespace(id=uuid.uuid4(), fiscal_year=2026)
    company = SimpleNamespace(id=cid)
    before = {"fiscal_year": 2026, "months": [{"status": "closed"}]}
    after = {"fiscal_year": 2026, "months": [{"status": "open"}]}
    monkeypatch.setattr(accounting_books, "company_or_404", AsyncMock(return_value=company))
    monkeypatch.setattr(accounting_books, "_books_year", AsyncMock(side_effect=[before, after]))
    monkeypatch.setattr(accounting_books, "reopen_month", AsyncMock(return_value=row))
    monkeypatch.setattr(accounting_books, "touch_books", lambda _: None)
    monkeypatch.setattr(accounting_books, "_reopen_year", AsyncMock(return_value=2026))
    db = MagicMock(); db.commit = AsyncMock(); db.flush = AsyncMock()
    await accounting_books.reopen_books_month(cid, user, db)
    event = db.add.call_args.args[0]
    assert event.action == "reopen" and event.before == before and event.after == after


def test_derived_edits_are_audited_on_the_affected_document():
    ent, cid, source = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    row = AADocument(id=uuid.uuid4(), company_id=cid, enterprise_id=ent, category="expenses", account="other",
                     review_reasons=[], needs_review=False, settles_document_id=None, settles_source="")
    before = accounting._derived_document_state(row)
    row.account = "repairs"
    row.review_reasons = ["supplier_rule_mismatch"]
    row.needs_review = True
    db = MagicMock()
    accounting._audit_related_documents(db, ent, SimpleNamespace(id=uuid.uuid4()), [(row, before)], source)
    event = db.add.call_args.args[0]
    assert event.entity_id == str(row.id) and event.before["account"] == "other"
    assert event.after["account"] == "repairs" and event.after["needs_review"] is True
    assert str(source) in event.reason


@pytest.mark.asyncio
async def test_account_rename_records_previous_name(monkeypatch):
    from app.models.accounting import AAAccount, AACompany
    from app.schemas.accounting_books import AccountPatch
    ent, cid = uuid.uuid4(), uuid.uuid4()
    row = AAAccount(id=uuid.uuid4(), enterprise_id=ent, company_id=cid, code="1010", name="Cash", active=True)
    monkeypatch.setattr(accounting_books, "_account_or_404", AsyncMock(return_value=row))
    monkeypatch.setattr(accounting_books, "company_or_404", AsyncMock(return_value=AACompany(id=cid)))
    db = MagicMock(); db.commit = AsyncMock()
    await accounting_books.patch_account(row.id, AccountPatch(name="Cash on hand"), SimpleNamespace(id=ent, role="enterprise"), db)
    event = db.add.call_args.args[0]
    assert event.entity == "account" and event.before["name"] == "Cash" and event.after["name"] == "Cash on hand"


@pytest.mark.asyncio
async def test_journal_update_records_previous_lines(monkeypatch):
    from datetime import datetime, timezone
    from app.models.accounting import AACompany, AAJournalEntry
    from app.schemas.accounting_books import JournalEntryIn
    ent, cid = uuid.uuid4(), uuid.uuid4()
    old = [{"account_code": "1010", "debit": "100", "credit": "0"}, {"account_code": "3010", "credit": "100", "debit": "0"}]
    row = AAJournalEntry(id=uuid.uuid4(), enterprise_id=ent, company_id=cid, entry_date=date(2026, 12, 1),
                         kind="manual", book="GJ", reference="Old", particulars="", lines=old,
                         created_at=datetime.now(timezone.utc))
    monkeypatch.setattr(accounting_books, "_entry_or_404", AsyncMock(return_value=row))
    monkeypatch.setattr(accounting_books, "company_or_404", AsyncMock(return_value=AACompany(id=cid)))
    monkeypatch.setattr(accounting_books, "_check_entry", AsyncMock())
    db = MagicMock(); db.commit = AsyncMock()
    body = JournalEntryIn(entry_date=date(2026, 12, 2), reference="Corrected",
                          lines=[{"account_code": "1010", "debit": "200"}, {"account_code": "3010", "credit": "200"}])
    await accounting_books.update_journal_entry(row.id, body, SimpleNamespace(id=ent, role="enterprise"), db)
    event = db.add.call_args.args[0]
    assert event.entity == "journal_entry" and event.before["lines"][0]["debit"] == "100"
    assert Decimal(event.after["lines"][0]["debit"]) == 200 and event.after["reference"] == "Corrected"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["close", "bind"])
async def test_close_and_bind_record_state_before_and_after(monkeypatch, action):
    from app.schemas.accounting_books import CloseMonthIn
    ent, cid = uuid.uuid4(), uuid.uuid4()
    company = SimpleNamespace(id=cid, fiscal_year_end_month=12)
    user = SimpleNamespace(id=ent, role="enterprise")
    row = SimpleNamespace(id=uuid.uuid4(), fiscal_year=2026)
    before, after = {"bound": False, "months": []}, {"bound": action == "bind", "months": [{"status": "closed"}]}
    monkeypatch.setattr(accounting_books, "company_or_404", AsyncMock(return_value=company))
    monkeypatch.setattr(accounting_books, "_books_year", AsyncMock(side_effect=[before, after]))
    monkeypatch.setattr(accounting_books, "touch_books", lambda _: None)
    monkeypatch.setattr(accounting_books, "close_month" if action == "close" else "bind_year", AsyncMock(return_value=row))
    db = MagicMock(); db.commit = AsyncMock(); db.flush = AsyncMock()
    if action == "close":
        await accounting_books.close_books_month(CloseMonthIn(month_start=date(2026, 12, 1)), cid, user, db)
    else:
        await accounting_books.bind_books_year(cid, 2026, user, db)
    event = db.add.call_args.args[0]
    assert event.action == action and event.before == before and event.after == after


@pytest.mark.asyncio
async def test_audit_list_rejects_reversed_date_range():
    with pytest.raises(HTTPException) as exc:
        await accounting_audit.list_audit_events(date_from=date(2026, 12, 31), date_to=date(2026, 12, 1),
            user=SimpleNamespace(id=uuid.uuid4(), role="enterprise"), db=MagicMock())
    assert exc.value.status_code == 400
