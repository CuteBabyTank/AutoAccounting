"""Request/response models for contacts (customers / suppliers), open items, aging and 2307 items."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ContactRowOut(BaseModel):
    id: uuid.UUID
    key: str
    role: str
    tin: str
    registered_name: str
    aliases: list[str]
    open_balance: Decimal          # A/R for a customer list, A/P for a supplier list
    overdue: Decimal
    open_count: int
    cwt_pending: Decimal           # customer CWT still waiting for its 2307
    unverified: int                # bills on credit with no payment seen (payment_unverified)
    last_date: date | None
    payment_terms_days: int | None = None
    default_account: str = ""      # supplier default (the supplier databank's account)


class ContactListOut(BaseModel):
    role: str
    as_of: date
    contacts: list[ContactRowOut]
    total_open: Decimal
    total_overdue: Decimal
    total_cwt_pending: Decimal


class OpenItemOut(BaseModel):
    document_id: str
    kind: str
    doc_number: str
    doc_date: date
    due: date
    total: Decimal
    withheld: Decimal
    paid: Decimal
    open: Decimal
    days_past_due: int
    bucket: str
    payment_unverified: bool
    contact_name: str = ""
    contact_tin: str = ""
    opening: bool = False           # imported opening item: no document to open
    recovered: Decimal = Decimal("0")   # received after the item was written off (a recovery to post)


class ContactDocumentOut(BaseModel):
    id: str
    doc_number: str
    doc_date: date | None
    title: str
    category: str
    kind: str                       # ar | ap | 2307 | receipt | other
    total: Decimal
    withheld: Decimal
    period_year: int | None
    period_quarter: int | None
    open: Decimal | None            # None when not an open-item document


class ContactPaymentOut(BaseModel):
    document_id: str
    doc_number: str
    on: date
    amount: Decimal
    via: str                        # cash | bank | ewallet
    source: str                     # receipt | paid_on | bank | writeoff
    ref: str


class Cwt2307Out(BaseModel):
    document_id: str
    doc_number: str
    doc_date: date
    amount: Decimal
    year: int | None
    quarter: int | None
    status: str                     # pending | received
    certificate_id: str | None
    certificate_label: str
    source: str                     # auto | user | ""


class Outgoing2307Out(BaseModel):
    document_id: str
    doc_number: str
    doc_date: date
    atc: str
    amount: Decimal
    year: int
    quarter: int
    output_id: str | None           # the quarter's latest version with 2307s (download its ZIP), None = not generated


class CertificateOut(BaseModel):
    id: str
    label: str


class ContactOut(BaseModel):
    id: uuid.UUID
    key: str
    role: str
    tin: str
    registered_name: str
    aliases: list[str]
    address: str
    vat_status: str
    payment_terms_days: int | None
    default_account: str            # from the supplier databank (by TIN)
    default_atc: str
    manual: list[str]
    merged_into_id: uuid.UUID | None
    merged_from: list[str]          # names of contacts merged into this one
    as_of: date
    receivable: Decimal
    payable: Decimal
    documents: list[ContactDocumentOut]
    payments: list[ContactPaymentOut]
    open_items: list[OpenItemOut]
    cwt_2307s: list[Cwt2307Out]
    certificates: list[CertificateOut]   # received 2307s from this contact, to link
    outgoing_2307s: list[Outgoing2307Out]


class ContactPatch(BaseModel):
    registered_name: str | None = Field(default=None, max_length=255)
    role: Literal["customer", "supplier", "both"] | None = None
    address: str | None = Field(default=None, max_length=500)
    vat_status: Literal["vat", "non_vat", ""] | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=3650)
    default_account: str | None = Field(default=None, max_length=10)
    default_atc: str | None = Field(default=None, max_length=10)
    reason: str = Field(default="", max_length=500)


class MergeIn(BaseModel):
    into: uuid.UUID
    reason: str = Field(default="", max_length=500)


class Cwt2307In(BaseModel):
    status: Literal["pending", "received", "auto"]   # auto = forget the person's mark
    certificate_id: uuid.UUID | None = None
    reason: str = Field(default="", max_length=500)


class AgingRowOut(BaseModel):
    contact_id: uuid.UUID | None
    name: str
    tin: str
    buckets: dict[str, Decimal]
    total: Decimal
    count: int
    unverified: int


class AgingOut(BaseModel):
    kind: str
    as_of: date
    rows: list[AgingRowOut]
    totals: dict[str, Decimal]
    items: list[OpenItemOut]
