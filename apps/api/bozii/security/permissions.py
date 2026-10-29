"""Permission checks and path confinement.

Every tool execution is checked against the *effective* permission set of the
task: the intersection of the acting employee's grants and, for delegated work,
the requesting employee's grants. An employee can never widen its own policy.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from bozii.states import TOOL_RISK_CONSEQUENTIAL


class PermissionDenied(Exception):
    def __init__(self, permission: str, detail: str = ""):
        self.permission = permission
        super().__init__(detail or f"Missing permission: {permission}")


def intersect_permissions(a: dict | None, b: dict | None) -> dict:
    """Effective permissions are the *narrowest* of both policies."""
    a = a or {}
    b = b or {}
    out: dict = {}
    for key in set(a) | set(b):
        va, vb = a.get(key), b.get(key)
        if isinstance(va, bool) or isinstance(vb, bool):
            out[key] = bool(va) and bool(vb)
        elif isinstance(va, str) and isinstance(vb, str):
            # rank: none < search < fetch  /  none < workspace  /  none < sandbox
            rank = {"none": 0, "search": 1, "fetch": 2, "workspace": 1, "sandbox": 1}
            out[key] = va if rank.get(va, 0) <= rank.get(vb, 0) else vb
        else:
            out[key] = va if va is not None else vb
    return out


def check_permission(effective: dict, required: dict, tool_name: str = "") -> None:
    """Raise :class:`PermissionDenied` when `required` is not satisfied."""
    for key, needed in (required or {}).items():
        granted = (effective or {}).get(key)
        if isinstance(needed, bool):
            if needed and not granted:
                raise PermissionDenied(key, f"Tool '{tool_name}' requires permission '{key}'")
            continue
        if isinstance(needed, str) and needed != "none":
            order = {"none": 0, "search": 1, "fetch": 2, "workspace": 1, "sandbox": 1}
            if order.get(str(granted), 0) < order.get(needed, 0):
                raise PermissionDenied(
                    key,
                    f"Tool '{tool_name}' requires permission '{key}={needed}', granted: '{granted}'",
                )
        elif needed and not granted:
            raise PermissionDenied(key, f"Tool '{tool_name}' requires permission '{key}'")


def requires_approval(tool, effective: dict | None = None) -> bool:
    """Whether a tool call must be approved by a human before it runs.

    The decision is based on the tool itself: consequential actions (delegation,
    capability registration) and anything that publishes externally always need
    explicit approval, regardless of who is calling.
    """
    if getattr(tool, "risk", "safe") == TOOL_RISK_CONSEQUENTIAL:
        return True
    required = getattr(tool, "required_permissions", {}) or {}
    if required.get("publish") is True:
        return True
    return False


# --------------------------------------------------------------------- paths
class PathEscapeError(Exception):
    pass


def safe_path(root: Path | str, *parts: str) -> Path:
    """Resolve `parts` under `root`, refusing traversal outside of it."""
    root_path = Path(root).resolve()
    candidate = root_path
    for part in parts:
        if part in ("", None):
            continue
        if os.path.isabs(part) or part.startswith("~"):
            raise PathEscapeError(f"Absolute paths are not allowed: {part}")
        candidate = (candidate / part).resolve()
        if candidate != root_path and root_path not in candidate.parents:
            raise PathEscapeError(f"Path escapes the workspace: {part}")
    if candidate != root_path and root_path not in candidate.parents and candidate != root_path:
        raise PathEscapeError("Path escapes the workspace")
    if not str(candidate).startswith(str(root_path)):
        raise PathEscapeError("Path escapes the workspace")
    return candidate


_BLOCKED_HOSTS = {"localhost", "0.0.0.0", "::1"}


def assert_public_url(url: str) -> None:
    """Reject URLs that resolve to private/link-local/metadata addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise PermissionDenied("net", f"Unsupported URL scheme: {parsed.scheme}")
    host = parsed.hostname
    if not host:
        raise PermissionDenied("net", "URL has no host")
    if host in _BLOCKED_HOSTS:
        raise PermissionDenied("net", f"Requests to {host} are blocked")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:  # DNS failure surfaces as a tool error
        raise PermissionDenied("net", f"DNS resolution failed for {host}: {exc}") from exc
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise PermissionDenied("net", f"Requests to private address {addr} are blocked")
        if str(ip) == "169.254.169.254":
            raise PermissionDenied("net", "Cloud metadata endpoint is blocked")


__all__ = [
    "PermissionDenied",
    "PathEscapeError",
    "assert_public_url",
    "check_permission",
    "intersect_permissions",
    "requires_approval",
    "safe_path",
]
