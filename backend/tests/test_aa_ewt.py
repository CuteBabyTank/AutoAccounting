from datetime import date
from decimal import Decimal

from app.services.accounting.compute.ewt import (
    ATC_NONE,
    atc_info,
    compute_ewt,
    effective_atc,
    is_corporate_name,
    month_in_quarter,
    rate_percent,
    suggest_atc,
    tax_base,
)
from tests.aa_factories import company, expense, purchase

D = Decimal
AGENT = dict(is_withholding_agent=True)


def test_payee_type_from_name():
    assert is_corporate_name("Cebu Fabric Supply Inc.") and is_corporate_name("ABC CORPORATION")
    assert is_corporate_name("SGV & Co.")
    assert not is_corporate_name("Maria Santos") and not is_corporate_name("")


def test_suggestions_follow_account_payee_and_top_agent():
    c = company(**AGENT)
    assert suggest_atc(expense(account="rent", counterparty_name="Ayala Land Inc."), c) == "WC100"
    assert suggest_atc(expense(account="rent", counterparty_name="Pedro Cruz"), c) == "WI100"
    assert suggest_atc(expense(account="professional_fees", counterparty_name="Atty. Reyes"), c) == "WI010"
    assert suggest_atc(expense(account="professional_fees", counterparty_name="Atty. Reyes",
                               counterparty_vat_registered=True), c) == "WI011"
    assert suggest_atc(expense(account="professional_fees", counterparty_name="SGV & Co."), c) == "WC010"
    assert suggest_atc(expense(account="repairs", counterparty_name="BuildRight Corp"), c) == "WC120"
    assert suggest_atc(expense(account="repairs", counterparty_name="BuildRight Corp", nature="services"), c) == "WC120"
    # Parts or lights bought for upkeep are goods, not a contractor's fee.
    assert suggest_atc(expense(account="repairs", counterparty_name="Ace Hardware Inc.", nature="goods_for_resale"),
                       c) == ""
    assert suggest_atc(purchase(counterparty_name="Cebu Fabric Supply Inc."), c) == ""
    top = company(is_top_withholding_agent=True)
    assert suggest_atc(purchase(counterparty_name="Cebu Fabric Supply Inc."), top) == "WC158"
    assert suggest_atc(expense(account="transportation", counterparty_name="Juan Dela Cruz"), top) == "WI160"
    assert suggest_atc(expense(account="utilities", counterparty_name="Meralco Inc."), top) == ""
    assert suggest_atc(expense(account="repairs", counterparty_name="Ace Hardware Inc.", nature="other"), top) == "WC158"


def test_not_an_agent_withholds_nothing():
    r = compute_ewt([expense(account="rent", gross="10000")], company(), 2026, 3)
    assert r.rows == [] and r.warnings == []


def test_document_choice_overrides_suggestion():
    c = company(**AGENT)
    assert effective_atc(expense(account="rent", ewt_atc=ATC_NONE), c) == ""
    assert effective_atc(expense(account="office_supplies", ewt_atc="wi160"), c) == "WI160"
    assert effective_atc(expense(account="rent", ewt_atc="XX999"), c) == ""
    r = compute_ewt([expense(account="rent", ewt_atc="XX999")], c, 2026, 3)
    assert r.rows == [] and any("fixed rate" in w for w in r.warnings)


def test_tax_base_is_net_of_vat_and_tax_is_base_times_rate():
    l = expense(account="rent", counterparty_name="Ayala Land Inc.", gross="11200", vat="1200", withholding="500",
                doc_date=date(2026, 7, 5))
    assert tax_base(l) == D("10000.00")
    r = compute_ewt([l], company(**AGENT), 2026, 3)
    row = r.rows[0]
    assert (row.atc, row.rate, row.base, row.tax, row.month) == ("WC100", D("0.05"), D("10000.00"), D("500.00"), 1)
    assert r.warnings == []
    assert r.by_line() == {l.id: ("WC100", D("500.00"))}


def test_missing_or_different_withholding_warns_but_reports_computed_tax():
    c = company(**AGENT)
    none = expense(account="rent", gross="10000", doc_date=date(2026, 8, 3))
    off = expense(account="rent", gross="20000", withholding="300", doc_date=date(2026, 9, 3))
    r = compute_ewt([none, off], c, 2026, 3)
    assert [row.tax for row in r.rows] == [D("500.00"), D("1000.00")]
    assert r.month_tax(2) == D("500.00") and r.month_tax(3) == D("1000.00") and r.month_tax(1) == D("0.00")
    assert any("none was withheld" in w for w in r.warnings)
    assert any("differs" in w for w in r.warnings)


def test_withheld_without_atc_warns():
    r = compute_ewt([expense(account="office_supplies", withholding="50")], company(**AGENT), 2026, 3)
    assert r.rows == [] and any("no ATC" in w for w in r.warnings)


def test_month_in_quarter_and_out_of_quarter_dates():
    assert month_in_quarter(date(2026, 7, 31), 2026, 3, 12) == 1
    assert month_in_quarter(date(2026, 9, 1), 2026, 3, 12) == 3
    assert month_in_quarter(date(2026, 10, 1), 2026, 3, 12) is None
    assert month_in_quarter(None, 2026, 3, 12) is None
    assert month_in_quarter(date(2025, 8, 15), 2026, 1, 6) == 2  # June year-end: FY2026 Q1 is Jul–Sep 2025
    r = compute_ewt([expense(account="rent", gross="1000", doc_date=date(2026, 5, 2))], company(**AGENT), 2026, 3)
    assert r.rows[0].month == 3 and any("month 3" in w for w in r.warnings)


def test_rates():
    assert atc_info("WC120") == ("Contractors", D("0.02"))
    assert atc_info("wi158")[1] == D("0.01") and atc_info("nope") is None
    assert rate_percent(D("0.15")) == D("15") and format(rate_percent(D("0.10")), "f") == "10"


def test_surname_co_is_not_a_corporate_marker():
    assert not is_corporate_name("Maria Santos Co") and not is_corporate_name("CO, JAMES")
    assert is_corporate_name("SGV & Co.") and is_corporate_name("Tan Hardware Co.") and is_corporate_name("Lim & Co")
    fee = expense(account="professional_fees", counterparty_name="Maria Santos Co")
    assert suggest_atc(fee, company(is_withholding_agent=True)) == "WI010"


def test_unknown_atc_with_tax_withheld_warns_once():
    r = compute_ewt([expense(account="rent", ewt_atc="WI999", withholding="100")], company(**AGENT), 2026, 3)
    assert len(r.warnings) == 1 and "fixed rate" in r.warnings[0]


def test_credit_memo_reduces_ewt_without_a_mismatch_warning():
    r = compute_ewt([expense(account="rent", gross="-10000", doc_date=date(2026, 7, 9))], company(**AGENT), 2026, 3)
    assert r.month_tax(1) == D("-500.00")
    assert not any("differs" in w or "none was withheld" in w for w in r.warnings)
    assert any("credit" in w for w in r.warnings)
