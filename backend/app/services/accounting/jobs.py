"""Recovery rules for AutoAccounting background jobs (pure).

Jobs run as in-process tasks, so a deploy or instance restart can kill one
mid-run (on Cloud Run, also an instance scaled in while its CPU was throttled).
A running upload that has made no progress for ``STALE_AFTER`` is treated as
dead: it is resumed where it stopped while younger than ``RESUME_WITHIN``, and
failed after that (which frees its files to be dropped again), so an upload
that keeps killing its job can't retry forever.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

STALE_AFTER = timedelta(minutes=30)
RESUME_WITHIN = timedelta(hours=24)
RUNNING_STATUSES = frozenset({"detecting", "extracting"})


def is_stale_job(status: str, updated_at: datetime, now: datetime) -> bool:
    return status in RUNNING_STATUSES and now - updated_at > STALE_AFTER


def stale_action(status: str, created_at: datetime, updated_at: datetime, now: datetime) -> str | None:
    """"resume" or "fail" for a dead job, None while it is alive or finished."""
    if not is_stale_job(status, updated_at, now):
        return None
    return "resume" if now - created_at <= RESUME_WITHIN else "fail"


class JobSlots:
    """Per-instance job scheduler: at most ``total`` jobs at once, one per firm.

    A firm's 1,000-file drop holds a single slot, so other firms' drops start
    as soon as any slot frees instead of queueing behind it.
    """

    def __init__(self, total: int) -> None:
        self._total = asyncio.Semaphore(total)
        # firm -> (lock, number of jobs holding or waiting on it)
        self._per_firm: dict[str, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def slot(self, firm: str) -> AsyncIterator[None]:
        lock, users = self._per_firm.get(firm, (asyncio.Lock(), 0))
        self._per_firm[firm] = (lock, users + 1)
        try:
            async with lock:
                async with self._total:
                    yield
        finally:
            lock, users = self._per_firm[firm]
            if users <= 1:
                del self._per_firm[firm]
            else:
                self._per_firm[firm] = (lock, users - 1)
