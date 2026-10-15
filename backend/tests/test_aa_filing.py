from datetime import datetime, timezone

from app.services.accounting.filing import (
    amended_forms, amends_payment, backfill, credited_output_id, derive, file_all, form_amended, set_form, unfile_all, unset_form,
)

T1 = datetime(2026, 2, 8, 9, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 3, 9, 9, 0, tzinfo=timezone.utc)
EXPECTED = ["2550Q", "0619E-M1", "0619E-M2", "1601EQ"]


def test_set_and_unset_do_not_mutate():
    a = {}
    b = set_form(a, "0619E-M1", "out-1", 1, T1)
    assert a == {} and b == {"0619E-M1": {"output_id": "out-1", "version": 1, "filed_at": T1.isoformat()}}
    assert unset_form(b, "0619E-M1") == {} and "0619E-M1" in b


def test_period_is_filed_only_when_every_expected_form_is():
    filed = set_form({}, "0619E-M1", "out-1", 1, T1)
    assert derive(filed, EXPECTED) == (None, None)
    for form in ("2550Q", "0619E-M2", "1601EQ"):
        filed = set_form(filed, form, "out-3", 3, T2)
    assert derive(filed, EXPECTED) == (T2, "out-3")
    assert derive({}, []) == (None, None)


def test_backfill_marks_everything_from_the_filed_version():
    filed = backfill(EXPECTED, "out-2", 2, T1)
    assert set(filed) == set(EXPECTED) and filed["1601EQ"]["version"] == 2
    assert derive(filed, EXPECTED) == (T1, "out-2")


def test_amended_only_for_newer_versions():
    filed = set_form({}, "2550Q", "out-2", 2, T1)
    assert form_amended(filed, "2550Q", 3) is True
    assert form_amended(filed, "2550Q", 2) is False
    assert form_amended(filed, "1601EQ", 3) is False


def test_a_newer_version_with_the_filed_figures_is_not_amended():
    filed = set_form(set_form({}, "2550Q", "out-2", 2, T1), "1702Q", "out-2", 2, T1)
    same, changed = {"14": "100.00"}, {"14": "120.00"}
    assert form_amended(filed, "2550Q", 3, same, {"14": "100.00"}) is False   # only the books changed
    assert form_amended(filed, "2550Q", 3, changed, {"14": "100.00"}) is True
    assert form_amended(filed, "2550Q", 3, same, None) is True                # filed snapshot unknown
    forms = {"2550Q": same, "1702Q": changed, "1601EQ": changed}
    assert amended_forms(filed, forms, {"2550Q": same, "1702Q": same}) == {"1702Q"}


def test_quarter_button_keeps_forms_already_filed():
    filed = set_form({}, "0619E-M1", "out-2", 2, T1)
    filed = file_all(filed, EXPECTED, "out-6", 6, T2)
    assert filed["0619E-M1"] == {"output_id": "out-2", "version": 2, "filed_at": T1.isoformat()}
    assert filed["2550Q"]["version"] == 6
    assert unfile_all(filed, ["0619E-M1", "2550Q"]) == {k: v for k, v in filed.items() if k not in ("0619E-M1", "2550Q")}


def test_annual_credits_the_version_the_income_tax_return_was_filed_from():
    filed = set_form(set_form({}, "1702Q", "out-3", 3, T1), "1601C-M3", "out-5", 5, T2)
    assert credited_output_id(filed, "1702Q", "out-5") == "out-3"
    assert credited_output_id(set_form({}, "2550Q", "out-3", 3, T1), "1702Q", None) is None   # ITR not filed yet
    assert credited_output_id({}, "1702Q", "out-2") == "out-2"                                  # filed before per-form


def test_only_returns_with_a_paid_on_original_input_make_a_version_amended():
    assert amends_payment(set_form({}, "0619E-M1", "out-1", 1, T1)) is False
    assert amends_payment(set_form({}, "1601C-M1", "out-1", 1, T1)) is False
    for form in ("2550Q", "2551Q", "1701Q", "1702Q", "1601EQ"):
        assert amends_payment(set_form({}, form, "out-1", 1, T1)) is True


def test_backfill_only_marks_forms_the_filed_version_had():
    filed = backfill(EXPECTED + ["1601C-M1"], "out-2", 2, T1, available=EXPECTED)
    assert set(filed) == set(EXPECTED)


def test_paid_on_is_stored_with_the_filed_entry():
    from datetime import date

    filed = set_form({}, "2550Q", "out-2", 2, T1, paid_on=date(2026, 1, 25))
    assert filed["2550Q"]["paid_on"] == "2026-01-25"
    filed = file_all(filed, EXPECTED, "out-3", 3, T2, paid_on=date(2026, 3, 1))
    assert filed["2550Q"]["paid_on"] == "2026-01-25" and filed["1601EQ"]["paid_on"] == "2026-03-01"


def test_filed_on_cannot_be_in_the_future():
    from datetime import date, timedelta

    import pytest
    from pydantic import ValidationError

    from app.schemas.accounting import FiledIn, FormFiledIn

    assert FormFiledIn(filed=True, filed_on=date(2026, 1, 25)).filed_on == date(2026, 1, 25)
    assert FiledIn(filed=True).filed_on is None
    tomorrow = date.today() + timedelta(days=2)
    with pytest.raises(ValidationError):
        FormFiledIn(filed=True, filed_on=tomorrow)
    with pytest.raises(ValidationError):
        FiledIn(filed=True, filed_on=tomorrow)
