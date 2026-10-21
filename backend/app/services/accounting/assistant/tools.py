"""The assistant's tools: read-only, firm-scoped wrappers over the routes and loaders the screens already use.

Each tool is ``async (ctx, **args) -> Result``. A tool reuses the GET handler or loader behind the matching screen
(search, reports, aging, health, work board, quarter folder), so the assistant sees exactly what the person would.
Nothing here writes firm data (some loaders sync contacts on read, as the screens do). Errors a person could fix
come back as ``{"error": ...}`` for the model to read, never as an exception.
"""

import uuid
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.models.accounting import AACompany, AADocument
from app.models.user import User
from app.routers.accounting_scope import company_or_404, scope_for
from app.schemas.accounting import manila_today
from app.services.accounting.assistant.windows import REPORT_PERIODS, ReportPeriod, day_window, report_window
from app.services.accounting.report_export import jsonable
from app.services.accounting.search import like_pattern

MAX_LIST = 25      # rows of a list shown to the model
SEARCH_K = 10      # search hits shown to the model, best first across all record kinds
MAX_GL_LINES = 30  # postings across a GL detail
OVERDUE_LOOKBACK_DAYS = 365


class ToolError(Exception):
    """A problem the model should read and react to (bad id, ambiguous company, books off)."""


@dataclass
class Ctx:
    db: AsyncSession
    user: User
    ent: uuid.UUID


@dataclass
class Result:
    data: dict
    sources: list[dict] = field(default_factory=list)  # search-item-shaped links the chat shows under the answer


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[..., Awaitable[Result]]


def _schema(props: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(required)}


_COMPANY = {"type": "string", "description": "The company's id from list_companies, or its name as the person said it"}
_DATE = {"type": "string", "description": "YYYY-MM-DD"}


