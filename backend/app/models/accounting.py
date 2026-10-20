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
    # Owner / officers: a purchase made out to one of them personally is not the company's expense.
    owner_names: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
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
    # Company-level review flags: {"opening_balance_missing": {account code: {date, statement, books}}}
    review_flags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
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
    # Branch code digits as printed after the TIN ("000"); the 9-digit TIN alone is what everything matches on.
    seller_branch: Mapped[str] = mapped_column(String(5), nullable=False, default="", server_default="")
    seller_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    seller_vat_registered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    buyer_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    buyer_tin: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    buyer_branch: Mapped[str] = mapped_column(String(5), nullable=False, default="", server_default="")
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
    # Per-reason details shown with the reason: {"ewt_expected": {"atc": "WC010", "amount": "1500.00"}, …}
    review_notes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Documents a person said this one is not a duplicate of (ids as strings); the double-check skips those pairs.
    not_duplicate_of: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # On a sale the customer withheld tax on: a person's "2307 to receive" mark {"status", "document_id"}.
    cwt_2307: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
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
    # Management report pack: the preparer's notes and the latest files ({"pdf", "docx", "generated_at", "by"})
    pack_notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    pack_files: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
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
    # Locked: people and extraction can't post new entries to it (existing postings stay).
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # A bank account's number as printed on its statements (statements are matched on the last 4 digits).
    bank_account_no: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
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
    # an adjusting entry (accruals, corrections at period end): shown in the Adjusted TB and the AJE report
    is_adjusting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # posted from a recurring template (one entry per template per date)
    recurring_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_recurring_entries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # a bulk write-off: [{"id": open item id, "amount": "…", "doc_number", "kind": document | opening}]
    writeoff_items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # the spreadsheet import that wrote it (None: typed, or imported before batches existed)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_import_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AARecurringEntry(Base):
    """A journal entry template on a schedule (rent accrual, retainer). Due entries post only on a person's action."""

    __tablename__ = "aa_recurring_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    book: Mapped[str] = mapped_column(String(5), nullable=False, default="GJ")
    reference: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    particulars: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)   # like aa_journal_entries.lines
    is_adjusting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    frequency: Mapped[str] = mapped_column(String(10), nullable=False, default="monthly")   # monthly | quarterly
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)          # anchor day 1–31
    next_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


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


class AAAuditEvent(Base):
    """One change a person made to a firm's data (append-only: RLS allows select and insert only)."""

    __tablename__ = "aa_audit_events"
    __table_args__ = (
        Index("ix_aa_audit_events_company_at", "company_id", "at"),
        Index("ix_aa_audit_events_entity", "entity", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # None = a firm-level event (firm settings, a task not linked to a company)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    user_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")  # email when it happened
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    entity: Mapped[str] = mapped_column(String(30), nullable=False)        # audit.ENTITIES
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # What it is about, as a person reads it ("SI 5838 · Luzon Paint", "July 2026"), kept as it was then.
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    before: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)   # changed fields only
    after: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AABankStatement(Base):
    """One bank statement document: header facts and whether its running balance ties."""

    __tablename__ = "aa_bank_statements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_documents.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    account_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")   # "" = not resolved yet
    account_number: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    bank_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    ties: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tie_breaks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)      # line numbers that don't tie
    created_at: Mapped[datetime] = _created()


