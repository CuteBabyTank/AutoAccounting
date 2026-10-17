"""Work board loader (async glue): the firm's filing cards and the cheap per-company health counts.

The decisions are in ``compute/work.py`` (which filings, status) and ``compute/health.py``. Every query is firm
scoped (``enterprise_id``) on top of RLS.
"""

import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import (
    AABankLine, AABankReconciliation, AABookClose, AACompany, AADocument, AAEmployee, AAOutput, AAPeriod, AAWorkItem,
)
from app.models.user import User, UserRole
from app.services.accounting.compute.health import months_not_closed, unreconciled_months
from app.services.accounting.compute.work import PeriodFacts, card, obligations, skip_obligation

PEOPLE_ROLES = (UserRole.ADMIN, UserRole.ENTERPRISE, UserRole.MANAGER, UserRole.EMPLOYEE)


async def firm_people(db: AsyncSession, ent: uuid.UUID) -> list[User]:
    """The firm owner and its active staff: who a filing or task can be assigned to."""
    rows = (await db.execute(select(User).where(
        ((User.id == ent) | (User.enterprise_id == ent)), User.role.in_(PEOPLE_ROLES), User.is_active.is_(True),
    ))).scalars().all()
    return sorted(rows, key=lambda u: (u.id != ent, (u.nickname or u.email).lower()))


def person_name(u: User | None) -> str:
    return (u.nickname or u.email) if u is not None else ""


def _live_docs(ent: uuid.UUID):
    return (AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False))


def _filed(row: AAPeriod) -> tuple[tuple[str, str], ...]:
    forms = row.filed_forms or {}
    if forms:
        return tuple((f, str(e.get("paid_on") or e.get("filed_at") or "")) for f, e in forms.items())
    if row.filed_at is not None:  # filed before per-form filing existed: every form of that version
        return (("*", row.filed_at.date().isoformat()),)
    return ()


async def load_cards(db: AsyncSession, ent: uuid.UUID, start: date, end: date, today: date,
                     companies: list[AACompany]) -> list[dict]:
    from app.routers.accounting_periods import company_facts

    docs: dict[tuple[str, int, int], list[int]] = defaultdict(lambda: [0, 0, 0])
    for cid, year, quarter, count, reviews, payroll in (await db.execute(select(
        AADocument.company_id, AADocument.period_year, AADocument.period_quarter, func.count(AADocument.id),
        func.count(AADocument.id).filter(AADocument.needs_review.is_(True), AADocument.reviewed.is_(False)),
        func.count(AADocument.id).filter(AADocument.category == "payroll"),
    ).where(*_live_docs(ent), AADocument.period_year.is_not(None))
     .group_by(AADocument.company_id, AADocument.period_year, AADocument.period_quarter))).all():
        for key in ((str(cid), year, quarter), (str(cid), year, 0)):
            docs[key][0] += count
            docs[key][1] += reviews
        docs[(str(cid), year, quarter)][2] += payroll
    periods = {(str(p.company_id), p.year, p.quarter): p for p in (await db.execute(
        select(AAPeriod).where(AAPeriod.enterprise_id == ent))).scalars().all()}
    generated = {(str(cid), y, q) for cid, y, q in (await db.execute(
        select(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter).join(AAOutput, AAOutput.period_id == AAPeriod.id)
        .where(AAPeriod.enterprise_id == ent).distinct())).all()}
    employees = {(str(cid), y): n for cid, y, n in (await db.execute(
        select(AAEmployee.company_id, AAEmployee.year, func.count(AAEmployee.id)).where(AAEmployee.enterprise_id == ent)
        .group_by(AAEmployee.company_id, AAEmployee.year))).all()}
    items = {(str(i.company_id), i.year, i.quarter, i.form): i for i in (await db.execute(
        select(AAWorkItem).where(AAWorkItem.enterprise_id == ent))).scalars().all()}

    cards: list[dict] = []
    for company in companies:
        cid = str(company.id)
        fye = company.fiscal_year_end_month
        facts = company_facts(company)
        payroll = {(y, q) for (c, y, q), v in docs.items() if c == cid and q and v[2]}
        staff_years = {y for (c, y) in employees if c == cid}
        added = company.created_at.date()
        for ob in obligations(facts, start, end, payroll, staff_years):
            key = (cid, ob.year, ob.quarter)
            if ob.form == "1604C":
                pf = PeriodFacts(documents=employees.get((cid, ob.year), 0))
            else:
                count, reviews, _ = docs.get(key, (0, 0, 0))
                period = periods.get(key)
                filed = _filed(period) if period is not None else ()
                if filed and filed[0][0] == "*":
                    filed = ((ob.form, filed[0][1]),)
                pf = PeriodFacts(count, reviews, key in generated, filed)
            item = items.get((cid, ob.year, ob.quarter, ob.form))
            has_data = bool(pf.documents or pf.generated or pf.filed or item is not None)
            if skip_obligation(ob, added, has_data=has_data):
                continue
            row = card(ob, fye, pf, {"assignee_id": str(item.assignee_id) if item.assignee_id else None,
                                     "status_override": item.status_override, "filed_on": item.filed_on}
                       if item is not None else None, today)
            row.update(key=f"{cid}:{ob.year}:{ob.quarter}:{ob.form}", company_id=cid,
                       company_name=company.registered_name)
            cards.append(row)
    return sorted(cards, key=lambda c: (c["due_date"], c["company_name"].lower(), c["form"]))