def _date(value: str | None, what: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ToolError(f"{what} must be a date as YYYY-MM-DD, not {value!r}") from None


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def resolve_company(ctx: Ctx, ref: str | None) -> AACompany:
    """A company by id, else by name / alias (a single match), else the firm's only company."""
    if ref and (cid := _uuid(ref)):
        try:
            return await company_or_404(ctx.db, ctx.ent, cid)
        except HTTPException:
            raise ToolError("No company with that id in this firm. Call list_companies.") from None
    base = select(AACompany).where(AACompany.enterprise_id == ctx.ent)
    if not ref:
        rows = (await ctx.db.execute(base.limit(2))).scalars().all()
        if len(rows) == 1:
            return rows[0]
        raise ToolError("Which company? This firm has several: call list_companies.")
    pattern = like_pattern(ref.strip())
    rows = (await ctx.db.execute(base.where(or_(
        AACompany.registered_name.ilike(pattern, escape="\\"),
        cast(AACompany.aliases, Text).ilike(pattern, escape="\\"))).order_by(AACompany.registered_name).limit(6)
    )).scalars().all()
    exact = [c for c in rows if c.registered_name.lower() == ref.strip().lower()]
    if len(exact) == 1 or len(rows) == 1:
        return (exact or rows)[0]
    if not rows:
        raise ToolError(f"No company matches {ref!r}. Call list_companies to see the firm's companies.")
    names = ", ".join(c.registered_name for c in rows)
    raise ToolError(f"Several companies match {ref!r}: {names}. Ask the person which one.")


def _company_brief(c: AACompany) -> dict:
    return {"company_id": str(c.id), "name": c.registered_name}


async def _http(coro):
    """Run a route handler; its HTTP error becomes a ToolError with the same message the screen would show."""
    try:
        return await coro
    except HTTPException as exc:
        raise ToolError(str(exc.detail)) from None


# ---- list_companies -----------------------------------------------------------------------------------------------

async def list_companies(ctx: Ctx) -> Result:
    rows = (await ctx.db.execute(select(AACompany).where(AACompany.enterprise_id == ctx.ent)
                                 .order_by(AACompany.registered_name))).scalars().all()
    return Result({"companies": [{
        **_company_brief(c), "aliases": list(c.aliases or [])[:3], "tin": c.tin,
        "taxpayer_type": c.taxpayer_type, "vat_status": c.vat_status, "income_tax_option": c.income_tax_option,
        "fiscal_year_end_month": c.fiscal_year_end_month, "withholding_agent": c.is_withholding_agent,
        "has_employees": c.has_employees, "books_start": c.books_start} for c in rows]})


# ---- search -------------------------------------------------------------------------------------------------------

_TYPES = ("document", "contact", "bank_line", "journal_entry", "task", "company")


async def search(ctx: Ctx, query: str = "", company: str | None = None, types: list[str] | None = None,
                 date_from: str | None = None, date_to: str | None = None, review_only: bool = False) -> Result:
    from app.routers.accounting_search import SEARCH_COUNT_CAP, Filters, _group, count_query, groups_for, rank
    from app.services.accounting.search import parse_query

    company_id = (await resolve_company(ctx, company)).id if company else None
    q = parse_query(str(query or "")[:200], manila_today())
    f = Filters(company_id=company_id, date_from=_date(date_from, "date_from"), date_to=_date(date_to, "date_to"),
                review=bool(review_only))
    wanted = [t for t in (types or []) if t in _TYPES] or None
    hits: list[tuple[str, dict]] = []
    totals: dict[str, dict] = {}
    for kind in groups_for(q, f, wanted):
        count = (await ctx.db.execute(count_query(kind, ctx.ent, q, f))).scalar_one()
        totals[kind] = {"total": min(count, SEARCH_COUNT_CAP)}
        if count > SEARCH_COUNT_CAP:
            totals[kind]["total_capped"] = True
        items, _ = rank(await _group(ctx.db, kind, ctx.ent, q, f, SEARCH_K * 4 + 1), SEARCH_K)
        hits += [(kind, i) for i in items]
    # Only the best SEARCH_K across every kind reach the model: more context costs tokens and adds little.
    hits.sort(key=lambda h: -(h[1].get("score") or 0))
    hits = hits[:SEARCH_K]
    groups: list[dict] = []
    for kind, item in hits:
        group = next((g for g in groups if g["type"] == kind), None)
        if group is None:
            groups.append(group := {"type": kind, **totals[kind], "items": []})
        group["items"].append({k: v for k, v in item.items() if k not in ("score", "matched")})
    groups += [{"type": kind, **total, "items": []} for kind, total in totals.items()
               if not any(g["type"] == kind for g in groups)]
    sources = [i for _, i in hits]
    total_matches = sum(t["total"] for t in totals.values())
    capped = any(t.get("total_capped") for t in totals.values())
    data: dict = {"total_matches": total_matches, "shown": len(hits)}
    if capped:
        data["total_capped"] = True
    if total_matches > len(hits):
        found = f"at least {total_matches}" if capped else str(total_matches)
        data["note"] = (f"Showing the {len(hits)} best of {found} matches. Use these totals for any count; "
                        "narrow by company, type or date to see others.")
    return Result({**data, "groups": groups}, sources)


# ---- get_document -------------------------------------------------------------------------------------------------

_DOC_FIELDS = ("document_title", "doc_type", "category", "client_role", "doc_number", "doc_date", "period_year",
               "period_quarter", "seller_name", "seller_tin", "seller_branch", "seller_address",
               "seller_vat_registered", "buyer_name", "buyer_tin", "buyer_branch", "gross_amount", "vatable_amount",
               "vat_amount", "exempt_amount", "zero_rated_amount", "withholding_amount", "ewt_atc", "paid_on",
               "paid_via", "payment_ref", "gl_account_code", "vat_treatment", "input_vat_valid", "confidence",
               "needs_review", "review_reasons", "review_notes", "reviewed", "excluded", "page_start", "page_end")


async def get_document(ctx: Ctx, document_id: str) -> Result:
    did = _uuid(document_id)
    row = None
    if did:
        row = (await ctx.db.execute(select(AADocument, AACompany.registered_name)
                                    .join(AACompany, AACompany.id == AADocument.company_id)
                                    .options(defer(AADocument.raw))
                                    .where(AADocument.id == did, AADocument.enterprise_id == ctx.ent,
                                           AACompany.enterprise_id == ctx.ent, AADocument.deleted_at.is_(None)))
               ).first()
    if row is None:
        raise ToolError("No document with that id. Use search to find it first.")
    doc, company_name = row
    data = {"document_id": str(doc.id), "company_id": str(doc.company_id), "company": company_name,
            **{k: getattr(doc, k) for k in _DOC_FIELDS}}
    kind = doc.document_title or doc.doc_type.replace("_", " ").capitalize()
    party = doc.buyer_name if doc.client_role == "seller" else doc.seller_name
    source = {"type": "document", "id": str(doc.id), "document_id": str(doc.id), "company_id": str(doc.company_id),
              "company_name": company_name, "title": f"{kind} {doc.doc_number or '(no number)'}",
              "subtitle": " · ".join(p for p in (party, company_name) if p),
              "date": doc.doc_date.isoformat() if doc.doc_date else None, "amount": f"{doc.gross_amount:.2f}",
              "page": doc.page_start, "period_year": doc.period_year, "period_quarter": doc.period_quarter,
              "category": doc.category, "review_reasons": list(doc.review_reasons or []),
              "needs_review": bool(doc.needs_review and not doc.reviewed and not doc.excluded),
              "excluded": bool(doc.excluded), "matched": [], "score": 0}
    return Result(data, [source])


# ---- report -------------------------------------------------------------------------------------------------------

_REPORTS = ("pnl", "balance-sheet", "adjusted-tb", "gl", "transactions")


def _table(data: dict) -> dict:
    """A P&L / balance sheet / TB as label: values lines (headers without figures dropped)."""
    cols = [c["label"] for c in data.get("columns", [])]
    rows = [{"line": r["label"], "values": r["values"], "total": r.get("kind") == "total"}
            for r in data.get("rows", []) if any(v is not None for v in r.get("values", []))]
    return {"columns": cols, "rows": rows}


def _gl(accounts: list[dict]) -> dict:
    left = MAX_GL_LINES
    out = []
    for a in accounts:
        lines = a["lines"][:max(left, 0)]
        left -= len(lines)
        out.append({"account": f"{a['code']} {a['name']}", "opening": a["opening"], "closing": a["closing"],
                    "postings": len(a["lines"]),
                    "lines": [{k: l.get(k) for k in ("date", "reference", "party", "particulars", "debit", "credit",
                                                     "balance")} for l in lines]})
    return {"accounts": out, "truncated": left < 0}


async def report(ctx: Ctx, kind: str, company: str | None = None, start: str | None = None, end: str | None = None,
                 by: str = "total", account: str | None = None, party: str | None = None,
                 period: ReportPeriod | None = None) -> Result:
    from app.routers.accounting_reports import Params, build

    if kind not in _REPORTS:
        raise ToolError(f"kind must be one of {', '.join(_REPORTS)}")
    c = await resolve_company(ctx, company)
    if c.books_start is None:
        raise ToolError(f"Books are off for {c.registered_name}, so there are no book reports. Quarterly returns "
                        "(quarter_returns) still work.")
    try:
        lo, hi = (report_window(manila_today(), c.fiscal_year_end_month, period) if period is not None else
                  (_date(start, "start"), _date(end, "end")))
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    p = Params(lo, hi, by if by in ("total", "month", "quarter") else "total",
               "none", True, False, (account or None), (party or "").strip() or None)
    data, subtitle = await _http(build(ctx.db, c, kind, p))
    if kind in ("pnl", "balance-sheet", "adjusted-tb"):
        body = _table(data)
    elif kind == "gl":
        body = _gl(data["accounts"])
    else:
        rows = data["rows"]
        body = {"count": len(rows), "rows": [{k: r.get(k) for k in ("date", "reference", "party", "particulars",
                                                                     "account_names", "amount")}
                                             for r in rows[:MAX_LIST]], "truncated": len(rows) > MAX_LIST}
    return Result({**_company_brief(c), "report": kind, "period": subtitle, "basis": "accrual", **body})


# ---- aging --------------------------------------------------------------------------------------------------------

async def aging(ctx: Ctx, kind: str, company: str | None = None, as_of: str | None = None) -> Result:
    from app.routers.accounting_contacts import get_aging

    if kind not in ("ar", "ap"):
        raise ToolError("kind must be ar (receivables) or ap (payables)")
    c = await resolve_company(ctx, company)
    out = await _http(get_aging(company_id=c.id, kind=kind, as_of=_date(as_of, "as_of"), format="json",
                                preview=False, user=ctx.user, db=ctx.db))
    rows = sorted(out.rows, key=lambda r: r.total, reverse=True)
    return Result({**_company_brief(c), "kind": "receivables" if kind == "ar" else "payables", "as_of": out.as_of,
                   "bucket_totals": out.totals, "contacts": len(rows),
                   "by_contact": [{"name": r.name, "tin": r.tin, "total": r.total, "buckets": r.buckets,
                                   "open_items": r.count} for r in rows[:MAX_LIST]],
                   "tie_to_books": [{"line": t.label, "amount": t.amount} for t in out.tie], "tie_note": out.tie_note})


# ---- company_health -----------------------------------------------------------------------------------------------

_ALL = frozenset({"", "all", "every", "any", "none", "null", "firm", "all companies", "everyone", "*"})


async def firm_review_summary(ctx: Ctx) -> Result:
    """Every company in the firm with its count of documents waiting for review (one firm-scoped query)."""
    d = AADocument
    waiting = func.count(d.id).filter(d.needs_review.is_(True), d.reviewed.is_(False), d.excluded.is_(False),
                                      d.deleted_at.is_(None))
    rows = (await ctx.db.execute(
        select(AACompany.id, AACompany.registered_name, waiting)
        .outerjoin(d, and_(d.company_id == AACompany.id, d.enterprise_id == ctx.ent))
        .where(AACompany.enterprise_id == ctx.ent)
        .group_by(AACompany.id, AACompany.registered_name).order_by(waiting.desc(), AACompany.registered_name)
    )).all()
    return Result({"scope": "firm", "companies": [{"company_id": str(cid), "name": name, "open_reviews": n}
                                                  for cid, name, n in rows],
                   "note": "Call company_health with one company for its bank, close and balance issues."})


async def company_health(ctx: Ctx, company: str | None = None) -> Result:
    from app.routers.accounting_work import company_health as health

    if (company or "").strip().lower() in _ALL:
        n = (await ctx.db.execute(select(func.count(AACompany.id)).where(AACompany.enterprise_id == ctx.ent))).scalar()
        if (n or 0) != 1:
            return await firm_review_summary(ctx)
    c = await resolve_company(ctx, company)
    out = await _http(health(company_id=c.id, user=ctx.user, db=ctx.db))
    data = out.model_dump(exclude={"company_id"})
    data["company_id"] = str(c.id)
    return Result(data)


# ---- filings (work board) -----------------------------------------------------------------------------------------

async def filings(ctx: Ctx, company: str | None = None, start: str | None = None, end: str | None = None,
                  status: str | None = None, mine: bool = False, overdue_only: bool = False,
                  within_days: int | None = None, past_days: int | None = None) -> Result:
    from app.routers.accounting_work import work_board

    company_id = (await resolve_company(ctx, company)).id if company else None
    today = manila_today()
    try:
        relative = day_window(today, within_days=within_days, past_days=past_days)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    lo, hi = relative or (None, None)
    if overdue_only:  # overdue = due before today and not filed: look back a full year, whatever window was asked
        lo, hi = today - timedelta(days=OVERDUE_LOOKBACK_DAYS), today
    elif relative is None:
        lo, hi = _date(start, "start"), _date(end, "end")
    out = await _http(work_board(start=lo, end=hi, company_id=company_id,
                                 status_filter=status or None, assignee="me" if mine else None,
                                 user=ctx.user, db=ctx.db))
    cards = sorted(out.cards, key=lambda c: (c.due_date, c.company_name))
    overdue = sum(1 for c in cards if c.overdue)
    if overdue_only:
        cards = [c for c in cards if c.overdue]
    return Result({"window": {"start": out.start, "end": out.end}, "today": out.today, "count": len(cards),
                   "overdue_count": overdue, "only_mine": bool(mine),
                   "filings": [{"company": c.company_name, "company_id": str(c.company_id), "form": c.form_label,
                                "period": c.period_label, "due": c.due_date, "status": c.status,
                                "overdue": c.overdue, "days_left": c.days_left, "filed_on": c.filed_on,
                                "assignee": c.assignee_name, "documents_in_period": c.documents,
                                "reviews_in_period": c.open_reviews} for c in cards[:MAX_LIST * 2]],
                   "truncated": len(cards) > MAX_LIST * 2})


# ---- quarter_returns ----------------------------------------------------------------------------------------------

async def quarter_returns(ctx: Ctx, year: int, quarter: int, company: str | None = None,
                          form: str | None = None) -> Result:
    from app.routers.accounting_periods import get_output, get_period

    try:
        year, quarter = int(year), int(quarter)
    except (TypeError, ValueError):
        raise ToolError("year and quarter must be numbers") from None
    if not (2000 <= year <= 2100 and 1 <= quarter <= 4):
        raise ToolError("year must be 2000–2100 and quarter 1–4 (the company's fiscal quarter)")
    c = await resolve_company(ctx, company)
    period = await _http(get_period(company_id=c.id, year=year, quarter=quarter, user=ctx.user, db=ctx.db))
    data: dict = {**_company_brief(c), "period": period.label, "forms_expected": period.forms_expected,
                  "due_dates": period.due_dates, "documents": period.document_count,
                  "open_reviews": period.open_reviews,
                  "filed": {k: {"version": v.version, "filed_at": v.filed_at, "paid_on": v.paid_on}
                            for k, v in period.filed_forms.items()}
                  if period.filed_forms else {},
                  "latest_version": period.latest_version,
                  "stale": period.stale or period.books_stale}
    if period.outputs:
        latest = max(period.outputs, key=lambda o: o.version)
        out = await _http(get_output(output_id=latest.id, user=ctx.user, db=ctx.db))
        wanted = (form or "").replace("-", "").upper()
        data["figures"] = {f.form: [{"item": i.label, "value": i.value} for i in f.items if i.value not in ("", "0.00")]
                           for f in out.forms if not wanted or f.form.replace("-", "").upper().startswith(wanted)}
        data["warnings"] = out.warnings
    else:
        data["note"] = "No version generated yet: the figures appear once someone clicks Generate in the quarter folder."
    return Result(data)


# ---- tax_reference (retrieval over the app's BIR notes and ATC table) ---------------------------------------------

def reference_corpus() -> list[dict]:
    """The BIR notes the assistant may quote: each return's guide and title, and every expanded withholding ATC."""
    from app.services.accounting.compute.ewt import ewt_codes, rate_percent
    from app.services.accounting.compute.specs import FORM_TITLES
    from app.services.accounting.filing_guide import _GUIDE

    out = []
    for form, text in _GUIDE.items():
        titles = [t for k, t in FORM_TITLES.items() if k.replace("-", "").startswith(form)]
        out.append({"kind": "form", "key": form, "title": titles[0] if titles else form, "text": text})
    for code, nature, rate in ewt_codes():
        out.append({"kind": "atc", "key": code, "title": f"ATC {code}", "text": f"{nature} — {rate_percent(rate)}% "
                                                                              "expanded withholding tax"})
    return out


def rank_reference(corpus: list[dict], query: str, k: int = 8) -> list[dict]:
    """Keyword ranking: an exact form / ATC code wins, then word overlap with title + text."""
    words = [w for w in "".join(ch if ch.isalnum() else " " for ch in (query or "").upper()).split() if len(w) > 1]
    if not words:
        return []
    scored = []
    for e in corpus:
        key = e["key"].replace("-", "").upper()
        hay = f"{e['title']} {e['text']}".upper().replace("-", "")
        s = sum(10 for w in words if w == key or (len(w) >= 4 and key.startswith(w)))
        s += sum(1 for w in words if w in hay)
        if s:
            scored.append((s, e))
    scored.sort(key=lambda p: -p[0])
    return [e for _, e in scored[:k]]


async def tax_reference(ctx: Ctx, query: str) -> Result:
    hits = rank_reference(reference_corpus(), query)
    if not hits:
        return Result({"matches": [], "note": "Nothing in AutoAccounting's BIR notes matches. Say so; don't guess "
                                              "a rule or rate."})
    return Result({"matches": [{k: e[k] for k in ("kind", "key", "title", "text")} for e in hits]})


# ---- registry -----------------------------------------------------------------------------------------------------

async def ask_clarification(ctx: Ctx, question: str) -> Result:
    # The loop consumes this pseudo-tool as a terminal clarify event, never as firm data.
    return Result({"question": question})


TOOLS: tuple[Tool, ...] = (
    Tool("ask_clarification", "Ask ONE short question only when company or period is genuinely ambiguous; "
         "resolve names with list_companies first.",
         _schema({"question": {"type": "string"}}, ("question",)), ask_clarification),
    Tool("list_companies", "The firm's client companies: id, name, TIN, taxpayer type, VAT status, fiscal year end, "
         "books start (null = books off).", _schema({}), list_companies),
    Tool("search", "Find documents (receipts, invoices, 2307s, statements), customers/suppliers, bank lines, journal "
         "entries, tasks or companies by number, name, TIN, ₱ amount, date or review reason. review_only lists "
         "documents still waiting for review.",
         _schema({"query": {"type": "string", "description": "e.g. 'OR 12345', 'Meralco', '123-456-789', '₱1,500', "
                                                             "'Oct 2026'"},
                  "company": _COMPANY,
                  "types": {"type": "array", "items": {"type": "string", "enum": list(_TYPES)}},
                  "date_from": _DATE, "date_to": _DATE,
                  "review_only": {"type": "boolean"}}), search),
    Tool("get_document", "Every extracted field of one document (parties, TINs, amounts, VAT, withholding, ATC, "
         "payment, account, review reasons).",
         _schema({"document_id": {"type": "string"}}, ("document_id",)), get_document),
    Tool("report", "A report from the company's books (accrual): pnl = profit and loss, balance-sheet, adjusted-tb = "
         "trial balance, gl = general ledger detail (filter with account code or party), transactions = list by "
         "date. Default window: the current fiscal quarter. Use period for relative months/quarters/fiscal years; "
         "it overrides start/end (this_year = fiscal year to date; last_year = previous full fiscal year).",
         _schema({"kind": {"type": "string", "enum": list(_REPORTS)}, "company": _COMPANY,
                  "start": _DATE, "end": _DATE,
                  "period": {"type": "string", "enum": list(REPORT_PERIODS)},
                  "by": {"type": "string", "enum": ["total", "month", "quarter"],
                         "description": "Columns for pnl / balance-sheet"},
                  "account": {"type": "string", "description": "Account code, e.g. 6100"},
                  "party": {"type": "string", "description": "Supplier or customer name"}}, ("kind",)), report),
    Tool("aging", "Open receivables (ar) or payables (ap) by customer/supplier with aging buckets and the tie to the "
         "books' control account.",
         _schema({"kind": {"type": "string", "enum": ["ar", "ap"]}, "company": _COMPANY, "as_of": _DATE},
                 ("kind",)), aging),
    Tool("company_health", "What needs attention at one company: documents to review by reason, unreconciled bank "
         "months, unmatched bank lines, months not closed, pending 2307s, A/R and A/P over 90 days, negative "
         "balances. Leave company out for every company's review-queue count across the firm.", _schema({"company": _COMPANY}), company_health),
    Tool("filings", "BIR filings owed across the firm (or one company) in a due-date window: form, period, due date, "
         "status, overdue, assignee. Next N days/weeks: within_days (weeks × 7); past N days: past_days. "
         "Relative windows override start/end. Default window: the work board's.",
         _schema({"company": _COMPANY, "start": _DATE, "end": _DATE,
                  "within_days": {"type": "integer", "minimum": 1, "maximum": 366,
                                  "description": "Due today through today + N days (Manila)"},
                  "past_days": {"type": "integer", "minimum": 1, "maximum": 366,
                                "description": "Due today - N days through today (Manila); omit within_days"},
                  "status": {"type": "string", "description": "e.g. todo, in_progress, ready, filed"},
                  "mine": {"type": "boolean", "description": "Only when the person says 'my' / 'assigned to me'"},
                  "overdue_only": {"type": "boolean", "description": "Overdue filings (any due date in the past "
                                                                     "year); use for 'what is overdue / late'"}}),
         filings),
    Tool("quarter_returns", "One fiscal quarter's BIR returns for a company: forms expected, due dates, filed or not, "
         "and the figures of the latest generated version (VAT payable, EWT, percentage tax, income tax).",
         _schema({"company": _COMPANY, "year": {"type": "integer", "description": "Fiscal year"},
                  "quarter": {"type": "integer", "description": "1-4"},
                  "form": {"type": "string", "description": "Optional, e.g. 2550Q, 1601EQ"}}, ("year", "quarter")),
         quarter_returns),
    Tool("tax_reference", "AutoAccounting's BIR notes: what a return is for and when it's due, and expanded "
         "withholding ATC codes with their nature and rate.",
         _schema({"query": {"type": "string", "description": "A form (2550Q, 0619-E), an ATC (WC158) or words "
                                                             "(rent, professional fee)"}}, ("query",)),
         tax_reference),
)
BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}


