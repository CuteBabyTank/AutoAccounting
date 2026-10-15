"""
Per-field text normalisation for BIR Form 2307 extraction output.

These functions are applied as post-processing after Gemini returns extracted
text. Originally from the desktop OCR pipeline, ported verbatim.
"""

import re


def clean_tin(text: str) -> str:
    """Normalise TIN to NNN-NNN-NNN-NNNNN (or shorter last group) format."""
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 12:
        # Keep ALL digits after the first 9 (last group can be 3-5+ digits)
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:9]}-{digits[9:]}"
    if len(digits) >= 9:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:9]}"
    return digits


def clean_date(text: str) -> str:
    """Normalise period dates to MM/DD/YYYY."""
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) == 8:
        return f"{digits[0:2]}/{digits[2:4]}/{digits[4:8]}"
    return re.sub(r"\s+", " ", text).strip()


def clean_amount(text: str) -> str:
    """Normalise currency amounts: remove peso signs, fix O/0 confusion."""
    text = re.sub(r"(?<=[0-9,. ])O(?=[0-9,. ])", "0", text)
    text = re.sub(r"^O", "0", text)
    text = re.sub(r"[^\d,.\-]", "", text)
    return text.strip()


def clean_text(text: str) -> str:
    """General-purpose: collapse whitespace, strip common border noise."""
    text = re.sub(r"\s+", " ", text)
    return text.strip(" |_-:")


def clean_atc(text: str) -> str:
    """ATC codes are alphanumeric up to 6 chars."""
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()[:6]


def clean_zip(text: str) -> str:
    """Philippine zip codes are 4 digits."""
    return re.sub(r"[^0-9]", "", text)[:4]
