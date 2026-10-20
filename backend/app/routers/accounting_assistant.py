"""The firm assistant: one chat turn as a server-sent event stream (read-only; see services/accounting/assistant)."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.security import RateLimiter
from app.config import settings
from app.database import async_session
from app.dependencies import bind_session_user, get_current_user
from app.models.user import User
from app.routers.accounting_scope import scope_for
from app.services.accounting.assistant import loop, tools

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


@router.get("/assistant/info")
async def assistant_info(user: User = Depends(get_current_user)) -> dict:
    """What the chat shows in its composer: the model answering, and whether it runs on this server's machine."""
    scope_for(user)
    base = settings.assistant_llm_base_url.strip()
    return {"model": settings.assistant_llm_model, "provider": settings.assistant_llm_provider,
            "ready": bool(base), "local": any(h in base for h in ("localhost", "127.0.0.1", "host.docker.internal"))}


@router.post("/assistant/chat")
async def assistant_chat(body: ChatIn, user: User = Depends(get_current_user)):
    ent = scope_for(user)
    if not settings.assistant_llm_base_url.strip():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The assistant isn't set up on this server yet.")
    if assistant_limiter.is_rate_limited(str(user.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "That's a lot of questions at once. Try again in a "
                                                               "few minutes.", headers={"Retry-After": "60"})
    assistant_limiter.record(str(user.id))
    question = body.question.strip()
    history = [m.model_dump() for m in body.history]

    async def stream():
        # Its own session: the stream outlives the request's dependencies. RLS binds to the person, as everywhere.
        async with async_session() as db:
            await bind_session_user(db, str(user.id))
            ctx = tools.Ctx(db=db, user=user, ent=ent)
            async for event in loop.run(ctx, question, history):
                yield _sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
