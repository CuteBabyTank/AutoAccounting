import fitz
import pytest

from app.forms import (
    bir0619e_layout, bir1601c_layout, bir1601eq_layout, bir1701q_layout, bir1702q_layout, bir2551q_layout,
)
from app.services.accounting.pdf_returns import header_from_snapshot, render_return, split_form, wrap

COMPANY = {
    "registered_name": "Juan's Cloth Trading Corporation", "tin": "123456789", "branch_code": "00000",
    "rdo_code": "030", "address": "123 Rizal Avenue, Quiapo, Manila", "zip_code": "1001",
    "taxpayer_type": "corporation", "income_tax_option": "graduated", "deduction_method": "itemized",
    "fiscal_year_end_month": 12,
}


def H(year=2026, quarter=3, **company):
    return header_from_snapshot({**COMPANY, **company}, year, quarter)


def _words(pdf: bytes, page: int = 0):
    return fitz.open("pdf", pdf)[page].get_text("words")


def _ticked(words, check) -> bool:
    return any(w[4] == "X" and abs((w[0] + w[2]) / 2 - check.x) < 3 and abs(w[3] - check.baseline) < 4
               for w in words)


_PRINTED = {"-", "/", ".", "●", "%"}  # separators printed on the template itself


def _text_in(words, cells, baseline) -> str:
    inside = [w for w in words if w[4] not in _PRINTED and abs(w[3] - baseline) < 4
              and cells[0][0] - 1 <= (w[0] + w[2]) / 2 <= cells[-1][1] + 1]
    return "".join(w[4] for w in sorted(inside, key=lambda w: w[0]))


def _amount(words, spec) -> str:
    return _text_in(words, spec.pesos + spec.cents, spec.baseline)


def test_split_form_and_wrap():
    assert split_form("0619E-M2") == ("0619E", 2) and split_form("1601EQ") == ("1601EQ", None)
    assert wrap("Juan's Cloth Trading", [8, 8]) == ["JUAN'S", "CLOTH"]
    assert wrap("Supercalifragilistic", [5, 5]) == ["SUPER", "CALIF"]
    assert wrap("", [3]) == [""]


def test_header_from_an_older_snapshot_uses_defaults():
    h = header_from_snapshot({"registered_name": "A", "tin": "123456789"}, 2026, 2)
    assert (h.branch_code, h.fiscal_year_end_month, h.taxpayer_type) == ("00000", 12, "corporation")
    assert (h.period_from.isoformat(), h.period_to.isoformat()) == ("2026-04-01", "2026-06-30")


def test_unknown_form_is_rejected():
    with pytest.raises(ValueError):
        render_return("2550Q", {}, H())


def test_2551q_header_and_amounts():
    L = bir2551q_layout.LAYOUT
    values = {"S1_1_ATC": "PT 010", "S1_1_TAXABLE": "100000.00", "S1_1_RATE": "3", "S1_1_DUE": "3000.00",
              "S1_7": "3000.00", "14": "3000.00", "24": "3000.00"}
    pdf = render_return("2551Q", values, H()).pdf
    p1, p2 = _words(pdf, 0), _words(pdf, 1)
    for check in ("q3", "calendar", "amended_no", "relief_no"):
        assert _ticked(p1, L.checks[check]), check
    assert _text_in(p1, L.cells["tin"].cells, L.cells["tin"].baseline) == "12345678900000"
    assert _text_in(p1, L.cells["year_ended"].cells, L.cells["year_ended"].baseline) == "122026"
    assert _text_in(p1, L.cells["name"].cells, L.cells["name"].baseline) == "JUAN'SCLOTHTRADINGCORPORATION"
    assert _amount(p1, L.amounts["14"]) == "300000"
    assert _text_in(p2, L.cells["S1_1_ATC"].cells, L.cells["S1_1_ATC"].baseline) == "PT010"


def test_1701q_graduated_and_eight_percent_choices():
    L = bir1701q_layout.LAYOUT
    graduated = {"36": "500000", "46": "22500", "62": "0", "63": "22500", "67": "0", "68": "22500"}
    pdf = render_return("1701Q", graduated, H(quarter=2, taxpayer_type="individual"),
                        highlights=frozenset({"46"})).pdf
    p1 = _words(pdf, 0)
    for check in ("q2", "atc_II012", "rate_graduated", "itemized", "single_proprietor", "foreign_credits_no"):
        assert _ticked(p1, L.checks[check]), check
    assert _amount(p1, L.amounts["P3_26"]) == "22500" and _amount(p1, L.amounts["P3_31"]) == "22500"
    assert _amount(_words(pdf, 1), L.amounts["36"]) == "500000"
    fills = [d.get("fill") for d in fitz.open("pdf", pdf)[0].get_drawings() if d.get("fill")]
    assert any(abs(f[1] - 0.957) < 0.01 and abs(f[2] - 0.702) < 0.01 for f in fills)  # Part III mirrors item 46

    eight = {"47": "900000", "53": "650000", "54": "52000", "62": "0", "63": "52000", "68": "52000"}
    p1 = _words(render_return("1701Q", eight, H(quarter=1, taxpayer_type="individual",
                                                  income_tax_option="eight_percent")).pdf, 0)
    assert _ticked(p1, L.checks["atc_II015"]) and _ticked(p1, L.checks["rate_eight"])
    assert not _ticked(p1, L.checks["itemized"]) and _amount(p1, L.amounts["P3_26"]) == "52000"


