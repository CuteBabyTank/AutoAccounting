"""The firm assistant: one chat turn as a server-sent event stream (read-only; see services/accounting/assistant)."""

import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import RateLimiter
from app.config import settings
from app.database import async_session
from app.dependencies import bind_session_user, get_current_user, get_db
from app.models.user import User
from app.routers.accounting_scope import MANAGER_ROLES, scope_for
from app.services.accounting.assistant import loop, tools, usage

logger = logging.getLogger("assistant")
router = APIRouter()

RATE_LIMIT_TURNS = 40
RATE_LIMIT_WINDOW_SECONDS = 600
assistant_limiter = RateLimiter(max_attempts=RATE_LIMIT_TURNS, window_seconds=RATE_LIMIT_WINDOW_SECONDS)  # turns per person per 10 minutes


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(default="", max_length=4000)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=60)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


_pending_writes: set[asyncio.Task] = set()  # strong references until each shielded write finishes


async def _save_usage(ent, user: User, totals: dict) -> None:
    """Add one turn to today's counters; a failed write logs and never breaks the reply."""
    day = usage.today()  # A turn spanning midnight belongs to the day it finishes.
    usage.platform.add(totals, day)
    async with async_session() as db:
        try:
            await bind_session_user(db, str(user.id))
            await usage.record(db, ent, user.id, day, totals)
            await db.commit()
        except Exception:
            logger.exception("assistant_usage_write_failed user=%s firm=%s", user.id, ent)
            try:
                await db.rollback()
            except Exception:
                logger.exception("assistant_usage_rollback_failed user=%s", user.id)


@router.get("/assistant/info")
async def assistant_info(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """What the chat shows in its composer: the model answering, and whether it runs on this server's machine."""
    ent = scope_for(user)
    day = usage.today()
    totals = await usage.daily(db, ent, user.id, day)
    if user.role not in MANAGER_ROLES:
        totals.pop("firm")
    base = settings.assistant_llm_base_url.strip()
    return {"day": day, "usage": totals,
            "caps": {"firm": settings.assistant_firm_daily_tokens, "user": settings.assistant_user_daily_tokens},
            "model": settings.assistant_llm_model, "provider": settings.assistant_llm_provider,
            "ready": bool(base), "local": any(h in base for h in ("localhost", "127.0.0.1", "host.docker.internal"))}


@router.post("/assistant/chat")
async def assistant_chat(body: ChatIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    if not settings.assistant_llm_base_url.strip():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The assistant isn't set up on this server yet.")
    day = usage.today()
    if usage.platform.limited(day):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The assistant is resting for today.",
                            headers={"Retry-After": str(usage.seconds_to_midnight())})
    totals = await usage.daily(db, ent, user.id, day)
    reason = usage.cap_reason(usage.token_total(totals["firm"]), usage.token_total(totals["user"]),
                              settings.assistant_firm_daily_tokens, settings.assistant_user_daily_tokens)
    if reason:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, usage.CAP_MESSAGES[reason],
                            headers={"Retry-After": str(usage.seconds_to_midnight())})
    if assistant_limiter.is_rate_limited(str(user.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "That's a lot of questions at once. Try again in a "
                                                               "few minutes.", headers={"Retry-After": "60"})
    assistant_limiter.record(str(user.id))
    question = body.question.strip()
    history = [m.model_dump() for m in body.history]

    meter = {"prompt": 0, "completion": 0, "cached": 0, "calls": 0}  # loop.run adds every model call as it happens

    async def stream():
        saved = False
        try:
            # Its own session: the stream outlives the request's dependencies. RLS binds to the person, as everywhere.
            async with async_session() as db:
                await bind_session_user(db, str(user.id))
                ctx = tools.Ctx(db=db, user=user, ent=ent)
                async for event in loop.run(ctx, question, history, meter=meter):
                    if event["type"] in {"final", "clarify", "error"}:
                        meter.update(event.get("usage") or {})
                        if event["type"] != "error" or meter["calls"]:
                            await _save_usage(ent, user, dict(meter))
                        saved = True
                    yield _sse(event)
        finally:
            if not saved and meter["calls"]:
                # The person left mid-turn: the calls already made still count. Shielded so the write
                # finishes even though this stream is being cancelled.
                task = asyncio.create_task(_save_usage(ent, user, dict(meter)))
                _pending_writes.add(task)
                task.add_done_callback(_pending_writes.discard)
                await asyncio.shield(task)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
