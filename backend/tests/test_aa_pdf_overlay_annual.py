import hashlib

import fitz
import pytest

from app.forms import bir1701_layout, bir1701a_layout, bir1702rt_layout
from app.forms.overlay import ticks
from app.services.accounting.pdf_overlay import render_form

LAYOUTS = {"1702RT": bir1702rt_layout.LAYOUT, "1701": bir1701_layout.LAYOUT, "1701A": bir1701a_layout.LAYOUT}


def _pages(pdf: bytes):
    return [page.get_text("words") for page in fitz.open("pdf", pdf)]


def test_ticks_pairs_consecutive_marks():
    assert ticks(0, 10, 25) == ((0, 10), (10, 25))


@pytest.mark.parametrize("name", LAYOUTS)
def test_templates_are_the_calibrated_official_forms(name):
    layout = LAYOUTS[name]
    assert hashlib.sha256(layout.template.read_bytes()).hexdigest() == layout.sha256


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
def test_every_cell_and_check_lands_on_its_page(name):
    layout = LAYOUTS[name]
    out = render_form(layout, amounts={}, cells={key: "Q" * len(c.cells) for key, c in layout.cells.items()},
                      checks=list(layout.checks))
    pages = _pages(out.pdf)
    for key, spec in layout.cells.items():
        x0, x1 = spec.cells[0]
        assert any(w[4].startswith("Q") and x0 - 1 <= w[0] <= x1 and abs(w[3] - spec.baseline) < 4
                   for w in pages[spec.page]), key
    for key, spec in layout.checks.items():
        assert any(w[4] == "X" and abs((w[0] + w[2]) / 2 - spec.x) < 3 and abs(w[3] - spec.baseline) < 4
                   for w in pages[spec.page]), key


def test_too_long_amount_is_printed_whole_in_red():
    layout = LAYOUTS["1701A"]  # 8-cell boxes
    out = render_form(layout, amounts={"20": "123456789"})
    assert out.overflow == ("20",)
    assert any(w[4] == "123456789" for w in _pages(out.pdf)[0])
