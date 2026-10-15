"""Quarterly VAT return, BIR Form 2550-Q (April 2024 ENCS) — pure."""

from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.compute.cogs import claims_input_vat
from app.services.accounting.compute.inputs import DocLine, PeriodInputs
from app.services.accounting.compute.money import ZERO, c2, total

VAT_RATE = Decimal("0.12")


@dataclass(frozen=True)
class VatResult:
    items: dict[str, Decimal]
    excess_input_vat_out: Decimal


def _is_import(line: DocLine) -> bool:
    return line.account == "importation" or line.doc_type == "import"


def compute_2550q(lines, inputs: PeriodInputs, carry_in: Decimal) -> VatResult:
    sales = [l for l in lines if l.category == "sales"]
    buys = [l for l in lines if l.category in ("purchases", "expenses") and l.client_role == "buyer"]
    claimed = [l for l in buys if claims_input_vat(l, True)]
    unclaimed = [l for l in buys if not claims_input_vat(l, True)]

    i: dict[str, Decimal] = {}
    # Part IV — sales and output tax
    i["31A"] = total(l.vatable for l in sales)
    i["31B"] = c2(i["31A"] * VAT_RATE)
    i["32A"] = total(l.zero_rated for l in sales)
    i["33A"] = total(l.exempt for l in sales)
    i["34A"] = total([i["31A"], i["32A"], i["33A"]])
    i["34B"] = i["31B"]
    i["35B"] = c2(inputs.uncollected_output_vat)
    i["36B"] = c2(inputs.recovered_output_vat)
    i["37B"] = c2(i["34B"] - i["35B"] + i["36B"])
    # Input tax brought forward
    i["38B"] = c2(carry_in)
    for key in ("39B", "40B", "41B", "42B"):
        i[key] = ZERO
    i["43B"] = total(i[k] for k in ("38B", "39B", "40B", "41B", "42B"))
    # Current transactions
    domestic = [l for l in claimed if not _is_import(l)]
    imported = [l for l in claimed if _is_import(l)]
    i["44A"] = total(l.gross - l.vat for l in domestic)
    i["44B"] = total(l.vat for l in domestic)
    i["45A"] = ZERO
    i["45B"] = ZERO
    # An import entry's total is what was paid to Customs; its VAT base is the landed cost.
    i["46A"] = total(l.vatable if l.vatable > 0 else l.gross - l.vat for l in imported)
    i["46B"] = total(l.vat for l in imported)
    i["47A"] = ZERO
    i["47B"] = ZERO
    i["48A"] = total(l.gross for l in unclaimed if not _is_import(l))
    i["49A"] = total(l.gross for l in unclaimed if _is_import(l))
    i["50A"] = total(i[k] for k in ("44A", "45A", "46A", "47A", "48A", "49A"))
    i["50B"] = total(i[k] for k in ("44B", "45B", "46B", "47B"))
    i["51B"] = c2(i["43B"] + i["50B"])
    # Deductions from input tax
    i["52B"] = ZERO
    i["53B"] = c2(i["50B"] * i["33A"] / i["34A"]) if i["33A"] > 0 and i["34A"] > 0 else ZERO
    i["54B"] = ZERO
    i["55B"] = c2(inputs.unpaid_input_vat)
    i["56B"] = ZERO
    i["57B"] = total(i[k] for k in ("52B", "53B", "54B", "55B", "56B"))
    i["58B"] = c2(inputs.settled_input_vat)
    i["59B"] = c2(i["57B"] - i["58B"])  # settled payables restore the input VAT 55B took out
    i["60B"] = c2(i["51B"] - i["59B"])
    i["61B"] = c2(i["37B"] - i["60B"])
    # Part II — total tax payable
    i["15"] = i["61B"]
    i["16"] = c2(inputs.vat_withheld)
    i["17"] = c2(inputs.advance_vat)
    i["18"] = c2(inputs.amended_paid_business_tax)
    i["19"] = ZERO
    i["20"] = total(i[k] for k in ("16", "17", "18", "19"))
    i["21"] = c2(i["15"] - i["20"])
    for key in ("22", "23", "24", "25"):
        i[key] = ZERO
    i["26"] = c2(i["21"] + i["25"])

    excess = c2(-i["61B"]) if i["61B"] < 0 else ZERO
    return VatResult(i, excess)
