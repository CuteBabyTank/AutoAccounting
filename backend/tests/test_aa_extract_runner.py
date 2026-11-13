from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.accounting.extract import builtins, formats, runner
from app.services.accounting.jobs import INTERRUPTED_MESSAGE, MAX_INTERRUPTS

SNAP = {"name": "Receipt", "fields": builtins.BUILTINS["receipt"]["fields"],
        "checks": builtins.BUILTINS["receipt"]["checks"]}
TODAY = date(2026, 11, 13)


def values(**header):
    base = {f["key"]: "" for f in SNAP["fields"] if f["scope"] == "header"}
    base.update(header)
    return {"header": base, "rows": []}


def test_run_status():
    assert runner.run_status(["done", "reading"]) == "reading"
    assert runner.run_status(["done", "choose", "error"]) == "done"
    assert runner.run_status(["error", "error"]) == "failed"
    assert runner.run_status([]) == "done"


def test_edit_fixes_a_red_total_and_marks_the_cell():
    # Explicit zeros: Task 3's `sum` skips when any term is blank (see the task-8 report).
    v = values(date="2026-11-01", seller_name="ACME", vatable_sales="1000.00", vat_amount="120.00",
               vat_exempt_sales="0.00", zero_rated_sales="0.00", total_amount="1200.00")
    assert any(f["level"] == "red" for f in runner.reflag(v, SNAP, TODAY, 95, []))
    v2, bad, edited = runner.apply_edit(v, SNAP, [{"key": "total_amount", "row": None, "value": "1,120.00"}])
    assert v2["header"]["total_amount"] == "1120.00" and bad == []
    assert edited == [{"key": "total_amount", "row": None}]
    assert runner.reflag(v2, SNAP, TODAY, 95, bad) == []


def test_edit_refuses_unknown_cells_and_flags_unreadable_text():
    v = values()
    with pytest.raises(ValueError):
        runner.apply_edit(v, SNAP, [{"key": "ghost", "row": None, "value": "1"}])
    with pytest.raises(ValueError):
        runner.apply_edit(v, SNAP, [{"key": "total_amount", "row": 4, "value": "1"}])
    _, bad, _ = runner.apply_edit(v, SNAP, [{"key": "total_amount", "row": None, "value": "abc"}])
    assert bad == [{"key": "total_amount", "row": None}]


def test_old_run_uses_its_own_snapshot():
    old = {"name": "Receipt", "fields": SNAP["fields"], "checks": []}      # the format later gained checks
    v = values(vatable_sales="1000.00", vat_amount="5.00", total_amount="9999.00")
    assert runner.reflag(v, old, TODAY, 95, []) == []


# ── beyond the brief ──────────────────────────────────────────────────────

ROW_SNAP = {"name": "Invoice", "fields": builtins.BUILTINS["invoice"]["fields"],
            "checks": builtins.BUILTINS["invoice"]["checks"]}


def test_edit_keeps_other_unreadable_cells_and_does_not_touch_the_input():
    v = values(total_amount="abc", vat_amount="12.00")
    v2, bad, edited = runner.apply_edit(v, SNAP, [{"key": "vat_amount", "row": None, "value": "15"}])
    assert bad == [{"key": "total_amount", "row": None}]
    assert v["header"]["vat_amount"] == "12.00" and v2["header"]["vat_amount"] == "15.00"
    assert edited == [{"key": "vat_amount", "row": None}]


def test_edit_row_cells_need_a_row_and_header_cells_refuse_one():
    row_key = next(f["key"] for f in ROW_SNAP["fields"] if f["scope"] == "row")
    head_key = next(f["key"] for f in ROW_SNAP["fields"] if f["scope"] == "header")
    v = {"header": {}, "rows": [{row_key: "1"}]}
    with pytest.raises(ValueError):
        runner.apply_edit(v, ROW_SNAP, [{"key": row_key, "row": None, "value": "2"}])
    with pytest.raises(ValueError):
        runner.apply_edit(v, ROW_SNAP, [{"key": head_key, "row": 0, "value": "2"}])
    with pytest.raises(ValueError):
        runner.apply_edit(v, ROW_SNAP, [{"key": row_key, "row": -1, "value": "2"}])
    v2, _, edited = runner.apply_edit(v, ROW_SNAP, [{"key": row_key, "row": 0, "value": "2"},
                                                    {"key": row_key, "row": 0, "value": "3"}])
    assert edited == [{"key": row_key, "row": 0}]
    assert v["rows"][0][row_key] == "1"


