from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.due_dates import due_dates, quarter_end, quarter_start
from app.services.accounting.compute.engine import build_quarter
from app.services.accounting.compute.inputs import PeriodData, PeriodInputs
from app.services.accounting.compute.specs import form_items
from tests.aa_factories import company, expense, line, purchase, sale

D = Decimal


def P(year, quarter, *lines, **inputs):
    return PeriodData(year, quarter, tuple(lines), PeriodInputs(**inputs))


def test_vat_corporation_quarter_has_all_forms_and_ledgers():
    r = build_quarter(company(), [P(2026, 1, sale(vatable="100000", vat="12000", gross="112000"),
                                    purchase(gross="56000", vat="6000", input_vat_valid=True),
                                    opening_inventory=D("0"), ending_inventory=D("10000"))])
    assert set(r.forms) == {"2550Q", "1702Q", "COGS", "Expenses"}
    assert set(r.ledgers) == {"Transactions", "SLS", "SLP"}
    assert r.forms["COGS"]["cost_of_sales"] == D("40000.00")
    assert (r.forms["1702Q"]["S2_1"], r.forms["1702Q"]["S2_2"]) == (D("100000"), D("40000"))
    assert r.forms["2550Q"]["26"] == D("6000.00")
    assert r.warnings == [] and r.review_open == 0


def test_vat_excess_chains_into_next_quarter():
    periods = [P(2026, 1, sale(vatable="1000", vat="120"), purchase(gross="5600", vat="600", input_vat_valid=True),
                 opening_inventory=D("0"), ending_inventory=D("0")),
               P(2026, 2, sale(vatable="10000", vat="1200"), ending_inventory=D("0"))]
    r = build_quarter(company(), periods)
    assert r.forms["2550Q"]["38B"] == D("480.00") and r.forms["2550Q"]["61B"] == D("720.00")
    assert r.carry_out["excess_input_vat"] == D("0.00")


def test_inventory_chains_between_quarters():
    periods = [P(2026, 1, sale(vatable="1"), opening_inventory=D("0"), ending_inventory=D("3000")),
               P(2026, 2, purchase(gross="5000"), ending_inventory=D("1000"))]
    cogs = build_quarter(company(), periods).forms["COGS"]
    assert (cogs["beginning_inventory"], cogs["purchases"], cogs["cost_of_sales"]) == (D("3000.00"), D("5000.00"), D("7000.00"))


def test_missing_ending_inventory_warns():
    r = build_quarter(company(), [P(2026, 1, purchase(gross="500"), opening_inventory=D("0"))])
    assert any(w.startswith("Ending inventory was not provided") for w in r.warnings)


def test_missing_earlier_quarters_warn():
    r = build_quarter(company(), [P(2026, 3, sale(vatable="1000"), opening_inventory=D("0"), ending_inventory=D("0"))])
    assert any(w.startswith("No documents for Q1, Q2 of 2026") for w in r.warnings)


def test_prior_override_used_for_mid_year_start():
    r = build_quarter(company(), [P(2026, 3, sale(vatable="100000"), opening_inventory=D("0"), ending_inventory=D("0"),
                                    prior_taxable_income=D("200000"), prior_tax_paid=D("50000"))])
    assert r.forms["1702Q"]["S2_8"] == D("200000") and r.forms["1702Q"]["S4_2"] == D("50000")
    assert not any(w.startswith("No documents for") for w in r.warnings)


def test_eight_percent_individual_files_only_1701q():
    person = company(taxpayer_type="individual", vat_registered=False, income_tax_option="eight_percent",
                     business_type="services")
    r = build_quarter(person, [P(2026, 1, sale(gross="300000"))])
    assert set(r.forms) == {"1701Q", "Expenses"} and set(r.ledgers) == {"Transactions"}
    assert r.forms["1701Q"]["54"] == D("4000")


def test_non_vat_corporation_files_2551q():
    r = build_quarter(company(vat_registered=False, business_type="services"), [P(2026, 1, sale(gross="100000"))])
    assert {"2551Q", "1702Q"} <= set(r.forms) and "2550Q" not in r.forms


