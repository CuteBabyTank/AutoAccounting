import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.accounting import audit


class _Role(enum.Enum):
    MANAGER = "manager"


class _Session:
    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)


USER = SimpleNamespace(id=uuid.uuid4(), email="ana@firm.ph")
ENT, COMPANY = uuid.uuid4(), uuid.uuid4()


def test_json_safe_handles_decimal_date_uuid_enum():
    uid = uuid.uuid4()
    value = {"gross": Decimal("1200.50"), "on": date(2026, 10, 3), "at": datetime(2026, 10, 3, 1, 2, tzinfo=timezone.utc),
             "id": uid, "role": _Role.MANAGER, "lines": [{"debit": Decimal("5")}], "pair": (1, None)}
    assert audit.json_safe(value) == {
        "gross": "1200.50", "on": "2026-10-03", "at": "2026-10-03T01:02:00+00:00", "id": str(uid),
        "role": "manager", "lines": [{"debit": "5"}], "pair": [1, None],
    }


def test_snapshot_reads_attributes_json_safe():
    doc = SimpleNamespace(gross_amount=Decimal("1000.00"), doc_date=date(2026, 10, 3), seller_name="Luzon Paint")
    assert audit.snapshot(doc, ("gross_amount", "doc_date")) == {"gross_amount": "1000.00", "doc_date": "2026-10-03"}


def test_diff_keeps_only_changed_fields():
    before = {"gross_amount": "1000.00", "seller_name": "Luzon Paint", "review_reasons": ["vat_math_mismatch"]}
    after = {"gross_amount": "1200.00", "seller_name": "Luzon Paint", "review_reasons": ["vat_math_mismatch"],
             "ewt_atc": "WC158"}
    assert audit.diff(before, after) == ({"gross_amount": "1000.00", "ewt_atc": None},
                                         {"gross_amount": "1200.00", "ewt_atc": "WC158"})


def test_diff_compares_decimals_by_value_text():
    assert audit.diff({"a": Decimal("5.00")}, {"a": "5.00"}) == ({}, {})


def test_record_skips_empty_update_and_adds_otherwise():
    db = _Session()
    same = {"gross_amount": "1000.00"}
    assert audit.record(db, ent=ENT, company_id=COMPANY, user=USER, entity="document", entity_id=uuid.uuid4(),
                        action="update", before=same, after=dict(same)) is None
    assert db.added == []
    doc_id = uuid.uuid4()
    event = audit.record(db, ent=ENT, company_id=COMPANY, user=USER, entity="document", entity_id=doc_id,
                         action="update", before=same, after={"gross_amount": "1200.00"}, reason="  typo  ")
    assert db.added == [event]
    assert (event.enterprise_id, event.company_id, event.user_id, event.user_label) == (ENT, COMPANY, USER.id,
                                                                                          "ana@firm.ph")
    assert (event.entity, event.entity_id, event.action) == ("document", str(doc_id), "update")
    assert (event.before, event.after, event.reason) == ({"gross_amount": "1000.00"}, {"gross_amount": "1200.00"},
                                                         "typo")


def test_record_always_writes_create_and_delete_events():
    db = _Session()
    event = audit.record(db, ent=ENT, company_id=COMPANY, user=USER, entity="books_month", entity_id="x",
                         action="reopen", always=True)
    assert event is not None and event.before == {} and event.after == {}
    created = audit.record(db, ent=ENT, company_id=COMPANY, user=USER, entity="account", entity_id="y",
                           action="create", after={"code": "6021", "name": "Rent"})
    assert created is not None and created.after == {"code": "6021", "name": "Rent"} and created.before == {}


def test_record_rejects_unknown_entities():
    import pytest

    with pytest.raises(ValueError):
        audit.record(_Session(), ent=ENT, company_id=COMPANY, user=USER, entity="nope", entity_id="x",
                     action="update", always=True)
