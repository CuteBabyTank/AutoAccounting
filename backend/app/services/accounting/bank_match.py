"""Match bank statement lines to what they pay or collect (pure).

A candidate needs the exact amount (or, for a partial payment, a smaller line whose narration names the payee and
the document) inside a date window. The narration decides: a candidate is *strong* when the narration names its payee
(or a learned payee rule does) or carries its document / check number, and *conflicting* when the narration names
someone else. Only a single strong candidate links by itself; amount and date alone never do. Lines nothing pays
become suggested postings (bank charges, interest, transfers) or wait for review.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.inputs import DocLine
from app.services.accounting.compute.money import ZERO, c2

BANK_REVIEW_REASONS = ("bank_match_ambiguous", "bank_line_unmatched")
DAYS_BEFORE = 7      # a line may come a few days before the document date (cheque dated ahead, deposit first)
DAYS_AFTER = 90
_PAYROLL_WORDS = ("payroll", "salary", "salaries", "wages")
_MONTHS = ("jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july august "
           "september october november december")
_STOP = frozenset((
    "check chk cheque pos deposit deposits cash online transfer transfers fund funds credit credits debit debits memo "
    "payment payments pay paid bills bill billing service services charge charges fee fees atm withdrawal interest "
    "earned tax ref reference from for the and via instapay pesonet partial store sales sale employees employee net "
    "gross total auto adjustment encashment branch account acct savings current checking mobile internet banking "
    "inward outward remittance received receipt purchase purchases inc corp corporation company ltd limited ent "
    "enterprise enterprises trading center centre phil philippines city government municipality gas station shop mart "
    "new dated "
    + _MONTHS).split())


@dataclass(frozen=True)
class Candidate:
    kind: str                       # document | tax | journal
    ref: str
    on: date
    amount: Decimal                 # still open, > 0
    direction: str                  # in | out (money into / out of the bank account)
    payee: str
    numbers: tuple[str, ...] = ()   # document number, check / payment reference
    label: str = ""
    keywords: tuple[str, ...] = ()  # more words that name this payee (payroll: payroll, salary …)
    payee_tin: str = ""
    partial_ok: bool = True


@dataclass(frozen=True)
class BankLineFact:
    id: str
    on: date
    amount: Decimal                 # signed
    narration: str
    check_no: str = ""
    account_code: str = ""


@dataclass(frozen=True)
class Rule:
    pattern: str                    # name tokens, space separated; all must be in the narration
    direction: str                  # in | out | any
    kind: str                       # payee | posting
    account_code: str = ""
    payee_name: str = ""
    payee_tin: str = ""


@dataclass(frozen=True)
class Match:
    status: str                     # matched | suggested | ambiguous | unmatched
    kind: str = ""                  # document | tax | journal | posting
    ref: str = ""
    amount: Decimal | None = None
    posting: dict = field(default_factory=dict)       # {kind, key | account, label}
    candidates: tuple[dict, ...] = ()
    reason: str = ""


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _ordered_names(text: str) -> list[str]:
    seen: list[str] = []
    for w in _words(text):
        if len(w) >= 3 and w not in _STOP and w not in seen:
            seen.append(w)
    return seen


def name_tokens(text: str) -> set[str]:
    """Words in a narration or payee name that identify somebody (bank, corporate and month words dropped)."""
    return set(_ordered_names(text))


def _number_groups(number: str) -> set[str]:
    groups = re.findall(r"\d+", number or "")
    keep = {g.lstrip("0") for g in groups if len(g) >= 3 and not (len(g) == 4 and 2000 <= int(g) <= 2100)}
    return {g for g in keep if g}


def _direction(amount: Decimal) -> str:
    return "in" if amount > 0 else "out"


def _rule_applies(rule: Rule, line: BankLineFact, words: set[str]) -> bool:
    pattern = set(rule.pattern.split())
    return bool(pattern) and pattern <= words and rule.direction in ("any", _direction(line.amount))


def _strength(line: BankLineFact, c: Candidate, rules: Iterable[Rule]) -> tuple[str, bool]:
    """('strong' | 'weak' | 'conflict', number hit) for a candidate against the line's narration."""
    words = tokens(line.narration)
    names = name_tokens(line.narration)
    payee = name_tokens(c.payee) | set(c.keywords)
    payee_hit = bool(payee & words)
    if not payee_hit:
        payee_hit = any(r.kind == "payee" and _rule_applies(r, line, words)
                        and ((r.payee_tin and r.payee_tin == c.payee_tin) or
                             (r.payee_name and name_tokens(r.payee_name) == name_tokens(c.payee)))
                        for r in rules)
    numbers = {g for n in c.numbers for g in _number_groups(n)}
    said = {g for g in _number_groups(line.narration + " " + line.check_no)}
    number_hit = bool(numbers & said)
    if payee_hit or number_hit:
        return "strong", number_hit
    return ("conflict" if names else "weak"), False


