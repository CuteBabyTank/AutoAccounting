"""Import undo, pure parts: fingerprints, what an undo deletes or restores, and the guards that refuse it."""

from datetime import date
from types import SimpleNamespace

from app.services.accounting.import_undo import (
    UndoFacts, bank_touches, batch_status, closed_hits, entries_plan, entry_state, filed_hits, fingerprint, opening_bank_delta,
    opening_plan, reconciled_hits, undo_problem,
)

START = date(2026, 1, 1)
BATCH = "b1"


def _je(**kw):
    base = dict(id="e1", kind="manual", book="GJ", entry_date=date(2026, 2, 3), reference="JV-1",
                particulars="Payroll", is_adjusting=False, import_batch_id=BATCH, deleted_at=None,
                lines=[{"account_code": "6000", "debit": "120000.00", "credit": "0", "party_name": "", "party_tin": ""},
                       {"account_code": "1020", "debit": "0", "credit": "120000.00", "party_name": "",
                        "party_tin": ""}])
    base.update(kw)
    return SimpleNamespace(**base)


def test_fingerprint_is_stable_and_sees_edits():
    a = entry_state(_je())
    assert fingerprint(a) == fingerprint(entry_state(_je()))
    # JSONB may hand the line keys back in another order: same fingerprint
    shuffled = _je(lines=[dict(reversed(list(l.items()))) for l in _je().lines])
    assert fingerprint(entry_state(shuffled)) == fingerprint(a)
    assert fingerprint(entry_state(_je(particulars="Payroll Dec"))) != fingerprint(a)
    assert fingerprint(entry_state(_je(entry_date=date(2026, 2, 4)))) != fingerprint(a)
    # the batch tag is bookkeeping, not content
    assert fingerprint(entry_state(_je(import_batch_id="other"))) == fingerprint(a)


def test_entries_plan_deletes_live_unedited_and_reports_edits():
    e1, e2, e3 = _je(id="e1"), _je(id="e2", reference="JV-2"), _je(id="e3", reference="JV-3")
    written = {r.id: fingerprint(entry_state(r)) for r in (e1, e2, e3)}
    edited = _je(id="e2", reference="JV-2", particulars="changed")
    delete, changed = entries_plan(written, [e1, edited])   # e3 deleted by a person since: nothing to do
    assert delete == ["e1", "e2"] and changed == ["e2"]
    delete, changed = entries_plan(written, [e1])
    assert delete == ["e1"] and changed == []


def test_opening_plan_without_prior_deletes_the_entry():
    row = _je(id="op", kind="opening", entry_date=START)
    written = {"op": fingerprint(entry_state(row))}
    plan = opening_plan(BATCH, {"opening": None}, written, row)
    assert plan.action == "delete" and plan.problem == "" and plan.restore is None


def test_opening_plan_restores_the_prior_entry():
    prior = entry_state(_je(id="op", kind="opening", entry_date=START, particulars="Opening balances",
                            import_batch_id=None))
    row = _je(id="op", kind="opening", entry_date=START, particulars="Opening balances (imported from tb.xlsx)")
    plan = opening_plan(BATCH, {"opening": prior}, {"op": fingerprint(entry_state(row))}, row)
    assert plan.action == "restore" and plan.problem == ""
    assert plan.restore["particulars"] == "Opening balances" and plan.restore["import_batch_id"] is None


def test_opening_plan_refuses_superseded_edited_or_deleted():
    row = _je(id="op", kind="opening", entry_date=START)
    written = {"op": fingerprint(entry_state(row))}
    later = _je(id="op", kind="opening", entry_date=START, import_batch_id="b2")
    assert "later import" in opening_plan(BATCH, {"opening": None}, written, later).problem
    edited = _je(id="op", kind="opening", entry_date=START, particulars="typed over")
    assert "edited" in opening_plan(BATCH, {"opening": None}, written, edited).problem
    assert "deleted" in opening_plan(BATCH, {"opening": None}, written, None).problem
    other = _je(id="other", kind="opening", entry_date=START)   # a different opening entry now
    assert opening_plan(BATCH, {"opening": None}, written, other).problem


