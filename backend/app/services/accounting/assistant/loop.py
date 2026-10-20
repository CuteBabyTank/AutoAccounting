"""The assistant's agent loop: OpenAI-compatible function calling over ``tools.TOOLS``, yielding stream events.

Events (one JSON object each, sent as SSE by the router):
  {"type": "start"}
  {"type": "action", "tool", "args"}                       a tool is about to run
  {"type": "observation", "tool", "ok", "summary"}         it ran (summary is a short human line)
  {"type": "clarify", "question"}                         missing company or period
  {"type": "final", "answer", "sources", "tools_used", "grounded", "ungrounded_numbers"}
  {"type": "error", "message"}

At most ``MAX_STEPS`` model turns with tools; then one turn with tools off forces an answer. A repeated call (same
tool, same arguments) is answered from the first result instead of running again. Tool results are sanitized and
capped before the model reads them. The answer's figures are checked against the question, the conversation and the
tool results (``guard.ungrounded``); a peso figure with no tool behind it is replaced with a refusal.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from app.config import settings
from app.schemas.accounting import manila_today
from app.services.accounting.assistant import guard, llm, tools
from app.services.accounting.assistant.prompt import system_instruction

logger = logging.getLogger("assistant")

MAX_STEPS = settings.assistant_max_steps
MAX_CALLS_PER_STEP = settings.assistant_max_calls_per_step
OBSERVATION_CHARS = settings.assistant_observation_chars
MAX_SOURCES = 12
TIMEOUT_MESSAGE = "The assistant took too long; try a narrower question"
EARLY_STOP = "I stopped early to stay within the lookup limits."
STEP_LABELS = {
    "list_companies": "Looking up the firm's companies",
    "search": "Searching the firm's records", "get_document": "Reading the document",
    "report": "Checking the books", "aging": "Checking outstanding balances",
    "company_health": "Checking what needs attention", "filings": "Checking upcoming filings",
    "quarter_returns": "Checking the quarter's returns", "tax_reference": "Checking the BIR notes",
}
NO_FIGURE = ("I couldn't find that figure in the firm's books or documents, so I won't guess it. Tell me the company "
             "and period and I'll look it up.")

Generate = Callable[[list[dict], list[dict], str], Awaitable[dict]]


def _companies(data: object) -> dict[str, str]:
    """Company ids and labels in fact rows, including nested search / filing results."""
    found: dict[str, str] = {}
    if isinstance(data, dict):
        cid = data.get("company_id") or (data.get("id") if data.get("type") == "company" else None)
        if cid:
            name = data.get("company_name") or data.get("company") or data.get("name")
            found[str(cid)] = guard.sanitize(str(name or cid))
        for value in data.values():
            found.update(_companies(value))
    elif isinstance(data, list):
        for row in data:
            found.update(_companies(row))
    return found


@dataclass
class Coverage:
    checked: dict[str, str] = field(default_factory=dict)
    catalog: dict[str, str] | None = None
    firm_wide: bool = False

    def add(self, name: str, args: dict, result: tools.Result) -> None:
        if "error" in result.data:
            return
        if name == "list_companies":
            self.catalog = _companies(result.data)
            return
        if name not in {"company_health", "filings", "search", "report", "aging", "quarter_returns", "get_document"}:
            return
        for facts in (result.data, result.sources):
            for cid, label in _companies(facts).items():
                if label != cid or cid not in self.checked:
                    self.checked[cid] = label
        if ((name == "company_health" and (result.data.get("scope") == "firm"
                                          or (args.get("company") or "").strip().lower() in tools._ALL))
                or (name in {"filings", "search"} and not args.get("company"))):
            self.firm_wide = True

    def names(self) -> str:
        labels = [(self.catalog or {}).get(cid, label) if label == cid else label
                  for cid, label in self.checked.items()]
        return ", ".join(dict.fromkeys(labels)) or "no companies"


def clarify_event(question: str) -> dict:
    return {"type": "clarify", "question": question[:settings.assistant_history_chars]}


async def _needs_clarification(ctx: tools.Ctx, answer: str, used: list[str], coverage: Coverage) -> bool:
    if any(name != "list_companies" for name in used) or not guard.clarification(answer):
        return False
    if guard.company_only_clarification(answer):
        if coverage.catalog is not None:
            return len(coverage.catalog) != 1
        try:
            await tools.resolve_company(ctx, None)
        except tools.ToolError:
            return True
        return False
    return True


def declarations() -> list[dict]:
    return [{"type": "function", "function": {
        "name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools.TOOLS]


def observation(data: dict) -> str:
    text = guard.sanitize(json.dumps(data, ensure_ascii=False))
    if len(text) > OBSERVATION_CHARS:
        fragment = text[:OBSERVATION_CHARS - 100]
        capped = json.dumps({"truncated": True, "result": fragment}, ensure_ascii=False)
        while len(capped) > OBSERVATION_CHARS:
            fragment = fragment[:len(fragment) // 2]
            capped = json.dumps({"truncated": True, "result": fragment}, ensure_ascii=False)
        return capped
    return text


def summarize(name: str, data: dict) -> str:
    """One short line for the chat's step list."""
    if "error" in data:
        return str(data["error"])[:200]
    if name == "list_companies":
        return f"{len(data.get('companies', []))} companies"
    if name == "search":
        n = sum(len(g["items"]) for g in data.get("groups", []))
        return f"{n} match{'es' if n != 1 else ''}" if n else data.get("note", "No matches")
    if name == "get_document":
        return " · ".join(str(p) for p in (data.get("document_title") or data.get("doc_type"), data.get("doc_number"),
                                           data.get("company")) if p)
    if name == "report":
        return f"{data.get('report')} · {data.get('name')} · {data.get('period')}"
    if name == "aging":
        return f"{data.get('kind')} · {data.get('name')} · {data.get('contacts', 0)} contacts"
    if name == "company_health":
        if data.get("scope") == "firm":
            waiting = sum(1 for c in data.get("companies", []) if c.get("open_reviews"))
            return f"{waiting} of {len(data.get('companies', []))} companies have documents to review"
        return f"{data.get('company_name')} · {data.get('issues', 0)} issue(s)"
    if name == "filings":
        return f"{data.get('count', 0)} filing(s)"
    if name == "quarter_returns":
        return f"{data.get('name')} · {data.get('period')}"
    if name == "tax_reference":
        return f"{len(data.get('matches', []))} note(s)"
    return "done"


