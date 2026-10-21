"""Deterministic assignment decisions. No database or mutations of the input facts."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    enterprise_id: str | None
    role: str
    is_active: bool = True


def plan_assignments(items: list[dict], people: list[Member], ent: str, handlers: dict[str, str | None],
                     open_counts: dict[str, int], recent_counts: dict[str, int]) -> dict[str, str]:
    members = {p.id: p for p in people if p.is_active and (
        (p.id == ent and p.role in ("admin", "enterprise")) or
        (p.enterprise_id == ent and p.role in ("manager", "employee")))}
    if not members:
        return {}
    loads, recent = dict(open_counts), dict(recent_counts)
    assigned = {}
    for item in items:
        if item.get("assignee_id") or item.get("status") in ("done", "filed"):
            continue
        handler = handlers.get(item.get("company_id"))
        chosen = handler if handler in members else min(members, key=lambda pid: (
            loads.get(pid, 0), recent.get(pid, 0), members[pid].name.casefold(), pid))
        assigned[item["key"]] = chosen
        loads[chosen] = loads.get(chosen, 0) + 1
        recent[chosen] = recent.get(chosen, 0) + 1
    return assigned
