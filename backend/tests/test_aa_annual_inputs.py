from datetime import date
from decimal import Decimal as D

from app.services.accounting.compute.annual_inputs import (
    AnnualInputs, QuarterSource, annual_inputs_from_json, annual_inputs_to_json, quarter_credits,
)
from app.services.accounting.compute.carryover import CarryRow
from app.services.accounting.compute.due_dates import annual_due_date


def test_parse_with_fallbacks_and_round_trip():
    raw = {"ending_inventory": "1200.5", "q2_paid": "abc", "cit_20_percent": True, "other_reconciling": "-300",
           "opening_nolco": [{"year": 2023, "amount": "5000", "used": "1000"}, {"year": "bad"}]}
    inputs = annual_inputs_from_json(raw)
    assert inputs.ending_inventory == D("1200.50") and inputs.q2_paid is None and inputs.cit_20_percent
    assert inputs.other_reconciling == D("-300.00")
    assert inputs.opening_nolco == (CarryRow(2023, D("5000.00"), D("1000.00")),)
    assert annual_inputs_from_json(annual_inputs_to_json(inputs)) == inputs
    assert annual_inputs_from_json(None) == AnnualInputs()


def test_quarter_credits_filed_latest_override_missing():
    sources = {1: QuarterSource(1, D("1000"), 2, True, 3), 2: QuarterSource(2, D("-50"), 1, False, 1)}
    rows, paid, warnings = quarter_credits(sources, AnnualInputs(q3_paid=D("700")), {1: D("10"), 4: D("40")})
    assert [(r["quarter"], r["source"], r["tax_paid"], r["cwt"]) for r in rows] == [
        ("Q1", "filed v2", D("1000.00"), D("10.00")), ("Q2", "latest v1", D("0.00"), D("0.00")),
        ("Q3", "entered", D("700.00"), D("0.00")), ("Q4", "this return", D("0.00"), D("40.00"))]
    assert paid == D("1700.00")
    assert any("Q1 has v3" in w for w in warnings) and not any("Q3" in w for w in warnings)
    _, _, missing = quarter_credits({}, AnnualInputs(), {})
    assert sum("taken as ₱0" in w for w in missing) == 3


def test_annual_due_dates():
    assert annual_due_date("1702RT", 2026, 12) == date(2027, 4, 15)
    assert annual_due_date("1702RT", 2026, 6) == date(2026, 10, 15)
    assert annual_due_date("1701", 2026) == date(2027, 4, 15)
    assert annual_due_date("1701A", 2025) == date(2026, 4, 15)
    assert annual_due_date("1702RT", 2027, 3) == date(2027, 7, 15)
