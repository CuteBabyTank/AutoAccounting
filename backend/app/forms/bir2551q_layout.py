"""Overlay map for BIR Form 2551-Q (January 2018 ENCS), page 612 × 936.

Calibrated from the template's comb tick marks (cells are 14.2 pt wide) and box
outlines; baselines sit 2 pt above each comb's bottom ticks.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb, ticks

_P1_PESOS, _P1_CENTS = comb(376.9, 547.4, 12), comb(561.7, 590.1, 2)
_P1_ROWS = {"14": 377.8, "15": 407.5, "16": 425.9, "17": 444.1, "18": 462.4, "19": 480.6, "20": 510.2,
            "21": 528.5, "22": 546.7, "23": 565.0, "24": 583.7}
_DUE_PESOS, _DUE_CENTS = comb(363.3, 533.5, 12), comb(547.5, 576.0, 2)

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir2551q_jan2018.pdf",
    sha256="1f270ecf66d778836a14697863e420ff65d5ed0a5576a6cf58b97c9a8e8c9b24",
    cells={
        # page 2+ header strips: TIN (without branch) and name, calibrated from the comb ticks
        "tin_p2": Cells(1, ((23.0, 37.2), (37.2, 51.4), (51.4, 65.5), (65.8, 79.8), (79.8, 93.9), (93.9, 107.9), (108.1, 122.3), (122.3, 136.5), (136.5, 150.6), (150.6, 164.8), (164.8, 178.9), (178.9, 193.2), (193.2, 207.3), (207.3, 221.6)), 123.0),
        "name_p2": Cells(1, ticks(221.6, 235.7, 249.9, 264.0, 278.2, 292.4, 306.6, 320.7, 335.0, 349.1, 363.3, 377.5, 391.6, 405.8, 420.1, 434.1, 448.4, 462.6, 476.7, 490.9, 505.1, 519.2, 533.5, 547.5, 561.8, 576.0, 590.1), 123.0),
        "year_ended": Cells(0, comb(136.3, 164.7, 2) + comb(164.7, 221.5, 4), 142.4),
        "tin": Cells(0, comb(220.8, 263.3, 3) + comb(277.5, 320.1, 3) + comb(334.4, 377.0, 3)
                     + comb(391.1, 462.1, 5), 175.9),
        "rdo": Cells(0, comb(547.4, 590.1, 3), 175.9),
        "name": Cells(0, comb(23.0, 590.1, 40), 205.0),
        "address": Cells(0, comb(23.0, 590.1, 40), 234.2),
        "address_2": Cells(0, comb(23.0, 462.1, 31), 252.4),
        "zip": Cells(0, comb(533.1, 590.1, 4), 252.4),
        "contact": Cells(0, ticks(23.0, 37.1, 51.1, 65.3, 79.5, 93.5, 107.7, 121.7, 135.9, 150.0, 164.1, 178.2,
                                  192.4), 281.7),
        "email": Cells(0, ticks(192.4, 206.6, 220.8, 235.0, 249.2, 263.3, 277.5, 291.8, 305.9, 320.1, 334.4, 348.5,
                                362.7, 377.0, 391.1, 405.3, 419.6, 433.8, 447.9, 462.1, 476.4, 490.5, 504.7, 519.0,
                                533.1, 547.4, 561.7, 575.7, 590.1), 281.7),
        "S1_1_ATC": Cells(1, comb(37.2, 108.1, 5), 178.3),
        "S1_1_RATE": Cells(1, comb(320.7, 349.1, 2), 178.3, align="right"),
    },
    checks={
        "calendar": Check(0, 91.8, 122.5), "fiscal": Check(0, 164.1, 122.5),
        "q1": Check(0, 251.1, 135.9), "q2": Check(0, 293.4, 136.2), "q3": Check(0, 335.8, 135.9),
        "q4": Check(0, 377.9, 135.6),
        "amended_yes": Check(0, 432.4, 136.7), "amended_no": Check(0, 474.1, 137.3),
        "relief_no": Check(0, 241.7, 297.0),
        "rate_graduated": Check(0, 187.9, 337.5), "rate_eight": Check(0, 355.2, 337.7),
    },
    amounts={
        **{key: Amount(0, _P1_PESOS, y, _P1_CENTS) for key, y in _P1_ROWS.items()},
        "S1_1_TAXABLE": Amount(1, comb(108.1, 278.2, 12), 178.3, comb(292.4, 320.7, 2)),
        "S1_1_DUE": Amount(1, _DUE_PESOS, 178.3, _DUE_CENTS),
        "S1_7": Amount(1, _DUE_PESOS, 287.8, _DUE_CENTS),
    },
)
