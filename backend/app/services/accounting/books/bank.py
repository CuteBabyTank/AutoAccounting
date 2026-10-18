"""Bank statements in the books: store extracted lines, (re)match them, feed the books, reconcile (async glue).

The decisions are in the pure modules: ``bank_statement`` (parse, tie-out, account by last 4), ``bank_match``
(candidates and narration), ``compute.bank_books`` (payments and postings) and ``compute.bank_reconcile``.
"""

import asyncio
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.accounting import (
    AAAccount, AABankLine, AABankReconciliation, AABankRule, AABankStatement, AACompany, AADocument,
    AAJournalEntry, AAOutput, AAPeriod,
)
from app.services.accounting.bank_match import (
    BankLineFact, Candidate, Match, Rule, learn_rule, match_all, open_items,
)
from app.services.accounting.bank_report_pdf import reconciliation_pdf
from app.services.accounting.bank_statement import parse_statement, resolve_account, tie_out
from app.services.accounting.compute.bank_books import POSTING_STATUSES, MatchedLine, tax_key
from app.services.accounting.compute.bank_reconcile import (
    Reconciliation, cleared_entry_ids, opening_gap, reconcile, statement_balance,
)
from app.services.accounting.compute.books import BooksInput, Entry, QuarterTaxes, employee_contributions
from app.services.accounting.compute.ewt import compute_ewt
from app.services.accounting.compute.inputs import PeriodData, inputs_from_json
from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.opening_items import opening_doc_line
from app.services.accounting.periods import period_for
from app.services.accounting.review_rules import sync_payment_flags

OPEN_STATUSES = ("unmatched", "ambiguous", "suggested")
_TAX_WORDS = ("bir", "bureau", "revenue", "tax", "taxes", "ebir", "efps")


# --- accounts and statements ---------------------------------------------------------------------------------------

def live_statement_ids():
    """Statements whose document is still in the databank (not deleted, not excluded): only their lines count."""
    return select(AABankStatement.id).join(AADocument, AADocument.id == AABankStatement.document_id).where(
        AADocument.deleted_at.is_(None), AADocument.excluded.is_(False))


def live_line():
    return AABankLine.statement_id.in_(live_statement_ids())


def live_statement():
    return AABankStatement.id.in_(live_statement_ids())


async def bank_accounts(db: AsyncSession, company_id: uuid.UUID) -> list[AAAccount]:
    """The company's bank accounts: Cash in bank and every active asset account with an account number."""
    rows = (await db.execute(select(AAAccount).where(AAAccount.company_id == company_id, AAAccount.active.is_(True),
                                                     AAAccount.type == "asset"))).scalars().all()
    return sorted([r for r in rows if r.system_key == "bank" or (r.bank_account_no or "").strip()],
                  key=lambda r: r.code)


async def store_statement(db: AsyncSession, doc: AADocument) -> AABankStatement | None:
    """Save a statement document's lines (once per document); flushes, the caller commits."""
    data = parse_statement(doc.raw)
    if data is None:
        return None
    existing = (await db.execute(select(AABankStatement).where(AABankStatement.document_id == doc.id))
                ).scalar_one_or_none()
    if existing is not None:
        return existing
    accounts = await bank_accounts(db, doc.company_id)
    code = resolve_account(data.account_number, [(a.code, a.bank_account_no) for a in accounts]) or ""
    ties, breaks = tie_out(data)
    statement = AABankStatement(
        id=uuid.uuid4(), enterprise_id=doc.enterprise_id, company_id=doc.company_id, document_id=doc.id,
        account_code=code, account_number=data.account_number, bank_name=data.bank_name,
        period_start=data.period_start or data.lines[0].on, period_end=data.period_end or data.lines[-1].on,
        opening_balance=data.opening, closing_balance=data.closing, ties=ties, tie_breaks=breaks,
    )
    db.add(statement)
    await db.flush()  # no ORM relationship orders the inserts: the statement must exist before its lines
    for l in data.lines:
        db.add(AABankLine(enterprise_id=doc.enterprise_id, company_id=doc.company_id, statement_id=statement.id,
                          account_code=code, line_no=l.line_no, line_date=l.on, amount=l.amount, balance=l.balance,
                          narration=l.narration, check_no=l.check_no, match_status="unmatched"))
    await db.flush()
    return statement


