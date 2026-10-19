"""Request/response models for /api/accounting."""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.accounting.books.chart import default_books
from app.services.accounting.compute.ewt import ATC_NONE, atc_info
from app.services.accounting.parsing import normalize_tin

_MANILA = ZoneInfo("Asia/Manila")

Category = Literal["sales", "purchases", "expenses", "payroll", "2307", "support", "unsorted"]
Account = Literal[
    "purchases", "raw_materials", "importation", "capital_goods", "salaries", "rent",
    "utilities", "professional_fees", "office_supplies", "representation", "transportation",
    "repairs", "taxes_licenses", "other", "sales", "2307_received", "2307_issued",
]
VatTreatment = Literal["", "vatable", "exempt", "zero_rated", "no_input_vat"]
def _money_field():
    return Field(default=None, max_digits=14, decimal_places=2)


def _tin_base(value: str) -> str:
    base, _ = normalize_tin(value)
    if not base:
        raise ValueError("TIN needs at least 9 digits")
    return base


class CompanyIn(BaseModel):
    registered_name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    owner_names: list[str] = Field(default_factory=list, max_length=20)
    tin: str = Field(min_length=9, max_length=25)
    branch_code: str = "00000"
    rdo_code: str = Field(default="", max_length=5)
    address: str = Field(default="", max_length=1000)
    zip_code: str = Field(default="", max_length=10)
    taxpayer_type: Literal["individual", "corporation", "partnership"] = "corporation"
    vat_status: Literal["vat", "non_vat"] = "vat"
    income_tax_option: Literal["graduated", "eight_percent"] = "graduated"
    deduction_method: Literal["itemized", "osd"] = "itemized"
    business_type: Literal["trading", "manufacturing", "services"] = "trading"
    is_withholding_agent: bool = False
    is_top_withholding_agent: bool = False
    has_employees: bool = False
    has_compensation_income: bool = False
    fiscal_year_end_month: int = Field(default=12, ge=1, le=12)
    operations_start_year: int | None = Field(default=None, ge=1900, le=2100)
    contact_number: str = Field(default="", max_length=20)
    email: str = Field(default="", max_length=255)
    taxpayer_classification: Literal["", "micro", "small", "medium", "large"] = ""
    books_start: date | None = None
    books_kept: list[Literal["SJ", "PJ", "CRJ", "CDJ", "GJ", "GL"]] = Field(default_factory=list)
    books_signatory: str = Field(default="", max_length=120)
    books_signatory_title: str = Field(default="", max_length=60)
    pinned: bool = False

    @field_validator("registered_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Registered name is required")
        return v

    @field_validator("aliases", "owner_names")
    @classmethod
    def _clean_aliases(cls, v: list[str]) -> list[str]:
        return [a.strip()[:255] for a in v if a and a.strip()]

    @field_validator("tin")
    @classmethod
    def _tin(cls, v: str) -> str:
        return _tin_base(v)

    @field_validator("branch_code")
    @classmethod
    def _branch(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v or "")[:5]
        return digits.zfill(5) if digits else "00000"

    @model_validator(mode="after")
    def _eight_percent_individuals_only(self):
        if self.income_tax_option == "eight_percent":
            if self.taxpayer_type != "individual":
                raise ValueError("The 8% income tax option is only for individuals")
            if self.vat_status == "vat":
                raise ValueError("The 8% income tax option is only for non-VAT taxpayers")
        if self.has_compensation_income and self.taxpayer_type != "individual":
            raise ValueError("Compensation income (mixed income) is only for individuals")
        return self

    @model_validator(mode="after")
    def _books_kept(self):
        kept = self.books_kept or default_books(self.vat_status == "vat")
        order = ("SJ", "PJ", "CRJ", "CDJ", "GJ", "GL")
        self.books_kept = [b for b in order if b in set(kept) | {"GJ", "GL"}]
        return self


class CompanyCreateIn(CompanyIn):
    # "" = the standard chart (seeded on first use); a built-in template key or a firm template id
    coa_template: str = Field(default="", max_length=40)


