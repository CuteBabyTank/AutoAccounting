"""Live Extract isolation smoke check over HTTP; creates fixtures and removes them in finally.

Run inside backend (server must be up): python -m scripts.extract_isolation_check [base_url]
Uses the configured real DB and the running API, no model calls: formats, a run, a file and a record are inserted
directly. Throwaway users: an admin, two firm owners (A, B) and an employee of A, with tokens minted locally. Tests
application filtering, role guards and feature switches even with a superuser DB role (RLS is not exercised).
"""

import asyncio
import sys
import uuid
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, func, select

from app.auth.jwt import create_access_token
from app.config import settings
from app.database import async_session
from app.dependencies import bind_session_user
from app.models.accounting import AAExtractFile, AAExtractFormat, AAExtractRecord, AAExtractRun
from app.models.user import User, UserRole

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "backend"}  # backend = the compose service name
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
FIELDS = [{"key": "invoice_no", "label": "Invoice no", "type": "text", "scope": "header", "required": True,
           "description": ""}]
SECRET = "IsolationSecretFormat"


async def make_user(role: UserRole, email: str, enterprise_id: uuid.UUID | None = None, org: str | None = None):
    async with async_session() as db:
        user = User(id=uuid.uuid4(), email=email, role=role, enterprise_id=enterprise_id, organization_name=org)
        db.add(user)
        await db.commit()
        return user.id, {"Authorization": f"Bearer {create_access_token(str(user.id))}", **UA}


async def seed_firm(owner: uuid.UUID, name: str) -> dict:
    async with async_session() as db:
        await bind_session_user(db, str(owner))
        fmt = AAExtractFormat(enterprise_id=owner, name=name, fields=FIELDS, checks=[], created_by=owner,
                              updated_by=owner)
        run = AAExtractRun(enterprise_id=owner, format_key="auto", format_name="Auto detect", snapshots={})
        db.add_all([fmt, run])
        await db.flush()
        file = AAExtractFile(enterprise_id=owner, run_id=run.id, original_name="x.pdf",
                             stored_path=f"/tmp/extract-isolation-unused/{run.id}/x.pdf", file_type="pdf",
                             page_count=1, status="choose")
        db.add(file)
        await db.flush()
        rec = AAExtractRecord(enterprise_id=owner, run_id=run.id, file_id=file.id, values={"header": {}, "rows": []})
        db.add(rec)
        await db.flush()
        out = {"format": str(fmt.id), "run": str(run.id), "file": str(file.id), "record": str(rec.id)}
        await db.commit()
        return out


def refuse_unless_safe(base: str) -> None:
    """Creates and deletes users and mints tokens from the configured secret: development databases only."""
    if settings.environment != "development":
        sys.exit(f"Refusing to run: ENVIRONMENT is {settings.environment!r}, this check is for development only.")
    host = urlparse(base).hostname
    if host not in ALLOWED_HOSTS:
        sys.exit(f"Refusing to run: base URL host {host!r} is not one of {sorted(ALLOWED_HOSTS)}.")


