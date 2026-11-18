import httpx
import pytest

from app.config import settings
from app.services.accounting import gemini, qwen_reader


def payload(monkeypatch, base, **kw):
    monkeypatch.setattr(settings, "accounting_reader_base_url", base)
    return qwen_reader._payload([], "p", **kw)


def test_default_keeps_reasoning_off(monkeypatch):
    p = payload(monkeypatch, "https://openrouter.ai/api/v1")
    assert p["reasoning"] == {"enabled": False} and p["model"] == settings.accounting_reader_model
    assert p["provider"]["data_collection"] == "deny"
    d = payload(monkeypatch, "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    assert d["enable_thinking"] is False


def test_thinking_turns_reasoning_on(monkeypatch):
    p = payload(monkeypatch, "https://openrouter.ai/api/v1", thinking="high", model="x/y")
    assert p["reasoning"] == {"enabled": True, "effort": "high"} and p["model"] == "x/y"
    assert p["provider"]["data_collection"] == "deny"
    d = payload(monkeypatch, "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", thinking="high")
    assert d["enable_thinking"] is True


def test_unknown_thinking_value_means_high(monkeypatch):
    p = payload(monkeypatch, "https://openrouter.ai/api/v1", thinking="max")
    assert p["reasoning"] == {"enabled": True, "effort": "high"}
    p = payload(monkeypatch, "https://openrouter.ai/api/v1", thinking="low")
    assert p["reasoning"] == {"enabled": True, "effort": "low"}


async def test_network_errors_from_the_reader_become_reader_unavailable(monkeypatch):
    async def broken(*args, **kwargs):
        raise httpx.RemoteProtocolError("peer closed connection SECRET-DOC-TEXT")

    monkeypatch.setattr(settings, "accounting_reader", "qwen")
    monkeypatch.setattr(qwen_reader, "read", broken)
    with pytest.raises(gemini.ReaderUnavailable) as caught:
        await gemini.call_gemini_raw(b"%PDF", "application/pdf", "prompt", "u1")
    assert "SECRET" not in str(caught.value) and "RemoteProtocolError" in str(caught.value)
