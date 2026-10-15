"""Overlay map for BIR Form 1601-C (January 2018 ENCS), page 612 × 936.

Calibrated from the template's comb tick marks (cells are 14.4 pt wide);
baselines sit 2 pt above the bottom ticks. Part IV (adjustment schedules) is not filled.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb, ticks

_PESOS, _CENTS = comb(390.8, 549.1, 11), comb(564.2, 594.5, 2)
_ROWS = {"14": 307.4, "15": 333.1, "16": 349.0, "17": 364.9, "18": 380.8, "19": 396.8, "20": 412.8,
         "21": 428.7, "22": 444.7, "23": 460.7, "24": 476.6, "25": 492.6, "26": 508.5, "27": 524.5,
         "28": 540.3, "29": 556.3, "30": 573.0, "31": 589.0, "32": 604.8, "33": 620.8, "34": 636.7,
         "35": 652.7, "36": 668.7}

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1601c_jan2018.pdf",
    sha256="c8faaa71015337a73b4ceb96bfb265c539589ab5e10eb27899bb81f87f417397",
    cells={
        # page 2+ header strips: TIN (without branch) and name, calibrated from the comb ticks
        "tin_p2": Cells(1, ((17.6, 31.9), (31.9, 46.2), (46.2, 60.5), (60.6, 74.9), (74.9, 89.2), (89.2, 103.5), (103.6, 118.0), (118.0, 132.4), (132.4, 146.8), (146.7, 161.1), (161.1, 175.5), (175.5, 189.9), (189.9, 204.2), (204.2, 218.5)), 106.0),
        "name_p2": Cells(1, ticks(218.5, 232.8, 247.1, 261.4, 275.8, 290.2, 304.6, 318.9, 333.2, 347.6, 361.9, 376.3, 390.5, 404.9, 419.2, 433.6, 447.9, 462.2, 476.6, 490.9, 505.2, 519.6, 533.9, 549.0, 564.1, 579.1, 593.5), 106.0),
        "month": Cells(0, comb(46.4, 132.3, 6), 125.2),
        "tin": Cells(0, comb(233.1, 276.0, 3) + comb(290.4, 333.4, 3) + comb(347.8, 390.8, 3)
                     + comb(405.2, 476.9, 5), 155.5),
        "rdo": Cells(0, comb(549.1, 594.5, 3), 155.5),
        "name": Cells(0, comb(17.6, 594.5, 40), 181.9),
        "address": Cells(0, comb(17.6, 594.5, 40), 208.1),
        "address_2": Cells(0, comb(17.6, 462.5, 31), 224.1),
        "zip": Cells(0, comb(534.1, 594.5, 4), 224.1),
        "contact": Cells(0, ticks(104.2, 118.5, 132.7, 147.1, 161.4, 175.7, 190.1, 204.4, 218.7, 233.1, 247.4, 261.6,
                                  276.0), 242.3),
        "email": Cells(0, ticks(104.2, 118.5, 132.7, 147.1, 161.4, 175.7, 190.1, 204.4, 218.7, 233.1, 247.4, 261.6,
                                276.0, 290.4, 304.7, 319.0, 333.4, 347.8, 362.1, 376.4, 390.8, 405.2, 419.5, 433.9,
                                448.1, 462.5, 476.9, 491.1, 505.4, 519.7, 534.1, 549.1, 564.2, 579.3, 594.5), 258.3),
    },
    checks={
        "amended_yes": Check(0, 190.3, 122.0), "amended_no": Check(0, 238.1, 122.3),
        "withheld_yes": Check(0, 311.3, 122.4), "withheld_no": Check(0, 351.9, 121.8),
        "private": Check(0, 454.1, 239.6), "relief_no": Check(0, 225.4, 275.0),
    },
    amounts={key: Amount(0, _PESOS, y, _CENTS) for key, y in _ROWS.items()},
)
