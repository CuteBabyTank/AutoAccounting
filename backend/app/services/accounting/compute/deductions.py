"""Itemized deductions for a quarter, with the representation cap applied year to date (pure)."""

from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.compute.cogs import cost_base
from app.services.accounting.compute.inputs import CompanyFacts
from app.services.accounting.compute.money import ZERO, c2, total

_CAP_GOODS = Decimal("0.005")     # RR 10-2002: 0.5% of net sales
_CAP_SERVICES = Decimal("0.01")   # 1% of net revenue


@dataclass(frozen=True)
class ExpenseBreakdown:
    by_account: dict[str, Decimal]
    payroll: Decimal
    contributions: Decimal
    capital_goods: Decimal
    representation: Decimal
    representation_allowed: Decimal
    representation_disallowed_ytd: Decimal
    deductions: Decimal


def quarter_expenses(lines, company: CompanyFacts, rep_ytd_before: Decimal, allowed_ytd_before: Decimal,
                     sales_ytd: Decimal, contributions: Decimal = ZERO) -> tuple[ExpenseBreakdown, Decimal, Decimal]:
    """``contributions``: the employer's SSS / PhilHealth / Pag-IBIG share, from the payroll inputs."""
    by_account: dict[str, Decimal] = {}
    capital = ZERO
    deductible = ("expenses", "purchases") if company.business_type == "services" else ("expenses",)
    for l in lines:
        if l.category not in deductible:  # trading/manufacturing purchases go through cost of sales
            continue
        amount = cost_base(l, company.vat_registered)
        if l.account == "capital_goods":
            capital = c2(capital + amount)
            continue
        by_account[l.account] = c2(by_account.get(l.account, ZERO) + amount)
    payroll = total(l.gross for l in lines if l.category == "payroll")
    representation = by_account.get("representation", ZERO)

    rep_ytd = c2(rep_ytd_before + representation)
    rate = _CAP_SERVICES if company.business_type == "services" else _CAP_GOODS
    allowed_ytd = min(rep_ytd, c2(sales_ytd * rate))
    allowed_q = c2(allowed_ytd - allowed_ytd_before)
    other = total(v for k, v in by_account.items() if k != "representation")
    breakdown = ExpenseBreakdown(
        by_account=dict(sorted(by_account.items())),
        payroll=payroll,
        contributions=c2(contributions),
        capital_goods=capital,
        representation=representation,
        representation_allowed=allowed_q,
        representation_disallowed_ytd=c2(rep_ytd - allowed_ytd),
        deductions=c2(other + payroll + contributions + allowed_q),
    )
    return breakdown, rep_ytd, allowed_ytd


def expenses_form(b: ExpenseBreakdown, depreciation: Decimal = ZERO) -> dict[str, Decimal]:
    form = {k: v for k, v in b.by_account.items() if k != "representation"}
    if b.payroll:
        form["payroll"] = b.payroll
    if b.contributions:
        form["contributions"] = b.contributions
    form["representation"] = b.representation
    form["representation_allowed"] = b.representation_allowed
    form["representation_disallowed_ytd"] = b.representation_disallowed_ytd
    form["capital_goods_not_expensed"] = b.capital_goods
    form["depreciation"] = c2(depreciation)
    form["total_deductions"] = c2(b.deductions + depreciation)
    return form
