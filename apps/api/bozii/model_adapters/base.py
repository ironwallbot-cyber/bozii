"""Model adapter contract shared by every inference provider."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ModelError(Exception):
    """Base class for adapter failures."""


class ModelUnavailableError(ModelError):
    """The provider could not be reached or the model is missing."""


class ModelProtocolError(ModelError):
    """The provider answered but with something we cannot interpret."""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]

    def as_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def as_ollama(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            data["name"] = self.name
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            data["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in self.tool_calls
            ]
        return data

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ChatMessage":
        calls = []
        for raw in data.get("tool_calls") or []:
            fn = raw.get("function", {}) if isinstance(raw, dict) else {}
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": args}
            calls.append(ToolCall(id=raw.get("id", ""), name=fn.get("name", ""), arguments=args or {}))
        return ChatMessage(
            role=data.get("role", "user"),
            content=data.get("content") or "",
            name=data.get("name"),
            tool_call_id=data.get("tool_call_id"),
            tool_calls=calls,
        )


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ChatResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatRequest:
    model: str
    messages: list[ChatMessage]
    tools: list[ToolSpec] = field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int | None = None
    tool_choice: str | None = None
    response_format: str | None = None  # "json" when the caller needs strict JSON


@dataclass
class ModelInfo:
    name: str
    display_name: str = ""
    context_window: int | None = None
    capabilities: list[str] = field(default_factory=list)


class ModelAdapter(ABC):
    """Common execution contract for every inference backend."""

    kind: str = "base"

    def __init__(self, base_url: str = "", api_key: str = "", config: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.config = config or {}

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def ping(self) -> tuple[bool, str]: ...


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """Normalise tool arguments that arrive as JSON strings."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": raw}


__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ModelAdapter",
    "ModelError",
    "ModelInfo",
    "ModelProtocolError",
    "ModelUnavailableError",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "parse_tool_arguments",
]
