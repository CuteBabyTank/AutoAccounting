"""Maintenance switches: the platform admin turns a feature off (for everyone, or one firm) while it's fixed.

The catalog (``FEATURES``) is the single list the admin panel and the frontend read. Enforcement is one table,
``ROUTES``: each API route template maps to at most one feature, and ``feature_gate`` (a dependency on the
accounting and team routers) refuses a request whose feature is off. The platform admin is never blocked, so they
can keep testing a feature that's hidden from firms. A new route under ``/api/accounting`` or ``/api/team`` must be
added to ``ROUTES`` or ``ALWAYS_ON`` (``tests/test_features.py`` checks).

State is tiny (a few dozen rows), so it's read whole and cached per instance for ``_TTL`` seconds; writes on this
instance clear the cache at once, other instances catch up within the TTL.
"""

import logging
import re
import time
import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.feature_toggle import FeatureToggle, FirmFeatureOverride
from app.models.user import User, UserRole

logger = logging.getLogger("admin")

# (key, label, group, what it covers). Groups order the admin panel.
FEATURES: tuple[tuple[str, str, str, str], ...] = (
    ("documents", "Documents", "Pages", "The Documents page: company tree, quarter folders, document panel"),
    ("work", "Work board", "Pages", "Work board, tasks and checklists"),
    ("companies", "Companies", "Pages", "Companies page: add and edit companies, chart templates"),
    ("team", "Team", "Pages", "Team page: firm staff and managers"),
    ("upload", "Uploads", "Documents", "Dropping files and Gemini extraction"),
    ("search", "Search", "Documents", "Global search (/ or Cmd-K)"),
    ("assistant", "Assistant", "Tools", "The AI assistant chat (read-only questions about clients, books and filings)"),
    ("notifications", "Notifications", "Documents", "The notification bell"),
    ("filing", "Quarterly returns", "Filing", "Generate, edit, download and mark filed (2550-Q, 1601-EQ…)"),
    ("annual", "Annual returns", "Filing", "Annual return folder (1701, 1702-RT)"),
    ("employees", "Employees", "Filing", "Employees, 1604-C alphalist and 2316s"),
    ("books", "Books", "Books", "Journals, ledgers, chart edits, bound books"),
    ("close", "Month close", "Books", "Closing and reopening months"),
    ("recurring", "Recurring entries", "Books", "Recurring journal templates"),
    ("bank", "Bank", "Books", "Bank statements, matching and reconciliation"),
    ("subledgers", "Customers & suppliers", "Books", "A/R and A/P, aging, statements, write-offs, 2307 tracking"),
    ("reports", "Reports", "Tools", "Live reports, management pack, KPI and cash tiles"),
    ("reclassify", "Reclassify", "Tools", "Bulk reclassify"),
    ("imports", "Import", "Tools", "Opening TB, open items and journal imports"),
    ("atc", "ATC databank", "Tools", "Supplier and account ATC defaults"),
    ("audit", "Audit log", "Tools", "The company audit log"),
)
KEYS: tuple[str, ...] = tuple(f[0] for f in FEATURES)
LABELS: dict[str, str] = {f[0]: f[1] for f in FEATURES}

_A = "/api/accounting"
_ID = "[^/]+"
_WRITE = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# (methods or None for all, regex on the request path, feature). Ids match ``[^/]+``, so a pattern fits both the
# route template and a real path. First match wins, so specific rows come first.
ROUTES: tuple[tuple[frozenset[str] | None, re.Pattern[str], str], ...] = tuple(
    (methods, re.compile(pattern), key) for methods, pattern, key in (
        (None, rf"^{_A}/uploads/(latest|{_ID}/move-company)$", "documents"),   # fixing a drop, not uploading
        (frozenset({"POST"}), rf"^{_A}/uploads", "upload"),
        (None, rf"^{_A}/documents/{_ID}/cwt-2307$", "subledgers"),
        (None, rf"^{_A}/(tree|folders|documents|duplicates|files)(/|$)", "documents"),
        (_WRITE, rf"^{_A}/companies(/{_ID})?$", "companies"),
        (_WRITE, rf"^{_A}/(companies/{_ID}/coa-template|coa-templates)(/|$)", "companies"),
        (None, rf"^{_A}/(work|tasks|checklist-templates)(/|$)", "work"),
        (None, rf"^{_A}/notifications(/|$)", "notifications"),
        (None, rf"^{_A}/search$", "search"),
        (None, rf"^{_A}/assistant(/|$)", "assistant"),
        (None, rf"^{_A}/companies/{_ID}/books/(close|reopen)$", "close"),
        (None, rf"^{_A}/companies/{_ID}/(journal-entries|books)(/|$)", "books"),
        (None, rf"^{_A}/journal-entries/", "books"),
        (_WRITE, rf"^{_A}/(companies/{_ID}/accounts|accounts/{_ID})$", "books"),
        (None, rf"^{_A}/(companies/{_ID}/recurring-entries|recurring-entries)(/|$)", "recurring"),
        (None, rf"^{_A}/(companies/{_ID}/bank|bank-[a-z]+)(/|$)", "bank"),
        (None, rf"^{_A}/(companies/{_ID}/(contacts|aging|writeoffs)|contacts)(/|$)", "subledgers"),
        (None, rf"^{_A}/companies/{_ID}/(reports|report-postings|report-source|kpis|cash-forecast|pack)(/|$)",
         "reports"),
        (None, rf"^{_A}/companies/{_ID}/reclassify(/|$)", "reclassify"),
        (None, rf"^{_A}/(companies/{_ID}/(imports|opening-items)|imports|import-batches|opening-items)(/|$)",
         "imports"),
        (None, rf"^{_A}/(companies/{_ID}/employees|employees|alphalist-status)(/|$)", "employees"),
        (None, rf"^{_A}/companies/{_ID}/atc-databank(/|$)", "atc"),
        (None, rf"^{_A}/audit-events$", "audit"),
        (None, rf"^{_A}/periods/{_ID}/{_ID}/annual(/|$)", "annual"),
        (None, rf"^{_A}/periods/{_ID}/{_ID}/{_ID}/(generate|filed|filed-forms|inputs)(/|$)", "filing"),
        (None, rf"^{_A}/outputs/", "filing"),
        (None, r"^/api/team(/|$)", "team"),
    )
)

