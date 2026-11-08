"""Real job orchestration, identity binding and relinking with an RLS-aware DB double."""

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.sql.elements import TextClause

from app.config import settings
from app.dependencies import _reapply_rls_guc
from app.models.accounting import (
    AAAccount, AABankLine, AACompany, AADocument, AAFile, AASupplierRule, AAUpload,
)
from app.models.user import User, UserRole
from app.services.accounting import pipeline


class Result:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    def scalars(self) -> "Result":
        return self

    def all(self) -> list:
        return self.rows


class JobDB:
    def __init__(self, image: str) -> None:
        self.owner = User(id=uuid.uuid4(), role=UserRole.ADMIN, is_active=True)
        self.other = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, is_active=True)
        self.actor = User(id=uuid.uuid4(), role=UserRole.EMPLOYEE, enterprise_id=self.owner.id)
        self.users = {u.id: u for u in (self.owner, self.other, self.actor)}
        self.upload = SimpleNamespace(id=uuid.uuid4(), enterprise_id=self.owner.id, uploaded_by=self.actor.id,
                                      total_files=1, processed_files=0, status="extracting")
        self.company = AACompany(id=uuid.uuid4(), enterprise_id=self.owner.id, registered_name="Client",
                                 tin="123456789", aliases=[], owner_names=[], books_signatory="",
                                 vat_status="non-vat", fiscal_year_end_month=12, business_type="services",
                                 is_withholding_agent=False, is_top_withholding_agent=False)
        self.file = SimpleNamespace(id=uuid.uuid4(), enterprise_id=self.owner.id, company_id=self.company.id,
                                    stored_path=image, file_type="jpg", page_count=1, sha256="a" * 64,
                                    pages_charged=False, status="uploaded", interrupts=0, detection=None)
        self.sync_session = SimpleNamespace(info={})
        self.bound: uuid.UUID | None = None
        self.docs: list[AADocument] = []
        self.locked = False
        self.relink_reads = 0
        self.rollbacks = 0

    def firm(self) -> uuid.UUID | None:
        user = self.users.get(self.bound)
        return None if user is None else (user.id if user.role in (UserRole.ADMIN, UserRole.ENTERPRISE)
                                          else user.enterprise_id)

    def begin(self) -> None:
        if self.bound is None:
            # Use the real transaction hook after every commit/rollback, as the pooler requires.
            def exec_driver_sql(sql: str) -> None:
                self.bound = uuid.UUID(sql.split("'")[3])
            _reapply_rls_guc(self.sync_session, None, SimpleNamespace(exec_driver_sql=exec_driver_sql))

    async def get(self, model, ident):
        self.begin()
        if model is User:
            return self.users.get(ident)
        if self.firm() != self.owner.id:
            return None
        return {AAUpload: self.upload, AAFile: self.file, AACompany: self.company}[model]

    async def execute(self, stmt, params=None) -> Result:
        if isinstance(stmt, TextClause):
            self.bound = uuid.UUID(params["uid"])
            return Result([])
        self.begin()
        if getattr(stmt, "is_update", False):
            assert self.firm() == self.owner.id
            if stmt.table.name == "aa_uploads":
                params = stmt.compile().params
                assert self.owner.id in params.values()
                self.upload.updated_at = params["updated_at"]
            return Result([])
        entity = stmt.column_descriptions[0]["entity"]
        if entity is User:
            assert stmt._for_update_arg is not None
            assert self.owner.id in stmt.compile().params.values()
            self.locked = True
            return Result([])
        assert self.firm() == self.owner.id, "RLS denies reads under the departed initiator"
        if entity is AAFile:
            return Result([self.file])
        if entity is AACompany:
            return Result([(self.company.id, self.company.tin)] if len(stmt.column_descriptions) > 1
                          else [self.company])
        if entity is AADocument:
            if len(stmt.column_descriptions) > 1:
                return Result([])
            assert self.locked, "relink/duplicate reads must take the firm lock before document locks"
            self.relink_reads += 1
            return Result(self.docs)
        assert entity in (AAAccount, AASupplierRule, AABankLine)
        return Result([])

    def add_all(self, docs: list[AADocument]) -> None:
        self.docs.extend(docs)

    async def flush(self) -> None:
        self.begin()
        assert self.firm() == self.owner.id, "RLS denies writes after initiator changes firms"
        for doc in self.docs:
            for column in doc.__table__.columns:
                if getattr(doc, column.name) is None and column.default is not None:
                    default = column.default.arg
                    setattr(doc, column.name, default(None) if callable(default) else default)
            assert doc.enterprise_id == self.firm()

    async def commit(self) -> None:
        await self.flush()
        self.bound = None
        self.locked = False

    async def rollback(self) -> None:
        self.bound = None
        self.locked = False
        self.rollbacks += 1


@contextmanager
def session_factory(monkeypatch: pytest.MonkeyPatch, db: JobDB) -> Iterator[None]:
    class Session:
        async def __aenter__(self) -> JobDB:
            return db

        async def __aexit__(self, *args) -> None:
            pass

    monkeypatch.setattr(pipeline, "async_session", Session)
    yield