def test_q4_has_no_quarterly_income_tax_return():
    r = build_quarter(company(business_type="services"), [P(2026, 4, sale(vatable="1000"))])
    assert "1702Q" not in r.forms
    assert any(w.startswith("Q4 has no quarterly income tax return") for w in r.warnings)


def test_draft_and_unsorted_warnings():
    lines = [sale(vatable="1000", open_review=True), line(category="unsorted")]
    r = build_quarter(company(business_type="services"), [P(2026, 1, *lines)])
    assert r.review_open == 1 and r.warnings[0].startswith("1 document(s) in this quarter still need review")
    assert any(w.startswith("1 unsorted document(s) were left out") for w in r.warnings)


def test_2307s_feed_sawt_and_income_tax_credit():
    cert = sale(category="2307", account="2307_received", gross="50000", withholding="1000",
                counterparty_name="Payor Inc", counterparty_tin="999888777")
    r = build_quarter(company(business_type="services"), [P(2026, 1, sale(vatable="50000"), cert)])
    assert r.ledgers["SAWT"] == [{"key": cert.id, "doc_date": "2026-08-01", "tin": "999888777", "name": "Payor Inc",
                                  "income_payment": D("50000.00"), "tax_withheld": D("1000.00")}]
    assert r.forms["1702Q"]["S4_5"] == D("1000")
    assert any("VAT withheld" in w for w in r.warnings)


def test_sls_and_slp_group_by_counterparty():
    lines = [sale(vatable="1000", counterparty_tin="555666777"), sale(vatable="2000", counterparty_tin="555666777"),
             purchase(gross="11200", vat="1200", input_vat_valid=True, counterparty_tin="111"),
             expense(gross="5600", vat="600", input_vat_valid=True, account="rent", counterparty_tin="222"),
             expense(gross="300", input_vat_valid=False, counterparty_tin="333", counterparty_name="Sari-sari")]
    r = build_quarter(company(business_type="services"), [P(2026, 1, *lines)])
    [sls] = r.ledgers["SLS"]
    assert (sls["taxable"], sls["output_tax"], sls["gross_sales"]) == (D("3000.00"), D("360.00"), D("3000.00"))
    slp = {row["key"]: row for row in r.ledgers["SLP"]}
    assert (slp["111"]["other_goods"], slp["111"]["input_tax"]) == (D("10000.00"), D("1200.00"))
    assert slp["222"]["services"] == D("5000.00")
    assert (slp["333"]["exempt"], slp["333"]["input_tax"]) == (D("300.00"), D("0.00"))


def test_quarter_bounds_and_due_dates_roll_off_weekends():
    assert (quarter_start(2026, 3, 12), quarter_end(2026, 3, 12)) == (date(2026, 7, 1), date(2026, 9, 30))
    assert (quarter_start(2027, 1, 6), quarter_end(2027, 1, 6)) == (date(2026, 7, 1), date(2026, 9, 30))
    due = due_dates(["2550Q", "1702Q", "1701Q", "2551Q"], 2026, 3, 12)
    assert due["2550Q"] == date(2026, 10, 26)   # Oct 25 is a Sunday
    assert due["2551Q"] == date(2026, 10, 26)
    assert due["1702Q"] == date(2026, 12, 1)    # 60 days → Sun Nov 29; Mon Nov 30 is Bonifacio Day
    assert due["1701Q"] == date(2026, 11, 16)   # Nov 15 is a Sunday


def test_form_items_follow_spec_order_and_skip_absent_keys():
    items = form_items("2550Q", {"26": D("1"), "31A": D("2")})
    assert [k for k, _ in items] == ["31A", "26"]
    exp = form_items("Expenses", {"rent": D("1"), "total_deductions": D("1")})
    assert exp == [("rent", "Rent"), ("total_deductions", "Total deductions this quarter")]


