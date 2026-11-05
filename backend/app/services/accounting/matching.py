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


MAX_OPTIONS = 4
_LEVEL_RANK = {"certain": 0, "likely": 1, "new": 2}


def _party_match(party: Party, companies: list[CompanyCandidate]) -> tuple[str | None, str]:
    """One party against the databank: exact TIN (certain), else a name match (likely), else a new company."""
    if party.tin:
        for c in companies:
            if c.tin and c.tin == party.tin:
                return c.id, "certain"
    if party.name:
        best, score = None, 0.0
        for c in companies:
            sc = max(name_similarity(party.name, n) for n in (c.registered_name, *c.aliases))
            if sc > score:
                best, score = c, sc
        if best is not None and score >= NAME_MATCH_THRESHOLD:
            return best.id, "likely"
    return None, "new"


def file_options(reads: list[tuple[int, Detection]], companies: list[CompanyCandidate],
                 suggested: str | None = None) -> list[dict]:
    """Every company a file could be for: both parties on every page read (1-based ``page``), deduplicated.

    An existing company is keyed by id, a new one by its TIN / name. ``suggested`` (a company id) goes first, then
    databank companies before new ones, then the parties seen on more pages.
    """
    found: dict[str, dict] = {}
    for page, d in reads:
        for side, party in (("seller", d.seller), ("buyer", d.buyer)):
            pk = _party_key(party)
            if not pk:
                continue
            cid, level = _party_match(party, companies)
            key = f"company:{cid}" if cid else f"new:{pk}"
            o = found.get(key)
            if o is None:
                found[key] = {"key": key, "company_id": cid, "name": party.name, "tin": party.tin,
                              "address": party.address, "side": side, "level": level, "pages": [page]}
            else:
                if page not in o["pages"]:
                    o["pages"].append(page)
                if _LEVEL_RANK[level] < _LEVEL_RANK[o["level"]]:
                    o["level"] = level
    # The suggestion first; then whoever is on the most pages read (the party a file's pages share is whose
    # books it is), databank companies before new ones on a tie.
    return sorted(found.values(), key=lambda o: (o["company_id"] != suggested or suggested is None,
                                                 -len(o["pages"]), o["company_id"] is None,
                                                 _LEVEL_RANK[o["level"]]))[:MAX_OPTIONS]


def is_ambiguous(matches: list[MatchResult], options: list[dict]) -> bool:
    """True when the pages read don't settle whose books the file belongs to.

    Both parties are clients in the databank; the sampled pages point at different clients; the suggested client
    isn't on every page read while another party is (a supplier's own sales invoices billed to several customers);
    or the only match is by name (no TIN), with another party also on the page."""
    if sum(1 for o in options if o["company_id"]) >= 2:
        return True
    if len({m.company_id for m in matches if m.company_id}) >= 2:
        return True
    primary = matches[0] if matches else None
    if primary and primary.company_id and len(matches) >= 2:
        pages = max((len(o["pages"]) for o in options), default=0)
        mine = next((len(o["pages"]) for o in options if o["company_id"] == primary.company_id), 0)
        if mine < pages:
            return True
    return bool(primary and primary.level == "likely" and len(options) >= 2)


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
    reader_down: bool = False  # it failed because the reading service was unavailable (quota, outage), not the file
    options: list[dict] = field(default_factory=list)  # every party read on the sampled pages (see file_options)
    ambiguous: bool = False  # the pages don't settle whose books this is: ask, suggest nothing


@dataclass
class UploadGroup:
    key: str
    company_id: str | None
    level: str
    detected: Party
    file_ids: list[str] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)  # merged across the group's files, most likely first


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
        if f.ambiguous and len(f.options) >= 2:  # several real possibilities: ask, suggest nothing
            key = "choose:" + "|".join(sorted(o["key"] for o in f.options))
            group = groups.setdefault(key, UploadGroup(key, None, "choose", Party()))
        elif f.match.company_id is not None:
            key = f"company:{f.match.company_id}"
            party = f.seller if f.match.side == "seller" else f.buyer
            group = groups.setdefault(key, UploadGroup(key, f.match.company_id, f.match.level, party))
            if f.match.level == "likely":
                group.level = "likely"
        elif f.reader_down:  # the reader never looked at it: say so, don't blame the file
            group = groups.setdefault("reader_down", UploadGroup("reader_down", None, "reader_down", Party()))
        elif f.failed or not (_party_key(f.seller) or _party_key(f.buyer)):  # nothing read: nobody to match
            group = groups.setdefault("unreadable", UploadGroup("unreadable", None, "unreadable", Party()))
        else:
            client = _client_party(f, freq)
            pk = _party_key(client)
            key = f"new:{pk}"
            group = groups.setdefault(key, UploadGroup(key, None, "unknown", client))
        group.file_ids.append(f.file_id)
        _merge_options(group, f.options)
    return sorted(groups.values(), key=lambda g: (g.company_id is None, g.level in ("unreadable", "reader_down"),
                                                  -len(g.file_ids)))


def _merge_options(group: UploadGroup, options: list[dict]) -> None:
    have = {o["key"]: o for o in group.options}
    for o in options:
        if o["key"] in have:
            have[o["key"]]["files"] += 1
            have[o["key"]]["weight"] += len(o.get("pages") or [1])
        else:
            merged = {k: v for k, v in o.items() if k != "pages"} | {"files": 1, "weight": len(o.get("pages") or [1])}
            group.options.append(merged)
            have[o["key"]] = merged
    # The group's own company first, then the parties on the most pages read, databank companies first on a tie.
    group.options.sort(key=lambda o: (o["company_id"] != group.company_id or group.company_id is None,
                                      -o["weight"], o["company_id"] is None))
    del group.options[MAX_OPTIONS:]


def detection_json(detection: Detection, match: MatchResult, options: list[dict] | None = None,
                   ambiguous: bool = False, pages: list[int] | None = None) -> dict:
    return {
        "options": options or [],
        "ambiguous": ambiguous,
        "pages_read": pages or [1],
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
                         failed="error" in data, reader_down=bool(data.get("reader_down")),
                         options=[o for o in data.get("options") or [] if isinstance(o, dict) and o.get("key")],
                         ambiguous=bool(data.get("ambiguous")))
