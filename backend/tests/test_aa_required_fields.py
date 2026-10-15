from dataclasses import asdict

from app.services.accounting.required_fields import missing_fields
from tests.aa_factories import company

FULL = asdict(company(contact_number="09171234567", email="a@b.ph", taxpayer_classification="small",
                      has_employees=True))


def test_complete_company_has_nothing_missing():
    forms = {"2550Q": {}, "1601EQ": {"19": "0.00"}, "1601C-M1": {"14": "50000.00"}}
    assert missing_fields(FULL, forms, forms) == []


def test_identity_fields_in_order():
    c = {**FULL, "tin": "12345", "rdo_code": "", "zip_code": "10", "contact_number": "", "email": ""}
    assert missing_fields(c, ["2551Q"], {}) == ["TIN (9 digits)", "RDO code", "ZIP code", "Contact number",
                                                "Email address"]


def test_old_snapshot_without_new_keys():
    old = {k: v for k, v in FULL.items() if k not in ("contact_number", "email", "taxpayer_classification")}
    assert missing_fields(old, ["2550Q"], {}) == ["Contact number", "Email address", "VAT taxpayer classification"]


def test_classification_only_for_2550q():
    c = {**FULL, "taxpayer_classification": ""}
    assert missing_fields(c, ["2551Q"], {}) == []
    assert missing_fields(c, ["2550Q"], {}) == ["VAT taxpayer classification"]


def test_1601eq_needs_an_atc_when_tax_was_withheld():
    assert missing_fields(FULL, ["1601EQ"], {"1601EQ": {"19": "500.00"}}) == ["1601-EQ ATC schedule"]
    assert missing_fields(FULL, ["1601EQ"], {"1601EQ": {"19": "500.00", "S1_ATC": "WC100"}}) == []


def test_1601c_month_with_no_compensation():
    assert missing_fields(FULL, ["1601C-M2"], {"1601C-M2": {"14": "0.00"}}) == ["Month 2 compensation"]
    no_staff = {**FULL, "has_employees": False}
    assert missing_fields(no_staff, ["1601C-M2"], {"1601C-M2": {"14": "0.00"}}) == []


def test_no_forms_no_check():
    assert missing_fields({}, [], {}) == []
