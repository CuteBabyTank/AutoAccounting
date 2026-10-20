"""ATC databank: a company's remembered EWT ATC per supplier and per expense account."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AAAtcDefault, AACompany, AADocument, AASupplierRule
from app.models.user import User
from app.routers.accounting_periods import company_facts
from app.routers.accounting_scope import company_or_404, scope_for
from app.schemas.accounting import AtcCodeOut, AtcDatabankOut, AtcDefaultOut, AtcSet, AtcSupplierOut
from app.services.accounting import audit
from app.services.accounting.atc_prefs import Automatic, SeenSupplier, automatic_for, document_pick, supplier_rows
from app.services.accounting.compute.ewt import account_suggestions, ewt_codes, tree_suggestion
from app.services.accounting.compute.inputs import CompanyFacts, DocLine
from app.services.accounting.extraction import EXPENSE_ACCOUNTS
from app.services.accounting.parsing import normalize_tin

router = APIRouter()

# Expense accounts that can carry expanded withholding (salaries are withheld on compensation instead).
ATC_ACCOUNTS = tuple(a for a in EXPENSE_ACCOUNTS if a != "salaries")
_PAYMENT = (AADocument.client_role == "buyer", AADocument.category.in_(("purchases", "expenses")))


async def _touch(db: AsyncSession, company: AACompany, *where) -> None:
    """The quarters holding the affected payments (and later ones) may now use a different ATC: mark them stale."""
    await db.execute(update(AADocument).where(
        AADocument.company_id == company.id, AADocument.deleted_at.is_(None), *_PAYMENT, *where,
    ).values(updated_at=datetime.now(timezone.utc)))


async def _seen_suppliers(db: AsyncSession, company_id: uuid.UUID) -> list[SeenSupplier]:
    latest_name = func.array_agg(aggregate_order_by(AADocument.seller_name, AADocument.doc_date.desc().nulls_last()))
    rows = (await db.execute(select(
        AADocument.seller_tin, latest_name[1], func.count(AADocument.id), func.max(AADocument.doc_date),
    ).where(
        AADocument.company_id == company_id, AADocument.deleted_at.is_(None), AADocument.seller_tin != "", *_PAYMENT,
    ).group_by(AADocument.seller_tin))).all()
    return [SeenSupplier(tin, name or "", count, last) for tin, name, count, last in rows]


async def _automatic(db: AsyncSession, company_id: uuid.UUID, defaults: dict[str, str],
                     facts: CompanyFacts) -> dict[str, Automatic]:
    """tin -> what the returns use for the supplier's documents without their own ATC, and the tree's hint."""
    rows = (await db.execute(select(
        AADocument.seller_tin, AADocument.seller_name, AADocument.category, AADocument.account,
        AADocument.raw["nature"].astext, AADocument.raw["description"].astext, AADocument.gross_amount,
        AADocument.vat_amount, AADocument.withholding_amount, AADocument.seller_vat_registered,
    ).where(
        AADocument.company_id == company_id, AADocument.deleted_at.is_(None), AADocument.seller_tin != "",
        AADocument.ewt_atc == "", *_PAYMENT,
    ))).all()
    current: dict[str, list[str]] = {}
    tree: dict[str, list[tuple[str, str]]] = {}
    for tin, name, category, account, nature, description, gross, vat, withheld, vat_registered in rows:
        line = DocLine(id="", category=category, account=account, doc_type="", client_role="buyer", doc_date=None,
                       doc_number="", counterparty_tin=tin, counterparty_name=name or "", counterparty_address="",
                       gross=gross, vat=vat, withholding=withheld, counterparty_vat_registered=vat_registered,
                       nature=nature or "", description=(description or "")[:200])
        current.setdefault(tin, []).append(document_pick(line, defaults.get(account, ""), facts))
        decision = tree_suggestion(line, facts)
        tree.setdefault(tin, []).append((decision.atc, decision.reason))
    return {tin: automatic_for(current[tin], tree[tin]) for tin in current}


async def suggestions_from_other_companies(db: AsyncSession, company: AACompany,
                                           tins: set[str]) -> dict[str, tuple[str, str]]:
    """tin -> (ATC, company name): the most recently set ATC for the supplier in another company of the firm."""
    if not tins:
        return {}
    rows = (await db.execute(select(
        AASupplierRule.counterparty_tin, AASupplierRule.ewt_atc, AACompany.registered_name,
    ).join(AACompany, AACompany.id == AASupplierRule.company_id).where(
        AACompany.enterprise_id == company.enterprise_id, AACompany.id != company.id,
        AASupplierRule.ewt_atc != "", AASupplierRule.counterparty_tin.in_(tins),
    ).order_by(AASupplierRule.updated_at.desc()))).all()
    out: dict[str, tuple[str, str]] = {}
    for tin, atc, name in rows:
        out.setdefault(tin, (atc, name))
    return out


async def _databank(db: AsyncSession, company: AACompany) -> AtcDatabankOut:
    defaults = dict((await db.execute(select(AAAtcDefault.account, AAAtcDefault.ewt_atc).where(
        AAAtcDefault.company_id == company.id))).all())
    rules = {tin: (atc, name) for tin, atc, name in (await db.execute(select(
        AASupplierRule.counterparty_tin, AASupplierRule.ewt_atc, AASupplierRule.counterparty_name,
    ).where(AASupplierRule.company_id == company.id))).all()}
    seen = await _seen_suppliers(db, company.id)
    missing = {s.tin for s in seen if not rules.get(s.tin, ("", ""))[0]}
    elsewhere = await suggestions_from_other_companies(db, company, missing)
    facts = company_facts(company)
    automatic = await _automatic(db, company.id, defaults, facts)
    return AtcDatabankOut(
        defaults=[AtcDefaultOut(account=a, ewt_atc=defaults.get(a, ""),
                                suggestion=" / ".join(account_suggestions(a, facts))) for a in ATC_ACCOUNTS],
        suppliers=[AtcSupplierOut(**vars(r)) for r in supplier_rows(seen, rules, elsewhere, automatic)],
    )


@router.get("/atc-codes", response_model=list[AtcCodeOut])
async def list_atc_codes(user: User = Depends(get_current_user)):
    """Every expanded withholding ATC a payment can carry (the pickers' list)."""
    return [AtcCodeOut(code=c, nature=n, rate=r) for c, n, r in ewt_codes()]


@router.get("/companies/{company_id}/atc-databank", response_model=AtcDatabankOut)
async def get_atc_databank(company_id: uuid.UUID, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    company = await company_or_404(db, scope_for(user), company_id)
    return await _databank(db, company)


async def _set_supplier(db: AsyncSession, company: AACompany, tin: str, atc: str, name: str) -> None:
    """Upsert the supplier's ATC; an empty ATC forgets it but keeps the supplier's category / GL memory.
    A new rule has no category, so extraction keeps classifying the supplier's documents itself."""
    stmt = pg_insert(AASupplierRule).values(
        id=uuid.uuid4(), company_id=company.id, counterparty_tin=tin, category="", account="",
        ewt_atc=atc, counterparty_name=name.strip()[:255], updated_at=datetime.now(timezone.utc),
    )
    learned = {"ewt_atc": stmt.excluded.ewt_atc, "updated_at": stmt.excluded.updated_at}
    if name.strip():
        learned["counterparty_name"] = stmt.excluded.counterparty_name
    await db.execute(stmt.on_conflict_do_update(constraint="uq_aa_supplier_rule", set_=learned))
    if not atc:  # nothing left to remember
        await db.execute(delete(AASupplierRule).where(
            AASupplierRule.company_id == company.id, AASupplierRule.counterparty_tin == tin,
            AASupplierRule.category == "", AASupplierRule.gl_account_code == ""))


@router.put("/companies/{company_id}/atc-databank/suppliers/{tin}", response_model=AtcDatabankOut)
async def set_supplier_atc(company_id: uuid.UUID, tin: str, body: AtcSet, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    digits = normalize_tin(tin)[0]
    if not digits:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A supplier needs a 9-digit TIN")
    before = (await db.execute(select(AASupplierRule.ewt_atc).where(
        AASupplierRule.company_id == company.id, AASupplierRule.counterparty_tin == digits))).scalar() or ""
    await _set_supplier(db, company, digits, body.ewt_atc, body.name)
    audit.record(db, label=f"Supplier {digits}",
                 ent=ent, company_id=company.id, user=user, entity="atc", entity_id=digits, action="supplier",
                 before={"ewt_atc": before}, after={"ewt_atc": body.ewt_atc})
    await _touch(db, company, AADocument.seller_tin == digits)
    await db.commit()
    return await _databank(db, company)


@router.post("/companies/{company_id}/atc-databank/use-suggestions", response_model=AtcDatabankOut)
async def use_suggestions(company_id: uuid.UUID, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Adopt every supplier ATC suggested from another company (suppliers with no ATC here yet)."""
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    current = await _databank(db, company)
    adopted = [s for s in current.suppliers if s.suggestion and not s.ewt_atc]
    for s in adopted:
        await _set_supplier(db, company, s.tin, s.suggestion, s.name)
    if adopted:
        audit.record(db, label="Suggested supplier ATCs",
                     ent=ent, company_id=company.id, user=user, entity="atc", entity_id="suppliers",
                     action="use_suggestions", before={s.tin: "" for s in adopted},
                     after={s.tin: s.suggestion for s in adopted})
    if adopted:
        await _touch(db, company, AADocument.seller_tin.in_([s.tin for s in adopted]))
    await db.commit()
    return await _databank(db, company)


@router.post("/companies/{company_id}/atc-databank/use-hints", response_model=AtcDatabankOut)
async def use_hints(company_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Adopt every ATC the decision tree suggests for suppliers with no ATC here yet (it then reaches the returns)."""
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    current = await _databank(db, company)
    adopted = [s for s in current.suppliers if s.hint and not s.ewt_atc]
    for s in adopted:
        await _set_supplier(db, company, s.tin, s.hint, s.name)
    if adopted:
        audit.record(db, label="AutoAccounting's supplier ATCs",
                     ent=ent, company_id=company.id, user=user, entity="atc", entity_id="suppliers",
                     action="use_hints", before={s.tin: "" for s in adopted},
                     after={s.tin: s.hint for s in adopted})
        await _touch(db, company, AADocument.seller_tin.in_([s.tin for s in adopted]))
    await db.commit()
    return await _databank(db, company)


@router.put("/companies/{company_id}/atc-databank/accounts/{account}", response_model=AtcDatabankOut)
async def set_account_atc(company_id: uuid.UUID, account: str, body: AtcSet,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    if account not in ATC_ACCOUNTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{account} doesn't carry expanded withholding")
    before = (await db.execute(select(AAAtcDefault.ewt_atc).where(
        AAAtcDefault.company_id == company.id, AAAtcDefault.account == account))).scalar() or ""
    audit.record(db, label=f"Default ATC · {account}",
                 ent=ent, company_id=company.id, user=user, entity="atc", entity_id=account, action="account",
                 before={"ewt_atc": before}, after={"ewt_atc": body.ewt_atc})
    if body.ewt_atc:
        stmt = pg_insert(AAAtcDefault).values(id=uuid.uuid4(), company_id=company.id, account=account,
                                              ewt_atc=body.ewt_atc, updated_at=datetime.now(timezone.utc))
        await db.execute(stmt.on_conflict_do_update(
            constraint="uq_aa_atc_default", set_={"ewt_atc": stmt.excluded.ewt_atc,
                                                  "updated_at": stmt.excluded.updated_at}))
    else:
        await db.execute(delete(AAAtcDefault).where(AAAtcDefault.company_id == company.id,
                                                    AAAtcDefault.account == account))
    await _touch(db, company, AADocument.account == account)
    await db.commit()
    return await _databank(db, company)
