from datetime import date

import fitz

from app.forms import bir1701_layout, bir1701a_layout, bir1702rt_layout
from app.services.accounting.pdf_2550q import Header2550Q, render_2550q
from app.services.accounting.pdf_returns import header_from_snapshot, render_return

COMPANY = {
    "registered_name": "Juan's Cloth Trading Corporation", "tin": "123456789", "branch_code": "00000",
    "rdo_code": "030", "address": "123 Rizal Avenue, Quiapo, Manila", "zip_code": "1001",
    "taxpayer_type": "corporation", "income_tax_option": "graduated", "deduction_method": "itemized",
    "fiscal_year_end_month": 12,
}
_PRINTED = {"-", "/", ".", "●", "%"}


def H(year=2026, **company):
    return header_from_snapshot({**COMPANY, **company}, year, 4)


def _words(pdf: bytes, page: int = 0):
    return fitz.open("pdf", pdf)[page].get_text("words")


def _ticked(words, check) -> bool:
    return any(w[4] == "X" and abs((w[0] + w[2]) / 2 - check.x) < 3 and abs(w[3] - check.baseline) < 4
               for w in words)


def _text_in(words, cells, baseline) -> str:
    inside = [w for w in words if w[4] not in _PRINTED and abs(w[3] - baseline) < 4
              and cells[0][0] - 1 <= (w[0] + w[2]) / 2 <= cells[-1][1] + 1]
    return "".join(w[4] for w in sorted(inside, key=lambda w: w[0]))


def _cell(words, layout, key) -> str:
    spec = layout.cells[key]
    return _text_in(words, spec.cells, spec.baseline)


def _amount(words, layout, key) -> str:
    spec = layout.amounts[key]
    return _text_in(words, spec.pesos + spec.cents, spec.baseline)


def test_1702rt_header_items_schedules_and_overpayment():
    L = bir1702rt_layout.LAYOUT
    values = {"21": "-2500", "40": "25", "39": "568000", "S1_17D": "4000", "S3_4_YEAR": "2024", "S3_4_A": "9000",
              "S4_1_YEAR": "2025", "S4_1_C": "17500", "S5_1": "550000", "S5_2": "20000",
              "OVERPAYMENT_OPTION": "carry_over"}
    pdf = render_return("1702RT", values, H(fiscal_year_end_month=6, deduction_method="osd"), amended=True).pdf
    p1, p2, p3, p4 = (_words(pdf, n) for n in range(4))
    for check in ("fiscal", "amended_yes", "short_no", "atc_IC055", "osd", "carry_over"):
        assert _ticked(p1, L.checks[check]), check
    assert not _ticked(p1, L.checks["refund"])
    assert _cell(p1, L, "year_month") == "06" and _cell(p1, L, "year_yy") == "26"
    assert _cell(p1, L, "tin") == "123456789"
    assert _amount(p1, L, "21") == "(2500)"
    assert _cell(p2, L, "40") == "25" and _amount(p2, L, "39") == "568000"
    assert _cell(p2, L, "tin_p2") == "123456789" and _cell(p4, L, "tin_p4") == "123456789"
    assert _cell(p3, L, "S1_17D_DESC").startswith("OTHERS")
    assert _cell(p4, L, "S3_4_YEAR") == "2024" and _amount(p4, L, "S3_4_A") == "9000"
    assert _cell(p4, L, "S4_1_YEAR") == "2025" and _amount(p4, L, "S4_1_C") == "17500"
    assert _cell(p4, L, "S5_2_DESC").startswith("NON")


def test_1702rt_refund_box_and_no_box_without_overpayment():
    L = bir1702rt_layout.LAYOUT
    refund = _words(render_return("1702RT", {"21": "-5", "OVERPAYMENT_OPTION": "refund"}, H()).pdf)
    assert _ticked(refund, L.checks["refund"]) and _ticked(refund, L.checks["calendar"])
    plain = _words(render_return("1702RT", {"21": "5", "OVERPAYMENT_OPTION": ""}, H()).pdf)
    assert not any(_ticked(plain, L.checks[c]) for c in ("refund", "tcc", "carry_over"))
    assert _ticked(plain, L.checks["amended_no"]) and _ticked(plain, L.checks["itemized"])


