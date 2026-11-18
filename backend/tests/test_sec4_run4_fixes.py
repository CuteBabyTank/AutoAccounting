"""Regressions for the run-4 security audit fixes (each test names the finding it pins)."""

import asyncio
import io
import time
import uuid
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.accounting import AAAuditEvent, AABankLine, AABankReconciliation, AABankStatement, AADocument
from app.models.user import User, UserRole
from tests.test_sec3_match_retention import MatchDB, Result, stored


# --- bank: line changes keep retained (closed / reconciled) history -------------------------------------------------

class BankDB(MatchDB):
    """Closed March 2026 with a live March reconciliation; line A (31 March) auto-matches the invoice."""

    def __init__(self):
        super().__init__()
        owner = self.user
        self.employee = stored(User, id=uuid.uuid4(), role=UserRole.EMPLOYEE, enterprise_id=owner.id,
                               email="employee@example.test")
        self.statement = stored(AABankStatement, id=self.line.statement_id, enterprise_id=owner.id,
                                company_id=self.company.id, document_id=uuid.uuid4(), account_code="1020",
                                period_start=date(2026, 3, 1), period_end=date(2026, 4, 30))
        self.line_b = stored(AABankLine, id=uuid.uuid4(), enterprise_id=owner.id, company_id=self.company.id,
                             statement_id=self.line.statement_id, account_code="1020", line_date=date(2026, 4, 10),
                             line_no=2, amount=Decimal("-100"), narration="Online transfer 555")
        self.rec = stored(AABankReconciliation, id=uuid.uuid4(), enterprise_id=owner.id, company_id=self.company.id,
                          account_code="1020", month_start=date(2026, 3, 1), month_end=date(2026, 3, 31),
                          statement_balance=Decimal("0"), book_balance=Decimal("0"),
                          reconciled_at=datetime.now(timezone.utc))
        self.rec.voided_at = None
        self.others = []

    def lines(self):
        return [self.line, self.line_b]

    async def execute(self, stmt):
        cols = stmt.column_descriptions
        entity, name = cols[0]["entity"], cols[0]["name"]
        params = list(stmt.compile().params.values()) if entity is not User else []
        where = str(stmt.whereclause)
        if entity is AABankLine and name == "AABankLine":
            hit = [l for l in self.lines() if l.id in params]
            if hit:
                return Result(hit)
            if self.statement.id in params and "statement_id =" in where:
                return Result([l for l in self.lines() if l.statement_id == self.statement.id])
            return Result([l for l in self.lines() if l.account_code])
        if entity is AABankLine and name == "id":
            if "matched_ref" in where:  # lines already paying a document
                return Result([l.id for l in self.lines() if l.matched_ref in params and l.id not in params
                               and l.match_kind == "document" and l.match_status in ("matched", "confirmed")])
            return Result([l.id for l in self.lines() if l.account_code])
        if entity is AABankLine and name == "matched_ref":
            return Result([l.matched_ref for l in self.lines() if l.match_kind == "document"
                           and l.match_status in ("matched", "confirmed")])
        if entity is AABankReconciliation and name == "AABankReconciliation":
            on = next((p for p in params if isinstance(p, date)), None)
            acct = next((p for p in params if isinstance(p, str)), None)
            return Result([r for r in [self.rec] if r.voided_at is None and (acct is None or r.account_code == acct)
                           and (on is None or r.month_end >= on)])
        if entity is AABankStatement and name == "AABankStatement":
            return Result([self.statement] if self.statement.id in params else [])
        if entity is AADocument and name == "id" and len(cols) == 1:
            return Result([])
        return await super().execute(stmt)

    async def get(self, model, ident):
        return self.doc if ident == self.doc.id else None

    def add(self, row):
        (self.audits if isinstance(row, AAAuditEvent) else self.others).append(row)


async def bank_db(monkeypatch):
    from app.routers import accounting_bank
    from app.services.accounting.books import bank

    async def month_out(*args):
        return None
    monkeypatch.setattr(accounting_bank, "_month_out", month_out)
    db = BankDB()
    db.locked = True
    await bank.rematch(db, db.company)
    db.locked = False
    db.rec.voided_at = None
    db.audits.clear()
    assert db.line.match_status == "matched" and db.line.matched_ref == str(db.doc.id)
    return db