# Shared lookups every screen needs; never switched off (turning off a page hides it, not these).
ALWAYS_ON: frozenset[str] = frozenset({
    f"{_A}/companies",                                  # GET: the company list
    f"{_A}/companies/{{company_id}}/accounts",          # GET: chart for account pickers
    f"{_A}/uploads/pending", f"{_A}/uploads/{{upload_id}}",
    f"{_A}/periods/{{company_id}}/{{year}}/{{quarter}}",  # the quarter folder's documents
    f"{_A}/companies/{{company_id}}/health",
    f"{_A}/companies/{{company_id}}/assets", f"{_A}/assets/{{asset_id}}",
    f"{_A}/coa-templates", f"{_A}/coa-templates/{{template_id}}",
    f"{_A}/atc-codes",                                  # the ATC pickers' list
})


def feature_for_route(method: str, path: str) -> str | None:
    """The feature a request to ``path`` (a real path or its route template) belongs to, or None (always on)."""
    for methods, pattern, key in ROUTES:
        if (methods is None or method in methods) and pattern.search(path):
            return key
    return None


def resolve(toggles: dict[str, bool], overrides: dict[str, bool]) -> dict[str, bool]:
    """Effective on/off per key for one firm: its override, else the global switch, else on."""
    return {k: overrides.get(k, toggles.get(k, True)) for k in KEYS}


def firm_of(user: User) -> uuid.UUID | None:
    if user.role == UserRole.ENTERPRISE:
        return user.id
    return user.enterprise_id


# ---- state (cached) ---------------------------------------------------------------------------

_TTL = 15.0
_cache: tuple[float, dict[str, bool], dict[uuid.UUID, dict[str, bool]]] | None = None


def invalidate() -> None:
    global _cache
    _cache = None


async def load_state(db: AsyncSession) -> tuple[dict[str, bool], dict[uuid.UUID, dict[str, bool]]]:
    """``(global switches, {firm: overrides})`` from the DB, cached for ``_TTL`` seconds."""
    global _cache
    now = time.monotonic()
    if _cache and _cache[0] > now:
        return _cache[1], _cache[2]
    toggles = {r.key: r.enabled for r in (await db.execute(select(FeatureToggle))).scalars()}
    overrides: dict[uuid.UUID, dict[str, bool]] = {}
    for r in (await db.execute(select(FirmFeatureOverride))).scalars():
        overrides.setdefault(r.enterprise_id, {})[r.key] = r.enabled
    _cache = (now + _TTL, toggles, overrides)
    return toggles, overrides


async def effective_for(db: AsyncSession, user: User) -> dict[str, bool]:
    toggles, overrides = await load_state(db)
    firm = firm_of(user)
    return resolve(toggles, overrides.get(firm, {}) if firm else {})


def off_message(key: str) -> str:
    return f"{LABELS.get(key, key)} is turned off for maintenance. Please try again later."


async def feature_gate(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Router dependency: 503 when the request's feature is off for the caller's firm (the admin passes)."""
    if user.role == UserRole.ADMIN:
        return
    key = feature_for_route(request.method, request.url.path)
    if key is None:
        return
    if not (await effective_for(db, user))[key]:
        logger.info("feature_blocked key=%s user=%s path=%s", key, user.id, request.url.path)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=off_message(key))
