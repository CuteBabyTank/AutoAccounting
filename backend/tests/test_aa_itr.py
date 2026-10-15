from decimal import Decimal

from app.services.accounting.compute.deductions import expenses_form, quarter_expenses
from app.services.accounting.compute.inputs import PeriodInputs
from app.services.accounting.compute.itr import (
    PriorOverride, QuarterFigures, compute_1701q, compute_1702q, graduated_tax,
)
from app.services.accounting.compute.pt import compute_2551q
from tests.aa_factories import company, expense, line, sale

D = Decimal


def q(sales="0", cogs="0", deductions="0", nonop="0", cwt="0"):
    return QuarterFigures(D(sales), D(cogs), D(deductions), D(nonop), D(cwt))


def test_graduated_table_2023_onwards():
    assert graduated_tax(D("250000")) == D("0")
    assert graduated_tax(D("400000")) == D("22500")
    assert graduated_tax(D("500000")) == D("42500")
    assert graduated_tax(D("2000000")) == D("402500")
    assert graduated_tax(D("9000000")) == D("2552500")
    assert graduated_tax(D("-5")) == D("0")


def test_2551q_three_percent_of_gross_sales_less_withheld():
    lines = [sale(gross="100000"), sale(gross="50000"), expense(gross="999")]
    i = compute_2551q(lines, PeriodInputs(percentage_tax_withheld=D("300")))
    assert (i["S1_1_ATC"], i["S1_1_TAXABLE"], i["S1_1_DUE"]) == ("PT 010", D("150000.00"), D("4500.00"))
    assert (i["14"], i["15"], i["18"], i["19"], i["24"]) == (D("4500.00"), D("300.00"), D("300.00"), D("4200.00"), D("4200.00"))


def test_1702q_cumulative_with_prior_payments_and_cwt():
    corp = company()
    quarters = [q(sales="1000000", cogs="600000", deductions="100000", cwt="5000"),
                q(sales="800000", cogs="500000", deductions="80000", cwt="4000")]
    i = compute_1702q(quarters, corp, PeriodInputs())
    # Q1: taxable 300,000 → tax 75,000; paid 75,000 − 5,000 = 70,000
    assert (i["S2_1"], i["S2_2"], i["S2_3"], i["S2_5"], i["S2_6"], i["S2_7"]) == (D("800000"), D("500000"), D("300000"), D("300000"), D("80000"), D("220000"))
    assert (i["S2_8"], i["S2_9"], i["S2_10"], i["S2_11"]) == (D("300000"), D("520000"), D("25"), D("130000"))
    assert (i["S4_2"], i["S4_4"], i["S4_5"], i["S4_7"]) == (D("70000"), D("5000"), D("4000"), D("79000"))
    assert (i["14"], i["19"], i["20"], i["25"]) == (D("130000"), D("79000"), D("51000"), D("51000"))


def test_1702q_osd_and_mcit():
    corp = company(deduction_method="osd")
    quarters = [q(sales="1000000", cogs="990000")]
    i = compute_1702q(quarters, corp, PeriodInputs(mcit_applies=True))
    # gross income 10,000; OSD 4,000; taxable 6,000 → RCIT 1,500; MCIT 2% × 10,000 = 200
    assert (i["S2_6"], i["S2_11"], i["S3_6"], i["S2_13"]) == (D("4000"), D("1500"), D("200"), D("1500"))
    loss = compute_1702q([q(sales="1000000", cogs="999000", deductions="50000")], company(), PeriodInputs(mcit_applies=True))
    assert (loss["S2_11"], loss["S3_6"], loss["S2_13"]) == (D("0"), D("20"), D("20"))


def test_1702q_twenty_percent_rate():
    i = compute_1702q([q(sales="100000")], company(), PeriodInputs(cit_rate=20))
    assert (i["S2_10"], i["S2_11"]) == (D("20"), D("20000"))


def test_1701q_graduated_itemized_and_osd():
    person = company(taxpayer_type="individual")
    i = compute_1701q([q(sales="900000", cogs="300000", deductions="100000", cwt="1000")], person, PeriodInputs())
    assert (i["36"], i["37"], i["38"], i["39"], i["41"], i["45"]) == (D("900000"), D("300000"), D("600000"), D("100000"), D("500000"), D("500000"))
    assert (i["46"], i["58"], i["62"], i["63"]) == (D("42500"), D("1000"), D("1000"), D("41500"))
    osd = compute_1701q([q(sales="900000", cogs="300000")], company(taxpayer_type="individual", deduction_method="osd"), PeriodInputs())
    assert (osd["37"], osd["40"], osd["41"]) == (D("0"), D("360000"), D("540000"))


def test_1701q_eight_percent_cumulative():
    person = company(taxpayer_type="individual", vat_registered=False, income_tax_option="eight_percent")
    i = compute_1701q([q(sales="200000"), q(sales="300000", cwt="500")], person, PeriodInputs())
    assert (i["47"], i["49"], i["50"], i["51"], i["52"], i["53"], i["54"]) == (
        D("300000"), D("300000"), D("200000"), D("500000"), D("250000"), D("250000"), D("20000"))
    assert (i["56"], i["58"], i["63"]) == (D("0"), D("500"), D("19500"))


