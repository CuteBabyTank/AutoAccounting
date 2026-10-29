"""The asset register: one row per capital-goods document, kept in step at generation time."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AACompany, AAAsset, AADocument
from app.services.accounting.compute.cogs import cost_base
from app.services.accounting.compute.depreciation import DEFAULT_LIFE_MONTHS, Asset
from app.services.accounting.compute.due_dates import quarter_start


def is_asset_document(doc: AADocument) -> bool:
    """A live capital-goods purchase: it depreciates; deleted, excluded, re-filed or receipt-linked documents drop out."""
    return (doc.deleted_at is None and not doc.excluded and doc.account == "capital_goods"
            and doc.category in ("purchases", "expenses") and doc.client_role == "buyer"
            and doc.settles_document_id is None)


def asset_defaults(doc: AADocument, vat_registered: bool, fye: int) -> tuple[str, Decimal, date] | None:
    """(description, cost, in service) for a new register row; None when the document has no date or period."""
    from app.routers.accounting_periods import doc_line  # local: the router module imports this one

    if doc.doc_date is not None:
        in_service = doc.doc_date
    elif doc.period_year is not None and doc.period_quarter is not None:
        in_service = quarter_start(doc.period_year, doc.period_quarter, fye)
    else:
        return None
    description = f"{doc.seller_name} {doc.doc_number}".strip()[:255] or "Capital goods"
    return description, cost_base(doc_line(doc), vat_registered), in_service


def to_asset(row: AAAsset, doc: AADocument | None) -> Asset:
    return Asset(id=str(row.id), document_id=str(row.document_id or ""), description=row.description,
                 doc_number=doc.doc_number if doc else "Opening", cost=row.cost, in_service=row.in_service,
                 life_months=row.useful_life_months or DEFAULT_LIFE_MONTHS, end_date=row.end_date)


async def sync_assets(db: AsyncSession, company: AACompany) -> list[tuple[AAAsset, AADocument]]:
    """Create missing register rows, follow document cost changes, and return the active (row, document) pairs.

    Rows of documents that were deleted, excluded or re-filed stay (so edits survive a restore) but are
    not returned. Edited description, in-service date, life and end date are kept. Flushes; the caller commits.
    """
    docs = (await db.execute(select(AADocument).where(
        AADocument.company_id == company.id, AADocument.account == "capital_goods",
    ))).scalars().all()
    rows = {r.document_id: r for r in (await db.execute(
        select(AAAsset).where(AAAsset.company_id == company.id, AAAsset.document_id.is_not(None)))).scalars().all()}
    vat = company.vat_status == "vat"
    active: list[tuple[AAAsset, AADocument]] = []
    for doc in docs:
        if not is_asset_document(doc):
            continue
        defaults = asset_defaults(doc, vat, company.fiscal_year_end_month)
        if defaults is None:
            continue
        description, cost, in_service = defaults
        row = rows.get(doc.id)
        if row is None:
            row = AAAsset(id=uuid.uuid4(), enterprise_id=company.enterprise_id, company_id=company.id,
                          document_id=doc.id, description=description, cost=cost, in_service=in_service,
                          useful_life_months=DEFAULT_LIFE_MONTHS)
            db.add(row)
            rows[doc.id] = row
        elif row.cost != cost:
            row.cost = cost
        active.append((row, doc))
    await db.flush()
    return active


async def opening_assets(db: AsyncSession, company: AACompany) -> list[AAAsset]:
    """Assets carried in at the books' start (no document)."""
    return list((await db.execute(select(AAAsset).where(
        AAAsset.company_id == company.id, AAAsset.enterprise_id == company.enterprise_id,
        AAAsset.document_id.is_(None), AAAsset.deleted_at.is_(None),
    ).order_by(AAAsset.in_service, AAAsset.description))).scalars().all())


async def active_assets(db: AsyncSession, company: AACompany) -> list[Asset]:
    return ([to_asset(row, doc) for row, doc in await sync_assets(db, company)]
            + [to_asset(row, None) for row in await opening_assets(db, company)])
