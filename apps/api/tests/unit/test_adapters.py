"""Unit tests: model adapter HTTP contracts (Ollama and OpenAI-compatible)."""

from __future__ import annotations

import json

import httpx
import pytest

from bozii.model_adapters.base import (
    ChatMessage,
    ChatRequest,
    ToolSpec,
    parse_tool_arguments,
)
from bozii.model_adapters.mock import MockAdapter
from bozii.model_adapters.ollama import OllamaAdapter
from bozii.model_adapters.openai_compat import OpenAICompatAdapter, _join

TOOLS = [ToolSpec(name="write_file", description="write", parameters={"type": "object", "properties": {}})]


@pytest.fixture
def patch_client(monkeypatch):
    """Route every httpx.AsyncClient the adapters build through a test transport."""

    def factory(transport: httpx.BaseTransport):
        real_client = httpx.AsyncClient

        def make(*args, **kwargs):
            kwargs.pop("transport", None)
            kwargs.pop("timeout", None)
            return real_client(transport=transport, timeout=10.0)

        monkeypatch.setattr(httpx, "AsyncClient", make)

    return factory


async def test_openai_chat_parses_tool_calls(patch_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "write_file", "arguments": "{\"path\":\"a.txt\"}"},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        )

    patch_client(httpx.MockTransport(handler))
    adapter = OpenAICompatAdapter(base_url="https://api.example.com/v1", api_key="secret")
    response = await adapter.chat(
        ChatRequest(model="test-model", messages=[ChatMessage(role="user", content="hi")], tools=TOOLS)
    )
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["body"]["tools"][0]["function"]["name"] == "write_file"
    assert captured["headers"].get("authorization") == "Bearer secret"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "write_file"
    assert response.tool_calls[0].arguments == {"path": "a.txt"}
    assert response.usage.total_tokens == 17


async def test_openai_unreachable_reports_clear_error(patch_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    patch_client(httpx.MockTransport(handler))
    adapter = OpenAICompatAdapter(base_url="https://api.example.com/v1")
    with pytest.raises(Exception) as exc:
        await adapter.chat(ChatRequest(model="m", messages=[]))
    assert "unreachable" in str(exc.value).lower()


async def test_openai_missing_key_is_actionable(patch_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    patch_client(httpx.MockTransport(handler))
    adapter = OpenAICompatAdapter(base_url="https://api.example.com/v1", api_key="")
    with pytest.raises(Exception) as exc:
        await adapter.chat(ChatRequest(model="m", messages=[]))
    assert "credential" in str(exc.value).lower()


async def test_openai_model_list(patch_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "llama3.1:8b"}, {"id": "qwen2.5-vl"}]})

    patch_client(httpx.MockTransport(handler))
    adapter = OpenAICompatAdapter(base_url="http://localhost:11434/v1")
    models = await adapter.list_models()
    assert [m.name for m in models] == ["llama3.1:8b", "qwen2.5-vl"]
    assert "vision" in models[1].capabilities


async def test_ollama_chat_parses_tool_calls(patch_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "llama3.2",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "write_file", "arguments": {"path": "b.txt"}}}],
                },
                "done": True,
                "done_reason": "tool_calls",
                "prompt_eval_count": 30,
                "eval_count": 8,
            },
        )

    patch_client(httpx.MockTransport(handler))
    adapter = OllamaAdapter(base_url="http://localhost:11434")
    response = await adapter.chat(
        ChatRequest(model="llama3.2", messages=[ChatMessage(role="user", content="hi")], tools=TOOLS)
    )
    assert captured["path"] == "/api/chat"
    assert captured["body"]["stream"] is False
    assert response.tool_calls[0].name == "write_file"
    assert response.tool_calls[0].arguments == {"path": "b.txt"}
    assert response.usage.prompt_tokens == 30


async def test_ollama_missing_model_is_actionable(patch_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    patch_client(httpx.MockTransport(handler))
    adapter = OllamaAdapter()
    with pytest.raises(Exception) as exc:
        await adapter.chat(ChatRequest(model="nope", messages=[]))
    assert "ollama pull" in str(exc.value)


async def test_ollama_tags_and_ping(patch_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})

    patch_client(httpx.MockTransport(handler))
    adapter = OllamaAdapter()
    ok, message = await adapter.ping()
    assert ok, message
    models = await adapter.list_models()
    assert models[0].name == "llama3.2:latest"


def test_url_join_variants():
    assert _join("https://api.openai.com", "/chat/completions") == "https://api.openai.com/v1/chat/completions"
    assert _join("https://host/v1", "/chat/completions") == "https://host/v1/chat/completions"
    assert _join("https://host/v1/chat/completions", "/chat/completions") == "https://host/v1/chat/completions"
    with pytest.raises(Exception):
        _join("", "/chat/completions")


def test_parse_tool_arguments():
    assert parse_tool_arguments('{"a": 1}') == {"a": 1}
    assert parse_tool_arguments({"a": 1}) == {"a": 1}
    assert parse_tool_arguments("") == {}
    assert parse_tool_arguments("not json") == {"_raw": "not json"}


async def test_mock_adapter_is_scripted_and_deterministic():
    MockAdapter.reset_cursors()
    adapter = MockAdapter(config={"script": [
        {"type": "tool_call", "name": "list_files", "arguments": {"path": "."}},
        {"type": "message", "content": "done"},
    ]})
    first = await adapter.chat(ChatRequest(model="m", messages=[]))
    assert first.tool_calls[0].name == "list_files"
    second = await adapter.chat(ChatRequest(model="m", messages=[]))
    assert second.content == "done"
    third = await adapter.chat(ChatRequest(model="m", messages=[]))
    assert "script finished" in third.content
    ok, _ = await adapter.ping()
    assert ok
    MockAdapter.reset_cursors()
