from app.services.accounting.extraction import parse_extraction
from app.services.accounting.parsing import normalize_tin, printed_branch


def test_printed_branch_keeps_the_digits_as_printed():
    assert printed_branch("VAT REG TIN: 010-234-567-000") == "000"
    assert printed_branch("010-234-567-00000") == "00000"
    assert printed_branch("010234567") == ""
    assert printed_branch("") == ""
    assert normalize_tin("010-234-567-000") == ("010234567", "00000")  # the forms still get the 5-digit code


def test_extraction_keeps_the_branch_beside_the_tin():
    [doc] = parse_extraction('[{"seller": {"tin": "010-234-567-000"}, "buyer": {"tin": "201-345-678"}}]')
    assert (doc.seller.tin, doc.seller.printed_branch) == ("010234567", "000")
    assert (doc.buyer.tin, doc.buyer.printed_branch) == ("201345678", "")


def test_backfill_reads_the_branch_only_while_the_tin_is_unchanged():
    from app.services.accounting.books.tin_branches import branch_from_raw

    raw = {"seller": {"tin": "010-234-567-000"}, "buyer": {"tin": "201-345-678-00001"}}
    assert branch_from_raw(raw, "seller", "010234567") == "000"
    assert branch_from_raw(raw, "buyer", "201345678") == "00001"
    assert branch_from_raw(raw, "seller", "999999999") == ""   # a person corrected the TIN
    assert branch_from_raw(None, "seller", "010234567") == ""
