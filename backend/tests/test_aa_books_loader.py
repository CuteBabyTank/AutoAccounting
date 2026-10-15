# backend/tests/test_aa_books_loader.py
from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, standard_chart
from app.services.accounting.books.loader import (
    _manual, books_warnings, books_window, filed_payments, opening_ppe_warning, tax_periods,
)
from app.services.accounting.compute.inputs import PeriodData, PeriodInputs

D = Decimal
CHART = Chart(standard_chart("corporation"))


def test_filed_payments_read_the_payable_of_the_filed_version_in_manila_time():
    filed = {"2550Q": {"output_id": "o1", "version": 2, "filed_at": "2026-10-24T17:30:00+00:00"},
             "1702RT": {"output_id": "o2", "version": 1, "filed_at": "2026-04-10T01:00:00+00:00"}}
    outputs = {"o1": {"forms": {"2550Q": {"26": "1234.50"}}}}
    [p] = filed_payments([(2026, 3, filed)], outputs)
    assert (p.form, p.year, p.quarter, p.on, p.amount) == ("2550Q", 2026, 3, date(2026, 10, 25), D("1234.50"))


def test_filed_payments_skip_missing_outputs_and_post_the_annual_return():
    assert filed_payments([(2026, 3, {"2550Q": {"output_id": "gone", "version": 1,
                                                "filed_at": "2026-10-20T00:00:00+00:00"}})], {}) == ()
    [p] = filed_payments([(2026, 0, {"1702RT": {"output_id": "o", "version": 1,
                                                "filed_at": "2027-04-10T00:00:00+00:00"}})],
                         {"o": {"forms": {"1702RT": {"21": "5", "51": "2"}}}})
    assert (p.form, p.year, p.quarter, p.on, p.amount) == ("1702RT", 2026, 0, date(2027, 4, 10), D("7.00"))


def test_books_window():
    assert books_window(date(2026, 8, 15), 2026, 3, 12) == (date(2026, 8, 15), date(2026, 9, 30))
    assert books_window(date(2026, 1, 1), 2026, 3, 12) == (date(2026, 7, 1), date(2026, 9, 30))
    assert books_window(date(2026, 10, 1), 2026, 3, 12) is None


def test_books_warnings():
    tb_off = {"TB": [{"key": "~total", "debit": D("10"), "credit": D("9")}], "GL": []}
    warnings = books_warnings(tb_off, PeriodInputs(non_operating_income=D("500")), True, CHART, 4)
    assert any("trial balance doesn't balance" in w for w in warnings)
    assert any("Other income of ₱500.00" in w for w in warnings)
    ok = {"TB": [{"key": "~total", "debit": D("9"), "credit": D("9")}],
          "GL": [{"code": "2170", "credit": D("1"), "debit": D("0")}, {"code": "4100", "credit": D("500"),
                                                                       "debit": D("0")}]}
    assert books_warnings(ok, PeriodInputs(non_operating_income=D("500")), True, CHART, 4) == []


def test_books_leave_contributions_to_the_payroll_inputs():
    tabs = {"TB": [{"key": "~total", "debit": D("9"), "credit": D("9")}], "GL": []}
    for quarter in (1, 2, 3, 4):  # the returns warn when payroll has no contributions entered
        assert books_warnings(tabs, PeriodInputs(), True, CHART, quarter) == []


def test_filed_payments_skip_a_snapshot_without_the_payable_and_a_malformed_filed_at():
    no_item = {"2550Q": {"output_id": "o", "version": 1, "filed_at": "2026-10-20T00:00:00+00:00"}}
    assert filed_payments([(2026, 3, no_item)], {"o": {"forms": {"2550Q": {"31A": "1"}}}}) == ()
    bad_date = {"2550Q": {"output_id": "o", "version": 1, "filed_at": "not a date"}}
    assert filed_payments([(2026, 3, bad_date)], {"o": {"forms": {"2550Q": {"26": "5"}}}}) == ()


def test_tax_periods_start_at_the_fiscal_year_of_books_start():
    periods = [PeriodData(y, q) for y in (2024, 2025, 2026) for q in (1, 2, 3, 4) if (y, q) <= (2026, 3)]
    assert [(periods[i].year, periods[i].quarter) for i in tax_periods(periods, date(2026, 8, 15), 12)] == [
        (2026, 1), (2026, 2), (2026, 3)]
    got = [(periods[i].year, periods[i].quarter) for i in tax_periods(periods, date(2025, 1, 1), 12)]
    assert got[0] == (2025, 1) and len(got) == 7


