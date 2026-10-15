"""Idempotent startup schema setup.

Policy: additive changes live here (``services/accounting/schema.py`` for aa_*
columns); destructive changes belong in alembic/. Everything must be safe to run
repeatedly.
"""

from sqlalchemy import text


async def _ensure_accounting_rls(conn) -> None:
    """Additive aa_* columns, then row-level security (idempotent; tables exist after create_all)."""
    from app.services.accounting.rls import rls_statements
    from app.services.accounting.schema import column_statements
    for statement in column_statements() + rls_statements():
        await conn.execute(text(statement))


async def run_all(engine) -> None:
    """create_all → aa_* columns + RLS, each in its own transaction."""
    from app.database import Base
    from app import models  # noqa: F401  registers every table on Base.metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        await _ensure_accounting_rls(conn)
