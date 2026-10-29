"""Ollama adapter - local, free, open-weight model inference."""

from __future__ import annotations

import logging

import httpx

from bozii.model_adapters.base import (
    ChatRequest,
    ChatResponse,
    ModelAdapter,
    ModelInfo,
    ModelProtocolError,
    ModelUnavailableError,
    ToolCall,
    Usage,
    parse_tool_arguments,
)

logger = logging.getLogger("bozii.models.ollama")

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class OllamaAdapter(ModelAdapter):
    kind = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434", api_key: str = "", config: dict | None = None):
        super().__init__(base_url or "http://127.0.0.1:11434", api_key, config)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        payload: dict = {
            "model": request.model,
            "messages": [m.as_dict() for m in request.messages],
            "stream": False,
            "options": {"temperature": request.temperature},
        }
        if request.max_tokens:
            payload["options"]["num_predict"] = request.max_tokens
        if request.tools:
            payload["tools"] = [t.as_ollama() for t in request.tools]
        if request.response_format == "json":
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            except httpx.HTTPError as exc:
                raise ModelUnavailableError(
                    f"Ollama is unreachable at {self.base_url}: {exc}. Start it with `ollama serve`."
                ) from exc
        if resp.status_code == 404:
            raise ModelUnavailableError(
                f"Model '{request.model}' is not present in Ollama. Pull it with `ollama pull {request.model}`."
            )
        if resp.status_code >= 400:
            raise ModelProtocolError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:400]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelProtocolError("Ollama returned a non-JSON body") from exc

        message = data.get("message") or {}
        content = message.get("content") or ""
        tool_calls: list[ToolCall] = []
        for i, raw in enumerate(message.get("tool_calls") or []):
            fn = raw.get("function") or {}
            tool_calls.append(
                ToolCall(
                    id=raw.get("id") or f"call_{i}",
                    name=fn.get("name") or "",
                    arguments=parse_tool_arguments(fn.get("arguments")),
                )
            )
        usage = Usage(
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or 0),
        )
        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=str(data.get("done_reason") or ("tool_calls" if tool_calls else "stop")),
            usage=usage,
            model=str(data.get("model") or request.model),
            raw={"done": data.get("done")},
        )

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(f"{self.base_url}/api/tags")
            except httpx.HTTPError as exc:
                raise ModelUnavailableError(f"Ollama is unreachable at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise ModelProtocolError(f"Ollama /api/tags returned HTTP {resp.status_code}")
        data = resp.json()
        models: list[ModelInfo] = []
        for entry in (data.get("models") or [])[:30]:
            name = entry.get("name") or entry.get("model") or ""
            if not name:
                continue
            info = ModelInfo(name=name, display_name=name)
            details = entry.get("details") or {}
            info.context_window = None
            info.capabilities = ["completion"]
            models.append(info)
        return models

    async def model_capabilities(self, model: str) -> list[str]:
        """Ask Ollama what a model supports (tools/vision) via /api/show."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.post(f"{self.base_url}/api/show", json={"model": model})
            except httpx.HTTPError:
                return ["completion"]
        if resp.status_code >= 400:
            return ["completion"]
        try:
            data = resp.json()
        except ValueError:
            return ["completion"]
        caps = [str(c).lower() for c in (data.get("capabilities") or [])]
        mapped = ["completion"]
        if "tools" in caps:
            mapped.append("tools")
        if "vision" in caps:
            mapped.append("vision")
        if "thinking" in caps:
            mapped.append("thinking")
        ctx = (data.get("model_info") or {}).get("context_length")
        if ctx:
            self.config.setdefault("_ctx", {})[model] = int(ctx)
        return mapped

    async def context_window(self, model: str) -> int | None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.post(f"{self.base_url}/api/show", json={"model": model})
                if resp.status_code >= 400:
                    return None
                data = resp.json()
            except (httpx.HTTPError, ValueError):
                return None
        ctx = (data.get("model_info") or {}).get("context_length")
        return int(ctx) if ctx else None

    async def ping(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
            if resp.status_code >= 400:
                return False, f"Ollama answered HTTP {resp.status_code}"
            count = len(resp.json().get("models") or [])
            return True, f"Ollama reachable ({count} model(s))"
        except httpx.HTTPError as exc:
            return False, f"Ollama unreachable at {self.base_url}: {exc}"


__all__ = ["OllamaAdapter"]
