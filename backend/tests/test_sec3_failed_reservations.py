"""Job failure releases admission reservations and leaves assigned files retryable."""

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.sql.elements import TextClause

from app.models.accounting import AAAuditEvent, AACompany, AAFile, AAUpload
from app.models.api_usage import ApiUsage
from app.routers import accounting
from app.services import usage_service
from app.services.accounting import pipeline
from tests.test_sec3_job_boundaries import JobDB, Result, session_factory


class FailureDB(JobDB):
    """Execute file/upload SQL against a tiny SQLite persistence double, including joins and predicates."""

    def __init__(self, image):
        super().__init__(image)
        from app.models.user import UserRole

        self.owner.role = UserRole.ENTERPRISE
        self.owner.special_page_rate, self.owner.budget = 1.0, 10.0
        now = datetime.now(timezone.utc)
        self.upload.preselected_company_id = None
        self.upload.created_at = self.upload.updated_at = now
        self.file.upload_id = self.upload.id
        self.file.error_message = None
        self.file.original_filename, self.file.file_size = "receipt.jpg", 5
        self.file.created_at = now
        self.file.page_count = 10
        self.files = [self.file]
        self.uploads = [self.upload]
        self.usage = SimpleNamespace(pages_used=0)
        self.fail_company_read = False
        self.committed = []
        self.events = []
        self.engine = create_engine("sqlite://")
        self.sql = self.engine.connect()
        # Only the SQL storage is substituted. Use real admission/update WHERE clauses, rather than
        # teaching a fake the intended failed-upload/status filtering and thereby hiding a missing predicate.
        for model in (AAFile, AAUpload):
            columns = ", ".join(f'"{c.name}"' for c in model.__table__.columns)
            self.sql.exec_driver_sql(f"CREATE TABLE {model.__tablename__} ({columns})")

    def close(self):
        self.sql.close()
        self.engine.dispose()

    def sync_sql(self):
        for model, rows in ((AAFile, self.files), (AAUpload, self.uploads)):
            self.sql.execute(model.__table__.delete())
            for row in rows:
                values = {c.name: getattr(row, c.name, None) for c in model.__table__.columns}
                self.sql.execute(model.__table__.insert().values(**values))

    async def execute(self, stmt, params=None):
        if isinstance(stmt, TextClause):
            return await super().execute(stmt, params)
        entity = None if getattr(stmt, "is_update", False) else stmt.column_descriptions[0]["entity"]
        if entity is AACompany and self.fail_company_read:
            self.fail_company_read = False
            raise ValueError("transient DB failure before processing")
        if getattr(stmt, "is_update", False) or entity in (AAFile, AAUpload):
            self.begin()
            assert self.firm() == self.owner.id
            self.sync_sql()
            if getattr(stmt, "is_update", False):
                result = self.sql.execute(stmt)
                if stmt.table.name == "aa_files":
                    for ident, state, message in self.sql.execute(select(AAFile.id, AAFile.status,
                                                                       AAFile.error_message)):
                        row = next(f for f in self.files if f.id == ident)
                        row.status, row.error_message = state, message
                else:
                    for ident, state in self.sql.execute(select(AAUpload.id, AAUpload.status)):
                        next(u for u in self.uploads if u.id == ident).status = state
                return SimpleNamespace(rowcount=result.rowcount)
            if entity is AAFile and stmt.column_descriptions[0]["name"] == "page_count":
                return Result(self.sql.execute(stmt).scalars().all())
            ids = self.sql.execute(stmt).scalars().all()
            return Rows([row for row in (self.files if entity is AAFile else self.uploads) if row.id in ids])
        if entity is ApiUsage:
            return Rows([self.usage])
        if entity is AACompany and stmt.column_descriptions[0]["name"] == "id":
            return Rows([])  # the company is active, so retry's archived-company check has no hit
        return await super().execute(stmt, params)

    async def refresh(self, row, **kwargs):
        assert kwargs.get("with_for_update") is True
        self.locked = True

    async def commit(self):
        await super().commit()
        self.committed.append((self.upload.status, [f.status for f in self.files]))

    def add(self, row):
        assert isinstance(row, AAAuditEvent)
        self.events.append(row)


class Rows(Result):
    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def first(self):
        return self.rows[0] if self.rows else None


@pytest.mark.parametrize("state", ["uploaded", "detected", "extracting"])
@pytest.mark.parametrize("job", [pipeline.run_detection, pipeline.run_extraction])
async def test_failed_job_atomically_releases_files_and_allows_retry(monkeypatch, tmp_path, state, job):
    db = FailureDB(str(tmp_path / "receipt.jpg"))
    db.file.status = state
    # Finished/error files, another upload, and another firm must remain untouched.
    for status in ("extracted", "duplicate", "skipped", "superseded", "error"):
        db.files.append(SimpleNamespace(**(vars(db.file) | {"id": uuid.uuid4(), "status": status})))
    db.files.append(SimpleNamespace(**(vars(db.file) | {"id": uuid.uuid4(), "upload_id": uuid.uuid4()})))
    db.files.append(SimpleNamespace(**(vars(db.file) | {"id": uuid.uuid4(), "enterprise_id": db.other.id})))
    try:
        db.fail_company_read = True
        with session_factory(monkeypatch, db):
            await pipeline._guarded(job, db.upload.id, str(db.actor.id), db.owner.id)
            assert db.committed == [("failed", ["error", "extracted", "duplicate", "skipped",
                                                "superseded", "error", state, state])]
            assert db.file.error_message
            await usage_service.assert_pending_page_budget(db, db.owner)

            # Retry must reach the real admission check and response; stop its newly scheduled task
            # before it starts reading, keeping this regression entirely at the persistence boundary.
            # Use just the assigned failed file for this retry; prior file-level errors also remain retryable.
            db.files = [db.file]
            try:
                out = await accounting.retry_upload(db.upload.id, user=db.owner, db=db)
                assert out.status == "extracting" and out.files[0].status == "uploaded"
                assert db.file.error_message is None and db.owner.budget == 10.0
                assert db.events[-1].action == "retry"
            finally:
                tasks = list(pipeline._TASKS)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        db.close()


@pytest.mark.parametrize("state", ["uploaded", "detected", "extracting"])
async def test_old_failed_upload_does_not_reserve_budget_for_a_new_drop(state, tmp_path):
    db = FailureDB(str(tmp_path / "receipt.jpg"))
    db.upload.status = "failed"
    db.file.status = state  # legacy failed job, before atomic cleanup was introduced
    fresh = SimpleNamespace(**(vars(db.upload) | {"id": uuid.uuid4(), "status": "detecting"}))
    db.uploads.append(fresh)
    db.files.append(SimpleNamespace(**(vars(db.file) | {"id": uuid.uuid4(), "upload_id": fresh.id})))
    db.bound = db.owner.id  # a request session is RLS-bound by get_current_user before admission runs
    try:
        await usage_service.assert_pending_page_budget(db, db.owner)
        assert db.owner.budget == 10.0
        db.upload.status = "detecting"
        with pytest.raises(ValueError, match="budget"):
            await usage_service.assert_pending_page_budget(db, db.owner)
    finally:
        db.close()
