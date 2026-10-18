"""Request/response models for the spreadsheet importers (opening TB, opening open items, journal entries)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ImportKind = Literal["opening-tb", "open-items", "journal-entries"]


class ImportOptions(BaseModel):
    """The person's choices, sent as JSON next to the file on preview and confirm."""

    model_config = ConfigDict(extra="ignore")

    columns: dict[str, str] | None = None             # field → header (None = guess)
    date_format: str | None = Field(default=None, max_length=20)
    accounts: dict[str, str] = Field(default_factory=dict)   # source key → chart code
    default_kind: Literal["ar", "ap"] | None = None
    difference_account: str | None = Field(default=None, max_length=10)


class RowIssueOut(BaseModel):
    row: int
    message: str


class AccountChoiceOut(BaseModel):
    key: str
    code_in: str
    name_in: str
    match_code: str | None
    how: str
    score: float
    alternatives: list[str]
    chosen: str | None
    problem: str
    rows: int


class DateFormatOut(BaseModel):
    value: str
    label: str


class TbLineOut(BaseModel):
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal


class OpenItemPreviewOut(BaseModel):
    row: int
    kind: str
    contact_name: str
    contact_tin: str
    doc_number: str
    doc_date: date
    due_date: date | None
    terms_days: int | None
    amount: Decimal


class JePreviewOut(BaseModel):
    row: int
    entry_date: date | None
    posts_on: date | None
    reference: str
    particulars: str
    is_adjusting: bool
    debit: Decimal
    credit: Decimal
    lines: int
    errors: list[str]


class ImportPreviewOut(BaseModel):
    kind: str
    filename: str
    headers: list[str]
    columns: dict[str, str]
    fields: dict[str, str]
    row_count: int
    date_format: str | None
    date_formats: list[DateFormatOut]          # every format that reads the dates (pick one when several)
    accounts: list[AccountChoiceOut] = Field(default_factory=list)
    errors: list[RowIssueOut]
    warnings: list[str]
    ready: bool
    # opening TB
    tb_lines: list[TbLineOut] = Field(default_factory=list)
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    difference: Decimal = Decimal("0")
    raw_difference: Decimal = Decimal("0")
    as_of: date | None = None
    has_opening: bool = False
    # open items
    items: list[OpenItemPreviewOut] = Field(default_factory=list)
    item_count: int = 0
    totals: dict[str, Decimal] = Field(default_factory=dict)
    control: dict[str, Decimal] = Field(default_factory=dict)
    skipped: int = 0
    # journal entries
    entries: list[JePreviewOut] = Field(default_factory=list)
    last_closed: date | None = None
    books_start: date | None = None


class ImportResultOut(BaseModel):
    kind: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    warnings: list[str] = Field(default_factory=list)


class OpeningItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    contact_name: str
    contact_tin: str
    doc_number: str
    doc_date: date
    due_date: date | None
    terms_days: int | None
    amount: Decimal
    paid_on: date | None
    paid_via: str
    paid_account: str
    open: Decimal = Decimal("0")


class OpeningItemsOut(BaseModel):
    items: list[OpeningItemOut]
    totals: dict[str, Decimal]
    control: dict[str, Decimal]
    warnings: list[str]
    books_start: date | None


class OpeningItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paid_on: date | None = None
    paid_via: Literal["cash", "bank", "ewallet"] = "cash"
    paid_account: str = Field(default="", max_length=10)
