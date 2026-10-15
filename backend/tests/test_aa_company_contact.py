from dataclasses import asdict

import pytest
from pydantic import ValidationError

from app.models.accounting import AACompany
from app.routers.accounting_periods import company_facts
from app.schemas.accounting import CompanyIn
from app.services.accounting.pdf_returns import header_from_snapshot
from tests.aa_factories import company


def test_facts_carry_contact_fields_into_the_snapshot():
    facts = company(contact_number="09171234567", email="juan@example.com", taxpayer_classification="small")
    snap = asdict(facts)
    assert (snap["contact_number"], snap["email"], snap["taxpayer_classification"]) == (
        "09171234567", "juan@example.com", "small")


def test_company_facts_reads_the_new_columns():
    row = AACompany(registered_name="X", tin="123456789", branch_code="00000", rdo_code="030", address="A",
                    zip_code="1001", taxpayer_type="corporation", vat_status="vat", income_tax_option="graduated",
                    deduction_method="itemized", business_type="trading", fiscal_year_end_month=12,
                    is_withholding_agent=False, is_top_withholding_agent=False, has_employees=False,
                    contact_number="0288881234", email="a@b.ph", taxpayer_classification="micro")
    f = company_facts(row)
    assert (f.contact_number, f.email, f.taxpayer_classification) == ("0288881234", "a@b.ph", "micro")


def test_old_snapshot_without_contact_keys_defaults_to_blank():
    h = header_from_snapshot({"tin": "123456789", "registered_name": "X"}, 2026, 1)
    assert h.contact_number == "" and h.email == ""


def test_company_in_validates_classification():
    base = dict(registered_name="X", tin="123456789")
    assert CompanyIn(**base, taxpayer_classification="medium").taxpayer_classification == "medium"
    assert CompanyIn(**base).taxpayer_classification == ""
    with pytest.raises(ValidationError):
        CompanyIn(**base, taxpayer_classification="huge")
