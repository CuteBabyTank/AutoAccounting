"""Assignment decisions use only firm facts; no database."""
from app.services.accounting.compute.assign import Member, plan_assignments


def member(id, name=None, **kw):
    return Member(id, name or id, "firm", "employee", **kw)


def item(key, **kw):
    return {"key": key, "company_id": "client", "status": "open", "assignee_id": None, **kw}


def test_handler_wins_only_when_active_and_in_firm():
    people = [member("a"), member("b"), Member("foreign", "Foreign", "elsewhere", "employee"),
              member("gone", is_active=False), Member("pending", "Pending", "firm", "unverified")]
    for handler in ("foreign", "gone", "pending", "removed"):
        assert plan_assignments([item("x")], people, "firm", {"client": handler}, {}, {}) == {"x": "a"}
    assert plan_assignments([item("x")], people, "firm", {"client": "b"}, {"b": 99}, {}) == {"x": "b"}
    assert plan_assignments([item("x")], [], "firm", {}, {}, {}) == {}


def test_least_open_then_recent_then_name_with_stable_ties():
    people = [member("b", "Ben"), member("a", "Ana")]
    assert plan_assignments([item("x")], people, "firm", {}, {"a": 2}, {"b": 99}) == {"x": "b"}
    assert plan_assignments([item("x")], people, "firm", {}, {}, {"a": 1}) == {"x": "b"}
    assert plan_assignments([item("x")], people, "firm", {}, {}, {}) == {"x": "a"}
    assert plan_assignments([item("x"), item("y"), item("z")], people, "firm", {}, {}, {}) == {
        "x": "a", "y": "b", "z": "a"}
    owner = Member("firm", "Owner", None, "enterprise")
    assert plan_assignments([item("x")], [owner], "firm", {}, {}, {}) == {"x": "firm"}


def test_manual_assignments_completed_items_and_repeat_are_untouched():
    items = [item("manual", assignee_id="removed"), item("auto", assignee_id="a", assigned_auto=True),
             item("done", status="done"), item("filed", status="filed"), item("x")]
    chosen = plan_assignments(items, [member("a")], "firm", {}, {}, {})
    assert chosen == {"x": "a"}
    repeated = [{**i, "assignee_id": chosen.get(i["key"], i["assignee_id"])} for i in items]
    assert plan_assignments(repeated, [member("a")], "firm", {}, {}, {}) == {}
