"""Completion dates and summaries (pure)."""
from datetime import date, datetime, timezone

from app.services.accounting.compute.work_history import Completion, history_page, validate_window
from app.services.accounting.compute.tasks import completion_fields


NOW = datetime(2026, 10, 21, 1, tzinfo=timezone.utc)


def test_completion_actor_tracks_done_and_reopen_transitions():
    assert completion_fields("open", "done", "ana", NOW, None, None) == (NOW, "ana")
    assert completion_fields(None, "done", "ana", NOW, None, None) == (NOW, "ana")
    assert completion_fields("done", "done", "ben", NOW, NOW, "ana") == (NOW, "ana")
    assert completion_fields("done", "in_progress", "ben", NOW, NOW, "ana") == (None, None)


def rows():
    return [Completion("1", "task", "On time", "c", "Client", "ana", NOW, "ben", date(2026, 10, 21), "task"),
            Completion("2", "filing", "Late", "c", "Client", "ben", NOW, "ana", date(2026, 10, 20), "board"),
            Completion("3", "task", "No due", None, "", None, NOW, None, None, "task")]


def test_summary_counts_actual_completer_and_open_now_pagination():
    result = history_page(rows(), [{"assignee_id": "ana", "company_id": "c", "kind": "task"}],
                          {"ana": "Ana", "ben": "Ben"}, date(2026, 10, 1), date(2026, 10, 31), limit=1)
    assert result["total"] == 3 and len(result["items"]) == 1
    summary = {s["person_id"]: s for s in result["summary"]}
    assert (summary["ana"]["completed"], summary["ana"]["on_time"], summary["ana"]["open_now"]) == (1, 1, 1)
    assert summary["ben"]["late"] == 1
    assert summary[None]["person_name"] == "Unknown" and summary[None]["on_time"] == 0


def test_employee_scope_overrides_requested_person_for_items_and_summary():
    result = history_page(rows(), [{"assignee_id": "ben", "kind": "task"}], {"ana": "Ana", "ben": "Ben"},
                          date(2026, 10, 1), date(2026, 10, 31), person="ben", employee_id="ana")
    assert [i["id"] for i in result["items"]] == ["1"]
    assert [s["person_id"] for s in result["summary"]] == ["ana"]
    assert result["summary"][0]["open_now"] == 0


def test_filters_and_manila_day_lateness():
    late_utc = datetime(2026, 10, 21, 17, tzinfo=timezone.utc)  # Oct 22 Manila
    completions = [Completion("x", "task", "Task", "c", "Client", "ana", late_utc, None,
                              date(2026, 10, 21), "task")]
    args = (completions, [], {"ana": "Ana"})
    assert history_page(*args, date(2026, 10, 1), date(2026, 10, 21))["total"] == 0
    page = history_page(*args, date(2026, 10, 22), date(2026, 10, 22), company="c", kind="task")
    assert page["items"][0]["on_time"] is False
    assert history_page(*args, date(2026, 10, 1), date(2026, 10, 31), kind="filing")["total"] == 0


def test_window_validation_and_backfill_actor_evidence():
    from app.services.accounting.compute.work_history import completion_actor
    for start, end in ((date(2026, 1, 2), date(2026, 1, 1)), (date(2020, 1, 1), date(2026, 1, 1))):
        try:
            validate_window(start, end)
        except ValueError:
            pass
        else:
            raise AssertionError("Unbounded window accepted")
    events = [{"after": {"status": "done"}, "user_id": "ana"},
              {"after": {"title": "Edited"}, "user_id": "ben"}]
    assert completion_actor(events) == "ana"
    assert completion_actor([{"after": {"status": "done"}, "user_id": None}]) is None
    assert completion_actor(events + [{"after": {"status": "open"}, "user_id": "ben"}]) is None


def test_version_actor_requires_matching_company_period_form_and_filed_state():
    from app.services.accounting.compute.work_history import filing_actor
    entry = {"output_id": "version", "filed_at": NOW.isoformat()}
    events = [{"company_id": "c", "entity_id": "2026-Q3", "user_id": "ana", "after": {"2550Q": entry}},
              {"company_id": "other", "entity_id": "2026-Q3", "user_id": "ben", "after": {"2550Q": entry}}]
    assert filing_actor(events, "c", "2026-Q3", "2550Q", entry) == "ana"
    assert filing_actor(events, "c", "2026-Q3", "1702Q", entry) is None
    assert filing_actor(events, "c", "2026-annual", "2550Q", entry) is None
    assert filing_actor(events, "c", "2026-Q3", "2550Q", {**entry, "output_id": "new"}) is None
