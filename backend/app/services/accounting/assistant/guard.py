"""Pure safety pieces of the assistant: observation sanitizing, numeric grounding, history trimming.

Grounding is numeric provenance, not claim checking: every figure in the answer must appear in the question, the
conversation or a tool result of this turn. Unsupported figures are reported with the answer (the UI flags them).
"""

import re
from dataclasses import dataclass

from app.config import settings

HISTORY_TURNS = settings.assistant_history_turns
HISTORY_CHARS = settings.assistant_history_chars
HISTORY_BUDGET_CHARS = settings.assistant_history_budget_chars
INSTRUCTION_DECLINE = "I can only help with this firm's records and BIR notes; I can't reveal or change my instructions."
_INJECTION = re.compile(
    r"\b(?:ignore|disregard|override|forget|bypass)\b.{0,60}\b(?:instructions?|rules?|prompts?|guardrails?)\b"
    r"|\b(?:show|reveal|print|repeat|expose|display|change|rewrite|give|tell)\b.{0,60}"
    r"\b(?:system|developer|hidden|internal)\s+(?:instructions?|prompts?)\b"
    r"|\b(?:show|reveal|print|repeat|change|rewrite)\s+(?:(?:me|us)\s+)?(?:your|the)\s+(?:instructions|prompt)\b"
    r"|(?:^|\n)\s*(?:system|developer)\s*:"
    r"|\b(?:you are now|new instructions\s*:|role[ -]?play|pretend (?:you are|to be))\b", re.I | re.S)


def precheck(question: str) -> str | None:
    """Cheap rejection of obvious instruction attacks, not a general scope classifier."""
    return INSTRUCTION_DECLINE if _INJECTION.search(question) else None


# Line-leading labels / phrases a document's text could use to pose as instructions.
_CONTROL = re.compile(
    r"(?im)^\s*(system|assistant|user|developer|tool|function)\s*:"
    r"|ignore (all )?(the )?(previous|prior|above) (instructions|prompts?)"
    r"|disregard (all )?(the )?(previous|prior|above)"
    r"|you are now\b|new instructions\s*:"
)


def sanitize(text: str) -> str:
    """Neutralize text read from documents / the books before the model sees it as a tool result."""
    return _CONTROL.sub("[removed]", text or "")


# A figure: 1,234.56 · 1234 · 12.5 (a leading ₱ / P / PHP is outside the match).
_NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])-?\d+(?:\.\d+)?")
_SMALL = 31  # counts / day numbers up to here are too common to police ("3 documents", "the 25th")
_YEAR = re.compile(r"(19|20)\d\d")  # a bare year ("Q3 2026"): the model knows today's date


def _norm(token: str) -> str | None:
    raw = token.replace(",", "").lstrip("-")
    try:
        value = float(raw)
    except ValueError:
        return None
    return f"{value:.2f}"


def numbers(text: str) -> set[str]:
    """Normalized figures in ``text`` (``1,234.5`` and ``1234.50`` are the same)."""
    out = set()
    for m in _NUMBER.finditer(text or ""):
        n = _norm(m.group())
        if n is not None:
            out.add(n)
    return out


def _derived(seen: set[str]) -> set[str]:
    """Figures that are plainly the seen ones restated: thousands shown in full, rounded to whole pesos."""
    out = set()
    for n in seen:
        v = float(n)
        out.add(f"{round(v):.2f}")
        out.add(f"{v * 1000:.2f}")
    return out


def ungrounded(answer: str, sources: list[str]) -> list[str]:
    """Figures in the answer that appear in none of the sources (question, history, tool results)."""
    seen: set[str] = set()
    for s in sources:
        seen |= numbers(s)
    seen |= _derived(seen)
    out = []
    for m in _NUMBER.finditer(answer or ""):
        n = _norm(m.group())
        if n is None or n in seen or float(n) <= _SMALL or _YEAR.fullmatch(m.group()):
            continue
        if m.group() not in out:
            out.append(m.group())
    return out


_MONEY_CLAIM = re.compile(r"(₱|\bPHP\b|\bpesos?\b)\s*-?\d|\d[\d,]*\.\d{2}\b", re.I)


