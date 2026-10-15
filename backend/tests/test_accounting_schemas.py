from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.accounting import CompanyIn, ConfirmAssignment, DocumentPatch


def test_company_tin_normalised_and_required():
    c = CompanyIn(registered_name="Juan's Cloth Trading", tin="123-456-789-000")
    assert c.tin == "123456789" and c.branch_code == "00000"
    with pytest.raises(ValidationError):
        CompanyIn(registered_name="X", tin="12345")


def test_eight_percent_only_for_individuals():
    with pytest.raises(ValidationError):
        CompanyIn(registered_name="X Corp", tin="123456789", income_tax_option="eight_percent")
    ok = CompanyIn(registered_name="Juan", tin="123456789", taxpayer_type="individual", vat_status="non_vat",
                   income_tax_option="eight_percent")
    assert ok.income_tax_option == "eight_percent"


def test_branch_code_zero_padded():
    assert CompanyIn(registered_name="X", tin="123456789", branch_code="1").branch_code == "00001"


def test_confirm_assignment_needs_exactly_one_target():
    import uuid
    fid = uuid.uuid4()
    with pytest.raises(ValidationError):
        ConfirmAssignment(file_ids=[fid])
    with pytest.raises(ValidationError):
        ConfirmAssignment(file_ids=[fid], company_id=uuid.uuid4(), skip=True)
    assert ConfirmAssignment(file_ids=[fid], skip=True).skip is True


def test_document_patch_period_pair_and_tins():
    with pytest.raises(ValidationError):
        DocumentPatch(period_year=2026)
    p = DocumentPatch(period_year=None, period_quarter=None, seller_tin="111-222-333-000")
    assert {"period_year", "period_quarter"} <= p.model_fields_set
    assert p.seller_tin == "111222333"
    with pytest.raises(ValidationError):
        DocumentPatch(category="nonsense")
    with pytest.raises(ValidationError):
        DocumentPatch(unknown_field=1)


def test_eight_percent_requires_non_vat():
    with pytest.raises(ValidationError):
        CompanyIn(registered_name="Juan", tin="123456789", taxpayer_type="individual", vat_status="vat",
                  income_tax_option="eight_percent")


def test_period_inputs_validation():
    from decimal import Decimal

    from app.schemas.accounting import PeriodInputsModel

    ok = PeriodInputsModel(ending_inventory="5000", prior_taxable_income="-1200.50", cit_rate=20)
    assert ok.ending_inventory == Decimal("5000") and ok.prior_taxable_income == Decimal("-1200.50")
    with pytest.raises(ValidationError):
        PeriodInputsModel(ending_inventory="-1")
    with pytest.raises(ValidationError):
        PeriodInputsModel(cit_rate=30)
    with pytest.raises(ValidationError):
        PeriodInputsModel(vat_withheld="1.234")
    with pytest.raises(ValidationError):
        PeriodInputsModel(unknown=1)


def test_document_patch_ewt_atc():
    assert DocumentPatch(ewt_atc=" wc158 ").ewt_atc == "WC158"
    assert DocumentPatch(ewt_atc="none").ewt_atc == "NONE"
    assert DocumentPatch(ewt_atc="").ewt_atc == ""
    with pytest.raises(ValidationError):
        DocumentPatch(ewt_atc="ZZ999")


def test_period_inputs_payroll_months():
    from app.schemas.accounting import PeriodInputsModel
    from app.services.accounting.compute.inputs import inputs_from_json

    default = PeriodInputsModel()
    assert len(default.payroll) == 3 and default.payroll[0].contributions == Decimal("0")
    ok = PeriodInputsModel(payroll=[{}, {"contributions": "5000", "adjustment": "-25.50"}, {}], ewt_remitted_m1="0")
    assert ok.payroll[1].adjustment == Decimal("-25.50") and ok.ewt_remitted_m1 == Decimal("0")
    assert inputs_from_json(ok.model_dump(mode="json")).payroll[1].contributions == Decimal("5000.00")
    with pytest.raises(ValidationError):
        PeriodInputsModel(payroll=[{}, {}])
    with pytest.raises(ValidationError):
        PeriodInputsModel(payroll=[{"de_minimis": "-1"}, {}, {}])