def _in_window(line: BankLineFact, c: Candidate) -> bool:
    days = (line.on - c.on).days
    return -DAYS_BEFORE <= days <= DAYS_AFTER


def _alt(c: Candidate, strength: str) -> dict:
    return {"kind": c.kind, "ref": c.ref, "label": c.label, "amount": str(c2(c.amount)), "date": c.on.isoformat(),
            "strength": strength}


_TRANSFER = {"kind": "transfer", "key": "cash", "label": "Transfer from cash on hand"}


def _builtin_posting(line: BankLineFact, words: set[str], own_accounts: Iterable[tuple[str, str]]) -> tuple[dict, bool] | None:
    """(posting, safe to link without a person) from what the narration says."""
    incoming = line.amount > 0
    if incoming and "cash" in words and "deposit" in words:
        return dict(_TRANSFER), True
    charge_words = bool({"service", "bank"} & words and {"charge", "charges", "fee", "fees"} & words)
    if not incoming and (charge_words or {"svc", "chg"} <= words):
        return {"kind": "bank_charges", "key": "bank_charges", "label": "Bank charges"}, False
    if incoming and "interest" in words:
        return {"kind": "interest", "key": "interest_income", "label": "Interest income"}, False
    if not incoming and ({"atm", "withdrawal", "encashment"} & words):
        return {"kind": "transfer", "key": "cash", "label": "Transfer to cash on hand"}, False
    if "transfer" in words:
        said = {g[-4:] for g in re.findall(r"\d{4,}", line.narration)}
        for code, number in own_accounts:
            if number and re.sub(r"\D", "", number)[-4:] in said:
                label = "Transfer from" if incoming else "Transfer to"
                return {"kind": "transfer", "account": code, "label": f"{label} {code}"}, False
    return None


def match_line(line: BankLineFact, candidates: Iterable[Candidate], rules: Iterable[Rule] = (),
               rejected: Iterable[str] = (), own_accounts: Iterable[tuple[str, str]] = ()) -> Match:
    rules, rejected = list(rules), set(rejected)
    amount = c2(abs(line.amount))
    direction = _direction(line.amount)
    pool = [c for c in candidates if c.direction == direction and c.ref not in rejected and c.amount > 0
            and _in_window(line, c)]
    exact = [(c, *_strength(line, c, rules)) for c in pool if c2(c.amount) == amount]
    strong = [c for c, s, _ in exact if s == "strong"]
    others = tuple(_alt(c, s) for c, s, _ in exact if s != "strong")
    if len(strong) == 1:
        c = strong[0]
        return Match("matched", c.kind, c.ref, amount, candidates=others)
    if len(strong) > 1:
        return Match("ambiguous", candidates=tuple(_alt(c, "strong") for c in strong) + others,
                     reason="bank_match_ambiguous")

    words = tokens(line.narration)
    partial = [(c, hit) for c in pool if c.partial_ok and c2(c.amount) > amount
               for s, hit in [_strength(line, c, rules)] if s == "strong" and (hit or "partial" in words)]
    if partial:
        if any(hit for _, hit in partial):
            partial = [(c, hit) for c, hit in partial if hit]
        if len(partial) == 1:
            c = partial[0][0]
            return Match("matched", c.kind, c.ref, amount, candidates=others)
        return Match("ambiguous", candidates=tuple(_alt(c, "partial") for c, _ in partial) + others,
                     reason="bank_match_ambiguous")

    learned = next((r for r in rules if r.kind == "posting" and _rule_applies(r, line, words)), None)
    if learned is not None:
        return Match("suggested", "posting", amount=amount, candidates=others,
                     posting={"kind": "rule", "account": learned.account_code, "label": f"Rule: {learned.pattern}"})
    builtin = _builtin_posting(line, words, own_accounts)
    if builtin is not None:
        posting, safe = builtin
        status = "matched" if safe and not others else "suggested"
        return Match(status, "posting", amount=amount, posting=posting, candidates=others)
    if others:
        return Match("ambiguous", candidates=others, reason="bank_match_ambiguous")
    return Match("unmatched", reason="bank_line_unmatched")


