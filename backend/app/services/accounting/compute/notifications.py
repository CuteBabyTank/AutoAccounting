"""Notifications, derived on read from the work board, client health and tasks (pure).

A notification's key names what it is about and, where the situation can change, how it stands (a count, a due
date), so dismissing "3 documents need review" doesn't hide "5 documents need review" later.
"""

from dataclasses import dataclass
from datetime import date, timedelta

_SEVERITY = {"high": 0, "normal": 1}


@dataclass(frozen=True)
class Notification:
    key: str
    kind: str              # deadline | review | bank | cwt | task_assigned | task_due
    title: str
    detail: str
    company_id: str | None
    due_date: date | None
    severity: str          # high | normal


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def build(*, user_id: str, cards: list[dict], summaries: dict[str, dict], cwt: dict[str, tuple[int, int]],
          tasks: list[dict], today: date, days: int) -> list[Notification]:
    """``cards`` from the board, ``summaries`` the cheap per-company counts, ``cwt`` company → (pending, overdue),
    ``tasks`` dicts with id, title, assignee_id, due_date, status, company_id, company_name."""
    horizon = today + timedelta(days=days)
    out: list[Notification] = []
    for c in cards:
        if c["status"] == "filed" or c["due_date"] > horizon:
            continue
        if c.get("assignee_id") and str(c["assignee_id"]) != user_id:
            continue
        late = c["due_date"] < today
        when = "was due" if late else "is due"
        out.append(Notification(
            f"deadline:{c['key']}", "deadline",
            f"{c['form_label']} {c['period_label']} {when} {c['due_date']:%d %b}",
            c["company_name"], c["company_id"], c["due_date"], "high" if late else "normal"))
    for cid, s in summaries.items():
        if s.get("open_reviews"):
            n = s["open_reviews"]
            out.append(Notification(f"review:{cid}:{n}", "review", f"{_plural(n, 'document')} to review",
                                    s["company_name"], cid, None, "normal"))
        if s.get("unreconciled_months"):
            n = s["unreconciled_months"]
            out.append(Notification(f"bank:{cid}:{n}", "bank", f"{_plural(n, 'bank statement month')} not reconciled",
                                    s["company_name"], cid, None, "normal"))
        late_2307 = cwt.get(cid, (0, 0))[1]
        if late_2307:
            out.append(Notification(f"cwt:{cid}:{late_2307}", "cwt", f"{_plural(late_2307, '2307')} still missing",
                                    s["company_name"], cid, None, "normal"))
    for t in tasks:
        if t["status"] == "done" or str(t.get("assignee_id") or "") != user_id:
            continue
        where = t.get("company_name") or ""
        out.append(Notification(f"task:{t['id']}:assigned", "task_assigned", f"Task for you: {t['title']}", where,
                                t.get("company_id"), t.get("due_date"), "normal"))
        due = t.get("due_date")
        if due is not None and due <= horizon:
            late = due < today
            out.append(Notification(f"task:{t['id']}:due:{due.isoformat()}", "task_due",
                                    f"{t['title']} {'was due' if late else 'is due'} {due:%d %b}", where,
                                    t.get("company_id"), due, "high" if late else "normal"))
    return sorted(out, key=lambda n: (_SEVERITY[n.severity], n.due_date or date.max, n.kind, n.title))
