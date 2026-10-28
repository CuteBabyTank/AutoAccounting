"""Which returns a month or quarter files, and the plain-language guide shown beside each (pure)."""

from decimal import Decimal, InvalidOperation

from app.services.accounting.compute.due_dates import month_start
from app.services.accounting.compute.specs import FORM_ORDER
from app.services.accounting.periods import quarter_label

SCOPES = ("M1", "M2", "M3", "Q")
_SCOPE_FORMS = {
    "M1": frozenset({"0619E-M1", "1601C-M1"}),
    "M2": frozenset({"0619E-M2", "1601C-M2"}),
    "M3": frozenset({"1601C-M3"}),  # month 3's expanded withholding is on the 1601-EQ
    "Q": frozenset({"2550Q", "2551Q", "1701Q", "1702Q", "1601EQ"}),
}

_GUIDE = {
    "0619E": "Monthly expanded withholding remittance for months 1 and 2 of the quarter. Due the 10th of the "
             "following month.",
    "1601C": "Monthly withholding on employees' compensation, filed every month. Due the 10th of the following "
             "month (January 15 for December).",
    "1601EQ": "End-of-quarter expanded withholding return. Combines the 0619-Es of months 1 and 2 with month 3 and "
              "lists every ATC. Due the last day of the month after the quarter.",
    "2550Q": "Quarterly VAT return. Due the 25th day after the quarter ends.",
    "2551Q": "Quarterly percentage tax return. Due the 25th day after the quarter ends.",
    "1701Q": "Quarterly income tax (individuals), cumulative from Q1. Q4 is covered by the annual 1701/1701-A.",
    "1702Q": "Quarterly income tax (corporations), cumulative from Q1. Due 60 days after the quarter; Q4 is "
             "covered by the annual 1702-RT.",
}


def _base(form: str) -> str:
    return form.partition("-M")[0]


def scope_forms(expected: list[str], scope: str) -> list[str]:
    if scope not in _SCOPE_FORMS:
        raise ValueError(f"Unknown scope {scope!r}")
    wanted = _SCOPE_FORMS[scope]
    return [form for form in FORM_ORDER if form in wanted and form in expected]


def scope_label(scope: str, year: int, quarter: int, fye: int) -> str:
    if scope == "Q":
        return f"Quarter: {quarter_label(quarter, fye)} {year}"
    month = int(scope[1])
    return f"Month {month}: {month_start(year, quarter, fye, month).strftime('%b %Y')}"


def scope_note(scope: str, quarter: int, forms: list[str]) -> str | None:
    if scope == "Q" and quarter == 4:
        return "Income tax: Q4 is covered by the annual return. See Annual."
    if not forms and scope == "M3":
        return ("No month 3 returns: month 3's expanded withholding goes on the quarter's 1601-EQ, and there's no "
                "payroll to report on a 1601-C.")
    if not forms and scope != "Q":
        return ("No monthly returns: the company isn't a withholding agent on calendar quarters and has no "
                "employees.")
    if not forms:
        return "No quarterly returns apply to this company for this quarter."
    return None


def guide(form: str) -> str:
    return _GUIDE.get(_base(form), "")


def _peso(text: str) -> str:
    try:
        return f"₱{Decimal(text):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return text


def _source(code: str) -> str:
    if code.startswith("filed:"):
        return f"from filed 0619-E {code.partition(':')[2]}"
    return {"entered": "as entered in the quarter inputs", "calculated": "calculated"}.get(code, code)


def source_line(form: str, values: dict[str, str]) -> str | None:
    """Where the 1601-EQ's months 1–2 remittances came from (None when the version predates this)."""
    if form != "1601EQ" or "_SRC_20" not in values:
        return None
    return " · ".join(
        f"Item {item} (month {month}) {_peso(values.get(item, '0'))} {_source(values[f'_SRC_{item}'])}"
        for month, item in ((1, "20"), (2, "21"))
    )
