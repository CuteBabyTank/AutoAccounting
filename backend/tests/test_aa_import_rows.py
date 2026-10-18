"""Opening TB, opening open items and journal-entry import: rows → validated drafts (pure)."""

from datetime import date
from decimal import Decimal

from app.services.accounting.import_rows import (
    TB_SYNONYMS, TEMPLATES, build_journals, build_open_items, build_tb, control_tie,
)
from app.services.accounting.importing import AccountRef, source_key, suggest_columns

D = Decimal
START = date(2026, 1, 1)
CHART = [AccountRef("1010", "Cash on hand"), AccountRef("1020", "Cash in bank"),
         AccountRef("1100", "Accounts receivable - trade"), AccountRef("1500", "Property and equipment"),
         AccountRef("2010", "Accounts payable - trade"), AccountRef("2140", "Withholding tax on compensation payable"),
         AccountRef("2170", "SSS / PhilHealth / Pag-IBIG payable"), AccountRef("3010", "Capital"),
         AccountRef("3020", "Retained earnings"), AccountRef("6010", "Salaries and wages"),
         AccountRef("6020", "Rent", locked=True), AccountRef("6900", "Miscellaneous", active=False)]
TB_HEAD = ["Account code", "Account name", "Debit", "Credit"]
TB_COLS = {"account_code": "Account code", "account_name": "Account name", "debit": "Debit", "credit": "Credit"}


def tb(rows, **kw):
    return build_tb(TB_HEAD, rows, TB_COLS, CHART, kw.pop("overrides", {}), **kw)


def test_tb_columns_are_guessed():
    assert suggest_columns(["Acct No.", "Account Title", "Dr", "Cr", "As of"], TB_SYNONYMS) == {
        "account_code": "Acct No.", "account_name": "Account Title", "debit": "Dr", "credit": "Cr", "as_of": "As of"}


def test_tb_balances_and_merges():
    r = tb([["1020", "Cash in bank", "330,854.85", ""], ["", "Accounts receivable trade", "100,000", ""],
            ["3010", "Capital", "", "430,854.85"]])
    assert r.lines == [("1020", D("330854.85"), D("0")), ("1100", D("100000"), D("0")),
                       ("3010", D("0"), D("430854.85"))]
    assert (r.debit, r.credit, r.difference, r.ready) == (D("430854.85"), D("430854.85"), D("0"), True)


def test_tb_merges_duplicate_accounts():
    r = tb([["1020", "", "100", ""], ["1020", "", "50", ""], ["3010", "", "", "150"]])
    assert r.lines == [("1020", D("150"), D("0")), ("3010", D("0"), D("150"))]


def test_tb_skips_total_rows():
    r = tb([["1020", "", "100", ""], ["3010", "", "", "100"], ["", "TOTAL", "100", "100"], ["", "", "", ""]])
    assert r.debit == D("100") and r.ready


def test_tb_negative_debit_is_credit():
    r = tb([["1020", "", "100", ""], ["3010", "", "-100", ""]])
    assert r.lines[-1] == ("3010", D("0"), D("100")) and r.ready


def test_tb_override_wins_over_fuzzy_and_unmapped_blocks():
    rows = [["", "Bank - BDO", "100", ""], ["3010", "", "", "100"]]
    r = tb(rows)
    assert not r.ready
    assert next(a for a in r.accounts if a.name_in == "Bank - BDO").problem == "unmapped"
    r = tb(rows, overrides={source_key("", "Bank - BDO"): "1020"})
    assert r.ready and r.lines[0] == ("1020", D("100"), D("0"))


def test_tb_locked_and_inactive_accounts_error():
    r = tb([["6020", "", "100", ""], ["6900", "", "50", ""], ["3010", "", "", "150"]])
    problems = {a.chosen: a.problem for a in r.accounts}
    assert problems["6020"] == "locked" and problems["6900"] == "inactive" and not r.ready


def test_tb_difference_needs_an_explicit_account():
    rows = [["1020", "", "100", ""], ["3010", "", "", "90"]]
    r = tb(rows)
    assert r.difference == D("10") and not r.ready
    r = tb(rows, difference_account="3020")
    assert r.ready and ("3020", D("0"), D("10")) in r.lines and r.difference == D("0")
    assert not tb(rows, difference_account="6020").ready      # locked can't take it


