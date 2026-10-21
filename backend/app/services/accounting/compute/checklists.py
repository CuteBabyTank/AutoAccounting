"""Close-checklist templates (pure): the steps of a monthly / quarterly / annual close, turned into tasks for one
company and period. Re-applying to the same period skips steps whose task already exists (same title)."""

from datetime import date, timedelta

from app.services.accounting.periods import period_for

CADENCES = ("monthly", "quarterly", "annual")
PRIORITIES = ("low", "normal", "high")
MAX_ITEMS = 50

BUILTIN: dict[str, dict] = {
    "builtin:monthly-close": {"name": "Monthly close", "cadence": "monthly", "items": [
        {"title": "Collect the client's receipts, invoices and bank statement", "offset_days": 3, "priority": "high"},
        {"title": "Clear the review queue", "offset_days": 5},
        {"title": "Match and reconcile the bank accounts", "offset_days": 7},
        {"title": "Post accruals and recurring entries", "offset_days": 7},
        {"title": "Check A/R and A/P aging; follow up old items", "offset_days": 8},
        {"title": "Review the trial balance and health check", "offset_days": 9},
        {"title": "Close the month in Books", "offset_days": 10, "priority": "high"},
    ]},
    "builtin:quarter-close": {"name": "Quarter close", "cadence": "quarterly", "items": [
        {"title": "Close the quarter's three months in Books", "offset_days": 10, "priority": "high"},
        {"title": "Review VAT / percentage tax and withholding for the quarter", "offset_days": 15},
        {"title": "Generate the quarter's returns and check the 2307s", "offset_days": 18},
        {"title": "Send outgoing 2307s and chase 2307s to receive", "offset_days": 20},
        {"title": "Generate the management pack for the client", "offset_days": 25},
    ]},
}


def clean_items(items: list[dict]) -> list[dict]:
    """Validated steps (raises ValueError): 1–50, each with a title, offset −60…365 days, a known priority."""
    if not items:
        raise ValueError("Add at least one step")
    if len(items) > MAX_ITEMS:
        raise ValueError(f"A checklist has at most {MAX_ITEMS} steps")
    out = []
    for raw in items:
        title = str(raw.get("title") or "").strip()
        if not title:
            raise ValueError("Every step needs a title")
        try:
            offset = int(raw.get("offset_days") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"{title}: days after the period end must be a whole number") from None
        if not -60 <= offset <= 365:
            raise ValueError(f"{title}: due between 60 days before and 365 days after the period end")
        priority = raw.get("priority") or "normal"
        if priority not in PRIORITIES:
            raise ValueError(f"{title}: unknown priority {priority!r}")
        out.append({"title": title[:150], "notes": str(raw.get("notes") or "").strip()[:2000], "offset_days": offset,
                    "priority": priority})
    return out


def period_label(cadence: str, period_end: date, fye: int) -> str:
    where = period_for(period_end, fye)
    if cadence == "monthly":
        return f"{period_end:%b %Y}"
    if cadence == "quarterly":
        return f"Q{where.quarter} {where.fiscal_year}" if fye == 12 else f"Q{where.quarter} FY{where.fiscal_year}"
    return f"FY {where.fiscal_year}"


def plan_tasks(items: list[dict], cadence: str, period_end: date, fye: int, existing_titles: set[str]) -> list[dict]:
    """Task values for each step not already there (``existing_titles`` lower-cased)."""
    label = period_label(cadence, period_end, fye)
    where = period_for(period_end, fye)
    out = []
    for item in clean_items(items):
        title = f"{item['title']} · {label}"
        if title.lower() in existing_titles:
            continue
        out.append({"title": title, "notes": item["notes"], "priority": item["priority"],
                    "due_date": period_end + timedelta(days=item["offset_days"]), "period_year": where.fiscal_year,
                    "period_quarter": 0 if cadence == "annual" else where.quarter})
    return out
