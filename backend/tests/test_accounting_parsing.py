from datetime import date
from decimal import Decimal

from app.services.accounting.parsing import normalize_tin, parse_doc_date, parse_money


def test_normalize_tin_splits_base_and_branch():
    assert normalize_tin("123-456-789-000") == ("123456789", "00000")
    assert normalize_tin("VAT REG TIN: 123 456 789 00001") == ("123456789", "00001")
    assert normalize_tin("123456789") == ("123456789", "00000")


def test_normalize_tin_rejects_short_or_empty():
    assert normalize_tin("12345") == ("", "")
    assert normalize_tin(None) == ("", "")
    assert normalize_tin("") == ("", "")


def test_parse_money_handles_text_numbers_and_junk():
    assert parse_money("₱1,234.50") == Decimal("1234.50")
    assert parse_money(1234.5) == Decimal("1234.50")
    assert parse_money("(500.00)") == Decimal("-500.00")
    assert parse_money("") == Decimal("0.00")
    assert parse_money(None) == Decimal("0.00")
    assert parse_money("n/a") == Decimal("0.00")
    assert parse_money(float("nan")) == Decimal("0.00")
    assert parse_money(True) == Decimal("0.00")


def test_parse_doc_date_formats():
    assert parse_doc_date("2026-08-14") == date(2026, 8, 14)
    assert parse_doc_date("08/14/2026") == date(2026, 8, 14)
    assert parse_doc_date("August 14, 2026") == date(2026, 8, 14)
    assert parse_doc_date("Aug 14, 2026") == date(2026, 8, 14)


def test_parse_doc_date_rejects_garbage_and_out_of_range():
    assert parse_doc_date("") is None
    assert parse_doc_date(None) is None
    assert parse_doc_date("yesterday") is None
    assert parse_doc_date("1899-01-01") is None


def test_parse_money_rejects_values_too_large_for_numeric_14_2():
    assert parse_money("123456789012345") == Decimal("0.00")
    assert parse_money(1e12) == Decimal("0.00")
    assert parse_money("999,999,999,999.99") == Decimal("999999999999.99")
