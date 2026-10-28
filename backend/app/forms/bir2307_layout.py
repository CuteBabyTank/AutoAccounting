"""
Coordinate map for the BIR Form 2307 (January 2018 ENCS) overlay renderer.
Coordinates are in PDF points with origin at top-left of page (PyMuPDF convention).
Calibrated against ``backend/app/forms/templates/bir2307_jan2018.pdf``
(page rect: 612 x 936, US Letter portrait) by extracting the template's vector
rectangles and dividers; see ``_extract_layout.py`` (one-shot).
"""
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "templates" / "bir2307_jan2018.pdf"

FONT_NAME = "helv"
FONT_SIZE = 9


def _evenly_spaced(x0: float, x1: float, n: int) -> list[float]:
    """Return centers of n equal-width cells across [x0, x1]."""
    w = (x1 - x0) / n
    return [x0 + w * (i + 0.5) for i in range(n)]


# --- Period dates ------------------------------------------------------------
# Each date is split into 8 cells (MMDDYYYY).
# "From" date area spans x=151.5..256.7, "To" area spans x=399.1..504.5,
# both at y=106.4..122.3. Text baseline ≈ y=118.
DATE_CELLS_FROM: list[float] = _evenly_spaced(151.5, 256.7, 8)
DATE_CELLS_TO:   list[float] = _evenly_spaced(399.1, 504.5, 8)
DATE_BASELINE_Y: float = 118.0

# --- TIN rows ----------------------------------------------------------------
# 14 cells per TIN: groups of 3-3-3-5. Calibrated from rect+divider extraction.
# Payee TIN baseline y=149; Payor TIN baseline y=264.
PAYEE_TIN_CELLS: list[float] = [
    # Group 1 (rect 207.2-246.8, ticks 219.3, 232.7)
    213.25, 226.00, 239.75,
    # Group 2 (rect 258.9-298.5, ticks 271.0, 284.3)
    264.95, 277.65, 291.40,
    # Group 3 (rect 310.2-349.8, ticks 322.8, 336.1)
    316.50, 329.45, 342.95,
    # Group 4 (rect 361.5-435.4, ticks 375.9, 391.0, 407.0, 421.9)
    368.70, 383.45, 399.00, 414.45, 428.65,
]
PAYEE_TIN_BASELINE_Y: float = 149.0

PAYOR_TIN_CELLS: list[float] = [
    # Group 1 (rect 208.0-247.6, ticks 219.6, 233.0)
    213.80, 226.30, 240.30,
    # Group 2 (rect 259.5-299.1, ticks 271.6, 285.0)
    265.55, 278.30, 292.05,
    # Group 3 (rect 310.9-350.5, ticks 323.5, 336.9)
    317.20, 330.20, 343.70,
    # Group 4 (rect 362.3-436.3, ticks 376.7, 391.8, 407.8, 422.7)
    369.50, 384.25, 399.80, 415.25, 429.50,
]
PAYOR_TIN_BASELINE_Y: float = 264.0

# --- ZIP code (4 cells, x range identical for 4A and 8A) ---------------------
# Rect x=541.8..591.8 (w=50), ticks at 553.9, 567.3, 580.5
ZIP_CELLS: list[float] = [547.85, 560.60, 573.90, 586.15]
PAYEE_ZIP_BASELINE_Y: float = 204.0  # rect y=192.7..208.5
PAYOR_ZIP_BASELINE_Y: float = 319.0  # rect y=307.9..323.7

# --- Free-text rows (single-line input strips) -------------------------------
# (x_left, baseline_y, max_width_pt): x_left = a hair inside the input rect.
PAYEE_NAME:                  tuple[float, float, float] = (36.0, 176.0, 555.0)
PAYEE_REGISTERED_ADDRESS:    tuple[float, float, float] = (36.0, 204.0, 500.0)
PAYEE_FOREIGN_ADDRESS:       tuple[float, float, float] = (36.0, 233.0, 555.0)
PAYOR_NAME:                  tuple[float, float, float] = (36.0, 291.0, 555.0)
PAYOR_REGISTERED_ADDRESS:    tuple[float, float, float] = (36.0, 319.0, 500.0)

# --- Part III tables ---------------------------------------------------------
# Calibrated from horizontal row dividers + vertical column dividers.
LINE_ROW_HEIGHT: float = 13.7
EWT_FIRST_ROW_TOP_Y: float = 364.8
MP_FIRST_ROW_TOP_Y: float = 534.3
LINE_TEXT_Y_OFFSET: float = 9.7  # baseline = row_top + offset
EWT_ROWS: int = 10
MP_ROWS: int = 10

# Column geometry. "left" / "right" tell the renderer how to align text.
# (col_left, col_right, alignment)
COL_DESCRIPTION:  tuple[float, float, str] = (21.4, 174.4, "left")
COL_ATC:          tuple[float, float, str] = (178.4, 217.6, "left")
COL_M1:           tuple[float, float, str] = (221.6, 289.6, "right")
COL_M2:           tuple[float, float, str] = (293.6, 364.0, "right")
COL_M3:           tuple[float, float, str] = (368.0, 436.0, "right")
COL_TOTAL:        tuple[float, float, str] = (440.0, 508.0, "right")
COL_TAX_WITHHELD: tuple[float, float, str] = (512.0, 594.0, "right")

# --- Payor signature box (upper signature block) -----------------------------
# The empty signing strip sits between the perjury-declaration row (which ends at
# y=722) and the caption line (y=750): "Signature over Printed Name of Payor/
# Payor's Authorized Representative/Tax Agent". The full strip spans x=18.5..597;
# we center a narrower box over the caption (caption text spans x≈165..448).
# E-signatures are stamped here on every page of a generated document.
PAYOR_SIGNATURE_BOX: tuple[float, float, float, float] = (200.0, 723.0, 412.0, 749.0)
# Printed name is drawn just under the signature image, inside the same strip.
SIGNATURE_NAME_FONT_SIZE: float = 7.0
