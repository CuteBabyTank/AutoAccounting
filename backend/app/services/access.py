"""Per-person access: the firm owner (or a manager, for employees) turns areas off for one person, and sets what
Casper may do for them. Pure rules; stored as ``users.access`` = ``{"off": [feature keys], "assistant": level}``.

Layering (most restrictive wins): the platform admin's maintenance switches → the person's own access. Casper:
the person's level when set, else the firm default (``aa_firm_settings.assistant_writes`` by role). The firm
setting "off" still turns changes off for everyone. The firm owner and the platform admin always have full access.
"""

from collections.abc import Iterable

# Areas a person can be given or refused. ``assistant`` / ``assistant_write`` are set with the Casper level instead.
PERSONAL_KEYS: tuple[str, ...] = (
    "documents", "upload", "search", "notifications", "work", "companies", "team",
    "filing", "annual", "employees", "books", "close", "recurring", "bank", "subledgers",
    "reports", "reclassify", "imports", "atc", "audit",
)
ASSISTANT_LEVELS = ("off", "read", "write")  # missing = the firm default

LEVEL_WORDS = {"off": "Casper off", "read": "Casper: ask only", "write": "Casper: can make changes"}


def clean(access: dict | None) -> dict:
    """Normalise stored or submitted access: known keys only, sorted, no duplicates; an unknown level is dropped."""
    access = access if isinstance(access, dict) else {}
    off = sorted({k for k in access.get("off") or [] if k in PERSONAL_KEYS})
    out: dict = {"off": off}
    if access.get("assistant") in ASSISTANT_LEVELS:
        out["assistant"] = access["assistant"]
    return out


def restricted(role: str) -> bool:
    """Only firm members (employees, managers) can be limited; owners and the platform admin never are."""
    return role in ("employee", "manager")


def apply(enabled: dict[str, bool], access: dict | None, role: str) -> dict[str, bool]:
    """The firm's on/off switches narrowed by one person's access."""
    if not restricted(role):
        return dict(enabled)
    a = clean(access)
    out = dict(enabled)
    for key in a["off"]:
        if key in out:
            out[key] = False
    level = a.get("assistant")
    if level == "off":
        out["assistant"] = False
    if level in ("off", "read") and "assistant_write" in out:
        out["assistant_write"] = False
    return out


def blocked_personally(key: str, firm_enabled: dict[str, bool], access: dict | None, role: str) -> bool:
    """On for the firm, off for this person (a 403 'ask your firm owner', not a 503 'maintenance')."""
    return firm_enabled.get(key, True) and not apply(firm_enabled, access, role).get(key, True)


def can_manage(caller_role: str, member_role: str) -> bool:
    """The owner sets anyone's access; a manager sets employees' only (as for activating members)."""
    if caller_role == "enterprise":
        return True
    return caller_role == "manager" and member_role == "employee"


def summary(access: dict | None, labels: dict[str, str]) -> str:
    """One line for the Team list: 'Full access', '3 areas off · Casper: ask only'."""
    a = clean(access)
    parts = []
    if a["off"]:
        parts.append(f"{labels.get(a['off'][0], a['off'][0])} off" if len(a["off"]) == 1 else f"{len(a['off'])} areas off")
    if "assistant" in a:
        parts.append(LEVEL_WORDS[a["assistant"]])
    return " · ".join(parts) or "Full access"


def changed_keys(before: dict | None, after: dict | None) -> Iterable[str]:
    b, a = clean(before), clean(after)
    yield from sorted(set(b["off"]) ^ set(a["off"]))
    if b.get("assistant") != a.get("assistant"):
        yield "assistant"