def test_1701_itemized_individual():
    L = bir1701_layout.LAYOUT
    values = {"31": "52500", "S3_8": "1000000", "S3_19": "5000", "S4_17D": "300", "S6_4_YEAR": "2023",
              "S6_4_A": "7000", "P9_1": "100", "P9_2": "5"}
    pdf = render_return("1701", values, H(taxpayer_type="individual", registered_name="Dela Cruz, Juan")).pdf
    p1, p2, p3, p4 = (_words(pdf, n) for n in range(4))
    for check in ("amended_no", "short_no", "single_proprietor", "atc_II012", "foreign_credits_no", "exempt_no",
                  "special_no", "rate_graduated", "itemized"):
        assert _ticked(p1, L.checks[check]), check
    assert _cell(p1, L, "year") == "2026" and _amount(p1, L, "31") == "52500"
    assert _amount(p2, L, "S3_8") == "1000000" and _cell(p2, L, "S3_19_DESC").startswith("OTHER")
    assert _cell(p3, L, "S6_4_YEAR") == "2023" and _amount(p3, L, "S6_4_A") == "7000"
    assert _cell(p3, L, "S4_17D_DESC").startswith("OTHERS")
    assert _cell(p4, L, "P9_2_DESC").startswith("NON")


def test_1701a_osd_and_eight_percent():
    L = bir1701a_layout.LAYOUT
    osd = render_return("1701A", {"46": "62500", "29": "62500", "41": "5000"},
                        H(taxpayer_type="individual", deduction_method="osd")).pdf
    p1, p2 = _words(osd, 0), _words(osd, 1)
    for check in ("amended_no", "short_no", "single_proprietor", "atc_II012", "foreign_credits_no", "rate_osd"):
        assert _ticked(p1, L.checks[check]), check
    assert _cell(p1, L, "year_month") == "12" and _cell(p1, L, "year") == "2026"
    assert _amount(p1, L, "29") == "62500" and _amount(p2, L, "46") == "62500"
    assert _cell(p2, L, "41_DESC").startswith("OTHER") and _cell(p2, L, "tin_p2") == "123456789"
    eight = _words(render_return("1701A", {"56": "260000"}, H(taxpayer_type="individual",
                                                              income_tax_option="eight_percent")).pdf)
    assert _ticked(eight, L.checks["atc_II015"]) and _ticked(eight, L.checks["rate_eight"])


def test_changed_item_is_highlighted_on_the_annual_pdf():
    pdf = render_return("1702RT", {"21": "5"}, H(), highlights=frozenset({"21"})).pdf
    fills = [d.get("fill") for d in fitz.open("pdf", pdf)[0].get_drawings() if d.get("fill")]
    assert any(abs(f[0] - 1.0) < 0.01 and abs(f[1] - 0.957) < 0.01 for f in fills)


def test_2550q_prints_a_branch_code_over_the_preprinted_zeros():
    header = Header2550Q("123456789", "030", "Juan", "Quiapo", "1001", 12, 2026, 3, date(2026, 7, 1),
                         date(2026, 9, 30), branch_code="00012")
    words = _words(render_2550q({}, header))
    branch = [w for w in words if 400 < (w[0] + w[2]) / 2 < 476 and abs(w[3] - 182) < 4]
    assert "".join(w[4] for w in sorted(branch, key=lambda w: w[0])) == "00012"
    head_office = Header2550Q("123456789", "030", "Juan", "Quiapo", "1001", 12, 2026, 3, date(2026, 7, 1),
                              date(2026, 9, 30))
    kept = [w for w in _words(render_2550q({}, head_office)) if 400 < (w[0] + w[2]) / 2 < 476 and abs(w[3] - 182) < 4]
    assert "".join(w[4] for w in sorted(kept, key=lambda w: w[0])) == "00000"  # the template's own zeros


def test_mixed_income_1701_ticks_the_mixed_income_atc():
    from app.services.accounting.pdf_returns import _FILLERS, header_from_snapshot
    base = {"taxpayer_type": "individual", "has_compensation_income": True}
    graduated = _FILLERS["1701"]({}, header_from_snapshot(base, 2026, 0), False, None)
    assert {"atc_II013", "compensation_earner", "rate_graduated"} <= set(graduated.checks)
    eight = _FILLERS["1701"]({}, header_from_snapshot({**base, "income_tax_option": "eight_percent"}, 2026, 0),
                             False, None)
    assert {"atc_II017", "rate_eight"} <= set(eight.checks) and "itemized" not in eight.checks
