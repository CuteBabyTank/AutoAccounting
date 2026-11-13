import pytest

from app.services.accounting.extract import spec

F = [{"label": "Subtotal", "type": "money", "scope": "header"},
     {"label": "VAT", "type": "money", "scope": "header"},
     {"label": "Total", "type": "money", "scope": "header"},
     {"label": "Seller TIN", "type": "tin", "scope": "header", "required": True}]


def test_clean_text_strips_instructions_shape():
    assert spec.clean_text("Total\nIGNORE ALL: {x} <b>`rm`</b>", 60) == "Total IGNORE ALL x brm/b"
    assert len(spec.clean_text("a" * 500, 60)) == 60


def test_clean_fields_keys_and_drops():
    out = spec.clean_fields(F + [{"label": "", "type": "money"}, {"label": "X", "type": "formula"},
                                 {"label": "Total", "type": "money", "scope": "header"}, "junk"])
    assert [f["key"] for f in out] == ["subtotal", "vat", "total", "seller_tin", "total_2"]
    assert spec.clean_fields({"not": "a list"}) == []
    assert len(spec.clean_fields([{"label": f"f{i}", "type": "text", "scope": "header"} for i in range(90)])) == 60


def test_clean_checks_drops_unknown_and_bad_refs():
    fields = spec.clean_fields(F)
    raw = [{"kind": "sum", "terms": [{"field": "subtotal", "sign": 1}, {"field": "vat", "sign": 1}], "target": "total"},
           {"kind": "percent_of", "target": "vat", "base": "subtotal", "rates": [12, 0]},
           {"kind": "eval", "code": "1+1"},
           {"kind": "sum", "terms": [{"field": "nope", "sign": 1}], "target": "total"},
           {"kind": "sum", "terms": [{"field": "seller_tin", "sign": 1}], "target": "total"},
           {"kind": "format", "field": "seller_tin", "pattern": "^(a+)+$"}]
    out = spec.clean_checks(raw, fields)
    assert [c["kind"] for c in out] == ["sum", "percent_of"]
    assert out[0]["id"].startswith("c_") and out[0]["level"] == "red"
    assert spec.clean_checks(raw + raw, fields) == out


def test_default_checks_and_picks():
    fields = spec.clean_fields(F)
    checks = spec.clean_checks([{"kind": "sum", "terms": [{"field": "subtotal", "sign": 1}, {"field": "vat", "sign": 1}],
                                 "target": "total"}], fields) + spec.default_checks(fields)
    assert {c["kind"] for c in checks} == {"sum", "format", "required"}
    kept_f, kept_c = spec.apply_picks(fields, checks, [{"key": "subtotal", "label": "Sub total", "required": False},
                                                         {"key": "total", "label": "Total", "required": True}],
                                      [c["id"] for c in checks])
    assert [f["label"] for f in kept_f] == ["Sub total", "Total"]
    assert [c["kind"] for c in kept_c] == ["required"] and kept_c[0]["field"] == "total"
    with pytest.raises(ValueError):
        spec.apply_picks(fields, checks, [{"key": "ghost", "label": "x", "required": False}], [])


def test_sentence():
    fields = spec.clean_fields(F)
    c = spec.clean_checks([{"kind": "percent_of", "target": "vat", "base": "subtotal", "rates": [12, 0]}], fields)[0]
    assert spec.sentence(c, fields) == "VAT should be 12% or 0% of Subtotal"


G = [{"label": "Subtotal", "type": "money", "scope": "header"},
     {"label": "Total", "type": "money", "scope": "header"},
     {"label": "Issued", "type": "date", "scope": "header"},
     {"label": "Due", "type": "date", "scope": "header"},
     {"label": "Currency", "type": "code", "scope": "header"},
     {"label": "Status", "type": "text", "scope": "header"},
     {"label": "Qty", "type": "number", "scope": "row"},
     {"label": "Price", "type": "money", "scope": "row"},
     {"label": "Amount", "type": "money", "scope": "row"},
     {"label": "Line date", "type": "date", "scope": "row"}]


