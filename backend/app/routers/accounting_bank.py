"""Bank statements: lines and their matches, confirm / reject / re-match, statement account, reconcile, rules."""

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import (
    AAAccount, AABankLine, AABankReconciliation, AABankRule, AABankStatement, AACompany, AADocument,
)
from app.models.user import User
from app.routers.accounting_scope import company_or_404, scope_for
from app.schemas.accounting_bank import (
    BankAccountOut, BankLineOut, BankMonthOut, BankOverviewOut, BankReconciliationOut, BankRuleOut, BankStatementOut,
    ConfirmLineIn, LineReasonIn, ReconcileIn, ReconcileOut, StatementPatch,
)
from app.services.accounting import audit
from app.services.accounting.books import bank
from app.services.accounting.books.closing import stored_file
from app.services.accounting.books.loader import ensure_chart, touch_books
from app.services.accounting.compute.money import ZERO, c2

router = APIRouter()

_LINE_FIELDS = ("match_status", "match_kind", "matched_ref", "match_amount", "posting")


def _line_label(line: AABankLine) -> str:
    return " · ".join(p for p in (line.line_date.isoformat(), line.narration[:80], f"{line.amount:,.2f}") if p)


async def _company(db: AsyncSession, user: User, company_id: uuid.UUID) -> tuple[uuid.UUID, AACompany]:
    ent = scope_for(user)
    return ent, await company_or_404(db, ent, company_id)


