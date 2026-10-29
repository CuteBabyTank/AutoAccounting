"""Choose a safe PDF raster size before MuPDF allocates a pixmap."""

import math

MAX_RENDER_PIXELS = 40_000_000
MAX_RENDER_SIDE = 10_000


def render_zoom(width: float, height: float, dpi: float) -> float:
    """Keep the requested DPI when possible, bounded by both area and side length."""
    if any(not math.isfinite(v) or v <= 0 for v in (width, height, dpi)):
        raise ValueError("Page dimensions and DPI must be finite and positive")
    # Transformed rectangle edges may round outwards by up to two pixels per
    # axis, including clips with nonzero origins. Reserve room for that here.
    pixels = MAX_RENDER_PIXELS - 4 * MAX_RENDER_SIDE
    return min(dpi / 72, (MAX_RENDER_SIDE - 2) / width, (MAX_RENDER_SIDE - 2) / height,
               math.sqrt(pixels / width / height))

