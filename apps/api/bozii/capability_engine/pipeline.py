"""Capability build pipeline: generate -> validate -> sandbox test -> register.

Every capability passes through the same stages regardless of where the code
came from (model generated, imported bundle, or written by a person through the
API). Failures are persisted so the user can inspect exactly what went wrong.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bozii.capability_engine.codegen import CapabilityGenerationError, generate_capability_files
from bozii.capability_engine.manifest import CapabilityManifest, slugify
from bozii.capability_engine.scanner import check_dependencies, scan_capability
from bozii.config import get_settings
from bozii.models import Capability, Employee, Task
from bozii.sandbox import run_sandboxed
from bozii.states import CAP_ACTIVE, CAP_DEPRECATED, CAP_FAILED, CAP_VALIDATING

logger = logging.getLogger("bozii.capabilities")

MAX_FILES = 20
MAX_TOTAL_BYTES = 400_000


@dataclass
class BuildOutcome:
    ok: bool
    slug: str
    version: int = 0
    capability_id: str | None = None
    errors: list[str] = field(default_factory=list)
    test_results: dict[str, Any] = field(default_factory=dict)
    scan_results: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "slug": self.slug,
            "version": self.version,
            "capability_id": self.capability_id,
            "errors": self.errors,
            "test_results": self.test_results,
            "scan_results": self.scan_results,
        }


def _api_root() -> str:
    import bozii

    return str(Path(bozii.__file__).resolve().parent.parent)


def checksum_files(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode())
        digest.update(files[path].encode())
    return digest.hexdigest()


def _validate_structure(kind: str, files: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if len(files) > MAX_FILES:
        errors.append(f"Too many files ({len(files)} > {MAX_FILES})")
    total = sum(len(v.encode()) for v in files.values())
    if total > MAX_TOTAL_BYTES:
        errors.append(f"Capability is too large ({total} bytes > {MAX_TOTAL_BYTES})")
    py_files = {p for p in files if p.endswith(".py")}
    if kind == "tool":
        if "tool.py" not in files:
            errors.append("A tool capability must include tool.py")
        if not any(p.startswith("test_") and p.endswith(".py") for p in py_files):
            errors.append("A tool capability must include a pytest test file (test_*.py)")
    if kind == "skill":
        if "SKILL.md" not in files:
            errors.append("A skill capability must include SKILL.md")
        elif not files["SKILL.md"].strip():
            errors.append("SKILL.md is empty")
        elif "#" not in files["SKILL.md"]:
            errors.append("SKILL.md must contain at least one Markdown heading")
    import ast

    for path in sorted(py_files):
        try:
            tree = ast.parse(files[path], filename=path)
        except SyntaxError as exc:
            errors.append(f"{path} does not compile: {exc.msg} (line {exc.lineno})")
            continue
        if path == "tool.py":
            has_execute = any(
                isinstance(node, ast.FunctionDef) and node.name == "execute" for node in tree.body
            )
            if not has_execute:
                errors.append("tool.py must define execute(args: dict) -> dict")
    return errors


async def run_capability_tests(files: dict[str, str], slug: str, version: int) -> dict[str, Any]:
    """Run the capability's tests inside the sandbox (never on the host)."""
    settings = get_settings()
    cap_dir = settings.capability_dir / slug / f"v{version}"
    test_file = next((p for p in files if p.startswith("test_") and p.endswith(".py")), None)
    if test_file is None:
        return {"ran": False, "passed": False, "reason": "no test file"}

    env = {"PYTHONPATH": os.pathsep.join([_api_root(), str(cap_dir)])}
    result = await run_sandboxed(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--no-header", "-x", test_file,
        ],
        cwd=cap_dir,
        timeout=settings.capability_test_timeout_seconds,
        network=False,
        extra_env=env,
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    passed_match = re.search(r"(\d+) passed", output)
    failed_match = re.search(r"(\d+) failed", output)
    error_match = re.search(r"(\d+) error", output)
    summary = {
        "ran": True,
        "passed": bool(result.ok),
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "passed_count": int(passed_match.group(1)) if passed_match else 0,
        "failed_count": int(failed_match.group(1)) if failed_match else 0,
        "error_count": int(error_match.group(1)) if error_match else 0,
        "output": output[-6000:],
        "duration_ms": result.duration_ms,
        "isolation": result.isolation,
        "command": " ".join(result.command),
    }
    return summary


