from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, default_books, standard_chart
from app.services.accounting.compute.book_ledgers import (
    BOOK_TABS, build_books, entry_numbers, trial_balance_totals,
)
from app.services.accounting.compute.books import BooksInput, Line, ManualEntry, Payment, post_all
from app.services.accounting.compute.money import ZERO
from app.services.accounting.compute.specs import LEDGER_COLUMNS, LEDGER_ORDER
from tests.aa_factories import company, expense, sale

D = Decimal
CHART = Chart(standard_chart("corporation"))
C = CHART.code


def _entries():
    opening = ManualEntry("o", "opening", "GJ", date(2026, 7, 1), "OB", "Opening balances",
                          (Line(C("cash"), debit=D("5000")), Line(C("ar"), debit=D("1000"), party_name="Old Client"),
                           Line(C("capital"), credit=D("6000"))))
    s = sale(gross="11200", vatable="10000", vat="1200", doc_date=date(2026, 7, 5), doc_number="SI-1")
    e = expense(account="rent", gross="5600", vat="600", input_vat_valid=True, doc_date=date(2026, 7, 6),
                doc_number="B-9")
    inp = BooksInput(company(), CHART, frozenset(default_books(True)), date(2026, 7, 1), date(2026, 9, 30),
                     lines=(s, e), ewt={e.id: D("250")}, manual=(opening,),
                     payments=(Payment("p1", s.id, date(2026, 8, 1), None, "bank", "CR-1"),
                               Payment("p2", e.id, date(2026, 8, 2), None, "cash", "")))
    return post_all(inp)[0], s, e


def test_every_tab_has_columns_and_rows_carry_every_column():
    entries, _, _ = _entries()
    tabs = build_books(entries, CHART, date(2026, 7, 1), date(2026, 9, 30), 12, frozenset(default_books(True)), C("retained_earnings"))
    assert set(tabs) == set(BOOK_TABS)
    for name in BOOK_TABS:
        assert name in LEDGER_ORDER
        keys = {k for k, _, _ in LEDGER_COLUMNS[name]}
        for row in tabs[name]:
            assert keys <= set(row) and "key" in row, (name, row)
        assert len({r["key"] for r in tabs[name]}) == len(tabs[name]), name


def test_journal_columns():
    entries, s, e = _entries()
    tabs = build_books(entries, CHART, date(2026, 7, 1), date(2026, 9, 30), 12, frozenset(default_books(True)), C("retained_earnings"))
    [sj] = tabs["SJ"]
    assert (sj["reference"], sj["ar"], sj["vatable"], sj["output_vat"]) == ("SI-1", D("11200.00"), D("10000"),
                                                                         D("1200.00"))
    [pj] = tabs["PJ"]
    assert (pj["expense"], pj["input_vat"], pj["ewt"], pj["ap"]) == (D("5000.00"), D("600.00"), D("250.00"),
                                                                    D("5350.00"))
    [crj] = tabs["CRJ"]
    assert (crj["bank"], crj["ar"], crj["cash"]) == (D("11200.00"), D("11200.00"), D("0.00"))
    [cdj] = tabs["CDJ"]
    assert (cdj["cash"], cdj["ap"]) == (D("5350.00"), D("5350.00"))
    assert {r["code"] for r in tabs["GJ"]} == {C("cash"), C("ar"), C("capital")}


def test_trial_balance_balances_and_ledgers_carry_balances():
    entries, _, _ = _entries()
    tabs = build_books(entries, CHART, date(2026, 8, 1), date(2026, 9, 30), 12, frozenset(default_books(True)), C("retained_earnings"))
    debit, credit = trial_balance_totals(tabs["TB"])
    assert debit == credit
    ar_rows = [r for r in tabs["GL"] if r["code"] == C("ar")]
    assert ar_rows[0]["particulars"] == "Balance brought forward" and ar_rows[0]["balance"] == D("12200.00")
    assert ar_rows[-1]["balance"] == D("1000.00") and ar_rows[-1]["side"] == "Dr"
    parties = {r["party"] for r in tabs["AR"]}
    assert {"Old Client", "Customer"} <= parties


