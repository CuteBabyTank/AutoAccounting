"""Request/response models for the work board, client health, tasks, firm settings and notifications."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.accounting import manila_today

BoardStatus = Literal["no_docs", "docs_in", "needs_review", "generated", "filed"]


class PersonOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str


class FirmSettingsOut(BaseModel):
    approve_before_close: bool
    deadline_days: int
    can_edit: bool        # the firm owner (or platform admin) may change these
    can_file: bool        # this person may mark returns filed


class FirmSettingsIn(BaseModel):
    approve_before_close: bool
    deadline_days: int = Field(default=7, ge=1, le=60)


class WorkCardOut(BaseModel):
    key: str
    company_id: uuid.UUID
    company_name: str
    form: str
    form_label: str
    year: int
    quarter: int
    period_label: str
    due_date: date
    status: str
    auto_status: str
    status_override: str
    overdue: bool
    days_left: int
    filed_on: str | None
    filed_source: str | None
    assignee_id: uuid.UUID | None
    assignee_name: str = ""
    documents: int
    open_reviews: int


class CompanySummaryOut(BaseModel):
    company_id: uuid.UUID
    company_name: str
    open_reviews: int
    unmatched_bank_lines: int
    unreconciled_months: int
    months_not_closed: int
    books_on: bool
    open_tasks: int = 0
    overdue_filings: int = 0


class BoardOut(BaseModel):
    start: date
    end: date
    today: date
    cards: list[WorkCardOut]
    companies: list[CompanySummaryOut]
    people: list[PersonOut]


class WorkItemIn(BaseModel):
    """Only the fields sent are changed: assignee_id null unassigns, status_override "" goes back to automatic,
    filed_on null clears a board filing."""

    company_id: uuid.UUID
    year: int = Field(ge=2000, le=2100)
    quarter: int = Field(ge=0, le=4)
    form: str = Field(min_length=2, max_length=12)
    assignee_id: uuid.UUID | None = None
    status_override: Literal["", "no_docs", "docs_in", "needs_review", "generated"] = ""
    filed_on: date | None = None

    @field_validator("filed_on")
    @classmethod
    def _not_future(cls, value: date | None) -> date | None:
        if value is not None and value > manila_today():
            raise ValueError("The filing date can't be in the future")
        return value


# --- client health --------------------------------------------------------------------------------------------------

class HealthBankAccountOut(BaseModel):
    code: str
    name: str
    reconciled_through: date | None
    unreconciled_months: list[date]
    unmatched_lines: int


class HealthBalanceOut(BaseModel):
    code: str
    name: str
    type: str
    balance: Decimal


class HealthRecoveryOut(BaseModel):
    """Money received on an invoice after it was written off: a bad-debt recovery for a person to post."""
    document_id: str
    doc_number: str
    contact_name: str
    amount: Decimal
    opening: bool = False


class HealthOut(BaseModel):
    company_id: uuid.UUID
    company_name: str
    as_of: date
    reviews_by_reason: dict[str, int]
    open_reviews: int
    bank_accounts: list[HealthBankAccountOut]
    unassigned_statements: int
    unmatched_bank_lines: int
    cwt_pending_count: int
    cwt_pending_amount: Decimal
    months_not_closed: list[date]
    books_on: bool
    ar_over_90_count: int
    ar_over_90_amount: Decimal
    ap_over_90_count: int
    ap_over_90_amount: Decimal
    negative_balances: list[HealthBalanceOut]
    review_balances: list[HealthBalanceOut]
    writeoff_recoveries: list[HealthRecoveryOut] = []
    issues: int
    notes: list[str] = []


# --- tasks ----------------------------------------------------------------------------------------------------------

TaskStatus = Literal["open", "in_progress", "done"]
TaskPriority = Literal["low", "normal", "high"]


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=4000)
    due_date: date | None = None
    assignee_id: uuid.UUID | None = None
    status: TaskStatus = "open"
    priority: TaskPriority = "normal"
    company_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    period_year: int | None = Field(default=None, ge=2000, le=2100)
    period_quarter: int | None = Field(default=None, ge=0, le=4)

    @field_validator("title")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A task needs a title")
        return value


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)
    due_date: date | None = None
    assignee_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    company_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    period_year: int | None = Field(default=None, ge=2000, le=2100)
    period_quarter: int | None = Field(default=None, ge=0, le=4)


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    notes: str
    due_date: date | None
    assignee_id: uuid.UUID | None
    assignee_name: str
    status: str
    priority: str
    company_id: uuid.UUID | None
    company_name: str
    document_id: uuid.UUID | None
    document_label: str
    period_year: int | None
    period_quarter: int | None
    created_by: uuid.UUID | None
    created_by_name: str
    created_at: datetime
    completed_at: datetime | None
    overdue: bool


# --- notifications --------------------------------------------------------------------------------------------------

class NotificationOut(BaseModel):
    key: str
    kind: str
    title: str
    detail: str
    company_id: uuid.UUID | None
    due_date: date | None
    severity: str
    read: bool


class NotificationsOut(BaseModel):
    items: list[NotificationOut]
    unread: int


class NotificationKeysIn(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=500)
    all: bool = False
