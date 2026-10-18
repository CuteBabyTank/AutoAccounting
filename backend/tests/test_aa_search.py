"""Global search: pure query parsing (amount / TIN / PH dates / review reasons) and ranking."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.accounting.search import (
    REASON_NAMES, like_pattern, match_reasons, parse_amount, parse_dates, parse_query, parse_tin, score,
)

TODAY = date(2026, 10, 18)


@pytest.mark.parametrize("raw", ["1500", "1,500.00", "₱1,500", "P1,500", "PHP 1500", "php1,500.00", "₱ 1,500.0"])
def test_amount_formats(raw):
    assert parse_amount(raw) == Decimal("1500.00")


@pytest.mark.parametrize("raw", ["12/2026", "1,50", "1.234,50", "abc", "", "1,5000", "₱", "1.2.3"])
def test_not_amounts(raw):
    assert parse_amount(raw) is None


def test_amount_decimals():
    assert parse_amount("1500.5") == Decimal("1500.50")
    assert parse_amount("330,854.85") == Decimal("330854.85")


@pytest.mark.parametrize("raw", ["123-456-789", "123 456 789", "123456789", "123-456-789-000", "123 456 789 00000"])
def test_tin_formats(raw):
    assert parse_tin(raw) == "123456789"


@pytest.mark.parametrize("raw", ["12345678", "123-456-78", "SI 123456789", "1234567890123456"])
def test_not_tins(raw):
    assert parse_tin(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-15", [(date(2026, 10, 15), date(2026, 10, 15))]),
    ("10/15/2026", [(date(2026, 10, 15), date(2026, 10, 15))]),
    ("15/10/2026", [(date(2026, 10, 15), date(2026, 10, 15))]),
    ("10-15-2026", [(date(2026, 10, 15), date(2026, 10, 15))]),
    ("10/15/26", [(date(2026, 10, 15), date(2026, 10, 15))]),
    ("Oct 15, 2026", [(date(2026, 10, 15), date(2026, 10, 15))]),
    ("October 15 2026", [(date(2026, 10, 15), date(2026, 10, 15))]),
    ("15 Oct 2026", [(date(2026, 10, 15), date(2026, 10, 15))]),
    ("Sept 3, 2026", [(date(2026, 9, 3), date(2026, 9, 3))]),
    ("Oct 2026", [(date(2026, 10, 1), date(2026, 10, 31))]),
    ("February 2028", [(date(2028, 2, 1), date(2028, 2, 29))]),
    ("2026-10", [(date(2026, 10, 1), date(2026, 10, 31))]),
])
def test_dates(raw, expected):
    assert parse_dates(raw, TODAY) == expected


def test_ambiguous_slash_date_gives_both_readings_mmdd_first():
    assert parse_dates("03/04/2026", TODAY) == [(date(2026, 3, 4), date(2026, 3, 4)), (date(2026, 4, 3), date(2026, 4, 3))]
    assert parse_dates("04/04/2026", TODAY) == [(date(2026, 4, 4), date(2026, 4, 4))]


@pytest.mark.parametrize("raw", ["13/13/2026", "Feb 30, 2026", "2026-13", "1500", "Octopus 2026", "1850-01-01"])
def test_not_dates(raw):
    assert parse_dates(raw, TODAY) == []


def test_reasons():
    assert set(match_reasons("duplicate")) == {"possible_duplicate", "duplicate_invoice_number"}
    assert match_reasons("ewt") == ["ewt_expected"]
    assert match_reasons("Missing date") == ["missing_date"]
    assert match_reasons("vat_math_mismatch") == ["vat_math_mismatch"]
    assert match_reasons("xy") == []
    assert match_reasons("the") == []
    assert all(code in REASON_NAMES for code in match_reasons("vat"))


def test_like_pattern_escapes_wildcards():
    assert like_pattern("50%_\\") == "%50\\%\\_\\\\%"
    assert like_pattern("luzon") == "%luzon%"


def test_parse_query_short_and_structured():
    assert parse_query("a", TODAY).too_short
    assert parse_query("   ", TODAY).too_short
    assert not parse_query("₱5", TODAY).too_short
    assert parse_query("₱5", TODAY).amount == Decimal("5.00")
    assert not parse_query("si", TODAY).too_short
    q = parse_query("  Luzon   Paint  5838 ", TODAY)
    assert q.text == "Luzon Paint 5838" and q.tokens == ["Luzon", "Paint", "5838"]
    assert q.amount is None and q.tin is None and q.dates == []
    assert parse_query("1500", TODAY).amount == Decimal("1500.00")
    assert parse_query("123-456-789", TODAY).tin == "123456789"
    assert parse_query("4005", TODAY).tin_prefix == "4005"
    assert parse_query("40", TODAY).tin_prefix is None
    assert parse_query("a b c d e f g h", TODAY).tokens == ["a", "b", "c", "d", "e"]
    assert len(parse_query("x" * 500, TODAY).text) == 100


def test_parse_query_date_with_spaces_is_one_value():
    q = parse_query("Oct 15, 2026", TODAY)
    assert q.dates == [(date(2026, 10, 15), date(2026, 10, 15))]


def test_score_orders_exact_prefix_contains():
    q = parse_query("5838", TODAY)
    exact = score({"number": "5838"}, q, set())
    prefix = score({"number": "5838-A"}, q, set())
    contains = score({"number": "SI-15838"}, q, set())
    assert exact > prefix > contains > 0
    assert score({"number": "9999"}, q, set()) == 0


def test_score_structured_and_tokens():
    q = parse_query("luzon paint", TODAY)
    both = score({"name": "Luzon Paint Center"}, q, set())
    one = score({"name": "Luzon Hardware"}, q, set())
    assert both > one > 0
    assert score({"name": "x"}, parse_query("123-456-789", TODAY), {"tin"}) >= 90
    assert score({"name": "x"}, parse_query("1500", TODAY), {"amount"}) >= 70


@pytest.mark.parametrize("raw", ["(1,500)", "₱(1,500.00)", "(₱1,500)", "PHP (1500)"])
def test_amount_in_parentheses(raw):
    # Accounting negatives are written in parentheses; the search amount is the absolute value.
    assert parse_amount(raw) == Decimal("1500.00")


@pytest.mark.parametrize("raw", ["(1,500", "1,500)", "((1500))"])
def test_unbalanced_parentheses_not_amounts(raw):
    assert parse_amount(raw) is None


def test_query_drops_control_characters():
    # Postgres rejects NUL in text parameters (a 500); other control characters never match anything.
    q = parse_query("a\x00b\x07c", TODAY)
    assert q.text == "abc" and q.tokens == ["abc"]
    assert parse_query("\x00\x00", TODAY).too_short

