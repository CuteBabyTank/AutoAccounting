import io
import zipfile

import pytest

from app.services.accounting.pdf_bundle import validate_requested, zip_pdfs

EXPECTED = ["2550Q", "1702Q", "0619E-M1", "0619E-M2", "1601EQ"]


def test_zip_has_one_entry_per_pdf():
    data = zip_pdfs([("a 2550Q v3.pdf", b"%PDF-a"), ("a 1601EQ v3.pdf", b"%PDF-b")])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.namelist() == ["a 2550Q v3.pdf", "a 1601EQ v3.pdf"]
        assert z.read("a 1601EQ v3.pdf") == b"%PDF-b"


def test_requested_are_ordered_and_deduplicated():
    assert validate_requested(["1601EQ", "2550Q", "2550Q"], EXPECTED, EXPECTED) == ["2550Q", "1601EQ"]


@pytest.mark.parametrize("requested,message", [
    ([], "Pick at least one form"),
    (["2551Q"], "2551Q isn't filed for this quarter"),
    (["Expenses"], "Expenses isn't filed for this quarter"),
])
def test_rejects_bad_requests(requested, message):
    with pytest.raises(ValueError, match=message):
        validate_requested(requested, EXPECTED, EXPECTED)


def test_rejects_form_missing_from_version():
    with pytest.raises(ValueError, match="This version has no 1601EQ"):
        validate_requested(["1601EQ"], EXPECTED, ["2550Q"])