async def company_summaries(db: AsyncSession, ent: uuid.UUID, companies: list[AACompany], today: date) -> dict[str, dict]:
    """Cheap health counts for every client at once (the full check is per company)."""
    from app.services.accounting.books.bank import OPEN_STATUSES, live_line

    reviews = dict((await db.execute(select(AADocument.company_id, func.count(AADocument.id)).where(
        *_live_docs(ent), AADocument.needs_review.is_(True), AADocument.reviewed.is_(False))
        .group_by(AADocument.company_id))).all())
    unmatched = dict((await db.execute(select(AABankLine.company_id, func.count(AABankLine.id)).where(
        AABankLine.enterprise_id == ent, AABankLine.match_status.in_(OPEN_STATUSES), live_line())
        .group_by(AABankLine.company_id))).all())
    month = func.date_trunc("month", AABankLine.line_date)
    line_months: dict[uuid.UUID, set] = defaultdict(set)
    for cid, code, m in (await db.execute(select(AABankLine.company_id, AABankLine.account_code, month).where(
            AABankLine.enterprise_id == ent, AABankLine.account_code != "", live_line()).distinct())).all():
        line_months[cid].add((code, m.date() if hasattr(m, "date") else m))
    recs: dict[uuid.UUID, set] = defaultdict(set)
    for cid, code, m in (await db.execute(select(
            AABankReconciliation.company_id, AABankReconciliation.account_code, AABankReconciliation.month_start).where(
            AABankReconciliation.enterprise_id == ent, AABankReconciliation.voided_at.is_(None)))).all():
        recs[cid].add((code, m))
    closes: dict[uuid.UUID, set] = defaultdict(set)
    for cid, m in (await db.execute(select(AABookClose.company_id, AABookClose.month_start).where(
            AABookClose.enterprise_id == ent, AABookClose.kind == "month", AABookClose.voided_at.is_(None)))).all():
        closes[cid].add(m)
    out = {}
    for c in companies:
        out[str(c.id)] = {
            "company_id": str(c.id), "company_name": c.registered_name,
            "open_reviews": int(reviews.get(c.id, 0)), "unmatched_bank_lines": int(unmatched.get(c.id, 0)),
            "unreconciled_months": len(unreconciled_months(line_months[c.id], recs[c.id], today)),
            "months_not_closed": len(months_not_closed(c.books_start, closes[c.id], today)),
            "books_on": c.books_start is not None,
        }
    return out