class AABankLine(Base):
    """One statement line and what it was matched to (a document's payment, a posting, a filed return …)."""

    __tablename__ = "aa_bank_lines"
    __table_args__ = (Index("ix_aa_bank_lines_account_date", "company_id", "account_code", "line_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_bank_statements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    line_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = _money()          # signed: + money into the account, − money out
    balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    narration: Mapped[str] = mapped_column(Text, nullable=False, default="")
    check_no: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)   # file page it is printed on (drill-down)
    # unmatched | ambiguous | suggested | matched (by the matcher) | confirmed (by a person) | excluded
    match_status: Mapped[str] = mapped_column(String(12), nullable=False, default="unmatched")
    match_kind: Mapped[str] = mapped_column(String(12), nullable=False, default="")   # document | posting | tax | journal
    matched_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    match_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    posting: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)        # {account, kind, label}
    candidates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rejected: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)       # refs a person said no to
    review_reason: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    matched_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AABankRule(Base):
    """"Narration contains X → payee Z / account Y", learned from confirmed matches (the bank side of the
    supplier databank)."""

    __tablename__ = "aa_bank_rules"
    __table_args__ = (UniqueConstraint("company_id", "pattern", "direction", "kind", name="uq_aa_bank_rule"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pattern: Mapped[str] = mapped_column(String(80), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False, default="any")   # in | out | any
    kind: Mapped[str] = mapped_column(String(10), nullable=False)                       # payee | posting
    account_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    payee_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    payee_tin: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = _updated()


class AABankReconciliation(Base):
    """A bank account reconciled for one month: statement vs book balance, uncleared items, report PDF."""

    __tablename__ = "aa_bank_reconciliations"
    __table_args__ = (Index("ix_aa_bank_recs_account", "company_id", "account_code", "month_start"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_code: Mapped[str] = mapped_column(String(10), nullable=False)
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    month_end: Mapped[date] = mapped_column(Date, nullable=False)
    statement_balance: Mapped[Decimal] = _money()
    book_balance: Mapped[Decimal] = _money()
    uncleared: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    reconciled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reconciled_at: Mapped[datetime] = _created()
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AAContact(Base):
    """A company's customer or supplier, keyed by TIN (else by normalized name), built from its documents."""

    __tablename__ = "aa_contacts"
    __table_args__ = (UniqueConstraint("company_id", "key", name="uq_aa_contact_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(300), nullable=False)          # TIN, or "NAME:<normalized name>"
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="supplier")   # customer | supplier | both
    tin: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    registered_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    vat_status: Mapped[str] = mapped_column(String(10), nullable=False, default="")   # vat | non_vat | ""
    payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")  # fields a person set
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_contacts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAWorkItem(Base):
    """What the work board can't derive for one filing (company × period × form): who does it, a manual status, and
    a filed date marked on the board (a return filed outside AutoAccounting)."""

    __tablename__ = "aa_work_items"
    __table_args__ = (UniqueConstraint("company_id", "year", "quarter", "form", name="uq_aa_work_item"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)          # 0 = annual return / 1604-C
    form: Mapped[str] = mapped_column(String(12), nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status_override: Mapped[str] = mapped_column(String(15), nullable=False, default="")
    filed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    filed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AATask(Base):
    """A free-form to-do, optionally about a company, one of its documents or a period."""

    __tablename__ = "aa_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_documents.id", ondelete="SET NULL"), nullable=True
    )
    period_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 0 = the year
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")       # open | in_progress | done
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="normal")    # low | normal | high
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAFirmSettings(Base):
    """Firm-wide settings the firm owner sets (one row per firm; defaults when missing)."""

    __tablename__ = "aa_firm_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Only owners and managers may mark returns filed (closing a month is already theirs).
    approve_before_close: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deadline_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)   # notify this many days ahead
    updated_at: Mapped[datetime] = _updated()


class AANotificationState(Base):
    """A person read or dismissed a notification (notifications themselves are derived on read)."""

    __tablename__ = "aa_notification_states"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_aa_notification_state"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AACoaTemplate(Base):
    """A firm's chart-of-accounts template, saved from a company's chart, applied when creating a company."""

    __tablename__ = "aa_coa_templates"
    __table_args__ = (UniqueConstraint("enterprise_id", "name", name="uq_aa_coa_template_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # [{"code", "name", "type", "contra", "system_key", "parent_code", "active"}]
    accounts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAOpeningItem(Base):
    """A customer invoice (A/R) or supplier bill (A/P) still open when the books start, imported from a list.

    The opening trial balance already carries it in A/R / A/P, so it never posts on its own: it only shows in the
    aging and can be paid (a matched bank line, or a payment recorded on the item), which posts the collection.
    """

    __tablename__ = "aa_opening_items"
    __table_args__ = (Index("ix_aa_opening_items_company", "company_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(2), nullable=False)                      # ar | ap
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    contact_tin: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    doc_number: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    doc_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[Decimal] = _money()
    # a payment a person recorded on the item (cash / bank); a matched bank line replaces it
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_via: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    paid_account: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_import_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AAImportBatch(Base):
    """One confirmed spreadsheet import (opening TB, opening open items or journal entries), so it can be undone.

    The rows it wrote carry its id (``import_batch_id``); ``written`` keeps their fingerprints (an undo refuses rows
    edited since) and ``restore`` the opening entry the opening TB import replaced (``{"opening": None}`` when there
    was none).
    """

    __tablename__ = "aa_import_batches"
    __table_args__ = (Index("ix_aa_import_batches_company", "company_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)       # opening-tb | open-items | journal-entries
    filename: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)   # rows written (lines / items / entries)
    written: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")   # id → fingerprint
    restore: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    undone_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class AAChecklistTemplate(Base):
    """A firm's close checklist (e.g. the monthly close): applying it creates one task per step for a company."""

    __tablename__ = "aa_checklist_templates"
    __table_args__ = (UniqueConstraint("enterprise_id", "name", name="uq_aa_checklist_template_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    cadence: Mapped[str] = mapped_column(String(10), nullable=False, default="monthly")   # monthly | quarterly | annual
    # [{"title", "notes", "offset_days", "priority"}]: due = period end + offset_days
    items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
