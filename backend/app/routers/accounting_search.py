"""Global search across the firm: documents, contacts, bank lines, journal entries, tasks and companies.

The query is read by ``services/accounting/search.parse_query`` (text words + a detected amount / TIN / date / review
reason). Each group is one firm-scoped SELECT (ILIKE on trigram-indexed columns when pg_trgm is installed, equality on
amount / TIN / date) ordered exact-first then newest; a few candidates per group are ranked in Python and cut."""

import uuid
from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, Text, and_, case, cast, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.dependencies import get_current_user, get_db
from app.models.accounting import (
    AABankLine, AABankStatement, AACompany, AAContact, AADocument, AAJournalEntry, AATask,
)
from app.models.user import User
from app.routers.accounting_scope import scope_for
from app.schemas.accounting import manila_today
from app.services.accounting.periods import period_for
from app.services.accounting.search import SearchQuery, like_pattern, parse_query, score

router = APIRouter()

GROUP_TYPES = ("document", "contact", "bank_line", "journal_entry", "task", "company")
_UNDATED = frozenset({"contact", "company"})
MAX_LIMIT = 50
SEARCH_COUNT_CAP = 1000
_CANDIDATES = 4  # rows fetched per result shown, ranked in Python


@dataclass(frozen=True)
class Filters:
    company_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    review: bool = False


def groups_for(q: SearchQuery, f: Filters, types: list[str] | None) -> list[str]:
    """Which groups to search: the review filter is documents only (and may have no query); a date range hides
    the groups that have no date (contacts, companies)."""
    wanted = [t for t in GROUP_TYPES if types is None or t in types]
    if f.review:
        return ["document"] if "document" in wanted else []
    if q.too_short or not q.text:
        return []
    if f.date_from or f.date_to:
        wanted = [t for t in wanted if t not in _UNDATED]
    return wanted


def _text(q: SearchQuery, *cols):
    """Every typed word appears in one of the columns (ILIKE, wildcards in the text taken literally)."""
    if not q.tokens:
        return None
    return and_(*[or_(*[c.ilike(like_pattern(t), escape="\\") for c in cols]) for t in q.tokens])


def _tin(q: SearchQuery, *cols):
    if q.tin:
        return or_(*[c == q.tin for c in cols])
    if q.tin_prefix:
        return or_(*[c.like(q.tin_prefix + "%") for c in cols])
    return None


def _dates(q: SearchQuery, col):
    return or_(*[col.between(lo, hi) for lo, hi in q.dates]) if q.dates else None


def _any(*conds):
    conds = [c for c in conds if c is not None]
    return or_(*conds) if conds else false()


def _date_window(f: Filters, col) -> list:
    out = []
    if f.date_from:
        out.append(col >= f.date_from)
    if f.date_to:
        out.append(col <= f.date_to)
    return out


def _company(f: Filters, col) -> list:
    return [col == f.company_id] if f.company_id else []


def _exact(col, q: SearchQuery):
    return case((func.lower(col) == q.text.lower(), 0), else_=1)


def document_query(ent: uuid.UUID, q: SearchQuery, f: Filters, cap: int) -> Select:
    d = AADocument
    conds = [d.enterprise_id == ent, AACompany.enterprise_id == ent, d.deleted_at.is_(None),
             *_company(f, d.company_id), *_date_window(f, d.doc_date)]
    if f.review:
        conds += [d.needs_review.is_(True), d.reviewed.is_(False), d.excluded.is_(False)]
    if q.text:
        amount = (or_(d.gross_amount == q.amount, d.vatable_amount == q.amount, d.vat_amount == q.amount,
                      d.withholding_amount == q.amount) if q.amount is not None else None)
        reasons = or_(*[d.review_reasons.contains([r]) for r in q.reasons]) if q.reasons else None
        conds.append(_any(_text(q, d.doc_number, d.seller_name, d.buyer_name, d.document_title, d.payment_ref),
                          _tin(q, d.seller_tin, d.buyer_tin), amount, _dates(q, d.doc_date), reasons))
        order = [_exact(d.doc_number, q), d.doc_date.desc().nulls_last(), d.created_at.desc()]
    else:
        order = [d.doc_date.desc().nulls_last(), d.created_at.desc()]
    return (select(d, AACompany.registered_name).join(AACompany, AACompany.id == d.company_id)
            .options(defer(d.raw)).where(*conds).order_by(*order).limit(cap))