def test_closed_and_filed_hits():
    closes = [(date(2026, 1, 1), date(2026, 1, 31)), (date(2026, 2, 1), date(2026, 2, 28))]
    assert closed_hits([date(2026, 2, 3), date(2026, 3, 1)], closes) == [(date(2026, 2, 1), date(2026, 2, 28))]
    assert closed_hits([date(2026, 3, 1)], closes) == []
    # December fiscal year end: Feb is Q1 of FY 2026; June fiscal year end: Feb is Q3 of FY 2026
    assert filed_hits([date(2026, 2, 3)], {(2026, 1)}, 12) == [(2026, 1)]
    assert filed_hits([date(2026, 2, 3)], {(2026, 1)}, 6) == []
    assert filed_hits([date(2026, 2, 3)], {(2026, 3)}, 6) == [(2026, 3)]


def test_bank_touches_and_reconciled_hits():
    touches = bank_touches([_je()], {"1020"})
    assert touches == [("1020", date(2026, 2, 3))]
    assert bank_touches([_je()], {"1030"}) == []
    recs = [("1020", date(2026, 1, 1), date(2026, 1, 31)), ("1020", date(2026, 2, 1), date(2026, 2, 28)),
            ("1030", date(2026, 3, 1), date(2026, 3, 31))]
    # the February reconciliation holds the entry; a later month's would carry its balance too
    assert reconciled_hits(touches, recs) == [("1020", date(2026, 2, 1))]
    assert reconciled_hits([("1020", date(2026, 3, 5))], recs) == []


def test_opening_bank_delta_only_counts_changed_bank_lines():
    old = [{"account_code": "1020", "debit": "5000.00", "credit": "0"}, {"account_code": "3000", "debit": "0",
                                                                        "credit": "5000.00"}]
    new = [{"account_code": "1020", "debit": "5000", "credit": "0"}, {"account_code": "1030", "debit": "100",
                                                                     "credit": "0"},
           {"account_code": "3000", "debit": "0", "credit": "5100"}]
    assert opening_bank_delta(old, new, {"1020", "1030"}) == {"1030"}
    assert opening_bank_delta([], new, {"1020", "1030"}) == {"1020", "1030"}
    assert opening_bank_delta(old, old, {"1020"}) == set()


def _facts(**kw):
    base = dict(kind="journal-entries", undone=False, fye=12)
    base.update(kw)
    return UndoFacts(**base)


def test_undo_problem_none_when_clear():
    assert undo_problem(_facts()) == ""


def test_undo_problem_messages_in_priority_order():
    assert "already undone" in undo_problem(_facts(undone=True, closed=[(date(2026, 1, 1), date(2026, 1, 31))]))
    msg = undo_problem(_facts(closed=[(date(2026, 1, 1), date(2026, 1, 31))]))
    assert "January 2026 is closed" in msg and "Reopen" in msg
    assert "Q1 2026" in undo_problem(_facts(filed=[(2026, 1)]))
    assert "1020" in undo_problem(_facts(reconciled=[("1020", date(2026, 2, 1))]))
    assert "INV-9" in undo_problem(_facts(kind="open-items", confirmed=["INV-9"]))
    assert "INV-9" in undo_problem(_facts(kind="open-items", paid=["INV-9"]))
    assert "INV-9" in undo_problem(_facts(kind="open-items", written_off=["INV-9"]))
    assert "JV-2" in undo_problem(_facts(edited=["JV-2"]))
    assert "later import" in undo_problem(_facts(kind="opening-tb", opening="A later import replaced these opening "
                                                                            "balances; undo that one first"))


def test_undo_problem_lists_at_most_a_few_names():
    msg = undo_problem(_facts(kind="open-items", confirmed=[f"INV-{i}" for i in range(12)]))
    assert "INV-0" in msg and "INV-11" not in msg and "and 7 more" in msg


def test_batch_status():
    assert batch_status("journal-entries", "b1", False, None) == "active"
    assert batch_status("journal-entries", "b1", True, None) == "undone"
    assert batch_status("opening-tb", "b1", False, "b1") == "active"
    assert batch_status("opening-tb", "b1", False, "b2") == "replaced"
    assert batch_status("opening-tb", "b1", False, None) == "replaced"   # deleted or typed over by a person
    assert batch_status("opening-tb", "b1", True, "b2") == "undone"
