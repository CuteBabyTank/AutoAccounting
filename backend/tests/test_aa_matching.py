

def test_reader_outage_gets_its_own_group_not_unreadable():
    from app.services.accounting.matching import file_detection_from_json, suggest_groups
    down = file_detection_from_json("a", {"error": "Gemini API failed: 402", "reader_down": True})
    blank = file_detection_from_json("b", {"error": "bad image"})
    groups = {g.key: g.file_ids for g in suggest_groups([down, blank])}
    assert groups == {"reader_down": ["a"], "unreadable": ["b"]}


from app.services.accounting.extraction import Detection, Party  # noqa: E402
from app.services.accounting.matching import (  # noqa: E402
    CompanyCandidate, file_detection_from_json, detection_json, file_options, is_ambiguous, match_company,
    suggest_groups,
)

def _det(seller, buyer):
    return Detection("SALES INVOICE", "invoice", seller, buyer, None)


MABUHAY = CompanyCandidate("m-id", "MABUHAY BUILDERS INC.", "201345678")
BAYANIHAN = CompanyCandidate("b-id", "Bayanihan Hardware Trading Corp.", "010234567")
INVOICE = _det(seller=Party("BAYANIHAN HARDWARE TRADING CORP.", "010234567"),
                    buyer=Party("MABUHAY BUILDERS INC.", "201345678"))


def _file(fid, reads, companies):
    matches = [match_company(d.seller, d.buyer, companies) for _, d in reads]
    options = file_options(reads, companies, suggested=matches[0].company_id)
    ambiguous = is_ambiguous(matches, options)
    if ambiguous:
        options = file_options(reads, companies)
    data = detection_json(reads[0][1], matches[0], options, ambiguous, [p for p, _ in reads])
    return file_detection_from_json(fid, data)


def test_one_client_on_the_invoice_is_suggested_and_the_other_party_is_offered():
    f = _file("a", [(1, INVOICE)], [MABUHAY])
    [g] = suggest_groups([f])
    assert g.company_id == "m-id" and g.level == "certain"
    assert [(o["company_id"], o["name"], o["level"]) for o in g.options] == [
        ("m-id", "MABUHAY BUILDERS INC.", "certain"), (None, "BAYANIHAN HARDWARE TRADING CORP.", "new")]


def test_both_parties_are_clients_so_it_asks():
    f = _file("a", [(1, INVOICE)], [MABUHAY, BAYANIHAN])
    [g] = suggest_groups([f])
    assert g.level == "choose" and g.company_id is None
    assert {o["company_id"] for o in g.options} == {"m-id", "b-id"}


def test_pages_pointing_at_different_clients_ask():
    other = _det(seller=Party("Some Supplier", "999888777"), buyer=Party("Bayanihan Hardware", "010234567"))
    first = _det(seller=Party("Some Supplier", "999888777"), buyer=Party("Mabuhay Builders", "201345678"))
    f = _file("a", [(1, first), (7, other)], [MABUHAY, BAYANIHAN])
    assert f.ambiguous
    [g] = suggest_groups([f])
    assert g.level == "choose"


def test_same_client_on_both_pages_stays_certain():
    a = _det(seller=Party("Supplier A", "111222333"), buyer=Party("Mabuhay Builders", "201345678"))
    b = _det(seller=Party("Supplier B", "444555666"), buyer=Party("Mabuhay Builders", "201345678"))
    f = _file("a", [(1, a), (5, b)], [MABUHAY])
    assert not f.ambiguous
    [g] = suggest_groups([f])
    assert g.company_id == "m-id" and g.options[0]["company_id"] == "m-id"


def test_supplier_on_every_page_beats_a_client_on_one_page():
    """Page 1: Bayanihan bills Mabuhay (a client). Page 2: Bayanihan bills someone else. It's Bayanihan's file."""
    p2 = _det(seller=Party("BAYANIHAN HARDWARE TRADING CORP.", "010234567"),
              buyer=Party("KALAYAAN CONSTRUCTION CO.", "305112908"))
    f = _file("a", [(1, INVOICE), (2, p2)], [MABUHAY])
    assert f.ambiguous
    [g] = suggest_groups([f])
    assert g.level == "choose"
    assert g.options[0]["name"] == "BAYANIHAN HARDWARE TRADING CORP." and g.options[0]["company_id"] is None
    assert "m-id" in [o["company_id"] for o in g.options]