async def statement_document_changed(db: AsyncSession, doc: AADocument) -> None:
    """A statement's document was deleted, excluded or put back: its lines stop (or start) counting, so the
    reconciliations from its period on no longer hold and the other lines may match differently. Flushes."""
    from app.services.accounting.books.loader import touch_books

    statement = (await db.execute(select(AABankStatement).where(AABankStatement.document_id == doc.id))
                 ).scalar_one_or_none()
    if statement is None:
        return
    if statement.account_code:
        await void_reconciliations(db, doc.company_id, statement.account_code, statement.period_start or date.min)
    await db.flush()
    company = await db.get(AACompany, doc.company_id)
    if company is not None:
        await rematch(db, company)
        touch_books(company)


async def assign_account(db: AsyncSession, statement: AABankStatement, account: AAAccount) -> None:
    """A person says which bank account a statement is; remembers the number on the account if it had none."""
    statement.account_code = account.code
    if not (account.bank_account_no or "").strip() and statement.account_number:
        account.bank_account_no = statement.account_number[:40]
    lines = (await db.execute(select(AABankLine).where(AABankLine.statement_id == statement.id))).scalars().all()
    for l in lines:
        l.account_code = account.code
        if l.match_status not in ("confirmed", "excluded"):
            l.match_status = "unmatched"
    await db.flush()


# --- candidates ----------------------------------------------------------------------------------------------------

def _dir(category: str) -> str:
    return "in" if category == "sales" else "out"


async def _contributions(db: AsyncSession, company: AACompany, lines, chart) -> dict[str, Decimal]:
    from app.services.accounting.books.loader import month_contributions   # loader imports the router

    fye = company.fiscal_year_end_month
    rows = (await db.execute(select(AAPeriod).where(AAPeriod.company_id == company.id, AAPeriod.quarter >= 1))
            ).scalars().all()
    quarters = tuple(QuarterTaxes(r.year, r.quarter, date.max, {}, contributions=month_contributions(
        PeriodData(r.year, r.quarter, (), inputs_from_json(r.inputs)), fye)) for r in rows)
    from app.routers.accounting_periods import company_facts

    inp = BooksInput(company_facts(company), chart, frozenset(), date.min, date.max, lines=tuple(lines),
                     quarters=quarters)
    return employee_contributions(inp)[0]