class CompanyOut(CompanyIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


class CompanyBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    registered_name: str
    tin: str


class UploadFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    status: str
    company_id: uuid.UUID | None
    error_message: str | None


class UploadGroupOut(BaseModel):
    key: str
    company: CompanyBrief | None
    level: Literal["certain", "likely", "unknown", "unreadable"]
    detected_name: str
    detected_tin: str
    detected_address: str
    file_ids: list[uuid.UUID]
    file_names: list[str]


class AffectedPeriodOut(BaseModel):
    company_id: uuid.UUID
    company_name: str
    year: int
    quarter: int
    label: str
    latest_version: int
    filed: bool
    new_documents: int


class UploadOut(BaseModel):
    id: uuid.UUID
    status: str
    total_files: int
    processed_files: int
    preselected_company_id: uuid.UUID | None
    files: list[UploadFileOut]
    groups: list[UploadGroupOut]
    affected_periods: list[AffectedPeriodOut] = Field(default_factory=list)


class ConfirmAssignment(BaseModel):
    file_ids: list[uuid.UUID] = Field(min_length=1)
    company_id: uuid.UUID | None = None
    skip: bool = False

    @model_validator(mode="after")
    def _one_target(self):
        if (self.company_id is None) == (not self.skip):
            raise ValueError("Each assignment needs either a company_id or skip=true")
        return self


class ConfirmIn(BaseModel):
    assignments: list[ConfirmAssignment] = Field(min_length=1)


class TreeQuarterOut(BaseModel):
    year: int
    quarter: int
    label: str
    document_count: int
    review_count: int
    latest_version: int | None = None
    stale: bool = False
    filed: bool = False


class TreeAnnualOut(BaseModel):
    latest_version: int | None = None
    stale: bool = False
    filed: bool = False


class TreeBankMonthOut(BaseModel):
    month_start: date
    lines: int
    open: int
    reconciled: bool


class TreeBankAccountOut(BaseModel):
    account_code: str
    name: str
    last4: str = ""
    months: list[TreeBankMonthOut]


class TreeYearOut(BaseModel):
    year: int
    quarters: list[TreeQuarterOut]
    annual: TreeAnnualOut = Field(default_factory=TreeAnnualOut)
    bank: list[TreeBankAccountOut] = Field(default_factory=list)


class TreeCompanyOut(BaseModel):
    id: uuid.UUID
    registered_name: str
    tin: str
    pinned: bool
    fiscal_year_end_month: int
    books_start: date | None = None
    has_employees: bool = False
    years: list[TreeYearOut]
    undated_count: int


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    file_id: uuid.UUID
    page_start: int
    page_end: int
    document_title: str
    doc_type: str
    category: str
    account: str
    client_role: str
    doc_number: str
    doc_date: date | None
    period_year: int | None
    period_quarter: int | None
    period_month: int | None
    period_locked: bool
    seller_name: str
    seller_tin: str
    seller_address: str
    seller_vat_registered: bool | None
    buyer_name: str
    buyer_tin: str
    buyer_address: str
    gross_amount: Decimal
    vatable_amount: Decimal
    vat_amount: Decimal
    exempt_amount: Decimal
    zero_rated_amount: Decimal
    withholding_amount: Decimal
    ewt_atc: str
    ewt_atc_effective: str = ""   # what the next generation uses (own, remembered or suggested)
    ewt_atc_source: str = ""      # document | supplier | account | "" (built-in suggestion)
    ewt_atc_suggestion: str = ""  # this supplier's ATC in another company of the firm (not applied)
    ewt_atc_suggestion_company: str = ""
    rule_applied_to: int = 0  # after a correction: the supplier's other unreviewed documents it also changed
    paid_on: date | None = None
    paid_via: str = ""
    payment_ref: str = ""
    settles_document_id: uuid.UUID | None = None
    settles_source: str = ""
    gl_account_code: str = ""
    vat_treatment: str
    input_vat_valid: bool | None
    confidence: float
    needs_review: bool
    review_reasons: list[str]
    review_notes: dict = Field(default_factory=dict)
    reviewed: bool
    excluded: bool
    created_at: datetime


class FolderOut(BaseModel):
    company: CompanyBrief
    year: int | None
    quarter: int | None
    label: str
    counts: dict[str, int]
    documents: list[DocumentOut]


class DuplicatePairOut(BaseModel):
    """Two documents that look like the same paper filed twice; ``duplicate`` was filed later."""

    original: DocumentOut
    duplicate: DocumentOut
    reason: Literal["same_number", "same_details", "number_reused"]
    original_file: str
    duplicate_file: str


class NotDuplicateIn(BaseModel):
    other_id: uuid.UUID
    reason: str = Field(default="", max_length=500)   # why both are kept (audit log)


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category | None = None
    account: Account | None = None
    doc_number: str | None = Field(default=None, max_length=60)
    doc_date: date | None = None
    period_year: int | None = Field(default=None, ge=2000, le=2100)
    period_quarter: int | None = Field(default=None, ge=1, le=4)
    seller_name: str | None = Field(default=None, max_length=255)
    seller_tin: str | None = None
    seller_address: str | None = Field(default=None, max_length=500)
    buyer_name: str | None = Field(default=None, max_length=255)
    buyer_tin: str | None = None
    gross_amount: Decimal | None = _money_field()
    vatable_amount: Decimal | None = _money_field()
    vat_amount: Decimal | None = _money_field()
    exempt_amount: Decimal | None = _money_field()
    zero_rated_amount: Decimal | None = _money_field()
    withholding_amount: Decimal | None = _money_field()
    ewt_atc: str | None = Field(default=None, max_length=10)
    vat_treatment: VatTreatment | None = None
    reviewed: bool | None = None
    excluded: bool | None = None
    paid_on: date | None = None
    paid_via: Literal["", "cash", "bank", "ewallet"] | None = None
    payment_ref: str | None = Field(default=None, max_length=60)
    gl_account_code: str | None = Field(default=None, max_length=10)
    settles_document_id: uuid.UUID | None = None
    # Why (audit log only, never stored on the document): e.g. accepting a review flag anyway.
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("seller_tin", "buyer_tin")
    @classmethod
    def _tin(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return "" if v is not None else None
        return _tin_base(v)

    @field_validator("ewt_atc")
    @classmethod
    def _ewt_atc(cls, v: str | None) -> str | None:
        if v is None:
            return None
        code = v.strip().upper()
        if code and code != ATC_NONE and atc_info(code) is None:
            raise ValueError("Unknown ATC, or one without a fixed rate")
        return code

    @model_validator(mode="after")
    def _period_pair(self):
        sent = self.model_fields_set
        if ("period_year" in sent) != ("period_quarter" in sent):
            raise ValueError("period_year and period_quarter must be sent together")
        if (self.period_year is None) != (self.period_quarter is None):
            raise ValueError("period_year and period_quarter must both be set or both be null")
        return self


def _amount(default=None, minimum=0):
    if minimum is None:
        return Field(default=default, max_digits=14, decimal_places=2)
    return Field(default=default, ge=minimum, max_digits=14, decimal_places=2)


class PayrollMonthModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mwe_basic: Decimal = _amount(Decimal("0"))
    mwe_premium: Decimal = _amount(Decimal("0"))
    thirteenth_month: Decimal = _amount(Decimal("0"))
    de_minimis: Decimal = _amount(Decimal("0"))
    contributions: Decimal = _amount(Decimal("0"))
    employer_contributions: Decimal = _amount(Decimal("0"))
    other_non_taxable: Decimal = _amount(Decimal("0"))
    not_subject: Decimal = _amount(Decimal("0"))
    adjustment: Decimal = _amount(Decimal("0"), minimum=None)
    amended_paid: Decimal = _amount(Decimal("0"))
    no_payroll: bool = False


class PeriodInputsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_inventory: Decimal | None = _amount()
    opening_inventory: Decimal | None = _amount()
    opening_excess_input_vat: Decimal = _amount(Decimal("0"))
    vat_withheld: Decimal = _amount(Decimal("0"))
    advance_vat: Decimal = _amount(Decimal("0"))
    uncollected_output_vat: Decimal = _amount(Decimal("0"))
    recovered_output_vat: Decimal = _amount(Decimal("0"))
    unpaid_input_vat: Decimal = _amount(Decimal("0"))
    settled_input_vat: Decimal = _amount(Decimal("0"))
    percentage_tax_withheld: Decimal = _amount(Decimal("0"))
    non_operating_income: Decimal = _amount(Decimal("0"))
    prior_year_excess_credits: Decimal = _amount(Decimal("0"))
    prior_taxable_income: Decimal | None = _amount(minimum=None)  # can be a loss
    prior_tax_paid: Decimal | None = _amount()
    prior_cwt: Decimal | None = _amount()
    prior_gross_income: Decimal | None = _amount(minimum=None)
    amended_paid_business_tax: Decimal = _amount(Decimal("0"))
    amended_paid_income_tax: Decimal = _amount(Decimal("0"))
    cit_rate: Literal[20, 25] = 25
    mcit_applies: bool = False
    ewt_remitted_m1: Decimal | None = _amount()
    ewt_remitted_m2: Decimal | None = _amount()
    ewt_over_remittance: Decimal = _amount(Decimal("0"))
    amended_paid_withholding: Decimal = _amount(Decimal("0"))
    payroll: list[PayrollMonthModel] = Field(default_factory=lambda: [PayrollMonthModel() for _ in range(3)],
                                             min_length=3, max_length=3)


class OutputBrief(BaseModel):
    id: uuid.UUID
    version: int
    created_at: datetime
    review_open: int
    changes: int
    amended: bool


class FiledFormOut(BaseModel):
    output_id: uuid.UUID
    version: int
    filed_at: datetime
    paid_on: date | None = None


def manila_today() -> date:
    return datetime.now(_MANILA).date()


def _not_future(value: date | None) -> date | None:
    if value is not None and value > manila_today():
        raise ValueError("The filing date can't be in the future")
    return value


class FormFiledIn(BaseModel):
    filed: bool
    output_id: uuid.UUID | None = None   # default: the latest version
    filed_on: date | None = None         # the day it was filed and paid; default today (Manila)

    _filed_on = field_validator("filed_on")(_not_future)


class PrepareFormOut(BaseModel):
    form: str
    title: str
    guide: str
    source: str | None
    due: date | None
    filed: FiledFormOut | None
    amended: bool
    missing: list[str]


class PrepareOut(BaseModel):
    scope: Literal["M1", "M2", "M3", "Q"]
    label: str
    note: str | None
    forms: list[PrepareFormOut]
    stale: bool
    version: int
    latest_version: int


class PdfsIn(BaseModel):
    forms: list[str] = Field(max_length=12)
    clean: bool = False


class FormEditIn(BaseModel):
    """Hand edits to one form of a version: item key → new value (preview, or saved as a new version)."""
    form: str = Field(max_length=20)
    values: dict[str, str] = Field(default_factory=dict, max_length=400)


class PdfFieldOut(BaseModel):
    key: str
    label: str
    value: str
    kind: Literal["amount", "text"]


class CertificateOut(BaseModel):
    id: str
    label: str
    fields: list[PdfFieldOut]


class CertificatePreviewIn(BaseModel):
    id: str = Field(max_length=64)
    values: dict[str, str] = Field(default_factory=dict, max_length=200)


class CertificatesIn(BaseModel):
    """Edits per certificate id for the exported zip."""
    edits: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=2000)


class PeriodOut(BaseModel):
    company: CompanyBrief
    year: int
    quarter: int
    label: str
    inputs: PeriodInputsModel
    filed_at: datetime | None
    filed_forms: dict[str, FiledFormOut] = Field(default_factory=dict)
    document_count: int
    open_reviews: int
    latest_version: int | None
    stale: bool
    books_stale: bool = False
    forms_expected: list[str]
    due_dates: dict[str, date]
    outputs: list[OutputBrief]


class ItemOut(BaseModel):
    key: str
    label: str
    value: str
    changed: bool
    before: str | None
    engine: str | None = None  # the figure from the books, when this one was edited by hand


class FormOut(BaseModel):
    form: str
    title: str
    items: list[ItemOut]
    pdf: bool
    payable_item: str | None


class OutputOut(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    year: int
    quarter: int
    label: str
    version: int
    parent_version: int | None
    created_at: datetime
    review_open: int
    amended: bool
    changes: int
    warnings: list[str]
    forms: list[FormOut]
    ledgers: dict[str, int]


class FiledIn(BaseModel):
    filed: bool
    filed_on: date | None = None         # the day it was filed and paid; default today (Manila)

    _filed_on = field_validator("filed_on")(_not_future)


# --- Annual returns and the asset register (Phase 4a) -----------------------------------------

class OpeningRowModel(BaseModel):
    """A NOLCO or excess MCIT row carried in from years before AutoAccounting."""

    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=2000, le=2100)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    used: Decimal = _amount(Decimal("0"))


class AnnualInputsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_inventory: Decimal | None = _amount()
    non_operating_income: Decimal | None = _amount()
    prior_year_excess_credits: Decimal | None = _amount()
    q1_paid: Decimal | None = _amount()
    q2_paid: Decimal | None = _amount()
    q3_paid: Decimal | None = _amount()
    amended_paid_income_tax: Decimal = _amount(Decimal("0"))
    cit_20_percent: bool = False
    refund_overpayment: bool = False
    current_assets: Decimal | None = _amount()
    ppe_net: Decimal | None = _amount()
    other_noncurrent_assets: Decimal | None = _amount()
    current_liabilities: Decimal | None = _amount()
    noncurrent_liabilities: Decimal | None = _amount()
    equity: Decimal | None = _amount(minimum=None)
    book_net_income: Decimal | None = _amount(minimum=None)
    nondeductible_expenses: Decimal = _amount(Decimal("0"))
    nontaxable_income: Decimal = _amount(Decimal("0"))
    other_reconciling: Decimal = _amount(Decimal("0"), minimum=None)
    pre_books_sales: Decimal = _amount(Decimal("0"))
    pre_books_cost_of_sales: Decimal = _amount(Decimal("0"))
    pre_books_deductions: Decimal = _amount(Decimal("0"))
    pre_books_cwt: Decimal = _amount(Decimal("0"))
    compensation_income: Decimal = _amount(Decimal("0"))
    compensation_nontaxable: Decimal = _amount(Decimal("0"))
    compensation_tax_withheld: Decimal = _amount(Decimal("0"))
    opening_nolco: list[OpeningRowModel] = Field(default_factory=list, max_length=20)
    opening_excess_mcit: list[OpeningRowModel] = Field(default_factory=list, max_length=20)


class AnnualPeriodOut(BaseModel):
    company: CompanyBrief
    year: int
    label: str
    form: str
    inputs: AnnualInputsModel
    filed_at: datetime | None
    document_count: int
    open_reviews: int
    latest_version: int | None
    stale: bool
    forms_expected: list[str]
    due_dates: dict[str, date]
    outputs: list[OutputBrief]
    carry_source: Literal["previous_year", "opening"]
    previous_year_version: int | None = None
    pre_books_quarters: list[int] = Field(default_factory=list)  # quarters of this year before the books start
    has_compensation_income: bool = False  # mixed-income individual: the 2316 inputs apply


class AssetOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID | None  # None: an opening asset carried in at the books' start
    doc_number: str
    doc_date: date | None
    description: str
    cost: Decimal
    in_service: date
    useful_life_months: int
    end_date: date | None
    active: bool
    this_year: Decimal
    accumulated: Decimal
    net_book_value: Decimal


class OpeningAssetIn(BaseModel):
    """An asset already owned when the books start: its net book value then, over its remaining life."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=255)
    cost: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    in_service: date | None = None  # default: the books' start
    useful_life_months: int = Field(default=60, ge=1, le=600)


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, min_length=1, max_length=255)
    in_service: date | None = None
    useful_life_months: int | None = Field(default=None, ge=1, le=600)
    end_date: date | None = None

    @model_validator(mode="after")
    def _end_after_start(self):
        if self.in_service and self.end_date and self.end_date < self.in_service:
            raise ValueError("The end date can't be before the in-service date")
        return self


def _atc_code(v: str) -> str:
    code = v.strip().upper()
    if code and code != ATC_NONE and atc_info(code) is None:
        raise ValueError("Unknown ATC, or one without a fixed rate")
    return code


class AtcSet(BaseModel):
    ewt_atc: str = Field(max_length=10)   # "" forgets it, NONE = no withholding
    name: str = Field(default="", max_length=255)

    @field_validator("ewt_atc")
    @classmethod
    def _code(cls, v: str) -> str:
        return _atc_code(v)


class AtcSupplierOut(BaseModel):
    tin: str
    name: str
    documents: int
    ewt_atc: str
    suggestion: str = ""
    suggestion_company: str = ""


class AtcDefaultOut(BaseModel):
    account: str
    ewt_atc: str


class AtcDatabankOut(BaseModel):
    defaults: list[AtcDefaultOut]
    suppliers: list[AtcSupplierOut]
