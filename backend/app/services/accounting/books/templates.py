"""Chart-of-accounts templates (built-in by industry, or a firm's own saved from a company) and where an account
lands on the financial statements (pure)."""

import re

from app.services.accounting.books.chart import (
    _CAPITAL, ACCOUNT_TYPES, Chart, ChartAccount, missing_standard, standard_chart,
)
from app.services.accounting.compute.statements import _key, _root

_REVENUE = {"sales", "sales_returns"}

# Built-in templates: the standard PH chart (the engine needs every system account) plus industry sub-accounts.
# key → (label, description, ((code, name, parent code), …))
BUILTIN_TEMPLATES: dict[str, tuple[str, str, tuple[tuple[str, str, str], ...]]] = {
    "trading": ("Trading", "Standard chart plus freight-in, store supplies, communication, advertising, insurance.", (
        ("5011", "Freight-in", "5010"),
        ("6031", "Communication", "6030"),
        ("6051", "Store supplies", "6050"),
        ("6901", "Advertising and promotion", "6900"),
        ("6902", "Insurance", "6900"),
    )),
    "services": ("Services", "Standard chart plus subcontracting, software, communication, fuel, insurance.", (
        ("4011", "Service revenue", "4010"),
        ("6031", "Communication", "6030"),
        ("6041", "Subcontracting and outside services", "6040"),
        ("6052", "Software subscriptions", "6050"),
        ("6071", "Fuel and oil", "6070"),
        ("6902", "Insurance", "6900"),
    )),
    "manufacturing": ("Manufacturing", "Standard chart plus direct labor, factory overhead and supplies, freight-in.", (
        ("5011", "Freight-in", "5010"),
        ("5021", "Direct labor", "5020"),
        ("5022", "Factory overhead", "5020"),
        ("5023", "Factory supplies", "5020"),
        ("6031", "Communication", "6030"),
        ("6081", "Repairs - machinery", "6080"),
        ("6902", "Insurance", "6900"),
    )),
    "non_vat": ("Non-VAT", "Standard chart plus communication and insurance. The VAT accounts stay (the books need "
                           "them) and simply remain empty for a non-VAT taxpayer.", (
        ("6031", "Communication", "6030"),
        ("6901", "Advertising and promotion", "6900"),
        ("6902", "Insurance", "6900"),
    )),
}


def placement(chart: Chart, code: str) -> str:
    """Where an account lands: "Profit and loss · Operating expenses", "Balance sheet · Assets (reduces the total)" …
    (sub-accounts land where their parent does)."""
    account = chart.get(code)
    if account is None:
        return ""
    root = _root(chart, code) or account
    key = _key(chart, code)
    if account.type == "income":
        if key in _REVENUE:
            return "Profit and loss · Revenue" + (" (reduces net sales)" if account.contra else "")
        return "Profit and loss · Other income"
    if account.type == "cost":
        return "Profit and loss · Cost of sales"
    if account.type == "expense":
        tax = root.system_key == "income_tax"
        return "Profit and loss · " + ("Income tax expense" if tax else "Operating expenses")
    section = {"asset": "Assets", "liability": "Liabilities", "equity": "Equity"}.get(account.type, "")
    return f"Balance sheet · {section}" + (" (reduces the total)" if account.contra else "")


def template_rows(accounts: list[ChartAccount]) -> list[dict]:
    """A chart as stored in a template (no bank numbers, no locks: those belong to one company)."""
    return [{"code": a.code, "name": a.name, "type": a.type, "contra": a.contra, "system_key": a.system_key,
             "parent_code": a.parent_code, "active": a.active} for a in sorted(accounts, key=lambda a: a.code)]


def _builtin(key: str, taxpayer_type: str) -> list[ChartAccount]:
    standard = standard_chart(taxpayer_type)
    by_code = {a.code: a for a in standard}
    extra = []
    for code, name, parent in BUILTIN_TEMPLATES[key][2]:
        p = by_code[parent]
        extra.append(ChartAccount(code, name, p.type, p.contra, None, parent))
    return standard + extra


def template_accounts(source: str | list[dict], taxpayer_type: str) -> list[ChartAccount]:
    """The accounts a new company gets from a built-in template key or stored template rows (raises ValueError)."""
    if isinstance(source, str):
        if source not in BUILTIN_TEMPLATES:
            raise ValueError(f"Unknown template {source!r}")
        return _builtin(source, taxpayer_type)
    capital_names = set(_CAPITAL.values()) | {"Capital"}
    out: list[ChartAccount] = []
    codes: set[str] = set()
    keys: set[str] = set()
    for row in source:
        code, name = str(row.get("code", "")).strip(), str(row.get("name", "")).strip()[:120]
        kind, key = row.get("type"), row.get("system_key") or None
        if not re.fullmatch(r"\d{4,10}", code):
            raise ValueError(f"Account code {code!r} must be 4 to 10 digits")
        if kind not in ACCOUNT_TYPES:
            raise ValueError(f"Account {code} has an unknown type {kind!r}")
        if not name:
            raise ValueError(f"Account {code} has no name")
        if code in codes or (key and key in keys):
            raise ValueError(f"Account {code} appears twice in the template")
        codes.add(code)
        if key:
            keys.add(key)
            if key == "capital" and name in capital_names:
                name = _CAPITAL.get(taxpayer_type, "Capital")
        out.append(ChartAccount(code, name, kind, bool(row.get("contra")), key, row.get("parent_code") or None,
                                bool(row.get("active", True))))
    for a in out:
        if a.parent_code and a.parent_code not in codes:
            raise ValueError(f"Account {a.code}'s parent {a.parent_code} isn't in the template")
    return out + missing_standard(out, taxpayer_type)
