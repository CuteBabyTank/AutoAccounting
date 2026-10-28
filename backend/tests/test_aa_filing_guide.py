import pytest

from app.services.accounting.filing_guide import guide, scope_forms, scope_label, scope_note, source_line

ALL = ["2550Q", "1702Q", "0619E-M1", "0619E-M2", "1601EQ", "1601C-M1", "1601C-M2", "1601C-M3"]


def test_monthly_scopes():
    assert scope_forms(ALL, "M1") == ["0619E-M1", "1601C-M1"]
    assert scope_forms(ALL, "M2") == ["0619E-M2", "1601C-M2"]
    assert scope_forms(ALL, "M3") == ["1601C-M3"]          # month 3 EWT is on the 1601-EQ


def test_quarter_scope_only_quarterly_returns():
    assert scope_forms(ALL, "Q") == ["2550Q", "1702Q", "1601EQ"]
    assert scope_forms(["2551Q"], "Q") == ["2551Q"]


def test_scope_only_narrows_expected():
    assert scope_forms(["2550Q", "1702Q"], "M1") == []


def test_unknown_scope():
    with pytest.raises(ValueError):
        scope_forms(ALL, "M4")


def test_labels_use_calendar_months():
    assert scope_label("M1", 2026, 1, 12) == "Month 1: Jan 2026"
    assert scope_label("M3", 2026, 3, 12) == "Month 3: Sep 2026"
    assert scope_label("Q", 2026, 1, 12).startswith("Quarter: Q1")
    assert scope_label("M1", 2026, 1, 6) == "Month 1: Jul 2025"   # FY ending June: Q1 starts July of the prior year


def test_notes():
    assert "annual" in scope_note("Q", 4, ["2550Q"]).lower()
    assert scope_note("M1", 1, []).startswith("No monthly returns")
    assert scope_note("Q", 2, ["2550Q"]) is None


def test_guide_lines():
    assert "months 1 and 2" in guide("0619E-M1")
    assert "every month" in guide("1601C-M3")
    assert "0619-Es" in guide("1601EQ")


def test_1601eq_source_line():
    values = {"20": "500.00", "21": "1000.00", "_SRC_20": "filed:v3", "_SRC_21": "calculated"}
    assert source_line("1601EQ", values) == ("Item 20 (month 1) ₱500.00 from filed 0619-E v3 · "
                                             "Item 21 (month 2) ₱1,000.00 calculated")
    assert source_line("1601EQ", {"20": "0", "21": "0"}) is None   # old snapshot
    assert source_line("2550Q", {}) is None


def test_empty_month_3_points_to_the_1601eq():
    note = scope_note("M3", 3, [])
    assert "1601-EQ" in note and "withholding agent" not in note
