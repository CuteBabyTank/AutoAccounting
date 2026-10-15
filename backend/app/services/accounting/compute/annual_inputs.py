"""Annual return inputs and the Q1–Q3 income tax credit (pure)."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.services.accounting.compute.carryover import CarryRow, rows_from_json
from app.services.accounting.compute.money import ZERO, c2

_OPTIONAL = ("ending_inventory", "non_operating_income", "prior_year_excess_credits", "q1_paid", "q2_paid",
             "q3_paid", "current_assets", "ppe_net", "other_noncurrent_assets", "current_liabilities",
             "noncurrent_liabilities", "equity", "book_net_income")
_AMOUNTS = ("amended_paid_income_tax", "nondeductible_expenses", "nontaxable_income", "other_reconciling",
            "pre_books_sales", "pre_books_cost_of_sales", "pre_books_deductions", "pre_books_cwt",
            "compensation_income", "compensation_nontaxable", "compensation_tax_withheld")
_FLAGS = ("cit_20_percent", "refund_overpayment")


@dataclass(frozen=True)
class AnnualInputs:
    ending_inventory: Decimal | None = None
    non_operating_income: Decimal | None = None
    prior_year_excess_credits: Decimal | None = None
    q1_paid: Decimal | None = None
    q2_paid: Decimal | None = None
    q3_paid: Decimal | None = None
    amended_paid_income_tax: Decimal = ZERO
    cit_20_percent: bool = False
    refund_overpayment: bool = False
    current_assets: Decimal | None = None
    ppe_net: Decimal | None = None
    other_noncurrent_assets: Decimal | None = None
    current_liabilities: Decimal | None = None
    noncurrent_liabilities: Decimal | None = None
    equity: Decimal | None = None
    book_net_income: Decimal | None = None
    nondeductible_expenses: Decimal = ZERO
    nontaxable_income: Decimal = ZERO
    other_reconciling: Decimal = ZERO
    # The fiscal year's months before the books start (a client that moved onto AutoAccounting mid-year):
    pre_books_sales: Decimal = ZERO            # net sales / receipts
    pre_books_cost_of_sales: Decimal = ZERO    # cost of sales (inventory carried in sits in the first quarter)
    pre_books_deductions: Decimal = ZERO       # itemized deductions
    pre_books_cwt: Decimal = ZERO              # creditable tax withheld (2307s received)
    # A mixed-income individual's salary for the year, from the employer's BIR 2316 (1701 Schedules 1–2):
    compensation_income: Decimal = ZERO        # gross compensation
    compensation_nontaxable: Decimal = ZERO    # non-taxable / exempt (13th month up to the cap, de minimis, contributions)
    compensation_tax_withheld: Decimal = ZERO  # tax withheld per 2316 (Part VII item 5)
    opening_nolco: tuple[CarryRow, ...] = field(default_factory=tuple)
    opening_excess_mcit: tuple[CarryRow, ...] = field(default_factory=tuple)


def _money(raw) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return c2(raw)
    except (InvalidOperation, TypeError, ValueError):
        return None


def annual_inputs_from_json(data: dict | None) -> AnnualInputs:
    data = data if isinstance(data, dict) else {}
    kwargs: dict = {}
    for name in _OPTIONAL + _AMOUNTS:
        value = _money(data.get(name))
        if value is not None:
            kwargs[name] = value
    for name in _FLAGS:
        kwargs[name] = bool(data.get(name, False))
    kwargs["opening_nolco"] = tuple(CarryRow(r.year, r.amount, r.used)
                                    for r in rows_from_json(data.get("opening_nolco")))
    kwargs["opening_excess_mcit"] = tuple(CarryRow(r.year, r.amount, r.used)
                                          for r in rows_from_json(data.get("opening_excess_mcit")))
    return AnnualInputs(**kwargs)


def _rows(rows) -> list[dict]:
    return [{"year": r.year, "amount": str(r.amount), "used": str(r.used)} for r in rows]


def annual_inputs_to_json(inputs: AnnualInputs) -> dict:
    out: dict = {}
    for name in _OPTIONAL + _AMOUNTS:
        value = getattr(inputs, name)
        out[name] = None if value is None else str(value)
    for name in _FLAGS:
        out[name] = getattr(inputs, name)
    out["opening_nolco"] = _rows(inputs.opening_nolco)
    out["opening_excess_mcit"] = _rows(inputs.opening_excess_mcit)
    return out


@dataclass(frozen=True)
class QuarterSource:
    """What a quarterly income tax return says was payable: its filed version, else its latest."""

    quarter: int
    payable: Decimal | None = None
    version: int | None = None
    filed: bool = False
    latest_version: int | None = None


def quarter_credits(sources: dict, inputs: AnnualInputs, cwt_by_quarter: dict) -> tuple[list[dict], Decimal, list[str]]:
    rows: list[dict] = []
    warnings: list[str] = []
    paid_total = ZERO
    overrides = {1: inputs.q1_paid, 2: inputs.q2_paid, 3: inputs.q3_paid}
    for q in (1, 2, 3):
        src = sources.get(q) or QuarterSource(q)
        if overrides[q] is not None:
            source, paid = "entered", c2(overrides[q])
        elif src.payable is not None and src.version is not None:
            source = f"{'filed' if src.filed else 'latest'} v{src.version}"
            paid = max(c2(src.payable), ZERO)  # an overpayment paid nothing
            if src.filed and src.latest_version and src.latest_version > src.version:
                warnings.append(f"Q{q} has v{src.latest_version}, newer than the filed v{src.version}. The annual "
                                "return credits the tax paid on the filed version.")
        else:
            source, paid = "none", ZERO
            warnings.append(f"There is no Q{q} income tax return on AutoAccounting, so Q{q} tax paid was taken as "
                            f"₱0. Enter it in the annual inputs if Q{q} was filed elsewhere.")
        paid_total = c2(paid_total + paid)
        rows.append({"key": f"Q{q}", "quarter": f"Q{q}", "source": source, "tax_paid": paid,
                     "cwt": c2(cwt_by_quarter.get(q, ZERO))})
    rows.append({"key": "Q4", "quarter": "Q4", "source": "this return", "tax_paid": ZERO,
                 "cwt": c2(cwt_by_quarter.get(4, ZERO))})
    return rows, paid_total, warnings
