from datetime import date

import fitz
import pytest

from app.forms import bir2550q_layout as Q
from app.services.accounting.pdf_2550q import Header2550Q, render_2550q
from app.services.accounting.pdf_overlay import banner_text
from app.services.accounting.pdf_returns import LAYOUTS, ReturnHeader, render_return

H = ReturnHeader(tin="123456789", branch_code="00000", rdo_code="030", name="JUAN TRADING", address="QUIAPO",
                 zip_code="1001", taxpayer_type="corporation", income_tax_option="graduated",
                 deduction_method="itemized", fiscal_year_end_month=12, fiscal_year=2026, quarter=3,
                 contact_number="09171234567", email="juan@example.com")
H50 = Header2550Q("123456789", "030", "JUAN", "QUIAPO", "1001", 12, 2026, 3, date(2026, 7, 1), date(2026, 9, 30),
                  contact_number="09171234567", email="juan@example.com", classification="small")


def _words(pdf: bytes, page: int = 0):
    return fitz.open("pdf", pdf)[page].get_text("words")


def test_banner_text():
    assert banner_text(0, []) is None
    assert banner_text(2, []) == "DRAFT — 2 document(s) unreviewed — not for filing"
    assert banner_text(0, ["RDO code", "Email address"]) == "DRAFT — missing: RDO code, Email address — not for filing"
    assert banner_text(1, ["RDO code"]) == "DRAFT — missing: RDO code · 1 document(s) unreviewed — not for filing"


@pytest.mark.parametrize("form", [f for f in LAYOUTS if "contact" in LAYOUTS[f].cells])
def test_contact_digits_land_in_their_comb(form):
    spec = LAYOUTS[form].cells["contact"]
    pdf = render_return(form + ("-M1" if form in ("0619E", "1601C") else ""), {}, H).pdf
    row = sorted(w for w in _words(pdf, spec.page) if abs(w[3] - spec.baseline) < 3
                 and spec.cells[0][0] - 1 < w[0] < spec.cells[-1][1])
    assert "".join(w[4] for w in row).startswith("0917123456")
    for w, (x0, x1) in zip(row, spec.cells):
        assert x0 < (w[0] + w[2]) / 2 < x1


def test_long_email_is_cut_to_the_comb():
    spec = LAYOUTS["1601EQ"].cells["email"]
    long = ReturnHeader(**{**H.__dict__, "email": "x" * 80})
    pdf = render_return("1601EQ", {}, long).pdf
    xs = [w for w in _words(pdf, spec.page) if abs(w[3] - spec.baseline) < 3 and w[4] == "x"]
    assert len(xs) == len(spec.cells)


def test_2550q_classification_relief_and_contact():
    pdf = render_2550q({}, H50)
    marks = [w for w in _words(pdf) if w[4] == "X"]
    assert any(abs((w[0] + w[2]) / 2 - Q.P1_CLASS["small"][0]) < 3 and abs(w[3] - Q.P1_CLASS["small"][1]) < 4
               for w in marks)
    assert any(abs((w[0] + w[2]) / 2 - Q.P1_RELIEF_NO[0]) < 3 for w in marks)
    assert any(w[4] == "@" for w in _words(pdf))


def test_missing_banner_on_every_page_and_shrinks():
    missing = ["TIN (9 digits)", "RDO code", "Registered address", "ZIP code", "Contact number", "Email address",
               "VAT taxpayer classification", "1601-EQ ATC schedule"]
    pdf = render_return("1601EQ", {}, H, missing=missing).pdf
    doc = fitz.open("pdf", pdf)
    for page in doc:
        text = page.get_text()
        assert "missing: TIN (9 digits)" in text and "not for filing" in text
        banner = [b for b in page.get_text("dict")["blocks"] if "missing:" in str(b)]
        assert all(b["bbox"][2] <= page.rect.width - 10 for b in banner)
    assert "missing: RDO code" in fitz.open("pdf", render_2550q({}, H50, missing=["RDO code"]))[1].get_text()