def match_all(lines: Iterable[BankLineFact], candidates: Iterable[Candidate], rules: Iterable[Rule] = (),
              rejected: dict[str, set[str]] | None = None,
              own_accounts: Iterable[tuple[str, str]] = ()) -> dict[str, Match]:
    """Match lines in date order; what a line takes from a candidate's open amount is gone for later lines."""
    pool = {c.ref: c for c in candidates}
    rules, own_accounts, rejected = list(rules), list(own_accounts), rejected or {}
    out: dict[str, Match] = {}
    for line in sorted(lines, key=lambda l: (l.on, l.id)):
        m = match_line(line, pool.values(), rules, rejected.get(line.id, ()), own_accounts)
        out[line.id] = m
        if m.status == "matched" and m.ref in pool:
            c = pool[m.ref]
            pool[m.ref] = replace(c, amount=c2(c.amount - (m.amount or ZERO)))
    return out


def learn_rule(line: BankLineFact, kind: str, candidate: Candidate | None, account_code: str) -> Rule | None:
    """A rule from a match a person confirmed: which payee a bare narration means, or which account a line posts to."""
    direction = _direction(line.amount)
    if kind == "posting":
        words = [w for w in _words(line.narration) if len(w) >= 3]
        return Rule(" ".join(words[:3]), direction, "posting", account_code=account_code) if words and account_code \
            else None
    if candidate is None or _strength(line, candidate, ())[0] == "strong":
        return None   # the narration already names the payee
    names = _ordered_names(line.narration)
    if not names:
        return None
    return Rule(" ".join(names[:3]), direction, "payee", payee_name=candidate.payee, payee_tin=candidate.payee_tin)


def due_amount(l: DocLine, ewt: dict[str, Decimal], contributions: dict[str, Decimal]) -> Decimal:
    """What the counterparty pays / is paid in cash (shared with the books engine)."""
    if l.category == "sales":
        return c2(l.gross - l.withholding)
    if l.category in ("purchases", "expenses"):
        return c2(l.gross - ewt.get(l.id, ZERO))
    if l.category == "payroll":
        return c2(l.gross - l.withholding - contributions.get(l.id, ZERO))
    return ZERO


def open_items(lines: Iterable[DocLine], ewt: dict[str, Decimal], contributions: dict[str, Decimal],
               paid: dict[str, Decimal], refs: dict[str, str] | None = None) -> list[Candidate]:
    """Sales, bills and payroll with something left to collect or pay, as candidates."""
    out: list[Candidate] = []
    for l in lines:
        if l.doc_date is None:
            continue
        selling = l.category == "sales" and l.client_role == "seller"
        buying = l.category in ("purchases", "expenses", "payroll") and l.client_role == "buyer"
        if not (selling or buying):
            continue
        left = c2(due_amount(l, ewt, contributions) - paid.get(l.id, ZERO))
        if left <= 0:
            continue
        payroll = l.category == "payroll"
        name = l.counterparty_name or ("Payroll" if payroll else "")
        out.append(Candidate(
            "document", l.id, l.doc_date, left, "in" if selling else "out", l.counterparty_name,
            tuple(n for n in (l.doc_number, (refs or {}).get(l.id, "")) if n),
            " · ".join(p for p in (l.doc_number, name) if p), _PAYROLL_WORDS if payroll else (), l.counterparty_tin,
        ))
    return out
