"""Overlay map for BIR Form 1702-Q (January 2018 ENCS), page 612 × 936.

Whole pesos only ("DO NOT enter Centavos"). Calibrated from the template's comb
tick marks (cells are 15.2 pt wide); baselines sit 2 pt above the bottom ticks.
Schedule 1 (special-rate income) is not filled: AutoAccounting does not model it.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb, ticks

_PESOS = comb(412.2, 594.2, 12)
_PART_II = {"14": 395.0, "15": 414.3, "16": 433.8, "17": 453.2, "18": 472.5, "19": 492.0, "20": 511.4,
            "21": 530.8, "22": 550.2, "23": 569.6, "24": 589.0, "25": 609.5}
_SCHEDULES = {"S2_1": 393.6, "S2_2": 410.7, "S2_3": 427.8, "S2_4": 444.9, "S2_5": 462.0, "S2_6": 479.0,
              "S2_7": 496.2, "S2_8": 513.2, "S2_9": 530.4, "S2_11": 564.6, "S2_12": 581.6, "S2_13": 599.5,
              "S3_1": 633.3, "S3_2": 650.3, "S3_3": 667.5, "S3_4": 684.5, "S3_6": 720.9,
              "S4_1": 754.6, "S4_2": 771.7, "S4_3": 788.8, "S4_4": 805.9, "S4_5": 823.0, "S4_6": 840.2,
              "S4_7": 903.5}

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1702q_jan2018.pdf",
    sha256="589e22190b9211571cb8a0ba14c97c17dff250f3b8ee9f9e8f6cc3b37b1b1be4",
    cells={
        # page 2+ header strips: TIN (without branch) and name, calibrated from the comb ticks
        "tin_p2": Cells(1, ((18.0, 33.2), (33.2, 48.5), (48.5, 63.7), (63.6, 78.9), (78.9, 94.1), (94.1, 109.3), (109.2, 124.5), (124.5, 139.7), (139.7, 154.9)), 106.0),
        "name_p2": Cells(1, ticks(230.7, 245.8, 260.9, 276.2, 291.3, 306.4, 321.5, 336.8, 351.9, 367.1, 382.3, 397.4, 412.5, 427.8, 442.9, 458.1, 473.3, 488.4, 503.5, 518.7, 533.9, 549.0, 564.2, 579.3, 594.5), 106.0),
        "year_month": Cells(0, comb(33.8, 60.6, 2), 158.3),
        "year_yy": Cells(0, comb(82.6, 108.7, 2), 158.3),
        "tin": Cells(0, comb(215.1, 260.6, 3) + comb(275.8, 321.3, 3) + comb(336.4, 381.9, 3), 193.4),
        "rdo": Cells(0, comb(533.5, 579.0, 3), 193.4),
        "name": Cells(0, comb(18.0, 594.2, 38), 223.6),
        "name_2": Cells(0, comb(18.0, 594.2, 38), 241.9),
        "address": Cells(0, comb(18.0, 594.2, 38), 272.1),
        "address_2": Cells(0, comb(18.0, 472.9, 30), 290.4),
        "zip": Cells(0, comb(533.5, 594.2, 4), 290.4),
        "contact": Cells(0, ticks(18.0, 33.2, 48.4, 63.5, 78.6, 93.9, 109.0, 124.1, 139.3, 154.5, 169.6, 184.8),
                                  320.6),
        "email": Cells(0, ticks(184.8, 200.0, 215.1, 230.3, 245.5, 260.6, 275.8, 290.9, 306.0, 321.3, 336.4, 351.5,
                                366.8, 381.9, 397.0, 412.1, 427.4, 442.5, 457.8, 472.9, 488.0, 503.1, 518.4, 533.5,
                                548.7, 563.9, 579.0, 594.2), 320.6),
        "S2_10": Cells(1, comb(548.7, 579.0, 2), 547.4, align="right"),
    },
    checks={
        "calendar": Check(0, 56.5, 132.5), "fiscal": Check(0, 112.8, 132.1),
        "q1": Check(0, 162.1, 147.9), "q2": Check(0, 189.5, 148.1), "q3": Check(0, 218.5, 147.7),
        "amended_yes": Check(0, 262.7, 149.5), "amended_no": Check(0, 306.1, 149.5),
        "itemized": Check(0, 142.4, 335.4), "osd": Check(0, 358.7, 335.8),
        "relief_no": Check(0, 227.5, 353.8),
    },
    amounts={
        **{key: Amount(0, _PESOS, y) for key, y in _PART_II.items()},
        **{key: Amount(1, _PESOS, y) for key, y in _SCHEDULES.items()},
    },
)