def contact_query(ent: uuid.UUID, q: SearchQuery, f: Filters, cap: int) -> Select:
    c = AAContact
    match = _any(_text(q, c.registered_name, cast(c.aliases, Text)), _tin(q, c.tin))
    return (select(c, AACompany.registered_name).join(AACompany, AACompany.id == c.company_id)
            .where(c.enterprise_id == ent, AACompany.enterprise_id == ent, c.merged_into_id.is_(None),
                   *_company(f, c.company_id), match)
            .order_by(_exact(c.registered_name, q), c.registered_name).limit(cap))


def bank_query(ent: uuid.UUID, q: SearchQuery, f: Filters, cap: int) -> Select:
    b = AABankLine
    amount = b.amount.in_([q.amount, -q.amount]) if q.amount is not None else None
    match = _any(_text(q, b.narration, b.check_no), amount, _dates(q, b.line_date))
    return (select(b, AABankStatement.document_id, AACompany.registered_name, AACompany.fiscal_year_end_month)
            .join(AABankStatement, AABankStatement.id == b.statement_id)
            .join(AADocument, AADocument.id == AABankStatement.document_id)
            .join(AACompany, AACompany.id == b.company_id)
            .where(b.enterprise_id == ent, AACompany.enterprise_id == ent, AADocument.deleted_at.is_(None),
                   AADocument.excluded.is_(False), *_company(f, b.company_id), *_date_window(f, b.line_date), match)
            .order_by(b.line_date.desc(), b.line_no).limit(cap))


def journal_query(ent: uuid.UUID, q: SearchQuery, f: Filters, cap: int) -> Select:
    j = AAJournalEntry
    match = _any(_text(q, j.particulars, j.reference), _dates(q, j.entry_date))
    return (select(j, AACompany.registered_name, AACompany.fiscal_year_end_month)
            .join(AACompany, AACompany.id == j.company_id)
            .where(j.enterprise_id == ent, AACompany.enterprise_id == ent, j.deleted_at.is_(None),
                   *_company(f, j.company_id), *_date_window(f, j.entry_date), match)
            .order_by(_exact(j.reference, q), j.entry_date.desc()).limit(cap))


def task_query(ent: uuid.UUID, q: SearchQuery, f: Filters, cap: int) -> Select:
    t = AATask
    match = _any(_text(q, t.title, t.notes), _dates(q, t.due_date))
    return (select(t, AACompany.registered_name)
            .outerjoin(AACompany, and_(AACompany.id == t.company_id, AACompany.enterprise_id == ent))
            .where(t.enterprise_id == ent, *_company(f, t.company_id), *_date_window(f, t.due_date), match)
            .order_by(case((t.status == "done", 1), else_=0), t.due_date.asc().nulls_last(), t.created_at.desc())
            .limit(cap))


def company_query(ent: uuid.UUID, q: SearchQuery, f: Filters, cap: int) -> Select:
    c = AACompany
    match = _any(_text(q, c.registered_name, cast(c.aliases, Text)), _tin(q, c.tin))
    return (select(c).where(c.enterprise_id == ent, *_company(f, c.id), match)
            .order_by(_exact(c.registered_name, q), c.registered_name).limit(cap))


def count_query(kind: str, ent: uuid.UUID, q: SearchQuery, f: Filters) -> Select:
    """Count the same joins and filters without sorting or loading records, stopping just past the cap."""
    build = {"document": document_query, "contact": contact_query, "bank_line": bank_query,
             "journal_entry": journal_query, "task": task_query, "company": company_query}[kind]
    query = build(ent, q, f, SEARCH_COUNT_CAP + 1)
    matches = (select(1).select_from(*query.get_final_froms()).where(query.whereclause)
               .limit(SEARCH_COUNT_CAP + 1).subquery())
    return select(func.count()).select_from(matches)


# ---- result items ----------------------------------------------------------------------------------------------

def _hit(q: SearchQuery, *values: str) -> bool:
    words = [t.lower() for t in q.tokens]
    return bool(words) and any(any(w in (v or "").lower() for w in words) for v in values)


