"""Detection records which file was active, and caps crash recovery."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.sql.elements import TextClause

from app.models.accounting import AAUpload
from app.models.user import User, UserRole
from app.routers import accounting
from app.services.accounting import jobs, pipeline


@pytest.mark.parametrize("cancel", [False, True, None], ids=["unreadable", "interrupted", "already_capped"])
async def test_detection_claim_is_durable_before_reading(monkeypatch, cancel):
    upload = SimpleNamespace(id=uuid.uuid4(), enterprise_id=uuid.uuid4(), processed_files=0)
    file = SimpleNamespace(id=uuid.uuid4(), stored_path="unused", file_type="pdf", page_count=1,
                           status="uploaded", interrupts=0, detection=None)
    results = iter([[], [file]])
    committed = []

    async def execute(statement, params=None):
        if isinstance(statement, TextClause):
            assert params == {"uid": str(upload.enterprise_id)}
            return None
        rows = next(results)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    async def get(model, ident):
        if model is User:
            return SimpleNamespace(id=upload.enterprise_id, role=UserRole.ENTERPRISE)
        return upload if model is AAUpload else file

    async def commit():
        committed.append((file.status, file.detection))

    db = SimpleNamespace(get=get, execute=execute, commit=commit, sync_session=SimpleNamespace(info={}))

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return None

    async def read(*args):
        assert committed[-1] == ("uploaded", {"_in_progress": True})
        if cancel:
            # Cancellation simulates termination before the result can be committed.
            raise asyncio.CancelledError
        raise ValueError("Page unavailable: render timed out")

    monkeypatch.setattr(pipeline, "async_session", Session)
    monkeypatch.setattr(pipeline, "_first_page", read)
    if cancel is None:
        file.interrupts = jobs.MAX_INTERRUPTS
        await pipeline.run_detection(upload.id, str(uuid.uuid4()), upload.enterprise_id)
        assert file.status == "error" and file.error_message == jobs.INTERRUPTED_MESSAGE
    elif cancel:
        with pytest.raises(asyncio.CancelledError):
            await pipeline.run_detection(upload.id, str(uuid.uuid4()), upload.enterprise_id)
        assert file.status == "uploaded" and file.detection == {"_in_progress": True}
    else:
        reader = AsyncMock()
        monkeypatch.setattr(pipeline.aa_gemini, "call_gemini_raw", reader)
        await pipeline.run_detection(upload.id, str(uuid.uuid4()), upload.enterprise_id)
        assert file.status == "detected" and "Page unavailable" in file.detection["error"]
        reader.assert_not_awaited()


@pytest.mark.parametrize("interrupts", [0, jobs.MAX_INTERRUPTS - 1])
async def test_stale_detection_counts_only_active_file_and_stops_at_cap(monkeypatch, interrupts):
    now = datetime.now(timezone.utc)
    upload = SimpleNamespace(id=uuid.uuid4(), enterprise_id=uuid.uuid4(), uploaded_by=uuid.uuid4(),
                             status="detecting", created_at=now - timedelta(hours=1),
                             updated_at=now - jobs.STALE_AFTER - timedelta(seconds=1),
                             total_files=1, processed_files=0, preselected_company_id=None)
    file = SimpleNamespace(id=uuid.uuid4(), status="uploaded", interrupts=interrupts, error_message=None,
                           detection={"_in_progress": True})
    waiting = SimpleNamespace(id=uuid.uuid4(), status="uploaded", interrupts=0, error_message=None, detection=None)
    files = [file, waiting] if interrupts == 0 else [file]
    results = iter([SimpleNamespace(scalar_one_or_none=lambda: upload),
                    SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: files)),
                    SimpleNamespace(rowcount=1)])
    db = SimpleNamespace(execute=AsyncMock(side_effect=lambda statement: next(results)), commit=AsyncMock())
    events = []
    monkeypatch.setattr(accounting.pipeline, "is_running", lambda ident: False)
    monkeypatch.setattr(accounting.pipeline, "resume", lambda *args: events.append("resume"))
    monkeypatch.setattr(accounting.audit, "record", lambda *args, **kwargs: events.append("audit"))
    monkeypatch.setattr(accounting.UploadFileOut, "model_validate", lambda row: row)
    monkeypatch.setattr(accounting, "UploadOut", lambda **kwargs: SimpleNamespace(**kwargs))
    await accounting._upload_out(db, upload.enterprise_id, upload.id)
    assert file.interrupts == interrupts + 1
    assert file.detection is None
    assert "audit" in events
    if interrupts + 1 == jobs.MAX_INTERRUPTS:
        assert file.status == "error" and file.error_message == jobs.INTERRUPTED_MESSAGE
        assert upload.status == "failed" and "resume" not in events
    else:
        assert file.status == "uploaded" and "resume" in events
        assert waiting.status == "uploaded" and waiting.interrupts == 0

