from app.services.accounting.field_hints import doc_hints, norm, parse_hint, prune


def test_parse_hint_maps_chunk_page_and_scales():
    assert parse_hint([2, 100, 200, 300, 250], page_offset=4, first=5, last=6) == {"page": 6, "box": [0.1, 0.2, 0.3, 0.25]}


def test_parse_hint_rejects_bad_boxes():
    for bad in ([1, 300, 200, 100, 250], [1, 0, 0, 900, 50], [9, 1, 1, 2, 2], "x", [1, 1, 1], [1, -5, 0, 10, 10],
                [1, True, 0, 10, 10], [1, "a", 0, 10, 10], None, [1.5, 0, 0, 10, 10]):
        assert parse_hint(bad, page_offset=0, first=1, last=2) is None


def test_doc_hints_marks_computed_and_skips_blank():
    where = {"gross_amount": [1, 100, 100, 200, 120], "vat_amount": [1, 100, 130, 200, 150]}
    out = doc_hints(where, {"gross_amount": "1120.00", "vat_amount": "120.00", "doc_number": ""},
                    {"gross_amount": "1,120.00", "vat_amount": ""}, 0, 1, 1)
    assert out["gross_amount"]["page"] == 1 and out["vat_amount"] == {"computed": True} and "doc_number" not in out


def test_doc_hints_changed_value_is_computed_and_missing_where_gives_nothing():
    out = doc_hints({"gross_amount": [1, 1, 1, 50, 50]}, {"gross_amount": "1000.00", "seller_name": "ACME Corp"},
                    {"gross_amount": "1120.00", "seller_name": "Acme, Corp."}, 0, 1, 1)
    assert out["gross_amount"] == {"computed": True}
    assert "seller_name" not in out   # read as printed, but no box was given: nothing to store
    assert doc_hints("junk", {"a": "x"}, {"a": "x"}, 0, 1, 1) == {}


def test_norm_money_and_text():
    assert norm("1,234.5") == norm("1234.50") == "1234.50"
    assert norm("₱1,234.50") == "1234.50"
    assert norm(" Juan  Dela-Cruz ") == "juandelacruz"


def test_prune_drops_out_of_range_pages_in_both_shapes():
    assert prune({"a": {"page": 3, "box": [0, 0, .1, .1]}, "b": {"computed": True}}, 1, 2) == {"b": {"computed": True}}
    assert prune({"header": {"a": {"page": 1, "box": [0, 0, .1, .1]}}, "rows": [{"q": {"page": 4, "box": [0, 0, .1, .1]}}]}, 1, 2) \
        == {"header": {"a": {"page": 1, "box": [0, 0, .1, .1]}}, "rows": [{}]}
