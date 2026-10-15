from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.accounting import CompanyIn
from app.schemas.accounting_books import AccountIn, JournalEntryIn
from tests.test_accounting_annual_routes import _endpoint

LINES = [{"account_code": "1010", "debit": "500"}, {"account_code": "3010", "credit": "500"}]


def test_journal_entry_must_balance_and_lines_are_one_sided():
    e = JournalEntryIn(entry_date=date(2026, 7, 1), lines=LINES)
    assert e.kind == "manual" and e.book == "GJ" and e.lines[0].debit == Decimal("500")
    with pytest.raises(ValidationError, match="balance"):
        JournalEntryIn(entry_date=date(2026, 7, 1), lines=[LINES[0], {"account_code": "3010", "credit": "400"}])
    with pytest.raises(ValidationError):
        JournalEntryIn(entry_date=date(2026, 7, 1),
                       lines=[{"account_code": "1010", "debit": "5", "credit": "5"}, LINES[1]])
    with pytest.raises(ValidationError):
        JournalEntryIn(entry_date=date(2026, 7, 1), lines=[LINES[0]])
    with pytest.raises(ValidationError):
        JournalEntryIn(kind="opening", book="CRJ", entry_date=date(2026, 7, 1), lines=LINES)


def test_account_codes_are_digits():
    assert AccountIn(code="6021", name="Rent - warehouse", parent_code="6020").code == "6021"
    with pytest.raises(ValidationError):
        AccountIn(code="60-21", name="x", parent_code="6020")


def test_company_books_defaults_follow_vat_status():
    vat = CompanyIn(registered_name="A", tin="123456789", vat_status="vat")
    non = CompanyIn(registered_name="A", tin="123456789", vat_status="non_vat", books_kept=["CRJ"])
    assert vat.books_kept == ["SJ", "PJ", "CRJ", "CDJ", "GJ", "GL"]
    assert non.books_kept == ["CRJ", "GJ", "GL"]   # GJ and GL are always kept
    with pytest.raises(ValidationError):
        CompanyIn(registered_name="A", tin="123456789", books_kept=["XYZ"])


def test_routes_resolve():
    cid = "6a1c2f40-0000-4000-8000-000000000000"
    assert _endpoint("GET", f"/companies/{cid}/accounts") == "list_accounts"
    assert _endpoint("POST", f"/companies/{cid}/accounts") == "add_account"
    assert _endpoint("PATCH", f"/accounts/{cid}") == "patch_account"
    assert _endpoint("GET", f"/companies/{cid}/journal-entries") == "list_journal_entries"
    assert _endpoint("POST", f"/companies/{cid}/journal-entries") == "create_journal_entry"
    assert _endpoint("PUT", f"/journal-entries/{cid}") == "update_journal_entry"
    assert _endpoint("DELETE", f"/journal-entries/{cid}") == "delete_journal_entry"
    assert _endpoint("GET", f"/documents/{cid}/payments") == "document_payments"
    assert _endpoint("GET", f"/documents/{cid}") == "get_document"
