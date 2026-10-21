"""Plain inputs for the AutoAccounting computation engine (no ORM, no I/O)."""

from dataclasses import dataclass, field, fields
from datetime import date
from decimal import Decimal, InvalidOperation

from app.services.accounting.compute.money import ZERO, c2


@dataclass(frozen=True)
class DocLine:
    """One filed document, reduced to what the computations need."""

    id: str
    category: str          # sales | purchases | expenses | payroll | 2307 | unsorted
    account: str
    doc_type: str
    client_role: str       # seller | buyer
    doc_date: date | None
    doc_number: str
    counterparty_tin: str
    counterparty_name: str
    counterparty_address: str
    gross: Decimal = ZERO
    vatable: Decimal = ZERO
    vat: Decimal = ZERO
    vat_difference: Decimal = ZERO                    # printed VAT less recomputed VAT, held for review
    exempt: Decimal = ZERO
    zero_rated: Decimal = ZERO
    withholding: Decimal = ZERO
    input_vat_valid: bool | None = None
    open_review: bool = False
    ewt_atc: str = ""                                  # "" automatic | "NONE" | an ATC chosen on the document
    counterparty_vat_registered: bool | None = None    # supplier printed a VAT REG TIN
    gl_account: str = ""                               # chart account override ("" = mapped from account)
    nature: str = ""                                   # what Gemini read: goods_for_resale | services | … ("" unknown)


@dataclass(frozen=True)
class CompanyFacts:
    registered_name: str
    tin: str
    branch_code: str
    rdo_code: str
    address: str
    zip_code: str
    taxpayer_type: str        # individual | corporation | partnership
    vat_registered: bool
    income_tax_option: str    # graduated | eight_percent
    deduction_method: str     # itemized | osd
    business_type: str        # trading | manufacturing | services
    fiscal_year_end_month: int = 12
    is_withholding_agent: bool = False
    is_top_withholding_agent: bool = False
    has_employees: bool = False
    has_compensation_income: bool = False      # mixed-income individual: 1701, no ₱250,000 reduction under 8%
    operations_start_year: int | None = None   # MCIT applies from the 4th taxable year after this one
    contact_number: str = ""
    email: str = ""
    taxpayer_classification: str = ""         # micro | small | medium | large (2550-Q item 13)


@dataclass(frozen=True)
class PayrollMonth:
    """1601-C figures the payroll register doesn't give us, for one month of the quarter."""

    mwe_basic: Decimal = ZERO           # item 15
    mwe_premium: Decimal = ZERO         # item 16
    thirteenth_month: Decimal = ZERO    # item 17
    de_minimis: Decimal = ZERO          # item 18
    contributions: Decimal = ZERO       # item 19 (employee share)
    employer_contributions: Decimal = ZERO  # not on the 1601-C: the employer's share, an expense in the books
    other_non_taxable: Decimal = ZERO   # item 20
    not_subject: Decimal = ZERO         # item 23
    adjustment: Decimal = ZERO          # item 26 (can be negative)
    amended_paid: Decimal = ZERO        # item 28
    no_payroll: bool = False            # nobody was paid this month: a nil return, not a missing one


PAYROLL_FIELDS = tuple(f.name for f in fields(PayrollMonth) if f.name != "no_payroll")
_NO_PAYROLL = (PayrollMonth(), PayrollMonth(), PayrollMonth())


