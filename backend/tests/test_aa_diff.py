from decimal import Decimal

from app.services.accounting.compute.engine import QuarterResult
from app.services.accounting.diff import count_changes, diff_snapshots, snapshot
from tests.aa_factories import company


def _result(total="120.00", rows=None):
    rows = rows if rows is not None else [{"key": "555", "name": "A", "taxable": Decimal("1000.00")}]
    return QuarterResult(forms={"2550Q": {"26": Decimal(total), "31A": Decimal("1000.00")}},
                         ledgers={"SLS": rows}, warnings=[], carry_out={}, review_open=0)


def test_snapshot_is_plain_strings_with_company():
    snap = snapshot(_result(), company())
    assert snap["forms"]["2550Q"] == {"26": "120.00", "31A": "1000.00"}
    assert snap["ledgers"]["SLS"] == [{"key": "555", "name": "A", "taxable": "1000.00"}]
    assert snap["company"]["registered_name"] == "Juan's Cloth Trading"


def test_identical_snapshots_have_no_changes():
    a = snapshot(_result(), company())
    diff = diff_snapshots(a, snapshot(_result(), company()))
    assert diff == {"forms": {}, "ledgers": {}} and count_changes(diff) == 0


def test_changed_values_and_rows_are_reported():
    old = snapshot(_result(), company())
    new_rows = [{"key": "555", "name": "A", "taxable": Decimal("1500.00")},
                {"key": "777", "name": "B", "taxable": Decimal("10.00")}]
    new = snapshot(_result(total="180.00", rows=new_rows), company())
    diff = diff_snapshots(old, new)
    assert diff["forms"] == {"2550Q": {"26": ["120.00", "180.00"]}}
    assert diff["ledgers"]["SLS"] == {"added": ["777"], "changed": {"555": {"taxable": ["1000.00", "1500.00"]}},
                                      "removed": []}
    assert count_changes(diff) == 3


def test_removed_rows_and_new_forms():
    old = snapshot(_result(), company())
    new = snapshot(QuarterResult(forms={"2550Q": {"26": Decimal("120.00"), "31A": Decimal("1000.00")},
                                        "COGS": {"cost_of_sales": Decimal("5.00")}},
                                 ledgers={"SLS": []}, warnings=[], carry_out={}, review_open=0), company())
    diff = diff_snapshots(old, new)
    assert diff["forms"] == {"COGS": {"cost_of_sales": [None, "5.00"]}}
    assert diff["ledgers"]["SLS"]["removed"] == ["555"]
    assert count_changes(None) == 0


def test_new_ledger_columns_are_not_changes():
    old = snapshot(_result(rows=[{"key": "555", "name": "A"}]), company())
    new = snapshot(_result(rows=[{"key": "555", "name": "A", "ewt_atc": ""}]), company())
    assert diff_snapshots(old, new)["ledgers"] == {}


def test_metadata_keys_are_not_diffed():
    from app.services.accounting.diff import diff_snapshots
    old = {"forms": {"1601EQ": {"20": "1.00", "_SRC_20": "calculated"}}, "ledgers": {}}
    new = {"forms": {"1601EQ": {"20": "1.00", "_SRC_20": "filed:v2"}}, "ledgers": {}}
    assert diff_snapshots(old, new) == {"forms": {}, "ledgers": {}}
