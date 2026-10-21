"""A simple cash projection (pure): the books' cash today plus open A/R minus open A/P by due date, week by week.

Overdue items are listed apart and not assumed collected or paid; items due after the last week are summed as
"later". Without books there is no opening balance, so only the flows are shown.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.compute.subledger import OpenItem

MAX_WEEKS = 26


def projection(opening: Decimal | None, items: list[OpenItem], as_of: date, weeks: int) -> dict:
    weeks = max(1, min(weeks, MAX_WEEKS))
    # week 1 also takes what falls due on the as-of date itself
    bounds = [(as_of + timedelta(days=7 * n + 1), as_of + timedelta(days=7 * (n + 1))) for n in range(weeks)]
    flows = [[ZERO, ZERO] for _ in bounds]
    overdue = [ZERO, ZERO]
    later = [ZERO, ZERO]
    for i in items:
        side = 0 if i.doc.kind == "ar" else 1
        if i.due < as_of:
            overdue[side] += i.open
            continue
        n = max(0, (i.due - as_of).days - 1) // 7
        if n >= weeks:
            later[side] += i.open
        else:
            flows[n][side] += i.open
    rows = []
    balance = c2(opening) if opening is not None else None
    for (start, end), (inflow, outflow) in zip(bounds, flows):
        net = c2(inflow - outflow)
        if balance is not None:
            balance = c2(balance + net)
        rows.append({"start": start, "end": end, "inflow": c2(inflow), "outflow": c2(outflow), "net": net,
                     "closing": balance})
    return {"as_of": as_of, "opening": c2(opening) if opening is not None else None, "weeks": rows,
            "closing": balance, "overdue_in": c2(overdue[0]), "overdue_out": c2(overdue[1]),
            "later_in": c2(later[0]), "later_out": c2(later[1])}