def history_contents(turns: list[guard.Turn]) -> list[dict]:
    return [{"role": t.role, "content": t.text} for t in turns]


async def _run(ctx: tools.Ctx, question: str, history: list[dict] | None, generate: Generate = llm.chat) -> AsyncIterator[dict]:
    started = time.monotonic()
    stopped_early = False
    turns = guard.trim_history(history)
    contents = [{"role": "system", "content": system_instruction(manila_today())}]
    contents += history_contents(turns) + [{"role": "user", "content": question}]
    observed: list[str] = []
    sources: list[dict] = []
    seen: dict[str, str] = {}
    used: list[str] = []
    coverage = Coverage()
    answer = ""
    try:
        for _step in range(MAX_STEPS):
            remaining = settings.assistant_turn_seconds - (time.monotonic() - started)
            if _step and remaining < 1.5 * settings.assistant_llm_timeout_seconds:
                stopped_early = True
                break
            resp = await generate(contents, declarations(), "auto")
            calls = resp.get("tool_calls") or []
            if not calls:
                answer = llm.strip_think(resp.get("content") or "").strip()
                if await _needs_clarification(ctx, answer, used, coverage):
                    yield clarify_event(answer)
                    return
                remaining = settings.assistant_turn_seconds - (time.monotonic() - started)
                if (guard.overreach(answer) and not coverage.firm_wide and _step + 1 < MAX_STEPS
                        and remaining >= 1.5 * settings.assistant_llm_timeout_seconds):
                    contents.append({"role": "assistant", "content": answer})
                    contents.append({"role": "user", "content": f"You only checked {coverage.names()}. "
                                     "Call company_health with no company (or filings without company) "
                                     "to cover every company, then answer."})
                    answer = ""
                    continue
                break
            # Keep every call paired with an observation, including those beyond the execution cap.
            contents.append({"role": "assistant", "content": llm.strip_think(resp.get("content") or ""),
                             "tool_calls": calls})
            for index, call in enumerate(calls):
                if time.monotonic() - started >= settings.assistant_turn_seconds:
                    raise TimeoutError
                name = call["function"].get("name", "")
                invalid = None
                try:
                    args = json.loads(call["function"].get("arguments", "{}"))
                    if not isinstance(args, dict):
                        raise ValueError("Arguments must be an object")
                except (ValueError, TypeError):
                    args = {}
                    invalid = "Invalid JSON arguments: send a JSON object."
                if index >= MAX_CALLS_PER_STEP:
                    invalid = "Too many calls in one round; use fewer tools."
                if name == "ask_clarification" and not invalid:
                    question_text = llm.strip_think(str(args.get("question") or "")).strip()
                    if question_text:
                        yield clarify_event(question_text)
                        return
                    invalid = "Ask one short clarification question."
                key = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
                yield {"type": "action", "tool": name, "args": args,
                       "label": STEP_LABELS.get(name, "Checking the records")}
                if invalid:
                    text = json.dumps({"error": invalid})
                    yield {"type": "observation", "tool": name, "ok": False, "summary": invalid}
                elif key in seen:
                    text = seen[key]
                    yield {"type": "observation", "tool": name, "ok": True, "summary": "Same as before"}
                else:
                    try:
                        result = await tools.call(ctx, name, args)
                    except Exception as exc:  # a bug or a DB error: keep the turn alive, the session usable
                        logger.exception("assistant_tool_failed tool=%s", name)
                        await ctx.db.rollback()
                        result = tools.Result({"error": f"That lookup failed ({type(exc).__name__}). Try another way "
                                                        "or tell the person it isn't available right now."})
                    data = tools.as_json(result.data)
                    coverage.add(name, args, result)
                    text = observation(data)
                    seen[key] = text
                    used.append(name)
                    for s in result.sources:
                        if len(sources) < MAX_SOURCES and all(s["id"] != x["id"] for x in sources):
                            sources.append(tools.as_json(s))
                    yield {"type": "observation", "tool": name, "ok": "error" not in data,
                           "summary": summarize(name, data)}
                observed.append(text)
                contents.append({"role": "tool", "tool_call_id": call["id"], "content": text})
        else:
            stopped_early = True
        if stopped_early:
            remaining = settings.assistant_turn_seconds - (time.monotonic() - started)
            if remaining < settings.assistant_llm_timeout_seconds:
                raise TimeoutError
            contents.append({"role": "user", "content": "Stop looking up data. Answer briefly from the results so far; "
                             "say that you stopped early."})
            resp = await generate(contents, declarations(), "none")
            if not resp.get("tool_calls"):
                answer = llm.strip_think(resp.get("content") or "")
            answer = f"{EARLY_STOP} {answer}".strip()
        if not answer:
            answer = "I couldn't put an answer together from what I found. Try asking more specifically."
        if stopped_early and await _needs_clarification(ctx, answer, used, coverage):
            yield clarify_event(answer)
            return
        caveat = (f"\n\nI only checked {coverage.names()}; other companies weren't checked."
                  if guard.overreach(answer) and not coverage.firm_wide else "")
        answer = cap_answer(answer)
        context = [question, *(t.text for t in turns), *observed]
        loose = guard.ungrounded(answer, context)
        if loose and guard.unsupported_money_claim(answer, len(used)):
            answer, loose = NO_FIGURE, []
        if caveat:
            answer = cap_answer(answer, max(1, settings.assistant_answer_chars - len(caveat))) + caveat
        answer = cap_answer(answer)
        logger.info("assistant_turn user=%s tools=%s steps=%d ungrounded=%d ms=%d", ctx.user.id, ",".join(used),
                    len(used), len(loose), int((time.monotonic() - started) * 1000))
        yield {"type": "final", "answer": answer, "sources": sources, "tools_used": used,
               "grounded": not loose, "ungrounded_numbers": loose}
    except (TimeoutError, httpx.TimeoutException, httpx.ConnectError):
        raise
    except Exception:
        logger.exception("assistant_failed user=%s", ctx.user.id)
        yield {"type": "error", "message": "The assistant couldn't answer just now. Please try again."}


def cap_answer(answer: str, limit: int | None = None) -> str:
    limit = settings.assistant_answer_chars if limit is None else limit
    return answer if len(answer) <= limit else answer[:limit - 1] + "…"


async def run(ctx: tools.Ctx, question: str, history: list[dict] | None,
              generate: Generate = llm.chat) -> AsyncIterator[dict]:
    yield {"type": "start"}
    decline = guard.precheck(question)
    if decline:
        yield {"type": "final", "answer": cap_answer(decline), "sources": [], "tools_used": [],
               "grounded": True, "ungrounded_numbers": []}
        return
    try:
        # Cancellation covers tools, model retries and waits, not just individual HTTP calls.
        async with asyncio.timeout(settings.assistant_turn_seconds):
            async for event in _run(ctx, question, history, generate):
                yield event
    except (httpx.ConnectError, httpx.ConnectTimeout):
        yield {"type": "error", "message": "The assistant's model isn't reachable"}
    except (TimeoutError, httpx.TimeoutException):
        yield {"type": "error", "message": TIMEOUT_MESSAGE}
