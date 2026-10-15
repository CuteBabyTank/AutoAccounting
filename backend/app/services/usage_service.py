"""
Usage tracking + page billing: monthly page counts per firm and budget debits.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_usage import ApiUsage
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
    # Employee or unverified — load their parent enterprise
    if user.enterprise_id:
        result = await db.execute(select(User).where(User.id == user.enterprise_id))
        return result.scalar_one_or_none()
    return None


async def get_or_create_usage(db: AsyncSession, enterprise_id, year: int, month: int) -> ApiUsage:
    """Get or create the usage record for an admin in a given month."""
    result = await db.execute(
        select(ApiUsage).where(
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
    global_usage_cap overrides usage_cap. None = unlimited (display) — billing
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
    tiers which override admin's flat. Returns (flat_rate, tiers) — at most
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
    pages). Used as a snapshot fallback for activity logs only — billing
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
