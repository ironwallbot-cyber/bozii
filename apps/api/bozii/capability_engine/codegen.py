"""LLM-backed code generation for new capabilities.

The model is asked for a strict JSON bundle of files. Parsing is defensive: a
model that wraps the JSON in prose or a fenced block still works, and a model
that returns nothing usable produces an honest error instead of a half-built
capability.
"""

from __future__ import annotations

import json
import logging
import re

from bozii.model_adapters.base import ChatMessage, ChatRequest, ChatResponse, ModelAdapter, ModelError

logger = logging.getLogger("bozii.capabilities")

MAX_FILE_BYTES = 120_000

SYSTEM_PROMPT = """You are the capability compiler inside Bozii, an AI workforce platform.
You write SMALL, CORRECT, TESTED Python modules that employees can reuse.

Rules:
- Respond with a single JSON object and nothing else. No prose, no markdown outside the JSON.
- Shape: {"files": {"<filename>": "<full file content>", ...}}
- Python 3.10, standard library ONLY (no pip dependencies).
- A tool module MUST define: def execute(args: dict) -> dict
  It must validate its own inputs and return {"...": ...} on success or raise ValueError with a clear message.
- Raise ValueError with a helpful message for invalid input or unsupported input; never fabricate data.
- If a declared permission is unavailable at runtime, fail with a clear message rather than pretending.
- Include a pytest test file named test_tool.py with at least 3 meaningful assertions, using only stdlib.
- Keep the implementation dependency-free, deterministic and under ~200 lines.
- Never read environment variables, never touch absolute paths outside the working directory,
  never use eval/exec/pickle/ctypes/subprocess unless the declared permission 'exec' requires it.
"""

USER_TEMPLATE = """Create the capability "{name}" ({kind}).

Description: {description}

Requirements:
{requirements}

Declared permissions: {permissions}
{test_hint}

Return the JSON object with the complete file contents (tool.py and test_tool.py).
"""


class CapabilityGenerationError(Exception):
    pass


def extract_json_bundle(text: str) -> dict:
    """Best-effort extraction of a JSON object from a model response."""
    if not text or not text.strip():
        raise CapabilityGenerationError("The model returned an empty response.")
    candidates: list[str] = []
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates.extend(fenced)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            return data
        if isinstance(data, dict) and all(isinstance(v, str) for v in data.values()):
            return {"files": data}
    raise CapabilityGenerationError(
        "The model did not return the required JSON file bundle, so no capability was created."
    )


def sanitise_files(files: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_path, content in files.items():
        path = str(raw_path).lstrip("/")
        if ".." in path.split("/"):
            raise CapabilityGenerationError(f"Generated an unsafe path: {raw_path}")
        if not isinstance(content, str):
            raise CapabilityGenerationError(f"File content for {raw_path} is not a string")
        if len(content.encode()) > MAX_FILE_BYTES:
            raise CapabilityGenerationError(f"Generated file {raw_path} exceeds {MAX_FILE_BYTES} bytes")
        if path in {"tool.py", "SKILL.md"} or path.endswith(".py") or path.endswith(".md"):
            out[path] = content
        else:
            raise CapabilityGenerationError(f"Unexpected generated file name: {path}")
    if not out:
        raise CapabilityGenerationError("The model produced no files")
    return out


async def generate_capability_files(
    adapter: ModelAdapter,
    model: str,
    *,
    name: str,
    kind: str,
    description: str,
    requirements: str,
    permissions: list[str],
    test_hint: str = "",
    temperature: float = 0.1,
) -> dict[str, str]:
    user_prompt = USER_TEMPLATE.format(
        name=name,
        kind=kind,
        description=description or "(none)",
        requirements=requirements or "(none)",
        permissions=", ".join(permissions) or "none",
        test_hint=f"Test guidance: {test_hint}" if test_hint else "",
    )
    request = ChatRequest(
        model=model,
        messages=[
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_prompt),
        ],
        temperature=temperature,
        response_format="json",
    )
    try:
        response: ChatResponse = await adapter.chat(request)
    except ModelError as exc:
        raise CapabilityGenerationError(
            f"Could not generate the capability because the model is unavailable: {exc}"
        ) from exc
    bundle = extract_json_bundle(response.content)
    return sanitise_files(bundle["files"])


__all__ = ["CapabilityGenerationError", "extract_json_bundle", "generate_capability_files", "sanitise_files"]
