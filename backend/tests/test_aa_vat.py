from decimal import Decimal

from app.services.accounting.compute.inputs import PeriodInputs
from app.services.accounting.compute.vat import compute_2550q
from tests.aa_factories import expense, purchase, sale

D = Decimal


def _quarter():
    return [
        sale(vatable="25000", vat="3000", gross="28000"),
        purchase(gross="11200", vatable="10000", vat="1200", input_vat_valid=True, account="raw_materials"),
        expense(gross="2240", vatable="2000", vat="240", input_vat_valid=True, account="transportation"),
        expense(gross="3360", vatable="3000", vat="360", input_vat_valid=True),
        expense(gross="1120", vatable="1000", vat="120", input_vat_valid=False, account="representation"),
    ]


def test_full_return_for_a_typical_quarter():
    r = compute_2550q(_quarter(), PeriodInputs(vat_withheld=D("100")), D("500"))
    i = r.items
    assert (i["31A"], i["31B"], i["34A"], i["34B"], i["37B"]) == (D("25000.00"), D("3000.00"), D("25000.00"), D("3000.00"), D("3000.00"))
    assert (i["38B"], i["43B"]) == (D("500.00"), D("500.00"))
    assert (i["44A"], i["44B"]) == (D("15000.00"), D("1800.00"))
    assert i["48A"] == D("1120.00")  # the receipt that fails input-VAT checks
    assert (i["50A"], i["50B"], i["51B"]) == (D("16120.00"), D("1800.00"), D("2300.00"))
    assert (i["60B"], i["61B"]) == (D("2300.00"), D("700.00"))
    assert (i["15"], i["16"], i["20"], i["21"], i["26"]) == (D("700.00"), D("100.00"), D("100.00"), D("600.00"), D("600.00"))
    assert r.excess_input_vat_out == D("0.00")


def test_excess_input_vat_carries_out():
    lines = [sale(vatable="1000", vat="120"), purchase(gross="5600", vat="600", input_vat_valid=True)]
    r = compute_2550q(lines, PeriodInputs(), D("0"))
    assert r.items["61B"] == D("-480.00") and r.items["26"] == D("-480.00")
    assert r.excess_input_vat_out == D("480.00")


def test_zero_rated_and_exempt_sales_and_ratable_input_tax():
    lines = [
        sale(vatable="60000", vat="7200"),
        sale(zero_rated="20000"),
        sale(exempt="20000"),
        purchase(gross="11200", vat="1200", input_vat_valid=True),
    ]
    i = compute_2550q(lines, PeriodInputs(), D("0")).items
    assert (i["32A"], i["33A"], i["34A"]) == (D("20000.00"), D("20000.00"), D("100000.00"))
    assert i["53B"] == D("240.00")  # 1200 × 20,000 / 100,000
    assert i["60B"] == D("960.00")


def test_importations_payroll_and_2307s():
    lines = [
        purchase(gross="56000", vat="6000", input_vat_valid=True, account="importation", doc_type="import"),
        purchase(gross="9000", input_vat_valid=False, account="importation"),
        expense(category="payroll", account="salaries", gross="50000"),
        sale(category="2307", account="2307_received", gross="10000", withholding="200"),
    ]
    i = compute_2550q(lines, PeriodInputs(), D("0")).items
    assert (i["46A"], i["46B"], i["49A"]) == (D("50000.00"), D("6000.00"), D("9000.00"))
    assert (i["44A"], i["48A"], i["31A"]) == (D("0.00"), D("0.00"), D("0.00"))


def test_all_items_present():
    keys = set(compute_2550q([], PeriodInputs(), D("0")).items)
    expected = {str(n) for n in range(15, 27)} | {"31A", "31B", "32A", "33A", "34A", "34B", "44A", "44B", "45A", "45B",
                                                   "46A", "46B", "47A", "47B", "48A", "49A", "50A", "50B"}
    expected |= {f"{n}B" for n in range(35, 44)} | {f"{n}B" for n in range(51, 62)}
    assert keys == expected


def test_import_entry_reports_the_landed_cost_not_the_duties_paid():
    # An IEIRD's total is what was paid to Customs (duty + VAT); the VAT base is the landed cost.
    entry = purchase(gross="47600", vatable="230000", vat="27600", input_vat_valid=True, account="importation",
                     doc_type="import")
    i = compute_2550q([entry], PeriodInputs(), D("0")).items
    assert (i["46A"], i["46B"]) == (D("230000.00"), D("27600.00"))


def test_uncollected_receivables_and_unpaid_payables_adjust_the_vat():
    inputs = PeriodInputs(uncollected_output_vat=D("600"), recovered_output_vat=D("100"),
                          unpaid_input_vat=D("240"), settled_input_vat=D("40"))
    i = compute_2550q(_quarter(), inputs, D("500")).items
    assert (i["35B"], i["36B"], i["37B"]) == (D("600.00"), D("100.00"), D("2500.00"))
    assert (i["55B"], i["57B"], i["58B"], i["59B"]) == (D("240.00"), D("240.00"), D("40.00"), D("200.00"))
    assert (i["60B"], i["61B"]) == (D("2100.00"), D("400.00"))
