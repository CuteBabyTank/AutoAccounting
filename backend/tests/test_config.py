"""Production secret validation must reject insecure defaults."""

import importlib
import os
import sys

import pytest


def _reload_config(env: dict[str, str]):
    """Reload config module under a fresh env. Returns the module."""
    saved = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        os.environ[k] = v
    try:
        if "app.config" in sys.modules:
            del sys.modules["app.config"]
        return importlib.import_module("app.config")
    finally:
        for k, original in saved.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original
        if "app.config" in sys.modules:
            del sys.modules["app.config"]


def test_dev_skips_validation():
    cfg = _reload_config({"ENVIRONMENT": "development"})
    cfg.validate_secrets_at_startup()  # must not raise / exit


def test_prod_short_jwt_secret_exits():
    cfg = _reload_config({
        "ENVIRONMENT": "production",
        "JWT_SECRET": "short",
        "GEMINI_API_KEY": "real-key",
        "GOOGLE_CLIENT_ID": "client-id",
    })
    with pytest.raises(SystemExit):
        cfg.validate_secrets_at_startup()


def test_prod_default_jwt_secret_exits():
    cfg = _reload_config({
        "ENVIRONMENT": "production",
        "JWT_SECRET": "change-me-to-a-random-secret",
        "GEMINI_API_KEY": "real-key",
        "GOOGLE_CLIENT_ID": "client-id",
    })
    with pytest.raises(SystemExit):
        cfg.validate_secrets_at_startup()


def test_prod_missing_gemini_key_exits():
    cfg = _reload_config({
        "ENVIRONMENT": "production",
        "JWT_SECRET": "x" * 48,
        "GEMINI_API_KEY": "",
        "GOOGLE_CLIENT_ID": "client-id",
    })
    with pytest.raises(SystemExit):
        cfg.validate_secrets_at_startup()


def test_prod_missing_google_client_id_exits():
    cfg = _reload_config({
        "ENVIRONMENT": "production",
        "JWT_SECRET": "x" * 48,
        "GEMINI_API_KEY": "real-key",
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "client-secret",
    })
    with pytest.raises(SystemExit):
        cfg.validate_secrets_at_startup()


def test_prod_with_all_secrets_passes():
    cfg = _reload_config({
        "ENVIRONMENT": "production",
        "JWT_SECRET": "x" * 48,
        "GEMINI_API_KEY": "real-key",
        "GOOGLE_CLIENT_ID": "client-id",
        "GOOGLE_CLIENT_SECRET": "client-secret",
    })
    cfg.validate_secrets_at_startup()  # must not raise


def test_allowed_origins_parses_csv():
    cfg = _reload_config({
        "ENVIRONMENT": "development",
        "FRONTEND_URL": "http://localhost:3000, https://autoaccounting.example/, https://dev.autoaccounting.example",
    })
    origins = cfg.settings.allowed_origins
    assert origins == [
        "http://localhost:3000",
        "https://autoaccounting.example",
        "https://dev.autoaccounting.example",
    ]
