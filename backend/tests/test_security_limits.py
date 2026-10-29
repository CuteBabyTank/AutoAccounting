"""Resource limits reject hostile input without a DB or external services."""

import asyncio
import math
import uuid

import pytest

from app import config
from app.auth.jwt import create_access_token, create_sse_token
from app.auth.security import should_limit_ip
from app.body_limit import BodySizeLimitMiddleware
from app.services.pdf_render import render_zoom


@pytest.mark.parametrize("width,height,dpi", [
    (100000, 100000, 130), (1000000, 1, 300), (1, 1000000, 36),
    (612, 792, 10000), (20000.25, 8000.75, 130),
])
def test_render_zoom_caps_pixels_and_sides_before_allocation(width, height, dpi):
    zoom = render_zoom(width, height, dpi)
    # Allow two pixels for MuPDF rounding transformed rectangle origins/edges.
    w, h = math.ceil(width * zoom) + 2, math.ceil(height * zoom) + 2
    assert w * h <= 40000000
    assert max(w, h) <= 10000
    assert 0 < zoom <= dpi / 72


def test_render_zoom_preserves_normal_page_resolution():
    assert render_zoom(612, 792, 130) == 130 / 72


@pytest.mark.parametrize("width,height,dpi", [(0, 10, 72), (10, -1, 72), (math.inf, 10, 72),
                                                (10, math.nan, 72), (10, 10, 0)])
def test_render_zoom_rejects_invalid_dimensions(width, height, dpi):
    with pytest.raises(ValueError):
        render_zoom(width, height, dpi)


def _body_response(headers, chunks, *, swallow=False):
    received, sent = [], []
    messages = iter({"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
                    for i, chunk in enumerate(chunks))

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    async def endpoint(scope, receive, send):
        try:
            while True:
                message = await receive()
                received.append(message["body"])
                if not message.get("more_body", False):
                    break
        except Exception:
            if not swallow:
                raise
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BodySizeLimitMiddleware(endpoint, max_bytes=5, multipart_max_bytes=10)
    asyncio.run(middleware({"type": "http", "headers": headers}, receive, send))
    return received, sent


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")],
                                     [(b"transfer-encoding", b"chunked")]])
def test_body_limit_counts_received_bytes_without_trusting_headers(headers):
    received, sent = _body_response(headers, [b"123", b"456"])
    assert received == [b"123"]  # the over-limit chunk never reaches the parser
    assert [m["status"] for m in sent if m["type"] == "http.response.start"] == [413]


def test_body_limit_allows_exact_limit_and_counts_empty_chunks():
    received, sent = _body_response([], [b"12", b"", b"345"])
    assert b"".join(received) == b"12345"
    assert sent[0]["status"] == 200


def test_multipart_is_counted_with_its_own_limit():
    headers = [(b"content-type", b"multipart/form-data; boundary=test")]
    assert _body_response(headers, [b"12345", b"67890"])[1][0]["status"] == 200
    assert _body_response(headers, [b"12345", b"678901"])[1][0]["status"] == 413


def test_body_limit_still_returns_413_if_a_parser_catches_the_error():
    _, sent = _body_response([], [b"123456"], swallow=True)
    assert [m["status"] for m in sent if m["type"] == "http.response.start"] == [413]


@pytest.mark.parametrize("previous", ["short", "change-me-to-a-random-secret"])
def test_production_rejects_insecure_previous_secret(monkeypatch, previous):
    monkeypatch.setattr(config, "settings", config.Settings(
        _env_file=None, environment="production", jwt_secret="x" * 48,
        jwt_secret_previous=previous, gemini_api_key="test", google_client_id="test", enable_dev_login=False))
    with pytest.raises(SystemExit) as exc:
        config.validate_secrets_at_startup()
    assert exc.value.code == 1


@pytest.mark.parametrize("previous", ["", "y" * 32])
def test_production_allows_unset_or_strong_previous_secret(monkeypatch, previous):
    monkeypatch.setattr(config, "settings", config.Settings(
        _env_file=None, environment="production", jwt_secret="x" * 48,
        jwt_secret_previous=previous, gemini_api_key="test", google_client_id="test", enable_dev_login=False))
    config.validate_secrets_at_startup()


@pytest.mark.parametrize("path", ["/api/auth/google", "/api/auth/dev-login", "/api/auth/me", "/docs", "/public"])
def test_public_and_auth_paths_are_ip_limited_even_with_a_valid_token(path):
    assert should_limit_ip(path, "Bearer " + create_access_token(str(uuid.uuid4())))


@pytest.mark.parametrize("header", ["", "Bearer garbage", "Basic anything"])
def test_unverified_headers_never_skip_ip_limiting(header):
    assert should_limit_ip("/api/accounting/companies", header)


def test_only_verified_access_tokens_on_protected_routes_skip_ip_limiting():
    token = create_access_token(str(uuid.uuid4()))
    assert not should_limit_ip("/api/accounting/companies", "Bearer " + token)
    assert should_limit_ip("/api/accounting/companies", "Bearer " + create_sse_token(str(uuid.uuid4())))
    assert should_limit_ip("/api/accounting-public", "Bearer " + token)
