"""Pure Q4 pack regressions; no DB, Gemini or bank reconciliation required."""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from app.routers.accounting_periods import doc_line
from app.services.accounting.classify import CompanyProfile, classify_document, mark_duplicates
from app.services.accounting.extraction import Party, parse_extraction
from app.services.accounting.compute.vat import compute_2550q
from app.services.accounting.compute.inputs import PeriodInputs
from tests.test_accounting_classify import _ext
from tests.test_aa_books_documents import _doc
from tests.test_aa_books_posting import books, amounts, C
from app.services.accounting.compute.books import document_entries

CLIENT = CompanyProfile("123456789", "Juan's Cloth Trading", (), True, 12)


def classify(**kw):
    return classify_document(_ext(**kw), CLIENT, {}, frozenset())


@pytest.mark.parametrize("page,number,total,cash", [
    (20, "0048029", "2992.25", "2000"), (22, "0012151", "1970", "1500"),
    (25, "0128-0442219", "4319", "3000"), (28, "0052607", "3101.75", "3000"),
    (37, "0061504", "2353", "2000"),
])
def test_pack_negative_change_keeps_invoice_total(page, number, total, cash):
    f = classify(page_start=page, doc_number=number, gross_amount=D(total), cash_tendered=D(cash))
    assert "tendered_less_than_total" in f["review_reasons"]
    assert f["gross_amount"] == D(total)


def test_missing_tender_is_not_zero_and_negative_change_is_evidence():
    assert "tendered_less_than_total" not in classify()["review_reasons"]
    assert "tendered_less_than_total" in classify(change_amount=D("-1"))["review_reasons"]
    docs = parse_extraction('{"documents":[{"cash_tendered":0,"change_amount":-2},{}]}')
    assert docs[0].cash_tendered == 0 and docs[0].change_amount == -2
    assert docs[1].cash_tendered is None and docs[1].change_amount is None
    [blank] = parse_extraction('{"documents":[{"cash_tendered":"", "change_amount":"not shown"}]}')
    assert blank.cash_tendered is None and blank.change_amount is None


@pytest.mark.parametrize("supplier,account,atc,tax", [
    ("Reyes Santos & Co., CPAs", "professional_fees", "WC010", "2500"),
    ("Juan Reyes", "professional_fees", "WI010", "1250"),
    ("Sta. Elena Realty Corp.", "rent", "WC100", "1250"),
])
def test_ewt_expected_only_for_agent(supplier, account, atc, tax):
    ext = _ext(seller=Party(name=supplier), expense_account=account, nature="services",
               gross_amount=D("28000"), vatable_amount=D("25000"), vat_amount=D("3000"))
    assert "ewt_expected" not in classify_document(ext, CLIENT, {}, frozenset())["review_reasons"]
    agent = replace(CLIENT, is_withholding_agent=True)
    f = classify_document(ext, agent, {}, frozenset())
    assert "ewt_expected" in f["review_reasons"]
    from app.services.accounting.review import ewt_suggestion
    assert ewt_suggestion(f, True) == (atc, D(tax))
    assert "ewt_expected" not in classify_document(replace(ext, withholding_amount=D(tax)), agent, {}, frozenset())["review_reasons"]


def test_credit_terms_are_advisory_and_released_payroll_needs_source():
    f = classify(payment_terms="Net 30 / PDC")
    assert f["review_reasons"] == ["payment_unverified"] and not f["needs_review"]
    f = classify(page_start=43, kind="payroll", nature="payroll", payment_status="released",
                 doc_date=date(2026, 12, 15), gross_amount=D("120000"), vat_amount=D("0"), vatable_amount=D("0"))
    assert "payment_source_unknown" in f["review_reasons"] and f["needs_review"]


def test_import_unknown_freight_payee_is_flagged():
    assert "payment_source_unknown" in classify(page_start=18, kind="import", gross_amount=D("196000"),
        vatable_amount=D("196000"), vat_amount=D("23520"), payment_source_unknown=True)["review_reasons"]


def test_golden_vat_recomputes_without_inflating_cost_or_changing_printed_amount():
    f = classify(gross_amount=D("22600"), vatable_amount=D("20000"), vat_amount=D("2600"))
    assert f["input_vat_valid"] is True and f["vat_amount"] == D("2600")
    assert "vat_math_mismatch" in f["review_reasons"]
    l = doc_line(_doc(**f))
    assert l.vat == D("2400") and l.vat_difference == D("200")
    [e] = document_entries(l, books(through=date(2026, 12, 31)))
    assert amounts(e) == {(C("doc:raw_materials"), "Dr"): D("20000"),
                          (C("input_vat"), "Dr"): D("2400"),
                          (C("vat_difference"), "Dr"): D("200"), (C("ap"), "Cr"): D("22600")}
    vat = compute_2550q([l], PeriodInputs(), D("0"))
    assert vat.items["44A"] == D("20000") and vat.items["44B"] == D("2400")


