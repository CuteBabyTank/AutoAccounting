"""SLS / SLP / SAWT and transaction ledgers for the workbook (pure)."""

from app.services.accounting.compute.cogs import claimed_input_vat, claims_input_vat
from app.services.accounting.compute.money import ZERO, c2, total
from app.services.accounting.compute.vat import VAT_RATE
from app.services.accounting.matching import normalize_name

GOODS_ACCOUNTS = frozenset({"purchases", "raw_materials", "importation", "office_supplies"})


def _party_key(line) -> str:
    return line.counterparty_tin or f"NAME:{normalize_name(line.counterparty_name)}"


def _new_row(key: str, line, money_columns) -> dict:
    row = {"key": key, "tin": line.counterparty_tin, "name": line.counterparty_name,
           "address": line.counterparty_address}
    row.update({column: ZERO for column in money_columns})
    return row


def _sorted(rows: dict[str, dict]) -> list[dict]:
    return sorted(rows.values(), key=lambda r: (r["name"].lower(), r["key"]))


def build_sls(lines) -> list[dict]:
    rows: dict[str, dict] = {}
    for l in lines:
        if l.category != "sales":
            continue
        key = _party_key(l)
        row = rows.setdefault(key, _new_row(key, l, ("exempt", "zero_rated", "taxable")))
        row["exempt"] = c2(row["exempt"] + l.exempt)
        row["zero_rated"] = c2(row["zero_rated"] + l.zero_rated)
        row["taxable"] = c2(row["taxable"] + l.vatable)
    for row in rows.values():
        row["gross_sales"] = total([row["exempt"], row["zero_rated"], row["taxable"]])
        row["output_tax"] = c2(row["taxable"] * VAT_RATE)
    return _sorted(rows)


def build_slp(lines, company_vat: bool) -> list[dict]:
    columns = ("exempt", "zero_rated", "services", "capital_goods", "other_goods", "input_tax")
    rows: dict[str, dict] = {}
    for l in lines:
        if l.category not in ("purchases", "expenses") or l.client_role != "buyer":
            continue
        key = _party_key(l)
        row = rows.setdefault(key, _new_row(key, l, columns))
        if claims_input_vat(l, company_vat):
            if l.account == "capital_goods":
                column = "capital_goods"
            elif l.account in GOODS_ACCOUNTS:
                column = "other_goods"
            else:
                column = "services"
            row[column] = c2(row[column] + l.gross - l.vat)
            row["input_tax"] = c2(row["input_tax"] + claimed_input_vat(l, company_vat))
        else:
            row["exempt"] = c2(row["exempt"] + l.gross)
    for row in rows.values():
        row["gross_purchases"] = total(row[c] for c in columns if c != "input_tax")
    return _sorted(rows)


def build_sawt(lines) -> list[dict]:
    rows = [
        {"key": l.id, "doc_date": l.doc_date.isoformat() if l.doc_date else "", "tin": l.counterparty_tin,
         "name": l.counterparty_name, "income_payment": c2(l.gross), "tax_withheld": c2(l.withholding)}
        for l in lines if l.category == "2307" and l.client_role == "seller"
    ]
    return sorted(rows, key=lambda r: (r["doc_date"], r["name"], r["key"]))


def build_transactions(lines, company_vat: bool, ewt_by_line: dict | None = None) -> list[dict]:
    ewt_by_line = ewt_by_line or {}
    rows = []
    for l in lines:
        atc, due = ewt_by_line.get(l.id, ("", ZERO))
        rows.append({
            "key": l.id, "doc_date": l.doc_date.isoformat() if l.doc_date else "", "doc_number": l.doc_number,
            "counterparty": l.counterparty_name, "tin": l.counterparty_tin, "category": l.category,
            "account": l.account, "gross": c2(l.gross), "vatable": c2(l.vatable), "vat": c2(l.vat),
            "exempt": c2(l.exempt), "zero_rated": c2(l.zero_rated), "withholding": c2(l.withholding),
            "ewt_atc": atc, "ewt_due": c2(due),
            "input_vat_claimed": "yes" if claims_input_vat(l, company_vat) else "no",
            "needs_review": "yes" if l.open_review else "no",
        })
    return sorted(rows, key=lambda r: (r["doc_date"], r["doc_number"], r["key"]))
