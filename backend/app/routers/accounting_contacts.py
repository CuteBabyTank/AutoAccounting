"""Customers and suppliers: contacts master, open items, aging, 2307s to receive / issue, customer statements."""

import asyncio
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AAAccount, AACompany, AAContact, AADocument, AASupplierRule
from app.models.user import User
from app.routers.accounting_scope import MANAGER_ROLES, company_or_404, scope_for
from app.schemas.accounting_contacts import (
    AgingOut, AgingRowOut, CertificateOut, ContactDocumentOut, ContactListOut, ContactOut, ContactPatch,
    ContactPaymentOut, ContactRowOut, Cwt2307In, Cwt2307Out, MergeIn, OpenItemOut, Outgoing2307Out, TieLineOut,
)
from app.services.accounting import audit
from app.services.accounting.books.closing import header_for
from app.services.accounting.books.receipts import party_key
from app.services.accounting.books.subledger import (
    Subledger, control_ties, counterparty, doc_kind, key_map_for, load_subledger, outgoing_2307_outputs, payment_rows,
)
from app.services.accounting.compute import writeoff
from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.compute.statement import activity as statement_activity
from app.services.accounting.compute.subledger import OpenItem, aging, aging_totals
from app.services.accounting.contacts import EDITABLE, merge_check, role_union
from app.services.accounting.subledger_report import aging_pdf, aging_xlsx, statement_pdf
from app.services.accounting.xlsx_preview import workbook_preview

router = APIRouter()
_MANILA = ZoneInfo("Asia/Manila")
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CONTACT_FIELDS = EDITABLE + ("aliases", "merged_into_id")


def today() -> date:
    return datetime.now(_MANILA).date()


def _role_matches(role: str, wanted: str) -> bool:
    return role == wanted or role == "both"


def _recovered(sub: Subledger) -> dict[str, Decimal]:
    return writeoff.recovered([p for p in sub.payments if p.on <= sub.as_of])


def _item_out(i: OpenItem, recovered: dict[str, Decimal] | None = None) -> OpenItemOut:
    d = i.doc
    return OpenItemOut(document_id=d.id, kind=d.kind, doc_number=d.doc_number, doc_date=d.doc_date, due=i.due,
                       total=d.total, withheld=d.withheld, paid=i.paid, open=i.open, days_past_due=i.days_past_due,
                       bucket=i.bucket, payment_unverified=d.payment_unverified, contact_name=d.contact_name,
                       contact_tin=d.contact_tin, opening=d.opening,
                       recovered=(recovered or {}).get(d.id, Decimal("0")))


