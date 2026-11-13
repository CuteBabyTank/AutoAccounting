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
    import pytest
    with pytest.raises(ValueError):
        spec.apply_picks(fields, checks, [{"key": "ghost", "label": "x", "required": False}], [])


def test_sentence():
    fields = spec.clean_fields(F)
    c = spec.clean_checks([{"kind": "percent_of", "target": "vat", "base": "subtotal", "rates": [12, 0]}], fields)[0]
    assert spec.sentence(c, fields) == "VAT should be 12% or 0% of Subtotal"
