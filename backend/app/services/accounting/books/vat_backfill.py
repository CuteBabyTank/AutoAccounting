"""QBO 01's VAT-difference rule applied to documents stored before it (idempotent, run when periods load).

Before 01 a purchase whose VAT wasn't 12% of its VATable amount lost its input VAT (``input_vat_valid`` False). Now it
claims 12% and the excess goes to ``1310 VAT difference - for review``. Documents in a quarter whose return is
already filed keep the old treatment (the return didn't claim it) and get a note; the others are switched, with an
audit event, and their quarter's generated versions show as stale. Closed months of the books correct themselves
through ``book_close.apply_closes`` (a correcting entry on the first open day), as for any document edit.
"""

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AACompany, AADocument, AAPeriod
from app.services.accounting import audit
from app.services.accounting.review_rules import apply_legacy_vat_fix, legacy_vat_fix

SYSTEM = SimpleNamespace(id=None, email="AutoAccounting (VAT difference rule)")
_FIELDS = ("input_vat_valid", "vat_treatment")


async def backfill_vat_difference(db: AsyncSession, company: AACompany) -> int:
    """Switch the company's older VAT-mismatch purchases to the VAT-difference treatment; returns how many changed
    (flushes nothing itself, the caller's commit keeps it)."""
    if company.vat_status != "vat":
        return 0
    docs = (await db.execute(select(AADocument).where(
        AADocument.enterprise_id == company.enterprise_id, AADocument.company_id == company.id,
        AADocument.deleted_at.is_(None), AADocument.input_vat_valid.is_(False), AADocument.client_role == "buyer",
        AADocument.category.in_(("purchases", "expenses")), AADocument.vat_amount > 0,
        AADocument.review_reasons.contains(["vat_math_mismatch"]),
    ))).scalars().all()
    if not docs:
        return 0
    filed = {(p.year, p.quarter) for p in (await db.execute(select(AAPeriod).where(
        AAPeriod.enterprise_id == company.enterprise_id, AAPeriod.company_id == company.id,
        AAPeriod.quarter >= 1))).scalars() if p.filed_at is not None or p.filed_forms}
    changed = 0
    for doc in docs:
        is_filed = (doc.period_year, doc.period_quarter) in filed
        if legacy_vat_fix(doc, is_filed) is None:
            continue
        before = audit.snapshot(doc, _FIELDS)
        apply_legacy_vat_fix(doc, is_filed)
        if not is_filed:
            changed += 1
            audit.record(db, ent=company.enterprise_id, company_id=company.id, user=SYSTEM, entity="document",
                         entity_id=doc.id, action="update", before=before, after=audit.snapshot(doc, _FIELDS),
                         label=audit.document_label(doc),
                         reason="VAT not 12%: input VAT now claimed at 12%, the excess in VAT difference - for review "
                                "(rule applied to a document stored before it)")
    if changed:
        from app.services.accounting.books.loader import touch_books
        touch_books(company)
    return changed
