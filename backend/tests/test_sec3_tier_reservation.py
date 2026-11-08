"""Reservation admission must match the maximum bill from the real per-file debit path."""
import uuid
from decimal import Decimal
from itertools import permutations

import pytest

from app.models.accounting import AAFile
from app.models.api_usage import ApiUsage
from app.models.user import User
from app.services import usage_service as billing


class Rows:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    def scalars(self) -> "Rows":
        return self

    def all(self) -> list:
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class BillingDb:
    def __init__(self, pages: list[int]) -> None:
        self.pages = pages
        self.usage = ApiUsage(pages_used=0)

    async def refresh(self, row: User, **kwargs) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def execute(self, stmt) -> Rows:
        return Rows(self.pages if stmt.column_descriptions[0]["entity"] is AAFile else [self.usage])


async def test_tier_admission_accepts_batch_whose_worst_completion_order_fits_budget() -> None:
    owner = User(id=uuid.uuid4(), page_rate_tiers=[{"up_to": 1, "rate": 10}, {"up_to": None, "rate": 1}],
                 budget=15, usage_cap=198, global_usage_cap=None)
    db = BillingDb([100, 100])
    await billing.assert_pending_page_budget(db, owner)
    assert billing.page_batch_reservation([100, 100], 198, None, owner.page_rate_tiers) == 11
    for p in db.pages:
        await billing.charge_for_pages(db, owner, p)
        await billing.increment_usage(db, owner.id, p)
    assert owner.budget == 4 and db.usage.pages_used == 200


async def test_tier_admission_still_refuses_budget_below_the_worst_completion_order() -> None:
    owner = User(id=uuid.uuid4(), page_rate_tiers=[{"up_to": 2, "rate": 3}, {"up_to": None, "rate": 1}],
                 budget=5.50, usage_cap=3, global_usage_cap=None)
    with pytest.raises(ValueError, match="budget"):
        await billing.assert_pending_page_budget(BillingDb([1, 4]), owner)
    assert owner.budget == 5.50


@pytest.mark.parametrize("counts,free,tiers", [
    ([1, 4], 3, [{"up_to": 2, "rate": 3}, {"up_to": None, "rate": 1}]),
    ([2, 3, 6], 4, [{"up_to": 2, "rate": 1}, {"up_to": None, "rate": 5}]),
    ([2, 5, 7], 6, [{"up_to": 2, "rate": 4}, {"up_to": 4, "rate": 1}, {"up_to": None, "rate": 3}]),
    ([1, 2, 3], 2, [{"up_to": None, "rate": 0.005}]),
    ([3, 5, 7], 8, [{"up_to": 2, "rate": 0.015}, {"up_to": None, "rate": 0.001}]),
])
async def test_reservation_equals_maximum_real_charge_over_completion_orders(
    counts: list[int], free: int, tiers: list[dict],
) -> None:
    charges = []
    for order in permutations(counts):
        owner = User(id=uuid.uuid4(), page_rate_tiers=tiers, usage_cap=free, global_usage_cap=None, budget=1000)
        db = BillingDb(counts)
        total = Decimal(0)
        for p in order:
            _, charge, _ = await billing.charge_for_pages(db, owner, p)
            total += Decimal(str(charge))
            await billing.increment_usage(db, owner.id, p)
        charges.append(total)
    assert Decimal(str(billing.page_batch_reservation(counts, free, None, tiers))) == max(charges)
