"""Opening open items as the books, the subledger and the bank matcher see them (pure mappers).

An opening item is an invoice or bill outstanding when the books start. Its amount is already inside the opening trial
balance's A/R / A/P, so it enters the books engine as a sale / bill dated the day before the books start: the engine
never posts a document entry for it (documents before the start are in the opening balance) but posts its payments.
The same date puts it inside the bank matcher's window for statement lines from the first months.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.services.accounting.books.chart import Chart
from app.services.accounting.books.receipts import party_key
from app.services.accounting.compute.books import Payment
from app.services.accounting.compute.inputs import DocLine
from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.compute.subledger import OpenDoc
from app.services.accounting.contacts import SeenParty

_CONTROL = {"ar": "ar", "ap": "ap"}


def live(item) -> bool:
    return item.deleted_at is None


def opening_doc_line(item, books_start: date) -> DocLine:
    sale = item.kind == "ar"
    return DocLine(
        id=str(item.id), category="sales" if sale else "purchases", account="opening", doc_type="invoice",
        client_role="seller" if sale else "buyer", doc_date=books_start - timedelta(days=1),
        doc_number=item.doc_number or "", counterparty_tin=item.contact_tin or "",
        counterparty_name=item.contact_name or "", counterparty_address="", gross=c2(item.amount), ewt_atc="NONE",
    )


def opening_payments(items) -> list[Payment]:
    """The payments people recorded on the items (``paid:<id>``, replaced by a matched bank line like ``paid_on``)."""
    return [Payment(f"paid:{i.id}", str(i.id), i.paid_on, None, i.paid_via or "cash", i.doc_number or "",
                    i.paid_account or "")
            for i in items if live(i) and i.paid_on is not None]


def opening_open_doc(item, key_map: dict[str, str], names: dict[str, tuple[str, str]]) -> OpenDoc:
    key = party_key(item.contact_tin or "", item.contact_name or "")
    key = key_map.get(key, key)
    shown_name, shown_tin = names.get(key, (item.contact_name, item.contact_tin))
    return OpenDoc(id=str(item.id), kind=item.kind, contact_key=key, contact_name=shown_name or item.contact_name,
                   contact_tin=shown_tin or item.contact_tin, doc_number=item.doc_number or "",
                   doc_date=item.doc_date, total=c2(item.amount), due_date=item.due_date, terms_days=item.terms_days,
                   opening=True)


def opening_seen_party(item) -> SeenParty:
    role = "customer" if item.kind == "ar" else "supplier"
    return SeenParty(party_key(item.contact_tin or "", item.contact_name or ""), item.contact_tin or "",
                     item.contact_name or "", "", role, None, item.doc_date)


def _under(chart: Chart, code: str, control: str) -> bool:
    seen = set()
    while code and code not in seen:
        if code == control:
            return True
        seen.add(code)
        account = chart.get(code)
        code = account.parent_code if account else None
    return False


def control_balances(lines: list[dict], chart: Chart) -> dict[str, Decimal]:
    """The opening entry's A/R (debit) and A/P (credit) balances, sub-accounts included."""
    out = {"ar": ZERO, "ap": ZERO}
    for kind, key in _CONTROL.items():
        control = chart.code(key)
        for l in lines or []:
            if _under(chart, str(l.get("account_code", "")), control):
                net = c2(l.get("debit") or 0) - c2(l.get("credit") or 0)
                out[kind] += net if kind == "ar" else -net
    return out
