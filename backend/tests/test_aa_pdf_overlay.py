import hashlib

import fitz
import pytest

from app.forms import (
    bir0619e_layout, bir1601c_layout, bir1601eq_layout, bir1701q_layout, bir1702q_layout, bir2551q_layout,
)
from app.forms.overlay import comb
from app.services.accounting.pdf_overlay import amount_chars, render_form

LAYOUTS = {
    "2551Q": bir2551q_layout.LAYOUT, "1701Q": bir1701q_layout.LAYOUT, "1702Q": bir1702q_layout.LAYOUT,
    "0619E": bir0619e_layout.LAYOUT, "1601EQ": bir1601eq_layout.LAYOUT, "1601C": bir1601c_layout.LAYOUT,
}


def _pages(pdf: bytes):
    return [page.get_text("words") for page in fitz.open("pdf", pdf)]


def test_comb_splits_evenly():
    assert comb(0, 30, 3) == ((0, 10), (10, 20), (20, 30))


@pytest.mark.parametrize("name", LAYOUTS)
def test_templates_are_the_calibrated_official_forms(name):
    layout = LAYOUTS[name]
    assert hashlib.sha256(layout.template.read_bytes()).hexdigest() == layout.sha256


def test_amount_chars():
    assert amount_chars("1234.5", whole=False) == (["1", "2", "3", "4"], ["5", "0"])
    assert amount_chars("-480.00", whole=False) == (["(", "4", "8", "0"], ["0", "0)"])
    assert amount_chars("-1234.6", whole=True) == (["(", "1", "2", "3", "5", ")"], [])
    assert amount_chars("0", whole=True) == (["0"], [])
    assert amount_chars("abc", whole=False) is None


@pytest.mark.parametrize("name", LAYOUTS)
def test_every_amount_box_takes_its_digits(name):
    layout = LAYOUTS[name]
    out = render_form(layout, amounts={key: "7" for key in layout.amounts})
    assert out.overflow == ()
    pages = _pages(out.pdf)
    for key, spec in layout.amounts.items():
        x0, x1 = spec.pesos[-1]
        assert any(w[4] == "7" and x0 <= (w[0] + w[2]) / 2 <= x1 and abs(w[3] - spec.baseline) < 4
                   for w in pages[spec.page]), key


@pytest.mark.parametrize("name", LAYOUTS)
def test_every_check_and_cell_lands_on_its_page(name):
    layout = LAYOUTS[name]
    out = render_form(layout, amounts={}, cells={key: "8" * len(spec.cells) for key, spec in layout.cells.items()},
                      checks=list(layout.checks))
    pages = _pages(out.pdf)
    for key, spec in layout.checks.items():
        assert any(w[4] == "X" and abs((w[0] + w[2]) / 2 - spec.x) < 3 and abs(w[3] - spec.baseline) < 4
                   for w in pages[spec.page]), key
    for key, spec in layout.cells.items():
        x0, x1 = spec.cells[0]
        assert any("8" in w[4] and x0 - 1 <= w[0] and abs(w[3] - spec.baseline) < 4 for w in pages[spec.page]), key


def test_too_long_amount_is_printed_whole_and_flagged():
    out = render_form(bir1701q_layout.LAYOUT, amounts={"36": "123456789"})
    assert out.overflow == ("36",)
    doc = fitz.open("pdf", out.pdf)
    assert "123456789" in doc[1].get_text()
    assert "Too long for the boxes" in doc[0].get_text() and "36" in doc[0].get_text()


def test_cells_checks_highlight_draft_and_notes():
    layout = bir2551q_layout.LAYOUT
    out = render_form(layout, amounts={"14": "-480.00"}, cells={"tin": "12345678900000", "S1_1_RATE": "3"},
                      checks=["q3"], highlights=frozenset({"14"}), draft_reviews=2, notes=["Extra note"])
    doc = fitz.open("pdf", out.pdf)
    words = doc[0].get_text("words")
    assert any(w[4] == "(" for w in words) and any(w[4] == "0)" for w in words)
    tin = layout.cells["tin"]
    digits = sorted((w for w in words if w[4].isdigit() and abs(w[3] - tin.baseline) < 4
                     and tin.cells[0][0] <= w[0] <= tin.cells[-1][1]), key=lambda w: w[0])
    assert "".join(w[4] for w in digits) == "12345678900000"
    rate = layout.cells["S1_1_RATE"]
    assert any(w[4] == "3" and rate.cells[1][0] <= (w[0] + w[2]) / 2 <= rate.cells[1][1]
               for w in doc[1].get_text("words"))  # right-aligned into the second cell
    fills = [d.get("fill") for d in doc[0].get_drawings() if d.get("fill")]
    assert any(abs(f[0] - 1.0) < 0.01 and abs(f[1] - 0.957) < 0.01 and abs(f[2] - 0.702) < 0.01 for f in fills)
    assert "DRAFT" in doc[1].get_text()
    footer = doc[0].get_text()
    assert "Highlighted = changed" in footer and "Extra note" in footer
