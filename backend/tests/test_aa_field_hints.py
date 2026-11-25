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


def test_document_hints_maps_reader_keys_to_columns():
    from datetime import date
    from decimal import Decimal

    from app.services.accounting.field_hints import document_hints

    raw = {"doc_number": "SI-0042", "date": "2026-11-03", "gross_amount": "1,120.00", "vat_amount": 120,
           "seller": {"name": "Acme Hardware", "tin": "010-234-567-000"}, "buyer": {"name": ""},
           "where": {"doc_number": [1, 600, 50, 800, 80], "doc_date": [1, 600, 90, 800, 110],
                     "gross_amount": [1, 600, 800, 800, 830], "seller_tin": [1, 100, 120, 300, 140],
                     "seller_name": [1, 100, 60, 400, 100]}}
    fields = {"doc_number": "SI-0042", "doc_date": date(2026, 11, 3), "gross_amount": Decimal("1120.00"),
              "vat_amount": Decimal("120.00"), "vatable_amount": Decimal("1000.00"), "seller_name": "Acme Hardware",
              "seller_tin": "010234567", "buyer_name": "", "page_start": 1, "page_end": 1}
    out = document_hints(raw, page_offset=0, fields=fields)
    assert out["doc_number"]["page"] == 1 and out["doc_date"]["page"] == 1 and out["gross_amount"]["page"] == 1
    assert out["seller_tin"]["box"] == [0.1, 0.12, 0.3, 0.14]       # 9-digit base of the printed TIN: same value
    assert out["vatable_amount"] == {"computed": True}              # not read: worked out by the cleaner
    assert "vat_amount" not in out and "buyer_name" not in out     # read but no box / blank
    assert document_hints(None, 0, fields)["gross_amount"] == {"computed": True}


def test_parse_extraction_keeps_the_chunk_offset_and_prompt_asks_for_where():
    from app.services.accounting.extraction import EXTRACT_PROMPT, parse_extraction

    raw = '{"documents": [{"page_start": 2, "gross_amount": "1,120.00", "where": {"gross_amount": [2, 500, 800, 700, 830]}}]}'
    doc = parse_extraction(raw, page_offset=2, chunk_pages=2)[0]
    assert doc.page_offset == 2 and doc.page_start == 4
    assert '"where"' in EXTRACT_PROMPT and "0-1000" in EXTRACT_PROMPT