async def _candidates(db: AsyncSession, company: AACompany, docs: list[AADocument], used: dict[str, Decimal],
                      used_refs: set[str]) -> list[Candidate]:
    from app.routers.accounting_periods import company_facts, doc_line, supplier_atc_rules, supplier_gl_rules
    from app.services.accounting.books.loader import ensure_chart, filed_payments, opening_items

    facts = company_facts(company)
    chart = await ensure_chart(db, company)
    receipts = [d for d in docs if d.settles_document_id is not None]
    paid_by_receipt = {str(r.settles_document_id) for r in receipts}
    posted = [d for d in docs if d.settles_document_id is None]
    atc_rules, gl_rules = await supplier_atc_rules(db, company.id), await supplier_gl_rules(db, company.id)
    lines = [doc_line(d, atc_rules, gl_rules) for d in posted]
    opening = await opening_items(db, company) if company.books_start else []
    today = date.today()
    where = period_for(today, company.fiscal_year_end_month)
    ewt = {i: tax for i, (_, tax) in compute_ewt(lines, facts, where.fiscal_year, where.quarter).by_line().items()}
    contributions = await _contributions(db, company, lines, chart)

    paid = dict(used)
    by_id = {str(d.id): d for d in posted}
    for d in posted:  # paid in cash / e-wallet, or by a receipt: not waiting for the bank
        if (d.paid_on is not None and (d.paid_via or "cash") != "bank") or str(d.id) in paid_by_receipt:
            paid[str(d.id)] = Decimal("999999999999.99")
    for i in opening:  # an opening item paid in cash isn't waiting for the bank either
        if i.paid_on is not None and (i.paid_via or "cash") != "bank":
            paid[str(i.id)] = Decimal("999999999999.99")
    from app.services.accounting.books.subledger import writeoff_rows
    from app.services.accounting.compute.writeoff import written_off
    for item_id, amount in written_off(await writeoff_rows(db, company)).items():  # written off: not coming in
        paid[item_id] = paid.get(item_id, ZERO) + amount
    out = open_items(lines + [opening_doc_line(i, company.books_start) for i in opening], ewt, contributions, paid,
                     refs={str(d.id): d.payment_ref for d in posted})

    for r in receipts:  # a receipt that pays an invoice is the payment the bank shows
        invoice = by_id.get(str(r.settles_document_id))
        if invoice is None or r.doc_date is None or str(r.id) in used:
            continue
        amount = c2(r.gross_amount - (r.withholding_amount or ZERO))
        seller = invoice.client_role == "seller"
        name = invoice.buyer_name if seller else invoice.seller_name
        if amount > 0:
            out.append(Candidate("document", str(r.id), r.doc_date, amount, _dir(invoice.category), name,
                                 (r.doc_number, invoice.doc_number, r.payment_ref), f"{r.doc_number} · {name}",
                                 payee_tin=invoice.buyer_tin if seller else invoice.seller_tin))

    rows = (await db.execute(select(AAPeriod.year, AAPeriod.quarter, AAPeriod.filed_forms).where(
        AAPeriod.company_id == company.id))).all()
    ids = {uuid.UUID(str(e["output_id"])) for _, _, f in rows for e in (f or {}).values() if e.get("output_id")}
    outputs = {str(o.id): o.snapshot for o in (await db.execute(
        select(AAOutput).where(AAOutput.id.in_(ids)))).scalars().all()} if ids else {}
    for p in filed_payments([tuple(r) for r in rows], outputs):
        key = tax_key(p.form, p.year, p.quarter)
        if p.amount > 0 and key not in used_refs:
            out.append(Candidate("tax", key, p.on, p.amount, "out", "Bureau of Internal Revenue", (p.form,),
                                 f"BIR {p.form} {p.year} Q{p.quarter}", _TAX_WORDS, partial_ok=False))

    bank_codes = {a.code for a in await bank_accounts(db, company.id)}
    entries = (await db.execute(select(AAJournalEntry).where(
        AAJournalEntry.company_id == company.id, AAJournalEntry.deleted_at.is_(None),
        AAJournalEntry.kind == "manual"))).scalars().all()
    for je in entries:
        if str(je.id) in used_refs:
            continue
        net = c2(sum((c2(x.get("debit") or 0) - c2(x.get("credit") or 0) for x in je.lines or []
                      if x.get("account_code") in bank_codes), ZERO))
        if net:
            party = next((x.get("party_name") for x in je.lines or [] if x.get("party_name")), "") or je.particulars
            out.append(Candidate("journal", str(je.id), je.entry_date, abs(net), "in" if net > 0 else "out", party,
                                 (je.reference,), f"JE {je.reference or ''} {je.particulars}".strip(),
                                 partial_ok=False))
    return out


# --- matching ------------------------------------------------------------------------------------------------------

def _fact(l: AABankLine) -> BankLineFact:
    return BankLineFact(str(l.id), l.line_date, l.amount, l.narration, l.check_no, l.account_code)


async def company_rules(db: AsyncSession, company_id: uuid.UUID) -> list[Rule]:
    rows = (await db.execute(select(AABankRule).where(AABankRule.company_id == company_id)
                             .order_by(AABankRule.hits.desc()))).scalars().all()
    return [Rule(r.pattern, r.direction, r.kind, r.account_code, r.payee_name, r.payee_tin) for r in rows]


async def _documents(db: AsyncSession, company_id: uuid.UUID) -> list[AADocument]:
    return list((await db.execute(select(AADocument).where(
        AADocument.company_id == company_id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
        AADocument.doc_date.is_not(None)))).scalars().all())


