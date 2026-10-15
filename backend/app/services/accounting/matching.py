"""Match a document's parties to the firm's company databank (pure)."""

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

from app.services.accounting.extraction import Detection, Party

NAME_MATCH_THRESHOLD = 0.85
_LEVELS = ("certain", "likely", "unknown")
_LEGAL_SUFFIXES = frozenset(
    {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "opc", "llc"}
)


def normalize_name(name: str) -> str:
    text = (name or "").lower().replace("&", " and ")
    text = re.sub(r"['’`.]", "", text)
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def name_similarity(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


@dataclass(frozen=True)
class CompanyCandidate:
    id: str
    registered_name: str
    tin: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchResult:
    company_id: str | None
    level: str          # certain | likely | unknown
    score: float
    side: str | None    # seller | buyer


def match_company(seller: Party, buyer: Party, companies: list[CompanyCandidate]) -> MatchResult:
    """Exact TIN on either side wins; otherwise the best fuzzy name match ≥ threshold."""
    sides = (("seller", seller), ("buyer", buyer))
    for side, party in sides:
        if party.tin:
            for c in companies:
                if c.tin and c.tin == party.tin:
                    return MatchResult(c.id, "certain", 1.0, side)
    best = MatchResult(None, "unknown", 0.0, None)
    for side, party in sides:
        if not party.name:
            continue
        for c in companies:
            score = max(name_similarity(party.name, n) for n in (c.registered_name, *c.aliases))
            if score > best.score:
                best = MatchResult(c.id, "likely", score, side)
    if best.score >= NAME_MATCH_THRESHOLD:
        return best
    return MatchResult(None, "unknown", best.score, None)


@dataclass(frozen=True)
class FileDetection:
    file_id: str
    seller: Party
    buyer: Party
    match: MatchResult
    failed: bool = False  # the detection call itself failed: nothing is known about the parties


@dataclass
class UploadGroup:
    key: str
    company_id: str | None
    level: str
    detected: Party
    file_ids: list[str] = field(default_factory=list)


def _party_key(p: Party) -> str:
    return p.tin or normalize_name(p.name)


def _client_party(f: FileDetection, freq: Counter) -> Party:
    """Guess which party of an unmatched file is the client.

    A party seen on ≥2 unmatched files in the drop is the client (a drop is
    usually one client's papers). Otherwise the buyer, since receipts outnumber
    issued invoices; a file with no buyer gives no guess.
    """
    candidates = [p for p in (f.buyer, f.seller) if _party_key(p)]
    if not candidates:
        return Party()
    best = max(candidates, key=lambda p: freq[_party_key(p)])
    if freq[_party_key(best)] >= 2:
        return best
    return f.buyer if _party_key(f.buyer) else Party()


def suggest_groups(files: list[FileDetection]) -> list[UploadGroup]:
    unmatched = [f for f in files if f.match.company_id is None]
    freq: Counter = Counter(
        k for f in unmatched for k in {_party_key(f.seller), _party_key(f.buyer)} if k
    )
    groups: dict[str, UploadGroup] = {}
    for f in files:
        if f.match.company_id is not None:
            key = f"company:{f.match.company_id}"
            party = f.seller if f.match.side == "seller" else f.buyer
            group = groups.setdefault(key, UploadGroup(key, f.match.company_id, f.match.level, party))
            if f.match.level == "likely":
                group.level = "likely"
        elif f.failed or not (_party_key(f.seller) or _party_key(f.buyer)):  # nothing read: nobody to match
            group = groups.setdefault("unreadable", UploadGroup("unreadable", None, "unreadable", Party()))
        else:
            client = _client_party(f, freq)
            pk = _party_key(client)
            key = f"new:{pk}"
            group = groups.setdefault(key, UploadGroup(key, None, "unknown", client))
        group.file_ids.append(f.file_id)
    return sorted(groups.values(), key=lambda g: (g.company_id is None, g.level == "unreadable", -len(g.file_ids)))


def detection_json(detection: Detection, match: MatchResult) -> dict:
    return {
        "document_title": detection.document_title,
        "kind": detection.kind,
        "seller": asdict(detection.seller),
        "buyer": asdict(detection.buyer),
        "date": detection.doc_date.isoformat() if detection.doc_date else None,
        "match": asdict(match),
    }


def _party_from_json(data) -> Party:
    d = data if isinstance(data, dict) else {}
    return Party(
        name=str(d.get("name") or ""),
        tin=str(d.get("tin") or ""),
        branch=str(d.get("branch") or "00000"),
        address=str(d.get("address") or ""),
    )


def file_detection_from_json(file_id: str, data: dict) -> FileDetection:
    data = data if isinstance(data, dict) else {}
    m = data.get("match") if isinstance(data.get("match"), dict) else {}
    level = m.get("level") if m.get("level") in _LEVELS else "unknown"
    company_id = m.get("company_id") if level != "unknown" else None
    try:
        score = float(m.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    match = MatchResult(company_id, level if company_id else "unknown", score, m.get("side"))
    return FileDetection(file_id, _party_from_json(data.get("seller")), _party_from_json(data.get("buyer")), match,
                         failed="error" in data)
