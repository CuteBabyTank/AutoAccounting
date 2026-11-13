"""The formats a firm can use in the Extract tab, and the pure decisions behind building and saving one.

A firm sees the built-ins (in a fixed order) with its own copy of a built-in (`base_key`) in that built-in's place,
then its own formats by name. A format is keyed by the built-in key or the firm row's id.

Saving never takes definitions from the browser: the person sends keys, labels, required flags and check ids, and
the fields and checks come from the stored draft (and the current format when editing).
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AAExtractFormat
from app.services.accounting.extract import builtins, guard, spec

DRAFT_HOURS = 24
FIELD_KEYS = ("key", "label", "type", "scope", "required", "description")


def _fmt(key: str, name: str, description: str, builtin: bool, edited: bool, fields: list, checks: list,
         detect_hint: str, version: int) -> dict[str, Any]:
    return {"key": key, "name": name, "description": description, "builtin": builtin, "edited": edited,
            "fields": list(fields or []), "checks": list(checks or []), "detect_hint": detect_hint or "",
            "version": version}


def from_row(row: Any) -> dict[str, Any]:
    return _fmt(str(row.id), row.name, row.description or "", False, row.base_key in builtins.BUILTINS,
                row.fields, row.checks, row.detect_hint, row.version)


def overlay(firm_rows: list) -> list[dict]:
    """Built-ins in fixed order, each replaced by the firm's live copy of it, then the firm's own formats by name."""
    live = [r for r in firm_rows if getattr(r, "deleted_at", None) is None]
    copies = {r.base_key: r for r in live if r.base_key in builtins.BUILTINS}
    out = []
    for key, b in builtins.BUILTINS.items():
        copy = copies.get(key)
        out.append(from_row(copy) if copy is not None else
                   _fmt(key, b["name"], b["description"], True, False, b["fields"], b["checks"], b["detect_hint"], 0))
    own = sorted((r for r in live if r.base_key not in builtins.BUILTINS), key=lambda r: (r.name.casefold(), r.name))
    return out + [from_row(r) for r in own]


def find(listing: list[dict], key: str) -> dict | None:
    """The format with this key in an `overlay` listing; a built-in key also reaches the firm's copy that replaced
    it (overlay keeps the built-ins' places first, in BUILTINS order)."""
    for fmt in listing:
        if fmt["key"] == key:
            return fmt
    if key in builtins.BUILTINS:
        place = list(builtins.BUILTINS).index(key)
        return listing[place] if place < len(listing) and listing[place]["edited"] else None
    return None


async def firm_formats(db: AsyncSession, ent: uuid.UUID) -> list[dict]:
    rows = (await db.execute(select(AAExtractFormat).where(
        AAExtractFormat.enterprise_id == ent, AAExtractFormat.deleted_at.is_(None)))).scalars().all()
    return overlay(list(rows))


async def resolve(db: AsyncSession, ent: uuid.UUID, key: str) -> dict:
    """The firm's format for a key (built-in key or row id). Raises ValueError when the firm has no such format."""
    fmt = find(await firm_formats(db, ent), key) if isinstance(key, str) else None
    if fmt is None:
        raise ValueError("Unknown format")
    return fmt


def _with_sentences(checks: list[dict], fields: list[dict]) -> list[dict]:
    return [{**c, "sentence": spec.sentence(c, fields)} for c in checks]


def out(fmt: dict) -> dict:
    """A format for the screen: each check carries its plain sentence."""
    return {**fmt, "checks": _with_sentences(fmt["checks"], fmt["fields"])}


# ── drafts ────────────────────────────────────────────────────────────────

def fresh_proposal(proposal: dict) -> dict:
    """A new format's proposal: every field starts switched on."""
    return {**proposal, "fields": [{**f, "picked": True} for f in proposal["fields"]]}


def merge_for_edit(current: dict, proposal: dict) -> dict:
    """The current format's fields first (switched on, with the value read from the new sample), then the sample's
    fields whose key is new (switched off); checks unioned by id, current first. Name and hint stay the current's."""
    values = {f["key"]: f["value"] for f in proposal.get("fields", []) if f.get("value")}
    fields = []
    for f in current.get("fields", []):
        merged = {**{k: f[k] for k in FIELD_KEYS if k in f}, "picked": True}
        if f["key"] in values:
            merged["value"] = values[f["key"]]
        fields.append(merged)
    known = {f["key"] for f in fields}
    fields += [{**f, "picked": False} for f in proposal.get("fields", []) if f["key"] not in known]
    checks = list(current.get("checks", []))
    seen = {c["id"] for c in checks}
    checks += [c for c in proposal.get("checks", []) if c["id"] not in seen]
    return {"name": current.get("name") or proposal.get("name", ""),
            "detect_hint": current.get("detect_hint") or proposal.get("detect_hint", ""),
            "fields": fields[:spec.MAX_FIELDS], "checks": checks}


def draft_out(draft_id: uuid.UUID, proposal: dict, asks: int, page_count: int) -> dict:
    fields = [{**f, "value": f.get("value", ""), "picked": f.get("picked", True)} for f in proposal["fields"]]
    return {"id": str(draft_id), "name": proposal.get("name", ""), "detect_hint": proposal.get("detect_hint", ""),
            "fields": fields, "checks": _with_sentences(proposal["checks"], proposal["fields"]),
            "asks_left": max(0, guard.ASKS_PER_DRAFT - asks), "page_count": page_count}


def draft_expired(created_at: datetime, now: datetime) -> bool:
    return now - created_at > timedelta(hours=DRAFT_HOURS)


def ask_problem(asks: int, added: int) -> str | None:
    """Why another missing-fields ask is refused for this draft, or None."""
    if asks >= guard.ASKS_PER_DRAFT:
        return "No tries left for this sample."
    if added >= guard.ADDED_PER_DRAFT:
        return f"At most {guard.ADDED_PER_DRAFT} fields can be added from one sample."
    return None


def append_found(proposal: dict, found: list[dict], room: int) -> tuple[dict, list[dict]]:
    """Add fields found by a missing-fields ask (switched on, keys made unique), skipping labels the proposal already
    has, at most `room` and never past the field cap. New TIN / date fields get their default checks, listed first so the check cap can't crowd them out."""
    fields = list(proposal["fields"])
    labels = {f["label"].casefold() for f in fields}
    taken = {f["key"] for f in fields}
    added: list[dict] = []
    for f in found:
        if len(added) >= room or len(fields) >= spec.MAX_FIELDS:
            break
        if f["label"].casefold() in labels:
            continue
        key = f["key"] if f["key"] not in taken else spec._key_from(f["label"], taken)
        field = {**f, "key": key, "picked": True}
        taken.add(key)
        labels.add(f["label"].casefold())
        fields.append(field)
        added.append(field)
    checks = spec.clean_checks(spec.default_checks(added) + list(proposal["checks"]), fields) if added \
        else list(proposal["checks"])
    return {**proposal, "fields": fields, "checks": checks}, added


def _norm(text: str) -> str:
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text.casefold()).split())


