"""Per-person access rules (services/access.py) and how Casper's write permission reads the person's level."""

import pytest

from app.services import access
from app.services.accounting.assistant.action_policy import write_permission
from app.services.features import KEYS

ALL_ON = {k: True for k in KEYS}


def test_clean_keeps_known_areas_once_and_drops_bad_levels():
    assert access.clean({"off": ["books", "books", "nope", "assistant"], "assistant": "god"}) == {"off": ["books"]}
    assert access.clean(None) == {"off": []}
    assert access.clean({"off": [], "assistant": "read"}) == {"off": [], "assistant": "read"}


def test_every_personal_area_is_a_real_feature():
    assert set(access.PERSONAL_KEYS) <= set(KEYS)
    assert "assistant" not in access.PERSONAL_KEYS and "assistant_write" not in access.PERSONAL_KEYS


def test_apply_narrows_members_only():
    a = {"off": ["books", "bank"], "assistant": "read"}
    staff = access.apply(ALL_ON, a, "employee")
    assert not staff["books"] and not staff["bank"] and staff["documents"]
    assert staff["assistant"] and not staff["assistant_write"]
    assert access.apply(ALL_ON, a, "enterprise") == ALL_ON  # the owner is never limited
    assert access.apply(ALL_ON, a, "admin") == ALL_ON


def test_casper_off_turns_off_chat_and_changes():
    out = access.apply(ALL_ON, {"assistant": "off"}, "manager")
    assert not out["assistant"] and not out["assistant_write"]


def test_personal_access_never_turns_on_what_maintenance_turned_off():
    firm = {**ALL_ON, "bank": False}
    assert not access.apply(firm, {"off": []}, "employee")["bank"]
    assert not access.blocked_personally("bank", firm, {"off": ["bank"]}, "employee")  # 503, not 403
    assert access.blocked_personally("books", firm, {"off": ["books"]}, "employee")


@pytest.mark.parametrize("caller,member,ok", [
    ("enterprise", "manager", True), ("enterprise", "employee", True),
    ("manager", "employee", True), ("manager", "manager", False), ("employee", "employee", False),
])
def test_who_can_manage_access(caller, member, ok):
    assert access.can_manage(caller, member) is ok


def test_summary_reads_well():
    labels = {"books": "Books"}
    assert access.summary(None, labels) == "Full access"
    assert access.summary({"off": ["books"]}, labels) == "Books off"
    assert access.summary({"off": ["books", "bank", "close"], "assistant": "read"}, labels) == \
        "3 areas off · Casper: ask only"


@pytest.mark.parametrize("setting,role,level,allowed", [
    ("managers", "employee", "write", True),    # the person's own level wins over the role default
    ("managers", "manager", "read", False),
    ("managers", "manager", None, True),
    ("everyone", "employee", "off", False),
    ("off", "employee", "write", False),         # the firm's "off" still wins
    ("managers", "enterprise", "read", True),    # owners are never limited
])
def test_write_permission_reads_the_persons_level(setting, role, level, allowed):
    assert write_permission(setting, role, True, level)["allowed"] is allowed
    assert write_permission(setting, role, False, level)["allowed"] is False