async def call(ctx: Ctx, name: str, args: dict) -> Result:
    """Run one tool; a ToolError or a bad argument becomes ``{"error": ...}``."""
    tool = BY_NAME.get(name)
    if tool is None:
        return Result({"error": f"Unknown tool {name}"})
    allowed = set(tool.parameters["properties"])
    try:
        kwargs = {k: v for k, v in (args or {}).items() if k in allowed}
        inspect.signature(tool.run).bind(ctx, **kwargs)
        if scope_for(ctx.user) != ctx.ent:
            raise ToolError("Firm context is not available.")
        from app.services.accounting.assistant.scope import firm_reads, filter_sources
        with firm_reads(ctx.db, ctx.ent):
            result = await tool.run(ctx, **kwargs)
            result.sources = await filter_sources(ctx, result.sources)
            if name == "search":
                allowed_items = {(s["type"], s["id"]) for s in result.sources}
                groups = []
                for group in result.data.get("groups", []):
                    items = [item for item in group["items"] if (item["type"], item["id"]) in allowed_items]
                    if items:
                        groups.append({**group, "items": items})
                result.data = {**result.data, "groups": groups}
            return result
    except ToolError as exc:
        return Result({"error": str(exc)})
    except TypeError as exc:  # a required argument missing
        return Result({"error": f"Bad arguments: {exc}"})


def as_json(data: dict) -> dict:
    return jsonable(data)