def not_found(names: list[str], found: list[dict]) -> list[str]:
    """Names the reader found nothing for. A name matches a found field by label or key (one containing the other);
    found fields left unmatched are then paired with the remaining names in order (the reader renames labels)."""
    left = list(found)
    unmatched = []
    for name in names:
        n = _norm(name)
        hit = next((f for f in left if n and any(n == t or n in t or t in n
                                                 for t in (_norm(f["label"]), _norm(f["key"])) if t)), None)
        if hit is None:
            unmatched.append(name)
        else:
            left.remove(hit)
    return unmatched[len(left):]


# ── saving ────────────────────────────────────────────────────────────────

def known_for_save(current: dict | None, proposal: dict | None) -> dict:
    """What a save may pick from: the draft's proposal, merged onto the current format when editing."""
    if proposal is None:
        return current
    if current is None:
        return proposal
    return merge_for_edit(current, proposal)


def build_save(known: dict, picks: list[dict], check_ids: list[str]) -> tuple[list[dict], list[dict]]:
    """The fields and checks to store. Raises ValueError for an unknown key or when no field is picked."""
    fields, checks = spec.apply_picks(known["fields"], known["checks"], picks, check_ids)
    if not fields:
        raise ValueError("Pick at least one field")
    return [{k: f[k] for k in FIELD_KEYS} for f in fields], checks


def builtin_name_clash(name: str, base_key: str | None) -> bool:
    """A firm format may not take a built-in's name, except a copy of that built-in."""
    return any(b["name"].casefold() == name.casefold() and key != base_key for key, b in builtins.BUILTINS.items())


def audit_view(name: str, description: str, version: int, fields: list[dict], checks: list[dict]) -> dict:
    return {"name": name, "description": description, "version": version, "fields": [f["key"] for f in fields],
            "checks": [c["id"] for c in checks]}