async def test_confirming_an_open_line_cannot_take_a_retained_lines_document(monkeypatch):
    """accounting_bank.after_change-full-rematch-without-retention-guard (side-effect unmatch)."""
    from app.routers import accounting_bank
    from app.schemas.accounting_bank import ConfirmLineIn
    db = await bank_db(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await accounting_bank.confirm_line(db.line_b.id, ConfirmLineIn(kind="document", ref=str(db.doc.id)),
                                           user=db.employee, db=db)
    assert exc.value.status_code == 409
    assert db.line.match_status == "matched" and db.rec.voided_at is None and db.commits == 0


@pytest.mark.parametrize("route", ["exclude_line", "reject_line"])
async def test_changing_a_closed_month_line_is_refused(monkeypatch, route):
    """accounting_bank.after_change-full-rematch-without-retention-guard (direct change)."""
    from app.routers import accounting_bank
    db = await bank_db(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await getattr(accounting_bank, route)(db.line.id, None, user=db.employee, db=db)
    assert exc.value.status_code == 409 and "closed" in exc.value.detail
    assert db.line.match_status == "matched" and db.rec.voided_at is None and db.commits == 0


async def test_manual_rematch_keeps_retained_lines(monkeypatch):
    """accounting_bank.after_change-full-rematch-without-retention-guard (POST /bank/rematch)."""
    from app.routers import accounting_bank
    from app.services.accounting import deletion
    from app.services.accounting.books import bank
    db = await bank_db(monkeypatch)
    seen = []
    real = bank.rematch

    async def spy(db_, company, *, line_ids=None):
        seen.append(line_ids)
        return await real(db_, company, line_ids=line_ids)
    monkeypatch.setattr(bank, "rematch", spy)
    db.locked = True
    ids = await deletion.rematchable_line_ids(db, db.company)
    assert db.line.id not in ids and db.line_b.id in ids
    await bank.rematch(db, db.company, line_ids=ids)
    assert db.line.match_status == "matched" and db.rec.voided_at is None
    assert all(s is not None for s in seen)
    # The route itself never runs an unrestricted rematch any more.
    import inspect
    source = inspect.getsource(accounting_bank)
    assert "bank.rematch(db, company)" not in source


# --- audit log honours per-person areas ------------------------------------------------------------------------------

def test_audit_log_hides_entities_of_refused_areas():
    """audit-events-ignores-per-person-areas"""
    from app.routers.accounting_audit import ENTITY_AREA, events_query, hidden_entities
    from app.services.accounting.audit import ENTITIES
    assert set(ENTITY_AREA) <= ENTITIES
    hidden = hidden_entities({"employees": False, "books": False, "bank": False})
    assert {"employee", "journal_entry", "account", "bank_line", "bank_reconciliation"} <= set(hidden)
    assert "document" not in hidden and "task" not in hidden
    sql = str(events_query(uuid.uuid4(), hidden=hidden).compile(compile_kwargs={"literal_binds": True}))
    assert "NOT IN" in sql and "'employee'" in sql
    assert hidden_entities({}) == []


# --- request limiting counts revoked tokens before any DB work ------------------------------------------------------

async def test_revoked_token_is_rate_limited_before_the_user_lookup(monkeypatch):
    """backend/app/dependencies.py:get_current_user:global_user_limiter-after-_get_active_user"""
    from fastapi.security import HTTPAuthorizationCredentials
    from app import dependencies
    from app.auth.jwt import create_access_token
    from app.auth.security import RateLimiter
    monkeypatch.setattr(dependencies, "global_user_limiter", RateLimiter(max_attempts=3, window_seconds=60))
    uid = str(uuid.uuid4())
    token = HTTPAuthorizationCredentials(scheme="Bearer", credentials=create_access_token(uid))
    lookups = []

    class DB:
        async def execute(self, stmt, *a):
            lookups.append(stmt)
            return SimpleNamespace(scalar_one_or_none=lambda: None)  # user deleted
    statuses = []
    for _ in range(5):
        try:
            await dependencies.get_current_user(token, DB())
        except HTTPException as exc:
            statuses.append(exc.status_code)
    assert statuses == [401, 401, 401, 429, 429] and len(lookups) == 3


# --- team add-member gives one answer ---------------------------------------------------------------------------------

@pytest.mark.parametrize("target", [
    None,
    dict(role=UserRole.MANAGER), dict(role=UserRole.ENTERPRISE), dict(role=UserRole.ADMIN),
    dict(role=UserRole.UNVERIFIED, email_verified_at=None),
    dict(role=UserRole.UNVERIFIED, platform_disabled_at=datetime.now(timezone.utc)),
])
async def test_add_member_answers_every_non_addable_target_the_same(target):
    """team.add_member/distinct-errors-disclose-other-firms-member-role-and-platform-disable"""
    from app.routers import team
    from app.schemas.auth import AddMemberRequest
    user = None
    if target is not None:
        values = dict(email_verified_at=datetime.now(timezone.utc), platform_disabled_at=None) | target
        user = SimpleNamespace(id=uuid.uuid4(), email="x@example.com", **values)

    class DB:
        async def execute(self, stmt):
            return SimpleNamespace(scalar_one_or_none=lambda: user)
    ctx = SimpleNamespace(enterprise=SimpleNamespace(id=uuid.uuid4()), caller=SimpleNamespace(role=UserRole.MANAGER))
    with pytest.raises(HTTPException) as exc:
        await team.add_member(AddMemberRequest(email="x@example.com"), db=DB(), ctx=ctx)
    assert (exc.value.status_code, exc.value.detail) == (400, team._NOT_ADDABLE)


# --- password sign-in: unknown addresses lock like real ones -------------------------------------------------------

async def test_unknown_address_locks_like_a_real_account(monkeypatch):
    """auth/password-login/lockout-account-enumeration"""
    from app.auth.security import RateLimiter
    from app.services import password_auth, passwords
    monkeypatch.setattr(password_auth, "unknown_login_limiter", RateLimiter(max_attempts=10, window_seconds=900))

    async def nobody(db, email):
        return None

    async def verify(hash_, password):
        return False
    monkeypatch.setattr(password_auth, "_user_by_email", nobody)
    monkeypatch.setattr(passwords, "verify_password", verify)
    codes = []
    for _ in range(11):
        try:
            await password_auth.login(None, "nobody@example.test", "wrong-password-1")
        except HTTPException as exc:
            codes.append(exc.status_code)
    assert codes == [401] * 10 + [429]


# --- email allowance: one source can't use up an address's allowance ------------------------------------------------

def test_email_allowance_is_per_source_and_inbox_cap_counts_sends_only():
    """auth/email-send-limiter/victim-budget-exhaustion"""
    from starlette.requests import Request
    from app.auth import security
    from app.routers import auth
    security.email_send_limiter._attempts.clear()

    def req(ip):
        return Request({"type": "http", "headers": [], "client": (ip, 1), "method": "POST", "path": "/"})
    assert all(auth._throttle_email(req("203.0.113.9"), "Victim@Example.com") for _ in range(3))
    assert not auth._throttle_email(req("203.0.113.9"), "victim@example.com")   # the attacker is out
    assert auth._throttle_email(req("198.51.100.7"), "victim@example.com")       # the owner is not


async def test_inbox_cap_stops_sends_not_answers(monkeypatch):
    from app.auth.security import RateLimiter
    from app.services import password_auth
    monkeypatch.setattr(password_auth, "email_address_limiter", RateLimiter(max_attempts=2, window_seconds=3600))
    sent = []

    async def deliver(email, subject, text):
        sent.append(email)
    monkeypatch.setattr(password_auth, "_deliver", deliver)
    for _ in range(4):
        await password_auth._send_link("a@example.test", "s", "i", "/login?verify", "t", "1 hour")
    await asyncio.sleep(0)
    assert len(sent) == 2


# --- Extract export: exponent-form values stay text -----------------------------------------------------------------

def test_extract_export_keeps_huge_exponents_as_text():
    """extract/export.py:_number:unbounded-exponent-int"""
    from app.services.accounting.extract.export import _number, _put
    from openpyxl import Workbook
    assert _number("9E999999") is None and _number("1E-30") is None
    assert _number("1,234.50") == Decimal("1234.50")
    ws = Workbook().active
    started = time.monotonic()
    _put(ws, 1, 1, "money", "9E999999")
    assert time.monotonic() - started < 0.5 and ws.cell(1, 1).value == "9E999999"


# --- page viewer: one firm can't hold every render slot -------------------------------------------------------------

async def test_render_pool_caps_each_firm():
    """accounting/page-viewer/render-pool-per-user-not-per-firm-admission"""
    import threading
    from app.services.accounting import render_pool
    gate = threading.Event()
    held = [asyncio.ensure_future(render_pool.run_pdf_work(gate.wait, 5, owner=f"a{i}", firm="A"))
            for i in range(render_pool.VIEWER_PER_FIRM)]
    await asyncio.sleep(0.05)
    try:
        with pytest.raises(render_pool.RenderBusy):
            await render_pool.run_pdf_work(lambda: 1, owner="a-extra", firm="A")
        assert await render_pool.run_pdf_work(lambda: 2, owner="b1", firm="B") == 2
    finally:
        gate.set()
        await asyncio.gather(*held)
    assert render_pool._FIRMS == {}


# --- sheet import: aliased shared strings are cleaned once ----------------------------------------------------------

def test_aliased_padded_shared_string_is_not_copied_per_cell():
    """payroll_import.parse_sheet:shared-string-strip-copy-amplification"""
    from app.services.accounting import payroll_import
    calls = []
    real = payroll_import._cell

    def counting(v):
        calls.append(v)
        return real(v)
    buf = io.BytesIO()
    cells = "".join(f'<c r="{chr(65 + c)}{r}" t="s"><v>0</v></c>' for c in range(10) for r in [1])
    rows = "".join(f'<row r="{r}">' + cells.replace("1\"", f'{r}"') + "</row>" for r in range(1, 51))
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1"><si><t xml:space="preserve">Header value </t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{rows}</sheetData></worksheet>')
    import unittest.mock as m
    with m.patch.object(payroll_import, "_cell", counting):
        headers, data = payroll_import.parse_sheet(buf.getvalue(), "s.xlsx")
    assert headers[0] == "Header value"
    # One shared string referenced by 500 cells: cleaned (stripped) once, not once per reference.
    assert sum(1 for v in calls if isinstance(v, str)) <= 2


# --- Casper attachments: bounded queue, no secrets in the decoder child ----------------------------------------------

async def test_attachment_queue_is_bounded_and_worker_env_has_no_secrets(monkeypatch):
    """assistant-attachments-unbounded-parse-queue-retains-chat-bodies (+ worker environment hardening)"""
    from app.services.accounting.assistant import attachments
    monkeypatch.setenv("JWT_SECRET", "dummy-secret-for-test")
    env = attachments._worker_env()
    assert "JWT_SECRET" not in env and "DATABASE_URL" not in env
    monkeypatch.setattr(attachments, "_waiting", attachments.MAX_WAITING)
    with pytest.raises(ValueError, match="other attachments"):
        await attachments._parse(SimpleNamespace())


# --- anonymous bodies get only the default cap ----------------------------------------------------------------------

def test_bulk_allowance_needs_a_signature_valid_token():
    """backend/app/body_limit.py:route-agnostic-multipart-cap-parsed-before-auth"""
    from app.auth.jwt import create_access_token
    from app.main import _bearer_ok
    assert _bearer_ok(f"Bearer {create_access_token(str(uuid.uuid4()))}")
    assert not _bearer_ok("") and not _bearer_ok("Bearer nope") and not _bearer_ok("Basic abc")


# --- receipt re-link and fiscal-year change go through the retention guard -----------------------------------------

def test_relink_and_fiscal_year_paths_call_the_guard():
    """accounting.patch_document-settles_document_id-new-target-unchecked-by-deletion.protect_document,
    accounting.update_company/fiscal-year-change-reperiods-filed-documents-without-retention-guard,
    accounting_imports.patch_opening_item-no-retention-guard-bypasses-deletion.protect_opening_item"""
    import inspect
    from app.routers import accounting, accounting_imports
    patch = inspect.getsource(accounting.patch_document)
    assert 'protect_document(db, company, target, doing="linking a payment to it")' in patch
    update = inspect.getsource(accounting.update_company)
    assert 'doing="changing the fiscal year end"' in update
    assert update.index("protect_history") < update.index("setattr(company, name, value)")
    item = inspect.getsource(accounting_imports.patch_opening_item)
    assert 'protect_opening_item(db, company, row, doing="changing its payment")' in item
    assert "bank.rematch(db, company)" not in item
