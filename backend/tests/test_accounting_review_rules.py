"""Review rules from the Q4 2026 test pack (Bayanihan Hardware Trading Corp.)."""

from datetime import date
from decimal import Decimal

from app.services.accounting.classify import (
    REVIEW_REASONS,
    SOFT_REASONS,
    CompanyProfile,
    classify_document,
    needs_review_for,
)
from app.services.accounting.extraction import ExtractedDoc, Party

BAYANIHAN = CompanyProfile("009876543", "Bayanihan Hardware Trading Corp.", (), True, 12,
                           is_withholding_agent=True, owner_names=("Ramon P. Bayani",))
CLIENT = Party(name="Bayanihan Hardware Trading Corp.", tin="009876543")


def _ext(**kw) -> ExtractedDoc:
    base = dict(
        document_title="SALES INVOICE", kind="invoice", doc_number="1", doc_date=date(2026, 11, 3),
        seller=Party(name="Luzon Paint Supply", tin="111222333"), buyer=CLIENT, seller_vat_registered=True,
        gross_amount=Decimal("11200.00"), vatable_amount=Decimal("10000.00"), vat_amount=Decimal("1200.00"),
        nature="goods_for_resale", expense_account="purchases", confidence=95.0,
    )
    base.update(kw)
    return ExtractedDoc(**base)


def _classify(ext, company=BAYANIHAN):
    return classify_document(ext, company, {}, frozenset())


def test_new_reasons_are_known():
    for reason in ("tendered_less_than_total", "ewt_expected", "payment_source_unknown", "payment_unverified",
                   "duplicate_invoice_number", "personal_purchase"):
        assert reason in REVIEW_REASONS


def test_soft_reason_does_not_need_review():
    assert SOFT_REASONS == frozenset({"payment_unverified"})
    assert needs_review_for(["payment_unverified"]) is False
    assert needs_review_for(["payment_unverified", "low_confidence"]) is True
    assert needs_review_for([]) is False


def test_old_raw_without_new_fields_has_no_new_reasons():
    f = _classify(_ext())
    assert f["review_reasons"] == [] and f["review_notes"] == {} and f["excluded"] is False


def test_tendered_less_than_total_flags_and_keeps_the_total():
    # p20 Tindahan 0048029: cash tendered below the total, negative change
    receipt = _ext(document_title="SALES INVOICE", seller=Party(name="Tindahan ni Aling Nena", tin="222333444"),
                   doc_number="0048029", gross_amount=Decimal("560.00"), vatable_amount=Decimal("500.00"),
                   vat_amount=Decimal("60.00"), cash_tendered=Decimal("500.00"), change_amount=Decimal("-60.00"),
                   nature="other", expense_account="office_supplies")
    f = _classify(receipt)
    assert "tendered_less_than_total" in f["review_reasons"] and f["needs_review"] is True
    assert f["gross_amount"] == Decimal("560.00")
    assert f["review_notes"]["tendered_less_than_total"] == {"tendered": "500.00", "total": "560.00", "change": "-60.00"}
    only_change = _classify(_ext(change_amount=Decimal("-5.00")))
    assert "tendered_less_than_total" in only_change["review_reasons"]
    enough = _classify(_ext(cash_tendered=Decimal("12000.00"), change_amount=Decimal("800.00")))
    assert "tendered_less_than_total" not in enough["review_reasons"]


def test_ewt_expected_on_professional_fees_without_withholding():
    # p11 Reyes Santos RS-1048: professional fees, VAT-registered individual practitioner, no EWT shown
    bill = _ext(seller=Party(name="Reyes Santos Law Office", tin="333444555"), doc_number="RS-1048",
                gross_amount=Decimal("33600.00"), vatable_amount=Decimal("30000.00"), vat_amount=Decimal("3600.00"),
                nature="services", expense_account="professional_fees")
    f = _classify(bill)
    assert "ewt_expected" in f["review_reasons"]
    assert f["review_notes"]["ewt_expected"] == {"atc": "WI011", "rate": "10", "base": "30000.00", "amount": "3000.00"}
    withheld = _classify(_ext(**{**bill.__dict__, "withholding_amount": Decimal("3000.00")}))
    assert "ewt_expected" not in withheld["review_reasons"]
    not_agent = CompanyProfile(CLIENT.tin, CLIENT.name, (), True, 12)
    assert "ewt_expected" not in _classify(bill, not_agent)["review_reasons"]


def test_ewt_expected_on_corporate_rent():
    rent = _ext(seller=Party(name="Sta. Elena Realty Corp.", tin="444555666"), gross_amount=Decimal("33600.00"),
                vatable_amount=Decimal("30000.00"), vat_amount=Decimal("3600.00"), nature="services",
                expense_account="rent")
    f = _classify(rent)
    assert f["review_notes"]["ewt_expected"] == {"atc": "WC100", "rate": "5", "base": "30000.00", "amount": "1500.00"}


