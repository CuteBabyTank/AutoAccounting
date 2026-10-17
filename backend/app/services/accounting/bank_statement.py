"""Bank statement lines from the extraction reply, the running-balance tie-out, and account lookup (pure)."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.ocr import clean_text
from app.services.accounting.parsing import parse_doc_date, parse_money

_CENT = Decimal("0.01")
_CHECK = re.compile(r"(?:check|chk|cheque|ck)\s*(?:no\.?|#)?\s*#?\s*(\d{3,})|#\s*(\d{3,})", re.IGNORECASE)


@dataclass(frozen=True)
class StatementLine:
    line_no: int
    on: date
    narration: str
    amount: Decimal              # signed: + money into the account (credit on the bank's side), − out
    balance: Decimal | None      # running balance as printed
    check_no: str = ""


@dataclass(frozen=True)
class StatementData:
    bank_name: str
    account_number: str
    period_start: date | None
    period_end: date | None
    opening: Decimal | None
    closing: Decimal | None
    lines: tuple[StatementLine, ...]


def _opt_money(value) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_money(value)


def check_number(ref, narration: str) -> str:
    """The check / reference number: the ``ref`` Gemini read, else "Check #000818" in the narration."""
    text = clean_text(str(ref or "")).strip()
    if text:
        return text[:30]
    found = _CHECK.search(narration or "")
    return (found.group(1) or found.group(2)) if found else ""


def parse_statement(raw: dict | None) -> StatementData | None:
    """The ``statement`` object of one extracted document; None when it has no lines that move money. Never raises."""
    obj = raw.get("statement") if isinstance(raw, dict) else None
    if not isinstance(obj, dict) or not isinstance(obj.get("lines"), list):
        return None
    lines: list[StatementLine] = []
    for item in obj["lines"]:
        if not isinstance(item, dict):
            continue
        on = parse_doc_date(item.get("date"))
        if on is None:
            continue
        narration = clean_text(str(item.get("description") or ""))[:500]
        amount = abs(parse_money(item.get("credit"))) - abs(parse_money(item.get("debit")))
        if amount == 0:  # "Balance forward" and other rows that move no money: nothing to match or post
            continue
        lines.append(StatementLine(len(lines) + 1, on, narration, amount.quantize(_CENT),
                                   _opt_money(item.get("balance")), check_number(item.get("ref"), narration)))
    if not lines:
        return None
    return StatementData(
        bank_name=clean_text(str(obj.get("bank_name") or ""))[:120],
        account_number=clean_text(str(obj.get("account_number") or ""))[:40],
        period_start=parse_doc_date(obj.get("period_start")),
        period_end=parse_doc_date(obj.get("period_end")),
        opening=_opt_money(obj.get("opening_balance")),
        closing=_opt_money(obj.get("closing_balance")),
        lines=tuple(lines),
    )


def tie_out(s: StatementData) -> tuple[bool, list[int]]:
    """Whether opening + lines reaches every printed balance and the closing balance; the lines where it breaks
    (0 = the closing balance). With no opening balance, the first printed balance is the starting point."""
    breaks: list[int] = []
    running = s.opening
    for line in s.lines:
        if running is None:
            running = line.balance - line.amount if line.balance is not None else None
        if running is None:
            continue
        running += line.amount
        if line.balance is not None and abs(running - line.balance) > _CENT:
            breaks.append(line.line_no)
            running = line.balance  # carry on from what the bank printed, so one misread flags one line
    if s.closing is not None and running is not None and abs(running - s.closing) > _CENT:
        breaks.append(0)
    return not breaks, breaks


def last4(number: str) -> str:
    digits = re.sub(r"\D", "", number or "")
    return digits[-4:] if len(digits) >= 4 else ""


def resolve_account(number: str, accounts: Iterable[tuple[str, str]]) -> str | None:
    """The one bank account (code, account no.) whose number ends in the same 4 digits; None if none or several."""
    tail = last4(number)
    if not tail:
        return None
    found = [code for code, account_no in accounts if account_no and last4(account_no) == tail]
    return found[0] if len(found) == 1 else None
