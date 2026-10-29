"""Capability runtime: expose validated capabilities as sandboxed tools.

Generated code is NEVER imported into the Bozii process. Each call spawns the
sandbox runner in a separate process with resource limits and (when available)
no network, so a broken or malicious capability cannot damage the platform.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bozii.capability_engine.pipeline import BuildOutcome, build_capability
from bozii.capability_engine.runner import MARKER
from bozii.config import get_settings
from bozii.models import Capability, Employee, Task
from bozii.sandbox import run_sandboxed
from bozii.security.permissions import PathEscapeError, safe_path
from bozii.states import CAP_ACTIVE, TOOL_RISK_MUTATING
from bozii.tool_registry.base import Tool, ToolContext, ToolResult

logger = logging.getLogger("bozii.capabilities")

BUNDLE_FORMAT = "bozii-capability"
BUNDLE_VERSION = 1

PERMISSION_MAP: list[tuple[str, dict[str, Any]]] = [
    ("fs_read", {"fs": "workspace"}),
    ("fs_write", {"fs": "workspace"}),
    ("net_search", {"net": "search"}),
    ("net_fetch", {"net": "fetch"}),
    ("exec", {"exec": "sandbox"}),
    ("delegation", {"delegation": True}),
]
_RANK = {"none": 0, "search": 1, "fetch": 2, "workspace": 1, "sandbox": 1}


def requirements_for(permissions: list[str]) -> dict[str, Any]:
    """Translate a capability permission list into employee permission requirements."""
    required: dict[str, Any] = {}
    for perm in permissions:
        match = next((m for m in PERMISSION_MAP if m[0] == perm), None)
        if match is None:
            continue
        key, value = match[1]
        if isinstance(value, bool):
            required[key] = True
        elif key not in required or _RANK.get(str(value), 0) > _RANK.get(str(required[key]), 0):
            required[key] = value
    return required


def tool_name_for(capability: Capability, reserved: set[str]) -> str:
    base = capability.slug.replace("-", "_")
    if not base or base[0].isdigit():
        base = f"cap_{base}"
    if base in reserved:
        base = f"cap_{base}"
    return base


class CapabilityTool(Tool):
    """A validated capability, executed in the sandbox."""

    def __init__(self, capability: Capability, reserved: set[str]):
        self.capability = capability
        self.name = tool_name_for(capability, reserved)
        self.title = capability.name
        self.description = (
            f"{capability.description or capability.name} "
            f"[capability {capability.slug} v{capability.version}; permissions: "
            f"{', '.join(capability.permissions) or 'none'}]"
        )
        self.category = capability.category or "capabilities"
        self.risk = (
            TOOL_RISK_MUTATING
            if any(p in capability.permissions for p in ("fs_write", "exec"))
            else "safe"
        )
        self.required_permissions = requirements_for(capability.permissions)
        self.parameters = capability.input_schema or {"type": "object", "properties": {}, "required": []}
        self.version = f"v{capability.version}"

    def describe(self) -> dict[str, Any]:
        data = super().describe()
        data["kind"] = "capability"
        data["capability_id"] = self.capability.id
        data["slug"] = self.capability.slug
        return data

    def _capability_dir(self) -> Path:
        settings = get_settings()
        return settings.capability_dir / self.capability.slug / f"v{self.capability.version}"

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        settings = get_settings()
        cap_dir = self._capability_dir()
        if not (cap_dir / "tool.py").exists():
            return ToolResult(
                ok=False,
                error=(
                    f"Capability files for {self.capability.slug} v{self.capability.version} are "
                    "missing from disk; re-install or rebuild the capability."
                ),
            )
        try:
            workdir = safe_path(ctx.workspace, ".bozii")
        except PathEscapeError as exc:
            return ToolResult(ok=False, error=str(exc))
        workdir.mkdir(parents=True, exist_ok=True)
        if os.geteuid() == 0:
            try:
                os.chmod(workdir, 0o777)
            except OSError:
                pass
        input_path = workdir / f"input_{uuid.uuid4().hex}.json"
        input_path.write_text(json.dumps(args or {}, default=str), encoding="utf-8")

        allow_network = any(p in self.capability.permissions for p in ("net_fetch", "net_search"))
        env = {"PYTHONPATH": os.pathsep.join([_api_root(), str(cap_dir)])}
        result = await run_sandboxed(
            [
                sys.executable, "-m", "bozii.capability_engine.runner",
                "--dir", str(cap_dir),
                "--entry", "tool.py",
                "--input", str(input_path),
            ],
            cwd=ctx.workspace,
            timeout=settings.sandbox_timeout_seconds,
            network=allow_network,
            extra_env=env,
        )
        try:
            input_path.unlink(missing_ok=True)
        except OSError:
            pass

        stdout = result.stdout or ""
        if MARKER not in stdout:
            return ToolResult(
                ok=False,
                error=(
                    f"Capability '{self.name}' produced no result. "
                    f"exit={result.exit_code} timed_out={result.timed_out} stderr={result.stderr[:800]}"
                ),
            )
        payload_raw = stdout[stdout.rfind(MARKER) + len(MARKER) :].strip()
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            return ToolResult(ok=False, error=f"Capability '{self.name}' returned a malformed result.")
        if not payload.get("ok"):
            return ToolResult(
                ok=False,
                error=f"Capability '{self.name}' failed: {payload.get('error', 'unknown error')}",
            )
        output = payload.get("output")
        return ToolResult(
            ok=True,
            output=output if isinstance(output, (dict, list, str)) else {"result": output},
            metadata={"capability": self.capability.slug, "version": self.capability.version},
        )


def _api_root() -> str:
    import bozii

    return str(Path(bozii.__file__).resolve().parent.parent)


async def capability_tools_for_user(db: AsyncSession, user_id: str) -> list[CapabilityTool]:
    """Active capabilities this user may use (own + public)."""
    rows = await db.execute(
        select(Capability)
        .where(
            Capability.is_active.is_(True),
            Capability.status == CAP_ACTIVE,
            or_(Capability.created_by_user_id == user_id, Capability.visibility == "public"),
        )
        .order_by(Capability.slug.asc(), Capability.version.desc())
    )
    all_rows = list(rows.scalars())
    best: dict[str, Capability] = {}
    for cap in all_rows:  # keep the highest active version per slug
        if cap.slug not in best or cap.version > best[cap.slug].version:
            best[cap.slug] = cap
    reserved = set(_builtin_names())
    return [CapabilityTool(cap, reserved) for cap in best.values()]


def _builtin_names() -> set[str]:
    from bozii.tool_registry.builtins import builtin_tools

    return {t.name for t in builtin_tools()}


def export_bundle(capability: Capability) -> dict[str, Any]:
    return {
        "format": BUNDLE_FORMAT,
        "format_version": BUNDLE_VERSION,
        "manifest": {
            **(capability.manifest or {}),
            "name": capability.name,
            "slug": capability.slug,
            "kind": capability.kind,
            "version": capability.version,
            "description": capability.description,
            "category": capability.category,
            "tags": capability.tags,
            "permissions": capability.permissions,
            "dependencies": capability.dependencies,
            "input_schema": capability.input_schema,
        },
        "files": capability.files,
        "checksum": capability.checksum,
        "provenance": capability.provenance,
        "test_results": {
            "passed": bool((capability.test_results or {}).get("passed")),
            "summary": str((capability.test_results or {}).get("output", ""))[:500],
        },
    }


async def import_bundle(
    db: AsyncSession,
    user_id: str,
    bundle: dict[str, Any],
    *,
    activate: bool = True,
    employee: Employee | None = None,
    task: Task | None = None,
    emit: Callable[..., Awaitable[None]] | None = None,
) -> BuildOutcome:
    """Validate and register an exported capability bundle."""
    if bundle.get("format") != BUNDLE_FORMAT:
        return BuildOutcome(
            ok=False,
            slug="",
            errors=[f"Unsupported bundle format: {bundle.get('format')!r}. Expected '{BUNDLE_FORMAT}'."],
        )
    if int(bundle.get("format_version", 0)) > BUNDLE_VERSION:
        return BuildOutcome(
            ok=False,
            slug="",
            errors=[f"Bundle format version {bundle.get('format_version')} is newer than this Bozii supports."],
        )
    manifest = bundle.get("manifest") or {}
    files = bundle.get("files") or {}
    if not isinstance(files, dict) or not files:
        return BuildOutcome(ok=False, slug=str(manifest.get("slug", "")), errors=["Bundle contains no files."])
    return await build_capability(
        db,
        user_id=user_id,
        name=str(manifest.get("name") or "imported-capability"),
        kind=str(manifest.get("kind") or "tool"),
        description=str(manifest.get("description") or ""),
        category=str(manifest.get("category") or "general"),
        permissions=list(manifest.get("permissions") or []),
        tags=list(manifest.get("tags") or []),
        files={str(k): str(v) for k, v in files.items()},
        input_schema=manifest.get("input_schema") or None,
        employee=employee,
        task=task,
        activate=activate,
        visibility="private",
        emit=emit,
    )


async def make_capability_builder(
    db: AsyncSession,
    *,
    user_id: str,
    employee: Employee,
    task: Task | None,
    adapter=None,
    model_name: str = "",
    emit: Callable[..., Awaitable[None]] | None = None,
) -> Callable[..., Awaitable[Any]]:
    """Build the `capability_store` callable injected into ToolContext."""
    from bozii.capability_engine.codegen import generate_capability_files
    from bozii.tool_registry.base import ToolResult

    async def _store(
        *,
        name: str,
        kind: str,
        description: str,
        requirements: str,
        category: str,
        permissions: list[str],
        test_hint: str,
        activate: bool,
    ) -> Any:
        generate = None
        if kind == "tool":
            if adapter is None:
                return ToolResult(
                    ok=False,
                    error=(
                        "Code generation needs a model, and no usable model is configured. "
                        "Add a provider in Settings -> Models, then retry."
                    ),
                )

            async def generate() -> dict[str, str]:
                return await generate_capability_files(
                    adapter,
                    model_name,
                    name=name,
                    kind=kind,
                    description=description,
                    requirements=requirements,
                    permissions=permissions,
                    test_hint=test_hint,
                )

        outcome = await build_capability(
            db,
            user_id=user_id,
            name=name,
            kind=kind,
            description=description,
            requirements=requirements,
            category=category,
            permissions=permissions,
            files=None,
            generate=generate,
            employee=employee,
            task=task,
            activate=activate,
            emit=emit,
        )
        if not outcome.ok:
            return ToolResult(
                ok=False,
                error=(
                    f"Capability '{outcome.slug}' failed validation:\n- "
                    + "\n- ".join(outcome.errors[:8])
                ),
            )
        return {
            "slug": outcome.slug,
            "version": outcome.version,
            "capability_id": outcome.capability_id,
            "activated": bool(outcome.capability_id),
            "tests_passed": bool((outcome.test_results or {}).get("passed", True)),
            "scan_findings": len((outcome.scan_results or {}).get("findings", [])),
        }

    return _store


__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_VERSION",
    "CapabilityTool",
    "capability_tools_for_user",
    "export_bundle",
    "import_bundle",
    "make_capability_builder",
    "requirements_for",
    "tool_name_for",
]
