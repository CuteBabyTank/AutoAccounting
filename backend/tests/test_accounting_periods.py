from datetime import date

import pytest

from app.services.accounting.periods import Period, period_for, quarter_label


def test_calendar_year_quarters():
    assert period_for(date(2026, 1, 5)) == Period(2026, 1, 1)
    assert period_for(date(2026, 3, 31)) == Period(2026, 1, 3)
    assert period_for(date(2026, 8, 14)) == Period(2026, 3, 2)
    assert period_for(date(2026, 12, 31)) == Period(2026, 4, 3)


def test_june_fiscal_year_end():
    assert period_for(date(2026, 7, 1), 6) == Period(2027, 1, 1)
    assert period_for(date(2026, 12, 15), 6) == Period(2027, 2, 3)
    assert period_for(date(2027, 6, 30), 6) == Period(2027, 4, 3)


def test_quarter_labels():
    assert quarter_label(3) == "Q3 (Jul–Sep)"
    assert quarter_label(1, 6) == "Q1 (Jul–Sep)"
    assert quarter_label(4, 6) == "Q4 (Apr–Jun)"


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        period_for(date(2026, 1, 1), 13)
    with pytest.raises(ValueError):
        quarter_label(5)


def test_period_fields_for_optional_date():
    from app.services.accounting.periods import period_fields

    assert period_fields(None, 12) == (None, None, None)
    assert period_fields(date(2026, 7, 2), 6) == (2027, 1, 1)
    assert period_fields(date(2026, 7, 2), 12) == (2026, 3, 1)
