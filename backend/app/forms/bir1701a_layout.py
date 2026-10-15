"""Overlay map for BIR Form 1701-A (January 2018), page 612 × 936, two pages.

Whole pesos only. Only column A (taxpayer/filer) is filled: the spouse column,
Part V (spouse background) and payment details are not modelled. Calibrated
from the template's comb tick marks, which are unevenly spaced, so cells follow
the measured ticks; baselines sit 2 pt above the bottom ticks.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb, ticks

_ROW = ticks(14.9, 28.7, 42.5, 56.3, 70.2, 84.3, 98.4, 112.5, 126.5, 140.7, 154.8, 169.0, 183.3, 197.6, 211.8,
             226.2, 240.5, 255.3, 269.7, 284.0, 298.3, 312.9, 327.9, 342.3, 356.8, 371.4, 386.6, 401.8, 417.1,
             432.7, 447.9, 462.8, 477.8, 491.9, 506.0, 522.5, 538.8, 552.9, 568.3, 583.5, 599.0)
_HEADER_P2 = ticks(14.9, 28.1, 41.4, 54.7, 68.2, 81.6, 95.1, 108.5, 121.9, 135.4, 150.0, 164.8, 179.4, 194.2, 208.8,
                   222.3, 235.8, 249.4, 263.0, 276.5, 290.0, 303.6, 317.2, 330.8, 344.2, 357.8, 371.7, 385.6, 403.3,
                   421.0, 438.7, 456.3, 474.1, 491.1, 508.2, 526.2, 544.2, 557.7, 571.3, 584.9, 598.9)
_A_P1 = ticks(358.5, 373.0, 388.0, 402.9, 418.3, 433.5, 448.8, 463.9, 478.9)
_A_P2 = ticks(356.2, 371.2, 386.4, 401.5, 416.6, 431.7, 446.7, 462.6, 477.7)
_A_P2_CREDITS = ticks(356.9, 372.1, 387.1, 402.2, 417.3, 432.4, 447.4, 462.6, 477.7)
_PART_II = {"20": 450.3, "21": 468.5, "22": 486.8, "23": 505.1, "24": 523.4, "25": 541.6, "26": 559.9,
            "27": 578.1, "28": 596.3, "29": 614.6}
_PART_IV = {"36": 159.6, "37": 176.7, "38": 193.6, "39": 210.5, "40": 227.4, "41": 256.6, "42": 274.8,
            "43": 291.8, "44": 307.7, "45": 323.7, "46": 339.7, "47": 369.4, "48": 386.5, "49": 403.4,
            "50": 432.4, "51": 450.7, "52": 467.7, "53": 484.6, "54": 504.1, "55": 521.0, "56": 537.9}
_CREDITS = {"57": 565.8, "58": 581.7, "59": 597.7, "60": 613.6, "61": 629.6, "62": 645.6, "63": 661.4,
            "64": 677.4, "65": 694.4}


def _free(x0: float, x1: float, pitch: float = 7.5):
    """Even cells across an open box, so letters still sit one per cell."""
    return comb(x0 + 2, x1 - 2, int((x1 - x0 - 4) // pitch))


def _amounts() -> dict[str, Amount]:
    out = {key: Amount(0, _A_P1, y - 2) for key, y in _PART_II.items()}
    out["30"] = Amount(0, ticks(418.3, 433.5, 448.8, 463.9, 478.9, 493.2, 507.5, 524.1, 540.7), 630.9)
    out.update({key: Amount(1, _A_P2, y - 2) for key, y in _PART_IV.items()})
    out.update({key: Amount(1, _A_P2_CREDITS, y - 2) for key, y in _CREDITS.items()})
    return out


LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1701a_jan2018.pdf",
    sha256="8d492eabc6da2088cf9a55084488b192def5cc415048f607142c8bce1b72bfb8",
    cells={
        "year_month": Cells(0, ticks(113.9, 128.1, 142.3), 124.1),
        "year": Cells(0, ticks(142.3, 156.7, 171.3, 183.3, 197.6), 124.1),
        "tin": Cells(0, _ROW[1:4] + _ROW[5:8] + _ROW[9:12], 168.8),
        "rdo": Cells(0, _ROW[20:23], 168.8),
        "name": Cells(0, _ROW, 230.6),
        "address": Cells(0, _ROW, 259.3),
        "address_2": Cells(0, _ROW[:31], 277.5),
        "zip": Cells(0, _ROW[36:], 277.5),
        "contact": Cells(0, ticks(14.9, 28.7, 42.5, 56.3, 70.2, 84.3, 98.4, 112.5, 126.5, 140.7, 154.8, 169.0, 183.3,
                                  197.6), 364.3),
        "email": Cells(0, _ROW[8:], 306.1),
        "tin_p2": Cells(1, _HEADER_P2[:9], 105.7),
        "name_p2": Cells(1, _HEADER_P2[14:], 105.7),
        "41_DESC": Cells(1, _free(30.5, 342.1), 254.6),
        "50_DESC": Cells(1, _free(30.5, 342.1), 430.4),
    },
    checks={
        "amended_yes": Check(0, 306.2, 119.7), "amended_no": Check(0, 349.8, 119.7),
        "short_no": Check(0, 549.8, 119.8),
        "single_proprietor": Check(0, 399.7, 164.3), "professional": Check(0, 515.0, 165.5),
        "atc_II012": Check(0, 166.0, 184.0), "atc_II014": Check(0, 354.5, 184.0),
        "atc_II015": Check(0, 165.7, 197.8), "atc_II017": Check(0, 354.3, 197.1),
        "foreign_credits_no": Check(0, 319.2, 332.3),
        "rate_osd": Check(0, 88.7, 397.9), "rate_eight": Check(0, 275.9, 398.3),
        "refund": Check(0, 69.3, 652.8), "tcc": Check(0, 169.7, 652.9), "carry_over": Check(0, 366.9, 652.9),
    },
    amounts=_amounts(),
)
