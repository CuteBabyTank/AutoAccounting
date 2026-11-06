"""Regression tests for the 2026-11 security audit fixes (run-2 findings)."""

import asyncio
import logging
import random
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import fitz
import pytest
from fastapi import HTTPException

from app.config import settings
from app.models.user import User, UserRole
from app.services import avatar_service, features
from app.services.accounting import duplicates, jobs, pipeline, schema
from app.services.accounting.duplicates import DupDoc, duplicate_pairs


# ── duplicates: same pairs as before, without the quadratic rescans ──────────

def _reference_pairs(docs):
    """The pre-fix algorithm, kept verbatim as the behavioural oracle."""
    by_number, by_details, pairs = {}, {}, []
    for doc in docs:
        number_key = (doc.role, doc.counterparty, doc.doc_number) if doc.doc_number else None
        details_key = ((doc.role, doc.counterparty, doc.doc_date, doc.gross)
                       if doc.counterparty and doc.doc_date and doc.gross > 0 else None)
        found = reused = None
        for key, index, reason in ((number_key, by_number, duplicates.SAME_NUMBER),
                                   (details_key, by_details, duplicates.SAME_DETAILS)):
            if key is None or found:
                continue
            for earlier in index.get(key, []):
                if reason == duplicates.SAME_DETAILS and earlier.doc_number and doc.doc_number:
                    continue
                if (reason == duplicates.SAME_NUMBER and earlier.doc_date and doc.doc_date
                        and earlier.doc_date != doc.doc_date):
                    if (reused is None and duplicates._is_bill(doc) and duplicates._is_bill(earlier)
                            and not duplicates._cleared(earlier, doc)):
                        reused = duplicates.Pair(earlier.id, doc.id, duplicates.NUMBER_REUSED)
                    continue
                if not duplicates._cleared(earlier, doc):
                    found = duplicates.Pair(earlier.id, doc.id, reason)
                    break
        if found or reused:
            pairs.append(found or reused)
        if number_key:
            by_number.setdefault(number_key, []).append(doc)
        if details_key:
            by_details.setdefault(details_key, []).append(doc)
    return pairs


def _random_docs(rng: random.Random, n: int) -> list[DupDoc]:
    ids = [uuid.UUID(int=i + 1) for i in range(n)]
    docs = []
    for i in range(n):
        cleared = frozenset(str(ids[j]) for j in range(i) if rng.random() < 0.05)
        docs.append(DupDoc(
            id=ids[i], role=rng.choice(["buyer", "seller"]), counterparty=rng.choice(["", "A", "B"]),
            doc_number=rng.choice(["", "1", "2"]), doc_date=rng.choice([None, date(2026, 1, 1), date(2026, 1, 2)]),
            gross=Decimal(rng.choice([0, 100, 200])), not_duplicate_of=cleared,
            category=rng.choice(["purchases", "expenses", "sales", ""])))
    return docs


@pytest.mark.parametrize("seed", range(300))
def test_duplicate_pairs_match_the_previous_algorithm(seed):
    rng = random.Random(seed)
    docs = _random_docs(rng, rng.randint(1, 40))
    assert duplicate_pairs(docs) == _reference_pairs(docs)


def test_duplicate_scan_stays_near_linear_on_one_number():
    def build(n):
        return [DupDoc(id=uuid.UUID(int=i + 1), role="buyer", counterparty="123456789", doc_number="X",
                       doc_date=date(2000, 1, 1) + timedelta(days=i), gross=Decimal(100 + i), category="sales")
                for i in range(n)]
    docs = build(20_000)
    started = time.perf_counter()
    assert duplicate_pairs(docs) == []
    assert time.perf_counter() - started < 1.0  # was ~10 s at this size


# ── PDFs: page cap, chunks built one at a time ───────────────────────────────

def _blank_pdf(path, pages):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(path)
    doc.close()


def test_chunk_ranges_cover_every_page_without_building_chunks():
    assert pipeline.aa_gemini.pdf_chunk_ranges(5, 2) == [(0, 1), (2, 3), (4, 4)]


async def test_extraction_refuses_pdfs_over_the_page_cap(tmp_path, monkeypatch):
    path = tmp_path / "long.pdf"
    _blank_pdf(str(path), 4)
    monkeypatch.setattr(settings, "max_pdf_pages", 3)
    with pytest.raises(ValueError, match="limit is 3"):
        await pipeline._chunks(str(path), "pdf")