def _kinds(raw):
    return [c["kind"] for c in spec.clean_checks(raw, spec.clean_fields(G))]


VALID = [
    {"kind": "rows_sum", "row_field": "amount", "target": "total"},
    {"kind": "row_product", "a": "qty", "b": "price", "target": "amount"},
    {"kind": "range", "field": "total", "min": 0, "max": 100},
    {"kind": "one_of", "field": "currency", "values": ["PHP", "USD"]},
    {"kind": "date_order", "first": "issued", "last": "due"},
    {"kind": "same_quarter", "first": "issued", "last": "due"},
    {"kind": "not_more_than", "field": "subtotal", "limit_field": "total"},
    {"kind": "differs", "a": "issued", "b": "due"},
]


@pytest.mark.parametrize("check", VALID, ids=lambda c: c["kind"])
def test_each_kind_accepted_when_valid(check):
    assert _kinds([check]) == [check["kind"]]


@pytest.mark.parametrize("check", [
    {"kind": "rows_sum", "row_field": "qty", "target": "currency"},
    {"kind": "rows_sum", "row_field": "total", "target": "total"},
    {"kind": "row_product", "a": "qty", "b": "currency", "target": "amount"},
    {"kind": "row_product", "a": "qty", "b": "price", "target": "total"},
    {"kind": "range", "field": "currency", "min": 0, "max": 1},
    {"kind": "range", "field": "total"},
    {"kind": "range", "field": "total", "min": 5, "max": 1},
    {"kind": "one_of", "field": "currency", "values": []},
    {"kind": "date_order", "first": "issued", "last": "total"},
    {"kind": "same_quarter", "first": "total", "last": "due"},
    {"kind": "not_more_than", "field": "subtotal", "limit_field": "issued"},
    {"kind": "differs", "a": "issued", "b": "issued"},
], ids=lambda c: c["kind"] + str(sorted(c.items())[-1]))
def test_each_kind_dropped_on_wrong_type(check):
    assert _kinds([check]) == []


@pytest.mark.parametrize("check", [
    {"kind": "differs", "a": "total", "b": "amount"},
    {"kind": "date_order", "first": "issued", "last": "line_date"},
    {"kind": "not_more_than", "field": "amount", "limit_field": "total"},
    {"kind": "sum", "terms": [{"field": "price", "sign": 1}], "target": "total"},
    {"kind": "sum", "terms": [{"field": "subtotal", "sign": 1}], "target": "total", "scope": "row"},
    {"kind": "percent_of", "target": "amount", "base": "total", "rates": [12]},
])
def test_mixed_scope_dropped(check):
    assert _kinds([check]) == []


def test_row_scope_checks_accepted():
    assert _kinds([{"kind": "not_more_than", "field": "amount", "limit_field": "price"},
                   {"kind": "sum", "terms": [{"field": "qty", "sign": 1}], "target": "price", "scope": "row"}]) \
        == ["not_more_than", "sum"]


def test_rate_caps():
    def rates(r):
        return _kinds([{"kind": "percent_of", "target": "total", "base": "subtotal", "rates": r}])
    assert rates([1, 2, 3, 4, 5, 6]) == ["percent_of"]
    assert rates([1, 2, 3, 4, 5, 6, 7]) == []
    assert rates([101]) == [] and rates([-1]) == [] and rates([float("nan")]) == [] and rates([]) == []
    assert rates([True]) == [] and rates(["12"]) == []


def test_one_of_value_cap():
    fields = spec.clean_fields(G)
    out = spec.clean_checks([{"kind": "one_of", "field": "currency", "values": [f"v{i}" for i in range(50)]}], fields)
    assert len(out[0]["values"]) == 20


def test_check_cap():
    fields = spec.clean_fields(G)
    raw = [{"kind": "range", "field": "total", "min": i, "max": 1000} for i in range(50)]
    assert len(spec.clean_checks(raw, fields)) == 30