async def bank_paid_ids(db: AsyncSession, company_id: uuid.UUID) -> set[str]:
    """Documents a matched or confirmed bank line pays (a receipt's match pays its invoice)."""
    refs = (await db.execute(select(AABankLine.matched_ref).where(
        AABankLine.company_id == company_id, AABankLine.match_kind == "document", live_line(),
        AABankLine.match_status.in_(POSTING_STATUSES)))).scalars().all()
    if not refs:
        return set()
    ids = [uuid.UUID(r) for r in refs if r]
    settled = (await db.execute(select(AADocument.id, AADocument.settles_document_id).where(AADocument.id.in_(ids)))
               ).all()
    return {str(i) for i in ids} | {str(s) for _, s in settled if s is not None}


async def rematch(db: AsyncSession, company: AACompany) -> int:
    """Match every line a person hasn't decided yet; returns how many lines are matched. Flushes."""
    from app.services.accounting.books.loader import ensure_chart

    lines = (await db.execute(select(AABankLine).where(
        AABankLine.company_id == company.id, AABankLine.account_code != "", live_line()).order_by(AABankLine.line_date))
             ).scalars().all()
    if not lines:
        return 0
    docs = await _documents(db, company.id)
    decided = [l for l in lines if l.match_status in ("confirmed", "excluded")]
    used: dict[str, Decimal] = defaultdict(lambda: ZERO)
    used_refs: set[str] = set()
    for l in decided:
        if l.match_status == "confirmed" and l.matched_ref:
            used[l.matched_ref] += c2(l.match_amount if l.match_amount is not None else abs(l.amount))
            used_refs.add(l.matched_ref)
    candidates = await _candidates(db, company, docs, dict(used), used_refs)
    chart = await ensure_chart(db, company)
    accounts = await bank_accounts(db, company.id)
    pending = [l for l in lines if l.match_status not in ("confirmed", "excluded")]
    results = match_all([_fact(l) for l in pending], candidates, await company_rules(db, company.id),
                        {str(l.id): set(l.rejected or []) for l in pending},
                        [(a.code, a.bank_account_no) for a in accounts])
    matched = 0
    for l in pending:
        m = results[str(l.id)]
        if m.kind == "posting" and "posting" in (l.rejected or []):   # a person said no to posting it this way
            m = Match("ambiguous" if m.candidates else "unmatched", candidates=m.candidates,
                      reason="bank_match_ambiguous" if m.candidates else "bank_line_unmatched")
        posting = dict(m.posting)
        if posting.get("key"):
            posting["account"] = chart.code_or(posting["key"], "doc:other" if l.amount < 0 else "other_income")
        l.match_status, l.match_kind, l.matched_ref = m.status, m.kind, m.ref
        l.match_amount = m.amount if m.status in ("matched", "suggested") else None
        l.posting, l.candidates, l.review_reason = posting, list(m.candidates), m.reason
        if m.status == "matched":
            matched += 1
    sync_payment_flags(docs, await _flushed_paid_ids(db, company.id))
    await db.flush()
    await refresh_opening_flag(db, company)
    return matched


async def _flushed_paid_ids(db: AsyncSession, company_id: uuid.UUID) -> set[str]:
    await db.flush()
    return await bank_paid_ids(db, company_id)


