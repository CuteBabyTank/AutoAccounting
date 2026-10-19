"""Hand edits to returns before export, and editable certificate fields (2307, 2316)."""

from decimal import Decimal

import pytest

from app.schemas.form_filler import FilledForm, LineItem, Payee, Payor
from app.services.accounting.certificate_edits import apply_2307, apply_2316, fields_2307, fields_2316
from app.services.accounting.compute.alphalist import Employee, compute_employee
from app.services.accounting.form_edits import (
    apply_edits, clean_value, dropped_edits_warning, edits_warning, is_amount, merge_edited, parse_amount,
)

VAT = {"15": "10486.80", "26": "10486.80", "31A": "117390.00", "_YEAR": "2026", "note": ""}


def test_amounts_are_recognised_by_their_stored_shape():
    assert is_amount("10486.80") and is_amount("0") and is_amount("-5.00")
    assert not is_amount("") and not is_amount("X") and not is_amount("NaN")


@pytest.mark.parametrize("text,value", [("1,234.50", Decimal("1234.50")), ("(50)", Decimal("-50")),
                                        ("", Decimal("0")), ("₱ 12", Decimal("12"))])
def test_parse_amount_takes_what_people_type(text, value):
    assert parse_amount(text) == value


@pytest.mark.parametrize("text", ["abc", "1e400", "Infinity"])
def test_parse_amount_refuses_non_numbers(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_an_edited_figure_keeps_the_stored_decimal_places():
    assert clean_value("10486.80", "10,500") == "10500.00"
    assert clean_value("117390", "117,400.4") == "117400"  # whole-peso forms stay whole
    assert clean_value("", "  some   text ") == "some text"


def test_apply_edits_returns_only_real_changes():
    assert apply_edits(VAT, {"15": "10,486.80", "26": "10500"}) == {"26": "10500.00"}


def test_apply_edits_refuses_unknown_items_and_bad_amounts():
    with pytest.raises(ValueError, match="no item 99"):
        apply_edits(VAT, {"99": "1"})
    with pytest.raises(ValueError, match="Item 26"):
        apply_edits(VAT, {"26": "ten"})


def test_merge_edited_keeps_the_engine_figure_and_drops_items_set_back():
    first = merge_edited({}, VAT, {"26": "10500.00"})
    assert first == {"26": "10486.80"}
    after_second = {**VAT, "26": "10500.00"}
    assert merge_edited(first, after_second, {"26": "10600.00"}) == {"26": "10486.80"}
    assert merge_edited(first, after_second, {"26": "10486.80"}) == {}


def test_warnings_name_the_edited_items():
    edited = {"2550Q": {"26": "10486.80", "15": "1.00"}, "1601EQ": {}}
    assert edits_warning(3, edited).startswith("Edited by hand in v3: 2550Q items 26, 15.")
    assert "v3 had hand edits (2550Q items 26, 15)" in dropped_edits_warning(3, edited)
    assert edits_warning(3, {"2550Q": {}}) is None


def _cert() -> FilledForm:
    return FilledForm(
        excel_row=0, payee=Payee(tin="12345678900000", name="Santos Hardware", registered_address="Manila",
                                 zip_code=""),
        payor=Payor(tin="98765432100000", name="Client Inc", registered_address="Pasig", zip_code="1600"),
        period_from="07/01/2026", period_to="09/30/2026",
        ewt=[LineItem(description="Rental", atc="WI100", m1=1000, total=1000, tax_withheld=50)],
    )


def test_2307_fields_cover_the_payee_period_and_lines():
    fields = {f["key"]: f for f in fields_2307(_cert())}
    assert fields["payee.name"]["value"] == "Santos Hardware"
    assert fields["ewt.0.tax_withheld"] == {"key": "ewt.0.tax_withheld", "label": "Line 1 tax withheld",
                                            "value": "50.00", "kind": "amount"}


def test_apply_2307_changes_only_the_edited_fields():
    out = apply_2307(_cert(), {"payee.registered_address": "  Quezon   City ", "ewt.0.tax_withheld": "55",
                               "period_to": "09/30/2026"})
    assert out.payee.registered_address == "Quezon City"
    assert out.ewt[0].tax_withheld == 55.0 and out.ewt[0].total == 1000
    assert out.payor.name == "Client Inc"


@pytest.mark.parametrize("edits", [{"payor.name": "X"}, {"ewt.3.atc": "WI"}, {"period_from": "2026-07-01"},
                                   {"ewt.0.total": "lots"}])
def test_apply_2307_refuses_what_it_cannot_place(edits):
    with pytest.raises(ValueError):
        apply_2307(_cert(), edits)


def _employee():
    return compute_employee(Employee(id="e1", tin="123456789", last_name="Cruz", first_name="Ana",
                                     address="Makati", amounts={"t_basic": Decimal("400000")}), 2026)


def test_2316_fields_list_text_then_amounts():
    fields = {f["key"]: f for f in fields_2316(_employee())}
    assert fields["4"]["value"] == "Cruz, Ana" and fields["4"]["kind"] == "text"
    assert fields["21"]["kind"] == "amount" and fields["21"]["value"] == "400000.00"
    assert "9" not in fields  # not a minimum wage earner: no SMW boxes


def test_apply_2316_edits_a_copy():
    c = _employee()
    out = apply_2316(c, {"6": "Taguig", "25A": "1,000"})
    assert out.form["6"] == "Taguig" and out.form["25A"] == Decimal("1000.00")
    assert c.form["6"] == "Makati"
    with pytest.raises(ValueError):
        apply_2316(c, {"7": "1990-01-01"})
    with pytest.raises(ValueError):
        apply_2316(c, {"nope": "1"})
