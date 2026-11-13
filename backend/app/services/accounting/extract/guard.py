"""Guard for the free-text "missing fields" note people type into the Extract tab.

The note ends up near a model prompt, so it is never passed on as text. It is refused when it reads like an
instruction, otherwise reduced to a short list of plain field names that the builder asks the model about.
"""

import re
import unicodedata

from app.services.accounting.extract import spec

NOTE_MAX = 200
ASKS_PER_DRAFT = 5
ADDED_PER_DRAFT = 10

REFUSED_PHRASES = (
    "ignore", "disregard", "instead", "instruction", "system prompt", "prompt", "you are", "act as", "pretend",
    "assistant", "http", "www.", "override", "jailbreak", "do not", "don't", "return the", "list all",
    "every client", "other firm",
)
_MESSAGE = "Type only the names of the missing fields, separated by commas."
_SPLIT = re.compile(r"[,;]|\s+and\s+", re.IGNORECASE)
_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 \u00f1\u00d1-/.,()%#&';:")
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'", "\u02bc": "'"})


def _spaced(text: str) -> str:
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text.casefold()).split())


def _compact(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


_SPACED = tuple(_spaced(p) for p in REFUSED_PHRASES)
_COMPACT = tuple(_compact(p) for p in REFUSED_PHRASES if " " not in p and p not in ("don't", "do not"))


def _instructions(text: str) -> bool:
    spaced = _spaced(text)
    compact = _compact(text)
    return any(p in spaced for p in _SPACED) or any(p in compact for p in _COMPACT)


def field_names(note: str) -> list[str]:
    """Plain field names from a note: split on commas, semicolons and " and "; each at most 60 characters, at most
    10. Raises ``ValueError`` (a message for the person) when the note is empty, too long, holds anything but plain
    letters, digits and light punctuation, or looks like instructions. Nothing is silently removed: what is
    checked is what comes out."""
    if not isinstance(note, str) or not note.strip() or len(note) > NOTE_MAX:
        raise ValueError(_MESSAGE)
    text = " ".join("".join(" " if ch.isspace() else ch
                            for ch in unicodedata.normalize("NFKC", note).translate(_QUOTES)).split())
    if not text or any(ch not in _ALLOWED for ch in text) or _instructions(text):
        raise ValueError(_MESSAGE)
    names = [n for n in (spec.clean_text(part, spec.MAX_LABEL) for part in _SPLIT.split(text)) if n]
    if not names or _instructions(" ".join(names)) or any(_instructions(n) for n in names):
        raise ValueError(_MESSAGE)
    return names[:ADDED_PER_DRAFT]
