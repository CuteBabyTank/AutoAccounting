import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.accounting.extract import builder, builtins, formats, guard, spec


def row(**kw):
    base = dict(id=uuid.uuid4(), name="Hauling slip", description="", base_key=None, fields=[], checks=[],
                detect_hint="", version=3, deleted_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_overlay_order_and_firm_copy_replaces_builtin():
    copy = row(name="BIR 2307", base_key="bir2307", fields=builtins.BUILTINS["bir2307"]["fields"][:3])
    custom = row()
    out = formats.overlay([custom, copy])
    assert [f["name"] for f in out] == ["BIR 2307", "Receipt", "Invoice", "Hauling slip"]
    assert out[0]["key"] == str(copy.id) and out[0]["edited"] and len(out[0]["fields"]) == 3
    assert out[1]["key"] == "receipt" and out[1]["builtin"] and not out[1]["edited"]
    assert out[3]["version"] == 3 and not out[3]["builtin"]


def test_merge_for_edit_keeps_current_and_offers_new():
    current = {"fields": [{"key": "total", "label": "Total", "type": "money", "scope": "header", "required": True,
                           "description": ""}], "checks": [{"id": "c_1", "kind": "required", "field": "total",
                                                           "level": "red"}]}
    proposal = {"fields": [{"key": "total", "label": "TOTAL DUE", "type": "money", "scope": "header",
                            "required": False, "description": "", "value": "1,120.00"},
                           {"key": "po_number", "label": "PO Number", "type": "code", "scope": "header",
                            "required": False, "description": "", "value": "PO-7"}],
                "checks": [{"id": "c_1", "kind": "required", "field": "total", "level": "red"},
                           {"id": "c_2", "kind": "required", "field": "po_number", "level": "red"}]}
    m = formats.merge_for_edit(current, proposal)
    assert [(f["key"], f["label"], f["picked"]) for f in m["fields"]] == [
        ("total", "Total", True), ("po_number", "PO Number", False)]
    assert m["fields"][0]["value"] == "1,120.00" and [c["id"] for c in m["checks"]] == ["c_1", "c_2"]


def test_out_adds_sentences():
    out = formats.out(formats.overlay([])[1])
    assert all(c["sentence"] for c in out["checks"])


# ── helpers the router decides with ────────────────────────────────────────

def _f(key, ftype="text", scope="header", required=False, value=None, label=None):
    field = {"key": key, "label": label or key.replace("_", " ").capitalize(), "type": ftype, "scope": scope,
             "required": required, "description": ""}
    if value is not None:
        field["value"] = value
    return field


def test_overlay_skips_deleted_rows_and_sorts_firm_formats_by_name():
    gone = row(name="Old", deleted_at=datetime.now(timezone.utc))
    out = formats.overlay([row(name="zeta"), row(name="Alpha"), gone])
    assert [f["name"] for f in out] == ["BIR 2307", "Receipt", "Invoice", "Alpha", "zeta"]


def test_find_by_key_and_builtin_key_reaches_its_firm_copy():
    copy = row(name="My 2307", base_key="bir2307")
    listing = formats.overlay([copy])
    assert formats.find(listing, "receipt")["key"] == "receipt"
    assert formats.find(listing, "bir2307")["key"] == str(copy.id)
    assert formats.find(listing, str(copy.id))["name"] == "My 2307"
    assert formats.find(listing, str(uuid.uuid4())) is None and formats.find(listing, "nope") is None


def test_with_defaults_puts_default_checks_first_so_the_cap_cannot_crowd_them_out():
    fields = [_f("seller_tin", "tin"), _f("date", "date")] + [_f(f"n{i}", "money") for i in range(40)]
    model_checks = spec.clean_checks([{"kind": "range", "field": f"n{i}", "min": 0} for i in range(40)], fields)
    out = builder.with_defaults({"name": "X", "detect_hint": "", "fields": fields, "checks": model_checks})
    kinds = [c["kind"] for c in out["checks"]]
    assert len(out["checks"]) == spec.MAX_CHECKS and kinds[:2] == ["format", "not_future"]


def test_fresh_proposal_picks_everything():
    p = formats.fresh_proposal({"name": "Slip", "detect_hint": "h", "fields": [_f("a"), _f("b")], "checks": []})
    assert [f["picked"] for f in p["fields"]] == [True, True] and p["name"] == "Slip"


def test_merge_for_edit_keeps_current_name_and_hint():
    current = {"name": "Mine", "detect_hint": "old hint", "fields": [_f("a")], "checks": []}
    m = formats.merge_for_edit(current, {"name": "Model", "detect_hint": "new", "fields": [], "checks": []})
    assert (m["name"], m["detect_hint"]) == ("Mine", "old hint")


def test_draft_out_shape():
    p = formats.fresh_proposal({"name": "Slip", "detect_hint": "h", "fields": [_f("total", "money", value="5")],
                                "checks": [{"id": "c_x", "kind": "range", "field": "total", "min": "0", "max": None,
                                            "level": "red"}]})
    out = formats.draft_out(uuid.UUID(int=1), p, asks=2, page_count=7)
    assert out["id"] == str(uuid.UUID(int=1)) and out["asks_left"] == guard.ASKS_PER_DRAFT - 2
    assert out["page_count"] == 7 and out["fields"][0]["value"] == "5" and out["fields"][0]["picked"]
    assert out["checks"][0]["sentence"] == "Total should be at least 0"


def test_draft_expiry():
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    assert not formats.draft_expired(now - timedelta(hours=23, minutes=59), now)
    assert formats.draft_expired(now - timedelta(hours=24, seconds=1), now)


def test_ask_problem_limits():
    assert formats.ask_problem(0, 0) is None
    assert formats.ask_problem(guard.ASKS_PER_DRAFT, 0)
    assert formats.ask_problem(1, guard.ADDED_PER_DRAFT)


def test_append_found_rekeys_skips_known_labels_and_respects_room():
    proposal = formats.fresh_proposal({"name": "S", "detect_hint": "", "fields": [_f("po_number", "code")],
                                       "checks": []})
    found = [_f("po_number", "date", value="2026-01-02", label="PO date"),
             _f("po_number", "code", value="X", label="Po number"),
             _f("driver_tin", "tin", value="123", label="Driver TIN"),
             _f("plate", value="ABC", label="Plate")]
    new, added = formats.append_found(proposal, found, room=2)
    assert [f["label"] for f in added] == ["PO date", "Driver TIN"]
    assert len({f["key"] for f in new["fields"]}) == 3 and all(f["picked"] for f in added)
    assert {c["kind"] for c in new["checks"]} == {"not_future", "format"}


def test_append_found_puts_the_new_fields_default_checks_before_a_full_check_list():
    fields = [_f(f"n{i}", "money") for i in range(40)]
    full = spec.clean_checks([{"kind": "range", "field": f"n{i}", "min": 0} for i in range(40)], fields)
    assert len(full) == spec.MAX_CHECKS
    proposal = formats.fresh_proposal({"name": "S", "detect_hint": "", "fields": fields, "checks": full})
    new, added = formats.append_found(proposal, [_f("buyer_tin", "tin", value="123", label="Buyer TIN")], room=5)
    assert len(added) == 1 and len(new["checks"]) == spec.MAX_CHECKS
    assert new["checks"][0]["kind"] == "format" and new["checks"][0]["field"] == added[0]["key"]


def test_append_found_stops_at_the_field_cap():
    proposal = formats.fresh_proposal({"name": "S", "detect_hint": "", "checks": [],
                                       "fields": [_f(f"f{i}") for i in range(spec.MAX_FIELDS)]})
    _, added = formats.append_found(proposal, [_f("extra", value="1", label="Extra")], room=5)
    assert added == []


def test_not_found_matches_text_then_pairs_leftovers_in_order():
    found = [_f("po_number", value="1", label="PO number"), _f("purchase_ref", value="2", label="Purchase ref")]
    assert formats.not_found(["po number", "Delivery ref"], found) == []
    assert formats.not_found(["po number", "delivery date", "plate"], found[:1] + found[1:]) == ["plate"]
    assert formats.not_found(["Driver", "Plate"], []) == ["Driver", "Plate"]


def test_build_save_strips_values_and_drops_checks_of_unpicked_fields():
    known = formats.fresh_proposal({"name": "S", "detect_hint": "", "fields": [
        _f("a", "money", value="1"), _f("b", "money", value="2"), _f("total", "money", value="3")], "checks": []})
    known["checks"] = spec.clean_checks([
        {"kind": "sum", "terms": [{"field": "a", "sign": 1}, {"field": "b", "sign": 1}], "target": "total"},
        {"kind": "range", "field": "a", "min": 0}], known["fields"])
    ids = [c["id"] for c in known["checks"]]
    fields, checks = formats.build_save(known, [{"key": "a", "label": "A amt", "required": True},
                                                {"key": "total", "label": "", "required": False}], ids)
    assert fields == [{"key": "a", "label": "A amt", "type": "money", "scope": "header", "required": True,
                       "description": ""},
                      {"key": "total", "label": "Total", "type": "money", "scope": "header", "required": False,
                       "description": ""}]
    assert sorted(c["kind"] for c in checks) == ["range", "required"]


def test_build_save_refuses_nothing_picked_and_unknown_keys():
    known = formats.fresh_proposal({"name": "S", "detect_hint": "", "fields": [_f("a")], "checks": []})
    with pytest.raises(ValueError):
        formats.build_save(known, [], [])
    with pytest.raises(ValueError):
        formats.build_save(known, [{"key": "evil", "label": "x"}], [])


def test_build_save_cannot_bring_in_a_check_the_draft_never_had():
    known = formats.fresh_proposal({"name": "S", "detect_hint": "", "fields": [_f("a", "money")], "checks": []})
    _, checks = formats.build_save(known, [{"key": "a", "label": "A"}], ["c_0000000000"])
    assert checks == []


def test_known_for_save_merges_draft_onto_current():
    current = {"name": "Mine", "detect_hint": "", "fields": [_f("a")], "checks": []}
    proposal = formats.fresh_proposal({"name": "", "detect_hint": "", "fields": [_f("a"), _f("b")], "checks": []})
    assert [f["key"] for f in formats.known_for_save(current, proposal)["fields"]] == ["a", "b"]
    assert formats.known_for_save(current, None) is current
    assert formats.known_for_save(None, proposal) is proposal


def test_builtin_name_clash():
    assert formats.builtin_name_clash("receipt", None)
    assert formats.builtin_name_clash("BIR 2307", "receipt")
    assert not formats.builtin_name_clash("BIR 2307", "bir2307")
    assert not formats.builtin_name_clash("Hauling slip", None)


def test_audit_view_lists_keys_and_ids():
    view = formats.audit_view("Slip", "d", 2, [_f("a"), _f("b")], [{"id": "c_1"}])
    assert view == {"name": "Slip", "description": "d", "version": 2, "fields": ["a", "b"], "checks": ["c_1"]}


def test_admin_row_shows_prompt_and_deleted_flag():
    from datetime import datetime, timezone
    from app.routers.admin import extract_format_row
    r = row(name="Hauling slip", fields=builtins.BUILTINS["receipt"]["fields"], checks=builtins.BUILTINS["receipt"]["checks"],
            deleted_at=datetime(2026, 11, 1, tzinfo=timezone.utc), updated_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    out = extract_format_row(r, "Santos CPA", "Ana")
    assert out["firm"] == "Santos CPA" and out["deleted"] and out["updated_by"] == "Ana"
    assert '"total_amount"' in out["prompt"] and out["checks"][0]["sentence"]


def test_stale_draft_folders_are_picked_by_age_and_name():
    now = 1_000_000_000.0
    day = 24 * 3600
    old, young, odd = str(uuid.uuid4()), str(uuid.uuid4()), "not-a-draft"
    entries = [(old, now - day - builder.SWEEP_GRACE_SECONDS - 1), (young, now - day + 60),
               (odd, now - 10 * day), ("../" + old, now - 10 * day)]
    assert builder.stale_draft_folders(entries, now) == [old]
    assert builder.stale_draft_folders([], now) == []


def test_sweep_draft_folders_tolerates_a_missing_root(monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, "accounting_dir", str(tmp_path / "nowhere"))
    assert builder.sweep_draft_folders_sync() == 0


def test_sweep_draft_folders_removes_only_old_ones(monkeypatch, tmp_path):
    import os
    import time

    from app.config import settings
    monkeypatch.setattr(settings, "accounting_dir", str(tmp_path))
    drafts = tmp_path / "extract" / "drafts"
    old, young = drafts / str(uuid.uuid4()), drafts / str(uuid.uuid4())
    for folder in (old, young):
        folder.mkdir(parents=True)
        (folder / "sample.pdf").write_bytes(b"x")
    stamp = time.time() - 3 * 24 * 3600
    os.utime(old, (stamp, stamp))
    assert builder.sweep_draft_folders_sync() == 1
    assert not old.exists() and young.exists()
