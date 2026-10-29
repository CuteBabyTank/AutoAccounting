"""Request/response models for bank statements, line matching and reconciliation."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import re


class BankStatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    account_code: str
    account_number: str
    bank_name: str
    period_start: date | None
    period_end: date | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    ties: bool
    tie_breaks: list


class BankLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    statement_id: uuid.UUID
    account_code: str
    line_no: int
    line_date: date
    amount: Decimal
    balance: Decimal | None
    narration: str
    check_no: str
    match_status: str
    match_kind: str
    matched_ref: str
    match_label: str = ""
    match_amount: Decimal | None
    posting: dict
    candidates: list
    review_reason: str
    matched_at: datetime | None


class BankReconciliationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_code: str
    month_start: date
    month_end: date
    statement_balance: Decimal
    book_balance: Decimal
    uncleared: list
    reconciled_at: datetime


class BankAccountOut(BaseModel):
    code: str
    name: str
    bank_account_no: str
    reconciled_through: date | None
    opening_missing: dict | None = None


class BankOverviewOut(BaseModel):
    accounts: list[BankAccountOut]
    unassigned: list[BankStatementOut]
    rules: int


class BankMonthOut(BaseModel):
    account: BankAccountOut | None
    month_start: date
    statements: list[BankStatementOut]
    lines: list[BankLineOut]
    reconciliation: BankReconciliationOut | None
    opening_balance: Decimal | None      # statement balance at the start of the month
    closing_balance: Decimal | None      # … and at its end (opening + lines)


class ConfirmLineIn(BaseModel):
    """Empty = accept what the matcher proposed. Otherwise link a candidate or post to an account."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["document", "posting", "tax", "journal"] | None = None
    ref: str | None = Field(default=None, max_length=64)
    account_code: str | None = Field(default=None, max_length=10)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)   # a partial payment


class LineReasonIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class StatementPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_code: str = Field(min_length=1, max_length=10)


class ReconcileIn(BaseModel):
    account_code: str = Field(min_length=1, max_length=10)
    month_start: date


class ReconcileOut(BaseModel):
    ok: bool
    problem: str = ""
    statement_balance: Decimal | None = None
    book_balance: Decimal | None = None
    outstanding: Decimal | None = None
    difference: Decimal | None = None
    uncleared: list = []
    open_lines: int = 0
    reconciliation: BankReconciliationOut | None = None


class BankRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pattern: str
    direction: str
    kind: str
    account_code: str
    payee_name: str
    payee_tin: str = ""
    hits: int


class BankRuleIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=80)
    direction: Literal["in", "out", "any"] = "any"
    kind: Literal["payee", "posting"]
    account_code: str = Field(default="", max_length=10)
    payee_name: str = Field(default="", max_length=255)
    payee_tin: str = Field(default="", max_length=25)

    @field_validator("pattern", "account_code", "payee_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("pattern")
    @classmethod
    def normalize_pattern(cls, value: str) -> str:
        # The matcher compares space-separated tokens to lower-case alphanumeric tokens(narration).
        pattern = " ".join(dict.fromkeys(re.findall(r"[a-z0-9]+", value.lower())))
        if len(pattern) > 80:
            raise ValueError("The narration pattern is too long")
        return pattern

    @field_validator("payee_tin")
    @classmethod
    def tin_digits(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if value.strip() and len(digits) != 9:
            raise ValueError("Enter a 9-digit payee TIN, or leave it blank")
        return digits

    @model_validator(mode="after")
    def target(self):
        if len(self.pattern) < 2 or not re.search(r"\w", self.pattern):
            raise ValueError("Enter at least two characters of the bank narration")
        if self.kind == "posting":
            if not self.account_code:
                raise ValueError("Choose the account to post to")
            self.payee_name = self.payee_tin = ""
        else:
            if not self.payee_name and not self.payee_tin:
                raise ValueError("Enter a payee name or TIN")
            self.account_code = ""
        return self
