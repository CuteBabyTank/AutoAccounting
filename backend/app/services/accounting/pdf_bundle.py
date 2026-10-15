"""Choosing and bundling several return PDFs into one download (pure)."""

import io
import zipfile
from collections.abc import Iterable

from app.services.accounting.compute.specs import FORM_ORDER, PDF_FORMS


def validate_requested(requested: list[str], expected: list[str], available: Iterable[str]) -> list[str]:
    if not requested:
        raise ValueError("Pick at least one form")
    available = set(available)
    for form in requested:
        if form not in expected or form not in PDF_FORMS:
            raise ValueError(f"{form} isn't filed for this quarter")
        if form not in available:
            raise ValueError(f"This version has no {form}")
    wanted = set(requested)
    return [form for form in FORM_ORDER if form in wanted]


def zip_pdfs(files: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            z.writestr(name, data)
    return buffer.getvalue()
