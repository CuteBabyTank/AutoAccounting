"""AutoAccounting phase 1 tables: company databank, uploads, files, documents."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money():
    return mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0")


def _created():
    return mapped_column(DateTime(timezone=True), nullable=False, default=_now)


def _updated():
    return mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class AACompany(Base):
    """A client company in a firm's databank."""

    __tablename__ = "aa_companies"
    __table_args__ = (
        Index(
            "uq_aa_companies_tin", "enterprise_id", "tin", "branch_code",
            unique=True, postgresql_where=text("tin <> ''"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    registered_name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tin: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    branch_code: Mapped[str] = mapped_column(String(5), nullable=False, default="00000")
    rdo_code: Mapped[str] = mapped_column(String(5), nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    taxpayer_type: Mapped[str] = mapped_column(String(20), nullable=False, default="corporation")
    vat_status: Mapped[str] = mapped_column(String(10), nullable=False, default="vat")
    income_tax_option: Mapped[str] = mapped_column(String(15), nullable=False, default="graduated")
    deduction_method: Mapped[str] = mapped_column(String(10), nullable=False, default="itemized")
    business_type: Mapped[str] = mapped_column(String(15), nullable=False, default="trading")
    is_withholding_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_top_withholding_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_employees: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # An individual who also earns a salary (mixed income): files the 1701, and gets no ₱250,000 under 8%.
    has_compensation_income: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                          server_default="false")
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    operations_start_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_number: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    taxpayer_classification: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    # Books of accounts: null books_start = books off for this company.
    books_kept: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    books_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 1604-C import: {sheet header: alphalist field}, remembered per client
    payroll_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    books_signatory: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    books_signatory_title: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    # Set when the chart, journal entries or filed returns change: book tabs older than this are stale.
    books_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when a field that changes the returns is edited (not pin/aliases): outputs older than this are stale.
    facts_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAUpload(Base):
    """One drop of files; drives the detect → confirm → extract flow."""

    __tablename__ = "aa_uploads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    preselected_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="detecting")
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAFile(Base):
    """A physical uploaded file (may hold many documents)."""

    __tablename__ = "aa_files"
    __table_args__ = (
        Index("ix_aa_files_enterprise_sha", "enterprise_id", "sha256"),
        # One active copy of a file per company: claims are atomic across concurrent drops.
        Index(
            "uq_aa_files_company_sha_active", "company_id", "sha256",
            unique=True, postgresql_where=text("status IN ('extracting', 'extracted')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_uploads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    detection: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages_charged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class AADocument(Base):
    """One logical document (receipt, invoice, 2307 …) extracted from a file."""

    __tablename__ = "aa_documents"
    __table_args__ = (Index("ix_aa_documents_period", "company_id", "period_year", "period_quarter"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_start: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    document_title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="unsorted")
    account: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    client_role: Mapped[str] = mapped_column(String(10), nullable=False, default="buyer")
    doc_number: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    doc_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seller_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    seller_tin: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    seller_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    seller_vat_registered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    buyer_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    buyer_tin: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    buyer_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    gross_amount: Mapped[Decimal] = _money()
    vatable_amount: Mapped[Decimal] = _money()
    vat_amount: Mapped[Decimal] = _money()
    exempt_amount: Mapped[Decimal] = _money()
    zero_rated_amount: Mapped[Decimal] = _money()
    withholding_amount: Mapped[Decimal] = _money()
    ewt_atc: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_via: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    payment_ref: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    # On a receipt: the invoice it pays (then it is payment evidence, not a sale or expense of its own).
    settles_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    settles_source: Mapped[str] = mapped_column(String(5), nullable=False, default="", server_default="")
    gl_account_code: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    vat_treatment: Mapped[str] = mapped_column(String(15), nullable=False, default="")
    input_vat_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Documents a person said this one is not a duplicate of (ids as strings); the double-check skips those pairs.
    not_duplicate_of: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AASupplierRule(Base):
    """Remembered category/account for a counterparty, learned from corrections."""

    __tablename__ = "aa_supplier_rules"
    __table_args__ = (UniqueConstraint("company_id", "counterparty_tin", name="uq_aa_supplier_rule"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    counterparty_tin: Mapped[str] = mapped_column(String(9), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    account: Mapped[str] = mapped_column(String(40), nullable=False)
    ewt_atc: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    gl_account_code: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    counterparty_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    updated_at: Mapped[datetime] = _updated()


class AAAtcDefault(Base):
    """A company's default EWT ATC for an expense account (used when the supplier has none of its own)."""

    __tablename__ = "aa_atc_defaults"
    __table_args__ = (UniqueConstraint("company_id", "account", name="uq_aa_atc_default"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account: Mapped[str] = mapped_column(String(40), nullable=False)
    ewt_atc: Mapped[str] = mapped_column(String(10), nullable=False)
    updated_at: Mapped[datetime] = _updated()


class AAPeriod(Base):
    """A company's fiscal quarter: inputs the documents can't provide, and whether it was filed."""

    __tablename__ = "aa_periods"
    __table_args__ = (UniqueConstraint("company_id", "year", "quarter", name="uq_aa_period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Set only when inputs are saved, so marking a quarter filed doesn't make its outputs stale.
    inputs_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The version that was filed (latest when marked filed); credits on the annual return come from it.
    filed_output_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("aa_outputs.id", ondelete="SET NULL", use_alter=True, name="fk_aa_periods_filed_output"),
        nullable=True,
    )
    # {form: {"output_id", "version", "filed_at"}}; filed_at / filed_output_id are derived from it.
    filed_forms: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAOutput(Base):
    """One immutable generated version of a quarter's returns and workbook."""

    __tablename__ = "aa_outputs"
    __table_args__ = (UniqueConstraint("period_id", "version", name="uq_aa_output_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    review_open: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    xlsx_path: Mapped[str] = mapped_column(String(500), nullable=False)
    xlsx_clean_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()


class AAAsset(Base):
    """One asset in the register, depreciated straight-line over its useful life: a capital-goods document's, or
    (no document) one carried in at the books' start, at its net book value over its remaining life."""

    __tablename__ = "aa_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_documents.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    cost: Mapped[Decimal] = _money()
    in_service: Mapped[date] = mapped_column(Date, nullable=False)
    useful_life_months: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAAccount(Base):
    """One account in a company's chart of accounts (seeded from the standard PH chart)."""

    __tablename__ = "aa_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_aa_account_code"),
        Index("uq_aa_account_key", "company_id", "system_key", unique=True,
              postgresql_where=text("system_key IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(12), nullable=False)
    contra: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    system_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAJournalEntry(Base):
    """A journal entry typed by a person: the opening trial balance or a manual entry."""

    __tablename__ = "aa_journal_entries"
    __table_args__ = (Index("ix_aa_journal_entries_date", "company_id", "entry_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")     # opening | manual
    book: Mapped[str] = mapped_column(String(5), nullable=False, default="GJ")          # GJ | CRJ | CDJ
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    particulars: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # [{"account_code", "debit", "credit", "party_name", "party_tin"}], amounts as strings
    lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AABookClose(Base):
    """A closed month of the books (frozen entries + printed loose-leaf pages), or a bound fiscal year."""

    __tablename__ = "aa_book_closes"
    __table_args__ = (Index("ix_aa_book_closes_company", "company_id", "fiscal_year", "month_start"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="month")   # month | bound
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    month_end: Mapped[date] = mapped_column(Date, nullable=False)
    entries: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)       # frozen entries (entry_to_json)
    numbers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)       # entry id → final entry no.
    pages: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)         # book → [first, last]
    files: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)         # book → stored path
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[datetime] = _created()
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AAEmployee(Base):
    """One employee's compensation for a calendar year: a row of the 1604-C alphalist and their BIR 2316."""

    __tablename__ = "aa_employees"
    __table_args__ = (Index("ix_aa_employees_company_year", "company_id", "year"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)          # calendar year
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # alphalist fields (compute/alphalist.py)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
