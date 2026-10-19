"""Editable fields of the certificates a firm hands out (BIR 2307 to payees, 2316 to employees), pure.

Certificates aren't versioned: the preview lists each one's fields, and edits only change the file exported.
Fields are ``{key, label, value, kind}`` with ``kind`` "amount" or "text"; values are strings.
"""

import re
from dataclasses import replace
from decimal import Decimal

from app.schemas.form_filler import FilledForm
from app.services.accounting.compute.alphalist import FIELD_LABELS, NON_TAXABLE, TAXABLE, Computed
from app.services.accounting.form_edits import MAX_TEXT, parse_amount

_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _field(key: str, label: str, value, kind: str) -> dict:
    if kind == "amount":
        value = f"{Decimal(str(value or 0)):.2f}"
    return {"key": key, "label": label, "value": "" if value is None else str(value), "kind": kind}


def _text(value: str, key: str) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > MAX_TEXT:
        raise ValueError(f"{key}: keep text under {MAX_TEXT} characters")
    return text


def _amount(value: str, key: str) -> Decimal:
    try:
        return parse_amount(value).quantize(Decimal("0.01"))
    except ValueError as e:
        raise ValueError(f"{key}: {e}") from None


# --- 2307 ----------------------------------------------------------------------------------------

_PAYEE = (("payee.name", "Payee name"), ("payee.tin", "Payee TIN"),
          ("payee.registered_address", "Payee registered address"), ("payee.zip_code", "Payee ZIP code"))
_LINE_TEXT = (("description", "income payment"), ("atc", "ATC"))
_LINE_AMOUNTS = (("m1", "1st month"), ("m2", "2nd month"), ("m3", "3rd month"), ("total", "total"),
                 ("tax_withheld", "tax withheld"))


def fields_2307(form: FilledForm) -> list[dict]:
    out = [_field(key, label, getattr(form.payee, key.split(".")[1]), "text") for key, label in _PAYEE]
    out += [_field("period_from", "Period from (MM/DD/YYYY)", form.period_from, "text"),
            _field("period_to", "Period to (MM/DD/YYYY)", form.period_to, "text")]
    for i, item in enumerate(form.ewt):
        out += [_field(f"ewt.{i}.{attr}", f"Line {i + 1} {label}", getattr(item, attr), "text")
                for attr, label in _LINE_TEXT]
        out += [_field(f"ewt.{i}.{attr}", f"Line {i + 1} {label}", getattr(item, attr), "amount")
                for attr, label in _LINE_AMOUNTS]
    return out


def apply_2307(form: FilledForm, edits: dict[str, str]) -> FilledForm:
    """The certificate with ``edits`` applied. Unknown keys, bad amounts or dates are a ValueError."""
    payee = form.payee.model_dump()
    top = {"period_from": form.period_from, "period_to": form.period_to}
    lines = [item.model_dump() for item in form.ewt]
    for key, value in edits.items():
        parts = key.split(".")
        if key in dict(_PAYEE):
            payee[parts[1]] = _text(value, key)
        elif key in top:
            text = _text(value, key)
            if not _DATE.match(text):
                raise ValueError(f"{key}: use MM/DD/YYYY")
            top[key] = text
        elif parts[0] == "ewt" and len(parts) == 3 and parts[1].isdigit() and int(parts[1]) < len(lines):
            attr = parts[2]
            if attr in dict(_LINE_TEXT):
                lines[int(parts[1])][attr] = _text(value, key)
            elif attr in dict(_LINE_AMOUNTS):
                lines[int(parts[1])][attr] = float(_amount(value, key))
            else:
                raise ValueError(f"There is no field {key} on this certificate")
        else:
            raise ValueError(f"There is no field {key} on this certificate")
    return form.model_copy(update={"payee": form.payee.model_validate(payee), **top,
                                   "ewt": [type(item).model_validate(line) for item, line in zip(form.ewt, lines)]})


# --- 2316 ----------------------------------------------------------------------------------------

_2316_TEXT = (("4", "Employee name"), ("3", "Employee TIN"), ("6", "Registered address"), ("6A", "ZIP code"),
              ("7", "Date of birth (MM/DD/YYYY)"), ("8", "Contact number"), ("2_from", "Period from (MM/DD)"),
              ("2_to", "Period to (MM/DD)"), ("16", "Previous employer TIN"), ("17", "Previous employer name"))
_2316_AMOUNTS: tuple[tuple[str, str], ...] = (
    ("9", "Statutory minimum wage per day"), ("10", "Statutory minimum wage per month"),
    ("19", "19 Gross compensation income from present employer"),
    ("20", "20 Less: total non-taxable/exempt compensation"),
    ("21", "21 Taxable compensation income from present employer"),
    ("22", "22 Add: taxable compensation from previous employer"),
    ("23", "23 Gross taxable compensation income"), ("24", "24 Tax due"),
    ("25A", "25A Tax withheld — present employer"), ("25B", "25B Tax withheld — previous employer"),
    ("26", "26 Total amount of taxes withheld as adjusted"), ("27", "27 5% tax credit (PERA)"),
    ("28", "28 Total taxes withheld"),
    *((str(n), f"{n} {FIELD_LABELS[k]}") for n, k in zip(range(29, 38), NON_TAXABLE)),
    ("38", "38 Total non-taxable/exempt compensation"),
    *((n, f"{n} {FIELD_LABELS[k]}") for n, k in zip(("39", "40", "41", "42", "43", "44A", "45", "46", "47", "48",
                                                     "49", "50", "51A"), TAXABLE)),
    ("52", "52 Total taxable compensation"),
)


def fields_2316(c: Computed) -> list[dict]:
    f = c.form
    out = [_field(key, label, f.get(key, ""), "text") for key, label in _2316_TEXT if key in f]
    out += [_field(key, label, f[key], "amount") for key, label in _2316_AMOUNTS
            if isinstance(f.get(key), Decimal)]
    return out


def apply_2316(c: Computed, edits: dict[str, str]) -> Computed:
    form = dict(c.form)
    text_keys = {k for k, _ in _2316_TEXT}
    amount_keys = {k for k, _ in _2316_AMOUNTS if isinstance(form.get(k), Decimal)}
    for key, value in edits.items():
        if key in text_keys and key in form:
            text = _text(value, key)
            if key == "7" and text and not _DATE.match(text):
                raise ValueError("Date of birth: use MM/DD/YYYY")
            if key in ("2_from", "2_to") and not re.match(r"^\d{2}/\d{2}$", text):
                raise ValueError(f"{key}: use MM/DD")
            form[key] = text
        elif key in amount_keys:
            form[key] = _amount(value, key)
        else:
            raise ValueError(f"There is no field {key} on this 2316")
    return replace(c, form=form)
