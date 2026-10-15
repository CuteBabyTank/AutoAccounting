"""Year-end close in the books: inventory counts, Q4 / annual income tax, annual payments, contributions (pure)."""

from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, default_books, standard_chart
from app.services.accounting.compute.book_ledgers import balances
from app.services.accounting.compute.books import (
    AnnualTaxes, BooksInput, FiledPayment, Line, ManualEntry, Payment, QuarterTaxes, post_all,
)
from app.services.accounting.compute.engine import build_quarter
from app.services.accounting.compute.inputs import PayrollMonth, PeriodData, PeriodInputs
from tests.aa_factories import company, line, purchase

D = Decimal
CHART = Chart(standard_chart("corporation"))
C = CHART.code


def books(**kw):
    values = dict(company=company(vat_registered=False), chart=CHART, books_kept=frozenset(default_books(False)),
                  start=date(2026, 1, 1), through=date(2026, 12, 31))
    values.update(kw)
    return BooksInput(**values)


def entry(entries, entry_id):
    return next(e for e in entries if e.id == entry_id)


def amounts(e):
    out: dict = {}
    for l in e.lines:
        key = (l.account, "Dr" if l.debit else "Cr")
        out[key] = out.get(key, D("0")) + (l.debit or l.credit)
    return out


def test_inventory_is_set_to_each_quarter_count_through_cost_of_sales():
    opening = ManualEntry("o", "opening", "GJ", date(2026, 1, 1), "OB", "Opening",
                          (Line(C("inventory"), debit=D("10000")), Line(C("capital"), credit=D("10000"))))
    q1 = QuarterTaxes(2026, 1, date(2026, 3, 31), {}, ending_inventory=D("15000"))
    q2 = QuarterTaxes(2026, 2, date(2026, 6, 30), {}, ending_inventory=D("12000"))
    entries, warnings = post_all(books(lines=(purchase(gross="50000", doc_date=date(2026, 2, 1)),),
                                       manual=(opening,), quarters=(q1, q2), through=date(2026, 6, 30)))
    assert amounts(entry(entries, "inv:2026Q1")) == {(C("inventory"), "Dr"): D("5000.00"), (C("cogs"), "Cr"): D("5000.00")}
    assert amounts(entry(entries, "inv:2026Q2")) == {(C("inventory"), "Cr"): D("3000.00"), (C("cogs"), "Dr"): D("3000.00")}
    b = balances(entries, date(2026, 3, 31))
    # cost of sales per books = purchases 50,000 − 5,000 = 10,000 + 50,000 − 15,000, like the returns
    assert (b[C("inventory")], b[C("doc:purchases")] + b[C("cogs")]) == (D("15000.00"), D("45000.00"))
    assert not any("No ending inventory" in w for w in warnings)


def test_a_quarter_without_a_count_warns_and_services_have_no_inventory():
    q1 = QuarterTaxes(2026, 1, date(2026, 3, 31), {})
    entries, warnings = post_all(books(quarters=(q1,), through=date(2026, 3, 31)))
    assert not any(e.id.startswith("inv:") for e in entries)
    assert any("No ending inventory for 2026 Q1" in w for w in warnings)
    _, warnings = post_all(books(company=company(business_type="services"), quarters=(q1,), through=date(2026, 3, 31)))
    assert not any("ending inventory" in w for w in warnings)


def test_q4_income_tax_accrues_from_the_annual_return():
    q3 = QuarterTaxes(2026, 3, date(2026, 9, 30), {"1702Q": {"14": "3000", "S4_5": "0"}})
    annual = AnnualTaxes(2026, date(2026, 12, 31), "1702RT", {"1702RT": {"43": "5000", "49": "400", "47": "300"}})
    entries, _ = post_all(books(company=company(), quarters=(q3,), annual=(annual,)))
    assert amounts(entry(entries, "tax:ITA:2026:accrue")) == {
        (C("income_tax"), "Dr"): D("2000.00"), (C("it_payable"), "Cr"): D("2000.00"),
        (C("it_payable"), "Dr"): D("700.00"), (C("cwt"), "Cr"): D("400.00"), (C("income_tax"), "Cr"): D("300.00")}


