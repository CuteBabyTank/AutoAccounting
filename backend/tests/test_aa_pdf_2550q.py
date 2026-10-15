import hashlib
from datetime import date

import fitz

from app.forms import bir2550q_layout as L
from app.services.accounting.pdf_2550q import Header2550Q, render_2550q

HEADER = Header2550Q("123456789", "030", "Juan's Cloth Trading", "Quiapo, Manila", "1001", 12, 2026, 3,
                     date(2026, 7, 1), date(2026, 9, 30))


def _words(pdf: bytes, page: int):
    return fitz.open("pdf", pdf)[page].get_text("words")


def test_template_is_the_calibrated_official_form():
    assert hashlib.sha256(L.TEMPLATE_PATH.read_bytes()).hexdigest() == L.TEMPLATE_SHA256


def _row(pdf: bytes, page: int, baseline: float, x0: float, x1: float) -> list[tuple[float, str]]:
    return sorted(((w[0] + w[2]) / 2, w[4]) for w in _words(pdf, page) if abs(w[3] - baseline) < 3 and x0 < w[0] < x1)


def test_amounts_go_one_digit_per_cell():
    pdf = render_2550q({"31A": "25000.00", "31B": "3000.50", "26": "1234567.89"}, HEADER)
    for key, text in (("31A", "2500000"), ("31B", "300050"), ("26", "123456789")):
        spec = L.AMOUNTS[key]
        cells = spec.pesos[len(spec.pesos) - (len(text) - 2):] + spec.cents
        row = _row(pdf, spec.page, spec.baseline, spec.pesos[0][0] - 1, spec.cents[-1][1])
        assert "".join(c for _, c in row) == text  # each digit its own word: nothing joined, no commas
        for (x, _), (c0, c1) in zip(row, cells):
            assert c0 < x < c1


def test_negative_amount_in_parentheses():
    pdf = render_2550q({"61B": "-480.00"}, HEADER)
    spec = L.AMOUNTS["61B"]
    row = _row(pdf, 1, spec.baseline, spec.pesos[0][0] - 1, spec.cents[-1][1])
    assert [c for _, c in row] == ["(", "4", "8", "0", "0", "0)"]
    assert spec.cents[-1][0] < row[-1][0] < spec.cents[-1][1]


def test_header_boxes_are_filled():
    pdf = render_2550q({}, HEADER)
    page1 = _words(pdf, 0)
    xs = [w for w in page1 if w[4] == "X"]
    assert any(abs((w[0] + w[2]) / 2 - L.P1_QUARTER[3][0]) < 3 for w in xs)      # 3rd quarter
    assert any(abs((w[0] + w[2]) / 2 - L.P1_CALENDAR[0]) < 3 for w in xs)       # calendar year
    tin_digits = [w for w in page1 if w[4] in "123456789" and abs(w[3] - 184) < 4 and 233 < w[0] < 390]
    assert len(tin_digits) >= 9
    assert any(w[4] == "J" and w[0] < 40 and abs(w[3] - 213) < 4 for w in page1)  # name, first letter


def test_highlight_and_draft_banner():
    pdf = render_2550q({"31A": "1.00"}, HEADER, highlights=frozenset({"31A"}), draft_reviews=2)
    doc = fitz.open("pdf", pdf)
    fills = [d.get("fill") for d in doc[1].get_drawings() if d.get("fill")]
    assert any(abs(f[0] - 1.0) < 0.01 and abs(f[1] - 0.957) < 0.01 and abs(f[2] - 0.702) < 0.01 for f in fills)
    assert "DRAFT" in doc[0].get_text() and "Highlighted = changed" in doc[0].get_text()
