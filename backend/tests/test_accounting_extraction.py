from datetime import date
from decimal import Decimal

from app.services.accounting.extraction import EXTRACT_PROMPT, Party, extract_prompt, parse_detection, parse_extraction


def test_parse_detection_reads_parties():
    raw = (
        '```json\n{"document_title": "SALES INVOICE", "kind": "invoice",'
        ' "seller": {"name": "Cebu Fabric Supply", "tin": "111-222-333-000"},'
        ' "buyer": {"name": "Juan\'s Cloth Trading", "tin": "123-456-789-00000"},'
        ' "date": "2026-08-14"}\n```'
    )
    det = parse_detection(raw)
    assert det.kind == "invoice"
    assert det.seller == Party(name="Cebu Fabric Supply", tin="111222333", branch="00000")
    assert det.buyer.tin == "123456789"
    assert det.doc_date == date(2026, 8, 14)


def test_parse_detection_garbage_is_empty():
    det = parse_detection("I could not read this page.")
    assert det.kind == "other"
    assert det.seller == Party() and det.buyer == Party()
    assert det.doc_date is None


def test_parse_extraction_multiple_documents_with_page_offset():
    raw = """{"documents": [
      {"page_start": 1, "page_end": 1, "document_title": "OFFICIAL RECEIPT", "kind": "receipt",
       "doc_number": "0042", "date": "2026-07-03",
       "seller": {"name": "Max's Restaurant", "tin": "222-333-444-000", "address": "Makati", "vat_registered": true},
       "buyer": {"name": "", "tin": "", "address": ""},
       "gross_amount": 1120, "vatable_amount": 1000, "vat_amount": 120, "exempt_amount": 0,
       "zero_rated_amount": 0, "withholding_amount": 0, "nature": "services",
       "expense_account": "representation", "confidence": 88},
      {"page_start": 2, "page_end": 3, "document_title": "SALES INVOICE", "kind": "invoice",
       "doc_number": "SI-7", "date": "2026-07-09", "seller": {"name": "A"}, "buyer": {"name": "B"},
       "gross_amount": "5,600.00", "nature": "goods_for_resale", "expense_account": "nonsense",
       "confidence": 120}
    ]}"""
    docs = parse_extraction(raw, page_offset=10, chunk_pages=3)
    assert [(d.page_start, d.page_end) for d in docs] == [(11, 11), (12, 13)]
    first, second = docs
    assert first.seller_vat_registered is True
    assert first.vat_amount == Decimal("120.00")
    assert first.expense_account == "representation"
    assert second.gross_amount == Decimal("5600.00")
    assert second.expense_account == "other"
    assert second.confidence == 100.0
    assert second.seller_vat_registered is None


def test_parse_extraction_clamps_pages_to_chunk():
    raw = '{"documents": [{"page_start": 7, "page_end": 2, "kind": "receipt"}]}'
    [doc] = parse_extraction(raw, page_offset=0, chunk_pages=3)
    assert (doc.page_start, doc.page_end) == (3, 3)


def test_parse_extraction_garbage_returns_empty():
    assert parse_extraction("Sorry, nothing here") == []
    assert parse_extraction('{"documents": "none"}') == []
    assert parse_extraction("") == []


def test_parse_extraction_unknown_kind_and_nature_become_other():
    [doc] = parse_extraction('[{"kind": "spaceship", "nature": "magic"}]')
    assert doc.kind == "other"
    assert doc.nature == "other"


def test_extract_prompt_tells_the_ai_who_the_client_is():
    p = extract_prompt("Juan's Cloth Trading", "123456789", "trading")
    assert p.startswith(EXTRACT_PROMPT)
    assert "Juan's Cloth Trading (TIN 123456789)" in p and "a trading business" in p
    assert "a services business" in extract_prompt("Reyes CPAs", "", "services")
    assert "(TIN" not in extract_prompt("Reyes CPAs", "", "services").split(EXTRACT_PROMPT)[1]


def test_extract_prompt_defines_total_and_splits_rescans():
    assert "BEFORE any withholding tax" in EXTRACT_PROMPT
    assert "a second copy or a rescan" in EXTRACT_PROMPT
