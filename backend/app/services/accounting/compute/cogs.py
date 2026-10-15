"""Cost of goods sold (pure)."""

from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.compute.inputs import CompanyFacts, DocLine
from app.services.accounting.compute.money import ZERO, c2, total


def claims_input_vat(line: DocLine, company_vat: bool) -> bool:
    return company_vat and line.input_vat_valid is True and line.vat > 0


def is_capital_goods(line: DocLine) -> bool:
    """A purchase of a long-lived asset: depreciated through the asset register, never expensed."""
    return line.account == "capital_goods" and line.category in ("purchases", "expenses") and line.client_role == "buyer"


def cost_base(line: DocLine, company_vat: bool) -> Decimal:
    """What a purchase or expense costs the business: VAT-exclusive only when its input VAT is claimed."""
    if claims_input_vat(line, company_vat):
        return c2(line.gross - line.vat)
    return c2(line.gross)


@dataclass(frozen=True)
class CogsResult:
    beginning_inventory: Decimal
    purchases: Decimal
    ending_inventory: Decimal
    cost_of_sales: Decimal
    ending_provided: bool


def compute_cogs(lines, company: CompanyFacts, beginning: Decimal, ending: Decimal | None) -> CogsResult:
    """Beginning inventory + purchases − ending inventory (services carry no inventory)."""
    if company.business_type == "services":
        return CogsResult(ZERO, ZERO, ZERO, ZERO, True)
    purchases = total(cost_base(l, company.vat_registered) for l in lines
                      if l.category == "purchases" and not is_capital_goods(l))
    end = c2(ending) if ending is not None else ZERO
    begin = c2(beginning)
    return CogsResult(begin, purchases, end, c2(begin + purchases - end), ending is not None)


def cogs_form(result: CogsResult) -> dict[str, Decimal]:
    return {
        "beginning_inventory": result.beginning_inventory,
        "purchases": result.purchases,
        "goods_available": c2(result.beginning_inventory + result.purchases),
        "ending_inventory": result.ending_inventory,
        "cost_of_sales": result.cost_of_sales,
    }