def test_tb_bad_amount_is_a_row_error():
    r = tb([["1020", "", "abc", ""], ["3010", "", "", "100"]])
    assert r.errors and r.errors[0].row == 1 and not r.ready


def test_tb_as_of_warns_when_not_the_day_before_books_start():
    head = TB_HEAD + ["As of"]
    cols = {**TB_COLS, "as_of": "As of"}
    r = build_tb(head, [["1020", "", "1", "", "12/31/2025"], ["3010", "", "", "1", "12/31/2025"]], cols, CHART, {},
                 books_start=START)
    assert r.as_of == date(2025, 12, 31) and not r.warnings
    r = build_tb(head, [["1020", "", "1", "", "11/30/2025"], ["3010", "", "", "1", ""]], cols, CHART, {},
                 books_start=START)
    assert r.warnings


OI_HEAD = ["Type", "Customer / supplier", "TIN", "Invoice no.", "Date", "Due date", "Terms", "Amount"]
OI_COLS = {"kind": "Type", "contact_name": "Customer / supplier", "contact_tin": "TIN", "doc_number": "Invoice no.",
           "doc_date": "Date", "due_date": "Due date", "terms_days": "Terms", "amount": "Amount"}


def test_open_items_kinds_and_terms():
    r = build_open_items(OI_HEAD, [
        ["AR", "Mabuhay Builders", "123-456-789-000", "0003", "12/10/2025", "", "Net 30", "150,000.00"],
        ["Payable", "Pacific Steel", "", "PS-77", "12/20/2025", "01/19/2026", "", "80,000"],
    ], OI_COLS, START)
    a, b = r.items
    assert (a.kind, a.contact_tin, a.terms_days, a.amount, a.doc_date) == (
        "ar", "123456789", 30, D("150000.00"), date(2025, 12, 10))
    assert (b.kind, b.due_date) == ("ap", date(2026, 1, 19))
    assert r.totals == {"ar": D("150000.00"), "ap": D("80000")} and r.ready


def test_open_items_default_kind_and_duplicates():
    head, cols = OI_HEAD[1:], {k: v for k, v in OI_COLS.items() if k != "kind"}
    rows = [["Mabuhay", "", "0003", "2025-12-10", "", "", "100"], ["Mabuhay", "", "0003", "2025-12-10", "", "", "100"]]
    assert not build_open_items(head, rows, cols, START).ready              # no type column, no default
    r = build_open_items(head, rows, cols, START, default_kind="ar")
    assert len(r.items) == 1 and r.errors and "twice" in r.errors[0].message
    r = build_open_items(head, rows[:1], cols, START, default_kind="ar", existing={("ar", "mabuhay", "0003")})
    assert not r.items and r.skipped == 1


def test_open_items_refuse_dates_after_books_start():
    r = build_open_items(OI_HEAD, [["AR", "Mabuhay", "", "0009", "01/25/2026", "", "", "100"]], OI_COLS, START)
    assert not r.items and "before the books start" in r.errors[0].message


def test_open_items_ambiguous_date_needs_format():
    rows = [["AR", "Mabuhay", "", "1", "03/04/2025", "", "", "100"]]
    r = build_open_items(OI_HEAD, rows, OI_COLS, START)
    assert r.date_format is None and r.date_candidates[:2] == ["%m/%d/%Y", "%d/%m/%Y"] and not r.ready
    r = build_open_items(OI_HEAD, rows, OI_COLS, START, date_format="%d/%m/%Y")
    assert r.items[0].doc_date == date(2025, 4, 3) and r.ready


def test_control_tie_warns():
    assert control_tie({"ar": D("100")}, {"ar": D("100"), "ap": D("0")}) == []
    warnings = control_tie({"ar": D("90"), "ap": D("0")}, {"ar": D("100"), "ap": D("50")})
    assert len(warnings) == 2 and "10.00" in warnings[0]


