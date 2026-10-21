from decimal import Decimal

from app.services.accounting.atc_prefs import Automatic, automatic_for, document_pick, rank_picks
from app.services.accounting.compute.atc_tree import decide, withheld_rate
from app.services.accounting.compute.ewt import best_atc, suggest_atc, tree_suggestion
from tests.aa_factories import company, expense, purchase

D = Decimal
AGENT = company(is_withholding_agent=True)
TOP = company(is_top_withholding_agent=True)


def atc(line, top=False):
    return decide(line, top).atc


def test_government_and_taxes_are_never_withheld():
    assert atc(expense(account="other", counterparty_name="CITY GOVERNMENT OF MARIKINA")) == ""
    assert atc(expense(account="taxes_licenses", counterparty_name="Ace Builders Corp.")) == ""
    assert atc(expense(account="rent", counterparty_name="Philippine Ports Authority Bureau")) == ""


def test_rent_from_the_account_or_the_description():
    assert atc(expense(account="rent", counterparty_name="STA. ELENA REALTY CORP.")) == "WC100"
    assert atc(expense(account="other", counterparty_name="Pedro Cruz", description="office space rent, March")) == "WI100"
    assert atc(expense(account="other", counterparty_name="Pedro Cruz", description="rental of backhoe",
                       nature="services")) == "WI100"
    # goods sold by a "Leasing" company are still goods
    assert atc(expense(account="office_supplies", counterparty_name="ABC Leasing Inc.", nature="other")) == ""


def test_professional_tiers_from_vat_and_the_rate_withheld():
    assert atc(expense(account="professional_fees", counterparty_name="Atty. Reyes")) == "WI010"
    assert atc(expense(account="professional_fees", counterparty_name="Atty. Reyes",
                       counterparty_vat_registered=True)) == "WI011"
    assert atc(expense(account="professional_fees", counterparty_name="REYES SANTOS & CO., CPAs")) == "WC010"
    big = expense(account="professional_fees", counterparty_name="SGV & Co.", gross=D("11200"), vat=D("1200"),
                  withholding=D("1500"))
    assert atc(big) == "WC011"


def test_professional_kinds_from_the_payee():
    assert atc(expense(account="other", counterparty_name="Dela Cruz Management Consultants Inc.",
                       nature="services")) == "WC050"
    assert atc(expense(account="professional_fees", counterparty_name="Ana Lim Bookkeeping Services")) == "WI060"
    assert atc(expense(account="other", counterparty_name="FastLane Customs Brokerage Corp.",
                       nature="services")) == "WC139"
    assert atc(expense(account="other", counterparty_name="Dr. Jose Rizal", nature="services")) == "WI010"


def test_contractors_by_name_but_never_for_goods():
    assert atc(expense(account="repairs", counterparty_name="QUICKFIX AIRCON SERVICES", nature="services")) == "WI120"
    assert atc(expense(account="transportation", counterparty_name="PADALA EXPRESS COURIER",
                       nature="services")) == "WI120"
    assert atc(expense(account="representation", counterparty_name="HANDAAN CATERING SERVICES INC.",
                       nature="services")) == "WC120"
    assert atc(expense(account="office_supplies", counterparty_name="KIDLAT PRINTING & XEROX",
                       nature="services")) == "WI120"
    assert atc(expense(account="office_supplies", counterparty_name="KIDLAT PRINTING & XEROX", nature="other")) == ""
    # the toll road's "EXPRESSWAY" isn't a courier, restaurants and fuel aren't contractors
    assert atc(expense(account="transportation", counterparty_name="METRO EXPRESSWAY TOLL CORP.",
                       nature="services")) == ""
    assert atc(expense(account="representation", counterparty_name="KALDERO GRILL & RESTAURANT")) == ""


def test_the_rate_the_supplier_deducted():
    assert withheld_rate(expense(gross=D("33600"), vat=D("3600"), withholding=D("1500"))) == D("0.05")
    assert withheld_rate(expense(gross=D("1000"), withholding=D("20"))) == D("0.02")
    assert withheld_rate(expense(gross=D("1000"), withholding=D("33"))) is None
    two = expense(account="other", counterparty_name="Juan Dela Cruz", nature="services", gross=D("1000"),
                  withholding=D("20"))
    assert atc(two) == "WI120" and atc(two, top=True) == "WI160"
    five = expense(account="other", counterparty_name="Maria Santos", nature="services", gross=D("1000"),
                   withholding=D("50"))
    assert atc(five) == "WI010"


def test_top_withholding_agents_keep_the_goods_and_services_rules():
    assert atc(purchase(counterparty_name="Cebu Fabric Supply Inc."), top=True) == "WC158"
    assert atc(purchase(counterparty_name="Cebu Fabric Supply Inc.")) == ""
    assert atc(expense(account="transportation", counterparty_name="Juan Dela Cruz"), top=True) == "WI160"
    assert atc(expense(account="utilities", counterparty_name="Meralco Inc."), top=True) == ""


def test_every_decision_says_why():
    d = tree_suggestion(expense(account="rent", counterparty_name="Ayala Land Inc."), AGENT)
    assert d.atc == "WC100" and "Rent" in d.reason
    assert tree_suggestion(expense(account="rent"), company()).reason == "The company isn't a withholding agent"


def test_the_returns_keep_the_standard_rules_until_a_hint_is_adopted():
    courier = expense(account="transportation", counterparty_name="PADALA EXPRESS COURIER", nature="services")
    assert tree_suggestion(courier, AGENT).atc == "WI120"
    assert suggest_atc(courier, AGENT) == ""
    assert document_pick(courier, "", AGENT) == ""


def test_document_pick_uses_the_expense_type_default_first():
    rent = expense(account="rent", counterparty_name="Ayala Land Inc.")
    assert document_pick(rent, "", AGENT) == "WC100"
    assert document_pick(rent, "WI100", AGENT) == "WI100"
    assert document_pick(rent, "NONE", AGENT) == ""


def test_rank_picks_orders_the_supplier_documents():
    assert rank_picks([]) == ("", "")
    assert rank_picks([("", "No withholding expected")]) == ("", "No withholding expected")
    picks = [("WC120", "Contractor"), ("WC158", "Goods"), ("WC120", "Contractor"), ("", "x")]
    assert rank_picks(picks) == ("WC120 / WC158", "Contractor (2 of 4 documents)")
    assert rank_picks([("WI100", "Rent"), ("WI100", "Rent")]) == ("WI100", "Rent")


def test_a_hint_only_when_the_tree_disagrees_with_the_returns():
    assert automatic_for(["WC100"], [("WC100", "Rent")]) == Automatic("WC100", best="WC100", best_reason="Rent")
    assert automatic_for(["", ""], [("WI120", "Courier"), ("WI120", "Courier")]) == Automatic(
        "", "WI120", "Courier", "WI120", "Courier")
    assert automatic_for(["WC120"], [("", "Government office")]) == Automatic(
        "WC120", "NONE", "Government office", "NONE", "Government office")
    assert automatic_for(["", ""], [("", "x"), ("", "x")]) == Automatic("", best="NONE", best_reason="x")


def test_best_atc_is_a_picker_choice():
    assert best_atc(expense(account="rent", counterparty_name="Ayala Land Inc."), AGENT).atc == "WC100"
    assert best_atc(expense(account="representation", counterparty_name="KALDERO GRILL"), AGENT).atc == "NONE"
    assert best_atc(expense(account="rent"), company()).atc == ""
    assert best_atc(expense(category="sales", client_role="seller"), AGENT).atc == ""
