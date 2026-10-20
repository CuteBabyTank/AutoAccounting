"""Native Ollama and hosted OpenAI-compatible Qwen; replies share one message format."""

import asyncio
import json
import re
import uuid
from urllib.parse import urlsplit

import httpx

from app.config import settings

CONNECT_TIMEOUT_SECONDS = 5
RETRY_DELAY_SECONDS = 1.5


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
        for attempt in range(2):
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                return normalize(data["message"] if settings.assistant_llm_provider == "ollama"
                                 else data["choices"][0]["message"])
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt:
                    raise
            except httpx.HTTPStatusError as exc:
                if attempt or (exc.response.status_code != 429 and exc.response.status_code < 500):
                    raise
            await asyncio.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError("Chat completion failed")


async def chat(messages: list[dict], tools: list[dict], tool_choice: str) -> dict:
    # A wall-clock cap as well as HTTP inactivity timeouts, including retry delays.
    async with asyncio.timeout(settings.assistant_llm_timeout_seconds):
        return await _chat(messages, tools, tool_choice)
