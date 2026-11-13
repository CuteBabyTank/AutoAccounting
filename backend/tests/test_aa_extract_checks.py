from datetime import date
from decimal import Decimal as D

import pytest

from app.services.accounting.extract import builtins, checks, spec

FIELDS = spec.clean_fields([
    {"label": "Subtotal", "type": "money", "scope": "header"}, {"label": "VAT", "type": "money", "scope": "header"},
    {"label": "Total", "type": "money", "scope": "header"}, {"label": "Date", "type": "date", "scope": "header"},
    {"label": "Seller TIN", "type": "tin", "scope": "header"},
    {"label": "Qty", "type": "number", "scope": "row"}, {"label": "Price", "type": "money", "scope": "row"},
    {"label": "Amount", "type": "money", "scope": "row"}])
CHECKS = spec.clean_checks([
    {"kind": "sum", "terms": [{"field": "subtotal", "sign": 1}, {"field": "vat", "sign": 1}], "target": "total"},
    {"kind": "percent_of", "target": "vat", "base": "subtotal", "rates": [12, 0]},
    {"kind": "row_product", "a": "qty", "b": "price", "target": "amount", "level": "yellow"},
    {"kind": "rows_sum", "row_field": "amount", "target": "subtotal"},
    {"kind": "format", "field": "seller_tin", "pattern": "tin"},
    {"kind": "not_future", "field": "date"}], FIELDS)
TODAY = date(2026, 11, 13)


def flags(header, rows=()):
    values, bad = checks.clean_record({**header, "rows": list(rows)}, FIELDS)
    return checks.run_checks(values, FIELDS, CHECKS, TODAY, bad_cells=bad)


@pytest.mark.parametrize("text,expected", [
    ("₱1,234.50", ("1234.50", True)), ("(1,234.50)", ("-1234.50", True)), ("1,234.50-", ("-1234.50", True)),
    ("", ("", True)), (None, ("", True)), (1234.5, ("1234.50", True)), ("N/A", ("N/A", False))])
def test_money(text, expected):
    assert checks.clean_value(text, "money") == expected


@pytest.mark.parametrize("text", ["12/31/2026", "Dec 31, 2026", "2026-12-31"])
def test_dates(text):
    assert checks.clean_value(text, "date") == ("2026-12-31", True)


def test_grade():
    assert checks.grade(D("0.05"), D("1000")) == "pass"
    assert checks.grade(D("0.90"), D("500")) == "yellow"
    assert checks.grade(D("4"), D("5000")) == "yellow"      # 0.1% of 5000 = 5
    assert checks.grade(D("6"), D("5000")) == "red"


def test_vat_12_passes_and_zero_vat_passes():
    assert flags({"subtotal": "1000", "vat": "120", "total": "1120"}) == []
    assert flags({"subtotal": "1000", "vat": "0", "total": "1000"}) == []
    assert flags({"subtotal": "1000", "vat": "", "total": "1000"}) == []


def test_wrong_vat_and_wrong_total_are_red():
    out = flags({"subtotal": "1000", "vat": "50", "total": "1050"})
    assert [(f["level"], f["cells"][0]["key"]) for f in out] == [("red", "vat")]
    out = flags({"subtotal": "1000", "vat": "120", "total": "1200"})
    assert out[0]["level"] == "red" and {c["key"] for c in out[0]["cells"]} == {"subtotal", "vat", "total"}


def test_inclusive_vat():
    f = spec.clean_fields([{"label": "VAT", "type": "money", "scope": "header"},
                           {"label": "Total", "type": "money", "scope": "header"}])
    c = spec.clean_checks([{"kind": "percent_of", "target": "vat", "base": "total", "rates": [12, 0],
                            "inclusive": True}], f)
    values, _ = checks.clean_record({"vat": "120", "total": "1120"}, f)
    assert checks.run_checks(values, f, c, TODAY) == []


def test_rows_blank_fields_skip_and_cells_point_at_rows():
    assert flags({"subtotal": "", "vat": "", "total": ""}) == []          # nothing to check
    out = flags({"subtotal": "300"}, [{"qty": "2", "price": "100", "amount": "200"},
                                      {"qty": "1", "price": "100", "amount": "150"}])
    kinds = {(f["level"], f["cells"][0]["row"]) for f in out}
    assert ("yellow", 1) in kinds                                          # row 2: 1 x 100 != 150
    assert any(f["level"] == "red" and f["cells"][-1]["key"] == "subtotal" for f in out)   # 350 != 300


