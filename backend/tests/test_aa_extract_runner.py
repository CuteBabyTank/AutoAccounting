from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.accounting import EXTRACT_FILE_PENDING
from app.services import usage_service
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
    v = values(date="2026-11-01", seller_name="ACME", vatable_sales="1000.00", vat_amount="120.00",
               total_amount="1200.00")
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


def test_unread_extract_pages_query_counts_only_live_unread_files_of_the_firm():
    import uuid

    from sqlalchemy.dialects import postgresql

    firm = uuid.uuid4()
    stmt = usage_service.extract_pending_pages_query(firm)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "aa_extract_files.page_count" in sql and "JOIN aa_extract_runs" in sql
    assert "aa_extract_files.pages_charged IS false" in sql
    assert "aa_extract_runs.deleted_at IS NULL" in sql
    assert "aa_extract_files.enterprise_id" in sql and "aa_extract_runs.enterprise_id" in sql
    params = stmt.compile(dialect=postgresql.dialect()).params
    assert list(params.values()).count(firm) == 2
    assert any(v == list(EXTRACT_FILE_PENDING) for v in params.values())
    assert set(EXTRACT_FILE_PENDING) == runner.RUNNING and "choose" not in EXTRACT_FILE_PENDING


def test_format_summary_lists_used_formats_with_counts():
    snaps = {"bir2307": {"name": "BIR 2307"}, "receipt": {"name": "Receipt"}, "invoice": {"name": "Invoice"}}
    out = runner.format_summary(snaps, ["receipt", None, "bir2307"], {"bir2307": (30, 11, 2)})
    assert out == [{"format_key": "bir2307", "name": "BIR 2307", "records": 30, "red": 11, "yellow": 2},
                   {"format_key": "receipt", "name": "Receipt", "records": 0, "red": 0, "yellow": 0}]


def test_records_format_needs_a_key_only_when_several_formats_have_records():
    snaps = {"bir2307": {}, "receipt": {}}
    assert runner.records_format(None, ["bir2307"], snaps) == "bir2307"
    assert runner.records_format(None, [], snaps) is None
    assert runner.records_format("receipt", ["bir2307", "receipt"], snaps) == "receipt"
    with pytest.raises(ValueError):
        runner.records_format(None, ["bir2307", "receipt"], snaps)
    with pytest.raises(ValueError):
        runner.records_format("invoice", ["bir2307"], snaps)


def test_file_errors_are_friendly_and_internal_ones_distinct():
    from app.services.accounting import gemini, pipeline

    assert runner.file_error(gemini.ReaderUnavailable("quota")) == pipeline.READER_DOWN_MESSAGE
    assert runner.file_error(ValueError("unreadable_reply")) == runner.UNREADABLE_FILE
    assert runner.file_error(runner.Unprocessable("format_not_in_snapshot")) == runner.UNPROCESSABLE_FILE
    assert runner.file_error(RuntimeError("boom")) == runner.FAILED_FILE
