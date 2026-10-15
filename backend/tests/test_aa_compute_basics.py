from decimal import Decimal

from app.services.accounting.compute.cogs import claims_input_vat, cogs_form, compute_cogs, cost_base
from app.services.accounting.compute.inputs import PeriodInputs, inputs_from_json, inputs_to_json
from app.services.accounting.compute.money import c2, d, peso, total
from tests.aa_factories import company, purchase


def test_rounding_is_half_up():
    assert c2("2.345") == Decimal("2.35")
    assert c2("2.344") == Decimal("2.34")
    assert peso("1234.50") == Decimal("1235")
    assert peso("1234.49") == Decimal("1234")
    assert d(None) == Decimal("0") and d("") == Decimal("0")
    assert total(["1.005", "2"]) == Decimal("3.01")


def test_inputs_round_trip_through_json():
    original = PeriodInputs(ending_inventory=Decimal("5000.00"), vat_withheld=Decimal("120.50"), cit_rate=20,
                            mcit_applies=True, prior_taxable_income=Decimal("0.00"))
    data = inputs_to_json(original)
    assert data["ending_inventory"] == "5000.00" and data["opening_inventory"] is None
    assert inputs_from_json(data) == original


def test_inputs_from_json_ignores_junk():
    parsed = inputs_from_json({"ending_inventory": "", "cit_rate": 30, "vat_withheld": None})
    assert parsed == PeriodInputs()
    assert inputs_from_json(None) == PeriodInputs()


def test_cost_base_excludes_vat_only_when_claimed():
    claimed = purchase(gross="11200", vatable="10000", vat="1200", input_vat_valid=True)
    unclaimed = purchase(gross="1120", vatable="1000", vat="120", input_vat_valid=False)
    assert claims_input_vat(claimed, True) and not claims_input_vat(unclaimed, True)
    assert cost_base(claimed, True) == Decimal("10000.00")
    assert cost_base(unclaimed, True) == Decimal("1120.00")
    assert cost_base(claimed, False) == Decimal("11200.00")  # non-VAT company: VAT is part of cost


def test_trading_cost_of_sales():
    lines = [purchase(gross="11200", vat="1200", input_vat_valid=True), purchase(gross="500")]
    r = compute_cogs(lines, company(), Decimal("2000"), Decimal("3000"))
    assert (r.beginning_inventory, r.purchases, r.ending_inventory, r.cost_of_sales) == (
        Decimal("2000.00"), Decimal("10500.00"), Decimal("3000.00"), Decimal("9500.00"))
    assert r.ending_provided is True
    assert cogs_form(r)["goods_available"] == Decimal("12500.00")


def test_cogs_without_ending_inventory():
    r = compute_cogs([purchase(gross="500")], company(), Decimal("0"), None)
    assert r.ending_provided is False and r.ending_inventory == Decimal("0.00")
    assert r.cost_of_sales == Decimal("500.00")


def test_services_have_no_cost_of_sales():
    r = compute_cogs([purchase(gross="500")], company(business_type="services"), Decimal("100"), None)
    assert r.cost_of_sales == Decimal("0.00") and r.purchases == Decimal("0.00")


def test_withholding_inputs_round_trip():
    from app.services.accounting.compute.inputs import PayrollMonth

    original = PeriodInputs(ewt_remitted_m1=Decimal("500.00"), ewt_over_remittance=Decimal("10.00"),
                            payroll=(PayrollMonth(), PayrollMonth(contributions=Decimal("5000.00"),
                                                                  adjustment=Decimal("-25.00")), PayrollMonth()))
    data = inputs_to_json(original)
    assert data["ewt_remitted_m2"] is None and data["payroll"][1]["contributions"] == "5000.00"
    assert inputs_from_json(data) == original
    assert inputs_from_json({"payroll": [{"de_minimis": "x"}]}).payroll == (PayrollMonth(),) * 3
