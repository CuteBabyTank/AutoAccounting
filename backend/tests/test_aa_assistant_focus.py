"""The company the person confirmed ("Is this about …? Yes") becomes the default for company lookups."""

import uuid
from types import SimpleNamespace

from app.services.accounting.assistant import tools


async def test_no_company_named_uses_the_confirmed_company():
    focus = SimpleNamespace(id=uuid.uuid4(), registered_name="Bayanihan Hardware Trading Corp.")
    ctx = tools.Ctx(db=None, user=SimpleNamespace(id=uuid.uuid4()), ent=uuid.uuid4(), focus=focus)
    assert await tools.resolve_company(ctx, None) is focus
    assert await tools.resolve_company(ctx, "") is focus


async def test_without_focus_nothing_is_assumed(monkeypatch):
    ctx = tools.Ctx(db=None, user=SimpleNamespace(id=uuid.uuid4()), ent=uuid.uuid4())
    assert ctx.focus is None


def test_calendar_spells_out_this_and_next_week():
    from datetime import date
    from app.services.accounting.assistant.prompt import calendar
    text = calendar(date(2026, 11, 4))  # a Wednesday
    assert text.startswith("Wednesday. Tomorrow = 2026-11-05.")
    assert "Fri 2026-11-06" in text.split("Next week")[0]   # this Friday
    assert "Fri 2026-11-13" in text.split("Next week")[1]   # next Friday
    assert "Rest of this week: none" in calendar(date(2026, 11, 8))  # a Sunday


def test_relative_due_dates_follow_the_persons_words():
    from datetime import date
    from app.services.accounting.assistant import guard
    wed = date(2026, 11, 4)
    assert guard.relative_due("Remind me next Friday", wed) == date(2026, 11, 13)
    assert guard.relative_due("Remind me this Friday", wed) == date(2026, 11, 6)
    assert guard.relative_due("call the BIR tomorrow", wed) == date(2026, 11, 5)
    assert guard.relative_due("by Friday", wed) is None
    assert guard.relative_due("move it from this Friday to next Friday", wed) is None  # two dates: model decides
    args = guard.fix_due_date("propose_create_task", {"title": "x", "due_date": "2026-11-06"}, "next Friday", wed)
    assert args["due_date"] == "2026-11-13"
    upd = guard.fix_due_date("propose_update_task", {"task": "x", "changes": {"due_date": "2026-11-06"}},
                             "push it to next Friday", wed)
    assert upd["changes"]["due_date"] == "2026-11-13"
    assert guard.fix_due_date("report", {"start": "x"}, "next Friday", wed) == {"start": "x"}


def test_filing_labels_read_like_the_board():
    from app.services.accounting.assistant.actions import filing_label
    assert filing_label("1601C-M1", 2026, 4) == "1601-C for October 2026"
    assert filing_label("0619E-M2", 2026, 3) == "0619-E for August 2026"
    assert filing_label("2550Q", 2026, 3) == "2550-Q for Q3 2026"
    assert filing_label("1702RT", 2026, 0) == "1702-RT for 2026"
    # Fiscal year 2027 ending June: Q1 = July to September 2026.
    assert filing_label("1601C-M1", 2027, 1, fye_month=6) == "1601-C for July 2026"
    assert filing_label("1601C-M3", 2027, 2, fye_month=6) == "1601-C for December 2026"
