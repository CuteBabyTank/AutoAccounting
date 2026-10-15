"""Test config: stub env so app modules import cleanly without secrets/DB."""

import os

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET", "x" * 48)
os.environ.setdefault("HMAC_SECRET", "x" * 48)
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