async def test_chunks_are_built_inside_the_gate(tmp_path, monkeypatch):
    path = tmp_path / "doc.pdf"
    _blank_pdf(str(path), 6)
    monkeypatch.setattr(pipeline.aa_gemini, "pages_per_chunk", lambda: 2)
    monkeypatch.setattr(pipeline.aa_gemini, "chunks_at_once", lambda: 1)
    live, peak = 0, 0
    real_build = pipeline._chunk_bytes

    async def build(*args):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        return await real_build(*args)

    async def read(file_id, data, mime, start0, end0, prompt, user_id):
        nonlocal live
        await asyncio.sleep(0)
        live -= 1
        return start0, end0 - start0 + 1, None

    monkeypatch.setattr(pipeline, "_chunk_bytes", build)
    monkeypatch.setattr(pipeline, "_read_chunk", read)
    out = await pipeline._read_file(uuid.uuid4(), str(path), "pdf", "prompt", "u")
    assert [o[0] for o in out] == [0, 2, 4]
    assert peak == 1  # never more chunk bytes alive than calls in flight


def test_an_oversized_chunk_is_refused(tmp_path):
    path = tmp_path / "doc.pdf"
    _blank_pdf(str(path), 2)
    with pytest.raises(ValueError, match="expand"):
        pipeline.aa_gemini.pdf_chunk(str(path), 0, 1, limit=10)


# ── avatar ───────────────────────────────────────────────────────────────────

def test_avatar_pixel_cap_fits_a_small_avatar():
    assert avatar_service.MAX_PIXELS <= 16_000_000


async def test_avatar_is_processed_off_the_event_loop(monkeypatch):
    import threading
    from app.routers import auth as auth_router
    seen = []

    def fake_make(data):
        seen.append(threading.current_thread() is threading.main_thread())
        return b"webp"

    async def response(db, user):
        raise _Stop

    class _Stop(Exception):
        pass

    monkeypatch.setattr(auth_router, "make_avatar", fake_make)
    monkeypatch.setattr(auth_router, "_response", response)
    upload = SimpleNamespace(read=lambda n: asyncio.sleep(0, result=b"x"))
    db = SimpleNamespace(commit=lambda: asyncio.sleep(0))
    with pytest.raises(_Stop):
        await auth_router.upload_avatar(file=upload, user=SimpleNamespace(avatar=None), db=db)
    assert seen == [False]


# ── access areas ─────────────────────────────────────────────────────────────

def test_search_drops_groups_whose_area_is_off():
    from app.routers.accounting_search import GROUP_TYPES, allowed_groups
    enabled = {k: True for k in features.KEYS} | {"bank": False, "books": False}
    assert allowed_groups(list(GROUP_TYPES), enabled) == [
        k for k in GROUP_TYPES if k not in ("bank_line", "journal_entry")]
    assert allowed_groups(["company"], {}) == ["company"]


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/accounting/companies/abc/assets"),
    ("DELETE", "/api/accounting/assets/abc"),
])
def test_opening_asset_writes_are_gated_as_books(method, path):
    assert features.feature_for_route(method, path) == "books"


def test_asset_list_and_edits_are_checked_per_asset():
    assert features.feature_for_route("GET", "/api/accounting/companies/abc/assets") is None
    assert features.feature_for_route("PATCH", "/api/accounting/assets/abc") is None


@pytest.mark.parametrize("document_id,area", [(None, "books"), (uuid.uuid4(), "documents")])
async def test_asset_edit_checks_the_assets_own_area(monkeypatch, document_id, area):
    from app.routers import accounting_annual
    asked = []

    class _Stop(Exception):
        pass

    async def require(db, user, key):
        asked.append(key)
        raise _Stop

    async def no_lock(db, ent):
        return None

    row = SimpleNamespace(id=uuid.uuid4(), document_id=document_id, company_id=uuid.uuid4())

    class _Db:
        async def execute(self, stmt):
            return SimpleNamespace(one_or_none=lambda: (row, None))

    monkeypatch.setattr(accounting_annual.features, "require_area", require)
    monkeypatch.setattr(accounting_annual, "lock_firm", no_lock)
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.EMPLOYEE, enterprise_id=uuid.uuid4())
    with pytest.raises(_Stop):
        await accounting_annual.patch_asset(row.id, accounting_annual.AssetPatch(), year=None, user=user, db=_Db())
    assert asked == [area]


class _OneUserDb:
    def __init__(self, user):
        self.user, self.statements = user, []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return SimpleNamespace(scalar_one_or_none=lambda: self.user, scalar_one=lambda: 1, rowcount=2)

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


async def test_removing_a_member_drops_access_their_firm_set(monkeypatch):
    from app.routers import team
    firm = uuid.uuid4()
    member = User(id=uuid.uuid4(), email="x@example.test", role=UserRole.EMPLOYEE, enterprise_id=firm,
                  is_active=True, access={"off": ["reports"], "assistant": "write"})
    monkeypatch.setattr(team.audit, "record", lambda *a, **k: None)
    ctx = SimpleNamespace(enterprise=SimpleNamespace(id=firm), caller=SimpleNamespace(role=UserRole.ENTERPRISE))
    await team.remove_member(member.id, db=_OneUserDb(member), ctx=ctx)
    assert member.access is None and member.enterprise_id is None