async def learn_from(db: AsyncSession, company: AACompany, line: AABankLine, candidate: dict | None) -> None:
    """Remember a payee / posting rule from a confirmed line (generalises the supplier databank)."""
    payee, tin = "", ""
    if line.match_kind == "document" and line.matched_ref:
        doc = await db.get(AADocument, uuid.UUID(line.matched_ref))
        if doc is not None and doc.company_id == company.id:
            if doc.settles_document_id:
                doc = await db.get(AADocument, doc.settles_document_id) or doc
            seller = doc.client_role == "seller"
            payee, tin = (doc.buyer_name, doc.buyer_tin) if seller else (doc.seller_name, doc.seller_tin)
    cand = Candidate("document", line.matched_ref, line.line_date, abs(line.amount), "in" if line.amount > 0 else "out",
                     payee, (), payee_tin=tin) if payee else None
    rule = learn_rule(_fact(line), line.match_kind, cand, (line.posting or {}).get("account", ""))
    if rule is None:
        return
    row = (await db.execute(select(AABankRule).where(
        AABankRule.company_id == company.id, AABankRule.pattern == rule.pattern[:80],
        AABankRule.direction == rule.direction, AABankRule.kind == rule.kind))).scalar_one_or_none()
    if row is None:
        db.add(AABankRule(enterprise_id=company.enterprise_id, company_id=company.id, pattern=rule.pattern[:80],
                          direction=rule.direction, kind=rule.kind, account_code=rule.account_code,
                          payee_name=rule.payee_name[:255], payee_tin=rule.payee_tin))
    else:
        row.hits += 1
        row.account_code, row.payee_name, row.payee_tin = rule.account_code, rule.payee_name[:255], rule.payee_tin


# --- books ---------------------------------------------------------------------------------------------------------

async def matched_lines(db: AsyncSession, company_id: uuid.UUID, through: date) -> list[MatchedLine]:
    rows = (await db.execute(select(AABankLine).where(
        AABankLine.company_id == company_id, AABankLine.account_code != "", AABankLine.line_date <= through, live_line(),
        AABankLine.match_status.in_(POSTING_STATUSES)))).scalars().all()
    return [MatchedLine(str(r.id), r.line_date, r.amount, r.account_code, r.match_kind, r.matched_ref,
                        r.match_amount, (r.posting or {}).get("account", ""), r.narration, r.check_no) for r in rows]


async def book_entries(db: AsyncSession, company: AACompany, through: date) -> list[Entry] | None:
    """Every book entry through ``through`` (None when the books are off or start later)."""
    from app.routers.accounting_periods import company_facts, load_periods
    from app.services.accounting.assets import active_assets
    from app.services.accounting.books.loader import quarter_entries
    from app.services.accounting.compute.engine import build_quarter

    if company.books_start is None or through < company.books_start:
        return None
    where = period_for(through, company.fiscal_year_end_month)
    facts = company_facts(company)
    assets = await active_assets(db, company)
    periods = await load_periods(db, company, where.fiscal_year, where.quarter)
    result = build_quarter(facts, periods, assets=assets)
    q = await quarter_entries(db, company, facts, where.fiscal_year, where.quarter, result, assets, periods)
    return [e for e in q.entries if e.date <= through] if q else None


async def _statements(db: AsyncSession, company_id: uuid.UUID, account: str) -> list[AABankStatement]:
    return list((await db.execute(select(AABankStatement).where(
        AABankStatement.company_id == company_id, AABankStatement.account_code == account, live_statement())
        .order_by(AABankStatement.period_start))).scalars().all())


def month_bounds(month_start: date) -> tuple[date, date]:
    nxt = date(month_start.year + (month_start.month == 12), month_start.month % 12 + 1, 1)
    return month_start, nxt - timedelta(days=1)


async def reconcile_month(db: AsyncSession, company: AACompany, account: str,
                          month_start: date) -> tuple[Reconciliation | None, str]:
    """(reconciliation, problem) for one bank account and month."""
    start, end = month_bounds(month_start)
    statements = await _statements(db, company.id, account)
    if not statements:
        return None, "There's no bank statement for this account yet."
    first = statements[0]
    lines = (await db.execute(select(AABankLine).where(
        AABankLine.company_id == company.id, AABankLine.account_code == account, AABankLine.line_date <= end,
        live_line()))
             ).scalars().all()
    if not any(start <= l.line_date <= end for l in lines) and not any(
            s.period_start and s.period_end and s.period_start <= end and s.period_end >= start for s in statements):
        return None, f"No statement covers {start:%B %Y} for this account."
    if first.opening_balance is None:
        return None, "The first statement has no opening balance; it can't be reconciled."
    entries = await book_entries(db, company, end)
    if entries is None:
        return None, "This company has no books for that month (set Books start on the company)."
    balance = statement_balance(first.opening_balance, [(l.amount, l.match_status) for l in lines])
    open_ids = [str(l.id) for l in lines if l.match_status in OPEN_STATUSES]
    cleared = cleared_entry_ids(await matched_lines(db, company.id, end))
    return reconcile(account, start, end, balance, entries, cleared, first.period_start or start,
                     open_ids), ""


