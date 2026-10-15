"""Overlay map for BIR Form 0619-E (January 2018), page 612 × 792.

Calibrated from the template's comb tick marks (cells are 14.4 pt wide);
baselines sit 2 pt above the bottom ticks.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb, ticks

_PESOS, _CENTS = comb(391.9, 550.5, 11), comb(564.9, 593.8, 2)
_ROWS = {"14": 337.3, "15": 355.5, "16": 373.8, "17A": 402.8, "17B": 421.0, "17C": 439.3, "17D": 457.5,
         "18": 475.8}

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir0619e_jan2018.pdf",
    sha256="0418160d63d4e6f68c34f2bad553273a5d148c3686d8562d338d35fcdd0c5215",
    cells={
        "month": Cells(0, comb(46.1, 131.5, 6), 147.4),
        "due_date": Cells(0, comb(145.9, 260.8, 8), 147.4),
        "tin": Cells(0, comb(218.1, 261.3, 3) + comb(276.0, 319.3, 3) + comb(334.0, 377.2, 3)
                     + comb(392.1, 464.1, 5), 181.1),
        "rdo": Cells(0, comb(536.1, 579.3, 3), 181.1),
        "name": Cells(0, comb(17.6, 593.8, 40), 209.8),
        "address": Cells(0, comb(17.6, 593.8, 40), 238.4),
        "address_2": Cells(0, comb(17.6, 464.1, 31), 256.7),
        "zip": Cells(0, comb(536.1, 593.8, 4), 256.7),
        "contact": Cells(0, ticks(103.1, 117.4, 131.7, 146.1, 160.5, 174.9, 189.3, 203.7, 218.1, 232.5, 246.9, 261.3,
                                  276.0), 274.9),
        "email": Cells(0, ticks(17.6, 31.8, 46.1, 60.4, 74.7, 88.8, 103.1, 117.4, 131.7, 146.1, 160.5, 174.9, 189.3,
                                203.7, 218.1, 232.5, 246.9, 261.3, 276.0, 290.4, 304.9, 319.3, 334.0, 348.4, 362.8,
                                377.2, 392.1, 406.5, 420.9, 435.3, 449.7, 464.1, 478.5, 492.9, 507.3, 521.7, 536.1,
                                550.5, 564.9, 579.3, 593.8), 303.6),
    },
    checks={
        "amended_yes": Check(0, 282.4, 143.5), "amended_no": Check(0, 325.9, 143.6),
        "withheld_yes": Check(0, 383.5, 143.7), "withheld_no": Check(0, 427.3, 143.9),
        "private": Check(0, 452.1, 271.4),
    },
    amounts={key: Amount(0, _PESOS, y, _CENTS) for key, y in _ROWS.items()},
)