async def test_admin_move_to_another_firm_drops_access(monkeypatch):
    from app.routers import admin
    a, b = uuid.uuid4(), uuid.uuid4()
    member = User(id=uuid.uuid4(), email="y@example.test", role=UserRole.EMPLOYEE, enterprise_id=a,
                  is_active=True, access={"off": [], "assistant": "write"})

    async def firm(db, firm_id):
        return SimpleNamespace(id=firm_id)

    async def target(db, user_id):
        return member

    monkeypatch.setattr(admin, "_firm_or_404", firm)
    monkeypatch.setattr(admin, "_user_or_404", target)
    monkeypatch.setattr(admin.audit, "record", lambda *a, **k: None)
    req = admin.SetUserRoleRequest(role="employee", enterprise_id=str(b))
    await admin.set_user_role(member.id, req, db=_OneUserDb(member), admin=SimpleNamespace(id=uuid.uuid4()))
    assert member.enterprise_id == b and member.access is None


async def test_firm_reactivation_only_restores_members_the_suspension_turned_off(monkeypatch):
    from app.routers import admin
    owner = User(id=uuid.uuid4(), email="o@example.test", role=UserRole.ENTERPRISE, is_active=True)

    async def target(db, user_id):
        return owner

    monkeypatch.setattr(admin, "_user_or_404", target)
    monkeypatch.setattr(admin.audit, "record", lambda *a, **k: None)
    for expect in ("suspended_with_firm", "suspended_with_firm"):
        db = _OneUserDb(owner)
        await admin.toggle_active(owner.id, db=db, admin=SimpleNamespace(id=uuid.uuid4()))
        sql = str(db.statements[-1].compile(compile_kwargs={"literal_binds": True}))
        assert expect in sql
        if owner.is_active:  # reactivated: only rows the suspension marked
            assert "users.suspended_with_firm IS true" in sql
        else:  # suspended: only members still active
            assert "users.is_active IS true" in sql


# ── auth ─────────────────────────────────────────────────────────────────────

def test_startup_backfill_never_verifies_new_signups():
    stmts = schema.backfill_statements()
    verify = [s for s in stmts if "SET email_verified_at = created_at" in s]
    assert verify and all("created_at <" in s for s in verify)
    assert any("SET email_verified_at = NULL" in s for s in stmts)  # repairs the old boots


async def test_old_password_login_loses_to_a_reset_that_lands_meanwhile(monkeypatch):
    from app.services import password_auth
    user = User(id=uuid.uuid4(), email="v@example.test", role=UserRole.EMPLOYEE, is_active=True,
                password_hash="old-hash", email_verified_at=datetime.now(timezone.utc), failed_logins=0)

    async def by_email(db, email):
        return user

    async def verify(hashed, password):
        return hashed == "old-hash"

    async def lock(db, u):  # the reset committed while the hash was being checked
        u.password_hash = "new-hash"

    monkeypatch.setattr(password_auth, "_user_by_email", by_email)
    monkeypatch.setattr(password_auth.passwords, "verify_password", verify)
    monkeypatch.setattr(password_auth, "_lock_user", lock)
    with pytest.raises(HTTPException) as err:
        await password_auth.login(_OneUserDb(user), "v@example.test", "old password")
    assert err.value.status_code == 401


async def test_validation_errors_never_log_submitted_values():
    from fastapi.exceptions import RequestValidationError
    from app.main import _validation_exception_handler
    exc = RequestValidationError([{"loc": ("body", "password"), "type": "string_too_long",
                                   "input": "hunter2-SECRET", "ctx": {"max_length": 128}, "msg": "too long"}])
    request = SimpleNamespace(url=SimpleNamespace(path="/api/auth/password/login"))
    lines: list[str] = []
    handler = logging.Handler(logging.INFO)
    handler.emit = lambda record: lines.append(record.getMessage())
    app_logger = logging.getLogger("app")
    old_level = app_logger.level
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    try:
        await _validation_exception_handler(request, exc)
    finally:
        app_logger.removeHandler(handler)
        app_logger.setLevel(old_level)
    text = "\n".join(lines)
    assert "string_too_long" in text and "hunter2-SECRET" not in text


# ── upload recovery ──────────────────────────────────────────────────────────

def test_a_file_that_keeps_killing_its_job_is_set_aside():
    count, states = 0, []
    for _ in range(jobs.MAX_INTERRUPTS):
        count, status = jobs.after_interrupt(count)
        states.append(status)
    assert states == ["detected"] * (jobs.MAX_INTERRUPTS - 1) + ["error"]