def test_bad_cells_tin_future_date_and_confidence():
    out = flags({"total": "abc", "seller_tin": "12345", "date": "2027-01-05"})
    assert {f["cells"][0]["key"] for f in out} == {"total", "seller_tin", "date"}
    values, _ = checks.clean_record({}, FIELDS)
    low = checks.run_checks(values, FIELDS, [], TODAY, confidence=55)
    assert low == [{"check_id": "confidence", "level": "yellow",
                    "message": "The reader was not sure about this document", "cells": []}]


def test_clean_record_survives_junk():
    values, bad = checks.clean_record(["not", "a", "dict"], FIELDS)
    assert values == {"header": {k: "" for k in ("subtotal", "vat", "total", "date", "seller_tin")}, "rows": []}
    values, _ = checks.clean_record({"hack": 1, "rows": [{"qty": "1"}] * 900}, FIELDS)
    assert "hack" not in values["header"] and len(values["rows"]) == 500


def make(raw_fields, raw_checks, header, rows=()):
    f = spec.clean_fields(raw_fields)
    c = spec.clean_checks(raw_checks, f)
    values, bad = checks.clean_record({**header, "rows": list(rows)}, f)
    return checks.run_checks(values, f, c, TODAY, bad_cells=bad)


DATES = [{"label": "Start", "type": "date"}, {"label": "End", "type": "date"}]


def test_date_order_and_same_quarter():
    order = [{"kind": "date_order", "first": "start", "last": "end"}]
    assert make(DATES, order, {"start": "2026-01-01", "end": "2026-03-31"}) == []
    out = make(DATES, order, {"start": "2026-04-01", "end": "2026-03-31"})
    assert [c["key"] for c in out[0]["cells"]] == ["start", "end"] and out[0]["level"] == "red"
    quarter = [{"kind": "same_quarter", "first": "start", "last": "end"}]
    assert make(DATES, quarter, {"start": "2026-01-01", "end": "2026-03-31"}) == []
    assert len(make(DATES, quarter, {"start": "2026-03-31", "end": "2026-04-01"})) == 1
    assert make(DATES, quarter, {"start": "2026-03-31", "end": ""}) == []


def test_one_of_range_not_more_than_differs():
    fs = [{"label": "Terms", "type": "text"}, {"label": "Amt", "type": "money"}, {"label": "Max", "type": "money"},
          {"label": "A TIN", "type": "tin"}, {"label": "B TIN", "type": "tin"}]
    cs = [{"kind": "one_of", "field": "terms", "values": ["Cash", "30 days"]},
          {"kind": "range", "field": "amt", "min": "0"},
          {"kind": "not_more_than", "field": "amt", "limit_field": "max"},
          {"kind": "differs", "a": "a_tin", "b": "b_tin"}]
    good = {"terms": "cash", "amt": "5", "max": "10", "a_tin": "111-111-111", "b_tin": "222-222-222"}
    assert make(fs, cs, good) == []
    bad = {"terms": "net 60", "amt": "-5", "max": "-10", "a_tin": "111-111-111-000", "b_tin": "111111111000"}
    out = make(fs, cs, bad)
    assert [f["cells"][0]["key"] for f in out] == ["terms", "amt", "amt", "a_tin"]
    assert make(fs, cs, {"terms": "", "amt": "", "max": "", "a_tin": "", "b_tin": ""}) == []


def test_required_header_and_row():
    fs = [{"label": "Name", "type": "text", "required": True},
          {"label": "Item", "type": "text", "scope": "row", "required": True}]
    cs = [{"kind": "required", "field": "name"}, {"kind": "required", "field": "item"}]
    out = make(fs, cs, {"name": ""}, [{"item": "x"}, {"item": " "}])
    assert [(f["cells"][0]["key"], f["cells"][0]["row"]) for f in out] == [("name", None), ("item", 1)]


def test_format_zip_atc_and_tin_lengths():
    fs = [{"label": "Zip", "type": "text"}, {"label": "Atc", "type": "code"}, {"label": "TIN", "type": "tin"}]
    cs = [{"kind": "format", "field": "zip", "pattern": "zip"}, {"kind": "format", "field": "atc", "pattern": "atc"},
          {"kind": "format", "field": "tin", "pattern": "tin"}]
    assert make(fs, cs, {"zip": "1200", "atc": "wi010", "tin": "123-456-789-00000"}) == []
    out = make(fs, cs, {"zip": "12", "atc": "ZZ999", "tin": "1234567890"})
    assert [f["cells"][0]["key"] for f in out] == ["zip", "atc", "tin"]