def test_prior_override_replaces_missing_quarters():
    i = compute_1702q([q(sales="100000")], company(), PeriodInputs(),
                      PriorOverride(D("400000"), D("90000"), D("2000")))
    assert (i["S2_8"], i["S2_9"], i["S2_11"]) == (D("400000"), D("500000"), D("125000"))
    assert (i["S4_2"], i["S4_4"], i["20"]) == (D("90000"), D("2000"), D("33000"))


def test_prior_year_excess_credits_reduce_payable():
    i = compute_1702q([q(sales="100000")], company(), PeriodInputs(prior_year_excess_credits=D("5000")))
    assert (i["S4_1"], i["20"]) == (D("5000"), D("20000"))


def test_expenses_with_representation_cap_and_capital_goods():
    lines = [
        expense(gross="1120", vat="120", input_vat_valid=True, account="representation"),
        expense(gross="5000", account="rent"),
        expense(gross="80000", account="capital_goods"),
        line(category="payroll", account="salaries", gross="30000"),
    ]
    b, rep_ytd, allowed_ytd = quarter_expenses(lines, company(), D("0"), D("0"), D("100000"))
    # cap 0.5% × 100,000 = 500 of the 1,000 representation
    assert (b.representation, b.representation_allowed, b.representation_disallowed_ytd) == (D("1000.00"), D("500.00"), D("500.00"))
    assert (b.payroll, b.capital_goods, b.deductions) == (D("30000.00"), D("80000.00"), D("35500.00"))
    assert (rep_ytd, allowed_ytd) == (D("1000.00"), D("500.00"))
    form = expenses_form(b)
    assert form["rent"] == D("5000.00") and form["total_deductions"] == D("35500.00")
    # next quarter: sales YTD grows → more of the earlier representation becomes deductible
    b2, _, allowed2 = quarter_expenses([], company(), rep_ytd, allowed_ytd, D("300000"))
    assert (b2.representation_allowed, allowed2) == (D("500.00"), D("1000.00"))


def test_services_cap_is_one_percent():
    lines = [expense(gross="2000", account="representation")]
    b, _, _ = quarter_expenses(lines, company(business_type="services"), D("0"), D("0"), D("100000"))
    assert b.representation_allowed == D("1000.00")


def test_mcit_base_includes_prior_gross_income():
    i = compute_1702q([q(), q(), q(sales="1000000", cogs="900000")], company(), PeriodInputs(mcit_applies=True),
                      PriorOverride(D("0"), D("0"), D("0"), D("2900000")))
    assert (i["S3_1"], i["S3_3"], i["S3_4"], i["S3_6"]) == (D("2900000"), D("100000"), D("3000000"), D("60000"))


def test_amended_paid_amounts_on_1701q_and_2551q():
    person = company(taxpayer_type="individual", vat_registered=False)
    i = compute_1701q([q(sales="900000", cogs="300000", deductions="100000")], person,
                      PeriodInputs(amended_paid_income_tax=D("2500")))
    assert (i["59"], i["63"]) == (D("2500"), D("40000"))
    pt = compute_2551q([sale(gross="100000")], PeriodInputs(amended_paid_business_tax=D("1000")))
    assert (pt["16"], pt["24"]) == (D("1000.00"), D("2000.00"))


def test_1701q_eight_percent_mixed_income_gets_no_250k_reduction():
    from tests.aa_factories import company as make
    from app.services.accounting.compute.inputs import PeriodInputs
    from app.services.accounting.compute.itr import QuarterFigures, compute_1701q
    q1 = [QuarterFigures(Decimal("500000"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))]
    pure = make(taxpayer_type="individual", vat_registered=False, income_tax_option="eight_percent")
    mixed = make(taxpayer_type="individual", vat_registered=False, income_tax_option="eight_percent",
                 has_compensation_income=True)
    assert compute_1701q(q1, pure, PeriodInputs())["54"] == Decimal("20000")
    f = compute_1701q(q1, mixed, PeriodInputs())
    assert (f["52"], f["54"]) == (Decimal("0"), Decimal("40000"))


def test_create_act_transitional_rates():
    from datetime import date
    from app.services.accounting.compute.itr import graduated_tax, mcit_rate
    from app.services.accounting.compute.pt import pt_rate
    assert mcit_rate(2022) == Decimal("0.01")
    assert mcit_rate(2023) == Decimal("0.015")            # RMC 69-2023: 6 months at 1%, 6 at 2%
    assert mcit_rate(2023, 12, 2) == Decimal("0.01")      # Q2 2023 cumulative: all inside the relief period
    assert mcit_rate(2024) == Decimal("0.02")
    assert mcit_rate(2020) == Decimal("0.015")            # Jul–Dec 2020 at 1%
    assert pt_rate(date(2023, 6, 30)) == Decimal("0.01") and pt_rate(date(2023, 7, 1)) == Decimal("0.03")
    assert graduated_tax(Decimal("1000000"), 2022) == Decimal("190000.00")   # 130,000 + 30% × 200,000
    assert graduated_tax(Decimal("1000000"), 2023) == Decimal("152500.00")   # 102,500 + 25% × 200,000
    assert graduated_tax(Decimal("300000"), 2021) == Decimal("10000.00")
