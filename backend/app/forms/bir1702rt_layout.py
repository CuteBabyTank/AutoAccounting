"""Overlay map for BIR Form 1702-RT (January 2018 ENCS), page 612 × 936, four pages.

Whole pesos only. Calibrated from the template's comb tick marks (cells are
15.16 pt wide); baselines sit 2 pt above the bottom ticks. Full-width table rows
are one 38-cell comb (``_grid``) split at the printed column rules. Part V (tax
relief), Schedule II (special deductions) and payment details are not filled.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb, ticks

_LEFT, _RIGHT, _CELLS = 18.0, 594.2, 38
_STEP = (_RIGHT - _LEFT) / _CELLS


def _grid(k0: int, k1: int):
    """Cells k0..k1-1 of a full-width 38-cell row."""
    return comb(round(_LEFT + _STEP * k0, 2), round(_LEFT + _STEP * k1, 2), k1 - k0)


_PESOS = comb(412.2, 594.2, 12)
_PART_II = {"14": 429.9, "15": 449.2, "16": 468.7, "17": 498.9, "18": 518.3, "19": 537.7, "20": 557.1, "21": 576.5}
_PART_IV = {"27": 204.9, "28": 224.2, "29": 243.6, "30": 263.1, "31": 282.4, "32": 301.8, "33": 321.3,
            "34": 351.5, "35": 370.8, "36": 390.3, "37": 409.7, "38": 441.0, "39": 460.5, "41": 498.2,
            "42": 517.5, "43": 537.0, "44": 567.2, "45": 586.6, "46": 606.0, "47": 625.4, "48": 644.9,
            "49": 664.2, "50": 683.6, "51": 703.1, "52": 722.4, "53": 752.6, "54": 772.1, "55": 791.5,
            "56": 810.9}
_SCHEDULE_I = {"S1_1": 167.8, "S1_2": 187.2, "S1_3": 206.7, "S1_4": 226.0, "S1_5": 245.4, "S1_6": 264.9,
               "S1_7": 284.2, "S1_8": 303.7, "S1_9": 323.1, "S1_10": 342.4, "S1_11": 361.8, "S1_12": 381.2,
               "S1_13": 400.6, "S1_14": 420.0, "S1_15": 439.4, "S1_16": 458.8, "S1_17A": 489.1,
               "S1_17B": 508.5, "S1_17C": 527.8, "S1_17D": 547.3, "S1_17E": 566.7, "S1_17F": 586.0,
               "S1_18": 663.8}
_NOLCO_TOP = {4: 249.7, 5: 269.1, 6: 288.5, 7: 309.0}
_NOLCO_BOTTOM = {4: 365.0, 5: 384.4, 6: 403.8, 7: 423.2}
_MCIT_TOP = {1: 489.4, 2: 508.8, 3: 528.2}
_MCIT_BOTTOM = {1: 595.0, 2: 614.5, 3: 633.9}
_SCHEDULE_V = {"S5_1": 689.3, "S5_2": 719.5, "S5_3": 738.8, "S5_4": 758.3, "S5_5": 788.5, "S5_6": 807.9,
               "S5_7": 838.2, "S5_8": 857.5, "S5_9": 877.0, "S5_10": 897.5}
_PAGE_HEADER = {1: 169.9, 2: 121.1, 3: 121.1}
_DESCRIBED = ("S5_2", "S5_3", "S5_5", "S5_6", "S5_7", "S5_8")


def _amounts() -> dict[str, Amount]:
    out = {key: Amount(0, _PESOS, y - 2) for key, y in _PART_II.items()}
    out.update({key: Amount(1, _PESOS, y - 2) for key, y in _PART_IV.items()})
    out.update({key: Amount(2, _PESOS, y - 2) for key, y in _SCHEDULE_I.items()})
    out.update({"S3_1": Amount(3, _PESOS, 154.0), "S3_2": Amount(3, _PESOS, 173.3),
                "S3_3": Amount(3, _PESOS, 193.7), "S3_8": Amount(3, comb(230.3, 412.2, 12), 441.7),
                "S4_4": Amount(3, comb(306.1, 457.7, 10), 652.3)})
    for row, y in _NOLCO_TOP.items():
        out[f"S3_{row}_A"] = Amount(3, comb(200.0, 381.9, 12), y - 2)
        out[f"S3_{row}_B"] = Amount(3, comb(412.1, 594.2, 12), y - 2)
    for row, y in _NOLCO_BOTTOM.items():
        out[f"S3_{row}_C"] = Amount(3, comb(48.4, 230.3, 12), y - 2)
        out[f"S3_{row}_D"] = Amount(3, comb(230.3, 412.2, 12), y - 2)
        out[f"S3_{row}_E"] = Amount(3, comb(412.2, 594.2, 12), y - 2)
    for row, y in _MCIT_TOP.items():
        out[f"S4_{row}_A"] = Amount(3, _grid(5, 16), y - 2)
        out[f"S4_{row}_B"] = Amount(3, _grid(16, 27), y - 2)
        out[f"S4_{row}_C"] = Amount(3, _grid(27, 38), y - 2)
    for row, y in _MCIT_BOTTOM.items():
        out[f"S4_{row}_D"] = Amount(3, _grid(1, 10), y - 2)
        out[f"S4_{row}_E"] = Amount(3, _grid(10, 19), y - 2)
        out[f"S4_{row}_F"] = Amount(3, _grid(19, 29), y - 2)
        out[f"S4_{row}_G"] = Amount(3, _grid(29, 38), y - 2)
    out.update({key: Amount(3, _PESOS, y - 2) for key, y in _SCHEDULE_V.items()})
    return out


def _cells() -> dict[str, Cells]:
    out = {
        "year_month": Cells(0, comb(33.8, 60.6, 2), 161.3),
        "year_yy": Cells(0, comb(82.6, 108.7, 2), 161.3),
        "tin": Cells(0, comb(215.1, 260.6, 3) + comb(275.8, 321.3, 3) + comb(336.4, 381.9, 3), 196.9),
        "rdo": Cells(0, comb(533.5, 579.0, 3), 196.9),
        "name": Cells(0, _grid(0, 38), 227.1),
        "name_2": Cells(0, _grid(0, 38), 246.4),
        "name_3": Cells(0, _grid(0, 38), 265.9),
        "address": Cells(0, _grid(0, 38), 296.1),
        "address_2": Cells(0, _grid(0, 38), 315.6),
        "address_3": Cells(0, comb(18.0, 472.9, 30), 334.9),
        "zip": Cells(0, comb(533.5, 594.2, 4), 334.9),
        "contact": Cells(0, ticks(427.4, 442.5, 457.8, 472.9, 488.0, 503.1, 518.4, 533.5, 548.7, 563.9, 579.0, 594.2),
                                  354.3),
        "email": Cells(0, ticks(109.0, 124.1, 139.3, 154.5, 169.6, 184.8, 200.0, 215.1, 230.3, 245.5, 260.6, 275.8,
                                290.9, 306.0, 321.3, 336.4, 351.5, 366.8, 381.9, 397.0, 412.1, 427.4, 442.5, 457.8,
                                472.9, 488.0, 503.1, 518.4, 533.5, 548.7, 563.9, 579.0, 594.2), 373.8),
        "40": Cells(1, comb(548.7, 579.0, 2), 476.8, align="right"),
        "S1_17D_DESC": Cells(2, comb(48.4, 397.1, 23), 545.3),
        "S1_17E_DESC": Cells(2, comb(48.4, 397.1, 23), 564.7),
        "S1_17F_DESC": Cells(2, comb(48.4, 397.1, 23), 584.0),
    }
    for page, y in _PAGE_HEADER.items():  # every later page repeats the TIN and registered name
        out[f"tin_p{page + 1}"] = Cells(page, _grid(0, 9), y - 2)
        out[f"name_p{page + 1}"] = Cells(page, _grid(14, 38), y - 2)
    for row, y in _NOLCO_TOP.items():
        out[f"S3_{row}_YEAR"] = Cells(3, comb(78.6, 139.3, 4), y - 2)
    for row, y in _MCIT_TOP.items():
        out[f"S4_{row}_YEAR"] = Cells(3, _grid(1, 5), y - 2)
    for key in _DESCRIBED:
        out[f"{key}_DESC"] = Cells(3, _grid(1, 25), _SCHEDULE_V[key] - 2)
    return out


LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1702rt_jan2018.pdf",
    sha256="d9a6a8a13e0114934261151c4eb269a1573042e7ce670eaf12b15f169d308d2d",
    cells=_cells(),
    checks={
        "calendar": Check(0, 56.5, 138.3), "fiscal": Check(0, 112.8, 137.9),
        "amended_yes": Check(0, 167.0, 154.1), "amended_no": Check(0, 210.0, 154.1),
        "short_no": Check(0, 306.1, 154.1),
        "atc_IC055": Check(0, 572.0, 144.6),
        "itemized": Check(0, 142.5, 388.6), "osd": Check(0, 358.7, 388.8),
        "refund": Check(0, 43.0, 598.5), "tcc": Check(0, 136.3, 598.2), "carry_over": Check(0, 343.2, 598.3),
    },
    amounts=_amounts(),
)
