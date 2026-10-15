"""
Application configuration via environment variables.
"""

import sys
from pydantic_settings import BaseSettings

_INSECURE_DEFAULTS = {
    "change-me-to-a-random-secret",
}


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://autoaccounting:autoaccounting@localhost:5432/autoaccounting"

    # JWT Auth
    jwt_secret: str = "change-me-to-a-random-secret"
    # Optional previous secret kept valid for verification only during rotation.
    # Set when rotating jwt_secret to avoid logging out all sessions instantly.
    jwt_secret_previous: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 8

    # Google OAuth (SSO)
    google_client_id: str | None = None
    # The first Google sign-in with this email becomes the platform admin, as
    # long as no admin exists yet. Lets a fresh database be claimed without SQL.
    bootstrap_admin_email: str = ""
    # Passwordless email sign-in for local development, standing in for Google
    # SSO. Off unless set explicitly, and also refused outside development.
    enable_dev_login: bool = False

    # File Storage
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 5120
    max_batch_size: int = 1000
    # Source documents. Tax records must be kept >=5 years, so in production
    # this is a dedicated long-retention volume/bucket mounted here. Unset in
    # dev -> falls back to upload_dir.
    accounting_dir: str = ""

    @property
    def accounting_root(self) -> str:
        """Filesystem root for documents (long retention).
        Falls back to upload_dir so dev keeps a single local tree."""
        return self.accounting_dir or self.upload_dir

    # Security: CORS
    # Accepts a single origin or a comma-separated list of origins.
    frontend_url: str = "http://localhost:3000"

    @property
    def allowed_origins(self) -> list[str]:
        """Parse frontend_url into a list of origins, stripping trailing slashes and whitespace."""
        return [o.strip().rstrip("/") for o in self.frontend_url.split(",") if o.strip()]

    # Environment
    environment: str = "development"

    # Logging
    log_level: str = "INFO"

    # Database SSL (set to "require" in production)
    database_ssl_mode: str = "disable"
    # CA bundle used to verify the DB server certificate + hostname when SSL is
    # "require". Empty = encrypt without verifying.
    database_ssl_root_cert: str = ""

    # Connection pooler in front of Postgres: "auto" | "transaction" | "none".
    # "auto" = transaction mode when DATABASE_URL targets port 6543 (the
    # PgBouncer/Supavisor transaction-mode convention), otherwise none.
    database_pooler: str = "auto"

    # Gemini
    gemini_api_key: str = ""
    # Model + thinking level for document extraction (Gemini 3 takes a level,
    # not a thinking budget).
    accounting_gemini_model: str = "gemini-3.8-flash"
    accounting_gemini_thinking_level: str = "low"

    # Gemini API rate limits (requests per minute).
    # Per-user RPM is a hard ceiling. The platform-wide global RPM is *dynamic*:
    # it scales with the number of users active in the last 60s as
    #   target = active_users * gemini_user_rpm_limit
    # then clamped to [floor, ceiling]. Ceiling protects the shared Gemini quota;
    # floor keeps a sane minimum when 0-1 users are active.
    gemini_user_rpm_limit: int = 50
    gemini_global_rpm_floor: int = 30
    gemini_global_rpm_ceiling: int = 5000

    # Gemini prompt context caching (reuses the extraction prompt across calls).
    # Falls back gracefully to inline prompt if model/SDK doesn't support caching
    # or the prompt is below the model's minimum cacheable token count.
    gemini_enable_prompt_cache: bool = True
    gemini_prompt_cache_ttl_seconds: int = 3600

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


def validate_secrets_at_startup() -> None:
    """Refuse to start in production with default/insecure secrets."""
    if settings.environment == "development":
        return
    errors: list[str] = []
    if settings.jwt_secret in _INSECURE_DEFAULTS or len(settings.jwt_secret) < 32:
        errors.append("JWT_SECRET must be set to a random value (>= 32 chars) in production")
    if not settings.gemini_api_key or settings.gemini_api_key == "your-gemini-api-key-here":
        errors.append("GEMINI_API_KEY must be set to a valid API key")
    if not settings.google_client_id:
        errors.append("GOOGLE_CLIENT_ID must be set in production")
    if settings.enable_dev_login:
        errors.append("ENABLE_DEV_LOGIN must not be set outside development")
    if errors:
        for e in errors:
            print(f"SECURITY ERROR: {e}", file=sys.stderr)
        sys.exit(1)
