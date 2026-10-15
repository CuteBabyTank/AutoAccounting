"""Builders for AutoAccounting computation tests."""

from datetime import date
from decimal import Decimal

from app.services.accounting.compute.inputs import CompanyFacts, DocLine

_MONEY = ("gross", "vatable", "vat", "exempt", "zero_rated", "withholding")
_counter = iter(range(1, 1_000_000))


def line(**kw) -> DocLine:
    values = dict(
        id=f"d{next(_counter)}", category="purchases", account="purchases", doc_type="invoice",
        client_role="buyer", doc_date=date(2026, 8, 1), doc_number="1", counterparty_tin="111222333",
        counterparty_name="Supplier", counterparty_address="", input_vat_valid=None, open_review=False,
    )
    for name in _MONEY:
        values[name] = Decimal("0.00")
    values.update(kw)
    for name in _MONEY:
        values[name] = Decimal(str(values[name]))
    return DocLine(**values)


def sale(**kw) -> DocLine:
    kw.setdefault("category", "sales")
    kw.setdefault("account", "sales")
    kw.setdefault("client_role", "seller")
    kw.setdefault("counterparty_name", "Customer")
    kw.setdefault("counterparty_tin", "555666777")
    return line(**kw)


def purchase(**kw) -> DocLine:
    kw.setdefault("category", "purchases")
    kw.setdefault("account", "purchases")
    return line(**kw)


def expense(**kw) -> DocLine:
    kw.setdefault("category", "expenses")
    kw.setdefault("account", "office_supplies")
    return line(**kw)


def company(**kw) -> CompanyFacts:
    values = dict(
        registered_name="Juan's Cloth Trading", tin="123456789", branch_code="00000", rdo_code="030",
        address="Quiapo, Manila", zip_code="1001", taxpayer_type="corporation", vat_registered=True,
        income_tax_option="graduated", deduction_method="itemized", business_type="trading",
        fiscal_year_end_month=12,
    )
    values.update(kw)
    return CompanyFacts(**values)
