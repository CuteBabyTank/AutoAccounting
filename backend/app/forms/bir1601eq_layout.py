"""Overlay map for BIR Form 1601-EQ (January 2019 ENCS), page 612 × 936.

Calibrated from the template's comb tick marks (cells are 14.4 pt wide);
baselines sit 2 pt above the bottom ticks. Part II has six ATC rows (items 13–18), keyed S1_*…S6_*.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb, ticks

_TAX_PESOS, _TAX_CENTS = comb(390.7, 549.1, 11), comb(564.2, 594.5, 2)
_SCHEDULE_Y = {1: 310.9, 2: 328.4, 3: 345.8, 4: 363.3, 5: 380.7, 6: 398.2}  # schedule row i is form item 12 + i
_TOTALS = {"19": 415.7, "20": 433.0, "21": 450.6, "22": 468.0, "23": 485.5, "24": 502.9, "25": 520.4,
           "26": 537.8, "27": 555.3, "28": 572.8, "29": 590.2, "30": 607.7, "31": 625.1}

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1601eq_jan2019.pdf",
    sha256="5277addc6778c96a53fde99b8664b1a5213fcea638dea06033c9acf22ee73c25",
    cells={
        # page 2+ header strips: TIN (without branch) and name, calibrated from the comb ticks
        "tin_p2": Cells(1, ((17.5, 31.9), (31.9, 46.3), (46.3, 60.7), (60.6, 75.0), (75.0, 89.4), (89.4, 103.8), (103.9, 118.2), (118.2, 132.5), (132.5, 146.8), (147.0, 161.3), (161.3, 175.6), (175.6, 190.0), (190.0, 204.4), (204.4, 218.7)), 126.0),
        "name_p2": Cells(1, ticks(218.7, 233.1, 247.4, 261.6, 276.0, 290.4, 304.7, 319.0, 333.4, 347.8, 362.1, 376.4, 390.8, 405.2, 419.5, 433.9, 448.1, 462.5, 476.9, 491.1, 505.4, 519.7, 534.1, 549.1, 564.2, 579.3, 593.7), 126.0),
        "year": Cells(0, comb(32.0, 89.7, 4), 126.1),
        "tin": Cells(0, comb(233.1, 276.0, 3) + comb(290.4, 333.4, 3) + comb(347.8, 390.8, 3)
                     + comb(405.2, 476.9, 5), 159.8),
        "rdo": Cells(0, comb(549.1, 594.5, 3), 159.8),
        "name": Cells(0, comb(17.6, 594.5, 40), 187.3),
        "address": Cells(0, comb(17.6, 594.5, 40), 214.6),
        "address_2": Cells(0, comb(17.6, 462.5, 31), 231.8),
        "zip": Cells(0, comb(534.1, 594.5, 4), 231.8),
        "contact": Cells(0, ticks(103.8, 118.2, 132.5, 146.9, 161.3, 175.6, 190.0, 204.4, 218.7, 233.1, 247.4, 261.6,
                                  276.0), 250.0),
        "email": Cells(0, ticks(103.8, 118.2, 132.5, 146.9, 161.3, 175.6, 190.0, 204.4, 218.7, 233.1, 247.4, 261.6,
                                276.0, 290.4, 304.7, 319.0, 333.4, 347.8, 362.1, 376.4, 390.8, 405.2, 419.5, 433.9,
                                448.1, 462.5, 476.9, 491.1, 505.4, 519.7, 534.1, 549.1, 564.2, 579.3, 594.5), 267.2),
        **{f"S{i}_ATC": Cells(0, comb(32.6, 104.2, 5), y) for i, y in _SCHEDULE_Y.items()},
        **{f"S{i}_RATE": Cells(0, ((319.0, 390.7),), y) for i, y in _SCHEDULE_Y.items()},
    },
    checks={
        "q1": Check(0, 124.3, 123.3), "q2": Check(0, 168.4, 123.7), "q3": Check(0, 211.3, 123.7),
        "q4": Check(0, 255.4, 123.3),
        "amended_yes": Check(0, 312.4, 123.7), "amended_no": Check(0, 356.3, 123.6),
        "withheld_yes": Check(0, 413.3, 123.3), "withheld_no": Check(0, 456.3, 123.5),
        "private": Check(0, 454.1, 247.3),
    },
    amounts={
        **{f"S{i}_BASE": Amount(0, comb(104.2, 275.9, 12), y, comb(290.3, 319.0, 2))
           for i, y in _SCHEDULE_Y.items()},
        **{f"S{i}_TAX": Amount(0, _TAX_PESOS, y, _TAX_CENTS) for i, y in _SCHEDULE_Y.items()},
        **{key: Amount(0, _TAX_PESOS, y, _TAX_CENTS) for key, y in _TOTALS.items()},
    },
)