def unsupported_money_claim(answer: str, tools_used: int) -> bool:
    """A peso figure stated without any tool having run this turn (and not taken from the conversation)."""
    return tools_used == 0 and bool(_MONEY_CLAIM.search(answer or ""))


_OVERREACH = re.compile(
    r"\bno other compan|\bnone of the (?:other )?compan|\ball (?:of )?(?:the )?compan"
    r"|\bevery compan|\bonly compan|\bno compan|\bthe rest of the compan"
    r"|\bother companies (?:have|don't|do not)", re.I)
_MISSING_INFO = re.compile(
    r"\bplease (?:specify|provide|tell me|clarify|confirm)|\bwhich (?:company|period|quarter|month|year|client)"
    r"|\bcould you (?:specify|tell|confirm)|\bdid you mean\b", re.I)
_REFUSAL = re.compile(r"\bcan'?t\b|\bcannot\b|\bunable\b|\boutside (?:the )?scope\b|\bonly help\b", re.I)
_COMPANY_INFO = re.compile(r"\b(?:company|client)\b", re.I)
_PERIOD_INFO = re.compile(r"\b(?:period|quarter|month|year|date|range|time)s?\b", re.I)


def overreach(answer: str) -> bool:
    """Whether a company claim requires firm-wide facts this turn."""
    return bool(_OVERREACH.search(answer or ""))


_TOOL_TALK = re.compile(
    r"\b(?:list_companies|get_document|company_health|quarter_returns|tax_reference|ask_clarification|"
    r"filings|search|report|aging) tool\b|\buse the \w+ tool\b|\b(?:list_companies|get_document|company_health|"
    r"quarter_returns|tax_reference|ask_clarification|overdue_only|within_days|past_days)\b", re.I)


def tool_talk(answer: str) -> str | None:
    """A tool or argument named in the answer (the model telling the person to do its job), else None."""
    m = _TOOL_TALK.search(answer or "")
    return m.group(0) if m else None


_TOOL_NAMES = ("list_companies", "get_document", "company_health", "quarter_returns", "tax_reference", "filings",
               "search", "report", "aging")
_ARG_TOOL = {"overdue_only": "filings", "within_days": "filings", "past_days": "filings"}


def tool_named(talk: str) -> str | None:
    """The tool a piece of tool talk refers to ("the filings tool" → filings), if any."""
    low = (talk or "").lower()
    return next((t for t in _TOOL_NAMES if t in low), None) or _ARG_TOOL.get(low)


# Parts of a question that only one tool can answer: (words in the question, the tool).
_NEEDS = (
    (re.compile(r"\b(?:overdue|late filings?|past due|due (?:soon|this|next|in)|deadlines?|what'?s due|filings?)\b", re.I),
     "filings"),
    (re.compile(r"\b(?:waiting for review|to review|review queue|needs? review|need attention)\b", re.I),
     "company_health"),
)


def missing_tools(question: str, used: list[str]) -> list[str]:
    """Tools a part of the question clearly needs that haven't run this turn (two-part questions often lose a part)."""
    return [tool for words, tool in _NEEDS if words.search(question or "") and tool not in used]


_OVERDUE = re.compile(r"\b(?:overdue|late|past due)\b", re.I)


def default_args(tool: str, question: str) -> dict:
    """Arguments for a lookup the server runs itself: firm-wide, overdue or the next 30 days."""
    if tool == "filings":
        return {"overdue_only": True} if _OVERDUE.search(question or "") else {"within_days": 30}
    return {}


