"""Completion history filtering and aggregation; calendar days are in Manila."""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MANILA = ZoneInfo("Asia/Manila")


@dataclass(frozen=True)
class Completion:
    id: str
    kind: str
    title: str
    company_id: str | None
    company_name: str
    completed_by: str | None
    completed_at: datetime
    assignee_id: str | None
    due_date: date | None
    source: str


def validate_window(start: date, end: date) -> None:
    if start < date(2000, 1, 1) or end > date(2100, 12, 31) or end < start or end - start > timedelta(days=731):
        raise ValueError("Pick a completion window of up to two years (2000–2100)")


def completion_actor(events: list[dict]) -> str | None:
    """Chronological audit evidence: only the latest status transition can identify a completion actor."""
    actor = None
    for event in events:
        after = event.get("after") or {}
        if "status" in after:
            actor = event.get("user_id") if after["status"] == "done" else None
    return actor


def history_page(completions: list[Completion], open_items: list[dict], people: dict[str, str],
                 start: date, end: date, *, person: str | None = None, company: str | None = None,
                 kind: str | None = None, employee_id: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    validate_window(start, end)
    person = employee_id or person
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    summary = {}

    def bucket(pid):
        if pid not in summary:
            summary[pid] = {"person_id": pid, "person_name": people.get(pid, "Unknown"),
                            "completed": 0, "on_time": 0, "late": 0, "open_now": 0}
        return summary[pid]

    for pid in people:
        if not person or person == pid:
            bucket(pid)
    items = []
    for c in completions:
        day = c.completed_at.astimezone(MANILA).date()
        if not start <= day <= end or (person and c.completed_by != person) or \
                (company and c.company_id != company) or (kind and c.kind != kind):
            continue
        on_time = day <= c.due_date if c.due_date else None
        items.append({**asdict(c), "on_time": on_time,
                      "completed_by_name": people.get(c.completed_by, "Unknown"),
                      "assignee_name": people.get(c.assignee_id, "Unknown") if c.assignee_id else "Unassigned"})
        s = bucket(c.completed_by)
        s["completed"] += 1
        s["on_time"] += int(on_time is True)
        s["late"] += int(on_time is False)
    for item in open_items:
        pid = item.get("assignee_id")
        if not pid or (person and person != pid) or (company and item.get("company_id") != company) or \
                (kind and item["kind"] != kind):
            continue
        bucket(pid)["open_now"] += 1
    items.sort(key=lambda i: (i["completed_at"], i["id"]), reverse=True)
    return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset,
            "summary": sorted(summary.values(), key=lambda s: (s["person_name"].casefold(), s["person_id"] or ""))}


def filing_actor(events: list[dict], company_id: str, period: str, form: str, entry: dict) -> str | None:
    """Match the actual filed state, not the output's preparer or an unrelated filing in that period."""
    for event in reversed(events):
        if event.get("company_id") != company_id or event.get("entity_id") != period:
            continue
        after = (event.get("after") or {}).get(form)
        if after and after.get("output_id") == entry.get("output_id") and after.get("filed_at") == entry.get("filed_at"):
            return event.get("user_id")
    return None
