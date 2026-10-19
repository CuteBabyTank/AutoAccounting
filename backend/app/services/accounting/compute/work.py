"""Firm work board: the BIR filings a client owes in a date window, their status and labels (pure).

Which forms come from the engine's rules (``expected_forms`` per quarter, ``annual_form`` per fiscal year, the 1604-C
per calendar year for employers); due dates from ``due_dates``. Status is derived from what the databank holds; a
person can override it, but a real filing always wins.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.services.accounting.compute.annual import annual_form
from app.services.accounting.compute.due_dates import (
    alphalist_due_date, annual_due_date, due_dates, month_start, quarter_end,
)
from app.services.accounting.compute.engine import expected_forms
from app.services.accounting.compute.inputs import CompanyFacts
from app.services.accounting.periods import period_for

STATUSES = ("no_docs", "docs_in", "needs_review", "generated", "filed")
STATUS_LABELS = {"no_docs": "No documents", "docs_in": "Documents in", "needs_review": "Needs review",
                 "generated": "Generated", "filed": "Filed"}
ALPHALIST = "1604C"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Obligation:
    form: str
    year: int          # fiscal year (calendar year for the 1604-C)
    quarter: int       # 1–4; 0 = annual return / 1604-C
    due: date


def _quarters_between(start: date, end: date, fye: int):
    p = period_for(start, fye)
    year, quarter = p.fiscal_year, p.quarter
    last = period_for(end, fye)
    while (year, quarter) <= (last.fiscal_year, last.quarter):
        yield year, quarter
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)


def obligations(facts: CompanyFacts, start: date, end: date, payroll: set[tuple[int, int]],
                employees_years: set[int]) -> list[Obligation]:
    """Every filing due between ``start`` and ``end`` (inclusive). ``payroll`` = (year, quarter)s with payroll
    documents; ``employees_years`` = calendar years with employee rows (1604-C)."""
    fye = facts.fiscal_year_end_month
    out: list[Obligation] = []
    # The latest due date is 60 days (1702-Q) or ~4.5 months (annual) after the period: look back far enough.
    for year, quarter in _quarters_between(start - timedelta(days=200), end, fye):
        forms = expected_forms(facts, quarter, has_payroll=(year, quarter) in payroll)
        for form, due in due_dates(forms, year, quarter, fye).items():
            if start <= due <= end:
                out.append(Obligation(form, year, quarter, due))
    form = annual_form(facts)
    for year in range(start.year - 1, end.year + 1):
        due = annual_due_date(form, year, fye)
        if start <= due <= end:
            out.append(Obligation(form, year, 0, due))
        if facts.has_employees or year in employees_years:
            due = alphalist_due_date(year)
            if start <= due <= end:
                out.append(Obligation(ALPHALIST, year, 0, due))
    return sorted(out, key=lambda o: (o.due, o.form))


def period_end(ob: Obligation, fye: int) -> date:
    if ob.form == ALPHALIST:
        return date(ob.year, 12, 31)
    if ob.quarter == 0:
        return quarter_end(ob.year, 4, fye)
    if ob.form[-3:-1] == "-M":
        first = month_start(ob.year, ob.quarter, fye, int(ob.form[-1]))
        nxt = date(first.year + first.month // 12, first.month % 12 + 1, 1)
        return nxt - timedelta(days=1)
    return quarter_end(ob.year, ob.quarter, fye)


def skip_obligation(ob: Obligation, company_added: date, *, has_data: bool) -> bool:
    """A filing whose deadline had already passed when the client joined the databank, with nothing on file for it,
    isn't the firm's job: it would only show as overdue noise."""
    return not has_data and ob.due < company_added


def derive_status(*, filed: bool, generated: bool, documents: int, open_reviews: int, override: str = "") -> str:
    if filed:
        return "filed"
    if override in STATUSES:
        return override
    if generated:
        return "generated"
    if open_reviews:
        return "needs_review"
    return "docs_in" if documents else "no_docs"


def form_label(form: str) -> str:
    base = form.split("-M")[0]
    if base == ALPHALIST:
        return "1604-C"
    for suffix in ("RT", "EQ", "Q", "E", "C", "A"):
        if base.endswith(suffix) and base[: -len(suffix)].isdigit():
            return f"{base[: -len(suffix)]}-{suffix}"
    return base


def period_text(ob: Obligation, fye: int) -> str:
    if ob.form == ALPHALIST:
        return f"CY {ob.year}"
    if ob.quarter == 0:
        return f"FY {ob.year}" if fye == 12 else f"FY {_MONTHS[fye - 1]} {ob.year}"
    if ob.form[-3:-1] == "-M":
        first = month_start(ob.year, ob.quarter, fye, int(ob.form[-1]))
        return f"{_MONTHS[first.month - 1]} {first.year}"
    return f"Q{ob.quarter} {ob.year}"


def days_left(due: date, today: date) -> int:
    return (due - today).days


def is_overdue(status: str, due: date, today: date) -> bool:
    return status != "filed" and due < today


def filter_cards(cards: list[dict], *, company_id: str | None = None, status: str | None = None,
                 assignee: str | None = None) -> list[dict]:
    """``status`` "open" = anything not filed; ``assignee`` "unassigned" = nobody."""
    out = []
    for c in cards:
        if company_id and str(c["company_id"]) != str(company_id):
            continue
        if status == "open" and c["status"] == "filed":
            continue
        if status and status != "open" and c["status"] != status:
            continue
        if assignee == "unassigned" and c.get("assignee_id") is not None:
            continue
        if assignee and assignee != "unassigned" and str(c.get("assignee_id")) != str(assignee):
            continue
        out.append(c)
    return out


@dataclass(frozen=True)
class PeriodFacts:
    """What the databank holds for one period (a quarter, or a whole fiscal year for the annual return)."""

    documents: int = 0
    open_reviews: int = 0
    generated: bool = False
    filed: tuple[tuple[str, str], ...] = ()     # (form, filed date ISO)


def card(ob: Obligation, fye: int, facts: PeriodFacts, item: dict | None, today: date) -> dict:
    """One board card. ``item`` is the stored work item ({assignee_id, status_override, filed_on}) if any."""
    item = item or {}
    filed = dict(facts.filed)
    real = ob.form in filed
    manual = item.get("filed_on")
    generated = facts.generated and ob.form != ALPHALIST
    auto = derive_status(filed=real, generated=generated, documents=facts.documents, open_reviews=facts.open_reviews)
    status = derive_status(filed=real or manual is not None, generated=generated, documents=facts.documents,
                           open_reviews=facts.open_reviews, override=item.get("status_override") or "")
    return {
        "form": ob.form, "form_label": form_label(ob.form), "year": ob.year, "quarter": ob.quarter,
        "period_label": period_text(ob, fye), "due_date": ob.due, "status": status, "auto_status": auto,
        "status_override": item.get("status_override") or "", "overdue": is_overdue(status, ob.due, today),
        "days_left": days_left(ob.due, today),
        "filed_on": filed[ob.form][:10] if real else (manual.isoformat() if manual else None),
        "filed_source": "return" if real else ("board" if manual else None),
        "assignee_id": item.get("assignee_id"), "documents": facts.documents, "open_reviews": facts.open_reviews,
    }


def year_bounds(start: date, end: date) -> tuple[int, int]:
    """Fiscal years whose filings can fall due in ``start``–``end``: an annual return or 1604-C is due months after its
    year ends (so up to a year before ``start``), and a fiscal year is named for the year it ends (so up to a year
    after ``end``)."""
    return start.year - 1, end.year + 1
