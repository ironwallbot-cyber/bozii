"""Data tools: CSV profiling and table rendering (standard library only)."""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Any

from bozii.security.permissions import PathEscapeError, safe_path
from bozii.tool_registry.base import Tool, ToolContext, ToolResult, ToolError

MAX_ROWS = 50_000


def _resolve(ctx: ToolContext, path: str) -> Path:
    try:
        return safe_path(ctx.workspace, path)
    except PathEscapeError as exc:
        raise ToolError(str(exc)) from exc


def _read_rows(path: Path, delimiter: str | None = None, limit: int = MAX_ROWS) -> tuple[list[str], list[dict]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("rows") or data.get("data") or []
        if not isinstance(data, list) or not data:
            raise ValueError("JSON must be a non-empty array of objects")
        if not isinstance(data[0], dict):
            raise ValueError("JSON rows must be objects")
        headers = list(dict.fromkeys(k for row in data[:200] for k in row))
        rows = [{k: row.get(k, "") for k in headers} for row in data[:limit]]
        return headers, rows
    sample = text[:8192]
    delim = delimiter or (csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter if sample.strip() else ",")
    reader = csv.DictReader(text.splitlines(), delimiter=delim)
    headers = list(reader.fieldnames or [])
    rows = []
    for i, row in enumerate(reader):
        if i >= limit:
            break
        rows.append({k: (v if v is not None else "") for k, v in row.items()})
    return headers, rows


def _is_number(value: str) -> bool:
    if value is None or value == "":
        return False
    try:
        float(str(value).replace(",", "").replace("%", ""))
        return True
    except ValueError:
        return False


class CsvProfileTool(Tool):
    name = "csv_profile"
    title = "Profile a dataset"
    description = (
        "Profile a CSV, TSV or JSON dataset: columns, row count, missing values, and "
        "basic statistics (min/max/mean/median) for numeric columns."
    )
    category = "data"
    required_permissions = {"fs": "workspace"}
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to a .csv, .tsv or .json file"},
            "delimiter": {"type": "string", "description": "Override the field delimiter"},
            "max_rows": {"type": "integer", "description": "Rows to analyse (default 50000)"},
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _resolve(ctx, args["path"])
        if not path.exists():
            return ToolResult(ok=False, error=f"File not found: {args['path']}")
        try:
            headers, rows = _read_rows(path, args.get("delimiter"), int(args.get("max_rows") or MAX_ROWS))
        except (ValueError, json.JSONDecodeError) as exc:
            return ToolResult(ok=False, error=f"Could not parse {args['path']}: {exc}")
        if not rows:
            return ToolResult(ok=True, output={"columns": headers, "row_count": 0, "columns_detail": []})

        detail = []
        for col in headers:
            values = [row.get(col, "") for row in rows]
            missing = sum(1 for v in values if v in (None, ""))
            numeric = [float(str(v).replace(",", "").replace("%", "")) for v in values if _is_number(v)]
            entry: dict[str, Any] = {
                "name": col,
                "missing": missing,
                "missing_pct": round(100 * missing / len(values), 2),
                "unique": len({str(v) for v in values}),
                "numeric": len(numeric) == len(values) - missing and len(numeric) > 0,
            }
            if entry["numeric"] and numeric:
                entry["stats"] = {
                    "min": round(min(numeric), 4),
                    "max": round(max(numeric), 4),
                    "mean": round(statistics.fmean(numeric), 4),
                    "median": round(statistics.median(numeric), 4),
                    "stdev": round(statistics.pstdev(numeric), 4) if len(numeric) > 1 else 0,
                }
            else:
                entry["sample"] = [str(v) for v in values if v][:3]
            detail.append(entry)
        return ToolResult(
            ok=True,
            output={
                "path": args["path"],
                "row_count": len(rows),
                "column_count": len(headers),
                "columns": headers,
                "columns_detail": detail,
                "sample_rows": rows[:3],
            },
        )


class TableToMarkdownTool(Tool):
    name = "table_to_markdown"
    title = "Render table as Markdown"
    description = "Convert a CSV/TSV/JSON file into a Markdown table for use in a report."
    category = "data"
    required_permissions = {"fs": "workspace"}
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the data file"},
            "max_rows": {"type": "integer", "description": "Rows to render (default 100)"},
            "delimiter": {"type": "string", "description": "Override the field delimiter"},
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = _resolve(ctx, args["path"])
        if not path.exists():
            return ToolResult(ok=False, error=f"File not found: {args['path']}")
        max_rows = max(1, min(int(args.get("max_rows") or 100), 1000))
        try:
            headers, rows = _read_rows(path, args.get("delimiter"), max_rows)
        except (ValueError, json.JSONDecodeError) as exc:
            return ToolResult(ok=False, error=f"Could not parse {args['path']}: {exc}")

        def cell(value: Any) -> str:
            return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")[:200]

        lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
        for row in rows:
            lines.append("| " + " | ".join(cell(row.get(h, "")) for h in headers) + " |")
        return ToolResult(
            ok=True,
            output={"markdown": "\n".join(lines), "rows": len(rows), "columns": len(headers)},
        )


TOOLS: list[Tool] = [CsvProfileTool(), TableToMarkdownTool()]
