"""Web tools: search the public web and retrieve public pages."""

from __future__ import annotations

from typing import Any

import httpx

from bozii.config import get_settings
from bozii.security.permissions import PermissionDenied, assert_public_url
from bozii.states import TOOL_RISK_MUTATING
from bozii.tool_registry.base import Tool, ToolContext, ToolResult
from bozii.tool_registry.providers.search import html_to_text, web_search


class WebSearchTool(Tool):
    name = "web_search"
    title = "Search the web"
    description = (
        "Search the public web through the configured search provider. Returns titles, URLs "
        "and snippets that must be cited by URL in the final report."
    )
    category = "web"
    required_permissions = {"net": "search"}
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Number of results (default 8, max 20)"},
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        limit = max(1, min(int(args.get("limit") or 8), 20))
        try:
            results, provider = await web_search(args["query"], limit)
        except PermissionDenied as exc:
            return ToolResult(ok=False, error=str(exc))
        except httpx.HTTPError as exc:
            return ToolResult(ok=False, error=f"Search request failed: {exc}")
        except RuntimeError as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(
            ok=True,
            output={
                "provider": provider,
                "query": args["query"],
                "results": [r.as_dict() for r in results],
                "count": len(results),
            },
        )


class WebFetchTool(Tool):
    name = "web_fetch"
    title = "Fetch a web page"
    description = (
        "Retrieve a public HTTP(S) page and return its readable text plus metadata. "
        "Private, loopback and cloud-metadata addresses are blocked."
    )
    category = "web"
    required_permissions = {"net": "fetch"}
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute http(s) URL"},
            "max_chars": {"type": "integer", "description": "Truncate output to this many characters (default 20000)"},
        },
        "required": ["url"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        settings = get_settings()
        url = str(args["url"]).strip()
        try:
            assert_public_url(url)
        except PermissionDenied as exc:
            return ToolResult(ok=False, error=str(exc))
        max_chars = max(1000, min(int(args.get("max_chars") or 20000), 200000))
        headers = {"User-Agent": "Bozii/0.1 (+https://github.com/bozii/bozii)"}
        try:
            async with httpx.AsyncClient(
                timeout=25.0, follow_redirects=True, headers=headers, max_redirects=5
            ) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code >= 400:
                        return ToolResult(ok=False, error=f"HTTP {resp.status_code} fetching {url}")
                    final_url = str(resp.url)
                    try:
                        assert_public_url(final_url)
                    except PermissionDenied as exc:
                        return ToolResult(ok=False, error=f"Redirect blocked: {exc}")
                    content_type = resp.headers.get("content-type", "")
                    raw = b""
                    truncated = False
                    async for chunk in resp.aiter_bytes():
                        raw += chunk
                        if len(raw) > settings.web_fetch_max_bytes:
                            truncated = True
                            break
        except httpx.HTTPError as exc:
            return ToolResult(ok=False, error=f"Request to {url} failed: {exc}")

        if len(raw) == 0:
            return ToolResult(ok=False, error=f"{url} returned an empty body")
        body = raw.decode("utf-8", errors="replace")
        if "html" in content_type or body.lstrip()[:1] == "<":
            text, links = html_to_text(body)
        else:
            text, links = body, []
        if not text.strip():
            return ToolResult(
                ok=False,
                error=f"{url} returned no readable text (content-type: {content_type or 'unknown'})",
            )
        return ToolResult(
            ok=True,
            output={
                "url": url,
                "final_url": final_url,
                "content_type": content_type,
                "title": (text.splitlines()[0][:200] if text else ""),
                "text": text[:max_chars],
                "chars": min(len(text), max_chars),
                "total_chars": len(text),
                "links": links[:20],
                "truncated": truncated or len(text) > max_chars,
            },
        )


TOOLS: list[Tool] = [WebSearchTool(), WebFetchTool()]