@pytest.mark.parametrize("text", ["1e999999", "NaN", "Infinity", "-Infinity", "9" * 300, "1e15", "9" * 20])
def test_hostile_numbers_are_unreadable(text):
    for kind in ("money", "number", "percent"):
        value, ok = checks.clean_value(text, kind)
        assert ok is False and len(value) <= 200
    fs = spec.clean_fields([{"label": "Total", "type": "money"}])
    cs = spec.clean_checks([{"kind": "range", "field": "total", "min": "0"}], fs)
    values, bad = checks.clean_record({"total": text}, fs)
    out = checks.run_checks(values, fs, cs, TODAY, bad_cells=bad)
    assert [f["level"] for f in out] == ["red"] and out[0]["cells"] == [{"key": "total", "row": None}]


def test_other_types():
    assert checks.clean_value("12.50 %", "percent") == ("12.5", True)
    assert checks.clean_value("2", "number") == ("2", True)
    assert checks.clean_value(float("nan"), "money") == ("nan", False)
    assert checks.clean_value("Yes", "boolean") == ("true", True)
    assert checks.clean_value("no", "boolean") == ("false", True)
    assert checks.clean_value("maybe", "boolean") == ("maybe", False)
    assert checks.clean_value("123-456-789-000", "tin") == ("123456789000", True)
    assert checks.clean_value("n/a", "tin") == ("n/a", False)
    assert checks.clean_value("  a   b ", "text") == ("a b", True)
    assert checks.clean_value("1" * 201, "date")[1] is False
    assert checks.clean_value("2026-02-30", "date") == ("2026-02-30", False)


# ── blank terms count as 0; unreadable operands skip ──────────────────────

R_FIELDS = builtins.BUILTINS["receipt"]["fields"]
R_SUM = [c for c in builtins.BUILTINS["receipt"]["checks"] if c["kind"] == "sum"]


def receipt(**header):
    values, bad = checks.clean_record(header, R_FIELDS)
    return checks.run_checks(values, R_FIELDS, R_SUM, TODAY, bad_cells=bad)


def test_sum_counts_blank_terms_as_zero():
    out = receipt(vatable_sales="1000", vat_amount="120", total_amount="1200")   # exempt / zero-rated blank
    assert [f["level"] for f in out] == ["red"]
    assert [c["key"] for c in out[0]["cells"]] == ["vatable_sales", "vat_amount", "total_amount"]
    assert receipt(vatable_sales="1000", vat_amount="120", total_amount="1120") == []


def test_sum_skips_when_every_term_or_the_target_is_blank():
    assert receipt(total_amount="1200") == []
    assert receipt(vatable_sales="1000", vat_amount="120") == []


def test_sum_skips_on_an_unreadable_term():
    out = receipt(vatable_sales="1000", vat_amount="abc", total_amount="1200")
    assert [f["check_id"] for f in out] == ["unreadable"]


def test_rows_sum_blank_rows_count_as_zero_and_unreadable_skips():
    out = flags({"subtotal": "300"}, [{"amount": "200"}, {"amount": ""}, {"amount": "150"}])
    rows_sum = [f for f in out if f["cells"][-1]["key"] == "subtotal"]
    assert rows_sum and [c["row"] for c in rows_sum[0]["cells"][:-1]] == [0, 2]
    assert flags({"subtotal": "350"}, [{"amount": "200"}, {"amount": ""}, {"amount": "150"}]) == []
    out = flags({"subtotal": "300"}, [{"amount": "200"}, {"amount": "x"}])
    assert [f["check_id"] for f in out] == ["unreadable"]


def test_atc_ignores_spaces_hyphens_and_case():
    fs = spec.clean_fields([{"label": "ATC", "type": "code", "scope": "header"}])
    cs = spec.clean_checks([{"kind": "format", "field": "atc", "pattern": "atc"}], fs)
    for text in ("WC 158", "wc-158", "Wc158"):
        values, _ = checks.clean_record({"atc": text}, fs)
        assert checks.run_checks(values, fs, cs, TODAY) == [], text
    values, _ = checks.clean_record({"atc": "WC 999"}, fs)
    assert len(checks.run_checks(values, fs, cs, TODAY)) == 1


def test_control_characters_are_never_stored():
    assert checks.clean_value("AB\x00C\x07", "text") == ("ABC", True)
    assert checks.clean_value("A\x1fB\tC", "text") == ("A B C", True)