_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")
_ISO_DATE = re.compile(r"\b(20\d\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b"
# A range: an en dash or an unspaced dash between numbers, or any dash before a month ("Jul 1 – Sep 30").
_RANGE_DASH = re.compile(rf"(\d)(?:\s*–\s*(?=\d|{_MONTH})|—(?=\d)|\s*(?:--|—)\s*(?={_MONTH}))")
_DASH = re.compile(r"\s*(?:--+|[–—])\s*|\s+-\s+")  # a spaced single hyphen is a dash too ("2026 - 71 days")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\uFE0F\u200D]+[ \t]?")


def humanize(text: str) -> str:
    """The answer in plain prose: ISO dates spelled out, dash ranges as "to", other dashes as commas.
    Single hyphens (0619-E, 1601-EQ, list bullets) are left alone."""
    out = _EMOJI.sub("", text or "")
    out = _ISO_DATE.sub(lambda m: f"{_MONTHS[int(m.group(2)) - 1]} {int(m.group(3))}, {m.group(1)}", out)
    out = _RANGE_DASH.sub(r"\1 to ", out)
    lines = []
    for line in out.split("\n"):
        bullet = re.match(r"^(\s*)(?:--|[–—])\s+", line)  # a dash used as a bullet marker
        if bullet:
            line = f"{bullet.group(1)}- {line[bullet.end():]}"
        head, body = re.match(r"^(\s*(?:[-*•]|\d+\.)?\s*)(.*)$", line).groups()
        body = _DASH.sub(", ", body)
        body = re.sub(r",\s*([,.;:!?])", r"\1", body).strip(" ,")
        lines.append(head + body if body else head.rstrip())
    return "\n".join(lines)


_SAID_PERIOD = (
    (re.compile(r"\b(?:last|previous|prior) quarter\b", re.I), "last_quarter"),
    (re.compile(r"\b(?:this|current) quarter\b", re.I), "this_quarter"),
    (re.compile(r"\b(?:last|previous|prior) month\b", re.I), "last_month"),
    (re.compile(r"\b(?:this|current) month\b", re.I), "this_month"),
    (re.compile(r"\b(?:last|previous|prior) (?:fiscal )?year\b", re.I), "last_year"),
    (re.compile(r"\b(?:this|current) (?:fiscal )?year\b|\bytd\b|\byear to date\b", re.I), "this_year"),
)


def period_from(question: str) -> str | None:
    """The relative report period the person named ("last quarter" → last_quarter), if any."""
    return next((p for words, p in _SAID_PERIOD if words.search(question or "")), None)


def drop_tool_talk(answer: str) -> str:
    """The answer without the sentences that name a tool or argument (kept whole when that would empty it)."""
    if not tool_talk(answer):
        return answer
    lines = []
    for line in (answer or "").split("\n"):
        parts = re.split(r"(?<=[.!?])\s+", line)
        kept = " ".join(p for p in parts if not tool_talk(p))
        if kept.strip() or not line.strip():
            lines.append(kept)
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out or answer


_FIRM_WORDS = re.compile(
    r"\b(?:compan(?:y|ies)|clients?|documents?|receipts?|invoices?|filings?|returns?|due|overdue|late|review|"
    r"vat|ewt|tax|income|revenue|expenses?|profit|loss|p&l|balance|cash|receivables?|payables?|a/r|a/p|aging|"
    r"supplier|customer|bank|books?|ledger|quarter|month)\b", re.I)


_ABOUT_CHAT = re.compile(r"\b(?:did i (?:say|tell|mention)|i (?:said|told|mentioned)|you (?:said|told|mentioned|just)|"
                         r"earlier|above|previous(?:ly)?|last (?:answer|message|reply))\b", re.I)


def firm_question(question: str) -> bool:
    """A question about the firm's records (needs a fresh lookup), not chit-chat or a question about the chat itself."""
    return bool(_FIRM_WORDS.search(question or "")) and not _ABOUT_CHAT.search(question or "")


def declines(answer: str) -> bool:
    """A refusal / out-of-scope decline (never pushed back to the tools)."""
    return bool(_REFUSAL.search(answer or ""))


_YES_NO = re.compile(
    r"\b(?:please confirm|can you confirm|could you confirm|confirm (?:if|whether|that)|did you mean|do you mean|"
    r"is that (?:right|correct)|should i|shall i|do you want|would you like|want me to)\b", re.I)
_YES_NO_START = re.compile(r"(?:^|[.!?]\s+)(?:do|did|is|are|should|shall|would|can|could|was|were)\b[^.!?]*\?\s*$", re.I)


def quick_replies(text: str) -> list[str]:
    """One-tap replies for a yes/no question at the end of an answer ("Yes"); the person can still type."""
    tail = (text or "").strip()[-400:]
    return ["Yes"] if _YES_NO.search(tail) or _YES_NO_START.search(tail) else []


def asks_person(text: str) -> bool:
    """Whether the text ends by asking the person something (a question mark, or "please confirm / which …")."""
    tail = (text or "").strip()[-300:]
    return tail.endswith("?") or bool(_YES_NO.search(tail) or _MISSING_INFO.search(tail))


_WHICH = re.compile(r"\bwhich (?:one|company|companies|client|clients)\b|\bwhat (?:company|client)\b", re.I)


def asks_which_company(text: str) -> bool:
    """A question asking the person to pick a company (not a yes/no)."""
    return bool(_WHICH.search((text or "").strip()[-300:]))


_PROMISE = re.compile(r"\b(?:let me (?:check|look|pull|get|retrieve|find)|i'?ll (?:check|look|pull|get|retrieve|find|now)|"
                      r"i will (?:check|look|pull|get|retrieve|find)|checking|looking up|pulling up)\b[^.!?]*[.!]?\s*$", re.I)


def promises_lookup(answer: str) -> bool:
    """An answer that ends by saying it will look something up, without having done so."""
    return bool(_PROMISE.search((answer or "").strip()[-250:]))


def named_options(text: str, names: list[str]) -> list[str]:
    """The firm's company names the text mentions, in the order it mentions them (the choices in "which one?")."""
    low = (text or "").lower()
    found = [(low.find(n.lower()), n) for n in names if n and n.lower() in low]
    return [n for _, n in sorted(found)]


_PLAN_LEAD = re.compile(r"^\s*(?:checking|looking up|let me (?:check|look)|i'?ll check)\b[^.!?\n]*[.!]\s+", re.I)


def drop_plan_lead(answer: str) -> str:
    """An answer that opens with the model's own "Checking …" plan line, minus that line (kept if it's all there is)."""
    out = _PLAN_LEAD.sub("", answer or "", count=1)
    return out if out.strip() else answer


def clarification(answer: str) -> bool:
    """A short missing-info request, excluding refusals."""
    text = answer.strip()
    return (bool(text) and len(text) < 300 and not _REFUSAL.search(text)
            and (text.endswith("?") or bool(_MISSING_INFO.search(text))))


def company_only_clarification(answer: str) -> bool:
    """A company request that does not also ask for a period."""
    return bool(_COMPANY_INFO.search(answer)) and not _PERIOD_INFO.search(answer)


@dataclass(frozen=True)
class Turn:
    role: str   # user | assistant
    text: str


def topic(question: str, turns: list[Turn]) -> str:
    """The question in context: a short reply to the assistant's own question ("Bayanihan Trading", "yes") is read
    together with the person's question before it, so period and lookup checks still see what was asked."""
    if len(question or "") > 80 or len(turns) < 2 or turns[-1].role != "assistant" \
            or not asks_person(turns[-1].text):
        return question
    earlier = next((t.text for t in reversed(turns[:-1]) if t.role == "user"), "")
    return f"{earlier}\n{question}" if earlier else question


def trim_history(history: list[dict] | None) -> list[Turn]:
    """The newest messages that fit the budget, oldest first; each cut to ``HISTORY_CHARS``."""
    turns: list[Turn] = []
    for m in ((history or [])[-HISTORY_TURNS:] if HISTORY_TURNS else []):
        if not isinstance(m, dict):
            continue
        role = "assistant" if m.get("role") == "assistant" else "user"
        text = str(m.get("text") or "").strip()[:HISTORY_CHARS]
        if text:
            turns.append(Turn(role, text))
    kept: list[Turn] = []
    used = 0
    for t in reversed(turns):
        if used + len(t.text) > HISTORY_BUDGET_CHARS:
            break
        kept.append(t)
        used += len(t.text)
    kept.reverse()
    while kept and kept[0].role == "assistant":  # start with the person's message
        kept.pop(0)
    return kept