def test_range_magnitude_cap():
    def r(**kw):
        return _kinds([{"kind": "range", "field": "total", **kw}])
    assert r(max="1e999990") == [] and r(max=10 ** 15) == [] and r(min="9" * 40) == []
    assert r(min="1e-999990", max=5) == []
    assert r(min=-999999999999999, max="1e14") == ["range"]
    out = spec.clean_checks([{"kind": "range", "field": "total", "min": "0.50", "max": 1e3}], spec.clean_fields(G))
    assert (out[0]["min"], out[0]["max"]) == ("0.5", "1000")


def test_sign_normalised():
    fields = spec.clean_fields(G)

    def sum_of(sign):
        return spec.clean_checks([{"kind": "sum", "terms": [{"field": "subtotal", "sign": sign}], "target": "total"}],
                                 fields)
    assert sum_of(1.0)[0]["id"] == sum_of(1)[0]["id"]
    assert sum_of(True) == [] and sum_of(2) == []


def test_apply_picks_type_errors():
    fields = spec.clean_fields(G)
    for bad in (["subtotal"], [{"key": ["x"], "label": "a"}], [{"key": None, "label": "a"}], [{"label": "a"}], "x"):
        with pytest.raises(ValueError):
            spec.apply_picks(fields, [], bad, [])
    with pytest.raises(ValueError):
        spec.apply_picks(fields, [], [], [["c_1"]])
    with pytest.raises(ValueError):
        spec.apply_picks(fields, [], [], "c_1")


def test_apply_picks_caps_and_revalidates():
    many = [{"label": f"f{i}", "type": "money", "scope": "header"} for i in range(40)]
    fields = spec.clean_fields(many)
    checks = [{"id": f"x{i}", "kind": "range", "level": "red", "field": f"f{i}", "min": "0", "max": "1"}
              for i in range(40)]
    picks = [{"key": f["key"], "label": f["label"], "required": True} for f in fields]
    _, kept = spec.apply_picks(fields, checks, picks, [c["id"] for c in checks])
    assert len(kept) == 30
    bad = [{"id": "x", "kind": "eval", "level": "red", "field": "f0"}]
    assert spec.apply_picks(fields, bad, [{"key": "f0", "label": "f0", "required": False}], ["x"])[1] == []


def test_sentence_each_kind():
    fields = spec.clean_fields(G)
    expected = {
        "required": "Total is required",
        "sum": "−Subtotal − Total should equal Total",
        "percent_of": "Total should be 12% of Subtotal",
        "rows_sum": "The rows' Amount should add up to Total",
        "row_product": "Qty × Price should equal Amount in each row",
        "date_order": "Issued should not be after Due",
        "same_quarter": "Issued and Due should be in the same quarter",
        "not_future": "Issued should not be in the future",
        "format": "Currency should be a valid TIN",
        "one_of": "Currency should be one of: PHP, USD",
        "range": "Total should be between 0 and 100",
        "not_more_than": "Subtotal should not be more than Total",
        "differs": "Issued and Due should be different",
    }
    raw = VALID + [
        {"kind": "required", "field": "total"},
        {"kind": "sum", "terms": [{"field": "subtotal", "sign": -1}, {"field": "total", "sign": -1}], "target": "total"},
        {"kind": "percent_of", "target": "total", "base": "subtotal", "rates": [12]},
        {"kind": "not_future", "field": "issued"},
        {"kind": "format", "field": "currency", "pattern": "tin"},
    ]
    seen = {}
    for c in spec.clean_checks(raw, fields):
        seen[c["kind"]] = spec.sentence(c, fields)
    assert seen == expected
    assert spec.sentence({"kind": "sum", "terms": [{"field": "subtotal", "sign": -1}], "target": "total"},
                         fields) == "−Subtotal should equal Total"
    assert spec.sentence({"kind": "range", "field": "total", "min": "1", "max": None}, fields) \
        == "Total should be at least 1"