async def refresh_opening_flag(db: AsyncSession, company: AACompany) -> None:
    """``opening_balance_missing`` per bank account: the first statement opens at a balance the books don't have."""
    flags = dict(company.review_flags or {})
    missing: dict[str, dict] = {}
    for account in await bank_accounts(db, company.id):
        statements = await _statements(db, company.id, account.code)
        if not statements or statements[0].period_start is None:
            continue
        first = statements[0]
        entries = await book_entries(db, company, first.period_start)
        if entries is None:
            continue
        gap = opening_gap(entries, account.code, first.period_start, first.opening_balance)
        if gap:
            missing[account.code] = gap
    if missing:
        flags["opening_balance_missing"] = missing
    else:
        flags.pop("opening_balance_missing", None)
    if flags != (company.review_flags or {}):
        company.review_flags = flags


async def unreconciled_accounts(db: AsyncSession, company_id: uuid.UUID, start: date, end: date) -> list[str]:
    """Bank accounts with statement lines in the month and no reconciliation for it (the close soft-block)."""
    codes = set((await db.execute(select(AABankLine.account_code).where(
        AABankLine.company_id == company_id, AABankLine.account_code != "", AABankLine.line_date >= start, live_line(),
        AABankLine.line_date <= end))).scalars().all())
    done = set((await db.execute(select(AABankReconciliation.account_code).where(
        AABankReconciliation.company_id == company_id, AABankReconciliation.month_start == start,
        AABankReconciliation.voided_at.is_(None)))).scalars().all())
    return sorted(codes - done)


async def void_reconciliations(db: AsyncSession, company_id: uuid.UUID, account: str, on: date) -> int:
    """A line changed: reconciliations of its month and later ones no longer hold."""
    rows = (await db.execute(select(AABankReconciliation).where(
        AABankReconciliation.company_id == company_id, AABankReconciliation.account_code == account,
        AABankReconciliation.month_end >= on, AABankReconciliation.voided_at.is_(None)))).scalars().all()
    for r in rows:
        r.voided_at = datetime.now(timezone.utc)
    return len(rows)


async def save_reconciliation(db: AsyncSession, company: AACompany, rec: Reconciliation, account: AAAccount,
                              user_id: uuid.UUID, user_label: str) -> AABankReconciliation:
    from app.services.accounting.books.closing import _fy_dir, fiscal_months, header_for

    await void_reconciliations(db, company.id, rec.account, rec.month_start)
    fye = company.fiscal_year_end_month
    fiscal_year = period_for(rec.month_start, fye).fiscal_year
    months = [s for s, _ in fiscal_months(fiscal_year, fye)]
    index = months.index(rec.month_start) + 1 if rec.month_start in months else 0
    folder = _fy_dir(company, fiscal_year) / f"M{index:02d}-{rec.month_start:%Y-%m}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = folder / f"BANK-{rec.account}-{stamp}.pdf"
    number = f" · ****{account.bank_account_no[-4:]}" if (account.bank_account_no or "").strip() else ""
    label = f"{account.code} {account.name}{number}"
    data = reconciliation_pdf(header_for(company), label, rec, user_label)

    def _write() -> None:
        target = Path(settings.accounting_root) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    await asyncio.get_running_loop().run_in_executor(None, _write)
    row = AABankReconciliation(enterprise_id=company.enterprise_id, company_id=company.id, account_code=rec.account,
                               month_start=rec.month_start, month_end=rec.month_end,
                               statement_balance=rec.statement_balance, book_balance=rec.book_balance,
                               uncleared=list(rec.uncleared), file_path=str(path), reconciled_by=user_id)
    db.add(row)
    await db.flush()
    return row