def _tin_hit(q: SearchQuery, *tins: str) -> str | None:
    if q.tin and q.tin in tins:
        return "tin"
    if q.tin_prefix and any((t or "").startswith(q.tin_prefix) for t in tins):
        return "tin_prefix"
    return None


def _in_dates(q: SearchQuery, d: date | None) -> bool:
    return d is not None and any(lo <= d <= hi for lo, hi in q.dates)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _finish(item: dict, fields: dict[str, str], q: SearchQuery, structured: set[str], text_hits: list[str]) -> dict:
    item["matched"] = sorted({*text_hits, *("tin" if s == "tin_prefix" else s for s in structured)})
    item["score"] = score(fields, q, structured)
    return item


def document_item(d, company_name: str, q: SearchQuery) -> dict:
    party = d.buyer_name if d.client_role == "seller" else d.seller_name
    kind = d.document_title or d.doc_type.replace("_", " ").capitalize()
    structured: set[str] = set()
    if tin := _tin_hit(q, d.seller_tin, d.buyer_tin):
        structured.add(tin)
    if q.amount is not None and q.amount in (d.gross_amount, d.vatable_amount, d.vat_amount, d.withholding_amount):
        structured.add("amount")
    if _in_dates(q, d.doc_date):
        structured.add("date")
    if set(q.reasons) & set(d.review_reasons or []):
        structured.add("reason")
    hits = [label for label, values in (("number", (d.doc_number,)), ("name", (d.seller_name, d.buyer_name)),
                                        ("reference", (d.payment_ref,))) if _hit(q, *values)]
    item = {
        "type": "document", "id": str(d.id), "document_id": str(d.id), "company_id": str(d.company_id),
        "company_name": company_name, "title": f"{kind} {d.doc_number or '(no number)'}".strip(),
        "subtitle": " · ".join(p for p in (party, company_name) if p), "date": _iso(d.doc_date),
        "amount": f"{d.gross_amount:.2f}", "page": d.page_start, "period_year": d.period_year,
        "period_quarter": d.period_quarter, "category": d.category, "review_reasons": list(d.review_reasons or []),
        "needs_review": bool(d.needs_review and not d.reviewed and not d.excluded), "excluded": bool(d.excluded),
    }
    fields = {"number": d.doc_number, "seller": d.seller_name, "buyer": d.buyer_name, "title": d.document_title}
    return _finish(item, fields, q, structured, hits)


def contact_item(c, company_name: str, q: SearchQuery) -> dict:
    structured = {s} if (s := _tin_hit(q, c.tin)) else set()
    item = {"type": "contact", "id": str(c.id), "company_id": str(c.company_id), "company_name": company_name,
            "title": c.registered_name, "subtitle": " · ".join(p for p in (c.role.capitalize(), company_name) if p),
            "role": c.role, "tin": c.tin, "date": None, "amount": None}
    hits = ["name"] if _hit(q, c.registered_name, *[str(a) for a in (c.aliases or [])]) else []
    return _finish(item, {"name": c.registered_name}, q, structured, hits)


def bank_line_item(b, statement_document_id, company_name: str, fye: int, q: SearchQuery) -> dict:
    structured = set()
    if q.amount is not None and abs(b.amount) == q.amount:
        structured.add("amount")
    if _in_dates(q, b.line_date):
        structured.add("date")
    item = {"type": "bank_line", "id": str(b.id), "company_id": str(b.company_id), "company_name": company_name,
            "title": (b.narration or "Bank line")[:160],
            "subtitle": " · ".join(p for p in (b.account_code or "Account not set", company_name) if p),
            "date": _iso(b.line_date), "amount": f"{b.amount:.2f}", "account_code": b.account_code or "",
            "month": b.line_date.strftime("%Y-%m"), "fiscal_year": period_for(b.line_date, fye).fiscal_year,
            "statement_document_id": str(statement_document_id) if statement_document_id else None,
            "match_status": b.match_status}
    hits = ["narration"] if _hit(q, b.narration, b.check_no) else []
    return _finish(item, {"narration": b.narration, "check": b.check_no}, q, structured, hits)


