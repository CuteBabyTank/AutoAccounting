from datetime import date
from decimal import Decimal

from app.services.accounting.bank_statement import last4, parse_statement, resolve_account, tie_out
from app.services.accounting.extraction import EXTRACT_PROMPT

D = Decimal

# Q4 pack, December statement of Pinoy Commerce Bank checking 0041-2288-7710 (as Gemini would return it).
Q4_LINES = [
    ("2026-12-02", "Check #000818 - Sta. Elena Realty (Dec rent)", "32100.00", "", "380780.15"),
    ("2026-12-04", "POS - Petro Bayan Gas Station", "3500.00", "", "377280.15"),
    ("2026-12-11", "Deposit - Mabuhay Builders (partial SI 0008)", "", "50000.00", "427280.15"),
    ("2026-12-15", "Cash deposit - store sales", "", "38450.00", "465730.15"),
    ("2026-12-18", "Online transfer - QuickFix Aircon", "6720.00", "", "459010.15"),
    ("2026-12-23", "Payroll credit - 4 employees", "105405.30", "", "353604.85"),
    ("2026-12-25", "Check #000819 - Golden Hardware Wholesale", "22600.00", "", "331004.85"),
    ("2026-12-31", "Service charge", "150.00", "", "330854.85"),
]


def q4_raw(lines=Q4_LINES, closing="330,854.85"):
    return {"kind": "statement", "statement": {
        "bank_name": "Pinoy Commerce Bank", "account_number": "0041-2288-7710",
        "period_start": "2026-12-01", "period_end": "2026-12-31",
        "opening_balance": "412,880.15", "closing_balance": closing,
        "lines": [{"date": d, "description": t, "debit": dr, "credit": cr, "balance": b, "ref": ""}
                  for d, t, dr, cr, b in lines],
    }}


def test_extract_prompt_asks_for_statement_lines():
    assert '"statement"' in EXTRACT_PROMPT and "opening_balance" in EXTRACT_PROMPT


def test_parse_q4_statement():
    s = parse_statement(q4_raw())
    assert s.account_number == "0041-2288-7710" and s.bank_name == "Pinoy Commerce Bank"
    assert (s.period_start, s.period_end) == (date(2026, 12, 1), date(2026, 12, 31))
    assert s.opening == D("412880.15") and s.closing == D("330854.85")
    assert [l.amount for l in s.lines][:4] == [D("-32100.00"), D("-3500.00"), D("50000.00"), D("38450.00")]
    assert s.lines[0].check_no == "000818" and s.lines[6].check_no == "000819" and s.lines[1].check_no == ""
    assert [l.line_no for l in s.lines] == list(range(1, 9))


def test_parse_statement_without_lines_is_none():
    assert parse_statement({"kind": "statement"}) is None
    assert parse_statement(None) is None
    assert parse_statement({"statement": {"lines": []}}) is None


def test_ref_field_wins_and_undated_lines_are_dropped():
    raw = q4_raw([("2026-12-02", "CHECK 123", "10.00", "", ""), ("", "x", "1", "", "")], closing="")
    s = parse_statement(raw)
    assert len(s.lines) == 1 and s.lines[0].check_no == "123" and s.closing is None


def test_tie_out_q4_ties():
    assert tie_out(parse_statement(q4_raw())) == (True, [])


def test_tie_out_reports_the_breaking_line():
    lines = list(Q4_LINES)
    lines[2] = ("2026-12-11", "Deposit - Mabuhay Builders (partial SI 0008)", "", "5000.00", "427280.15")
    ok, breaks = tie_out(parse_statement(q4_raw(lines)))
    assert ok is False and breaks[0] == 3


def test_tie_out_without_printed_balances_checks_the_closing():
    lines = [(d, t, dr, cr, "") for d, t, dr, cr, _ in Q4_LINES]
    assert tie_out(parse_statement(q4_raw(lines))) == (True, [])
    assert tie_out(parse_statement(q4_raw(lines, closing="330,000.00")))[0] is False


def test_last4_and_resolve_account():
    assert last4("0041-2288-7710") == "7710" and last4("SA ****7710") == "7710" and last4("") == ""
    accounts = [("1020", "0041-2288-7710"), ("1021", "9999-0000-1234"), ("1010", "")]
    assert resolve_account("Acct No. 7710", accounts) == "1020"
    assert resolve_account("5555", accounts) is None
    assert resolve_account("7710", accounts + [("1022", "1111-7710")]) is None
    assert resolve_account("", accounts) is None


def test_line_pages_are_optional_and_map_to_file_pages():
    from app.services.accounting.bank_statement import file_page

    assert "\"page\"" in EXTRACT_PROMPT
    raw = {"page_start": 2, "statement": {"lines": [
        {"date": "2026-12-01", "description": "Check 000818", "debit": 50000, "credit": 0, "page": 2},
        {"date": "2026-12-20", "description": "Deposit", "debit": 0, "credit": 1000, "page": "3"},
        {"date": "2026-12-21", "description": "POS", "debit": 10, "credit": 0, "page": "x"},
        {"date": "2026-12-22", "description": "Fee", "debit": 150, "credit": 0}]}}
    s = parse_statement(raw)
    assert [l.page for l in s.lines] == [2, 3, None, None]       # older replies have no page: None
    # the reply's pages are within the chunk sent to Gemini; the document's pages are file pages (chunk + offset)
    assert file_page(3, raw, 12, 14) == 13
    assert file_page(2, raw, 12, 14) == 12
    assert file_page(9, raw, 12, 14) is None                     # outside the document: unknown
    assert file_page(None, raw, 12, 14) is None
    assert file_page(1, {}, 1, 3) == 1                           # no page_start in the reply: offset 0
