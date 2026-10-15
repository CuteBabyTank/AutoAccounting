"""Recovery rules for AutoAccounting background jobs (pure).

Jobs run as in-process tasks, so a deploy or instance restart can kill one
mid-run. A running upload that has made no progress for ``STALE_AFTER`` is
treated as dead and failed, which frees its files to be dropped again.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

STALE_AFTER = timedelta(minutes=30)
RUNNING_STATUSES = frozenset({"detecting", "extracting"})


def is_stale_job(status: str, updated_at: datetime, now: datetime) -> bool:
    return status in RUNNING_STATUSES and now - updated_at > STALE_AFTER


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