def journal_item(j, company_name: str, fye: int, q: SearchQuery) -> dict:
    title = " · ".join(p for p in (j.reference, j.particulars) if p) or "Journal entry"
    item = {"type": "journal_entry", "id": str(j.id), "company_id": str(j.company_id), "company_name": company_name,
            "title": title[:200], "subtitle": " · ".join(p for p in (j.book, "Adjusting" if j.is_adjusting else "",
                                                                       company_name) if p),
            "date": _iso(j.entry_date), "amount": None, "reference": j.reference,
            "fiscal_year": period_for(j.entry_date, fye).fiscal_year}
    structured = {"date"} if _in_dates(q, j.entry_date) else set()
    hits = [label for label, v in (("reference", j.reference), ("memo", j.particulars)) if _hit(q, v)]
    return _finish(item, {"reference": j.reference, "memo": j.particulars}, q, structured, hits)


def task_item(t, company_name: str | None, q: SearchQuery) -> dict:
    item = {"type": "task", "id": str(t.id), "company_id": str(t.company_id) if t.company_id else None,
            "company_name": company_name or "", "title": t.title,
            "subtitle": " · ".join(p for p in (t.status.replace("_", " ").capitalize(), company_name or "") if p),
            "date": _iso(t.due_date), "amount": None, "status": t.status}
    structured = {"date"} if _in_dates(q, t.due_date) else set()
    hits = ["title"] if _hit(q, t.title, t.notes) else []
    return _finish(item, {"title": t.title}, q, structured, hits)


def company_item(c, q: SearchQuery) -> dict:
    structured = {s} if (s := _tin_hit(q, c.tin)) else set()
    tin = f"TIN {c.tin[:3]}-{c.tin[3:6]}-{c.tin[6:9]}" if len(c.tin or "") == 9 else ""
    item = {"type": "company", "id": str(c.id), "company_id": str(c.id), "company_name": c.registered_name,
            "title": c.registered_name, "subtitle": tin, "date": None, "amount": None, "tin": c.tin}
    hits = ["name"] if _hit(q, c.registered_name, *[str(a) for a in (c.aliases or [])]) else []
    return _finish(item, {"name": c.registered_name}, q, structured, hits)


def rank(items: list[dict], limit: int) -> tuple[list[dict], bool]:
    """Best score first (SQL order breaks ties: exact, then newest); ``more`` = rows past the limit."""
    ordered = sorted(enumerate(items), key=lambda p: (-p[1]["score"], p[0]))
    return [i for _, i in ordered[:limit]], len(items) > limit


async def _group(db: AsyncSession, kind: str, ent: uuid.UUID, q: SearchQuery, f: Filters, cap: int) -> list[dict]:
    if kind == "document":
        rows = (await db.execute(document_query(ent, q, f, cap))).all()
        return [document_item(d, name, q) for d, name in rows]
    if kind == "contact":
        rows = (await db.execute(contact_query(ent, q, f, cap))).all()
        return [contact_item(c, name, q) for c, name in rows]
    if kind == "bank_line":
        rows = (await db.execute(bank_query(ent, q, f, cap))).all()
        return [bank_line_item(b, doc_id, name, fye, q) for b, doc_id, name, fye in rows]
    if kind == "journal_entry":
        rows = (await db.execute(journal_query(ent, q, f, cap))).all()
        return [journal_item(j, name, fye, q) for j, name, fye in rows]
    if kind == "task":
        rows = (await db.execute(task_query(ent, q, f, cap))).all()
        return [task_item(t, name, q) for t, name in rows]
    rows = (await db.execute(company_query(ent, q, f, cap))).scalars().all()
    return [company_item(c, q) for c in rows]


@router.get("/search")
async def search(
    q: str = Query("", max_length=200),
    types: str | None = Query(None, max_length=120, description="Comma-separated group types"),
    company_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    review: bool = False,
    limit: int = Query(5, ge=1, le=MAX_LIMIT),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    ent = scope_for(user)
    query = parse_query(q, manila_today())
    filters = Filters(company_id=company_id, date_from=date_from, date_to=date_to, review=review)
    wanted = [t.strip() for t in types.split(",")] if types else None
    cap = limit * _CANDIDATES
    groups = []
    for kind in groups_for(query, filters, wanted):
        items, more = rank(await _group(db, kind, ent, query, filters, cap + 1), limit)
        if items:
            groups.append({"type": kind, "items": items, "more": more})
    return {"query": query.text, "too_short": query.too_short and not review, "groups": groups}

