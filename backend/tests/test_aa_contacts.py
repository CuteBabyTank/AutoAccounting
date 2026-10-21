"""Contacts master: planned from documents (deduped by TIN), manual fields kept, merges resolved safely (pure)."""

from dataclasses import dataclass, field
from datetime import date

from app.services.accounting.contacts import (
    SeenParty, contact_key, merge_check, plan_contacts, resolve, role_union,
)
from app.services.accounting.schema import column_statements


@dataclass
class Row:
    key: str
    role: str = "supplier"
    tin: str = ""
    registered_name: str = ""
    aliases: list = field(default_factory=list)
    address: str = ""
    vat_status: str = ""
    manual: list = field(default_factory=list)
    id: str = ""
    company_id: str = "c1"
    merged_into_id: str | None = None


def seen(name, tin="", role="supplier", on=date(2026, 10, 1), address="", vat=None):
    return SeenParty(contact_key(tin, name), tin, name, address, role, vat, on)


def test_contact_key_is_tin_else_normalized_name():
    assert contact_key("123456789", "Luzon Paint") == "123456789"
    assert contact_key("", "Luzon Paint Distributors Corp.") == contact_key("", "LUZON PAINT DISTRIBUTORS CORP")


def test_same_tin_merges_name_variants():
    creates, updates = plan_contacts([
        seen("Luzon Paint Distributors Corp.", "111222333", on=date(2026, 10, 1)),
        seen("Luzon Paint Dist. Corp", "111222333", on=date(2026, 11, 5), address="Pasig"),
    ], [])
    assert updates == {}
    assert len(creates) == 1
    c = creates[0]
    assert (c["key"], c["tin"], c["registered_name"], c["address"]) == (
        "111222333", "111222333", "Luzon Paint Dist. Corp", "Pasig")
    assert c["aliases"] == ["Luzon Paint Distributors Corp."]


def test_name_only_contact():
    creates, _ = plan_contacts([seen("Mang Tomas Sari-Sari Store")], [])
    assert creates[0]["key"].startswith("NAME:") and creates[0]["tin"] == ""


def test_role_both():
    creates, _ = plan_contacts([seen("Mabuhay", "999888777", role="customer"),
                                seen("Mabuhay", "999888777", role="supplier")], [])
    assert creates[0]["role"] == "both"
    assert role_union("customer", "supplier") == "both" and role_union("both", "customer") == "both"
    assert role_union("supplier", "supplier") == "supplier"


def test_existing_contact_updated_and_variants_added():
    row = Row("111222333", tin="111222333", registered_name="Luzon Paint", vat_status="")
    _, updates = plan_contacts([seen("Luzon Paint Distributors Corp.", "111222333", vat=True)], [row])
    assert updates["111222333"] == {"registered_name": "Luzon Paint Distributors Corp.",
                                    "aliases": ["Luzon Paint"], "vat_status": "vat"}


def test_manual_fields_kept():
    row = Row("111222333", tin="111222333", registered_name="Luzon Paint (ours)", manual=["registered_name"])
    _, updates = plan_contacts([seen("Luzon Paint Distributors Corp.", "111222333")], [row])
    assert "registered_name" not in updates.get("111222333", {})
    assert updates["111222333"]["aliases"] == ["Luzon Paint Distributors Corp."]


def test_merged_contact_variants_go_to_target():
    target = Row("111222333", id="t", tin="111222333", registered_name="Luzon Paint")
    source = Row(contact_key("", "LP Distributors"), id="s", registered_name="LP Distributors", merged_into_id="t")
    creates, updates = plan_contacts([seen("LP Distributors", role="customer")], [target, source])
    assert creates == []
    assert updates == {"111222333": {"role": "both", "aliases": ["LP Distributors"]}}


def test_no_change_no_update():
    row = Row("111222333", tin="111222333", registered_name="Luzon Paint", vat_status="vat")
    assert plan_contacts([seen("Luzon Paint", "111222333", vat=True)], [row]) == ([], {})


def test_resolve_follows_chain_without_loop():
    a, b, c = Row("a", id="1", merged_into_id="2"), Row("b", id="2", merged_into_id="3"), Row("c", id="3")
    rows = [a, b, c]
    assert resolve("a", rows) is c
    x, y = Row("x", id="9", merged_into_id="8"), Row("y", id="8", merged_into_id="9")
    assert resolve("x", [x, y]) in (x, y)
    assert resolve("missing", rows) is None


def test_merge_check_rejects_cycle():
    a, b = Row("a", id="1"), Row("b", id="2", merged_into_id="1")
    assert merge_check(a, a, [a, b]) is not None
    assert merge_check(a, b, [a, b]) is not None            # target is itself merged
    assert merge_check(Row("o", id="5", company_id="c2"), a, [a]) is not None
    assert merge_check(b, a, [a, b]) is not None            # already merged
    c = Row("c", id="3")
    assert merge_check(c, a, [a, b, c]) is None


def test_schema_adds_cwt_2307_column():
    assert any("aa_documents ADD COLUMN IF NOT EXISTS cwt_2307 JSONB" in s for s in column_statements())
