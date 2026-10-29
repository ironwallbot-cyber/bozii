"""Static security scanner for generated capability code.

Capabilities are untrusted code. Before anything is executed, every Python file
is parsed with :mod:`ast` and checked against policy rules. Findings are either
`block` (the capability is rejected) or `warn` (recorded and shown during
review). Declared permissions are checked against actual imports and calls, so
a capability cannot quietly gain network or process access.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from bozii.capability_engine.manifest import CapabilityManifest

BLOCK = "block"
WARN = "warn"

# Import name -> permission it implies
IMPORT_PERMISSIONS = {
    "socket": "net_fetch",
    "http": "net_fetch",
    "urllib": "net_fetch",
    "requests": "net_fetch",
    "httpx": "net_fetch",
    "aiohttp": "net_fetch",
    "ftplib": "net_fetch",
    "smtplib": "net_fetch",
    "telnetlib": "net_fetch",
    "subprocess": "exec",
    "multiprocessing": "exec",
    "shutil": "fs_write",
    "ctypes": "native",
    "pickle": "unsafe_deserialization",
    "marshal": "unsafe_deserialization",
    "sqlite3": "fs_write",
}

BLOCKED_MODULES = {"ctypes", "pickle", "marshal", "multiprocessing", "importlib"}
BLOCKED_CALLS = {"eval", "exec", "compile", "__import__", "input"}
ENV_ACCESS = {"environ", "getenv"}


@dataclass
class Finding:
    level: str
    rule: str
    detail: str
    file: str
    line: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "rule": self.rule, "detail": self.detail, "file": self.file, "line": self.line}


@dataclass
class ScanReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.level == BLOCK for f in self.findings)

    @property
    def passed(self) -> bool:
        return not self.blocked

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "findings": [f.as_dict() for f in self.findings],
            "scanned_files": sorted({f.file for f in self.findings}),
        }


def _perm_for(module_root: str) -> str | None:
    if module_root in IMPORT_PERMISSIONS:
        return IMPORT_PERMISSIONS[module_root]
    for key, perm in IMPORT_PERMISSIONS.items():
        if module_root.startswith(key + "."):
            return perm
    return None


class _Scanner(ast.NodeVisitor):
    def __init__(self, filename: str, declared: set[str], report: ScanReport) -> None:
        self.filename = filename
        self.declared = declared
        self.report = report
        self.imported: dict[str, str] = {}

    def _add(self, level: str, rule: str, detail: str, node: ast.AST) -> None:
        self.report.findings.append(
            Finding(level=level, rule=rule, detail=detail, file=self.filename, line=getattr(node, "lineno", 0))
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            self.imported[alias.name] = root
            if root in BLOCKED_MODULES:
                self._add(BLOCK, "blocked_import", f"Import of '{root}' is not permitted in capabilities", node)
                continue
            perm = _perm_for(root)
            if perm and perm not in self.declared:
                self._add(
                    BLOCK,
                    "undeclared_permission",
                    f"Import of '{root}' requires the '{perm}' permission, which is not declared",
                    node,
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".")[0]
        if root:
            self.imported[node.module or ""] = root
            if root in BLOCKED_MODULES:
                self._add(BLOCK, "blocked_import", f"Import from '{root}' is not permitted", node)
                return
            perm = _perm_for(root)
            if perm and perm not in self.declared:
                self._add(
                    BLOCK,
                    "undeclared_permission",
                    f"Import from '{root}' requires the '{perm}' permission, which is not declared",
                    node,
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = ""
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name in BLOCKED_CALLS:
            self._add(BLOCK, "dangerous_call", f"Call to '{name}' is not permitted", node)
        elif name == "system":
            self._add(BLOCK, "dangerous_call", "os.system() is not permitted; use a declared, sandboxed helper", node)
        elif name in {"Popen", "run", "call", "check_output", "check_call"}:
            if "subprocess" in self.imported.get("subprocess", "subprocess"):
                if "exec" not in self.declared:
                    self._add(BLOCK, "undeclared_permission", "subprocess usage requires the 'exec' permission", node)
        elif name in ENV_ACCESS:
            self._add(BLOCK, "secret_access", "Reading process environment variables is not permitted", node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in ENV_ACCESS:
            self._add(BLOCK, "secret_access", "Accessing process environment is not permitted", node)
        elif node.attr in {"system", "popen"}:
            self._add(BLOCK, "dangerous_call", f"os.{node.attr}() is not permitted", node)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and node.value.startswith(("/etc/", "/proc/", "/sys/", "/dev/")):
            self._add(WARN, "sensitive_path", f"Hard-coded system path: {node.value}", node)
        self.generic_visit(node)


def scan_capability(manifest: CapabilityManifest, files: dict[str, str]) -> ScanReport:
    report = ScanReport()
    declared = set(manifest.permissions or [])
    for path, content in sorted(files.items()):
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError as exc:
            report.findings.append(
                Finding(
                    level=BLOCK,
                    rule="syntax_error",
                    detail=f"{path} does not parse: {exc.msg} (line {exc.lineno})",
                    file=path,
                    line=exc.lineno or 0,
                )
            )
            continue
        scanner = _Scanner(path, declared, report)
        scanner.visit(tree)
    return report


def check_dependencies(manifest: CapabilityManifest, allowlist: list[str]) -> list[str]:
    """Return blocking errors for dependencies outside the configured allow-list."""
    errors: list[str] = []
    for dep in manifest.dependencies or []:
        if dep.lower() not in allowlist:
            errors.append(
                f"Dependency '{dep}' is not in the capability dependency allow-list. "
                "Bozii capabilities must use the Python standard library unless an operator "
                "explicitly allows additional packages (CAPABILITY_DEP_ALLOWLIST)."
            )
    return errors


__all__ = ["BLOCK", "BLOCKED_MODULES", "Finding", "ScanReport", "WARN", "check_dependencies", "scan_capability"]
