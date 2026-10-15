from datetime import date
from decimal import Decimal

from app.services.accounting.compute.ewt import compute_ewt
from app.services.accounting.compute.inputs import PayrollMonth, PeriodInputs
from app.services.accounting.compute.withholding import (
    atc_summary,
    build_qap,
    form_0619e,
    form_1601c,
    form_1601eq,
    payroll_months,
)
from tests.aa_factories import company, expense, line

D = Decimal
AGENT = company(is_withholding_agent=True)


def _ewt():
    return compute_ewt([
        expense(account="rent", counterparty_name="Ayala Land Inc.", counterparty_tin="111222333",
                gross="10000", doc_date=date(2026, 7, 5)),
        expense(account="rent", counterparty_name="Ayala Land Inc.", counterparty_tin="111222333",
                gross="10000", doc_date=date(2026, 9, 5)),
        expense(account="professional_fees", counterparty_name="Atty. Reyes", counterparty_tin="444555666",
                gross="20000", doc_date=date(2026, 8, 20)),
    ], AGENT, 2026, 3)


def test_0619e_is_the_month_total():
    f = form_0619e(D("1500"))
    assert f["14"] == f["16"] == f["18"] == D("1500.00") and f["15"] == f["17D"] == D("0.00")


def test_1601eq_schedule_totals_and_remittances():
    ewt = _ewt()
    assert atc_summary(ewt) == [("WC100", D("20000.00"), D("0.05"), D("1000.00")),
                                ("WI010", D("20000.00"), D("0.05"), D("1000.00"))]
    f = form_1601eq(ewt, PeriodInputs())
    assert (f["S1_ATC"], f["S1_BASE"], f["S1_RATE"], f["S1_TAX"]) == ("WC100", D("20000.00"), D("5"), D("1000.00"))
    assert f["S2_ATC"] == "WI010" and "S3_ATC" not in f
    assert f["19"] == D("2000.00")
    assert (f["20"], f["21"]) == (D("500.00"), D("1000.00"))   # computed 0619-E months 1 and 2
    assert f["25"] == D("1500.00") and f["26"] == D("500.00") and f["31"] == D("500.00")


def test_1601eq_uses_amounts_actually_remitted():
    f = form_1601eq(_ewt(), PeriodInputs(ewt_remitted_m1=D("0"), ewt_over_remittance=D("100")))
    assert f["20"] == D("0.00") and f["23"] == D("100.00")
    assert f["26"] == D("900.00")  # 2000 − (0 + 1000 + 100)


def test_qap_one_row_per_payee_and_atc_with_monthly_bases():
    rows = build_qap(_ewt())
    assert [r["name"] for r in rows] == ["Atty. Reyes", "Ayala Land Inc."]
    ayala = rows[1]
    assert ayala["key"] == "111222333|WC100" and ayala["nature"] == "Rentals"
    assert (ayala["m1"], ayala["m2"], ayala["m3"], ayala["base"]) == (D("10000.00"), D("0.00"), D("10000.00"),
                                                                       D("20000.00"))
    assert ayala["rate"] == D("5") and ayala["tax"] == D("1000.00")


def test_1601c_non_taxable_and_withheld():
    month = PayrollMonth(mwe_basic=D("20000"), thirteenth_month=D("5000"), contributions=D("3000"),
                         not_subject=D("12000"), adjustment=D("-50"))
    f = form_1601c(D("100000"), D("6000"), month)
    assert f["21"] == D("28000.00") and f["22"] == D("72000.00") and f["24"] == D("60000.00")
    assert f["25"] == D("6000.00") and f["27"] == D("5950.00") and f["31"] == D("5950.00")
    assert f["36"] == D("5950.00")


def test_payroll_months_counts_out_of_quarter():
    payroll = dict(category="payroll", account="salaries")
    months, outside = payroll_months([
        line(**payroll, gross="50000", withholding="4000", doc_date=date(2026, 7, 31)),
        line(**payroll, gross="50000", withholding="4000", doc_date=date(2026, 8, 31)),
        line(**payroll, gross="10000", withholding="500", doc_date=None),
        expense(gross="999", doc_date=date(2026, 7, 2)),
    ], 2026, 3, 12)
    assert months[1] == (D("50000.00"), D("4000.00"))
    assert months[3] == (D("10000.00"), D("500.00")) and outside == 1


def test_1601eq_prefers_entered_then_filed_then_calculated():
    ewt = _ewt()
    f = form_1601eq(ewt, PeriodInputs(ewt_remitted_m2=D("900")), filed={1: (D("450.00"), 3), 2: (D("1.00"), 3)})
    assert (f["20"], f["_SRC_20"]) == (D("450.00"), "filed:v3")
    assert (f["21"], f["_SRC_21"]) == (D("900.00"), "entered")
    assert f["26"] == D("650.00")   # 2000 − (450 + 900)


def test_1601eq_without_filed_is_calculated():
    f = form_1601eq(_ewt(), PeriodInputs())
    assert (f["_SRC_20"], f["_SRC_21"]) == ("calculated", "calculated")
