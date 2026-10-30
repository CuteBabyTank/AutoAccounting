"""Native Ollama and hosted OpenAI-compatible Qwen; replies share one message format."""

import asyncio
import json
import logging
import math
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import uuid
from urllib.parse import urlsplit

import httpx

from app.config import settings

logger = logging.getLogger("assistant")

CONNECT_TIMEOUT_SECONDS = 5
RETRY_DELAY_SECONDS = 1.5


class RateLimited(Exception):
    """The provider cannot accept another request within this call's budget."""


class ContentRejected(Exception):
    """The provider declined the content; rephrasing needs a new turn."""


def retry_after(value: str | None, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            seconds = (when - (now or datetime.now(timezone.utc))).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, seconds) if math.isfinite(seconds) else None


def response_message(data: dict, provider: str) -> dict:
    if provider == "ollama":
        reply = normalize(data["message"])
        reply["usage"] = {"prompt": int(data.get("prompt_eval_count") or 0),
                          "completion": int(data.get("eval_count") or 0), "cached": 0}
        reply["truncated"] = data.get("done_reason") == "length"
    else:
        choice = data["choices"][0]
        reply = normalize(choice["message"])
        usage = data.get("usage") or {}
        reply["usage"] = {"prompt": int(usage.get("prompt_tokens") or 0),
                          "completion": int(usage.get("completion_tokens") or 0),
                          "cached": int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)}
        reply["truncated"] = choice.get("finish_reason") == "length"
    return reply


def strip_think(content: str) -> str:
    return re.sub(r"<think>.*?(?:</think>|$)", "", content, flags=re.DOTALL | re.IGNORECASE).strip()


def ollama_messages(messages: list[dict]) -> list[dict]:
    """Translate a fresh copy; never change the loop's OpenAI conversation."""
    names = {c["id"]: c["function"]["name"] for m in messages for c in m.get("tool_calls", [])}
    out = []
    for message in messages:
        m = {"role": message["role"], "content": message.get("content") or ""}
        if message.get("tool_calls"):
            m["tool_calls"] = []
            for call in message["tool_calls"]:
                function = call["function"]
                try:
                    args = json.loads(function["arguments"])
                    if not isinstance(args, dict):
                        args = {}
                except (ValueError, TypeError):
                    args = {}  # the following tool observation explains the malformed arguments
                m["tool_calls"].append({"function": {"name": function["name"], "arguments": args}})
        if message["role"] == "tool":
            m["tool_name"] = names.get(message["tool_call_id"], "")
        out.append(m)
    return out


def normalize(message: dict) -> dict:
    reply = {"role": "assistant", "content": strip_think(message.get("content") or "")}
    calls = []
    for call in message.get("tool_calls") or []:
        function = call["function"]
        args = function.get("arguments", {})
        calls.append({"id": call.get("id") or f"call_{uuid.uuid4().hex}", "type": "function",
                      "function": {"name": function.get("name", ""),
                                   "arguments": args if isinstance(args, str) else json.dumps(args)}})
    if calls:
        reply["tool_calls"] = calls
    return reply


async def _chat(messages: list[dict], tools: list[dict], tool_choice: str) -> dict:
    deadline = time.monotonic() + settings.assistant_llm_timeout_seconds
    base = settings.assistant_llm_base_url.rstrip("/")
    if settings.assistant_llm_provider == "ollama":
        url = f"{base}/api/chat"
        payload = {"model": settings.assistant_llm_model, "messages": ollama_messages(messages),
                   "stream": False, "think": settings.assistant_llm_think,
                   "keep_alive": settings.assistant_llm_keep_alive,
                   "options": {"num_ctx": settings.assistant_llm_num_ctx, "temperature": 0,
                               "num_predict": settings.assistant_llm_max_output_tokens}}
        if tool_choice != "none":
            payload["tools"] = tools
    else:
        url = f"{base}/chat/completions"
        payload = {"model": settings.assistant_llm_model, "messages": messages, "tools": tools,
                   "tool_choice": tool_choice, "temperature": 0,
                   "max_tokens": settings.assistant_llm_max_output_tokens}
        host = urlsplit(base).hostname or ""
        if not settings.assistant_llm_think and (host == "dashscope.aliyuncs.com" or
                host.startswith("dashscope-") and host.endswith(".aliyuncs.com")):
            # Raw HTTP: extra_body fields belong directly in the JSON body.
            payload["enable_thinking"] = False
    headers = {}
    if settings.assistant_llm_api_key:
        headers["Authorization"] = f"Bearer {settings.assistant_llm_api_key}"
    timeout = httpx.Timeout(settings.assistant_llm_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(3):
            delay = None
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response_message(response.json(), settings.assistant_llm_provider)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt == 2:
                    raise
                failure = None
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 400:
                    try:
                        body = exc.response.json()
                    except ValueError:
                        body = {}
                    if isinstance(body, dict) and (body.get("code") == "data_inspection_failed" or
                            isinstance(body.get("error"), dict) and
                            body["error"].get("code") == "data_inspection_failed"):
                        raise ContentRejected from exc
                if status != 429 and not 500 <= status < 600:
                    raise
                if attempt == 2:
                    if status == 429:
                        raise RateLimited from exc
                    raise
                failure = exc
                delay = retry_after(exc.response.headers.get("Retry-After"))
            if delay is None:
                delay = RETRY_DELAY_SECONDS * 2 ** attempt * random.uniform(.75, 1.25)
            if delay >= deadline - time.monotonic():
                if failure is not None and failure.response.status_code == 429:
                    raise RateLimited from failure
                raise TimeoutError("Provider retry exceeds the call budget")
            await asyncio.sleep(delay)
    raise RuntimeError("Chat completion failed")


async def chat(messages: list[dict], tools: list[dict], tool_choice: str) -> dict:
    started = time.monotonic()
    reply = {}
    try:
        # A wall-clock cap as well as HTTP inactivity timeouts, including retry delays.
        async with asyncio.timeout(settings.assistant_llm_timeout_seconds):
            reply = await _chat(messages, tools, tool_choice)
            return reply
    finally:
        usage = reply.get("usage", {})
        logger.info("assistant_llm_call provider=%s model=%s prompt=%d completion=%d cached=%d truncated=%s ms=%d",
                    settings.assistant_llm_provider, settings.assistant_llm_model, usage.get("prompt", 0),
                    usage.get("completion", 0), usage.get("cached", 0), reply.get("truncated", False),
                    int((time.monotonic() - started) * 1000))