async def main(base: str):
    refuse_unless_safe(base)
    marker = uuid.uuid4().hex[:10]
    made: list[uuid.UUID] = []
    passed = 0

    def check(label: str, got, want):
        nonlocal passed
        assert got == want, f"FAIL {label}: got {got}, want {want}"
        passed += 1
        print(f"PASS {label} -> {got}", flush=True)

    try:
        admin, h_admin = await make_user(UserRole.ADMIN, f"extract-iso-admin-{marker}@example.invalid")
        made.append(admin)
        a, h_a = await make_user(UserRole.ENTERPRISE, f"extract-iso-a-{marker}@example.invalid", org=f"Iso A {marker}")
        made.append(a)
        b, h_b = await make_user(UserRole.ENTERPRISE, f"extract-iso-b-{marker}@example.invalid", org=f"Iso B {marker}")
        made.append(b)
        emp, h_emp = await make_user(UserRole.EMPLOYEE, f"extract-iso-e-{marker}@example.invalid", enterprise_id=a)
        made.append(emp)
        fa = await seed_firm(a, f"{SECRET} A {marker}")
        fb = await seed_firm(b, f"{SECRET} B {marker}")
        base_x = f"{base}/api/accounting/extract"

        async with httpx.AsyncClient(timeout=30) as c:
            async def call(method, url, headers, **kw):
                return (await c.request(method, url, headers=headers, **kw)).status_code

            # Positive controls: each firm sees its own rows, so empty results mean isolation, not breakage.
            r = await c.get(f"{base_x}/formats", headers=h_a)
            check("A lists own format", fa["format"] in [f["key"] for f in r.json()], True)
            r = await c.get(f"{base_x}/formats", headers=h_b)
            check("B never lists A's format", [f["name"] for f in r.json() if SECRET in f["name"] and f["key"] != fb["format"]], [])
            check("A reads own records page", await call("GET", f"{base_x}/runs/{fa['run']}/records", h_a), 200)
            r = await c.get(f"{base_x}/runs", headers=h_a)
            check("A lists own run", fa["run"] in [x["id"] for x in r.json()["runs"]], True)
            r = await c.get(f"{base_x}/runs", headers=h_b, params={"limit": 50})
            check("B never lists A's run", fa["run"] in [x["id"] for x in r.json()["runs"]], False)

            # Firm B against firm A's ids: all 404.
            ghost = [
                ("GET", f"/runs/{fa['run']}", None), ("GET", f"/runs/{fa['run']}/records", None),
                ("GET", f"/runs/{fa['run']}/xlsx", None), ("DELETE", f"/runs/{fa['run']}", None),
                ("PATCH", f"/records/{fa['record']}", {"edits": [{"key": "invoice_no", "value": "x"}]}),
                ("GET", f"/files/{fa['file']}/pages/1", None),
                ("PUT", f"/files/{fa['file']}/format", {"format_key": "auto"}),
                ("PUT", f"/formats/{fa['format']}", {"name": "Hijack", "picks": []}),
                ("DELETE", f"/formats/{fa['format']}", None),
            ]
            for method, path, body in ghost:
                code = await call(method, base_x + path, h_b, **({"json": body} if body is not None else {}))
                check(f"B {method} {path} of A", code, 404)

            # Same calls on a random id answer the same (no existence leak).
            check("B random run id", await call("GET", f"{base_x}/runs/{uuid.uuid4()}", h_b), 404)

            # Employee of A: use is fine, writes are refused.
            check("employee lists formats", await call("GET", f"{base_x}/formats", h_emp), 200)
            body = {"name": "n", "picks": []}
            check("employee POST /formats", await call("POST", f"{base_x}/formats", h_emp, json=body), 403)
            check("employee PUT /formats", await call("PUT", f"{base_x}/formats/{fa['format']}", h_emp, json=body), 403)
            check("employee DELETE /formats", await call("DELETE", f"{base_x}/formats/{fa['format']}", h_emp), 403)
            check("employee POST /drafts", await call(
                "POST", f"{base_x}/drafts", h_emp, files={"file": ("s.pdf", b"%PDF-1.4", "application/pdf")}), 403)

            # Platform admin overview: both firms; non-admin refused; firm filter narrows.
            r = await c.get(f"{base}/api/admin/extract-formats", headers=h_admin)
            ids = {f["id"] for f in r.json()} if r.status_code == 200 else set()
            check("admin overview status", r.status_code, 200)
            check("admin sees both firms' formats", {fa["format"], fb["format"]} <= ids, True)
            r = await c.get(f"{base}/api/admin/extract-formats", headers=h_admin, params={"firm_id": str(a)})
            check("admin firm filter", {f["id"] for f in r.json()} & {fa["format"], fb["format"]}, {fa["format"]})
            check("owner A GET admin overview", await call("GET", f"{base}/api/admin/extract-formats", h_a), 403)
            check("employee GET admin overview", await call("GET", f"{base}/api/admin/extract-formats", h_emp), 403)
            check("admin cannot delete A's format", await call(
                "DELETE", f"{base_x}/formats/{fa['format']}", h_admin), 404)

            # Feature switch off for firm A: 503 for staff, owner too, features list says off; B unaffected.
            sw = f"{base}/api/admin/firms/{a}/features/extract"
            check("switch off for A", await call("PUT", sw, h_admin, json={"enabled": False}), 200)
            check("employee 503 when switched off", await call("GET", f"{base_x}/formats", h_emp), 503)
            r = await c.get(f"{base}/api/features", headers=h_emp)
            check("features reports off", r.json()["enabled"].get("extract"), False)
            check("B unaffected by A's switch", await call("GET", f"{base_x}/formats", h_b), 200)
            check("switch back on for A", await call("PUT", sw, h_admin, json={"enabled": None}), 200)
            check("employee 200 after switch back", await call("GET", f"{base_x}/formats", h_emp), 200)
            r = await c.get(f"{base}/api/features", headers=h_emp)
            check("features reports on", r.json()["enabled"].get("extract"), True)

            # Per-person access off: 403 (the maintenance switch is 503, the person's refusal is 403).
            acc = f"{base}/api/team/members/{emp}/access"
            check("owner turns employee's extract off", await call("PUT", acc, h_a, json={"off": ["extract"]}), 200)
            check("employee 403 with access off", await call("GET", f"{base_x}/formats", h_emp), 403)
            r = await c.get(f"{base}/api/features", headers=h_emp)
            check("features reports off for the person", r.json()["enabled"].get("extract"), False)
            check("owner turns it back on", await call("PUT", acc, h_a, json={"off": []}), 200)
            check("employee 200 after access restored", await call("GET", f"{base_x}/formats", h_emp), 200)

            # A deletes its own run: run and file rows stay as a tombstone, the records go.
            check("A deletes own run", await call("DELETE", f"{base_x}/runs/{fa['run']}", h_a), 204)
            r = await c.get(f"{base_x}/runs", headers=h_a)
            check("deleted run leaves the list", fa["run"] in [x["id"] for x in r.json()["runs"]], False)
            async with async_session() as db:
                await bind_session_user(db, str(a))
                run_id = uuid.UUID(fa["run"])
                left = (await db.execute(select(func.count(AAExtractRecord.id)).where(
                    AAExtractRecord.run_id == run_id, AAExtractRecord.enterprise_id == a))).scalar_one()
                kept = (await db.execute(select(func.count(AAExtractFile.id)).where(
                    AAExtractFile.run_id == run_id, AAExtractFile.enterprise_id == a))).scalar_one()
                await db.commit()
            check("deleted run's records removed", left, 0)
            check("deleted run's file row kept", kept, 1)
        print(f"ALL {passed} CHECKS PASSED")
    finally:
        # Everything hangs off the users (ON DELETE CASCADE): formats, runs, files, records, overrides, audit rows.
        # Each user in its own session so one failure never skips the rest; the original error still propagates.
        for uid in made[::-1]:
            try:
                async with async_session() as db:
                    await db.execute(delete(User).where(User.id == uid))
                    await db.commit()
            except Exception as exc:  # noqa: BLE001
                print(f"CLEANUP FAILED for user {uid}: {exc!r}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"))
