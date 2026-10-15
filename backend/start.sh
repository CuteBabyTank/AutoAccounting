#!/bin/bash
set -e

# Fail early if DATABASE_URL is not set
if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL is not set. Deployment will fail."
    exit 1
fi

# Accept plain postgres:// URLs from hosting providers
export DATABASE_URL="${DATABASE_URL/postgres:\/\//postgresql+asyncpg://}"

# Enable database SSL in production by default
if [ -z "$DATABASE_SSL_MODE" ] && [ "$ENVIRONMENT" = "production" ]; then
    export DATABASE_SSL_MODE="require"
fi

# Schema: the app's lifespan runs create_all + aa_* columns + RLS on boot
# (app/startup_migrations.py); alembic only holds destructive changes.
export PYTHONPATH=$PYTHONPATH:.
alembic upgrade head

echo "Starting FastAPI server on port ${PORT:-8000}..."
exec hypercorn app.main:app --bind 0.0.0.0:${PORT:-8000} --keep-alive 600