def test_annual_accrual_without_quarters_on_the_books_and_for_a_mixed_income_earner():
    rt = AnnualTaxes(2026, date(2026, 12, 31), "1702RT", {"1702RT": {"43": "5000", "44": "100", "46": "1500",
                                                                     "48": "400", "49": "0"}})
    entries, _ = post_all(books(company=company(), annual=(rt,)))
    assert amounts(entry(entries, "tax:ITA:2026:accrue")) == {(C("income_tax"), "Dr"): D("3100.00"),
                                                             (C("it_payable"), "Cr"): D("3100.00")}
    mixed = AnnualTaxes(2026, date(2026, 12, 31), "1701", {"1701": {"P6_5": "180000", "P7_5": "40000"}})
    entries, _ = post_all(books(annual=(mixed,)))
    assert amounts(entry(entries, "tax:ITA:2026:accrue"))[(C("income_tax"), "Dr")] == D("140000.00")


def test_annual_return_payment_is_posted_against_income_tax_payable():
    paid = FiledPayment("1702RT", 2025, 0, date(2026, 4, 14), D("2500.00"))
    entries, _ = post_all(books(filed=(paid,)))
    e = entry(entries, "tax:1702RT:2025Q0:paid")
    assert amounts(e) == {(C("it_payable"), "Dr"): D("2500.00"), (C("bank"), "Cr"): D("2500.00")}
    assert e.particulars == "Payment of BIR 1702RT for FY 2025"


def test_contributions_move_the_employee_share_and_book_the_employer_share():
    pay = line(category="payroll", account="salaries", gross="30000", withholding="2000", doc_date=date(2026, 1, 31))
    q1 = QuarterTaxes(2026, 1, date(2026, 3, 31), {}, contributions=((date(2026, 1, 31), D("1500"), D("3000")),))
    entries, warnings = post_all(books(company=company(business_type="services"), lines=(pay,), quarters=(q1,),
                                       payments=(Payment("p1", pay.id, date(2026, 2, 5), None, "bank", ""),)))
    assert amounts(entry(entries, "contrib:2026-01")) == {
        (C("salaries_payable"), "Dr"): D("1500.00"), (C("contributions_expense"), "Dr"): D("3000.00"),
        (C("contributions_payable"), "Cr"): D("4500.00")}
    assert amounts(entry(entries, "pay:p1"))[(C("bank"), "Cr")] == D("26500.00")  # net pay
    assert balances(entries, date(2026, 12, 31)).get(C("salaries_payable"), D("0")) == D("0")
    assert not warnings


def test_contributions_without_payroll_that_month_warn():
    q1 = QuarterTaxes(2026, 1, date(2026, 3, 31), {}, contributions=((date(2026, 2, 28), D("100"), D("200")),))
    _, warnings = post_all(books(company=company(business_type="services"), quarters=(q1,)))
    assert any("2026-02" in w and "no payroll document" in w for w in warnings)


def test_chart_has_contribution_accounts():
    assert C("contributions_payable") == "2170" and C("contributions_expense") == "6015"


def _payroll_quarter(**month):
    pay = line(category="payroll", account="salaries", gross="30000", withholding="2000", doc_date=date(2026, 1, 31))
    payroll = (PayrollMonth(**month), PayrollMonth(), PayrollMonth())
    return build_quarter(company(business_type="services", has_employees=True),
                         [PeriodData(2026, 1, (pay,), PeriodInputs(payroll=payroll))])


def test_returns_deduct_the_employer_share_and_warn_when_none_is_entered():
    r = _payroll_quarter()
    assert any("no SSS / PhilHealth / Pag-IBIG was entered" in w for w in r.warnings)
    r = _payroll_quarter(contributions=D("1500"), employer_contributions=D("3000"))
    assert r.forms["Expenses"]["contributions"] == D("3000.00")
    assert r.forms["1702Q"]["S2_6"] == D("33000")  # payroll 30,000 + employer share 3,000
    assert not any("no SSS" in w for w in r.warnings)
