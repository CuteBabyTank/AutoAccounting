"""
Async SQLAlchemy engine and session factory.
"""

import ssl
import uuid

from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def pooler_mode(database_url: str, configured: str) -> str:
    """Resolve the DATABASE_POOLER setting to "transaction" or "none".

    "auto" picks transaction mode when the URL targets port 6543, the port
    PgBouncer and Supabase's Supavisor use for transaction pooling. Any other
    value is taken as-is so the detection can be overridden.
    """
    if configured != "auto":
        return configured
    return "transaction" if make_url(database_url).port == 6543 else "none"


DB_POOLER = pooler_mode(settings.database_url, settings.database_pooler)


def ssl_context(mode: str, root_cert: str) -> ssl.SSLContext | None:
    """Build the asyncpg SSL context for DATABASE_SSL_MODE / DATABASE_SSL_ROOT_CERT.

    With a root cert the server certificate and hostname are verified (needed
    once traffic crosses the public internet, e.g. to Supabase). Without one,
    "require" only encrypts, which is fine over the Cloud SQL unix socket.
    """
    if mode != "require":
        return None
    if root_cert:
        return ssl.create_default_context(cafile=root_cert)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---------------------------------------------------------------------------
# Connect args (SSL + pooler compatibility). Shared with alembic/env.py so
# migrations connect exactly the way the app does.
# ---------------------------------------------------------------------------
DB_URL: URL = make_url(settings.database_url)
DB_CONNECT_ARGS: dict = {}
_ssl_ctx = ssl_context(settings.database_ssl_mode, settings.database_ssl_root_cert)
if _ssl_ctx is not None:
    DB_CONNECT_ARGS["ssl"] = _ssl_ctx

if DB_POOLER == "transaction":
    # Transaction pooling hands each transaction to whichever server
    # connection is free, so a prepared statement cached on one connection is
    # missing (or clashes) on the next. Disable asyncpg's statement cache and
    # SQLAlchemy's, and give every statement a unique name.
    DB_CONNECT_ARGS["statement_cache_size"] = 0
    DB_CONNECT_ARGS["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid.uuid4()}__"
    DB_URL = DB_URL.update_query_dict({"prepared_statement_cache_size": "0"})

# ---------------------------------------------------------------------------
# Engine with connection pooling
# ---------------------------------------------------------------------------
# Pool sizing: per-instance footprint = pool_size + max_overflow.
# Worst case across the fleet = max_instances × (pool_size + max_overflow);
# keep this comfortably under Cloud SQL max_connections to avoid
# TooManyConnectionsError under scale-out.
#
# Budget rationale (Cloud Run backend max-instances=5, Cloud SQL db-g1-small
# max_connections=100):
#   * Background process_batch holds 1 connection per running batch for the
#     full Gemini extraction (many minutes). Capped at _PROCESS_SEM=3 per
#     instance → up to 3 connections continuously occupied by background work.
#   * HTTP traffic (review page firing many concurrent /files/{id}/page/{n}
#     plus /status polls) must share whatever's left.
# pool_size=5 (the previous setting) left only 2 slots for HTTP and timed out.
# pool_size=15 gives ~12 free for HTTP after background work; max_overflow=0
# hard-caps per-instance at 15 so the fleet worst case (5 × 15 = 75) stays
# under Cloud SQL's 100 ceiling with headroom for superuser/maintenance.
#
# Exported as constants so connection-budgeting code elsewhere (e.g. the
# image-endpoint concurrency cap in routers/files.py) can size itself relative
# to the pool and stay in sync if these change.
#
# Supabase (Supavisor transaction mode, port 6543): the 75-connection fleet
# worst case counts against the pooler's max client connections (~200 on the
# free tier), not Postgres max_connections. Server-side work is multiplexed
# over the pooler's pool (~15), so a connection only holds a server slot while
# it is inside a transaction. Long-running transactions (process_batch)
# still pin one each.
DB_POOL_SIZE = 15
DB_MAX_OVERFLOW = 0
engine = create_async_engine(
    DB_URL,
    echo=False,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    connect_args=DB_CONNECT_ARGS,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass
