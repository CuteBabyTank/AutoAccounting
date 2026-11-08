"""
Usage tracking + page billing: monthly page counts per firm and budget debits.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from functools import cache
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_usage import ApiUsage
from app.models.accounting import AAFile, AAUpload
from app.models.user import User, UserRole


async def get_enterprise_for_user(db: AsyncSession, user: User) -> Optional[User]:
    """Resolve the billing/usage owner for a user.
    Returns the user themselves if enterprise, their parent enterprise if employee,
    None for platform admin or unverified users.
    """
    if user.role == UserRole.ADMIN:
        return None
    if user.role == UserRole.ENTERPRISE:
        return user
    # Employee or unverified: load their parent enterprise
    if user.enterprise_id:
        result = await db.execute(select(User).where(User.id == user.enterprise_id))
        return result.scalar_one_or_none()
    return None


async def get_or_create_usage(db: AsyncSession, enterprise_id, year: int, month: int) -> ApiUsage:
    """Get or create the usage record for an admin in a given month."""
    result = await db.execute(
        select(ApiUsage).execution_options(populate_existing=True).where(
            ApiUsage.enterprise_id == enterprise_id,
            ApiUsage.year == year,
            ApiUsage.month == month,
        )
    )
    usage = result.scalar_one_or_none()
    if usage is None:
        usage = ApiUsage(enterprise_id=enterprise_id, year=year, month=month, pages_used=0)
        db.add(usage)
        await db.flush()
    return usage


async def increment_usage(db: AsyncSession, enterprise_id, page_count: int) -> ApiUsage:
    """Increment page usage for the current month."""
    now = datetime.now(timezone.utc)
    usage = await get_or_create_usage(db, enterprise_id, now.year, now.month)
    usage.pages_used += page_count
    await db.flush()
    return usage


DEFAULT_USAGE_CAP: Optional[int] = None  # default = unlimited (no free-page allowance configured; budget governs billing)


def _effective_cap(user: User) -> Optional[int]:
    """Effective monthly free-page allowance. Pages within this allowance are not
    charged against budget; pages beyond are billable at the effective rate.
    global_usage_cap overrides usage_cap. None = unlimited (display); billing
    proceeds via budget without a free tier."""
    if user.global_usage_cap is not None:
        return user.global_usage_cap
    if user.usage_cap is not None:
        return user.usage_cap
    return DEFAULT_USAGE_CAP


async def _resolve_admin_rate_config(db: AsyncSession) -> tuple[Optional[float], Optional[list]]:
    """Pull platform admin's flat rate + tiers (either may be null)."""
    result = await db.execute(
        select(User.page_rate, User.page_rate_tiers)
        .where(User.role == UserRole.ADMIN)
        .limit(1)
    )
    row = result.first()
    if not row:
        return None, None
    return row[0], row[1]


async def get_effective_rate_config(
    db: AsyncSession, enterprise: User
) -> tuple[Optional[float], Optional[list]]:
    """Resolve enterprise's effective rate config.

    Per-enterprise tiers override per-enterprise flat which override admin's
    tiers which override admin's flat. Returns (flat_rate, tiers), at most
    one of the two is non-null in normal config.
    """
    if enterprise.page_rate_tiers:
        return None, enterprise.page_rate_tiers
    if enterprise.special_page_rate is not None:
        return enterprise.special_page_rate, None
    admin_flat, admin_tiers = await _resolve_admin_rate_config(db)
    if admin_tiers:
        return None, admin_tiers
    return admin_flat, None


async def get_effective_page_rate(db: AsyncSession, enterprise: User) -> Optional[float]:
    """Single-rate compatibility shim. Returns flat rate if configured,
    otherwise the FIRST tier rate (which is the effective rate for sub-cap
    pages). Used as a snapshot fallback for activity logs only; billing
    itself walks the tiers exactly via `charge_for_pages`.
    """
    flat, tiers = await get_effective_rate_config(db, enterprise)
    if flat is not None:
        return flat
    if tiers:
        return tiers[0].get("rate") if isinstance(tiers[0], dict) else None
    return None


def _split_pages_across_tiers(
    pages: int, baseline: int, tiers: list
) -> list[dict]:
    """Allocate `pages` across tiers given a `baseline` of pages already
    consumed BEFORE this slice (per-document, so baseline is normally 0).
    Returns [{rate, pages}]. Adjacent slices at the same rate collapse so the
    breakdown stays compact.
    """
    if pages <= 0 or not tiers:
        return []
    out: list[dict] = []
    cursor = baseline
    remaining = pages
    for t in tiers:
        if remaining <= 0:
            break
        # Each tier may be a Pydantic model OR a plain dict (JSONB load).
        up_to = t.get("up_to") if isinstance(t, dict) else t.up_to
        rate = t.get("rate") if isinstance(t, dict) else t.rate
        if up_to is None:
            take = remaining
        else:
            available = up_to - cursor
            if available <= 0:
                continue
            take = min(remaining, available)
        if take <= 0:
            continue
        if out and out[-1]["rate"] == rate:
            out[-1]["pages"] += take
        else:
            out.append({"rate": float(rate), "pages": int(take)})
        cursor += take
        remaining -= take
    return out


# Above this many DP steps (files x smaller side of the free boundary x log files) the exact reservation would
# hold the firm lock and the owner's row for too long; a closed-form upper bound is used instead.
EXACT_RESERVATION_WORK = 2_000_000


def _max_rate(flat: float | None, tiers: list | None) -> Decimal:
    rates = [t.get("rate") if isinstance(t, dict) else t.rate for t in tiers] if tiers else [flat]
    return max([Decimal(str(r)) for r in rates if r is not None] + [Decimal(0)])


def reservation_upper_bound(page_counts: list[int], free_pages: int, flat: float | None, tiers: list | None) -> float:
    """Never below any completion order's charge: every billable page at the highest rate, plus one centavo
    per file for charge_for_pages' per-file rounding. Billable pages total the same in every order."""
    counts = [max(1, p or 1) for p in page_counts]
    billable = max(0, sum(counts) - max(0, free_pages))
    if not billable or (not tiers and (flat is None or flat <= 0)):
        return 0.0
    cents = (_max_rate(flat, tiers) * billable * 100).to_integral_value(rounding="ROUND_CEILING")
    return float((cents + len(counts)) / 100)


def page_batch_reservation(
    page_counts: list[int], free_pages: int, flat: float | None, tiers: list | None,
) -> float:
    """Maximum actual charge over completion orders, including per-file cent rounding.

    An order has fully free files, at most one partly free file, and fully billable files.
    A subset-sum DP chooses the full files; each possible boundary file is excluded in turn
    using divide-and-conquer knapsack (O(n * min(free, billable) * log(n)), not permutations).
    """
    counts = [max(1, p or 1) for p in page_counts]
    free = max(0, free_pages)
    total = sum(counts)
    billable = max(0, total - free)
    if not billable or (not tiers and (flat is None or flat <= 0)):
        return 0.0

    @cache
    def cents(pages: int) -> int:
        # Keep the same float summation and rounding as charge_for_pages, then use integer cents in the DP.
        amount = (sum(b["rate"] * b["pages"] for b in _split_pages_across_tiers(pages, 0, tiers))
                  if tiers else pages * flat)
        return int(Decimal(str(round(amount, 2))) * 100)

    full = sum(cents(p) for p in counts)
    if free == 0:
        return full / 100
    # Work on the smaller side of the boundary. On the free side maximize negative savings.
    free_side = free < billable
    target = min(free, billable)
    if len(counts) * target * max(1, len(counts).bit_length()) > EXACT_RESERVATION_WORK:
        bound = reservation_upper_bound(counts, free, flat, tiers)
        # The no-free-pages charge also bounds every order when rates are non-negative (fewer pages never cost more).
        rates = [t.get("rate") if isinstance(t, dict) else t.rate for t in tiers] if tiers else [flat]
        return min(bound, full / 100) if all(r is not None and r >= 0 for r in rates) else bound
    best: int | None = None

    def add_files(dp: list[int | None], files: list[int]) -> list[int | None]:
        out = dp.copy()
        for p in files:
            value = -cents(p) if free_side else cents(p)
            for pages in range(target, p - 1, -1):
                prior = out[pages - p]
                if prior is not None and (out[pages] is None or prior + value > out[pages]):
                    out[pages] = prior + value
        return out

    def boundaries(files: list[int], outside: list[int | None]) -> None:
        nonlocal best
        if len(files) == 1:
            p = files[0]
            for part in range(1, min(p, target) + 1):
                prior = outside[target - part]
                if prior is not None:
                    value = cents(p - part) - cents(p) if free_side else cents(part)
                    candidate = prior + value
                    best = candidate if best is None else max(best, candidate)
            return
        mid = len(files) // 2
        left, right = files[:mid], files[mid:]
        boundaries(left, add_files(outside, right))
        boundaries(right, add_files(outside, left))

    boundaries(counts, [0] + [None] * target)
    assert best is not None  # an order always has a boundary while 0 < free < total
    return ((full if free_side else 0) + best) / 100


async def assert_pending_page_budget(db: AsyncSession, enterprise: User) -> None:
    """Reserve admission headroom through durable uncharged AAFile rows, under the firm row lock.

    Caller flushes its accepted/skipped files first and keeps this lock until its audited commit.
    Completion's budget debit and pages_charged flag atomically replace the reservation; errors and
    duplicates release it. No prepaid charge, duplicate debit, or extra schema is needed.
    """
    await db.refresh(enterprise, with_for_update=True)
    flat, tiers = await get_effective_rate_config(db, enterprise)
    if not tiers and (flat is None or flat <= 0):
        return  # billing off = free, even with no budget
    now = datetime.now(timezone.utc)
    usage = await get_or_create_usage(db, enterprise.id, now.year, now.month)
    cap = _effective_cap(enterprise)
    free = max(0, cap - usage.pages_used) if cap is not None else 0
    pages = (await db.execute(select(AAFile.page_count).join(AAUpload, AAUpload.id == AAFile.upload_id).where(
        AAFile.enterprise_id == enterprise.id, AAFile.pages_charged.is_(False),
        AAFile.status.in_(("uploaded", "detected", "extracting")),
        AAUpload.enterprise_id == enterprise.id, AAUpload.status != "failed",
    ))).scalars().all()
    required = await asyncio.to_thread(page_batch_reservation, list(pages), free, flat, tiers)
    if required > (enterprise.budget or 0) or (not pages and (enterprise.budget or 0) <= 0):
        raise ValueError("This batch exceeds the firm's remaining budget after pending uploads. Top up or upload fewer pages.")


async def upload_budget_refusal(db: AsyncSession, enterprise: User) -> str | None:
    """Cheap pre-check before an upload is streamed: billing on, no budget left and no free pages left this
    month means no page could be admitted. Takes no lock and writes nothing; the post-flush reservation
    (``assert_pending_page_budget``) stays the authoritative check."""
    if (enterprise.budget or 0) > 0:
        return None
    flat, tiers = await get_effective_rate_config(db, enterprise)
    if page_batch_reservation([1], 0, flat, tiers) <= 0:
        return None  # billing off (or a free first page)
    cap = _effective_cap(enterprise)
    if cap is not None:
        now = datetime.now(timezone.utc)
        used = (await db.execute(select(ApiUsage.pages_used).where(
            ApiUsage.enterprise_id == enterprise.id, ApiUsage.year == now.year, ApiUsage.month == now.month,
        ))).scalar_one_or_none() or 0
        if cap - used > 0:
            return None
    return "Budget depleted. Contact your administrator to top up before uploading again."


async def charge_for_pages(
    db: AsyncSession, enterprise: User, page_count: int
) -> tuple[int, float, list[dict]]:
    """Compute billable pages (overflow beyond free allowance) for an incoming
    page batch and debit them from enterprise.budget. Must be called BEFORE
    increment_usage so the pre-increment usage is used to compute free remaining.

    Returns (billable_pages, charge_amount, breakdown). Breakdown is a list of
    {rate, pages} entries (one per rate tier touched; single entry for flat).
    """
    if page_count <= 0:
        return 0, 0.0, []
    # Serialize the debit + caller's usage increment/pages_charged commit with upload admission.
    await db.refresh(enterprise, with_for_update=True)
    now = datetime.now(timezone.utc)
    usage = await get_or_create_usage(db, enterprise.id, now.year, now.month)
    cap = _effective_cap(enterprise)
    if cap is None:
        billable = page_count
    else:
        free_remaining = max(0, cap - usage.pages_used)
        billable = max(0, page_count - free_remaining)
    if billable == 0:
        return 0, 0.0, []

    flat, tiers = await get_effective_rate_config(db, enterprise)
    if tiers:
        # Tiers apply per-document: every file walks the tier ladder from 0.
        breakdown = _split_pages_across_tiers(billable, 0, tiers)
        charge = round(sum(b["rate"] * b["pages"] for b in breakdown), 2)
    elif flat is not None and flat > 0:
        breakdown = [{"rate": float(flat), "pages": int(billable)}]
        charge = round(billable * flat, 2)
    else:
        return billable, 0.0, []

    enterprise.budget = max(0.0, round((enterprise.budget or 0.0) - charge, 2))
    await db.flush()
    return billable, charge, breakdown


async def get_usage_stats(db: AsyncSession, enterprise_id) -> dict:
    """Get usage stats for an admin for the current month."""
    result = await db.execute(select(User).where(User.id == enterprise_id))
    enterprise = result.scalar_one_or_none()
    if not enterprise:
        return {}

    now = datetime.now(timezone.utc)
    usage = await get_or_create_usage(db, enterprise_id, now.year, now.month)
    cap = _effective_cap(enterprise)

    return {
        "pages_used": usage.pages_used,
        "usage_cap": enterprise.usage_cap,
        "global_usage_cap": enterprise.global_usage_cap,
        "effective_cap": cap,
        "remaining": max(0, cap - usage.pages_used) if cap is not None else None,
        "year": now.year,
        "month": now.month,
    }
