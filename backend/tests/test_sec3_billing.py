"""Documents, page charges and monthly usage belong to the same firm."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.sql.elements import TextClause

from app.models.accounting import AACompany, AAFile, AAUpload
from app.models.user import User, UserRole
from app.services.accounting import pipeline


def _extraction(monkeypatch, moved: bool):
    owner = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, is_active=True)
    other = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, is_active=True)
    uploader = User(id=uuid.uuid4(), role=UserRole.EMPLOYEE if moved else UserRole.UNVERIFIED,
                    enterprise_id=other.id if moved else None)
    upload = SimpleNamespace(id=uuid.uuid4(), enterprise_id=owner.id, uploaded_by=uploader.id,
                             total_files=1, processed_files=0, status="extracting")
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=owner.id, registered_name="Firm A client",
                              tin="123456789", business_type="services")
    file = SimpleNamespace(id=uuid.uuid4(), company_id=company.id, stored_path="unused", file_type="pdf",
                           page_count=5, sha256="a" * 64, pages_charged=False)
    users = {owner.id: owner, other.id: other, uploader.id: uploader}
    added = []
    results = iter([[file], [company], [], [], []])

    async def get(model, ident):
        if model is User:
            return users.get(ident)
        assert db.sync_session.info["rls_user_id"] == str(owner.id)
        return {AAUpload: upload, AAFile: file, AACompany: company}[model]

    async def execute(statement, params=None):
        if isinstance(statement, TextClause):
            assert params == {"uid": str(owner.id)}
            return None
        # The old resolver follows the uploader's new membership using this query.
        if getattr(statement, "column_descriptions", [{}])[0].get("entity") is User:
            return SimpleNamespace(scalar_one_or_none=lambda: other)
        rows = next(results)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows), all=lambda: rows)

    db = SimpleNamespace(get=get, execute=execute, commit=AsyncMock(), flush=AsyncMock(), rollback=AsyncMock(),
                         add_all=added.extend, sync_session=SimpleNamespace(info={}))

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(pipeline, "async_session", Session)
    monkeypatch.setattr(pipeline, "company_profile", lambda company: object())
    monkeypatch.setattr(pipeline, "extract_prompt", lambda *args: "prompt")
    monkeypatch.setattr(pipeline, "_locked_charts", AsyncMock(return_value={}))
    monkeypatch.setattr(pipeline, "_claim_file", AsyncMock(return_value=True))
    monkeypatch.setattr(pipeline, "_read_file", AsyncMock(return_value=[(0, 5, [{}])]))
    monkeypatch.setattr(pipeline, "classify_document", lambda *args: {"doc_type": "invoice"})
    monkeypatch.setattr(pipeline, "mark_duplicates", lambda *args: set())
    monkeypatch.setattr(pipeline, "relink_receipts", AsyncMock())
    monkeypatch.setattr(pipeline.duplicates, "refresh_flags", AsyncMock())
    monkeypatch.setattr(pipeline.bank, "rematch", AsyncMock())
    monkeypatch.setattr(pipeline, "charge_for_pages", AsyncMock())
    monkeypatch.setattr(pipeline, "increment_usage", AsyncMock())
    return db, upload, file, owner, users, added


@pytest.mark.parametrize("moved,admin_scope", [(False, False), (True, False), (True, True)],
                         ids=["uploader_removed", "uploader_moved", "admin_owned_scope"])
async def test_extraction_bills_upload_owner_after_membership_change(monkeypatch, moved, admin_scope):
    db, upload, file, owner, users, added = _extraction(monkeypatch, moved)
    if admin_scope:
        owner.role = UserRole.ADMIN
    await pipeline.run_extraction(upload.id, str(upload.uploaded_by), owner.id)
    assert len(added) == 1 and added[0].enterprise_id == owner.id
    assert file.status == "extracted"
    if admin_scope:
        pipeline.charge_for_pages.assert_not_awaited()
        pipeline.increment_usage.assert_not_awaited()
        assert not file.pages_charged
    else:
        pipeline.charge_for_pages.assert_awaited_once_with(db, owner, 5)
        pipeline.increment_usage.assert_awaited_once_with(db, owner.id, 5)
        assert file.pages_charged


@pytest.mark.parametrize("invalid", [None, UserRole.EMPLOYEE, UserRole.UNVERIFIED])
async def test_missing_or_invalid_upload_owner_is_an_error(monkeypatch, invalid):
    db, upload, file, owner, users, added = _extraction(monkeypatch, False)
    if invalid is None:
        del users[owner.id]
    else:
        owner.role = invalid
    with pytest.raises(ValueError, match="firm owner"):
        await pipeline.run_extraction(upload.id, str(upload.uploaded_by), owner.id)
    assert not added and not file.pages_charged
    pipeline.charge_for_pages.assert_not_awaited()
    pipeline.increment_usage.assert_not_awaited()

