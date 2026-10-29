"""Deterministic mock adapter.

Used for automated tests and manual UI development only. It is NEVER selected
automatically: a provider row with `kind = "mock"` must be created explicitly
and is clearly labelled in the interface.
"""

from __future__ import annotations

import hashlib
import json

from bozii.model_adapters.base import (
    ChatRequest,
    ChatResponse,
    ModelAdapter,
    ModelInfo,
    ToolCall,
    Usage,
)


class MockAdapter(ModelAdapter):
    """Deterministic scripted adapter for tests.

    The script cursor is shared per unique config so a scripted conversation
    keeps advancing across engine steps (planning, tool calls, resumes) even
    though adapters are constructed lazily.
    """

    kind = "mock"
    _cursors: dict[str, int] = {}

    def __init__(self, base_url: str = "", api_key: str = "", config: dict | None = None):
        super().__init__(base_url, api_key, config)
        self.calls: list[ChatRequest] = []
        self._key = self._config_key(self.config)

    @staticmethod
    def _config_key(config: dict) -> str:
        try:
            raw = json.dumps(config, sort_keys=True, default=str)
        except (TypeError, ValueError):
            raw = str(config)
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def reset_cursors(cls) -> None:
        cls._cursors.clear()

    def _advance(self, step: dict) -> None:
        MockAdapter._cursors[self._key] = self._cursor + 1

    @property
    def _cursor(self) -> int:
        return MockAdapter._cursors.get(self._key, 0)

    @property
    def script(self) -> list[dict]:
        script = self.config.get("script")
        if isinstance(script, list) and script:
            return script
        return []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls.append(request)
        script = self.script
        index = self._cursor
        if index < len(script):
            step = script[index]
            self._advance(step)
        else:
            step = {"type": "message", "content": "Mock adapter: script finished."}

        kind = step.get("type", "message")
        if kind == "error":
            from bozii.model_adapters.base import ModelUnavailableError

            raise ModelUnavailableError(step.get("message", "Scripted mock failure"))
        if kind == "tool_call":
            call = ToolCall(
                id=f"call_{index}",
                name=step.get("name", ""),
                arguments=step.get("arguments") or {},
            )
            return ChatResponse(
                content=step.get("content", ""),
                tool_calls=[call],
                finish_reason="tool_calls",
                usage=Usage(prompt_tokens=10, completion_tokens=10),
                model=request.model,
            )
        if kind == "json":
            content = json.dumps(step.get("value", {}))
        else:
            content = str(step.get("content", ""))
        return ChatResponse(
            content=content,
            finish_reason="stop",
            usage=Usage(prompt_tokens=10, completion_tokens=10),
            model=request.model,
        )

    async def list_models(self) -> list[ModelInfo]:
        names = self.config.get("models") or ["mock-model"]
        return [
            ModelInfo(
                name=str(n),
                display_name=f"{n} (mock)",
                context_window=int(self.config.get("context_window") or 8192),
                capabilities=["completion", "tools", "json"],
            )
            for n in names
        ]

    async def ping(self) -> tuple[bool, str]:
        return True, "Mock adapter ready (testing only)"


__all__ = ["MockAdapter"]
