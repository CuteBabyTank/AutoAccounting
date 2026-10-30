"""
FastAPI application entry point.
"""

import logging
import time
import uuid as _uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app import startup_migrations
from app.body_limit import BodySizeLimitMiddleware
from app.config import settings, validate_secrets_at_startup
from app.database import DB_POOLER, engine
from app.edge import client_ip, origin_allowed
from app.logging_config import setup_logging
from app.routers import accounting, admin, auth, features, team
from app.services.accounting import pipeline
from app.services.features import feature_gate
from app.auth.security import global_ip_limiter, should_limit_ip

logger = logging.getLogger("app")


# ---------------------------------------------------------------------------
# Startup validation & logging
# ---------------------------------------------------------------------------
validate_secrets_at_startup()
setup_logging()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_migrations.run_all(engine)
    try:
        yield
    finally:
        await pipeline.release_running()
        await engine.dispose()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AutoAccounting API",
    description="BIR document intake, returns and books of accounts for accounting firms",
    version="1.0.0",
    lifespan=lifespan,
    # Hide docs in production
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url="/redoc" if settings.environment == "development" else None,
)

# ---------------------------------------------------------------------------
# Custom Middlewares
# ---------------------------------------------------------------------------

@app.middleware("http")
async def https_redirect_middleware(request: Request, call_next) -> Response:
    """Redirect HTTP to HTTPS in production (behind reverse proxy)."""
    if settings.environment != "development":
        proto = request.headers.get("x-forwarded-proto", "https")
        if proto == "http":
            url = request.url.replace(scheme="https")
            return RedirectResponse(url=str(url), status_code=301)
    return await call_next(request)


# Content-Security-Policy for API responses. API never serves HTML so default-src 'none'
# is safe; allow self for any error pages FastAPI may render.
_CSP_POLICY = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


_JSON_BODY_MAX_BYTES = 25 * 1024 * 1024  # 25 MB
# Bound the whole batch as well as each file; reserve space for multipart headers/fields.
_MULTIPART_BODY_MAX_BYTES = min(
    settings.max_file_size_mb * settings.max_batch_size * 1024 * 1024, 256 * 1024 * 1024,
) + settings.max_batch_size * 64 * 1024 + 1024 * 1024


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = _CSP_POLICY
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    if settings.environment != "development":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    return response


def _extract_client_ip(request: Request) -> str:
    """The caller's IP: the Cloudflare Worker's X-AA-Client-IP when the origin secret proves it, else the last
    X-Forwarded-For entry (the one Cloud Run appends; earlier entries are client-supplied)."""
    return client_ip(request.headers, request.client.host if request.client else None, settings.origin_secret)


# User-Agent strings that indicate automated tooling / bots
_BLOCKED_UA_SUBSTRINGS = (
    "python-requests",
    "python-httpx",
    "curl/",
    "wget/",
    "scrapy",
    "httpclient",
    "go-http-client",
    "java/",
    "libwww-perl",
    "mechanize",
)


@app.middleware("http")
async def abuse_protection_middleware(request: Request, call_next) -> Response:
    # Skip health check and OPTIONS (CORS preflight)
    if request.url.path == "/api/health" or request.method == "OPTIONS":
        return await call_next(request)

    ip = _extract_client_ip(request)
    request_id = str(_uuid.uuid4())[:8]

    # --- Origin lock: with ORIGIN_LOCK on, only traffic through Cloudflare reaches the API ---
    if settings.origin_lock and not origin_allowed(request.url.path, request.headers, settings.origin_secret):
        logger.warning("blocked reason=bypassed_edge ip=%s path=%s rid=%s", ip, request.url.path, request_id)
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})

    # --- Bot detection: block requests with no User-Agent ---
    ua = request.headers.get("user-agent", "")
    if not ua:
        logger.warning("blocked reason=no_user_agent ip=%s path=%s rid=%s", ip, request.url.path, request_id)
        return JSONResponse(
            status_code=403,
            content={"detail": "Forbidden"},
        )

    # --- Bot detection: block known automated tooling in production ---
    if settings.environment != "development":
        ua_lower = ua.lower()
        if any(sub in ua_lower for sub in _BLOCKED_UA_SUBSTRINGS):
            logger.warning("blocked reason=bot_ua ip=%s ua=%s path=%s rid=%s", ip, ua[:80], request.url.path, request_id)
            return JSONResponse(
                status_code=403,
                content={"detail": "Automated access is not permitted"},
            )

    # --- Global per-IP rate limit (unauthenticated traffic only) ---
    # Authenticated requests are already gated per-user inside get_current_user
    # via global_user_limiter. Counting them per-IP penalises distinct accounts
    # that share an egress IP (corporate NAT, mobile carriers, ISP CGNAT), and a
    # stress test with many real accounts behind one IP would otherwise trip
    # 429s that aren't actually abuse. The IP cap still applies to anonymous
    # endpoints (login, OAuth callback, public assets) where it does block
    # credential-stuffing / scraping.
    if should_limit_ip(request.url.path, request.headers.get("authorization", "")):
        if not global_ip_limiter.check_and_record(ip):
            logger.warning("rate_limited scope=global_ip ip=%s path=%s rid=%s", ip, request.url.path, request_id)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": "60"},
            )

    # --- Request logging ---
    start = time.monotonic()
    response: Response = await call_next(request)
    elapsed_ms = round((time.monotonic() - start) * 1000)

    logger.info(
        "request method=%s path=%s status=%d ms=%d ip=%s rid=%s",
        request.method, request.url.path, response.status_code, elapsed_ms, ip, request_id,
    )

    return response


# ---------------------------------------------------------------------------
# Count bytes outside the HTTP middleware stack, including multipart parser reads.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=_JSON_BODY_MAX_BYTES,
                   multipart_max_bytes=_MULTIPART_BODY_MAX_BYTES)

# CORS: must be added LAST to be the outermost middleware (processed first for requests)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Accept", "Origin", "Idempotency-Key"],
    expose_headers=["Content-Disposition", "Content-Length"],
    max_age=600,
)
logger.info("cors_allowed_origins=%s", settings.allowed_origins)
logger.info(
    "db_config pooler=%s ssl=%s verify=%s",
    DB_POOLER, settings.database_ssl_mode, bool(settings.database_ssl_root_cert),
)


# ---------------------------------------------------------------------------
# Exception handlers: generic detail for 5xx, full trace in the logs
# ---------------------------------------------------------------------------

GENERIC_SERVER_ERROR = "An unexpected error occurred. Please try again later."


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> Response:
    if exc.status_code >= 500:
        logger.warning("http_error status=%d path=%s detail=%s", exc.status_code, request.url.path, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
    logger.info("validation_error path=%s errors=%r", request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid request. Please check your input and try again."},
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    logger.exception("unhandled_exception path=%s method=%s", request.url.path, request.method)
    return JSONResponse(status_code=500, content={"detail": GENERIC_SERVER_ERROR})


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
# Maintenance switches (services/features.py): a feature the platform admin turned off answers 503.
app.include_router(team.router, prefix="/api/team", tags=["team"], dependencies=[Depends(feature_gate)])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(features.router, prefix="/api/features", tags=["features"])
app.include_router(accounting.router, prefix="/api/accounting", tags=["accounting"],
                   dependencies=[Depends(feature_gate)])


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