def test_expected_forms_match_taxpayer_profile():
    from app.services.accounting.compute.engine import expected_forms

    assert expected_forms(company(), 3) == ["2550Q", "1702Q"]
    assert expected_forms(company(), 4) == ["2550Q"]
    assert expected_forms(company(vat_registered=False), 1) == ["2551Q", "1702Q"]
    eight = company(taxpayer_type="individual", vat_registered=False, income_tax_option="eight_percent")
    assert expected_forms(eight, 2) == ["1701Q"]


def test_opening_inventory_after_missing_ending_is_not_double_counted():
    periods = [P(2026, 1, purchase(gross="100000"), opening_inventory=D("0")),
               P(2026, 2, purchase(gross="50000"), opening_inventory=D("60000"), ending_inventory=D("70000"))]
    form = build_quarter(company(), periods).forms["1702Q"]
    # Q1 cost of sales is 0 + 100,000 − 60,000 (Q2's opening is Q1's closing stock)
    assert (form["S2_2"], form["S2_8"]) == (D("40000"), D("-40000"))


def test_mcit_with_prior_totals_but_no_gross_warns():
    r = build_quarter(company(), [P(2026, 3, sale(vatable="1000"), opening_inventory=D("0"), ending_inventory=D("0"),
                                    prior_taxable_income=D("0"), mcit_applies=True)])
    assert any(w.startswith("MCIT needs earlier quarters' gross income") for w in r.warnings)


def test_vat_sale_without_split_uses_total_less_vat():
    r = build_quarter(company(business_type="services"), [P(2026, 1, sale(gross="112000", vat="12000"))])
    assert r.forms["2550Q"]["31A"] == D("100000.00") and r.forms["1702Q"]["S2_1"] == D("100000")


def test_vat_sale_with_no_split_and_no_vat_warns_and_counts_for_income_tax():
    r = build_quarter(company(business_type="services"), [P(2026, 1, sale(gross="50000"))])
    assert r.forms["2550Q"]["31A"] == D("0.00") and r.forms["1702Q"]["S2_1"] == D("50000")
    assert any(w.startswith("1 sales document(s) have a total but no VATable") for w in r.warnings)


def test_services_purchases_are_deducted():
    r = build_quarter(company(business_type="services"), [P(2026, 1, sale(vatable="300000"), purchase(gross="200000"))])
    assert r.forms["Expenses"]["purchases"] == D("200000.00") and r.forms["1702Q"]["S2_6"] == D("200000")


def test_opening_excess_vat_entered_on_a_later_quarter_is_used():
    periods = [P(2026, 1, sale(vatable="1", vat="0.12")),
               P(2026, 2, sale(vatable="10000", vat="1200"), opening_excess_input_vat=D("500"))]
    assert build_quarter(company(business_type="services"), periods).forms["2550Q"]["38B"] == D("500.00")


def test_amended_return_credits_what_the_original_paid():
    r = build_quarter(company(business_type="services"),
                      [P(2026, 1, sale(vatable="100000", vat="12000"), amended_paid_business_tax=D("5000"),
                         amended_paid_income_tax=D("1000"))], amended=True)
    assert (r.forms["2550Q"]["18"], r.forms["2550Q"]["21"]) == (D("5000.00"), D("7000.00"))
    assert (r.forms["1702Q"]["S4_6"], r.forms["1702Q"]["20"]) == (D("1000"), D("24000"))
    assert not any("amended return" in w for w in r.warnings)
    bare = build_quarter(company(business_type="services"), [P(2026, 1, sale(vatable="100000"))], amended=True)
    assert any(w.startswith("This is an amended return") for w in bare.warnings)


def _machine(cost="60000", in_service=date(2026, 1, 15), life=60):
    from app.services.accounting.compute.depreciation import Asset

    return Asset("a1", "d1", "Sewing machine", "SI-9", D(cost), in_service, life)


def test_quarter_depreciation_reduces_itemized_income():
    periods = [P(2026, 1), P(2026, 2, sale(vatable="100000"), opening_inventory=D("0"), ending_inventory=D("0"))]
    plain = build_quarter(company(business_type="services"), periods)
    with_asset = build_quarter(company(business_type="services"), periods, assets=[_machine()])
    # Q1 + Q2 = 6 months × 1,000
    assert plain.forms["1702Q"]["S2_9"] - with_asset.forms["1702Q"]["S2_9"] == D("6000")
    assert with_asset.forms["Expenses"]["depreciation"] == D("3000.00")
    assert with_asset.forms["Expenses"]["total_deductions"] == D("3000.00")


def test_capital_goods_purchases_stay_out_of_cogs():
    r = build_quarter(company(), [P(2026, 1, purchase(gross="5000"), purchase(gross="80000", account="capital_goods"),
                                    opening_inventory=D("0"), ending_inventory=D("0"))])
    assert r.forms["COGS"]["purchases"] == D("5000.00")
    assert any("asset register" in w for w in r.warnings)
    assert not any("depreciation is not computed" in w for w in r.warnings)


def test_mcit_follows_the_company_start_year_over_the_quarter_input():
    period = P(2026, 1, sale(vatable="1000000"), opening_inventory=D("0"), ending_inventory=D("0"), mcit_applies=False)
    started_2020 = build_quarter(company(operations_start_year=2020), [period]).forms["1702Q"]
    assert started_2020["S3_6"] == D("20000")  # 2% of ₱1,000,000 gross income: the 6th year, MCIT applies
    started_2024 = build_quarter(company(operations_start_year=2024), [replace(period, inputs=PeriodInputs(
        opening_inventory=D("0"), ending_inventory=D("0"), mcit_applies=True))]).forms["1702Q"]
    assert started_2024["S3_6"] == D("0")  # still inside the first three years


def test_non_vat_sales_above_three_million_warn_to_register_for_vat():
    eight = company(taxpayer_type="individual", vat_registered=False, income_tax_option="eight_percent",
                    business_type="services")
    r = build_quarter(eight, [P(2026, 1, sale(gross="2000000")), P(2026, 2, sale(gross="1500000"))])
    assert any("above the ₱3,000,000 VAT threshold" in w and "graduated rates" in w for w in r.warnings)
    r = build_quarter(eight, [P(2026, 1, sale(gross="2000000"))])
    assert not any("VAT threshold" in w for w in r.warnings)


def test_due_dates_skip_philippine_holidays():
    from app.services.accounting.compute.due_dates import _easter, annual_due_date, ph_holidays
    assert _easter(2026) == date(2026, 4, 5) and _easter(2025) == date(2025, 4, 20)
    assert date(2025, 4, 17) in ph_holidays(2025) and date(2025, 4, 18) in ph_holidays(2025)  # Holy Week
    assert date(2026, 8, 31) in ph_holidays(2026)                                             # National Heroes Day
    # FY ending Dec 2024: 1701 due Apr 15, 2025 (a Tuesday, not in Holy Week)
    assert annual_due_date("1701", 2024) == date(2025, 4, 15)
    # 1601-C for November 2026 is due Dec 10 (Thursday): unchanged; 2550-Q FYE-Sept Q1 → Jan 25, 2027 (Mon)
    assert due_dates(["1601C-M2"], 2026, 4, 12)["1601C-M2"] == date(2026, 12, 10)
    # Q2 2026 1601-EQ: Jul 31 Friday, a working day
    assert due_dates(["1601EQ"], 2026, 2, 12)["1601EQ"] == date(2026, 7, 31)
    # Q3 2023 1601-EQ: Oct 31 2023 is a Tuesday, Nov 1–2 are holidays → stays Oct 31; Q4 2025 1601-C M3 Jan 15 2026
    assert due_dates(["1601C-M3"], 2025, 4, 12)["1601C-M3"] == date(2026, 1, 15)
    # Dec 2024 0619-E style monthly due on Jan 1 would roll: a holiday on the 1st, 2027-01-01 is Friday → Jan 4
    from app.services.accounting.compute.due_dates import _next_business_day
    assert _next_business_day(date(2027, 1, 1)) == date(2027, 1, 4)
    assert _next_business_day(date(2026, 6, 12)) == date(2026, 6, 15)  # Independence Day (Fri) → Mon
