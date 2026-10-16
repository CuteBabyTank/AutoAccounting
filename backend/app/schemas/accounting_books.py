"""Request/response models for the books of accounts endpoints."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MONEY = dict(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    type: str
    contra: bool
    parent_code: str | None
    system_key: str | None
    active: bool


class AccountIn(BaseModel):
    code: str = Field(pattern=r"^\d{4,10}$")
    name: str = Field(min_length=1, max_length=120)
    parent_code: str = Field(pattern=r"^\d{4,10}$")


class AccountPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None


class JournalLineIn(BaseModel):
    account_code: str = Field(min_length=1, max_length=10)
    debit: Decimal = Field(**_MONEY)
    credit: Decimal = Field(**_MONEY)
    party_name: str = Field(default="", max_length=255)
    party_tin: str = Field(default="", max_length=9)

    @model_validator(mode="after")
    def _one_side(self):
        if (self.debit > 0) == (self.credit > 0):
            raise ValueError("Each line needs either a debit or a credit")
        return self


class JournalEntryIn(BaseModel):
    kind: Literal["opening", "manual"] = "manual"
    book: Literal["GJ", "CRJ", "CDJ"] = "GJ"
    entry_date: date
    reference: str = Field(default="", max_length=60)
    particulars: str = Field(default="", max_length=255)
    lines: list[JournalLineIn] = Field(min_length=2, max_length=200)

    @field_validator("reference", "particulars")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _balanced(self):
        debit = sum((l.debit for l in self.lines), Decimal("0"))
        credit = sum((l.credit for l in self.lines), Decimal("0"))
        if debit != credit:
            raise ValueError(f"Debits ({debit:,.2f}) and credits ({credit:,.2f}) must balance")
        if self.kind == "opening" and self.book != "GJ":
            raise ValueError("The opening balances go in the General Journal")
        return self


class JournalEntryOut(BaseModel):
    id: uuid.UUID
    kind: str
    book: str
    entry_date: date
    reference: str
    particulars: str
    lines: list[JournalLineIn]
    created_at: datetime


class DocRefOut(BaseModel):
    id: uuid.UUID
    doc_number: str
    doc_date: date | None
    counterparty: str
    gross_amount: Decimal


class PaymentLinksOut(BaseModel):
    linked_invoice: DocRefOut | None
    candidates: list[DocRefOut]
    paid_by: list[DocRefOut]


class BookMonthOut(BaseModel):
    start: date
    end: date
    status: str                      # closed | open | before_books
    pages: dict[str, list[int]]
    books: list[str]                 # books with a PDF for the month
    closed_at: datetime | None


class BooksYearOut(BaseModel):
    fiscal_year: int
    months: list[BookMonthOut]
    bound: bool
    bound_books: list[str]
    bind_by: date


class CloseMonthIn(BaseModel):
    month_start: date


class ReopenMonthIn(BaseModel):
    reason: str = Field(default="", max_length=500)   # why the closed month is reopened (audit log)
