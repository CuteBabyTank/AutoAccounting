"""Decimal helpers for tax computation (pure)."""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
_CENT = Decimal("0.01")
_PESO = Decimal("1")


def d(value) -> Decimal:
    """Coerce a number or numeric string to Decimal (None or '' -> 0)."""
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def c2(value) -> Decimal:
    """Round to centavos, half up (VAT and percentage tax returns)."""
    return d(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def peso(value) -> Decimal:
    """Round to whole pesos, half up (income tax returns: 'DO NOT enter Centavos')."""
    return d(value).quantize(_PESO, rounding=ROUND_HALF_UP)


def total(values: Iterable) -> Decimal:
    return c2(sum((d(v) for v in values), Decimal("0")))
