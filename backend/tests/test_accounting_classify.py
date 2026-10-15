from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.models.accounting import AADocument
from app.services.accounting.classify import (
    CompanyProfile,
    classify_document,
    empty_document_fields,
    mark_duplicate,
)
from app.services.accounting.extraction import ExtractedDoc, Party

JUAN = CompanyProfile("123456789", "Juan's Cloth Trading", (), True, 12)
CLIENT = Party(name="Juan's Cloth Trading", tin="123456789")
SUPPLIER = Party(name="Cebu Fabric Supply", tin="111222333")


def _ext(**kw) -> ExtractedDoc:
    base = dict(
        document_title="SALES INVOICE", kind="invoice", doc_number="SI-1", doc_date=date(2026, 8, 14),
        seller=SUPPLIER, buyer=CLIENT, seller_vat_registered=True,
        gross_amount=Decimal("1120.00"), vatable_amount=Decimal("1000.00"), vat_amount=Decimal("120.00"),
        nature="raw_materials", expense_account="raw_materials", confidence=90.0,
    )
    base.update(kw)
    return ExtractedDoc(**base)


def test_fields_are_document_columns():
    columns = set(AADocument.__table__.columns.keys())
    assert set(classify_document(_ext(), JUAN, {}, frozenset())) <= columns
    assert set(empty_document_fields(3)) <= columns


def test_valid_purchase_invoice_needs_no_review():
    f = classify_document(_ext(), JUAN, {}, frozenset())
    assert f["category"] == "purchases" and f["account"] == "raw_materials"
    assert f["client_role"] == "buyer"
    assert f["vat_treatment"] == "vatable" and f["input_vat_valid"] is True
    assert f["review_reasons"] == [] and f["needs_review"] is False


def test_sales_invoice_issued_by_client():
    f = classify_document(_ext(seller=CLIENT, buyer=Party(name="Customer")), JUAN, {}, frozenset())
    assert f["category"] == "sales" and f["account"] == "sales" and f["client_role"] == "seller"
    assert f["input_vat_valid"] is None


def test_official_receipt_not_addressed_to_client_loses_input_vat():
    ext = _ext(document_title="OFFICIAL RECEIPT", kind="receipt", buyer=Party(),
               seller=Party(name="Max's Restaurant", tin="222333444"),
               nature="services", expense_account="representation")
    f = classify_document(ext, JUAN, {}, frozenset())
    assert f["category"] == "expenses" and f["account"] == "representation"
    assert f["vat_treatment"] == "no_input_vat" and f["input_vat_valid"] is False
    assert "not_an_invoice" in f["review_reasons"]
    assert "not_addressed_to_client" in f["review_reasons"]
    assert f["needs_review"] is True


def test_vat_math_mismatch_flagged():
    f = classify_document(_ext(vat_amount=Decimal("200.00")), JUAN, {}, frozenset())
    assert "vat_math_mismatch" in f["review_reasons"]


def test_misread_digit_flagged_because_amounts_dont_add_up():
    # Golden Hardware p16: VATable 20,000 read as 2,000 while the total still says 22,600
    f = classify_document(_ext(
        gross_amount=Decimal("22600.00"), vatable_amount=Decimal("2000.00"), vat_amount=Decimal("2600.00"),
    ), JUAN, {}, frozenset())
    assert "amounts_dont_add_up" in f["review_reasons"] and f["needs_review"] is True
    ok = classify_document(_ext(), JUAN, {}, frozenset())
    assert "amounts_dont_add_up" not in ok["review_reasons"]


def test_total_only_and_import_documents_skip_the_sum_check():
    receipt = _ext(vatable_amount=Decimal("0.00"), vat_amount=Decimal("0.00"))
    assert "amounts_dont_add_up" not in classify_document(receipt, JUAN, {}, frozenset())["review_reasons"]
    entry = _ext(kind="import", gross_amount=Decimal("196000.00"), vatable_amount=Decimal("196000.00"),
                 vat_amount=Decimal("23520.00"))
    assert "amounts_dont_add_up" not in classify_document(entry, JUAN, {}, frozenset())["review_reasons"]


def test_vatable_amount_derived_when_missing():
    f = classify_document(_ext(vatable_amount=Decimal("0.00")), JUAN, {}, frozenset())
    assert f["vatable_amount"] == Decimal("1000.00")
    assert "vat_math_mismatch" not in f["review_reasons"]


def test_non_vat_company_skips_input_vat_checks():
    non_vat = CompanyProfile("123456789", "Juan's Cloth Trading", (), False, 12)
    f = classify_document(_ext(document_title="OFFICIAL RECEIPT"), non_vat, {}, frozenset())
    assert "not_an_invoice" not in f["review_reasons"]
    assert f["input_vat_valid"] is None


