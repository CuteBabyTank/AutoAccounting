"""Daily assistant allowances and additive usage counters; days follow Manila."""

import math
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.accounting import AAAssistantUsage

MANILA = ZoneInfo("Asia/Manila")
COUNTERS = ("turns", "calls", "prompt_tokens", "completion_tokens", "cached_tokens")
CAP_MESSAGES = {
    "firm": "Your firm has used today's assistant allowance. It resets at midnight Manila time.",
    "user": "You have used today's assistant allowance. It resets at midnight Manila time.",
}


def today() -> date:
    return datetime.now(MANILA).date()


def seconds_to_midnight(now: datetime | None = None) -> int:
    local = (now or datetime.now(MANILA)).astimezone(MANILA)
    midnight = datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=MANILA)
    return max(1, math.ceil((midnight - local).total_seconds()))


def cap_reason(firm: int, user: int, firm_cap: int, user_cap: int) -> str | None:
    if firm_cap and firm >= firm_cap:
        return "firm"
    if user_cap and user >= user_cap:
        return "user"
    return None


class PlatformUsage:
    # Per instance; production runs at most one instance. Restarts reset this safety cap.
    def __init__(self) -> None:
        self.day: date | None = None
        self.tokens = 0

    def _reset(self, day: date) -> None:
        if self.day != day:
            self.day, self.tokens = day, 0

    def limited(self, day: date) -> bool:
        self._reset(day)
        cap = settings.assistant_platform_daily_tokens
        return bool(cap and self.tokens >= cap)

    def add(self, totals: dict, day: date) -> None:
        self._reset(day)
        self.tokens += totals.get("prompt", 0) + totals.get("completion", 0)


platform = PlatformUsage()


def token_total(totals: dict) -> int:
    # Cached input is already included in prompt_tokens.
    return totals["prompt_tokens"] + totals["completion_tokens"]


async def daily(db: AsyncSession, ent: uuid.UUID, user_id: uuid.UUID, day: date) -> dict:
    columns = [func.coalesce(func.sum(getattr(AAAssistantUsage, key)), 0).label(key) for key in COUNTERS]
    query = select(*columns).where(AAAssistantUsage.enterprise_id == ent, AAAssistantUsage.day == day)
    firm = (await db.execute(query)).mappings().one()
    person = (await db.execute(query.where(AAAssistantUsage.user_id == user_id))).mappings().one()
    # SUM over BIGINT is NUMERIC in Postgres: plain ints for JSON.
    return {"firm": {k: int(v) for k, v in firm.items()}, "user": {k: int(v) for k, v in person.items()}}


async def record(db: AsyncSession, ent: uuid.UUID, user_id: uuid.UUID, day: date, totals: dict) -> None:
    statement = insert(AAAssistantUsage).values(
        enterprise_id=ent, user_id=user_id, day=day, turns=1, calls=totals["calls"],
        prompt_tokens=totals["prompt"], completion_tokens=totals["completion"], cached_tokens=totals["cached"],
    )
    await db.execute(statement.on_conflict_do_update(
        index_elements=["enterprise_id", "user_id", "day"],
        set_={**{key: getattr(AAAssistantUsage, key) + getattr(statement.excluded, key) for key in COUNTERS},
              "updated_at": func.now()},
    ))


async def report(db: AsyncSession, days: int) -> list[dict]:
    end = today()
    rows = await db.execute(select(
        AAAssistantUsage.enterprise_id, AAAssistantUsage.day,
        *(func.sum(getattr(AAAssistantUsage, key)).label(key) for key in COUNTERS),
    ).where(AAAssistantUsage.day.between(end - timedelta(days=days - 1), end))
      .group_by(AAAssistantUsage.enterprise_id, AAAssistantUsage.day)
      .order_by(AAAssistantUsage.day.desc(), AAAssistantUsage.enterprise_id))
    return [dict(row) for row in rows.mappings()]
