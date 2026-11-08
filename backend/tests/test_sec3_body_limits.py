"""Production body caps apply before parsing and are specific to method, route and media type."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette import formparsers

from app.body_limit import BodySizeLimitMiddleware
from app.dependencies import get_db
from app.routers import auth

MIB = 1024 * 1024


def middleware(app):
    # Exercise the limits actually installed by production, without starting its lifespan.
    from app.main import app as production
    config = next(m for m in production.user_middleware if m.cls is BodySizeLimitMiddleware)
    return BodySizeLimitMiddleware(app, **config.kwargs)


async def request(app, path, chunks, *, method="POST", content_type="application/json", headers=()):
    sent = []
    parts = iter(chunks)
    consumed = 0

    async def receive():
        nonlocal consumed
        chunk = next(parts, None)
        if chunk is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        consumed += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "",
             "query_string": b"", "server": ("test", 80), "client": ("127.0.0.1", 1000),
             "headers": [(b"content-type", content_type.encode()), *headers]}
    await app(scope, receive, send)
    return SimpleNamespace(status=next(m["status"] for m in sent if m["type"] == "http.response.start"),
                           consumed=consumed)


@pytest.mark.parametrize("headers", [(), ((b"content-length", b"1"),),
                                     ((b"transfer-encoding", b"chunked"),)])
async def test_profile_json_over_one_mib_is_refused_before_json_loads(monkeypatch, headers):
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    limited = middleware(app)
    parsed = []
    real_loads = json.loads

    def loads(data, *args, **kwargs):
        parsed.append(len(data))
        return real_loads(data, *args, **kwargs)

    monkeypatch.setattr(json, "loads", loads)
    result = await request(limited, "/api/auth/me", [b"[" + b" " * MIB + b"]"],
                           method="PATCH", headers=headers)
    assert result.status == 413 and parsed == []


@pytest.mark.parametrize("many_parts", [False, True])
async def test_avatar_aggregate_cap_cleans_up_spooled_files(monkeypatch, many_parts):
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    reached_db = []

    async def no_db():
        reached_db.append(True)
        raise AssertionError("anonymous avatar must not reach the database")

    app.dependency_overrides[get_db] = no_db
    files = []
    factory = formparsers.SpooledTemporaryFile

    def spool(*args, **kwargs):
        file = factory(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", spool)
    header = b'--x\r\nContent-Disposition: form-data; name="file"; filename="dummy.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
    # The first chunk rolls to disk, then either more file bytes or several additional file parts exceed the cap.
    chunks = [header + b"x" * (2 * MIB)]
    if many_parts:
        chunks += [b"\r\n" + header + b"x" * (2 * MIB)] * 2
    else:
        chunks += [b"x" * (2 * MIB)] * 2
    chunks += [b"\r\n--x--\r\n"]
    result = await request(middleware(app), "/api/auth/me/avatar", chunks, method="PUT",
                           content_type="multipart/form-data; boundary=x")
    assert result.status == 413 and not reached_db
    assert files and all(file.closed for file in files)


async def consume(scope, receive, send):
    while True:
        message = await receive()
        if not message.get("more_body", False):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.parametrize("method,path,content_type,size", [
    ("POST", "/api/accounting/uploads", "multipart/form-data; boundary=x", 12 * MIB),
    ("POST", "/api/accounting/companies/id/imports/opening-tb/preview", "multipart/form-data; boundary=x", 5 * MIB),
    ("POST", "/api/accounting/companies/id/employees/2026/import", "multipart/form-data; boundary=x", 10 * MIB),
    ("POST", "/api/accounting/assistant/chat", "application/json", MIB + 1),
    ("POST", "/api/accounting/outputs/id/edits", "application/json", 2 * MIB),
    ("POST", "/api/accounting/outputs/id/2307s", "application/json", 20 * MIB),
    ("POST", "/api/accounting/companies/id/employees/2026/2316.zip", "application/json", 20 * MIB),
])
async def test_explicit_bulk_allowances_accept_larger_bodies_but_still_have_a_cap(method, path, content_type, size):
    allowed = await request(middleware(consume), path, [b"x" * size], method=method, content_type=content_type)
    assert allowed.status == 200
    unrelated = await request(middleware(consume), "/api/auth/me", [b"x" * size],
                              method="PATCH", content_type=content_type)
    assert unrelated.status == 413  # this exception must not leak to other routes
    # An allowance is finite, including upload routes.
    denied = await request(middleware(consume), path, [b"x" * MIB] * 300, method=method, content_type=content_type)
    assert denied.status == 413


@pytest.mark.parametrize("method,path,content_type", [
    ("PATCH", "/api/auth/me", "multipart/form-data; boundary=x"),
    ("PUT", "/api/auth/me/avatar", "application/json"),
    ("PUT", "/api/accounting/uploads", "multipart/form-data; boundary=x"),
    ("POST", "/api/accounting/uploads/other", "multipart/form-data; boundary=x"),
    ("POST", "/api/accounting/uploads", "application/json"),
    ("POST", "/api/accounting/companies/id/imports/opening-tb/undo", "multipart/form-data; boundary=x"),
])
async def test_content_type_alone_or_a_similar_route_never_gets_the_batch_cap(method, path, content_type):
    result = await request(middleware(consume), path, [b"x" * (MIB + 1)],
                           method=method, content_type=content_type)
    assert result.status == 413
