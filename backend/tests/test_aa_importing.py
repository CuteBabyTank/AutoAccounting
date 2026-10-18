"""Import primitives: amounts, date-format detection, column suggestion, fuzzy account matching (pure)."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.accounting.importing import (
    AccountRef, detect_date_format, match_account, parse_amount, parse_date, source_key, suggest_columns,
)

D = Decimal
CHART = [AccountRef("1010", "Cash on hand", True, False), AccountRef("1020", "Cash in bank", True, False),
         AccountRef("1100", "Accounts receivable - trade", True, False),
         AccountRef("2010", "Accounts payable - trade", True, False), AccountRef("3010", "Capital", True, False),
         AccountRef("6020", "Rent", True, True)]


def test_parse_amount_variants():
    assert parse_amount("1,234.50") == D("1234.50")
    assert parse_amount("(500)") == D("-500")
    assert parse_amount("₱ 2,000") == D("2000")
    assert parse_amount("PHP 10") == D("10")
    assert parse_amount("100 CR") == D("-100")
    assert parse_amount("100 dr") == D("100")
    assert parse_amount("-75.25") == D("-75.25")
    assert parse_amount("") is None and parse_amount("-") is None
    with pytest.raises(ValueError):
        parse_amount("abc")


def test_detect_date_format_iso_and_us():
    assert detect_date_format(["2026-01-31", "", "2026-02-01T00:00:00"])[0] == "%Y-%m-%d"
    assert detect_date_format(["12/31/2026", "01/15/2026"])[0] == "%m/%d/%Y"
    assert detect_date_format(["31/12/2026"])[0] == "%d/%m/%Y"
    assert detect_date_format(["Dec 31, 2026"])[0] == "%b %d, %Y"
    assert detect_date_format(["nonsense"]) == (None, [])


def test_detect_date_format_ambiguous():
    chosen, candidates = detect_date_format(["03/04/2026", "05/06/2026"])
    assert chosen is None
    assert candidates[:2] == ["%m/%d/%Y", "%d/%m/%Y"]


def test_parse_date():
    assert parse_date("03/04/2026", "%d/%m/%Y") == date(2026, 4, 3)
    assert parse_date("2026-01-31T00:00:00", "%Y-%m-%d") == date(2026, 1, 31)
    with pytest.raises(ValueError):
        parse_date("31/12/2026", "%m/%d/%Y")


def test_match_account_code_name_fuzzy():
    assert match_account("1020", "", CHART).code == "1020"
    assert match_account("1020", "", CHART).how == "code"
    m = match_account("", "cash in bank", CHART)
    assert (m.code, m.how) == ("1020", "name")
    m = match_account("", "Accts receivable - trade", CHART)   # abbreviation expanded: an exact name
    assert (m.code, m.how) == ("1100", "name")
    m = match_account("", "Account receivables trade", CHART)
    assert (m.code, m.how) == ("1100", "fuzzy")
    assert match_account("", "Zzz qqq", CHART).how == "none"
    # a code not in the chart falls back to the name
    assert match_account("9999", "Capital", CHART).code == "3010"


def test_match_account_leading_code_in_name():
    m = match_account("", "1010 - Cash on hand", CHART)
    assert (m.code, m.how) == ("1010", "code")


def test_match_account_still_matches_locked_so_the_row_can_say_why():
    assert match_account("6020", "", CHART).code == "6020"


def test_source_key_normalises_name():
    assert source_key(" 1020 ", "Cash  in Bank!") == source_key("1020", "cash in bank")


def test_suggest_columns():
    synonyms = ((r"code", "account_code"), (r"account|name", "account_name"), (r"debit|\bdr\b", "debit"),
                (r"credit|\bcr\b", "credit"))
    got = suggest_columns(["Acct Code", "Account Title", "Dr", "Cr"], synonyms)
    assert got == {"account_code": "Acct Code", "account_name": "Account Title", "debit": "Dr", "credit": "Cr"}
