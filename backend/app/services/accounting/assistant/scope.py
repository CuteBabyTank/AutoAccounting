"""Assistant-only application-level firm predicates, including nested shared loaders.

Some legacy loaders query by company/period id alone. This session-local ORM hook adds
enterprise_id criteria to every aa_* entity they read, including aggregates and joins.
It survives loader commits (unlike SET LOCAL), does not depend on RLS, and is removed
in finally. Explicit filters in tools and routes remain in place as the first guard.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import Select, event, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import with_loader_criteria

from app.database import Base
from app.models.accounting import (
    AABankLine, AACompany, AAContact, AADocument, AAJournalEntry, AATask,
)
from app.models.user import User

if TYPE_CHECKING:
    from app.services.accounting.assistant.tools import Ctx


def scoped_statement(statement: Select, ent: uuid.UUID) -> Select:
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if not model.__tablename__.startswith("aa_"):
            continue
        if hasattr(model, "enterprise_id"):
            criterion = model.enterprise_id == ent
        elif hasattr(model, "company_id"):
            # Supplier rules and ATC defaults inherit firm ownership through the company.
            criterion = model.company_id.in_(select(AACompany.id).where(AACompany.enterprise_id == ent))
        else:
            continue
        statement = statement.options(with_loader_criteria(model, criterion, include_aliases=True))
    # Work board assignees are also private to the firm (owner + staff).
    return statement.options(with_loader_criteria(
        User, or_(User.id == ent, User.enterprise_id == ent), include_aliases=True))


@contextmanager
def firm_reads(db: AsyncSession, ent: uuid.UUID) -> Iterator[None]:
    def restrict(state):
        if state.is_select:
            state.statement = scoped_statement(state.statement, ent)
    event.listen(db.sync_session, "do_orm_execute", restrict)
    try:
        yield
    finally:
        event.remove(db.sync_session, "do_orm_execute", restrict)


async def filter_sources(ctx: "Ctx", sources: list[dict]) -> list[dict]:
    """Fail closed on unknown source kinds or foreign entity/company ids."""
    models = {"document": AADocument, "company": AACompany, "contact": AAContact,
              "bank_line": AABankLine, "journal_entry": AAJournalEntry, "task": AATask}
    allowed = set()
    for kind, model in models.items():
        ids = []
        for source in sources:
            if source.get("type") == kind:
                try:
                    ids.append(uuid.UUID(str(source.get("id"))))
                except (ValueError, TypeError):
                    continue
        if ids:
            query = select(model.id).where(model.enterprise_id == ctx.ent, model.id.in_(ids))
            for value in (await ctx.db.execute(query)).scalars():
                allowed.add((kind, str(value)))
    # Check the displayed company id independently, even if an adapter supplied a bad source link.
    company_ids = {str(value) for value in (await ctx.db.execute(
        select(AACompany.id).where(AACompany.enterprise_id == ctx.ent))).scalars()} if sources else set()
    return [s for s in sources if (s.get("type"), str(s.get("id"))) in allowed and
            (not s.get("company_id") or str(s["company_id"]) in company_ids)]