async def _contact_or_404(db: AsyncSession, ent: uuid.UUID, contact_id: uuid.UUID) -> AAContact:
    row = (await db.execute(select(AAContact).where(AAContact.id == contact_id, AAContact.enterprise_id == ent))
           ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    return row


def _label(row: AAContact) -> str:
    return " · ".join(p for p in (row.registered_name, row.tin) if p) or row.key


def contact_rows(sub: Subledger, role: str) -> list[ContactRowOut]:
    """Customers (A/R) or suppliers (A/P) with their open balance, overdue part, pending 2307s and last activity."""
    kind = "ar" if role == "customer" else "ap"
    out = []
    for c in sub.contacts:
        if c.merged_into_id is not None or not _role_matches(c.role, role):
            continue
        items = [i for i in sub.items if i.doc.kind == kind and i.doc.contact_key == c.key]
        docs = [d for d in sub.docs if d.kind == kind and d.contact_key == c.key]
        pending = [x for x in sub.cwt if x.contact_key == c.key and x.status == "pending"] if kind == "ar" else []
        out.append(ContactRowOut(
            id=c.id, key=c.key, role=c.role, tin=c.tin, registered_name=c.registered_name,
            aliases=list(c.aliases or []), open_balance=c2(sum((i.open for i in items), ZERO)),
            overdue=c2(sum((i.open for i in items if i.days_past_due > 0), ZERO)), open_count=len(items),
            cwt_pending=c2(sum((x.amount for x in pending), ZERO)),
            unverified=sum(1 for i in items if i.doc.payment_unverified),
            last_date=max((d.doc_date for d in docs), default=None),
            payment_terms_days=getattr(c, "payment_terms_days", None),
        ))
    return sorted(out, key=lambda r: (-(r.open_balance > 0), r.registered_name.lower()))


@router.get("/companies/{company_id}/contacts", response_model=ContactListOut)
async def list_contacts(company_id: uuid.UUID, role: str = Query("customer", pattern="^(customer|supplier)$"),
                        as_of: date | None = None, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    sub = await load_subledger(db, company, as_of or today())
    await db.commit()  # contacts synced from the documents
    rows = contact_rows(sub, role)
    if role == "supplier":
        defaults = dict((await db.execute(select(AASupplierRule.counterparty_tin, AASupplierRule.gl_account_code).where(
            AASupplierRule.company_id == company.id, AASupplierRule.gl_account_code != ""))).all())
        for r in rows:
            r.default_account = defaults.get(r.tin, "")
    return ContactListOut(role=role, as_of=sub.as_of, contacts=rows,
                          total_open=c2(sum((r.open_balance for r in rows), ZERO)),
                          total_overdue=c2(sum((r.overdue for r in rows), ZERO)),
                          total_cwt_pending=c2(sum((r.cwt_pending for r in rows), ZERO)))


def _doc_out(d: AADocument, open_by_id: dict[str, Decimal]) -> ContactDocumentOut:
    kind = doc_kind(d) or ("2307" if d.category == "2307" else "receipt" if d.settles_document_id else "other")
    return ContactDocumentOut(id=str(d.id), doc_number=d.doc_number or "", doc_date=d.doc_date,
                              title=d.document_title or "", category=d.category, kind=kind,
                              total=d.gross_amount, withheld=d.withholding_amount, period_year=d.period_year,
                              period_quarter=d.period_quarter, open=open_by_id.get(str(d.id)))


_SOURCES = {"rcpt": "receipt", "paid": "paid_on", "bank": "bank", "wo": "writeoff"}


async def _supplier_defaults(db: AsyncSession, company_id: uuid.UUID, tin: str) -> tuple[str, str]:
    if not tin:
        return "", ""
    row = (await db.execute(select(AASupplierRule.gl_account_code, AASupplierRule.ewt_atc).where(
        AASupplierRule.company_id == company_id, AASupplierRule.counterparty_tin == tin))).first()
    return (row[0] or "", row[1] or "") if row else ("", "")


async def _contact_out(db: AsyncSession, company: AACompany, row: AAContact, sub: Subledger) -> ContactOut:
    key_map = key_map_for(sub.contacts)
    target = key_map.get(row.key, row.key)
    keys = {k for k, t in key_map.items() if t == target}
    mine = [d for d in sub.documents.values() if party_key(*counterparty(d)[:2]) in keys]
    mine.sort(key=lambda d: (d.doc_date or date.min, d.doc_number or ""), reverse=True)
    open_docs = [d for d in sub.docs if d.contact_key == target]
    items = [i for i in sub.items if i.doc.contact_key == target]
    open_by_id = {i.doc.id: i.open for i in items}
    numbers = {str(d.id): d.doc_number or "" for d in sub.documents.values()}
    payments = [ContactPaymentOut(document_id=p.settles, doc_number=numbers.get(p.settles, ""), on=p.on,
                                  amount=amount, via=p.via, source=_SOURCES.get(p.id.split(":", 1)[0], "paid_on"),
                                  ref=p.ref or "")
                for p, amount in payment_rows(open_docs, sub.payments) if p.on <= sub.as_of]
    payments.sort(key=lambda p: p.on, reverse=True)
    by_id = {d.id: d for d in open_docs}

    def cert_label(doc_id: str | None) -> str:
        d = sub.documents.get(doc_id or "")
        return " · ".join(p for p in (d.doc_number or "2307", d.doc_date.isoformat() if d.doc_date else "")
                          if p) if d else ""

    cwt = [Cwt2307Out(document_id=x.doc_id, doc_number=by_id[x.doc_id].doc_number, doc_date=by_id[x.doc_id].doc_date,
                      amount=x.amount, year=x.period[0] if x.period else None,
                      quarter=x.period[1] if x.period else None, status=x.status, certificate_id=x.document_id,
                      certificate_label=cert_label(x.document_id), source=x.source)
           for x in sub.cwt if x.contact_key == target and x.doc_id in by_id]
    certificates = [CertificateOut(id=r.id, label=cert_label(r.id)) for r in sub.received if r.contact_key == target]
    outputs = await outgoing_2307_outputs(db, company)
    outgoing = []
    for d in open_docs:
        atc, tax = sub.ewt.get(d.id, ("", ZERO))
        if d.kind == "ap" and tax > 0 and d.period:
            outgoing.append(Outgoing2307Out(document_id=d.id, doc_number=d.doc_number, doc_date=d.doc_date, atc=atc,
                                            amount=tax, year=d.period[0], quarter=d.period[1],
                                            output_id=outputs.get(d.period)))
    account, atc = await _supplier_defaults(db, company.id, row.tin)
    return ContactOut(
        id=row.id, key=row.key, role=row.role, tin=row.tin, registered_name=row.registered_name,
        aliases=list(row.aliases or []), address=row.address, vat_status=row.vat_status,
        payment_terms_days=row.payment_terms_days, default_account=account, default_atc=atc,
        manual=list(row.manual or []), merged_into_id=row.merged_into_id,
        merged_from=[c.registered_name for c in sub.contacts if c.merged_into_id == row.id],
        as_of=sub.as_of,
        receivable=c2(sum((i.open for i in items if i.doc.kind == "ar"), ZERO)),
        payable=c2(sum((i.open for i in items if i.doc.kind == "ap"), ZERO)),
        documents=[_doc_out(d, open_by_id) for d in mine], payments=payments,
        open_items=[_item_out(i, _recovered(sub)) for i in items], cwt_2307s=cwt, certificates=certificates,
        outgoing_2307s=sorted(outgoing, key=lambda o: o.doc_date, reverse=True),
    )


@router.get("/contacts/{contact_id}", response_model=ContactOut)
async def get_contact(contact_id: uuid.UUID, as_of: date | None = None, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    row = await _contact_or_404(db, ent, contact_id)
    company = await company_or_404(db, ent, row.company_id)
    sub = await load_subledger(db, company, as_of or today())
    await db.commit()
    return await _contact_out(db, company, row, sub)


async def _set_supplier_rule(db: AsyncSession, company: AACompany, tin: str, name: str, **values: str) -> None:
    """Upsert only the given databank fields (gl_account_code / ewt_atc) of the supplier's rule."""
    stmt = pg_insert(AASupplierRule).values(
        id=uuid.uuid4(), company_id=company.id, counterparty_tin=tin, category="", account="",
        counterparty_name=name[:255], updated_at=datetime.now(_MANILA), **values,
    )
    learned = {k: getattr(stmt.excluded, k) for k in values} | {"updated_at": stmt.excluded.updated_at}
    await db.execute(stmt.on_conflict_do_update(constraint="uq_aa_supplier_rule", set_=learned))


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
async def update_contact(contact_id: uuid.UUID, body: ContactPatch, as_of: date | None = None,
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.routers.accounting_atc import _touch

    ent = scope_for(user)
    row = await _contact_or_404(db, ent, contact_id)
    company = await company_or_404(db, ent, row.company_id)
    sent = body.model_fields_set - {"reason"}
    old_account, old_atc = await _supplier_defaults(db, company.id, row.tin)
    before = audit.snapshot(row, EDITABLE) | {"default_account": old_account, "default_atc": old_atc}
    manual = list(row.manual or [])
    for name in EDITABLE:
        if name not in sent:
            continue
        value = getattr(body, name)
        if value is None and name != "payment_terms_days":
            continue
        if name in ("registered_name", "address"):
            value = (value or "").strip()
            if name == "registered_name" and not value:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "A contact needs a name")
        setattr(row, name, value)
        if name not in manual:
            manual.append(name)
    row.manual = manual
    rule: dict[str, str] = {}
    if "default_account" in sent:
        code = (body.default_account or "").strip()
        found = (await db.execute(select(AAAccount.locked).where(
            AAAccount.company_id == company.id, AAAccount.code == code, AAAccount.active.is_(True)))).first() \
            if code else None
        if code and found is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Account {code} isn't an active account in the chart")
        if found is not None and found[0] and code != old_account:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Account {code} is locked: choose another default "
                                                             "account (unlock it in the chart of accounts first)")
        rule["gl_account_code"] = code
    if "default_atc" in sent:
        rule["ewt_atc"] = (body.default_atc or "").strip().upper()
    if rule:
        if not row.tin:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A default account or ATC needs the contact's TIN")
        await _set_supplier_rule(db, company, row.tin, row.registered_name, **rule)
        await _touch(db, company, AADocument.seller_tin == row.tin)
    after = audit.snapshot(row, EDITABLE) | {"default_account": rule.get("gl_account_code", old_account),
                                             "default_atc": rule.get("ewt_atc", old_atc)}
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="contact", entity_id=row.id, action="update",
                 before=before, after=after, reason=body.reason, label=_label(row))
    await db.commit()
    sub = await load_subledger(db, company, as_of or today())
    await db.commit()
    return await _contact_out(db, company, row, sub)


@router.post("/contacts/{contact_id}/merge", response_model=ContactOut)
async def merge_contact(contact_id: uuid.UUID, body: MergeIn, as_of: date | None = None,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Merge this contact into another one (same party under two names, or a mistyped TIN)."""
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can merge contacts")
    ent = scope_for(user)
    source = await _contact_or_404(db, ent, contact_id)
    target = await _contact_or_404(db, ent, body.into)
    company = await company_or_404(db, ent, source.company_id)
    rows = list((await db.execute(select(AAContact).where(AAContact.company_id == company.id))).scalars().all())
    problem = merge_check(source, target, rows)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    before_target = audit.snapshot(target, ("aliases", "role"))
    source.merged_into_id = target.id
    names = [source.registered_name, *(source.aliases or [])]
    target.aliases = list(target.aliases or []) + [n for n in dict.fromkeys(names)
                                                   if n and n != target.registered_name
                                                   and n not in (target.aliases or [])]
    target.role = role_union(target.role, source.role)
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="contact", entity_id=source.id, action="merge",
                 before={"merged_into": None},
                 after={"merged_into": str(target.id), "into": _label(target)}, reason=body.reason,
                 label=_label(source))
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="contact", entity_id=target.id,
                 action="merge_in", before=before_target, after=audit.snapshot(target, ("aliases", "role")),
                 reason=body.reason, label=_label(target))
    await db.commit()
    sub = await load_subledger(db, company, as_of or today())
    await db.commit()
    return await _contact_out(db, company, target, sub)


@router.put("/documents/{document_id}/cwt-2307", response_model=Cwt2307Out)
async def mark_cwt_2307(document_id: uuid.UUID, body: Cwt2307In, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Mark a sale's "2307 to receive" received (optionally linking the uploaded 2307) or pending; auto forgets."""
    ent = scope_for(user)
    doc = (await db.execute(select(AADocument).where(
        AADocument.id == document_id, AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None)))
           ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if doc_kind(doc) != "ar" or (doc.withholding_amount or ZERO) <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a sale the customer withheld tax on has a 2307 to receive")
    mark: dict = {}
    if body.status != "auto":
        mark = {"status": body.status}
        if body.certificate_id is not None:
            if body.status != "received":
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a received 2307 can be linked")
            cert = (await db.execute(select(AADocument).where(
                AADocument.id == body.certificate_id, AADocument.company_id == doc.company_id,
                AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None), AADocument.category == "2307",
                AADocument.client_role == "seller"))).scalar_one_or_none()
            if cert is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "That document isn't a 2307 received by this company")
            mark["document_id"] = str(cert.id)
    before = {"cwt_2307": doc.cwt_2307 or {}}
    doc.cwt_2307 = mark
    audit.record(db, ent=ent, company_id=doc.company_id, user=user, entity="document", entity_id=doc.id,
                 action="cwt_2307", before=before, after={"cwt_2307": mark}, reason=body.reason,
                 label=audit.document_label(doc))
    await db.commit()
    company = await company_or_404(db, ent, doc.company_id)
    sub = await load_subledger(db, company, today())
    await db.commit()
    item = next((x for x in sub.cwt if x.doc_id == str(doc.id)), None)
    if item is None:  # dated after today: still answer with what was stored
        return Cwt2307Out(document_id=str(doc.id), doc_number=doc.doc_number or "", doc_date=doc.doc_date,
                          amount=doc.withholding_amount, year=None, quarter=None,
                          status=mark.get("status", "pending"), certificate_id=mark.get("document_id"),
                          certificate_label="", source="user" if mark else "")
    cert = sub.documents.get(item.document_id or "")
    return Cwt2307Out(document_id=item.doc_id, doc_number=doc.doc_number or "", doc_date=doc.doc_date,
                      amount=item.amount, year=item.period[0] if item.period else None,
                      quarter=item.period[1] if item.period else None, status=item.status,
                      certificate_id=item.document_id,
                      certificate_label=(cert.doc_number or "2307") if cert else "", source=item.source)


