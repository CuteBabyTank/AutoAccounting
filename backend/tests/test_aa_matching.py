

def test_reader_outage_gets_its_own_group_not_unreadable():
    from app.services.accounting.matching import file_detection_from_json, suggest_groups
    down = file_detection_from_json("a", {"error": "Gemini API failed: 402", "reader_down": True})
    blank = file_detection_from_json("b", {"error": "bad image"})
    groups = {g.key: g.file_ids for g in suggest_groups([down, blank])}
    assert groups == {"reader_down": ["a"], "unreadable": ["b"]}
