"""Upload budget pre-check before streaming, bounded reservation time, and audited failed-job cleanup."""

import random
import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.accounting import AAAuditEvent
from app.models.user import User, UserRole
from app.routers import accounting
from app.services import usage_service
from app.services.accounting import pipeline
from tests.test_sec3_failed_reservations import FailureDB
from tests.test_sec3_job_boundaries import session_factory


class NoQueries:
    """The pre-check needs nothing from the DB for a firm with its own rate and no free-page cap."""

    async def execute(self, stmt):
        raise AssertionError("no query expected")


def _firm(budget: float, cap: int | None = None) -> User:
    return User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, budget=budget, special_page_rate=2.0,
                page_rate_tiers=None, usage_cap=cap, global_usage_cap=None)


async def test_empty_budget_is_refused_before_any_file_is_streamed(monkeypatch):
    async def never(*args, **kwargs):
        raise AssertionError("the upload must not be streamed or compressed")

    monkeypatch.setattr(accounting, "stream_upload", never)
    with pytest.raises(HTTPException) as error:
        await accounting.create_upload([SimpleNamespace(filename="a.pdf")], company_id=None, shrunk=[],
                                       user=_firm(0.0), db=NoQueries())
    assert error.value.status_code == 402 and "Budget depleted" in error.value.detail


async def test_precheck_allows_billing_off_budget_left_or_free_pages_left():
    off = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, budget=0.0, special_page_rate=None, page_rate_tiers=None,
               usage_cap=None, global_usage_cap=None)

    class AdminRate:  # billing off: the platform owner set no rate either
        async def execute(self, stmt):
            return SimpleNamespace(first=lambda: (None, None))

    assert await usage_service.upload_budget_refusal(AdminRate(), off) is None
    assert await usage_service.upload_budget_refusal(NoQueries(), _firm(5.0)) is None

    class Usage:
        def __init__(self, used):
            self.used = used

        async def execute(self, stmt):
            return SimpleNamespace(scalar_one_or_none=lambda: self.used)

    assert await usage_service.upload_budget_refusal(Usage(10), _firm(0.0, cap=50)) is None
    assert await usage_service.upload_budget_refusal(Usage(50), _firm(0.0, cap=50))


@pytest.mark.parametrize("seed", range(40))
def test_closed_form_bound_never_under_reserves(seed):
    rng = random.Random(seed)
    counts = [rng.randint(1, 12) for _ in range(rng.randint(1, 14))]
    free = rng.randint(0, sum(counts) + 3)
    tiers = [{"up_to": 3, "rate": 1.37}, {"up_to": 8, "rate": 0.91}, {"up_to": None, "rate": 0.333}]
    for flat, tier in ((0.777, None), (None, tiers)):
        exact = usage_service.page_batch_reservation(counts, free, flat, tier)
        assert usage_service.reservation_upper_bound(counts, free, flat, tier) >= exact


def test_large_reservation_is_bounded_in_time_and_still_conservative():
    counts = [((i * 7) % 9) + 1 for i in range(2000)]
    tiers = [{"up_to": 3, "rate": 1.5}, {"up_to": None, "rate": 0.5}]
    started = time.perf_counter()
    reserved = usage_service.page_batch_reservation(counts, 5_000, None, tiers)
    assert time.perf_counter() - started < 0.5
    billable = sum(counts) - 5_000
    assert billable > 1000
    assert reserved >= billable * 0.5  # at least the cheapest possible charge
    assert reserved <= usage_service.reservation_upper_bound(counts, 5_000, None, tiers)


@pytest.mark.parametrize("bind_fails", [False, True])
async def test_failed_job_cleanup_is_audited_and_survives_a_failing_firm_binding(monkeypatch, tmp_path, bind_fails):
    db = FailureDB(str(tmp_path / "receipt.jpg"))
    db.file.status = "extracting"
    real_bind = pipeline._bind_job_firm

    async def job(*args):
        raise RuntimeError("reader crashed")

    async def broken_bind(session, firm_id):
        raise ValueError("Upload firm owner is missing or invalid")

    if bind_fails:
        monkeypatch.setattr(pipeline, "_bind_job_firm", broken_bind)
    try:
        with session_factory(monkeypatch, db):
            await pipeline._guarded(job, db.upload.id, str(db.actor.id), db.owner.id)
        assert db.upload.status == "failed" and db.file.status == "error" and db.file.error_message
        events = [e for e in db.events if isinstance(e, AAAuditEvent)]
        assert [e.action for e in events] == ["fail"]
        assert events[0].entity == "upload" and events[0].enterprise_id == db.owner.id
        assert events[0].after["status"] == "failed"
    finally:
        monkeypatch.setattr(pipeline, "_bind_job_firm", real_bind)
        db.close()