def test_filed_payments_use_the_paid_on_date_when_given():
    filed = {"2550Q": {"output_id": "o1", "version": 1, "filed_at": "2026-10-28T03:00:00+00:00",
                       "paid_on": "2026-10-24"}}
    [p] = filed_payments([(2026, 3, filed)], {"o1": {"forms": {"2550Q": {"26": "500"}}}})
    assert p.on == date(2026, 10, 24)


def test_filed_payments_of_an_amended_return_add_back_what_the_original_paid():
    filed = {"2550Q": {"output_id": "o2", "version": 2, "filed_at": "2026-11-05T03:00:00+00:00"}}
    [p] = filed_payments([(2026, 3, filed)], {"o2": {"forms": {"2550Q": {"26": "300", "18": "1000"}}}})
    assert p.amount == D("1300.00")


def test_filed_payments_previously_paid_items_per_form():
    snaps = {"2551Q": {"24": "10", "16": "5"}, "1701Q": {"68": "10", "59": "5"}, "1702Q": {"25": "10", "S4_6": "5"},
             "1601EQ": {"31": "10", "22": "5"}, "1601C-M2": {"36": "10", "28": "5"}, "0619E-M1": {"18": "10"}}
    filed = {form: {"output_id": "o", "version": 2, "filed_at": "2026-10-20T00:00:00+00:00"} for form in snaps}
    got = {p.form: p.amount for p in filed_payments([(2026, 3, filed)], {"o": {"forms": snaps}})}
    assert got == {"2551Q": D("15.00"), "1701Q": D("15.00"), "1702Q": D("15.00"), "1601EQ": D("15.00"),
                   "1601C-M2": D("15.00"), "0619E-M1": D("10.00")}


def test_opening_entry_is_dated_books_start_and_manual_entries_keep_their_date():
    from app.models.accounting import AAJournalEntry

    lines = [{"account_code": "1010", "debit": "100", "credit": "0"}, {"account_code": "3100", "debit": "0",
                                                                       "credit": "100"}]
    opening = AAJournalEntry(kind="opening", book="GJ", entry_date=date(2026, 1, 1), reference="OB",
                             particulars="Opening balances", lines=lines)
    assert _manual(opening, date(2026, 8, 15)).on == date(2026, 8, 15)
    manual = AAJournalEntry(kind="manual", book="GJ", entry_date=date(2026, 9, 1), reference="", particulars="",
                            lines=lines)
    assert _manual(manual, date(2026, 8, 15)).on == date(2026, 9, 1)


def test_a_receipt_pays_what_it_shows_net_of_tax_withheld():
    from types import SimpleNamespace as NS
    from app.services.accounting.books.loader import document_payments
    receipt = NS(id="r1", settles_document_id="inv", doc_date=date(2026, 8, 1), gross_amount=D("112000"),
                 withholding_amount=D("2000"), paid_via="bank", doc_number="OR-1")
    invoice = NS(id="inv", paid_on=None, category="sales")
    a_2307 = NS(id="w", paid_on=date(2026, 8, 3), category="2307")
    other = NS(id="bill", paid_on=date(2026, 8, 2), paid_via="", payment_ref="CHK-9", category="expenses")
    by_receipt, direct = document_payments([receipt], [invoice, other, a_2307])
    assert (by_receipt.settles, by_receipt.amount, by_receipt.via) == ("inv", D("110000"), "bank")
    assert (direct.settles, direct.amount, direct.via, direct.ref) == ("bill", None, "cash", "CHK-9")


def test_opening_ppe_outside_the_asset_register_is_flagged():
    from app.services.accounting.compute.books import Line, ManualEntry
    from app.services.accounting.compute.depreciation import Asset

    opening = ManualEntry("o1", "opening", "GJ", date(2026, 7, 1), "", "Opening balances",
                          (Line(CHART.code("ppe"), debit=Decimal("600000")),
                           Line(CHART.code("cash"), debit=Decimal("100000")),
                           Line(CHART.code("retained_earnings"), credit=Decimal("700000"))))
    note = opening_ppe_warning([opening], CHART, [])
    assert note is not None and "₱600,000.00" in note
    carried = Asset("a1", "", "Store fixtures", "Opening", Decimal("600000"), date(2026, 7, 1), 60)
    assert opening_ppe_warning([opening], CHART, [carried]) is None
    bought = Asset("a2", "d1", "Truck", "SI-1", Decimal("600000"), date(2026, 8, 1), 60)
    assert opening_ppe_warning([opening], CHART, [bought]) is not None

