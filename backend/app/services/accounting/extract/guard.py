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
_SPLIT = re.compile(r"[,;\n]|\s+and\s+", re.IGNORECASE)


def _views(note: str) -> list[str]:
    """The note as typed, after NFKC (fullwidth forms), and with accents stripped (look-alike letters)."""
    nfkc = unicodedata.normalize("NFKC", note)
    bare = "".join(ch for ch in unicodedata.normalize("NFKD", nfkc) if not unicodedata.combining(ch))
    return [v.casefold() for v in (note, nfkc, bare)]


def field_names(note: str) -> list[str]:
    """Plain field names from a note: split on commas, semicolons, new lines and " and "; each at most 60
    characters, at most 10. Raises ``ValueError`` (a message for the person) when the note is empty, too long or
    looks like instructions."""
    if not isinstance(note, str) or not note.strip() or len(note) > NOTE_MAX:
        raise ValueError(_MESSAGE)
    if any(phrase in view for view in _views(note) for phrase in REFUSED_PHRASES):
        raise ValueError(_MESSAGE)
    names = [spec.clean_text(part, spec.MAX_LABEL) for part in _SPLIT.split(note)]
    names = [n for n in names if n]
    if not names:
        raise ValueError(_MESSAGE)
    return names[:ADDED_PER_DRAFT]
