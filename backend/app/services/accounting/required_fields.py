"""What a return still needs before it can be filed (pure; reads a version snapshot)."""

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

_CLASSES = frozenset({"micro", "small", "medium", "large"})


def _amount(values: dict, key: str) -> Decimal:
    try:
        return Decimal(values.get(key) or "0")
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def missing_fields(company: dict, forms: Iterable[str], values: dict[str, dict]) -> list[str]:
    forms = list(forms)
    if not forms:
        return []
    out: list[str] = []

    def need(ok: bool, label: str) -> None:
        if not ok and label not in out:
            out.append(label)

    text = {key: str(company.get(key) or "").strip() for key in
            ("tin", "rdo_code", "registered_name", "address", "zip_code", "contact_number", "email",
             "taxpayer_classification")}
    need(bool(re.fullmatch(r"\d{9}", text["tin"])), "TIN (9 digits)")
    need(bool(re.fullmatch(r"\d{3}", text["rdo_code"])), "RDO code")
    need(bool(text["registered_name"]), "Registered name")
    need(bool(text["address"]), "Registered address")
    need(bool(re.fullmatch(r"\d{4}", text["zip_code"])), "ZIP code")
    need(bool(text["contact_number"]), "Contact number")
    need(bool(text["email"]), "Email address")
    for form in forms:
        form_values = values.get(form, {})
        if form == "2550Q":
            need(text["taxpayer_classification"] in _CLASSES, "VAT taxpayer classification")
        elif form == "1601EQ":
            need(_amount(form_values, "19") <= 0 or bool(form_values.get("S1_ATC")), "1601-EQ ATC schedule")
        elif form.startswith("1601C-M") and company.get("has_employees") and not form_values.get("NO_PAYROLL"):
            need(_amount(form_values, "14") > 0, f"Month {form[-1]} compensation")
    return out
