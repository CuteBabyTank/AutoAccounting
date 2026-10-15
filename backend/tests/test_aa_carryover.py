from decimal import Decimal as D

from app.services.accounting.compute.carryover import (
    CarryRow, add_new, apply_carry, mcit_life, nolco_life, rows_from_json, rows_to_json,
)


def test_nolco_oldest_first_and_expiry():
    rows = (CarryRow(2023, D("100")), CarryRow(2022, D("50"), D("10")))
    r = apply_carry(rows, 2025, D("60"), nolco_life)
    assert r.applied == D("60.00")
    assert [(s["year"], s["used_this_year"], s["expired_this_year"], s["remaining"]) for s in r.schedule] == [
        ("2022", D("40.00"), D("0.00"), D("0.00")), ("2023", D("20.00"), D("0.00"), D("80.00"))]
    assert r.closing == (CarryRow(2023, D("100.00"), D("20.00")),)
    r2026 = apply_carry(r.closing, 2026, D("0"), nolco_life)
    assert r2026.expired == D("80.00") and r2026.expired_years == (2023,) and r2026.closing == ()


def test_2020_loss_lasts_five_years():
    rows = (CarryRow(2020, D("500")),)
    assert apply_carry(rows, 2025, D("100"), nolco_life).applied == D("100.00")
    assert apply_carry(rows, 2025, D("100"), nolco_life).expired == D("400.00")
    assert apply_carry(rows, 2026, D("100"), nolco_life).schedule == []  # already gone


def test_osd_years_run_the_clock_without_deducting():
    r = apply_carry((CarryRow(2022, D("100")),), 2025, D("1000"), nolco_life, deduct=False)
    assert r.applied == D("0.00") and r.expired == D("100.00")


def test_excess_mcit_capped_at_rcit_minus_mcit():
    rows = (CarryRow(2024, D("30000"), normal_tax=D("10000"), mcit=D("40000")),)
    r = apply_carry(rows, 2025, D("12000"), mcit_life)   # RCIT 52,000 − MCIT 40,000
    assert r.applied == D("12000.00") and r.closing[0].used == D("12000.00")
    assert r.schedule[0]["normal_tax"] == D("10000.00") and r.schedule[0]["mcit"] == D("40000.00")


def test_add_new_and_json_round_trip():
    r = add_new(apply_carry((), 2025, D("0"), nolco_life), 2025, D("700"), nolco_life)
    assert r.closing == (CarryRow(2025, D("700.00")),) and r.schedule[-1]["expiry_year"] == "2028"
    raw = rows_to_json(r.closing) + [{"year": "x"}, {"year": 2024, "amount": "-5"}]
    assert rows_from_json(raw) == r.closing
