"""OpenAI-compatible chat completions adapter.

Works with any endpoint that speaks the `/v1/chat/completions` dialect:
OpenAI, vLLM, llama.cpp server, LM Studio, LiteLLM, OpenRouter, Together,
Groq, and other self-hosted or remote open-weight hosts.
"""

from __future__ import annotations

import httpx

from bozii.model_adapters.base import (
    ChatRequest,
    ChatResponse,
    ModelAdapter,
    ModelError,
    ModelInfo,
    ModelProtocolError,
    ModelUnavailableError,
    ToolCall,
    Usage,
    parse_tool_arguments,
)

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def _join(base: str, path: str) -> str:
    base = (base or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}{path}"
    if not base:
        raise ModelUnavailableError("Provider base URL is empty")
    return f"{base}/v1{path}"


class OpenAICompatAdapter(ModelAdapter):
    kind = "openai_compat"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        extra = self.config.get("headers") or {}
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    def _model(self, request: ChatRequest) -> str:
        override = self.config.get("model_map", {}).get(request.model)
        return override or request.model

    async def chat(self, request: ChatRequest) -> ChatResponse:
        payload: dict = {
            "model": self._model(request),
            "messages": [m.as_dict() for m in request.messages],
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = [t.as_openai() for t in request.tools]
            payload["tool_choice"] = request.tool_choice or "auto"
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        url = _join(self.base_url, "/chat/completions")
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
            except httpx.HTTPError as exc:
                raise ModelUnavailableError(
                    f"Provider unreachable at {self.base_url}: {exc}"
                ) from exc
        if resp.status_code in (401, 403):
            raise ModelUnavailableError(
                f"Provider rejected the credentials (HTTP {resp.status_code}). "
                "Check the API key environment variable for this provider."
            )
        if resp.status_code == 404:
            raise ModelUnavailableError(f"Model '{request.model}' not found on provider (HTTP 404)")
        if resp.status_code >= 400:
            body = resp.text[:600]
            if "tools" in body.lower() and "not" in body.lower():
                raise ModelProtocolError(
                    f"This model does not support native tool calling (HTTP {resp.status_code}): {body}"
                )
            raise ModelProtocolError(f"Provider returned HTTP {resp.status_code}: {body}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelProtocolError("Provider returned a non-JSON body") from exc

        try:
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
        except (IndexError, AttributeError) as exc:
            raise ModelProtocolError("Provider response has no choices") from exc

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
        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
        )
        return ChatResponse(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            finish_reason=str(choice.get("finish_reason") or ("tool_calls" if tool_calls else "stop")),
            usage=usage,
            model=str(data.get("model") or request.model),
            raw={},
        )

    async def list_models(self) -> list[ModelInfo]:
        url = _join(self.base_url, "/models")
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.get(url, headers=self._headers())
            except httpx.HTTPError as exc:
                raise ModelUnavailableError(f"Provider unreachable at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise ModelProtocolError(f"GET /models returned HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelProtocolError("Provider returned a non-JSON model list") from exc
        entries = data.get("data") or data.get("models") or []
        out: list[ModelInfo] = []
        for entry in entries[:50]:
            name = entry.get("id") or entry.get("name") or ""
            if not name:
                continue
            caps = ["completion", "tools"]
            lname = name.lower()
            if any(tag in lname for tag in ("vision", "-vl", "llava", "multimodal")):
                caps.append("vision")
            ctx = entry.get("context_length") or entry.get("context_window")
            out.append(
                ModelInfo(
                    name=name,
                    display_name=str(entry.get("display_name") or name),
                    context_window=int(ctx) if ctx else None,
                    capabilities=caps,
                )
            )
        return out

    async def ping(self) -> tuple[bool, str]:
        try:
            models = await self.list_models()
        except ModelError as exc:
            return False, str(exc)
        return True, f"Provider reachable ({len(models)} model(s))"


__all__ = ["OpenAICompatAdapter", "_join"]