@pytest.mark.parametrize("title", ["OFFICIAL RECEIPT", "ACKNOWLEDGEMENT RECEIPT"])
def test_quickfix_parking_and_sari_sari_do_not_claim_vat(title):
    f = classify(document_title=title, kind="receipt")
    assert "not_an_invoice" in f["review_reasons"] and f["input_vat_valid"] is False


def test_owner_personal_purchase_excluded_and_blank_buyer_is_reviewable():
    owner = replace(CLIENT, owner_name="Maria Santos")
    f = classify_document(_ext(buyer=Party(name="Maria Santos")), owner, {}, frozenset())
    assert f["excluded"] and f["account"] == "drawings"
    assert "not_addressed_to_client" in f["review_reasons"]
    blank = classify(buyer=Party())
    assert not blank["excluded"] and "not_addressed_to_client" in blank["review_reasons"]


def test_luzon_5838_duplicate_scan_is_retained_and_flagged():
    f = classify(doc_number="5838", seller=Party(name="Luzon Paint Distributors Corp.", tin="111222333"))
    rows = [dict(f, review_reasons=[]), dict(f, review_reasons=[])]
    mark_duplicates(rows, set())
    assert rows[0]["review_reasons"] == []
    assert rows[1]["review_reasons"] == ["possible_duplicate"]


@pytest.mark.parametrize("category", ["expenses", "purchases"])
def test_included_drawings_post_to_equity_without_tax_deduction(category):
    from tests.aa_factories import company, line
    from app.services.accounting.compute.engine import build_quarter
    from app.services.accounting.compute.inputs import PeriodData
    l = line(category=category, account="drawings", gross="1000", doc_date=date(2026, 12, 15))
    r = build_quarter(company(), [PeriodData(2026, 4, (l,), PeriodInputs(ending_inventory=D("0")))])
    assert r.forms["COGS"]["purchases"] == 0
    assert r.forms["Expenses"]["total_deductions"] == 0
    assert r.forms["2550Q"]["48A"] == 0 and r.ledgers["SLP"] == []
    [e] = document_entries(l, books(through=date(2026, 12, 31)))
    assert amounts(e) == {(C("drawings"), "Dr"): D("1000"), (C("ap"), "Cr"): D("1000")}


def test_owner_name_with_company_tin_is_still_a_business_purchase():
    f = classify_document(_ext(buyer=Party(name="Maria Santos", tin=CLIENT.tin)),
                          replace(CLIENT, owner_name="Maria Santos"), {}, frozenset())
    assert not f["excluded"] and f["account"] != "drawings"


def test_linked_net_of_withholding_receipt_verifies_payment():
    from app.services.accounting.books.links import payment_is_verified
    from types import SimpleNamespace
    invoice = SimpleNamespace(gross_amount=D("33600"), withholding_amount=D("1500"), paid_on=None, paid_via="")
    assert payment_is_verified(invoice, [SimpleNamespace(gross_amount=D("32100"))])
    assert not payment_is_verified(invoice, [SimpleNamespace(gross_amount=D("16050"))])
    assert not payment_is_verified(invoice, [])


@pytest.mark.parametrize("name,number,base,terms", [
    ("Pacific Steel & Cement Supply Inc.", "88548", "143060", "30 days PDC"),
    ("Pacific Steel & Cement Supply Inc.", "89904", "235600", "30 days PDC"),
    ("Luzon Paint Distributors Corp.", "5838", "62580", "Net 15"),
    ("Metro Luzon Electric Company", "EB-7781-2525", "8450", "Net 10"),
    ("Handaan Catering Services Inc.", "HC-1219", "34500", "50% DP, balance on event"),
])
def test_pack_credit_purchases_do_not_block(name, number, base, terms):
    base = D(base)
    f = classify(seller=Party(name=name, tin="111222333"), doc_number=number,
                 vatable_amount=base, vat_amount=base * D("0.12"), gross_amount=base * D("1.12"),
                 payment_terms=terms)
    assert f["review_reasons"] == ["payment_unverified"] and not f["needs_review"]