def test_supplier_rule_overrides_category_and_account():
    rules = {"111222333": ("expenses", "office_supplies")}
    f = classify_document(_ext(), JUAN, rules, frozenset())
    assert (f["category"], f["account"]) == ("expenses", "office_supplies")


def test_other_company_tin_flagged():
    ext = _ext(buyer=Party(name="Maria's Bakery", tin="987654321"))
    f = classify_document(ext, JUAN, {}, frozenset({"987654321"}))
    assert "other_company_tin" in f["review_reasons"]


def test_other_company_tin_flagged_when_client_is_on_neither_side():
    maria = Party(name="Maria's Bakery", tin="987654321")
    ext = _ext(seller=maria, buyer=Party(name="XYZ Cafe", tin="444555666"))
    f = classify_document(ext, JUAN, {}, frozenset({"987654321"}))
    assert "other_company_tin" in f["review_reasons"]


def test_other_company_as_counterparty_is_not_flagged():
    ext = _ext(seller=Party(name="Maria's Bakery", tin="987654321"), buyer=CLIENT)
    f = classify_document(ext, JUAN, {}, frozenset({"987654321"}))
    assert "other_company_tin" not in f["review_reasons"]


def test_low_confidence_and_unreadable_go_to_review_or_unsorted():
    low = classify_document(_ext(confidence=60.0), JUAN, {}, frozenset())
    assert "low_confidence" in low["review_reasons"] and low["category"] == "purchases"
    junk = classify_document(_ext(kind="other", confidence=20.0), JUAN, {}, frozenset())
    assert junk["category"] == "unsorted" and "unsorted" in junk["review_reasons"]


def test_period_follows_document_date_and_fiscal_year():
    june_fye = CompanyProfile("123456789", "Juan's Cloth Trading", (), True, 6)
    f = classify_document(_ext(doc_date=date(2026, 7, 2)), june_fye, {}, frozenset())
    assert (f["period_year"], f["period_quarter"], f["period_month"]) == (2027, 1, 1)
    undated = classify_document(_ext(doc_date=None), JUAN, {}, frozenset())
    assert undated["period_year"] is None and "missing_date" in undated["review_reasons"]


def test_2307_and_payroll_categories():
    f = classify_document(_ext(kind="bir2307", seller=CLIENT, buyer=SUPPLIER), JUAN, {}, frozenset())
    assert (f["category"], f["account"]) == ("2307", "2307_received")
    p = classify_document(_ext(kind="payroll", seller=Party(), nature="payroll"), JUAN, {}, frozenset())
    assert (p["category"], p["account"]) == ("payroll", "salaries")


def test_empty_document_fields():
    f = empty_document_fields(4)
    assert (f["page_start"], f["page_end"]) == (1, 4)
    assert f["category"] == "unsorted" and f["review_reasons"] == ["nothing_extracted"]
    chunk = empty_document_fields(5, page_start=11)
    assert (chunk["page_start"], chunk["page_end"]) == (11, 15)


def test_mark_duplicate_flags_second_copy():
    seen: set[tuple[str, str]] = set()
    first = classify_document(_ext(), JUAN, {}, frozenset())
    second = classify_document(_ext(doc_number="si-1 "), JUAN, {}, frozenset())
    mark_duplicate(first, seen)
    mark_duplicate(second, seen)
    assert "possible_duplicate" not in first["review_reasons"]
    assert "possible_duplicate" in second["review_reasons"] and second["needs_review"] is True


def test_mark_duplicates_returns_new_seen_without_touching_input():
    from app.services.accounting.classify import mark_duplicates

    seen = {("111222333", "OLD-1")}
    rows = [
        classify_document(_ext(doc_number="SI-9"), JUAN, {}, frozenset()),
        classify_document(_ext(doc_number="si-9"), JUAN, {}, frozenset()),
        classify_document(_ext(doc_number="OLD-1"), JUAN, {}, frozenset()),
    ]
    new_seen = mark_duplicates(rows, seen)
    assert seen == {("111222333", "OLD-1")}  # caller's set untouched until the file commits
    assert "possible_duplicate" not in rows[0]["review_reasons"]
    assert "possible_duplicate" in rows[1]["review_reasons"]
    assert "possible_duplicate" in rows[2]["review_reasons"]
    assert ("111222333", "SI-9") in new_seen