def test_1702q_fiscal_year_rate_and_osd():
    L = bir1702q_layout.LAYOUT
    pdf = render_return("1702Q", {"S2_10": "25", "S2_1": "1000000", "25": "-1500"},
                        H(year=2027, quarter=1, fiscal_year_end_month=6, deduction_method="osd")).pdf
    p1, p2 = _words(pdf, 0), _words(pdf, 1)
    for check in ("fiscal", "q1", "osd", "relief_no"):
        assert _ticked(p1, L.checks[check]), check
    assert _text_in(p1, L.cells["year_month"].cells, L.cells["year_month"].baseline) == "06"
    assert _text_in(p1, L.cells["year_yy"].cells, L.cells["year_yy"].baseline) == "27"
    assert _text_in(p1, L.cells["tin"].cells, L.cells["tin"].baseline) == "123456789"  # branch is pre-printed
    assert _amount(p1, L.amounts["25"]) == "(1500)"
    assert _text_in(p2, L.cells["S2_10"].cells, L.cells["S2_10"].baseline) == "25"
    assert _amount(p2, L.amounts["S2_1"]) == "1000000"


def test_0619e_fiscal_month_due_date_and_nothing_withheld():
    L = bir0619e_layout.LAYOUT
    zero = {"14": "0.00", "16": "0.00", "18": "0.00"}
    p1 = _words(render_return("0619E-M1", zero, H(year=2027, quarter=1, fiscal_year_end_month=6)).pdf)
    assert _text_in(p1, L.cells["month"].cells, L.cells["month"].baseline) == "072026"
    assert _text_in(p1, L.cells["due_date"].cells, L.cells["due_date"].baseline) == "08102026"
    assert _ticked(p1, L.checks["withheld_no"]) and _ticked(p1, L.checks["private"])
    p1 = _words(render_return("0619E-M2", {"14": "500.00", "18": "500.00"}, H(), amended=True).pdf)
    assert _text_in(p1, L.cells["month"].cells, L.cells["month"].baseline) == "082026"
    assert _ticked(p1, L.checks["withheld_yes"]) and _ticked(p1, L.checks["amended_yes"])
    assert _amount(p1, L.amounts["18"]) == "50000"


def test_1601eq_schedule_caps_at_six_rows_with_a_note():
    L = bir1601eq_layout.LAYOUT
    values = {"19": "1000.00", "31": "0.00"}
    for i in range(1, 8):
        values.update({f"S{i}_ATC": f"WC{100 + i}", f"S{i}_BASE": "1000.00", f"S{i}_RATE": "5", f"S{i}_TAX": "50.00"})
    pdf = render_return("1601EQ", values, H(quarter=4))
    p1 = _words(pdf.pdf)
    assert _ticked(p1, L.checks["q4"]) and _ticked(p1, L.checks["withheld_yes"])
    assert _text_in(p1, L.cells["year"].cells, L.cells["year"].baseline) == "2026"
    assert _text_in(p1, L.cells["S6_ATC"].cells, L.cells["S6_ATC"].baseline) == "WC106"
    assert "WC107" not in fitz.open("pdf", pdf.pdf)[0].get_text()
    assert "More than six ATCs" in fitz.open("pdf", pdf.pdf)[0].get_text()
    assert _text_in(p1, L.cells["S1_RATE"].cells, L.cells["S1_RATE"].baseline) == "5"


def test_1601c_month_and_withheld():
    L = bir1601c_layout.LAYOUT
    p1 = _words(render_return("1601C-M3", {"14": "100000.00", "25": "8000.00", "36": "8000.00"}, H()).pdf)
    assert _text_in(p1, L.cells["month"].cells, L.cells["month"].baseline) == "092026"
    assert _ticked(p1, L.checks["withheld_yes"]) and _ticked(p1, L.checks["relief_no"])
    assert _amount(p1, L.amounts["36"]) == "800000"
    assert _text_in(p1, L.cells["address"].cells, L.cells["address"].baseline) == "123RIZALAVENUE,QUIAPO,MANILA"


@pytest.mark.parametrize("form", ["2551Q", "1701Q", "1702Q", "1601EQ", "1601C-M1", "1702RT", "1701", "1701A"])
def test_tin_and_name_repeat_on_every_later_page(form):
    from app.services.accounting.pdf_returns import LAYOUTS
    layout = LAYOUTS[split_form(form)[0]]
    pdf = render_return(form, {}, H(taxpayer_type="individual" if form.startswith("1701") else "corporation")).pdf
    keys = [k for k in layout.cells if k.startswith("tin_p")]
    assert keys, f"{form} has no page-2 header cells"
    for key in keys:
        tin, name = layout.cells[key], layout.cells[key.replace("tin_", "name_")]
        words = _words(pdf, tin.page)
        assert _text_in(words, tin.cells, tin.baseline) == ("12345678900000" if len(tin.cells) > 9 else "123456789"), key
        assert len(tin.cells) == len(layout.cells["tin"].cells), key  # page 2 carries the branch when page 1 does
        assert _text_in(words, name.cells, name.baseline).startswith("JUAN'SCLOTH"), key
