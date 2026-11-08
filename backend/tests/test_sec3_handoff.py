"""Bound employee preview echoes and re-admit retried pages before extraction."""

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, UploadFile

from app.models.accounting import AACompany, AAFile
from app.models.user import User, UserRole
from app.routers import accounting, accounting_employees
from app.services import usage_service as billing


@pytest.mark.parametrize("row_count", [2, 7])
async def test_employee_preview_bounds_cells_and_rows(monkeypatch, row_count):
    company_id = uuid.uuid4()
    owner = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ENTERPRISE)
    company = SimpleNamespace(payroll_mapping={})
    monkeypatch.setattr(accounting_employees, "company_or_404", AsyncMock(return_value=company))
    cells = ["A" * 2000, "B" * 201, "C" * 200, "Short", ""]
    data = "Last name,First name,Middle name,Address,TIN\n" + (",".join(cells) + "\n") * row_count
    file = UploadFile(filename="employees.csv", file=io.BytesIO(data.encode()))

    preview = await accounting_employees.preview_import(company_id, 2026, file, user=owner, db=object())

    assert preview.rows == row_count
    assert len(preview.sample) == min(row_count, 5)
    for row in preview.sample:
        assert row == ["A" * 199 + "…", "B" * 199 + "…", "C" * 200, "Short", ""]
    assert preview.headers == ["Last name", "First name", "Middle name", "Address", "TIN"]


@pytest.mark.parametrize(
    "flat,budget,pending_pages,refused",
    [(1.0, 10.0, [3], True), (1.0, 10.0, [2], False), (None, 0.0, [3], False)],
    ids=["pending-and-retried-pages-exceed-budget", "exact-budget", "billing-off"],
)
async def test_retry_admits_flushed_pages_under_firm_lock(
    monkeypatch, flat, budget, pending_pages, refused,
):
    owner = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ENTERPRISE, budget=budget,
                            usage_cap=None, global_usage_cap=None)
    upload_id = uuid.uuid4()
    file = SimpleNamespace(id=uuid.uuid4(), company_id=uuid.uuid4(), page_count=8,
                           status="error", error_message="Reader unavailable", original_filename="dummy.pdf")
    events = []

    class DB:
        locked = False
        stored_status = "error"

        async def execute(self, stmt):
            if getattr(stmt, "is_update", False):
                assert self.locked
                return SimpleNamespace(rowcount=1)
            column = stmt.column_descriptions[0]
            if column["entity"] is User:
                assert stmt._for_update_arg is not None
                assert owner.id in stmt.compile().params.values()
                self.locked = True
                events.append("lock")
                return None
            assert self.locked
            if column["entity"] is AACompany:
                return SimpleNamespace(first=lambda: None)
            assert column["entity"] is AAFile
            if column["name"] == "page_count":
                events.append("budget")
                pages = pending_pages + ([file.page_count] if self.stored_status == "uploaded" else [])
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: pages))
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [file]))

        async def refresh(self, row, **kwargs):
            assert self.locked and row is owner
            assert kwargs == {"with_for_update": True}

        async def flush(self):
            assert self.locked
            self.stored_status = file.status
            events.append("flush")

        async def commit(self):
            assert self.stored_status == "uploaded"
            events.append("commit")

    monkeypatch.setattr(billing, "get_effective_rate_config", AsyncMock(return_value=(flat, None)))
    monkeypatch.setattr(billing, "get_or_create_usage", AsyncMock(return_value=SimpleNamespace(pages_used=0)))
    monkeypatch.setattr(accounting.audit, "record", lambda *args, **kwargs: events.append("audit"))
    extraction = Mock(side_effect=lambda *args: events.append("extract"))
    monkeypatch.setattr(accounting.pipeline, "start_extraction", extraction)
    result = object()
    monkeypatch.setattr(accounting, "_upload_out", AsyncMock(return_value=result))
    db = DB()

    if refused:
        with pytest.raises(HTTPException) as error:
            await accounting.retry_upload(upload_id, user=owner, db=db)
        assert error.value.status_code == 402
        assert "budget" in error.value.detail.lower()
        assert events == ["lock", "flush", "budget"]
        extraction.assert_not_called()
    else:
        assert await accounting.retry_upload(upload_id, user=owner, db=db) is result
        admission = ["budget"] if flat else []
        assert events == ["lock", "flush", *admission, "audit", "commit", "extract"]
        extraction.assert_called_once_with(upload_id, str(owner.id), owner.id)
        assert file.status == "uploaded" and file.error_message is None
    assert owner.budget == budget  # Admission reserves headroom without charging again.
