"""Chart-of-accounts templates: built-in by industry plus the firm's own, saved from a company's chart."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AAAccount, AACoaTemplate, AACompany
from app.models.user import User
from app.routers.accounting_scope import MANAGER_ROLES, company_or_404, scope_for
from app.services.accounting import audit
from app.services.accounting.books.chart import Chart
from app.services.accounting.books.loader import _chart_account, ensure_chart
from app.services.accounting.books.templates import (
    BUILTIN_TEMPLATES, placement, template_accounts, template_rows,
)

router = APIRouter()


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A template needs a name")
        return value.strip()


class TemplateUpdateIn(TemplateIn):
    source_company_id: uuid.UUID | None = None


def _require_manager(user: User) -> None:
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners and managers can manage chart templates")


def _summary(key: str, name: str, description: str, builtin: bool, count: int) -> dict:
    return {"id": key, "name": name, "description": description, "builtin": builtin, "accounts_count": count}


async def _firm_template(db: AsyncSession, ent: uuid.UUID, template_id: str) -> AACoaTemplate:
    try:
        tid = uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found") from None
    row = (await db.execute(select(AACoaTemplate).where(AACoaTemplate.id == tid, AACoaTemplate.enterprise_id == ent))
           ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return row


async def resolve_template(db: AsyncSession, ent: uuid.UUID, template: str, taxpayer_type: str):
    """The accounts for a built-in key or a firm template id (raises HTTP 400 / 404)."""
    try:
        if template in BUILTIN_TEMPLATES:
            return template_accounts(template, taxpayer_type)
        return template_accounts((await _firm_template(db, ent, template)).accounts, taxpayer_type)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"The template can't be used: {exc}") from None


async def apply_template(db: AsyncSession, company: AACompany, template: str) -> int:
    """Seed a new company's chart from a template (before any account exists); returns the accounts added."""
    try:
        accounts = await resolve_template(db, company.enterprise_id, template, company.taxpayer_type)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown chart of accounts template") from None
    now = datetime.now(timezone.utc)
    await db.execute(pg_insert(AAAccount).values([
        dict(id=uuid.uuid4(), enterprise_id=company.enterprise_id, company_id=company.id, code=a.code, name=a.name,
             type=a.type, contra=a.contra, parent_code=a.parent_code, system_key=a.system_key, active=a.active,
             locked=False, created_at=now, updated_at=now) for a in accounts
    ]).on_conflict_do_nothing())
    return len(accounts)


@router.get("/coa-templates")
async def list_templates(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    out = [_summary(k, label, desc, True, len(template_accounts(k, "corporation")))
           for k, (label, desc, _) in BUILTIN_TEMPLATES.items()]
    rows = (await db.execute(select(AACoaTemplate).where(AACoaTemplate.enterprise_id == ent)
                             .order_by(AACoaTemplate.name))).scalars().all()
    out += [_summary(str(r.id), r.name, r.description, False, len(r.accounts or [])) for r in rows]
    return out


@router.get("/coa-templates/{template_id}")
async def get_template(template_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    accounts = await resolve_template(db, scope_for(user), template_id, "corporation")
    chart = Chart(accounts)
    return [{"code": a.code, "name": a.name, "type": a.type, "parent_code": a.parent_code, "active": a.active,
             "system_key": a.system_key, "placement": placement(chart, a.code)} for a in chart.accounts]


@router.post("/companies/{company_id}/coa-template", status_code=status.HTTP_201_CREATED)
async def save_template(company_id: uuid.UUID, body: TemplateIn, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Save this company's chart as a firm template."""
    _require_manager(user)
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    await ensure_chart(db, company)
    rows = (await db.execute(select(AAAccount).where(AAAccount.company_id == company.id))).scalars().all()
    accounts = template_rows([_chart_account(r) for r in rows])
    row = AACoaTemplate(id=uuid.uuid4(), enterprise_id=ent, name=body.name.strip(),
                        description=body.description.strip(), accounts=accounts, created_by=user.id)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"The firm already has a template named {body.name.strip()!r}")
    audit.record(db, ent=ent, company_id=company.id, user=user, entity="coa_template", entity_id=row.id,
                 action="create", after={"name": row.name, "description": row.description,
                                         "from_company": company.registered_name, "accounts": len(accounts)},
                 label=row.name)
    await db.commit()
    return _summary(str(row.id), row.name, row.description, False, len(accounts))


@router.put("/coa-templates/{template_id}")
async def update_template(template_id: str, body: TemplateUpdateIn, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    _require_manager(user)
    ent = scope_for(user)
    if template_id in BUILTIN_TEMPLATES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Built-in templates can't be edited; save a firm copy instead")
    row = await _firm_template(db, ent, template_id)
    before = audit.snapshot(row, ("name", "description", "accounts"))
    row.name, row.description = body.name, body.description.strip()
    if body.source_company_id is not None:
        company = await company_or_404(db, ent, body.source_company_id)
        await ensure_chart(db, company)
        accounts = (await db.execute(select(AAAccount).where(
            AAAccount.enterprise_id == ent, AAAccount.company_id == company.id))).scalars().all()
        row.accounts = template_rows([_chart_account(a) for a in accounts])
    row.updated_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "The firm already has a template with this name") from None
    audit.record(db, ent=ent, company_id=None, user=user, entity="coa_template", entity_id=row.id,
                 action="update", before=before, after=audit.snapshot(row, ("name", "description", "accounts")),
                 label=row.name)
    await db.commit()
    return _summary(str(row.id), row.name, row.description, False, len(row.accounts or []))


@router.delete("/coa-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_manager(user)
    ent = scope_for(user)
    if template_id in BUILTIN_TEMPLATES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Built-in templates can't be deleted")
    row = await _firm_template(db, ent, template_id)
    audit.record(db, ent=ent, company_id=None, user=user, entity="coa_template", entity_id=row.id, action="delete",
                 before={"name": row.name, "description": row.description, "accounts": len(row.accounts or [])},
                 after=None, label=row.name)
    await db.delete(row)
    await db.commit()
