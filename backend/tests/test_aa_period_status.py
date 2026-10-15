from datetime import datetime, timedelta, timezone

from app.services.accounting.tree import stale_periods

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def test_change_in_same_or_earlier_quarter_makes_output_stale():
    generated = {(2026, 2): T0, (2026, 3): T0}
    changes = {(2026, 2): T0 + timedelta(minutes=5)}
    assert stale_periods(changes, generated) == {(2026, 2), (2026, 3)}


def test_later_or_older_changes_do_not():
    generated = {(2026, 2): T0}
    changes = {(2026, 3): T0 + timedelta(hours=1), (2026, 1): T0 - timedelta(hours=1)}
    assert stale_periods(changes, generated) == set()


def test_quarterly_outputs_ignore_annual_period_changes():
    generated = {(2026, 3): T0}
    assert stale_periods({(2026, 0): T0 + timedelta(minutes=1)}, generated) == set()


def test_annual_stale_rules():
    generated = {(2026, 0): T0, (2026, 2): T0}
    later = T0 + timedelta(minutes=1)
    assert stale_periods({(2026, 4): later}, generated) == {(2026, 0)}           # a quarter of the year
    assert stale_periods({(2025, 1): later}, generated) == {(2026, 0), (2026, 2)}  # earlier year: both chains
    assert stale_periods({(2026, 0): later}, generated) == {(2026, 0)}           # its own inputs
    assert stale_periods({(2027, 1): later}, generated) == set()
    # quarterly versions generated or filed in the year, and the previous year's annual output
    assert stale_periods({}, generated, annual_changes={(2026, 1): later}) == {(2026, 0)}
    assert stale_periods({}, generated, annual_changes={(2025, 0): later}) == {(2026, 0)}
    assert stale_periods({}, generated, annual_changes={(2025, 3): later}) == set()


def test_company_fact_changes_make_every_output_stale():
    generated = {(2026, 0): T0, (2026, 2): T0}
    assert stale_periods({}, generated, always=T0 + timedelta(seconds=1)) == {(2026, 0), (2026, 2)}
    assert stale_periods({}, generated, always=T0 - timedelta(seconds=1)) == set()