def test_edit_caps():
    assert runner.edit_problem([{"key": "a", "row": None, "value": "x"}]) is None
    assert runner.edit_problem([]) is not None
    assert runner.edit_problem([{"key": "a", "row": None, "value": "x"}] * (runner.MAX_EDITS + 1)) is not None
    assert runner.edit_problem([{"key": "a", "row": None, "value": "x" * (runner.MAX_EDIT_CHARS + 1)}]) is not None


def test_merge_edited_cells():
    assert runner.merge_edited([{"key": "a", "row": None}], [{"key": "a", "row": None}, {"key": "b", "row": 2}]) \
        == [{"key": "a", "row": None}, {"key": "b", "row": 2}]


def test_snapshots_for_one_format_or_auto():
    listing = formats.overlay([])
    one = runner.snapshots_for(listing, "bir2307")
    assert list(one) == ["bir2307"]
    assert set(one["bir2307"]) == {"name", "fields", "checks", "detect_hint"}
    every = runner.snapshots_for(listing, runner.AUTO)
    assert list(every) == [f["key"] for f in listing]
    with pytest.raises(ValueError):
        runner.snapshots_for(listing, "nope")


def test_detect_choice_uses_the_threshold():
    keys = ["bir2307", "receipt"]
    assert runner.detect_choice(1, 60.0, keys) == "receipt"
    assert runner.detect_choice(1, 59.9, keys) is None
    assert runner.detect_choice(None, 99.0, keys) is None
    assert runner.detect_choice(5, 99.0, keys) is None


def test_only_read_uncharged_files_are_charged():
    assert runner.chargeable(read=True, pages_charged=False, owner_is_firm=True)
    assert not runner.chargeable(read=True, pages_charged=True, owner_is_firm=True)
    assert not runner.chargeable(read=False, pages_charged=False, owner_is_firm=True)
    assert not runner.chargeable(read=True, pages_charged=False, owner_is_firm=False)


def test_resume_requeues_interrupted_files_and_sets_aside_repeat_offenders():
    files = [("a", "done", 0), ("b", "reading", 0), ("c", "detecting", MAX_INTERRUPTS - 1), ("d", "queued", 0),
             ("e", "choose", 0)]
    plan = runner.recovery("resume", files)
    assert plan == {"b": ("queued", 1, ""), "c": ("error", MAX_INTERRUPTS, INTERRUPTED_MESSAGE)}


def test_failing_a_dead_run_ends_its_unfinished_files():
    files = [("a", "done", 0), ("b", "reading", 1), ("d", "queued", 0), ("e", "choose", 0)]
    plan = runner.recovery("fail", files)
    assert set(plan) == {"b", "d"}
    assert all(status == "error" and msg for status, _, msg in plan.values())


def test_stale_action_maps_reading_and_uses_the_latest_progress():
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    created = now - timedelta(hours=1)
    old = now - timedelta(minutes=45)
    assert runner.stale("reading", created, [old, old], now) == "resume"
    assert runner.stale("reading", created, [old, now - timedelta(minutes=1)], now) is None
    assert runner.stale("done", created, [old], now) is None
    assert runner.stale("reading", now - timedelta(hours=25), [old], now) == "fail"


def test_records_are_capped_per_file():
    many = [{"page_start": 1}] * (runner.MAX_RECORDS + 5)
    assert len(runner.capped_records([many[:10], many[10:]])) == runner.MAX_RECORDS