async def build_capability(
    db: AsyncSession,
    *,
    user_id: str,
    name: str,
    kind: str = "tool",
    description: str = "",
    requirements: str = "",
    category: str = "general",
    permissions: list[str] | None = None,
    tags: list[str] | None = None,
    files: dict[str, str] | None = None,
    generate: Callable[[], Awaitable[dict[str, str]]] | None = None,
    employee: Employee | None = None,
    task: Task | None = None,
    activate: bool | None = None,
    input_schema: dict[str, Any] | None = None,
    visibility: str = "private",
    emit: Callable[..., Awaitable[None]] | None = None,
) -> BuildOutcome:
    settings = get_settings()
    slug = slugify(name)
    permissions = sorted(set(permissions or []))
    activate = settings.capability_auto_activate if activate is None else activate

    # Version assignment: the next version for this slug.
    current_max = (
        await db.execute(select(func.max(Capability.version)).where(Capability.slug == slug))
    ).scalar()
    version = int(current_max or 0) + 1

    errors: list[str] = []
    outcome = BuildOutcome(ok=False, slug=slug, version=version)

    # ---- 1. obtain implementation -------------------------------------
    if files is None:
        if kind == "skill" and not requirements:
            errors.append("A skill requires instructions (requirements) to build from")
        elif generate is not None:
            try:
                files = await generate()
            except CapabilityGenerationError as exc:
                errors.append(str(exc))
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Capability generation failed")
                errors.append(f"Code generation failed: {exc}")
        elif kind == "tool":
            errors.append("No implementation was provided for this tool capability")
        else:
            files = {
                "SKILL.md": f"# {name}\n\n{description}\n\n## Instructions\n\n{requirements}\n"
            }
    files = dict(files or {})

    # ---- 2. structural validation --------------------------------------
    if not errors:
        errors.extend(_validate_structure(kind, files))

    # ---- 3. manifest + security scan -----------------------------------
    manifest: CapabilityManifest | None = None
    scan_dict: dict[str, Any] = {}
    if not errors:
        try:
            manifest = CapabilityManifest(
                name=name,
                slug=slug,
                kind=kind,  # type: ignore[arg-type]
                version=version,
                description=description,
                category=category,
                tags=tags or [],
                permissions=permissions,
                input_schema=input_schema or {"type": "object", "properties": {}, "required": []},
                dependencies=[],
            )
        except Exception as exc:
            errors.append(f"Invalid manifest: {exc}")
    if manifest is not None:
        report = scan_capability(manifest, files)
        scan_dict = report.as_dict()
        if report.blocked:
            errors.extend(
                f"{f.file}:{f.line} [{f.rule}] {f.detail}" for f in report.findings if f.level == "block"
            )
        errors.extend(check_dependencies(manifest, settings.capability_dep_allowlist_list))

    # ---- 4. persist a validating row so failures are inspectable --------
    cap = Capability(
        slug=slug,
        name=name,
        kind=kind,
        version=version,
        status=CAP_VALIDATING,
        category=category,
        description=description,
        tags=tags or [],
        manifest=manifest.model_dump() if manifest else {},
        files=files,
        input_schema=(manifest.input_schema if manifest else {}),
        permissions=permissions,
        dependencies=(manifest.dependencies if manifest else []),
        scan_results=scan_dict,
        test_results={},
        provenance={
            "generated_by": "model" if files and generate is not None else "provided",
            "employee_id": employee.id if employee else None,
            "task_id": task.id if task else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        checksum=checksum_files(files),
        visibility=visibility,
        created_by_user_id=user_id,
        created_by_employee_id=employee.id if employee else None,
        source_task_id=task.id if task else None,
    )
    db.add(cap)
    await db.flush()

    # ---- 5. write files to disk -----------------------------------------
    settings.ensure_dirs()
    cap_dir = settings.capability_dir / slug / f"v{version}"
    if errors:
        cap.status = CAP_FAILED
        cap.test_results = {"ran": False, "passed": False, "reason": "validation failed"}
        await db.commit()
        outcome.errors = errors
        outcome.scan_results = scan_dict
        outcome.capability_id = cap.id
        return outcome

    for rel, content in files.items():
        target = cap_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if os.geteuid() == 0:
        try:
            os.chmod(cap_dir, 0o777)
            for item in cap_dir.rglob("*"):
                if item.is_dir():
                    os.chmod(item, 0o777)
        except OSError:
            pass

    # ---- 6. run tests in the sandbox ------------------------------------
    test_results: dict[str, Any] = {"ran": False, "passed": False}
    if kind == "tool":
        test_results = await run_capability_tests(files, slug, version)
    else:
        test_results = {"ran": False, "passed": True, "reason": "skills are validated structurally"}
    cap.test_results = test_results

    if kind == "tool" and not test_results.get("passed"):
        cap.status = CAP_FAILED
        await db.commit()
        outcome.errors = [
            "Automated tests did not pass in the sandbox; the capability was not activated.",
        ]
        if test_results.get("timed_out"):
            outcome.errors.append("The test run exceeded its timeout.")
        outcome.test_results = test_results
        outcome.scan_results = scan_dict
        outcome.capability_id = cap.id
        return outcome

    # ---- 7. activate -----------------------------------------------------
    if activate:
        previous = (
            await db.execute(
                select(Capability).where(
                    Capability.slug == slug, Capability.is_active.is_(True), Capability.id != cap.id
                )
            )
        ).scalars().all()
        for old in previous:
            old.is_active = False
            old.status = CAP_DEPRECATED
        cap.is_active = True
        cap.status = CAP_ACTIVE
        cap.activated_at = datetime.now(timezone.utc)
    else:
        cap.status = CAP_VALIDATING

    await db.commit()

    outcome.ok = True
    outcome.capability_id = cap.id
    outcome.test_results = test_results
    outcome.scan_results = scan_dict
    outcome.files = files

    if emit is not None:
        await emit(
            "capability",
            f"Capability '{slug}' v{version} validated and {'activated' if activate else 'saved'}",
            {"slug": slug, "version": version, "capability_id": cap.id},
        )
    return outcome


async def regenerate_with_feedback(
    adapter, model: str, previous_errors: list[str], **kwargs
) -> dict[str, str]:
    """Ask the model to fix a failed build (used by the retry path)."""
    kwargs = dict(kwargs)
    requirements = kwargs.get("requirements", "")
    kwargs["requirements"] = (
        f"{requirements}\n\nThe previous attempt failed validation with these errors:\n- "
        + "\n- ".join(previous_errors)
        + "\nFix them and return the complete corrected files."
    )
    return await generate_capability_files(adapter, model, **kwargs)


__all__ = [
    "BuildOutcome",
    "build_capability",
    "checksum_files",
    "regenerate_with_feedback",
    "run_capability_tests",
]
