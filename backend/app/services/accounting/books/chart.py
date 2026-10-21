"""Chart of accounts: the standard PH SME chart and the lookups the posting engine uses (pure)."""

from collections.abc import Iterable
from dataclasses import dataclass

ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "cost", "expense")
JOURNAL_BOOKS = ("SJ", "PJ", "CRJ", "CDJ", "GJ")
_DEBIT_TYPES = frozenset({"asset", "cost", "expense"})
_CAPITAL = {"corporation": "Share capital", "individual": "Owner's capital", "partnership": "Partners' capital"}


@dataclass(frozen=True)
class ChartAccount:
    code: str
    name: str
    type: str
    contra: bool = False
    system_key: str | None = None
    parent_code: str | None = None
    active: bool = True

    @property
    def debit_normal(self) -> bool:
        return (self.type in _DEBIT_TYPES) != self.contra


# (code, name, type, contra, system_key); "capital" is renamed per taxpayer type.
_STANDARD = (
    ("1010", "Cash on hand", "asset", False, "cash"),
    ("1020", "Cash in bank", "asset", False, "bank"),
    ("1030", "E-wallet", "asset", False, "ewallet"),
    ("1100", "Accounts receivable - trade", "asset", False, "ar"),
    ("1200", "Merchandise / materials inventory", "asset", False, "inventory"),
    ("1300", "Input VAT", "asset", False, "input_vat"),
    ("1310", "VAT difference – for review", "asset", False, "vat_difference"),
    ("1320", "Creditable withholding tax", "asset", False, "cwt"),
    ("1500", "Property and equipment", "asset", False, "ppe"),
    ("1510", "Accumulated depreciation", "asset", True, "accum_dep"),
    ("2010", "Accounts payable - trade", "liability", False, "ap"),
    ("2100", "Output VAT", "liability", False, "output_vat"),
    ("2110", "VAT payable", "liability", False, "vat_payable"),
    ("2120", "Percentage tax payable", "liability", False, "pt_payable"),
    ("2130", "Expanded withholding tax payable", "liability", False, "ewt_payable"),
    ("2140", "Withholding tax on compensation payable", "liability", False, "wtc_payable"),
    ("2150", "Income tax payable", "liability", False, "it_payable"),
    ("2160", "Salaries payable", "liability", False, "salaries_payable"),
    ("2170", "SSS / PhilHealth / Pag-IBIG payable", "liability", False, "contributions_payable"),
    ("2200", "Loans payable", "liability", False, None),
    ("3010", "Capital", "equity", False, "capital"),
    ("3020", "Retained earnings", "equity", False, "retained_earnings"),
    ("3030", "Drawings", "equity", True, "drawings"),
    ("3900", "Income summary", "equity", False, "income_summary"),
    ("4010", "Sales", "income", False, "sales"),
    ("4020", "Sales returns and discounts", "income", True, "sales_returns"),
    ("4100", "Other income", "income", False, "other_income"),
    ("5010", "Purchases", "cost", False, "doc:purchases"),
    ("5020", "Raw materials", "cost", False, "doc:raw_materials"),
    ("5030", "Importations", "cost", False, "doc:importation"),
    ("5090", "Cost of sales", "cost", False, "cogs"),
    ("6010", "Salaries and wages", "expense", False, "doc:salaries"),
    ("6015", "SSS, PhilHealth and Pag-IBIG contributions", "expense", False, "contributions_expense"),
    ("6020", "Rent", "expense", False, "doc:rent"),
    ("6030", "Utilities", "expense", False, "doc:utilities"),
    ("6040", "Professional fees", "expense", False, "doc:professional_fees"),
    ("6050", "Office supplies", "expense", False, "doc:office_supplies"),
    ("6060", "Representation", "expense", False, "doc:representation"),
    ("6070", "Transportation and travel", "expense", False, "doc:transportation"),
    ("6080", "Repairs and maintenance", "expense", False, "doc:repairs"),
    ("6090", "Taxes and licenses", "expense", False, "doc:taxes_licenses"),
    ("6100", "Depreciation", "expense", False, "depreciation"),
    ("6110", "Percentage tax", "expense", False, "pt_expense"),
    ("6120", "Non-creditable input VAT", "expense", False, "input_vat_expense"),
    ("6900", "Miscellaneous expenses", "expense", False, "doc:other"),
    ("7010", "Income tax expense", "expense", False, "income_tax"),
)


def standard_chart(taxpayer_type: str) -> list[ChartAccount]:
    capital = _CAPITAL.get(taxpayer_type, "Capital")
    return [ChartAccount(code, capital if key == "capital" else name, kind, contra, key)
            for code, name, kind, contra, key in _STANDARD]


def missing_standard(existing: list[ChartAccount], taxpayer_type: str) -> list[ChartAccount]:
    """Standard accounts whose system key and code are both absent (charts seeded before a key was added)."""
    keys = {a.system_key for a in existing if a.system_key}
    codes = {a.code for a in existing}
    return [a for a in standard_chart(taxpayer_type)
            if a.system_key and a.system_key not in keys and a.code not in codes]


def default_books(vat_registered: bool) -> list[str]:
    """Books registered by default: six for VAT taxpayers, four for non-VAT (RMO 29-2002 practice)."""
    return ["SJ", "PJ", "CRJ", "CDJ", "GJ", "GL"] if vat_registered else ["CRJ", "CDJ", "GJ", "GL"]


class Chart:
    def __init__(self, accounts: Iterable[ChartAccount]):
        self._by_code = {a.code: a for a in accounts}
        self._by_key = {a.system_key: a.code for a in self._by_code.values() if a.system_key}

    @property
    def accounts(self) -> list[ChartAccount]:
        return sorted(self._by_code.values(), key=lambda a: a.code)

    def get(self, code: str) -> ChartAccount | None:
        return self._by_code.get(code)

    def code(self, system_key: str) -> str:
        try:
            return self._by_key[system_key]
        except KeyError:
            raise KeyError(f"The chart of accounts has no account for {system_key!r}") from None

    def name(self, code: str) -> str:
        account = self._by_code.get(code)
        return account.name if account else code

    def doc_account(self, account: str, override: str = "") -> str:
        """The chart account a document account posts to; an active override (sub-account) wins."""
        chosen = self._by_code.get(override) if override else None
        if chosen is not None and chosen.active:
            return chosen.code
        if account == "drawings":
            return self.code("drawings")
        if account == "capital_goods":
            return self.code("ppe")
        return self._by_key.get(f"doc:{account}") or self.code("doc:other")