@pytest.mark.parametrize("phase", ["queued", "reading"])
@pytest.mark.parametrize("membership", ["removed", "moved"])
async def test_job_keeps_original_firm_across_initiator_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog, phase: str, membership: str,
) -> None:
    db = JobDB(str(tmp_path / "receipt.jpg"))
    # Qwen forwards existing images, so no rasterization is needed for this RLS/lock test.
    (tmp_path / "receipt.jpg").write_bytes(b"image sent to mocked network")
    monkeypatch.setattr(settings, "accounting_reader", "qwen")
    monkeypatch.setattr(settings, "accounting_reader_base_url", "https://reader.test/v1")
    monkeypatch.setattr(settings, "accounting_reader_api_key", "test")

    def leave() -> None:
        db.actor.enterprise_id = db.other.id if membership == "moved" else None
        db.actor.role = UserRole.EMPLOYEE if membership == "moved" else UserRole.UNVERIFIED

    async def post(self: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        if phase == "reading":
            leave()
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"documents":[{"kind":"invoice","doc_number":"RLS","gross_amount":100}]}'}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    caplog.set_level("INFO", logger="reader")
    if phase == "queued":
        leave()
    with session_factory(monkeypatch, db):
        await pipeline._guarded(pipeline.run_extraction, db.upload.id, str(db.actor.id), db.owner.id)
    assert db.upload.status == "done" and db.file.status == "extracted"
    assert len(db.docs) == 1 and db.docs[0].enterprise_id == db.owner.id
    assert db.upload.uploaded_by == db.actor.id
    assert f"user_id={db.actor.id}" in caplog.text
    assert db.relink_reads >= 2 and db.rollbacks == 0


async def test_detection_uses_firm_owner_after_initiator_leaves(monkeypatch, tmp_path) -> None:
    db = JobDB(str(tmp_path / "receipt.jpg"))
    (tmp_path / "receipt.jpg").write_bytes(b"image")
    db.actor.role, db.actor.enterprise_id = UserRole.UNVERIFIED, None
    monkeypatch.setattr(settings, "accounting_reader", "qwen")
    monkeypatch.setattr(settings, "accounting_reader_base_url", "https://reader.test/v1")
    monkeypatch.setattr(settings, "accounting_reader_api_key", "test")

    async def post(self, url, **kwargs) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"kind":"invoice","seller":{"name":"Client","tin":"123456789"}}'}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with session_factory(monkeypatch, db):
        await pipeline._guarded(pipeline.run_detection, db.upload.id, str(db.actor.id), db.owner.id)
    assert db.upload.status == "awaiting_confirmation" and db.file.status == "detected"
    assert "error" not in db.file.detection


async def test_job_failure_is_persisted_after_initiator_leaves(monkeypatch, tmp_path) -> None:
    db = JobDB(str(tmp_path / "receipt.jpg"))
    db.actor.role, db.actor.enterprise_id = UserRole.UNVERIFIED, None
    execute = db.execute

    async def failing_select(stmt, params=None) -> Result:
        if (not isinstance(stmt, TextClause) and getattr(stmt, "column_descriptions", [{}])[0]
                .get("entity") is AACompany):
            raise ValueError("simulated DB read failure")
        return await execute(stmt, params)

    monkeypatch.setattr(db, "execute", failing_select)
    with session_factory(monkeypatch, db):
        await pipeline._guarded(pipeline.run_detection, db.upload.id, str(db.actor.id), db.owner.id)
    assert db.upload.status == "failed"


async def test_shutdown_releases_upload_under_its_original_firm(monkeypatch, tmp_path) -> None:
    db = JobDB(str(tmp_path / "receipt.jpg"))
    (tmp_path / "receipt.jpg").write_bytes(b"image")
    db.actor.role, db.actor.enterprise_id = UserRole.UNVERIFIED, None
    db.upload.status = "detecting"
    started, stop = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(settings, "accounting_reader", "qwen")
    monkeypatch.setattr(settings, "accounting_reader_base_url", "https://reader.test/v1")
    monkeypatch.setattr(settings, "accounting_reader_api_key", "test")
    monkeypatch.setattr(pipeline, "_ACTIVE", {})
    monkeypatch.setattr(pipeline, "_TASKS", set())

    async def post(self, url, **kwargs) -> httpx.Response:
        started.set()
        await stop.wait()
        raise AssertionError("shutdown should cancel the reader")

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with session_factory(monkeypatch, db):
        pipeline.start_detection(db.upload.id, str(db.actor.id), db.owner.id)
        try:
            await asyncio.wait_for(started.wait(), 2)
            await pipeline.release_running()
        finally:
            stop.set()
            await asyncio.gather(*pipeline._TASKS, return_exceptions=True)
    assert db.upload.updated_at < datetime.now(timezone.utc) - pipeline.STALE_AFTER
    assert not pipeline.is_running(db.upload.id)
