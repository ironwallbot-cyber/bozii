"""Workspace file tools: list, read, search, write and move (confined)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bozii.security.permissions import PathEscapeError, safe_path
from bozii.states import TOOL_RISK_MUTATING
from bozii.tool_registry.base import Tool, ToolContext, ToolResult, ToolError

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next", ".pytest_cache", "dist"}
MAX_ENTRIES = 500
MAX_READ_BYTES = 400_000


def _resolve(ctx: ToolContext, path: str) -> Path:
    try:
        return safe_path(ctx.workspace, path or "")
    except PathEscapeError as exc:
        raise ToolError(str(exc)) from exc


def _rel(ctx: ToolContext, path: Path) -> str:
    try:
        return str(path.relative_to(ctx.workspace))
    except ValueError:
        return str(path)


class ListFilesTool(Tool):
    name = "list_files"
    title = "List files"
    description = (
        "List files and directories inside the assigned workspace. Returns paths relative "
        "to the workspace root, with sizes for files."
    )
    category = "files"
    required_permissions = {"fs": "workspace"}
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Sub-directory to list (defaults to workspace root)"},
            "depth": {"type": "integer", "description": "Maximum recursion depth, 1-5 (default 3)"},
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        root = _resolve(ctx, args.get("path", ""))
        if not root.exists():
            return ToolResult(ok=False, error=f"Path not found: {args.get('path')}")
        depth = int(args.get("depth") or 3)
        depth = max(1, min(depth, 5))
        entries: list[dict[str, Any]] = []

        def walk(current: Path, level: int) -> None:
            if level > depth or len(entries) >= MAX_ENTRIES:
                return
            try:
                children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except PermissionError:
                return
            for child in children:
                if len(entries) >= MAX_ENTRIES:
                    return
                if child.name in IGNORED_DIRS or child.name.startswith(".venv"):
                    continue
                rel = _rel(ctx, child)
                if child.is_dir():
                    entries.append({"path": rel + "/", "type": "dir"})
                    walk(child, level + 1)
                elif child.is_file():
                    entries.append({"path": rel, "type": "file", "size": child.stat().st_size})

        walk(root, 1)
        return ToolResult(ok=True, output={"root": _rel(ctx, root) or ".", "count": len(entries), "entries": entries})


class ReadFileTool(Tool):
    name = "read_file"
    title = "Read file"
    description = (
        "Read a text file from the workspace. Supports line offsets for large files. "
        "Returns the file content with line numbers."
    )
    category = "files"
    required_permissions = {"fs": "workspace"}
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace root"},
            "offset": {"type": "integer", "description": "1-based line to start from"},
            "limit": {"type": "integer", "description": "Maximum number of lines to return (default 400)"},
            "raw": {"type": "boolean", "description": "Return raw content without line numbers"},
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _resolve(ctx, args["path"])
        if not path.exists() or not path.is_file():
            return ToolResult(ok=False, error=f"File not found: {args['path']}")
        size = path.stat().st_size
        if size > MAX_READ_BYTES:
            return ToolResult(
                ok=False,
                error=f"File is {size} bytes (limit {MAX_READ_BYTES}). Use search_files or read a slice.",
            )
        data = path.read_bytes()
        if b"\x00" in data[:4096]:
            return ToolResult(ok=False, error=f"File appears to be binary: {args['path']}")
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        offset = max(1, int(args.get("offset") or 1))
        limit = int(args.get("limit") or 400)
        limit = max(1, min(limit, 2000))
        window = lines[offset - 1 : offset - 1 + limit]
        if args.get("raw"):
            content = "\n".join(window)
        else:
            content = "\n".join(f"{i:>5}| {line}" for i, line in enumerate(window, start=offset))
        truncated = (offset - 1 + limit) < len(lines)
        return ToolResult(
            ok=True,
            output={
                "path": args["path"],
                "total_lines": len(lines),
                "offset": offset,
                "returned_lines": len(window),
                "more": truncated,
                "content": content,
            },
        )


class SearchFilesTool(Tool):
    name = "search_files"
    title = "Search files"
    description = "Search text files in the workspace for a literal string or regular expression."
    category = "files"
    required_permissions = {"fs": "workspace"}
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text or regex to search for"},
            "path": {"type": "string", "description": "Sub-directory to search (default: whole workspace)"},
            "glob": {"type": "string", "description": "Filename filter, e.g. '*.py'"},
            "regex": {"type": "boolean", "description": "Treat the query as a regular expression"},
            "max_results": {"type": "integer", "description": "Maximum matches to return (default 50)"},
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        import re

        root = _resolve(ctx, args.get("path", ""))
        if not root.exists():
            return ToolResult(ok=False, error=f"Path not found: {args.get('path')}")
        query = args["query"]
        try:
            pattern = re.compile(query if args.get("regex") else re.escape(query), re.IGNORECASE)
        except re.error as exc:
            return ToolResult(ok=False, error=f"Invalid regular expression: {exc}")
        glob = args.get("glob") or "*"
        max_results = int(args.get("max_results") or 50)
        max_results = max(1, min(max_results, 200))
        matches: list[dict[str, Any]] = []
        scanned = 0
        for path in sorted(root.rglob(glob)):
            if len(matches) >= max_results:
                break
            if not path.is_file() or any(part in IGNORED_DIRS for part in path.parts):
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            for lineno, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    matches.append({"path": _rel(ctx, path), "line": lineno, "text": line.strip()[:400]})
                    if len(matches) >= max_results:
                        break
        return ToolResult(
            ok=True,
            output={"matches": matches, "count": len(matches), "files_scanned": scanned, "truncated": len(matches) >= max_results},
        )


class WriteFileTool(Tool):
    name = "write_file"
    title = "Create or edit file"
    description = (
        "Write text content to a file inside the workspace (creates parent directories). "
        "Use mode='append' to add to an existing file."
    )
    category = "files"
    risk = TOOL_RISK_MUTATING
    required_permissions = {"fs": "workspace"}
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace root"},
            "content": {"type": "string", "description": "Full text content to write"},
            "mode": {"type": "string", "enum": ["overwrite", "append"], "description": "Default overwrite"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _resolve(ctx, args["path"])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if args.get("mode") == "append" else "w"
            with path.open(mode, encoding="utf-8") as fh:
                fh.write(args["content"])
        except OSError as exc:
            return ToolResult(ok=False, error=f"Could not write {args['path']}: {exc}")
        size = path.stat().st_size
        return ToolResult(ok=True, output={"path": _rel(ctx, path), "bytes": size, "mode": args.get("mode", "overwrite")})


class MoveFileTool(Tool):
    name = "move_file"
    title = "Move or rename file"
    description = "Move or rename a file or directory within the workspace."
    category = "files"
    risk = TOOL_RISK_MUTATING
    required_permissions = {"fs": "workspace"}
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Existing path"},
            "destination": {"type": "string", "description": "New path"},
        },
        "required": ["source", "destination"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        src = _resolve(ctx, args["source"])
        dst = _resolve(ctx, args["destination"])
        if not src.exists():
            return ToolResult(ok=False, error=f"Not found: {args['source']}")
        if dst.exists():
            return ToolResult(ok=False, error=f"Destination already exists: {args['destination']}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return ToolResult(
            ok=True,
            output={"from": _rel(ctx, src), "to": _rel(ctx, dst), "type": "dir" if dst.is_dir() else "file"},
        )


TOOLS: list[Tool] = [
    ListFilesTool(),
    ReadFileTool(),
    SearchFilesTool(),
    WriteFileTool(),
    MoveFileTool(),
]