def test_books_not_kept_have_no_tab():
    entries, _, _ = _entries()
    tabs = build_books(entries, CHART, date(2026, 7, 1), date(2026, 9, 30), 12, frozenset(default_books(False)), C("retained_earnings"))
    assert "SJ" not in tabs and "PJ" not in tabs and "GJ" in tabs and "GL" in tabs


def test_entry_numbers_restart_each_fiscal_year():
    entries, _, _ = _entries()
    numbers = entry_numbers(entries, 12)
    assert numbers["je:o"] == "GJ-2026-P0001"
    assert all(n.startswith(("SJ-2026", "PJ-2026", "CRJ-2026", "CDJ-2026", "GJ-2026")) for n in numbers.values())


def test_entry_numbers_cross_fiscal_year_boundary():
    """Test that entry numbers restart when crossing fiscal year end (fye=6)."""
    # Create entries that span fiscal year boundary; fye=6 means FY2026 ends 2026-06-30
    m1 = ManualEntry("je:1", "manual", "GJ", date(2026, 6, 30), "R1", "Before FY end",
                     (Line(C("cash"), debit=D("100")), Line(C("capital"), credit=D("100"))))
    m2 = ManualEntry("je:2", "manual", "GJ", date(2026, 7, 1), "R2", "After FY end",
                     (Line(C("cash"), debit=D("200")), Line(C("capital"), credit=D("200"))))

    inp = BooksInput(company(), CHART, frozenset(default_books(False)), date(2026, 6, 1), date(2026, 7, 31),
                     lines=(), ewt={}, manual=(m1, m2), payments=())
    entries = post_all(inp)[0]

    numbers = entry_numbers(entries, 6)
    # Find the je:1 and je:2 entries in the numbers
    je1_num = next(n for id, n in numbers.items() if "je:1" in id)
    je2_num = next(n for id, n in numbers.items() if "je:2" in id)

    assert je1_num == "GJ-2026-P0001", f"Expected GJ-2026-P0001, got {je1_num}"
    assert je2_num == "GJ-2027-P0001", f"Expected GJ-2027-P0001, got {je2_num}"


def test_pnl_accounts_close_to_equity():
    """Test that P&L accounts from prior fiscal year are closed into retained earnings."""
    # FY2025: sale on Dec 2025
    sale_2025 = sale(gross="10000", vatable="10000", vat="0", doc_date=date(2025, 12, 15), doc_number="SI-2025")

    # FY2026: sale on Feb 2026
    sale_2026 = sale(gross="5000", vatable="5000", vat="0", doc_date=date(2026, 2, 15), doc_number="SI-2026")

    inp = BooksInput(company(), CHART, frozenset(default_books(True)), date(2025, 1, 1), date(2026, 3, 31),
                     lines=(sale_2025, sale_2026), ewt={},
                     manual=())
    entries = post_all(inp)[0]

    # Build for window in FY2026
    tabs = build_books(entries, CHART, date(2026, 1, 1), date(2026, 3, 31), 12, frozenset(default_books(True)), C("retained_earnings"))

    # TB should show FY2026 sales only, with FY2025 sales closed into retained earnings
    tb_rows = {r["code"]: r for r in tabs["TB"]}
    sales_code = C("sales")
    retained_earnings_code = C("retained_earnings")

    # FY2026 TB shows only current year sales (5000)
    assert tb_rows[sales_code]["credit"] == D("5000.00"), f"Expected 5000 sales, got {tb_rows[sales_code]['credit']}"

    # Retained earnings shows prior year sales (10000)
    assert tb_rows[retained_earnings_code]["credit"] == D("10000.00"), f"Expected 10000 retained earnings, got {tb_rows[retained_earnings_code]['credit']}"

    # GL should not have non-zero balance-forward for sales
    gl_rows = [r for r in tabs["GL"] if r["code"] == sales_code]
    assert gl_rows[0]["particulars"] == "Balance brought forward" and gl_rows[0]["balance"] == ZERO

    # TB should balance
    debit, credit = trial_balance_totals(tabs["TB"])
    assert debit == credit


