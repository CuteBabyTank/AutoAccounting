"""Contacts master (customers / suppliers) planned from documents, deduped by TIN, with safe merges (pure).

A contact is keyed by the counterparty's TIN, else by its normalized name (``books.receipts.party_key``). Every
name seen for one key beyond the current one is kept as an alias. Fields a person edited (``manual``) are never
overwritten. A merged contact points at its target (``merged_into_id``); its documents count for the target.
"""

from dataclasses import dataclass
from datetime import date

from app.services.accounting.books.receipts import party_key

ROLES = ("customer", "supplier", "both")
EDITABLE = ("registered_name", "role", "address", "vat_status", "payment_terms_days")


@dataclass(frozen=True)
class SeenParty:
    key: str
    tin: str
    name: str
    address: str
    role: str                  # customer | supplier
    vat: bool | None           # supplier printed a VAT REG TIN
    on: date | None


def contact_key(tin: str, name: str) -> str:
    return party_key(tin or "", name or "")


def role_union(a: str, b: str) -> str:
    if not a:
        return b
    if not b or a == b:
        return a
    return "both"


def _vat(value: bool | None) -> str:
    return "" if value is None else ("vat" if value else "non_vat")


def resolve(key: str, rows: list):
    """The contact a key counts for, following merges (a broken cycle stops at the last row seen)."""
    by_key = {r.key: r for r in rows}
    by_id = {str(r.id): r for r in rows}
    row = by_key.get(key)
    seen: set[str] = set()
    while row is not None and row.merged_into_id is not None and str(row.id) not in seen:
        seen.add(str(row.id))
        nxt = by_id.get(str(row.merged_into_id))
        if nxt is None:
            break
        row = nxt
    return row


def merge_check(source, target, rows: list) -> str | None:
    """Why ``source`` can't be merged into ``target`` (None when it can)."""
    if str(source.id) == str(target.id):
        return "A contact can't be merged into itself."
    if str(source.company_id) != str(target.company_id):
        return "Both contacts must belong to the same company."
    if source.merged_into_id is not None:
        return "This contact is already merged into another one."
    if target.merged_into_id is not None:
        return "Pick the contact it was merged into instead."
    if resolve(target.key, rows) is source:
        return "That would merge the two contacts into each other."
    return None


def plan_contacts(seen: list[SeenParty], existing: list) -> tuple[list[dict], dict[str, dict]]:
    """(contacts to create, {key: field updates}) so the master covers every party seen on the documents."""
    grouped: dict[str, list[SeenParty]] = {}
    for s in seen:
        if s.key and s.key != "NAME:":
            grouped.setdefault(s.key, []).append(s)
    creates: list[dict] = []
    updates: dict[str, dict] = {}
    for key, group in grouped.items():
        group.sort(key=lambda s: (s.on or date.min))
        latest = group[-1]
        role = ""
        for s in group:
            role = role_union(role, s.role)
        names = list(dict.fromkeys(s.name.strip() for s in group if s.name.strip()))
        address = next((s.address for s in reversed(group) if s.address.strip()), "")
        vat = next((_vat(s.vat) for s in reversed(group) if s.vat is not None), "")
        row = resolve(key, existing)
        if row is None:
            creates.append({"key": key, "tin": latest.tin, "role": role, "registered_name": latest.name.strip(),
                            "aliases": [n for n in names if n != latest.name.strip()], "address": address,
                            "vat_status": vat})
            continue
        own = row.key == key           # a merged source's facts don't overwrite its target's
        manual = set(row.manual or [])
        change: dict = {}
        name = row.registered_name
        if own and "registered_name" not in manual and latest.name.strip() and latest.name.strip() != name:
            change["registered_name"] = name = latest.name.strip()
        current = updates.get(row.key, {})
        old_role = current.get("role", row.role)
        wanted_role = role_union(old_role, role)
        if "role" not in manual and wanted_role != old_role:
            change["role"] = wanted_role
        if own and "address" not in manual and address and address != row.address:
            change["address"] = address
        if own and "vat_status" not in manual and vat and vat != row.vat_status:
            change["vat_status"] = vat
        aliases = list(current.get("aliases", row.aliases or []))
        extra = [n for n in names + ([row.registered_name] if name != row.registered_name else [])
                 if n and n != name and n not in aliases]
        if extra:
            change["aliases"] = aliases + list(dict.fromkeys(extra))
        if change:
            updates.setdefault(row.key, {}).update(change)
    return creates, updates