JE_HEAD = ["JE no", "Date", "Account", "Account name", "Debit", "Credit", "Description", "Ref", "Adjusting"]
JE_COLS = {"journal_no": "JE no", "date": "Date", "account_code": "Account", "account_name": "Account name",
           "debit": "Debit", "credit": "Credit", "description": "Description", "reference": "Ref",
           "adjusting": "Adjusting"}
PAYROLL = [  # Q4 pack: December payroll, ₱105,405.30 left the bank
    ["1", "12/31/2026", "6010", "", "120,000.00", "", "December payroll", "PR-12", ""],
    ["1", "", "2140", "", "", "8,000.00", "", "", ""],
    ["1", "", "2170", "", "", "6,594.70", "", "", ""],
    ["1", "", "1020", "", "", "105,405.30", "", "", ""],
    ["2", "12/31/2026", "1500", "", "-500", "", "Reclass", "", "yes"],
    ["2", "12/31/2026", "3020", "", "", "-500", "", "", "yes"],
]


def je(rows, head=JE_HEAD, cols=JE_COLS, **kw):
    return build_journals(head, rows, cols, CHART, kw.pop("overrides", {}), books_start=START, **kw)


def test_je_groups_by_journal_no():
    r = je(PAYROLL)
    assert len(r.entries) == 2 and r.ready
    pay = r.entries[0]
    assert (pay.entry_date, pay.reference, pay.particulars, pay.is_adjusting) == (
        date(2026, 12, 31), "PR-12", "December payroll", False)
    assert [(l["account_code"], l["debit"], l["credit"]) for l in pay.lines][-1] == ("1020", D("0"), D("105405.30"))


def test_je_negative_amounts():
    reclass = je(PAYROLL).entries[1]
    assert reclass.is_adjusting
    assert [(l["account_code"], l["debit"], l["credit"]) for l in reclass.lines] == [
        ("1500", D("0"), D("500")), ("3020", D("500"), D("0"))]


def test_je_groups_by_date_and_ref_and_signed_amount_column():
    head = ["Date", "Ref", "Account", "Amount"]
    cols = {"date": "Date", "reference": "Ref", "account_code": "Account", "amount": "Amount"}
    rows = [["2026-02-01", "A", "1020", "100"], ["2026-02-01", "A", "3010", "-100"],
            ["2026-02-02", "B", "1020", "5"], ["", "", "3010", "(5)"]]
    r = je(rows, head, cols)
    assert [e.reference for e in r.entries] == ["A", "B"] and r.ready


def test_je_unbalanced_entry_errors():
    r = je([["1", "12/31/2026", "6010", "", "100", "", "", "", ""], ["1", "", "1020", "", "", "90", "", "", ""]])
    assert not r.ready and "balance" in r.entries[0].errors[0]


def test_je_single_line_and_locked_account_error():
    r = je([["1", "12/31/2026", "6020", "", "100", "", "", "", ""], ["1", "", "1020", "", "", "100", "", "", ""],
            ["2", "12/31/2026", "1020", "", "1", "", "", "", ""]])
    assert any("locked" in e for e in r.entries[0].errors)
    assert any("two lines" in e for e in r.entries[1].errors)


def test_je_before_books_start_errors():
    r = je([["1", "12/31/2025", "6010", "", "1", "", "", "", ""], ["1", "", "1020", "", "", "1", "", "", ""]])
    assert any("books start" in e for e in r.entries[0].errors)


def test_je_rows_use_override_format():
    rows = [["1", "03/04/2026", "6010", "", "1", "", "", "", ""], ["1", "", "1020", "", "", "1", "", "", ""]]
    assert not je(rows).ready
    assert je(rows, date_format="%d/%m/%Y").entries[0].entry_date == date(2026, 4, 3)


def test_je_closed_month_posts_on_first_open_day():
    r = je(PAYROLL, last_closed=date(2026, 12, 31))
    assert r.entries[0].posts_on == date(2027, 1, 1)
    assert je(PAYROLL).entries[0].posts_on == date(2026, 12, 31)


def test_templates_have_headers_and_rows():
    for kind in ("opening-tb", "open-items", "journal-entries"):
        headers, rows = TEMPLATES[kind]
        assert headers and rows and all(len(r) == len(headers) for r in rows)
