"""Notifications derived from the board, health counts and tasks (pure)."""

from datetime import date

from app.services.accounting.compute.notifications import build

TODAY = date(2026, 10, 17)


def card(key, due, status="docs_in", assignee=None):
    return {"key": key, "status": status, "due_date": due, "assignee_id": assignee, "form_label": "2550-Q",
            "period_label": "Q3 2026", "company_name": "Bayanihan", "company_id": "c1"}


def run(**kw):
    args = dict(user_id="me", cards=[], summaries={}, cwt={}, tasks=[], today=TODAY, days=7)
    args.update(kw)
    return build(**args)


def test_deadlines_within_days_for_me_or_unassigned():
    cards = [card("a", date(2026, 10, 20)), card("b", date(2026, 10, 26)), card("c", date(2026, 10, 20), "filed"),
             card("d", date(2026, 10, 15)), card("e", date(2026, 10, 20), assignee="someone"),
             card("f", date(2026, 10, 20), assignee="me")]
    got = run(cards=cards)
    assert [n.key for n in got] == ["deadline:d", "deadline:a", "deadline:f"]
    assert got[0].severity == "high" and "was due 15 Oct" in got[0].title
    assert got[1].title == "2550-Q Q3 2026 is due 20 Oct"


def test_review_key_changes_with_count():
    one = run(summaries={"c1": {"company_name": "B", "open_reviews": 3, "unreconciled_months": 0}})
    two = run(summaries={"c1": {"company_name": "B", "open_reviews": 5, "unreconciled_months": 2}})
    assert [n.key for n in one] == ["review:c1:3"]
    assert {n.key for n in two} == {"review:c1:5", "bank:c1:2"}
    assert one[0].title == "3 documents to review"


def test_2307_only_when_overdue():
    s = {"c1": {"company_name": "B", "open_reviews": 0, "unreconciled_months": 0}}
    assert run(summaries=s, cwt={"c1": (4, 0)}) == []
    got = run(summaries=s, cwt={"c1": (4, 1)})
    assert got[0].key == "cwt:c1:1" and got[0].title == "1 2307 still missing"


def test_tasks_for_the_assignee():
    tasks = [{"id": "t1", "title": "Ask for bank statement", "assignee_id": "me", "due_date": date(2026, 10, 18),
              "status": "open", "company_id": "c1", "company_name": "B"},
             {"id": "t2", "title": "Other", "assignee_id": "you", "due_date": None, "status": "open"},
             {"id": "t3", "title": "Done", "assignee_id": "me", "due_date": None, "status": "done"}]
    keys = {n.key for n in run(tasks=tasks)}
    assert keys == {"task:t1:due:2026-10-18", "task:t1:assigned"}


def test_recurring_entries_due_notify_everyone_with_count_and_date_in_the_key():
    due = [{"company_id": "c1", "company_name": "Bayanihan", "count": 3, "oldest": date(2026, 8, 31)},
           {"company_id": "c2", "company_name": "Mabuhay", "count": 0, "oldest": None}]
    [n] = run(recurring=due)
    assert n.kind == "recurring" and n.key == "recurring:c1:3:2026-08-31"
    assert n.title == "3 recurring entries due to post" and n.detail == "Bayanihan" and n.company_id == "c1"
    assert n.due_date == date(2026, 8, 31) and n.severity == "normal"
    # posting one changes the key, so a dismissed notice comes back with the new situation
    [m] = run(recurring=[{**due[0], "count": 2, "oldest": date(2026, 9, 30)}])
    assert m.key != n.key and m.title == "2 recurring entries due to post"
    assert run(recurring=[{**due[0], "count": 1}])[0].title == "1 recurring entry due to post"