def test_tinless_receipts_from_different_sellers_do_not_collide():
    from app.services.accounting.classify import mark_duplicates

    a = classify_document(_ext(seller=Party(name="Max's Restaurant"), doc_number="0042"), JUAN, {}, frozenset())
    b = classify_document(_ext(seller=Party(name="Jollibee Foods"), doc_number="0042"), JUAN, {}, frozenset())
    c = classify_document(_ext(seller=Party(name="MAX'S RESTAURANT"), doc_number="0042"), JUAN, {}, frozenset())
    mark_duplicates([a, b, c], set())
    assert "possible_duplicate" not in b["review_reasons"]
    assert "possible_duplicate" in c["review_reasons"]


def test_statements_and_quotations_are_support_not_review():
    f = classify_document(_ext(kind="statement", document_title="STATEMENT OF ACCOUNT", vat_amount=Decimal("0"),
                               vatable_amount=Decimal("0")), JUAN, {}, frozenset())
    assert f["category"] == "support" and f["review_reasons"] == []


def test_unreadable_documents_stay_unsorted_for_review():
    f = classify_document(_ext(kind="other"), JUAN, {}, frozenset())
    assert f["category"] == "unsorted" and "unsorted" in f["review_reasons"]


def test_purchases_expenses_and_assets_by_nature():
    def acct(**kw):
        f = classify_document(_ext(**kw), JUAN, {}, frozenset())
        return f["category"], f["account"]
    assert acct(nature="goods_for_resale", expense_account="purchases") == ("purchases", "purchases")
    assert acct(nature="raw_materials", expense_account="raw_materials") == ("purchases", "raw_materials")
    assert acct(kind="import", nature="import", expense_account="importation") == ("purchases", "importation")
    assert acct(kind="import", nature="capital_goods", expense_account="capital_goods") == ("purchases", "capital_goods")
    assert acct(nature="capital_goods", expense_account="capital_goods") == ("expenses", "capital_goods")
    assert acct(nature="other", expense_account="utilities") == ("expenses", "utilities")
    assert acct(nature="services", expense_account="professional_fees") == ("expenses", "professional_fees")


def test_own_invoice_is_a_sale_whatever_was_sold():
    f = classify_document(_ext(seller=CLIENT, buyer=SUPPLIER, nature="goods_for_resale"), JUAN, {}, frozenset())
    assert (f["category"], f["account"], f["client_role"]) == ("sales", "sales", "seller")


def test_2307_direction_follows_who_the_client_is():
    received = classify_document(_ext(kind="bir2307", seller=CLIENT, buyer=SUPPLIER), JUAN, {}, frozenset())
    issued = classify_document(_ext(kind="bir2307", seller=SUPPLIER, buyer=CLIENT), JUAN, {}, frozenset())
    assert received["account"] == "2307_received" and issued["account"] == "2307_issued"


def test_vat_on_importation_is_valid_input_vat_without_an_invoice():
    entry = _ext(kind="import", nature="import", document_title="IMPORT ENTRY AND INTERNAL REVENUE DECLARATION",
                 seller=Party(name="Bureau of Customs"), seller_vat_registered=None,
                 gross_amount=Decimal("47600.00"), vatable_amount=Decimal("230000.00"), vat_amount=Decimal("27600.00"))
    f = classify_document(entry, JUAN, {}, frozenset())
    assert f["input_vat_valid"] is True and f["vat_treatment"] == "vatable" and f["review_reasons"] == []
    not_ours = classify_document(replace(entry, buyer=Party(name="Someone Else Corp", tin="999888777")), JUAN, {}, frozenset())
    assert not_ours["input_vat_valid"] is False and "not_addressed_to_client" in not_ours["review_reasons"]


def test_support_papers_never_need_review_for_missing_figures():
    f = classify_document(_ext(kind="statement", doc_date=None, gross_amount=Decimal("0"), vat_amount=Decimal("0"),
                               vatable_amount=Decimal("0")), JUAN, {}, frozenset())
    assert f["category"] == "support" and f["review_reasons"] == []


def test_supplier_rule_that_does_not_fit_the_document_is_flagged_not_applied():
    from app.services.accounting.classify import rule_conflicts

    rules = {"111222333": ("expenses", "repairs")}   # learned from the store's repair job
    lights = classify_document(_ext(nature="goods_for_resale", expense_account="purchases"), JUAN, rules, frozenset())
    assert (lights["category"], lights["account"]) == ("purchases", "purchases")
    assert "supplier_rule_mismatch" in lights["review_reasons"]
    job = classify_document(_ext(nature="services", expense_account="repairs"), JUAN, rules, frozenset())
    assert job["account"] == "repairs" and "supplier_rule_mismatch" not in job["review_reasons"]
    assert rule_conflicts("services", "professional_fees", "purchases") is True
    assert rule_conflicts("", "purchases", "repairs") is False          # nature unknown: the rule applies
    assert rule_conflicts("other", "repairs", "repairs") is False

