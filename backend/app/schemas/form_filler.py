"""Pydantic models for the form filler feature.

Two input perspectives share one normalized output unit (``FilledForm``):

* **Payee Form** — you are the payee; you list every *payor* who withheld from
  you. The payee identity is filled once at the top.
* **Payor Form** — you are the withholding agent; you list every *payee* you
  withheld from. The payor identity is filled once at the top.

Both collapse to a flat ``list[FilledForm]``, one BIR 2307 PDF page each.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    atc: str
    m1: float = 0.0
    m2: float = 0.0
    m3: float = 0.0
    total: float
    tax_withheld: float
    excel_row: int = 0


class Payee(BaseModel):
    tin: str
    name: str
    registered_address: str
    zip_code: str
    foreign_address: str = ""


class Payor(BaseModel):
    tin: str
    name: str
    registered_address: str
    zip_code: str


class FilledForm(BaseModel):
    """One fully-resolved 2307 — both parties, period, and line items."""

    excel_row: int
    payee: Payee
    payor: Payor
    period_from: str
    period_to: str
    ewt: list[LineItem] = Field(default_factory=list)
    money_payments: list[LineItem] = Field(default_factory=list)


class FieldError(BaseModel):
    sheet: str
    row: int
    column: str
    code: str
    message: str


class GenerateErrorResponse(BaseModel):
    errors: list[FieldError]
