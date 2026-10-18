"""Close-checklist templates → tasks for a company and period (pure)."""

from datetime import date

import pytest

from app.services.accounting.compute.checklists import BUILTIN, clean_items, period_label, plan_tasks

ITEMS = [{"title": "Reconcile bank", "notes": "", "offset_days": 5, "priority": "high"},
         {"title": "Close the month", "notes": "After review", "offset_days": 10, "priority": "normal"}]


def test_labels():
    assert period_label("monthly", date(2026, 10, 31), 12) == "Oct 2026"
    assert period_label("quarterly", date(2026, 12, 31), 12) == "Q4 2026"
    assert period_label("quarterly", date(2026, 12, 31), 6) == "Q2 FY2027"
    assert period_label("annual", date(2026, 12, 31), 12) == "FY 2026"


def test_plan_tasks_titles_due_dates_and_period():
    out = plan_tasks(ITEMS, "monthly", date(2026, 10, 31), 12, set())
    assert [(t["title"], t["due_date"], t["priority"]) for t in out] == [
        ("Reconcile bank · Oct 2026", date(2026, 11, 5), "high"),
        ("Close the month · Oct 2026", date(2026, 11, 10), "normal")]
    assert (out[0]["period_year"], out[0]["period_quarter"], out[1]["notes"]) == (2026, 4, "After review")


def test_annual_checklist_is_the_year_and_reapply_skips_existing():
    out = plan_tasks(ITEMS, "annual", date(2026, 12, 31), 12, {"reconcile bank · fy 2026"})
    assert [t["title"] for t in out] == ["Close the month · FY 2026"] and out[0]["period_quarter"] == 0


def test_clean_items():
    assert clean_items([{"title": "  A  ", "offset_days": "3"}]) == [
        {"title": "A", "notes": "", "offset_days": 3, "priority": "normal"}]
    for bad in ([], [{"title": " "}], [{"title": "A", "offset_days": 400}], [{"title": "A"}] * 51,
                [{"title": "A", "priority": "urgent"}]):
        with pytest.raises(ValueError):
            clean_items(bad)


def test_builtins_are_valid():
    for t in BUILTIN.values():
        assert clean_items(t["items"]) and t["cadence"] in ("monthly", "quarterly", "annual")
