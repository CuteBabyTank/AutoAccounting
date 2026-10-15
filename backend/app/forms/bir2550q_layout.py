"""Overlay map for BIR Form 2550-Q (April 2024 ENCS).

Calibrated from the template's own vector boxes and item-number text positions
(PDF points, origin top-left as PyMuPDF uses; page 612 × 1008). Amounts go one
digit per comb cell: 12 pesos cells (right-aligned) then 2 centavos cells.
"""

from pathlib import Path

from app.forms.overlay import Amount, comb

TEMPLATE_PATH = Path(__file__).parent / "templates" / "bir2550q_apr2024.pdf"
TEMPLATE_SHA256 = "18eb16925010fdda820cef958221ba2c0d073066efa93a898113e39b31135a25"
FONT_NAME = "helv"
CELL_FONT_SIZE = 9.0


def _centres(edges: list[float]) -> list[float]:
    return [round((a + b) / 2, 1) for a, b in zip(edges, edges[1:])]


# (page, column) -> (pesos cells, centavos cells), measured from the template's comb tick marks
COLUMNS = {
    (0, "B"): (comb(375.6, 546.8, 12), comb(562.0, 590.4, 2)),
    (1, "A"): (comb(162.5, 332.9, 12), comb(347.6, 376.0, 2)),
    (1, "B"): (comb(376.0, 546.8, 12), comb(561.5, 589.8, 2)),
}

_P1 = {"15": 355.0, "16": 384.1, "17": 402.3, "18": 420.6, "19": 439.1, "20": 457.1, "21": 475.3, "22": 493.6,
       "23": 511.8, "24": 530.1, "25": 548.3, "26": 566.6}
_P2_ROWS = {"31": 141.4, "32": 157.3, "33": 173.3, "34": 190.4, "35": 206.9, "36": 222.9, "37": 238.8, "38": 265.1,
            "39": 281.0, "40": 297.0, "41": 312.9, "42": 328.9, "43": 344.8, "44": 375.1, "45": 390.9, "46": 407.0,
            "47": 422.9, "48": 438.9, "49": 454.8, "50": 470.9, "51": 489.1, "52": 514.8, "53": 532.5,
            "54": 548.4, "55": 564.4, "56": 580.3, "57": 596.3, "58": 612.2, "59": 628.2, "60": 644.1,
            "61": 660.1}
_P2_COLUMN_A = {"31", "32", "33", "34", "44", "45", "46", "47", "48", "49", "50"}
_P2_COLUMN_B = {"31", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44", "45", "46", "47", "50",
                "51", "52", "53", "54", "55", "56", "57", "58", "59", "60", "61"}

# item key -> (page index, column, baseline y)
ITEMS: dict[str, tuple[int, str, float]] = {key: (0, "B", y) for key, y in _P1.items()}
ITEMS.update({f"{n}A": (1, "A", y) for n, y in _P2_ROWS.items() if n in _P2_COLUMN_A})
ITEMS.update({f"{n}B": (1, "B", y) for n, y in _P2_ROWS.items() if n in _P2_COLUMN_B})
AMOUNTS: dict[str, Amount] = {key: Amount(page, COLUMNS[(page, column)][0], baseline, COLUMNS[(page, column)][1])
                              for key, (page, column, baseline) in ITEMS.items()}

# Header (page 1 unless noted). Points are (x centre, baseline y); cell groups are (x centres, baseline y).
P1_CALENDAR = (80.9, 119.5)
P1_FISCAL = (148.0, 119.5)
P1_YEAR_ENDED = (_centres([304.9, 318.8, 332.8, 347.1, 361.4, 375.9, 389.8]), 120.0)      # MMYYYY
P1_QUARTER = {1: (441.5, 119.5), 2: (477.3, 119.5), 3: (519.4, 119.5), 4: (561.1, 119.5)}
P1_PERIOD_FROM = (_centres([64.4, 78.4, 92.4, 106.5, 120.6, 134.6, 148.6, 162.6, 176.4]), 150.0)   # MMDDYYYY
P1_PERIOD_TO = (_centres([204.7, 219.0, 233.2, 247.3, 261.6, 275.6, 289.9, 304.5, 318.6]), 150.0)
P1_AMENDED = {True: (354.0, 148.8), False: (396.5, 148.8)}
P1_SHORT_PERIOD_NO = (540.1, 148.8)
P1_TIN = (_centres([233.4, 247.3, 261.5, 275.4]) + _centres([290.0, 304.5, 318.6, 332.5])
          + _centres([347.2, 361.3, 375.8, 389.6]), 182.0)
P1_BRANCH_EDGES = (404.3, 475.5)  # pre-printed "00000" (head office)
P1_BRANCH = _centres([404.3, 418.9, 433.0, 447.2, 461.4, 475.5])
P1_RDO = (_centres([547.1, 562.1, 576.3, 591.5]), 182.0)
_LINE = [22.8, 36.1, 50.2, 64.3, 78.4, 92.3, 106.5, 120.6, 134.6, 148.6, 162.6, 176.5, 190.6, 204.7, 219.0, 233.1,
         247.3, 261.5, 275.6, 289.9, 304.5, 318.6, 332.9, 347.0, 361.3, 375.8, 389.9, 404.4, 418.9, 433.0, 447.2,
         461.4, 475.6, 489.8, 504.0, 518.2, 532.4, 546.9, 562.1, 576.3, 591.5]
P1_NAME = (_centres(_LINE), 211.0)
P1_ADDRESS = (_centres(_LINE), 239.5)
P1_ZIP = (_centres([532.6, 546.9, 562.1, 576.3, 591.5]), 257.0)
P1_CONTACT = (_centres(_LINE[:14]), 288.0)
P1_EMAIL = (_centres(_LINE[13:]), 288.0)
# Item 13 taxpayer classification and item 14 tax relief: (x centre, baseline), from the template's check boxes.
P1_CLASS = {"micro": (168.2, 302.8), "small": (238.5, 302.8), "medium": (309.0, 302.8), "large": (396.3, 303.8)}
P1_RELIEF_NO = (241.8, 322.6)
P2_TIN = (_centres([22.8, 36.1, 50.2, 64.4, 78.4, 92.5, 106.6, 120.6, 134.7, 148.9]), 103.0)
P2_NAME = (_centres([219.4, 233.9, 248.1, 262.2, 276.4, 290.5, 305.0, 319.2, 333.5, 347.5, 361.8, 376.0, 390.2,
                     404.4, 418.6, 432.8, 447.0, 461.2, 475.4, 489.6, 503.8, 517.9, 532.1, 546.7, 561.4, 575.6,
                     589.7]), 103.0)
FOOTNOTE = (24.0, 985.0)
DRAFT_BANNER = (24.0, 970.0)
