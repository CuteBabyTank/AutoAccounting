"""Overlay map for BIR Form 1701 (January 2018 ENCS), page 612 × 936, four pages.

Whole pesos only. Only column A (taxpayer/filer) is filled: the spouse column,
the per-employer rows of Schedule 1 (Schedule 2 carries the 2316 totals), special deductions (Schedule 5), tax relief
(Part VIII) and payment details are not modelled. Calibrated from the template's
comb tick marks, which are unevenly spaced on this form, so cells follow the measured
ticks; baselines sit 2 pt above the bottom ticks. The NOLCO detail
table (Schedule 6.A.1) and description lines are open boxes: they get narrow
evenly spaced cells (``_free``).
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb, ticks


def _free(x0: float, x1: float, pitch: float = 7.0):
    """Even cells across an open box, so digits and letters still sit one per cell."""
    return comb(x0 + 2, x1 - 2, int((x1 - x0 - 4) // pitch))


_ROW = ticks(14.9, 28.7, 42.5, 56.4, 70.5, 84.5, 98.7, 112.7, 126.7, 141.0, 155.1, 169.3, 183.6, 197.9, 212.2,
             226.6, 240.9, 255.5, 269.9, 284.3, 298.5, 313.3, 328.3, 342.7, 357.1, 371.6, 386.8, 402.2, 417.4,
             432.7, 447.9, 462.8, 477.7, 491.9, 506.0, 522.3, 538.7, 552.8, 568.2, 583.5, 598.9)
_A_P1 = _ROW[22:31]
_A_P2 = ticks(327.8, 342.1, 356.5, 370.9, 386.1, 401.2, 416.5, 431.6, 446.8, 462.0)
_A_P3_SCHED4 = ticks(326.4, 340.8, 355.1, 369.7, 384.8, 399.9, 415.1, 430.3, 445.5, 460.7)
_A_P3_SCHED6 = ticks(328.2, 343.1, 358.1, 373.0, 388.1, 403.1, 418.5, 433.9, 448.9, 463.9)
_A_P4_PART9 = ticks(328.6, 342.9, 357.2, 371.7, 386.8, 401.9, 417.1, 432.2, 447.3, 462.3)
_PART_II = {"22": 481.4, "23": 498.4, "24": 515.5, "25": 533.8, "26": 551.0, "27": 568.0, "28": 585.2,
            "29": 602.2, "30": 619.4, "31": 636.5}
_SCHEDULE_3A = {"S3_8": 619.0, "S3_9": 635.0, "S3_10": 651.0, "S3_11": 666.9, "S3_12": 682.9, "S3_13": 708.5,
                "S3_14": 724.4, "S3_15": 740.4, "S3_16": 756.3, "S3_17": 782.0, "S3_18": 798.0, "S3_19": 822.5,
                "S3_20": 837.2, "S3_21": 852.0, "S3_22": 866.9, "S3_23": 881.6, "S3_24": 898.1, "S3_25": 918.6}
_SCHEDULE_2 = {"S2_4": 532.3, "S2_5": 548.2, "S2_6": 564.2, "S2_7": 580.1}
_SCHEDULE_3B = {"S3_26": 133.5, "S3_27": 161.4, "S3_28": 177.4, "S3_29": 196.2, "S3_30": 212.2, "S3_31": 228.1,
                "S3_32": 245.1}
_SCHEDULE_4 = {f"S4_{n}": y for n, y in zip(range(1, 17), (
    275.3, 291.3, 307.2, 323.2, 339.2, 355.1, 371.1, 387.0, 403.0, 419.0, 434.9, 450.8, 466.8, 482.7, 498.7,
    514.6))}
_SCHEDULE_4.update({"S4_17A": 542.0, "S4_17B": 559.2, "S4_17C": 576.2, "S4_17D": 593.3, "S4_18": 609.3})
_SCHEDULE_6 = {"S6_1": 789.5, "S6_2": 805.4, "S6_3": 821.3}
_NOLCO_ROWS = {4: 868.0, 5: 879.0, 6: 889.8, 7: 900.7}
_NOLCO_COLUMNS = {"A": (84.5, 184.3), "B": (184.3, 284.9), "C": (284.9, 387.4), "D": (387.4, 493.5),
                  "E": (493.5, 598.2)}
_PART_VI = {"P6_1": 224.9, "P6_2": 239.8, "P6_3": 254.5, "P6_4": 269.3, "P6_5": 284.2}
_PART_VII = {f"P7_{n}": y for n, y in zip(range(1, 11), (
    313.4, 328.1, 342.9, 357.8, 372.5, 387.3, 402.2, 416.9, 431.7, 446.6))}
_PART_IX = {"P9_1": 676.4, "P9_2": 701.0, "P9_3": 715.8, "P9_4": 730.5, "P9_5": 745.4, "P9_6": 769.9,
            "P9_7": 784.7, "P9_8": 809.1, "P9_9": 823.9, "P9_10": 838.8, "P9_11": 853.7}
_DESCRIBED = ("P9_2", "P9_3", "P9_4", "P9_6", "P9_7", "P9_8", "P9_9")
_PAGE_HEADER = {1: 93.0, 2: 93.5, 3: 90.1}
_HEADER = ticks(14.9, 28.1, 41.4, 54.7, 68.2, 81.6, 95.1, 108.5, 121.9, 135.4, 150.0, 164.8, 179.4, 194.2, 208.8,
                223.8, 238.8, 253.8, 268.9, 283.9, 298.9, 313.9, 328.9, 343.9, 358.9, 373.9, 388.9, 403.9, 418.9,
                433.9, 448.9, 463.9, 478.9, 493.9, 508.9, 523.9, 538.9, 553.9, 568.9, 583.9, 598.9)


def _amounts() -> dict[str, Amount]:
    out: dict[str, Amount] = {}
    for page, cells, rows in ((0, _A_P1, _PART_II), (1, _A_P2, _SCHEDULE_2), (1, _A_P2, _SCHEDULE_3A),
                              (2, _A_P2, _SCHEDULE_3B),
                              (2, _A_P3_SCHED4, _SCHEDULE_4), (2, _A_P3_SCHED6, _SCHEDULE_6), (3, _A_P2, _PART_VI),
                              (3, _A_P2, _PART_VII), (3, _A_P4_PART9, _PART_IX)):
        out.update({key: Amount(page, cells, y - 2) for key, y in rows.items()})
    out["32"] = Amount(0, _ROW[26:35], 650.4)
    for row, baseline in _NOLCO_ROWS.items():
        for column, (x0, x1) in _NOLCO_COLUMNS.items():
            out[f"S6_{row}_{column}"] = Amount(2, _free(x0, x1), baseline)
    out["S6_8"] = Amount(2, _free(387.4, 493.5), 911.5)
    return out


def _cells() -> dict[str, Cells]:
    out = {
        "year": Cells(0, ticks(128.1, 142.3, 156.7, 171.3, 185.5), 116.7),
        "tin": Cells(0, ticks(195.4, 209.6, 223.8, 238.1) + ticks(252.8, 267.5, 281.8, 296.4)
                     + ticks(313.3, 328.3, 342.7, 357.1), 149.3),
        "rdo": Cells(0, ticks(552.3, 567.7, 582.9, 598.9), 149.3),
        "name": Cells(0, _ROW, 224.9),
        "address": Cells(0, _ROW, 251.2),
        "address_2": Cells(0, _ROW[:31], 267.2),
        "zip": Cells(0, _ROW[36:], 267.2),
        "contact": Cells(0, ticks(14.9, 29.0, 43.2, 57.4, 71.7, 85.9, 100.2, 114.5, 128.8, 143.1, 157.5, 171.7, 186.0,
                                  197.8), 349.4),
        "email": Cells(0, _ROW[8:], 293.5),
        "S3_19_DESC": Cells(1, _free(31.4, 313.5, 7.5), 820.5),
        "S3_27_DESC": Cells(2, _free(31.4, 313.5, 7.5), 159.4),
        "S4_17D_DESC": Cells(2, _free(46.0, 312.0, 7.5), 591.3),
    }
    for page, y in _PAGE_HEADER.items():  # every later page repeats the TIN and the filer's name
        out[f"tin_p{page + 1}"] = Cells(page, _HEADER[:9], y - 2)
        out[f"name_p{page + 1}"] = Cells(page, _HEADER[14:], y - 2)
    for row, baseline in _NOLCO_ROWS.items():
        out[f"S6_{row}_YEAR"] = Cells(2, _free(28.6, 84.5, 9.0), baseline)
    for key in _DESCRIBED:
        out[f"{key}_DESC"] = Cells(3, _free(36.0, 314.0, 7.5), _PART_IX[key] - 2)
    return out


LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1701_jan2018.pdf",
    sha256="19be91d78258eb7c255f2615610db2739f10c378f8ac97adc0887c1bf40d1b2e",
    cells=_cells(),
    checks={
        "amended_yes": Check(0, 306.2, 112.2), "amended_no": Check(0, 349.8, 112.2),
        "short_no": Check(0, 549.8, 112.3),
        "single_proprietor": Check(0, 119.0, 162.5), "professional": Check(0, 218.0, 162.5),
        "compensation_earner": Check(0, 446.6, 162.5),
        "atc_II012": Check(0, 161.5, 180.5), "atc_II015": Check(0, 161.7, 194.4),
        "atc_II013": Check(0, 470.3, 180.5), "atc_II017": Check(0, 308.1, 194.4),
        "foreign_credits_no": Check(0, 326.4, 318.6),
        "exempt_no": Check(0, 267.4, 373.8), "special_no": Check(0, 562.4, 373.8),
        "rate_graduated": Check(0, 68.7, 405.5), "rate_eight": Check(0, 68.9, 427.5),
        "itemized": Check(0, 235.0, 406.0), "osd": Check(0, 366.6, 406.0),
        "refund": Check(0, 69.3, 672.4), "tcc": Check(0, 169.7, 672.5), "carry_over": Check(0, 366.9, 672.5),
    },
    amounts=_amounts(),
)