def aging_out(sub: Subledger, kind: str, tie: list | None = None, tie_note: str = "") -> AgingOut:
    items = [i for i in sub.items if i.doc.kind == kind]
    rows = aging(items)
    ids = {c.key: c.id for c in sub.contacts}
    recovered = _recovered(sub)
    return AgingOut(kind=kind, as_of=sub.as_of, totals=aging_totals(rows), items=[_item_out(i, recovered) for i in items],
                    rows=[AgingRowOut(contact_id=ids.get(r.contact_key), name=r.name, tin=r.tin, buckets=r.buckets,
                                      total=r.total, count=r.count, unverified=r.unverified) for r in rows],
                    tie=[TieLineOut(key=t.key, label=t.label, amount=t.amount) for t in tie or []], tie_note=tie_note)


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ._-]+", "", text).strip() or "company"


@router.get("/companies/{company_id}/aging", response_model=AgingOut)
async def get_aging(company_id: uuid.UUID, kind: str = Query("ar", pattern="^(ar|ap)$"), as_of: date | None = None,
                    format: str = Query("json", pattern="^(json|xlsx|pdf)$"), preview: bool = Query(False),
                    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    sub = await load_subledger(db, company, as_of or today())
    ties, tie_note = await control_ties(db, company, sub)
    tie = ties.get(kind, [])
    await db.commit()
    if format == "json":
        return aging_out(sub, kind, tie, tie_note)
    items = [i for i in sub.items if i.doc.kind == kind]
    rows = aging(items)
    header = header_for(company)
    what = "AR aging" if kind == "ar" else "AP aging"
    name = f"{_safe_name(company.registered_name)} {what} {sub.as_of.isoformat()}.{format}"
    if format == "xlsx":
        data = await asyncio.get_running_loop().run_in_executor(
            None, lambda: aging_xlsx(header, kind, sub.as_of, rows, aging_totals(rows), items, tie))
        media = _XLSX
        if preview:  # the in-app preview: the workbook's sheets as cells
            return JSONResponse({"sheets": await asyncio.get_running_loop().run_in_executor(None, workbook_preview, data)})
    else:
        data = await asyncio.get_running_loop().run_in_executor(
            None, lambda: aging_pdf(header, kind, sub.as_of, rows, aging_totals(rows), items, tie))
        media = "application/pdf"
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/contacts/{contact_id}/statement")
async def customer_statement(contact_id: uuid.UUID, as_of: date | None = None,
                             type: str = Query("open_item", pattern="^(open_item|balance_forward|transaction)$"),
                             start: date | None = None, user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """Customer statement with an aging footer and the 2307s still owed: open item (what is open on the date),
    balance forward (balance at ``start`` + the period's activity) or transaction (the period's activity)."""
    ent = scope_for(user)
    row = await _contact_or_404(db, ent, contact_id)
    company = await company_or_404(db, ent, row.company_id)
    as_of = as_of or today()
    start = start or as_of.replace(day=1)
    if start > as_of:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The statement starts after its end date")
    if start < date(2000, 1, 1) or (as_of - start).days > 3660 or as_of.year > 2100:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a period of ten years or less, from 2000 on")
    sub = await load_subledger(db, company, as_of)
    await db.commit()
    target = key_map_for(sub.contacts).get(row.key, row.key)
    items = [i for i in sub.items if i.doc.kind == "ar" and i.doc.contact_key == target]
    pending = c2(sum((x.amount for x in sub.cwt if x.contact_key == target and x.status == "pending"), ZERO))
    docs = [d for d in sub.docs if d.kind == "ar" and d.contact_key == target and d.doc_date <= as_of]
    act = statement_activity(docs, [(p, a) for p, a in payment_rows(docs, sub.payments) if p.on <= as_of], start,
                             as_of)
    data = await asyncio.get_running_loop().run_in_executor(None, lambda: statement_pdf(
        header_for(company), {"name": row.registered_name, "tin": row.tin, "address": row.address}, sub.as_of, items,
        pending, kind=type, start=start, activity=act))
    name = f"{_safe_name(row.registered_name)} statement {sub.as_of.isoformat()}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
