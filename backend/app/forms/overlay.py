"""Shared shapes for BIR "comb" form overlays: one character per printed cell.

Coordinates are PDF points, origin top-left (PyMuPDF). A cell is an (x0, x1)
pair; ``comb`` splits a run of equal cells, and runs are joined with ``+`` where
a box has printed separators (a TIN's dashes, an amount's decimal point).
"""

from dataclasses import dataclass
from pathlib import Path

Cell = tuple[float, float]


def comb(x0: float, x1: float, n: int) -> tuple[Cell, ...]:
    """``n`` equal cells across [x0, x1]."""
    step = (x1 - x0) / n
    return tuple((round(x0 + step * i, 2), round(x0 + step * (i + 1), 2)) for i in range(n))


def ticks(*xs: float) -> tuple[Cell, ...]:
    """Cells between consecutive measured tick marks, for combs whose spacing is uneven."""
    return tuple(zip(xs, xs[1:]))


@dataclass(frozen=True)
class Cells:
    """Text written one character per cell; a single cell takes the whole text, centred."""

    page: int
    cells: tuple[Cell, ...]
    baseline: float
    align: str = "left"  # left | right


@dataclass(frozen=True)
class Check:
    page: int
    x: float
    baseline: float


@dataclass(frozen=True)
class Amount:
    """Digits one per cell, right-aligned; ``cents=()`` for whole-peso returns."""

    page: int
    pesos: tuple[Cell, ...]
    baseline: float
    cents: tuple[Cell, ...] = ()


@dataclass(frozen=True)
class FormLayout:
    template: Path
    sha256: str
    cells: dict[str, Cells]
    checks: dict[str, Check]
    amounts: dict[str, Amount]
