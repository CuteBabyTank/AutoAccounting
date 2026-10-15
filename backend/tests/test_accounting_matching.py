from app.services.accounting.extraction import Detection, Party
from app.services.accounting.matching import (
    CompanyCandidate,
    FileDetection,
    MatchResult,
    detection_json,
    file_detection_from_json,
    match_company,
    normalize_name,
    suggest_groups,
)

JUAN = CompanyCandidate("c1", "Juan's Cloth Trading, Inc.", "123456789", ("JCT",))
MARIA = CompanyCandidate("c2", "Maria's Bakery", "987654321")


def test_normalize_name_strips_punctuation_and_legal_suffixes():
    assert normalize_name("Juan's Cloth Trading, Inc.") == "juans cloth trading"
    assert normalize_name("A & B Corp.") == "a and b"


def test_tin_match_is_certain_on_either_side():
    m = match_company(Party(name="Cebu Fabric", tin="111222333"), Party(tin="123456789"), [JUAN, MARIA])
    assert m == MatchResult("c1", "certain", 1.0, "buyer")
    m2 = match_company(Party(tin="987654321"), Party(), [JUAN, MARIA])
    assert (m2.company_id, m2.side) == ("c2", "seller")


def test_name_match_is_likely_and_uses_aliases():
    m = match_company(Party(name="Juans Cloth Trading"), Party(), [JUAN, MARIA])
    assert m.company_id == "c1" and m.level == "likely" and m.score >= 0.85
    assert match_company(Party(), Party(name="JCT"), [JUAN]).company_id == "c1"


def test_weak_name_match_is_unknown():
    m = match_company(Party(name="Jollibee Foods"), Party(), [JUAN, MARIA])
    assert m.company_id is None and m.level == "unknown"


def _fd(fid, seller=Party(), buyer=Party(), match=MatchResult(None, "unknown", 0.0, None)):
    return FileDetection(fid, seller, buyer, match)


def test_suggest_groups_groups_matched_and_unknown_files():
    certain = MatchResult("c1", "certain", 1.0, "buyer")
    likely = MatchResult("c1", "likely", 0.9, "buyer")
    new_co = Party(name="Reyes Logistics", tin="555666777")
    files = [
        _fd("f1", buyer=Party(tin="123456789"), match=certain),
        _fd("f2", buyer=Party(name="Juans Cloth"), match=likely),
        _fd("f3", seller=Party(name="Shell"), buyer=new_co),
        _fd("f4", seller=Party(name="Petron"), buyer=new_co),
        _fd("f5", seller=Party(name="Max's Restaurant")),
    ]
    groups = suggest_groups(files)
    assert [g.key for g in groups] == ["company:c1", "new:555666777", "new:"]
    assert groups[0].file_ids == ["f1", "f2"] and groups[0].level == "likely"
    assert groups[1].detected == new_co and groups[1].file_ids == ["f3", "f4"]
    assert groups[2].detected == Party() and groups[2].file_ids == ["f5"]


def test_frequent_seller_is_the_client_for_issued_invoices():
    client = Party(name="New Client Co", tin="444555666")
    files = [_fd("a", seller=client, buyer=Party(name="Buyer A")), _fd("b", seller=client, buyer=Party(name="Buyer B"))]
    [group] = suggest_groups(files)
    assert group.detected == client


def test_detection_json_round_trip_and_error_payload():
    det = Detection("SALES INVOICE", "invoice", Party(name="S", tin="111222333"), Party(name="B"), None)
    data = detection_json(det, MatchResult("c1", "likely", 0.9, "buyer"))
    fd = file_detection_from_json("f1", data)
    assert fd.seller == det.seller and fd.match.company_id == "c1" and fd.match.level == "likely"
    broken = file_detection_from_json("f2", {"error": "timeout"})
    assert broken.match.level == "unknown" and broken.seller == Party()


def test_files_whose_detection_failed_get_their_own_group_last():
    files = [
        file_detection_from_json("f1", {"error": "429 RESOURCE_EXHAUSTED"}),
        _fd("f2", buyer=Party(tin="123456789"), match=MatchResult("c1", "certain", 1.0, "buyer")),
        _fd("f3", seller=Party(name="Shell")),
        file_detection_from_json("f4", {"error": "timeout"}),
    ]
    assert files[0].failed and not files[1].failed
    groups = suggest_groups(files)
    assert [g.key for g in groups] == ["company:c1", "new:", "unreadable"]
    assert groups[-1].level == "unreadable" and groups[-1].file_ids == ["f1", "f4"]


def test_a_file_with_no_parties_read_is_unreadable_not_a_new_company():
    groups = suggest_groups([file_detection_from_json("f1", {"kind": "invoice", "seller": {}, "buyer": {}})])
    assert [(g.key, g.level) for g in groups] == [("unreadable", "unreadable")]
