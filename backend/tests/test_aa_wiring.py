import uuid
from datetime import date
from decimal import Decimal

from app.models.accounting import AACompany, AADocument
from app.routers.accounting_periods import company_facts, doc_line
from app.services.accounting.schema import column_statements


def _doc(**kw) -> AADocument:
    values = dict(
        id=uuid.uuid4(), client_role="buyer", category="expenses", account="rent", doc_type="invoice",
        doc_number="1", doc_date=date(2026, 7, 1), seller_name="Ayala Land Inc.", seller_tin="111222333",
        seller_address="Makati", seller_vat_registered=True, buyer_name="Juan", buyer_tin="123456789",
        buyer_address="", gross_amount=Decimal("11200.00"), vatable_amount=Decimal("10000.00"),
        vat_amount=Decimal("1200.00"), exempt_amount=Decimal("0.00"), zero_rated_amount=Decimal("0.00"),
        withholding_amount=Decimal("500.00"), input_vat_valid=True, needs_review=False, reviewed=False, ewt_atc="",
    )
    values.update(kw)
    return AADocument(**values)


def test_doc_line_carries_atc_choice_and_supplier_rule():
    plain = doc_line(_doc())
    assert plain.ewt_atc == "" and plain.counterparty_vat_registered is True
    assert doc_line(_doc(), {"111222333": "WC158"}).ewt_atc == "WC158"
    assert doc_line(_doc(ewt_atc="NONE"), {"111222333": "WC158"}).ewt_atc == "NONE"
    sale = doc_line(_doc(client_role="seller", category="sales"), {"123456789": "WC100"})
    assert sale.counterparty_tin == "123456789" and sale.ewt_atc == "" and sale.counterparty_vat_registered is None


def test_company_facts_carry_withholding_flags():
    c = AACompany(registered_name="Juan", tin="123456789", branch_code="00000", rdo_code="030", address="",
                  zip_code="", taxpayer_type="corporation", vat_status="vat", income_tax_option="graduated",
                  deduction_method="itemized", business_type="trading", fiscal_year_end_month=12,
                  is_withholding_agent=True, is_top_withholding_agent=False, has_employees=True)
    facts = company_facts(c)
    assert facts.is_withholding_agent and facts.has_employees and not facts.is_top_withholding_agent


def test_column_migrations_are_additive_and_idempotent():
    statements = column_statements()
    assert all("ADD COLUMN IF NOT EXISTS" in s or "CREATE INDEX IF NOT EXISTS" in s or s.endswith("DROP NOT NULL")
               for s in statements)  # dropping NOT NULL only relaxes a column and is safe to repeat
    assert {s.split()[2] for s in statements if "ADD COLUMN IF NOT EXISTS" in s} == {"aa_documents", "aa_supplier_rules", "aa_companies", "aa_periods"}
    joined = "\n".join(statements)
    for column in ("operations_start_year", "facts_updated_at", "filed_output_id"):
        assert column in joined


def test_effective_document_atc_shows_remembered_or_suggested():
    from app.routers.accounting_periods import effective_document_atc

    agent = AACompany(registered_name="Juan", tin="123456789", branch_code="00000", rdo_code="030", address="",
                      zip_code="", taxpayer_type="corporation", vat_status="vat", income_tax_option="graduated",
                      deduction_method="itemized", business_type="trading", fiscal_year_end_month=12,
                      is_withholding_agent=True, is_top_withholding_agent=False, has_employees=False)
    assert effective_document_atc(_doc(), agent, {}) == "WC100"
    assert effective_document_atc(_doc(), agent, {"111222333": "WC120"}) == "WC120"
    assert effective_document_atc(_doc(ewt_atc="NONE"), agent, {"111222333": "WC120"}) == ""


def test_active_assets_follow_documents():
    from app.services.accounting.assets import asset_defaults, is_asset_document

    assert is_asset_document(_doc(category="expenses", account="capital_goods"))
    assert is_asset_document(_doc(category="purchases", account="capital_goods"))
    assert not is_asset_document(_doc(category="expenses", account="rent"))
    assert not is_asset_document(_doc(category="expenses", account="capital_goods", excluded=True))
    from datetime import datetime, timezone
    assert not is_asset_document(_doc(account="capital_goods", deleted_at=datetime.now(timezone.utc)))
    assert not is_asset_document(_doc(account="capital_goods", client_role="seller"))
    description, cost, in_service = asset_defaults(_doc(account="capital_goods", doc_number="SI-9"), True, 12)
    assert (description, cost, in_service) == ("Ayala Land Inc. SI-9", Decimal("10000.00"), date(2026, 7, 1))
    _, gross_cost, _ = asset_defaults(_doc(account="capital_goods", input_vat_valid=False), True, 12)
    assert gross_cost == Decimal("11200.00")
    undated = _doc(account="capital_goods", doc_date=None, period_year=2026, period_quarter=2)
    assert asset_defaults(undated, True, 12)[2] == date(2026, 4, 1)
    assert asset_defaults(_doc(account="capital_goods", doc_date=None), True, 12) is None


def test_company_facts_carry_operations_start_year():
    c = AACompany(registered_name="Juan", tin="123456789", branch_code="00000", rdo_code="030", address="",
                  zip_code="", taxpayer_type="corporation", vat_status="vat", income_tax_option="graduated",
                  deduction_method="itemized", business_type="trading", fiscal_year_end_month=12,
                  is_withholding_agent=False, is_top_withholding_agent=False, has_employees=False,
                  operations_start_year=2019)
    assert company_facts(c).operations_start_year == 2019


def test_tax_relevant_company_changes():
    from app.routers.accounting import tax_facts_changed

    assert tax_facts_changed({"pinned": True, "aliases": ["X"]}) is False
    assert tax_facts_changed({"deduction_method": "osd"}) is True


def test_books_settings_are_not_tax_facts_but_touch_the_books():
    from app.routers.accounting import books_settings_changed, tax_facts_changed

    for name in ("books_start", "books_kept", "books_signatory", "books_signatory_title"):
        assert tax_facts_changed({name: "x"}) is False
        assert books_settings_changed({name: "x"}) is True
    assert books_settings_changed({"pinned": True, "deduction_method": "osd"}) is False


def test_books_stale_only_when_books_changed_after_the_latest_version():
    from datetime import date, datetime, timezone

    from app.routers.accounting_periods import books_stale

    made = datetime(2026, 10, 1, tzinfo=timezone.utc)
    later = datetime(2026, 10, 2, tzinfo=timezone.utc)
    on = AACompany(books_start=date(2026, 1, 1), books_updated_at=later)
    assert books_stale(on, made) is True
    assert books_stale(on, later) is False
    assert books_stale(on, None) is False
    assert books_stale(AACompany(books_start=None, books_updated_at=later), made) is False
    assert books_stale(AACompany(books_start=date(2026, 1, 1), books_updated_at=None), made) is False