def test_parties_consolidated_by_tin():
    """Test that parties with same name but different TIN get consolidated when possible."""
    # Opening AR line: "Customer" with no TIN
    opening = ManualEntry("o", "opening", "GJ", date(2026, 6, 1), "OB", "Opening",
                          (Line(C("ar"), debit=D("1000"), party_name="Customer"),
                           Line(C("capital"), credit=D("1000"))))

    # Sale: "Customer" with TIN 555666777
    sale_entry = sale(gross="5000", vatable="5000", vat="0", doc_date=date(2026, 7, 1), doc_number="SI-1")
    # Note: sale() sets counterparty_tin="555666777" by default

    inp = BooksInput(company(), CHART, frozenset(default_books(True)), date(2026, 6, 1), date(2026, 8, 31),
                     lines=(sale_entry,), ewt={},
                     manual=(opening,),
                     payments=())
    entries = post_all(inp)[0]

    # Build AR ledger
    tabs = build_books(entries, CHART, date(2026, 7, 1), date(2026, 8, 31), 12, frozenset(default_books(True)), C("retained_earnings"))

    # AR should have one party "Customer" with consolidated balance
    ar_rows = tabs["AR"]
    parties = {r["party"] for r in ar_rows}
    assert parties == {"Customer"}, f"Expected only 'Customer', got {parties}"

    # The opening 1000 (name only) and the 5000 sale (with TIN) are one party: nothing has been collected yet.
    assert [r["key"].split("|")[0] for r in ar_rows] == ["555666777", "555666777"]
    assert ar_rows[-1]["balance"] == D("6000.00")


def _journal_tabs(*manual: ManualEntry):
    inp = BooksInput(company(), CHART, frozenset(default_books(True)), date(2026, 7, 1), date(2026, 9, 30),
                     manual=manual)
    return build_books(post_all(inp)[0], CHART, date(2026, 7, 1), date(2026, 9, 30), 12,
                       frozenset(default_books(True)), C("retained_earnings"))


def test_cash_journal_columns_only_take_lines_on_their_side():
    remit = ManualEntry("r", "manual", "CDJ", date(2026, 8, 10), "0619E", "BIR remittance",
                        (Line(C("ewt_payable"), debit=D("2642.86")), Line(C("bank"), credit=D("2642.86"))))
    refund = ManualEntry("f", "manual", "CRJ", date(2026, 8, 11), "RF-1", "Refund to client",
                         (Line(C("ar"), debit=D("500")), Line(C("cash"), credit=D("500"))))
    tabs = _journal_tabs(remit, refund)
    [cdj] = tabs["CDJ"]
    assert (cdj["bank"], cdj["ewt"], cdj["sundry_dr"], cdj["sundry_cr"]) == (D("2642.86"), ZERO, D("2642.86"), ZERO)
    assert cdj["sundry_account"] == f"{C('ewt_payable')} {CHART.name(C('ewt_payable'))}"
    [crj, crj2] = tabs["CRJ"]
    assert (crj["cash"], crj["ar"]) == (ZERO, ZERO)
    assert crj["sundry_account"].startswith(C("ar")) and crj["sundry_dr"] == D("500.00")
    assert crj2["key"] == "je:f#1" and crj2["sundry_account"].startswith(C("cash")) and crj2["sundry_cr"] == D("500.00")


def test_cash_journal_several_sundry_lines_get_one_row_each():
    paid = ManualEntry("m", "manual", "CDJ", date(2026, 8, 12), "CV-1", "Rent and utilities",
                       (Line(C("doc:rent"), debit=D("1000")), Line(C("doc:utilities"), debit=D("500")),
                        Line(C("cash"), credit=D("1500"))))
    rows = _journal_tabs(paid)["CDJ"]
    assert [r["key"] for r in rows] == ["je:m", "je:m#1"]
    assert rows[0]["cash"] == D("1500.00") and rows[1]["cash"] == ZERO
    assert [(r["sundry_account"].split()[0], r["sundry_dr"]) for r in rows] == [(C("doc:rent"), D("1000.00")),
                                                                                (C("doc:utilities"), D("500.00"))]
