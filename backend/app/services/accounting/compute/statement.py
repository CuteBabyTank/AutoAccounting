"""Customer statement activity (pure): the lines of a balance-forward or transaction statement.

Amounts are what the customer owes the company: an invoice's total less the tax the customer withheld (the 2307 they
owe instead), as the aging shows. Payments (receipts, paid-on dates, matched bank lines) and write-offs are credits; a
credit memo (negative total) is a credit on its date. Sales paid at the counter never show.
"""

from datetime import date
from decimal import Decimal

from app.services.accounting.compute.books import Payment
from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.compute.subledger import OpenDoc

_ORDER = {"invoice": 0, "credit": 1, "payment": 2, "writeoff": 3}


def activity(docs: list[OpenDoc], pays: list[tuple[Payment, Decimal]], start: date, end: date) -> dict:
    """``pays`` = (payment, amount it paid) as ``books.subledger.payment_rows`` gives them."""
    live = {d.id: d for d in docs if d.kind == "ar" and not d.paid_at_counter}
    moves: list[dict] = []
    for d in live.values():
        amount = c2(d.total - d.withheld)
        kind = "invoice" if amount >= 0 else "credit"
        moves.append({"date": d.doc_date, "kind": kind, "number": d.doc_number, "ref": "",
                      "charge": amount if amount >= 0 else ZERO, "credit": -amount if amount < 0 else ZERO})
    for p, amount in pays:
        d = live.get(p.settles)
        if d is None or amount == 0:
            continue
        moves.append({"date": p.on, "kind": "writeoff" if p.via == "writeoff" else "payment",
                      "number": d.doc_number, "ref": p.ref or "", "charge": ZERO, "credit": c2(amount)})
    moves.sort(key=lambda m: (m["date"], _ORDER[m["kind"]], m["number"]))
    opening = c2(sum((m["charge"] - m["credit"] for m in moves if m["date"] < start), ZERO))
    balance = opening
    lines = []
    for m in moves:
        if start <= m["date"] <= end:
            balance = c2(balance + m["charge"] - m["credit"])
            lines.append({**m, "charge": c2(m["charge"]), "credit": c2(m["credit"]), "balance": balance})
    return {"start": start, "end": end, "opening": opening, "lines": lines, "closing": balance,
            "charges": c2(sum((l["charge"] for l in lines), ZERO)),
            "credits": c2(sum((l["credit"] for l in lines), ZERO))}
