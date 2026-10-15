"""Overlay map for BIR Form 1701-Q (January 2018 ENCS), page 612 × 936.

Whole pesos only. Column A (taxpayer) is filled; column B (spouse) is not
modelled. Calibrated from the template's comb tick marks; baselines sit 2 pt
above the bottom ticks. Part III items 26–31 summarise Part V (keys ``P3_*``).
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb, ticks

_PART_III = comb(362.3, 479.3, 8)
_PART_V = comb(355.6, 476.3, 8)
_P2_ROWS = {"36": 174.9, "37": 190.9, "38": 206.8, "39": 233.7, "40": 260.5, "41": 276.5, "42": 292.4,
            "43": 308.4, "44": 325.3, "45": 341.2, "46": 357.2, "47": 388.7, "48": 404.6, "49": 420.6,
            "50": 436.4, "51": 452.5, "52": 469.5, "53": 485.5, "54": 502.5, "55": 533.9, "56": 549.8,
            "57": 565.8, "58": 581.8, "59": 597.7, "60": 613.7, "61": 629.7, "62": 645.6, "63": 665.2,
            "64": 696.6, "65": 712.6, "66": 728.5, "67": 744.6, "68": 764.2}

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1701q_jan2018.pdf",
    sha256="c731d3f12556e6f19ab81f6113ca7c4a23f7ed099675c03451ac0074d96b85ed",
    cells={
        # page 2+ header strips: TIN (without branch) and name, calibrated from the comb ticks
        "tin_p2": Cells(1, ticks(13.3, 26.6, 40.0, 53.3, 66.7, 80.2, 93.6, 107.1, 120.5, 133.9), 112.0),
        "name_p2": Cells(1, ticks(207.4, 220.8, 234.4, 248.0, 261.5, 275.1, 288.5, 302.2, 315.8, 329.4, 342.8, 356.4, 370.3, 384.2, 401.8, 419.6, 437.2, 454.9, 472.7, 489.7, 506.7, 524.7, 542.7, 556.3, 569.9, 583.4, 597.0), 112.0),
        "year": Cells(0, comb(87.6, 145.6, 4), 108.8),
        "tin": Cells(0, comb(198.5, 242.1, 3) + comb(256.2, 299.9, 3) + comb(314.0, 357.5, 3), 140.2),
        "rdo": Cells(0, comb(532.9, 580.9, 3), 140.2),
        "name": Cells(0, comb(15.6, 595.6, 40), 216.2),
        "address": Cells(0, comb(15.6, 595.6, 40), 243.7),
        "address_2": Cells(0, comb(15.6, 475.5, 32), 260.8),
        "zip": Cells(0, comb(532.9, 595.6, 4), 260.8),
        "email": Cells(0, ticks(127.3, 141.4, 155.7, 169.8, 184.1, 198.5, 212.8, 227.2, 241.8, 256.6, 270.9, 285.3,
                                299.7, 314.2, 328.6, 343.0, 357.3, 372.1, 387.1, 401.9, 416.9, 432.1, 446.8, 461.3,
                                475.5, 489.8, 504.1, 518.5, 532.9, 548.9, 564.8, 580.9, 595.6), 288.2),
    },
    checks={
        "q1": Check(0, 195.2, 104.9), "q2": Check(0, 239.3, 104.9), "q3": Check(0, 297.1, 103.8),
        "amended_yes": Check(0, 428.9, 104.9), "amended_no": Check(0, 470.5, 105.8),
        "single_proprietor": Check(0, 119.6, 154.5),
        "atc_II012": Check(0, 163.6, 171.6), "atc_II015": Check(0, 163.7, 185.5),
        "foreign_credits_no": Check(0, 556.9, 313.5),
        "rate_graduated": Check(0, 66.5, 339.9), "rate_eight": Check(0, 67.2, 361.4),
        "itemized": Check(0, 233.9, 339.6), "osd": Check(0, 364.7, 339.5),
    },
    amounts={
        "P3_26": Amount(0, _PART_III, 600.1), "P3_27": Amount(0, _PART_III, 616.1),
        "P3_28": Amount(0, _PART_III, 632.1), "P3_29": Amount(0, _PART_III, 648.0),
        "P3_30": Amount(0, _PART_III, 664.0), "P3_31": Amount(0, comb(420.9, 536.9, 8), 679.9),
        **{key: Amount(1, _PART_V, y) for key, y in _P2_ROWS.items()},
    },
)