@dataclass(frozen=True)
class PeriodInputs:
    """What documents can't tell us, entered per quarter."""

    ending_inventory: Decimal | None = None
    opening_inventory: Decimal | None = None          # first quarter on the platform only
    opening_excess_input_vat: Decimal = ZERO           # carried into the first quarter on the platform
    vat_withheld: Decimal = ZERO                       # 2550-Q item 16
    advance_vat: Decimal = ZERO                        # 2550-Q item 17
    # RR 3-2024 (EOPT): output VAT on credit sales past due and uncollected, and the input VAT on purchases unpaid
    # past due; each comes back when it's collected / paid.
    uncollected_output_vat: Decimal = ZERO             # 2550-Q item 35B
    recovered_output_vat: Decimal = ZERO               # 2550-Q item 36B
    unpaid_input_vat: Decimal = ZERO                   # 2550-Q item 55B
    settled_input_vat: Decimal = ZERO                  # 2550-Q item 58B
    percentage_tax_withheld: Decimal = ZERO            # 2551-Q item 15
    non_operating_income: Decimal = ZERO
    prior_year_excess_credits: Decimal = ZERO
    prior_taxable_income: Decimal | None = None        # earlier quarters filed outside the platform
    prior_tax_paid: Decimal | None = None
    prior_cwt: Decimal | None = None
    prior_gross_income: Decimal | None = None          # earlier quarters' gross income, for the MCIT base
    amended_paid_business_tax: Decimal = ZERO          # paid on the original return: 2550-Q 18 / 2551-Q 16
    amended_paid_income_tax: Decimal = ZERO            # paid on the original return: 1702-Q S4_6 / 1701-Q 59
    cit_rate: int = 25
    mcit_applies: bool = False
    ewt_remitted_m1: Decimal | None = None             # 1601-EQ item 20 when it differs from the computed 0619-E
    ewt_remitted_m2: Decimal | None = None             # 1601-EQ item 21
    ewt_over_remittance: Decimal = ZERO                # 1601-EQ item 23
    amended_paid_withholding: Decimal = ZERO           # 1601-EQ item 22
    payroll: tuple[PayrollMonth, PayrollMonth, PayrollMonth] = _NO_PAYROLL


@dataclass(frozen=True)
class PeriodData:
    year: int
    quarter: int
    lines: tuple[DocLine, ...] = ()
    inputs: PeriodInputs = field(default_factory=PeriodInputs)


_DECIMALS = (
    "ending_inventory", "opening_inventory", "opening_excess_input_vat", "vat_withheld", "advance_vat",
    "uncollected_output_vat", "recovered_output_vat", "unpaid_input_vat", "settled_input_vat",
    "percentage_tax_withheld", "non_operating_income", "prior_year_excess_credits",
    "prior_taxable_income", "prior_tax_paid", "prior_cwt", "prior_gross_income", "amended_paid_business_tax",
    "amended_paid_income_tax", "ewt_remitted_m1", "ewt_remitted_m2", "ewt_over_remittance",
    "amended_paid_withholding",
)


def _payroll_from_json(raw) -> tuple[PayrollMonth, PayrollMonth, PayrollMonth]:
    months: list[PayrollMonth] = []
    for item in (raw if isinstance(raw, list) else [])[:3]:
        kwargs: dict = {}
        for name in PAYROLL_FIELDS:
            value = item.get(name) if isinstance(item, dict) else None
            if value is None or value == "":
                continue
            try:
                kwargs[name] = c2(value)
            except (InvalidOperation, ValueError):
                continue
        kwargs["no_payroll"] = isinstance(item, dict) and bool(item.get("no_payroll", False))
        months.append(PayrollMonth(**kwargs))
    while len(months) < 3:
        months.append(PayrollMonth())
    return tuple(months)


def inputs_from_json(data: dict | None) -> PeriodInputs:
    """Parse stored inputs; unknown or malformed values fall back to defaults."""
    data = data if isinstance(data, dict) else {}
    kwargs: dict = {}
    for name in _DECIMALS:
        raw = data.get(name)
        if raw is None or raw == "":
            continue
        try:
            kwargs[name] = c2(raw)
        except (InvalidOperation, ValueError):
            continue
    if str(data.get("cit_rate")) in ("20", "25"):
        kwargs["cit_rate"] = int(data["cit_rate"])
    kwargs["mcit_applies"] = bool(data.get("mcit_applies", False))
    kwargs["payroll"] = _payroll_from_json(data.get("payroll"))
    return PeriodInputs(**kwargs)


def inputs_to_json(inputs: PeriodInputs) -> dict:
    out: dict = {}
    for name in _DECIMALS:
        value = getattr(inputs, name)
        out[name] = None if value is None else str(value)
    out["cit_rate"] = inputs.cit_rate
    out["mcit_applies"] = inputs.mcit_applies
    out["payroll"] = [{**{name: str(getattr(month, name)) for name in PAYROLL_FIELDS}, "no_payroll": month.no_payroll}
                      for month in inputs.payroll]
    return out