def test_payment_source_unknown_on_released_payroll():
    # p43: 13th month pay ₱120,000 marked released on 12/15, nothing shows where the cash came from
    payroll = _ext(kind="payroll", document_title="13TH MONTH PAY REGISTER", seller=Party(), nature="payroll",
                   expense_account="salaries", gross_amount=Decimal("120000.00"), vatable_amount=Decimal("0"),
                   vat_amount=Decimal("0"), doc_date=date(2026, 12, 15), marked_paid=True)
    f = _classify(payroll)
    assert f["category"] == "payroll" and "payment_source_unknown" in f["review_reasons"] and f["needs_review"]
    unpaid = _classify(_ext(**{**payroll.__dict__, "marked_paid": False}))
    assert "payment_source_unknown" not in unpaid["review_reasons"]


def test_payment_unverified_is_soft():
    # Pacific Steel on credit terms: no payment evidence yet, shown but never blocking
    f = _classify(_ext(seller=Party(name="Pacific Steel Corp.", tin="555666777"), payment_terms="credit"))
    assert f["review_reasons"] == ["payment_unverified"] and f["needs_review"] is False
    cash = _classify(_ext(payment_terms="cash"))
    assert "payment_unverified" not in cash["review_reasons"]


def test_golden_hardware_vat_mismatch_keeps_input_vat_at_twelve_percent():
    # p16 Golden Hardware: VAT ₱2,600 printed on ₱20,000 (should be ₱2,400)
    golden = _ext(seller=Party(name="Golden Hardware Depot", tin="666777888"), gross_amount=Decimal("22600.00"),
                  vatable_amount=Decimal("20000.00"), vat_amount=Decimal("2600.00"))
    f = _classify(golden)
    assert "vat_math_mismatch" in f["review_reasons"]
    assert f["input_vat_valid"] is True and f["vat_treatment"] == "vatable"
    assert f["review_notes"]["vat_math_mismatch"] == {"expected": "2400.00", "difference": "200.00"}
    receipt = _classify(_ext(**{**golden.__dict__, "document_title": "OFFICIAL RECEIPT"}))
    assert receipt["input_vat_valid"] is False   # other input-VAT issues still disallow it


def test_personal_purchase_in_owners_name_is_excluded():
    # p38: purchase receipt made out to the owner personally
    personal = _ext(buyer=Party(name="RAMON P. BAYANI"), seller=Party(name="SM Appliance Center", tin="777888999"),
                    nature="other", expense_account="other")
    f = _classify(personal)
    assert {"not_addressed_to_client", "personal_purchase"} <= set(f["review_reasons"])
    assert f["excluded"] is True and f["needs_review"] is True
    blank = _classify(_ext(buyer=Party(), nature="other", expense_account="other"))  # p21: buyer block blank
    assert "personal_purchase" not in blank["review_reasons"] and blank["excluded"] is False


# --- VAT difference posting (p16 Golden Hardware) -------------------------------------------------

def _golden_line(vat="2600"):
    from tests.aa_factories import purchase
    return purchase(gross=str(20000 + int(vat)), vatable="20000", vat=vat, input_vat_valid=True,
                    counterparty_name="Golden Hardware Depot")


def test_golden_purchase_posts_the_excess_vat_to_vat_difference():
    from app.services.accounting.books.chart import Chart, default_books, standard_chart
    from app.services.accounting.compute.books import BooksInput, document_entries
    from tests.aa_factories import company

    chart = Chart(standard_chart("corporation"))
    assert chart.get(chart.code("vat_difference")).name == "VAT difference - for review"
    inp = BooksInput(company=company(), chart=chart, books_kept=frozenset(default_books(True)),
                     start=date(2026, 1, 1), through=date(2026, 12, 31))
    [e] = document_entries(_golden_line(), inp)
    got = {(l.account, "Dr" if l.debit else "Cr"): l.debit or l.credit for l in e.lines}
    assert got == {(chart.code("doc:purchases"), "Dr"): Decimal("20000.00"),
                   (chart.code("input_vat"), "Dr"): Decimal("2400.00"),
                   (chart.code("vat_difference"), "Dr"): Decimal("200.00"),
                   (chart.code("ap"), "Cr"): Decimal("22600.00")}


def test_golden_purchase_claims_twelve_percent_on_the_2550q():
    from app.services.accounting.compute.inputs import PeriodInputs
    from app.services.accounting.compute.vat import compute_2550q

    i = compute_2550q([_golden_line()], PeriodInputs(), Decimal("0")).items
    assert i["44A"] == Decimal("20000.00") and i["44B"] == Decimal("2400.00")


def test_vat_below_twelve_percent_claims_printed_vat():
    from app.services.accounting.compute.cogs import claimed_input_vat, vat_difference

    low = _golden_line(vat="2200")
    assert claimed_input_vat(low, True) == Decimal("2200.00") and vat_difference(low, True) == Decimal("0.00")
    assert claimed_input_vat(_golden_line(vat="2400"), True) == Decimal("2400.00")
    assert claimed_input_vat(_golden_line(), False) == Decimal("0.00")


def test_charts_seeded_before_vat_difference_get_it():
    from app.services.accounting.books.chart import missing_standard, standard_chart

    old = [a for a in standard_chart("corporation") if a.system_key != "vat_difference"]
    assert [a.code for a in missing_standard(old, "corporation")] == ["1310"]