async def _line_or_404(db: AsyncSession, ent: uuid.UUID, line_id: uuid.UUID) -> AABankLine:
    row = (await db.execute(select(AABankLine).where(AABankLine.id == line_id, AABankLine.enterprise_id == ent))
           ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank line not found")
    return row


async def _reconciled_through(db: AsyncSession, company_id: uuid.UUID, code: str) -> date | None:
    """The end of the last month in an unbroken run of reconciled months from the first statement."""
    months = sorted((await db.execute(select(AABankReconciliation.month_start, AABankReconciliation.month_end).where(
        AABankReconciliation.company_id == company_id, AABankReconciliation.account_code == code,
        AABankReconciliation.voided_at.is_(None)))).all())
    through = None
    for start, end in months:
        if through is not None and start > date.fromordinal(through.toordinal() + 1):
            break
        through = end
    return through


async def _account_out(db: AsyncSession, company: AACompany, account: AAAccount) -> BankAccountOut:
    missing = ((company.review_flags or {}).get("opening_balance_missing") or {}).get(account.code)
    return BankAccountOut(code=account.code, name=account.name, bank_account_no=account.bank_account_no or "",
                          reconciled_through=await _reconciled_through(db, company.id, account.code),
                          opening_missing=missing)


@router.get("/companies/{company_id}/bank", response_model=BankOverviewOut)
async def bank_overview(company_id: uuid.UUID, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    ent, company = await _company(db, user, company_id)
    await ensure_chart(db, company)
    accounts = [await _account_out(db, company, a) for a in await bank.bank_accounts(db, company.id)]
    unassigned = (await db.execute(select(AABankStatement).where(
        AABankStatement.enterprise_id == ent, AABankStatement.company_id == company.id,
        AABankStatement.account_code == "", bank.live_statement()))).scalars().all()
    rules = (await db.execute(select(func.count(AABankRule.id)).where(
        AABankRule.enterprise_id == ent, AABankRule.company_id == company.id))).scalar() or 0
    await db.commit()
    return BankOverviewOut(accounts=accounts, unassigned=[BankStatementOut.model_validate(s) for s in unassigned],
                           rules=rules)


async def _labels(db: AsyncSession, company_id: uuid.UUID, lines: list[AABankLine]) -> dict[str, str]:
    ids = {uuid.UUID(l.matched_ref) for l in lines if l.match_kind == "document" and l.matched_ref}
    if not ids:
        return {}
    docs = (await db.execute(select(AADocument).where(AADocument.company_id == company_id, AADocument.id.in_(ids)))
            ).scalars().all()
    return {str(d.id): " · ".join(p for p in (d.doc_number, d.buyer_name if d.client_role == "seller"
                                               else d.seller_name) if p) for d in docs}


def _line_out(l: AABankLine, labels: dict[str, str]) -> BankLineOut:
    out = BankLineOut.model_validate(l)
    if l.match_kind == "posting":
        out.match_label = (l.posting or {}).get("label", "")
    elif l.matched_ref:
        out.match_label = labels.get(l.matched_ref) or next(
            (c.get("label", "") for c in l.candidates or [] if c.get("ref") == l.matched_ref), "")
    return out


@router.get("/companies/{company_id}/bank/lines", response_model=BankMonthOut)
async def bank_month(company_id: uuid.UUID, account: str = Query("", max_length=10),
                     month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    ent, company = await _company(db, user, company_id)
    start, end = bank.month_bounds(date(int(month[:4]), int(month[5:]), 1))
    rows = (await db.execute(select(AABankLine).where(
        AABankLine.enterprise_id == ent, AABankLine.company_id == company.id, AABankLine.account_code == account,
        AABankLine.line_date >= start, AABankLine.line_date <= end, bank.live_line(),
    ).order_by(AABankLine.line_date, AABankLine.line_no))).scalars().all()
    statement_ids = {l.statement_id for l in rows}
    statements = (await db.execute(select(AABankStatement).where(
        AABankStatement.enterprise_id == ent, AABankStatement.id.in_(statement_ids)))).scalars().all() \
        if statement_ids else []
    acct = next((a for a in await bank.bank_accounts(db, company.id) if a.code == account), None) if account else None
    rec = None
    if account:
        rec = (await db.execute(select(AABankReconciliation).where(
            AABankReconciliation.company_id == company.id, AABankReconciliation.account_code == account,
            AABankReconciliation.month_start == start, AABankReconciliation.voided_at.is_(None))
            .order_by(AABankReconciliation.reconciled_at.desc()).limit(1))).scalars().first()
    # Statement balance at the month's start and end: the first statement's opening + every line before.
    first = (await db.execute(select(AABankStatement).where(
        AABankStatement.company_id == company.id, AABankStatement.account_code == account, bank.live_statement())
        .order_by(AABankStatement.period_start).limit(1))).scalars().first() if account else None
    opening = closing = None
    if first is not None and first.opening_balance is not None:
        before = (await db.execute(select(func.coalesce(func.sum(AABankLine.amount), 0)).where(
            AABankLine.company_id == company.id, AABankLine.account_code == account,
            AABankLine.line_date < start, bank.live_line()))).scalar()
        opening = c2(first.opening_balance + c2(before or ZERO))
        closing = c2(opening + sum((l.amount for l in rows), ZERO))
    labels = await _labels(db, company.id, list(rows))
    return BankMonthOut(
        account=await _account_out(db, company, acct) if acct else None, month_start=start,
        statements=[BankStatementOut.model_validate(s) for s in statements],
        lines=[_line_out(l, labels) for l in rows],
        reconciliation=BankReconciliationOut.model_validate(rec) if rec else None,
        opening_balance=opening, closing_balance=closing,
    )


async def _after_change(db: AsyncSession, company: AACompany, line: AABankLine) -> None:
    """A line's match changed: its month's reconciliation no longer holds, other lines may match differently,
    and the books move."""
    await bank.void_reconciliations(db, company.id, line.account_code, line.line_date)
    await db.flush()
    await bank.rematch(db, company)
    touch_books(company)


async def _month_out(db: AsyncSession, user: User, company: AACompany, line: AABankLine) -> BankMonthOut:
    return await bank_month(company.id, line.account_code, f"{line.line_date:%Y-%m}", user, db)


@router.post("/bank-lines/{line_id}/confirm", response_model=BankMonthOut)
async def confirm_line(line_id: uuid.UUID, body: ConfirmLineIn | None = None, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    line = await _line_or_404(db, ent, line_id)
    company = await company_or_404(db, ent, line.company_id)
    if not line.account_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose which bank account this statement is first")
    before = audit.snapshot(line, _LINE_FIELDS)
    body = body or ConfirmLineIn()
    full = c2(abs(line.amount))
    if body.kind is None:
        if line.match_status not in ("matched", "suggested") or not line.match_kind:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing is proposed for this line; pick a match")
        if line.match_kind == "posting" and not (line.posting or {}).get("account"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick the account to post this line to")
    elif body.kind == "posting":
        chart = await ensure_chart(db, company)
        account = chart.get(body.account_code or "")
        if account is None or not account.active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick an active account from the chart")
        if account.code == line.account_code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A line can't post to its own bank account")
        line.match_kind, line.matched_ref, line.match_amount = "posting", "", full
        line.posting = {"kind": "manual", "account": account.code, "label": f"{account.code} {account.name}"}
    else:
        if not body.ref:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick what this line pays")
        listed = any(c.get("ref") == body.ref and c.get("kind") == body.kind for c in line.candidates or [])
        if body.kind == "document" and not listed:
            try:
                doc_id = uuid.UUID(body.ref)
            except ValueError:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown document") from None
            doc = (await db.execute(select(AADocument).where(
                AADocument.id == doc_id, AADocument.company_id == company.id, AADocument.enterprise_id == ent,
                AADocument.deleted_at.is_(None)))).scalar_one_or_none()
            if doc is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "That document isn't in this company")
            receipt = (await db.execute(select(AADocument.id).where(
                AADocument.settles_document_id == doc.id, AADocument.company_id == company.id,
                AADocument.deleted_at.is_(None), AADocument.excluded.is_(False))
                .order_by(AADocument.doc_date, AADocument.id).limit(1))).scalar_one_or_none()
            if receipt is not None:  # a linked receipt is this invoice's payment: the line is that receipt
                body = body.model_copy(update={"ref": str(receipt)})
        elif not listed:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick one of the candidates shown for this line")
        if body.amount is not None and body.amount > full:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The amount can't be more than the line")
        line.match_kind, line.matched_ref = body.kind, body.ref
        line.match_amount = body.amount or full
        line.posting = {}
    line.match_status, line.review_reason = "confirmed", ""
    line.matched_by, line.matched_at = user.id, datetime.now(timezone.utc)
    line.rejected = [r for r in (line.rejected or []) if r != line.matched_ref]
    await bank.learn_from(db, company, line, None)
    audit.record(db, label=_line_label(line), ent=ent, company_id=company.id, user=user, entity="bank_line",
                 entity_id=line.id, action="match_confirmed", before=before, after=audit.snapshot(line, _LINE_FIELDS))
    await _after_change(db, company, line)
    await db.commit()
    return await _month_out(db, user, company, line)


@router.post("/bank-lines/{line_id}/reject", response_model=BankMonthOut)
async def reject_line(line_id: uuid.UUID, body: LineReasonIn | None = None, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """Say no to the current match (it won't be proposed again) and match the line afresh."""
    ent = scope_for(user)
    line = await _line_or_404(db, ent, line_id)
    company = await company_or_404(db, ent, line.company_id)
    before = audit.snapshot(line, _LINE_FIELDS)
    if line.match_status != "excluded":
        refused = line.matched_ref or ("posting" if line.match_kind == "posting" else "")
        if refused:
            line.rejected = sorted(set(line.rejected or []) | {refused})
    line.match_status, line.match_kind, line.matched_ref, line.match_amount = "unmatched", "", "", None
    line.posting, line.matched_by, line.matched_at = {}, user.id, datetime.now(timezone.utc)
    audit.record(db, label=_line_label(line), ent=ent, company_id=company.id, user=user, entity="bank_line",
                 entity_id=line.id, action="match_rejected", before=before, after=audit.snapshot(line, _LINE_FIELDS),
                 reason=body.reason if body else "")
    await _after_change(db, company, line)
    await db.commit()
    return await _month_out(db, user, company, line)


@router.post("/bank-lines/{line_id}/exclude", response_model=BankMonthOut)
async def exclude_line(line_id: uuid.UUID, body: LineReasonIn | None = None, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Leave a line out of matching and the books (a misread or duplicated line)."""
    ent = scope_for(user)
    line = await _line_or_404(db, ent, line_id)
    company = await company_or_404(db, ent, line.company_id)
    before = audit.snapshot(line, _LINE_FIELDS)
    line.match_status, line.match_kind, line.matched_ref, line.match_amount = "excluded", "", "", None
    line.posting, line.review_reason = {}, ""
    line.matched_by, line.matched_at = user.id, datetime.now(timezone.utc)
    audit.record(db, label=_line_label(line), ent=ent, company_id=company.id, user=user, entity="bank_line",
                 entity_id=line.id, action="exclude", before=before, after=audit.snapshot(line, _LINE_FIELDS),
                 reason=body.reason if body else "")
    await _after_change(db, company, line)
    await db.commit()
    return await _month_out(db, user, company, line)


@router.post("/companies/{company_id}/bank/rematch", response_model=BankOverviewOut)
async def rematch_company(company_id: uuid.UUID, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    _, company = await _company(db, user, company_id)
    await bank.rematch(db, company)
    touch_books(company)
    await db.commit()
    return await bank_overview(company_id, user, db)


@router.patch("/bank-statements/{statement_id}", response_model=BankStatementOut)
async def patch_statement(statement_id: uuid.UUID, body: StatementPatch, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    statement = (await db.execute(select(AABankStatement).where(
        AABankStatement.id == statement_id, AABankStatement.enterprise_id == ent))).scalar_one_or_none()
    if statement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found")
    company = await company_or_404(db, ent, statement.company_id)
    account = (await db.execute(select(AAAccount).where(
        AAAccount.company_id == company.id, AAAccount.code == body.account_code))).scalar_one_or_none()
    if account is None or not account.active or account.type != "asset":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick an active asset account (Cash in bank or a sub-account)")
    before = {"account_code": statement.account_code}
    old = statement.account_code
    await bank.assign_account(db, statement, account)
    if old:
        await bank.void_reconciliations(db, company.id, old, statement.period_start or date.min)
    await bank.void_reconciliations(db, company.id, account.code, statement.period_start or date.min)
    audit.record(db, label=f"{statement.bank_name} {statement.account_number}".strip(), ent=ent,
                 company_id=company.id, user=user, entity="bank_statement", entity_id=statement.id,
                 action="update", before=before, after={"account_code": account.code})
    await bank.rematch(db, company)
    touch_books(company)
    await db.commit()
    return statement


@router.post("/companies/{company_id}/bank/reconcile", response_model=ReconcileOut)
async def reconcile_account(company_id: uuid.UUID, body: ReconcileIn, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    """Reconcile one account for one month: saved (with the report PDF) only when it ties."""
    ent, company = await _company(db, user, company_id)
    account = next((a for a in await bank.bank_accounts(db, company.id) if a.code == body.account_code), None)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank account not found")
    rec, problem = await bank.reconcile_month(db, company, account.code, body.month_start.replace(day=1))
    await bank.refresh_opening_flag(db, company)
    if rec is None:
        await db.commit()
        return ReconcileOut(ok=False, problem=problem)
    out = ReconcileOut(ok=rec.ok, statement_balance=rec.statement_balance, book_balance=rec.book_balance,
                       outstanding=rec.outstanding, difference=rec.difference, uncleared=list(rec.uncleared),
                       open_lines=len(rec.open_lines))
    if not rec.ok:
        out.problem = (f"{len(rec.open_lines)} line(s) still need a match." if rec.open_lines else
                       f"The books differ from the statement by ₱{rec.difference:,.2f} after uncleared items.")
        await db.commit()
        return out
    row = await bank.save_reconciliation(db, company, rec, account, user.id, user.email or "")
    audit.record(db, label=f"{account.code} {account.name} · {audit.month_label(rec.month_start)}", ent=ent,
                 company_id=company.id, user=user, entity="bank_reconciliation", entity_id=row.id, action="reconcile",
                 after={"statement_balance": rec.statement_balance, "book_balance": rec.book_balance,
                        "uncleared": len(rec.uncleared)})
    await db.commit()
    out.reconciliation = BankReconciliationOut.model_validate(row)
    return out


@router.get("/bank-reconciliations/{rec_id}/file")
async def reconciliation_file(rec_id: uuid.UUID, user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    row = (await db.execute(select(AABankReconciliation).where(
        AABankReconciliation.id == rec_id, AABankReconciliation.enterprise_id == ent))).scalar_one_or_none()
    target = stored_file(row.file_path) if row and row.file_path else None
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(target, media_type="application/pdf",
                        filename=f"Bank-reconciliation-{row.account_code}-{row.month_start:%Y-%m}.pdf")


@router.get("/companies/{company_id}/bank/rules", response_model=list[BankRuleOut])
async def list_rules(company_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent, company = await _company(db, user, company_id)
    return (await db.execute(select(AABankRule).where(AABankRule.enterprise_id == ent,
                                                      AABankRule.company_id == company.id)
                             .order_by(AABankRule.hits.desc(), AABankRule.pattern))).scalars().all()


@router.delete("/bank-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    row = (await db.execute(select(AABankRule).where(AABankRule.id == rule_id, AABankRule.enterprise_id == ent))
           ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    audit.record(db, label=row.pattern, ent=ent, company_id=row.company_id, user=user, entity="bank_rule",
                 entity_id=row.id, action="delete",
                 before={"pattern": row.pattern, "kind": row.kind, "account_code": row.account_code,
                         "payee_name": row.payee_name}, after=None)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
