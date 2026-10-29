"""Utility tools: time operations and structured text transformations."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from bozii.tool_registry.base import Tool, ToolContext, ToolResult


class CurrentDatetimeTool(Tool):
    name = "current_datetime"
    title = "Current date and time"
    description = "Return the current UTC date and time, optionally converted to an IANA time zone."
    category = "utility"
    parameters = {
        "type": "object",
        "properties": {
            "timezone": {"type": "string", "description": "IANA time zone, e.g. 'Europe/Berlin' (default UTC)"},
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        tz_name = args.get("timezone")
        now = datetime.now(timezone.utc)
        offset_label = "UTC"
        if tz_name:
            name = str(tz_name)
            if name.upper() == "UTC":
                offset_label = "UTC"
            else:
                try:
                    from zoneinfo import ZoneInfo

                    now = now.astimezone(ZoneInfo(name))
                    offset_label = name
                except Exception as exc:
                    return ToolResult(
                        ok=False,
                        error=(
                            f"Time zone '{name}' could not be applied ({exc}). "
                            "The host may be missing the IANA time zone database (tzdata); "
                            "use UTC or an offset-aware zone that is installed."
                        ),
                    )
        return ToolResult(
            ok=True,
            output={
                "iso": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "weekday": now.strftime("%A"),
                "timezone": offset_label,
                "unix": int(now.timestamp()),
            },
        )


class TextTransformTool(Tool):
    name = "text_transform"
    title = "Transform text"
    description=(
        "Apply a sequence of deterministic text operations: upper, lower, title, trim, "
        "replace, regex_extract, count_lines, count_words, slugify, strip_markdown."
    )
    category = "utility"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Input text"},
            "operations": {
                "type": "array",
                "description": "Ordered list of operations to apply",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string"},
                        "pattern": {"type": "string"},
                        "replacement": {"type": "string"},
                    },
                    "required": ["op"],
                },
            },
        },
        "required": ["text", "operations"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        text = args["text"]
        applied: list[str] = []
        for step in args["operations"]:
            op = str(step.get("op", "")).lower()
            try:
                if op == "upper":
                    text = text.upper()
                elif op == "lower":
                    text = text.lower()
                elif op == "title":
                    text = text.title()
                elif op == "trim":
                    text = text.strip()
                elif op == "replace":
                    text = text.replace(str(step.get("pattern", "")), str(step.get("replacement", "")))
                elif op == "count_lines":
                    return ToolResult(ok=True, output={"count": len(text.splitlines()), "operation": "count_lines"})
                elif op == "count_words":
                    return ToolResult(ok=True, output={"count": len(text.split()), "operation": "count_words"})
                elif op == "slugify":
                    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
                elif op == "strip_markdown":
                    text = re.sub(r"[#*`_>\[\]()!]", "", text)
                elif op == "regex_extract":
                    found = re.findall(str(step.get("pattern", "")), text)
                    return ToolResult(ok=True, output={"matches": found, "count": len(found)})
                else:
                    return ToolResult(ok=False, error=f"Unknown operation '{op}'")
            except re.error as exc:
                return ToolResult(ok=False, error=f"Invalid regex in '{op}': {exc}")
            applied.append(op)
        return ToolResult(ok=True, output={"text": text, "applied": applied})


TOOLS: list[Tool] = [CurrentDatetimeTool(), TextTransformTool()]
