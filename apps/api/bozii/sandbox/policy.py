"""Command allow-list policy for sandboxed execution."""

from __future__ import annotations

import shlex
from pathlib import Path

from bozii.config import get_settings
from bozii.security.permissions import PermissionDenied, PathEscapeError, safe_path


class CommandNotAllowed(PermissionDenied):
    def __init__(self, command: str, detail: str = ""):
        self.command = command
        super().__init__("exec", detail or f"Command '{command}' is not in the allow-list")


def allowed_commands() -> set[str]:
    return set(get_settings().allowed_command_list)


def parse_command(command: str) -> list[str]:
    """Split a shell-style command string into argv (no shell is ever spawned)."""
    if not isinstance(command, str) or not command.strip():
        raise CommandNotAllowed("", "Empty command")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise CommandNotAllowed(command, f"Could not parse command: {exc}") from exc
    if not argv:
        raise CommandNotAllowed(command, "Empty command")
    return argv


def check_command(command: str) -> list[str]:
    """Validate a command string against the allow-list, returning its argv."""
    argv = parse_command(command)
    binary = Path(argv[0]).name
    allow = allowed_commands()
    if binary not in allow:
        raise CommandNotAllowed(
            command,
            f"Command '{binary}' is not permitted. Allowed commands: {', '.join(sorted(allow))}.",
        )
    if any(tok in command for tok in (";", "&&", "||", "|", ">", "<", "`", "$(", "\n")):
        # shlex already split these, but a shell operator inside an argument is suspicious.
        for token in argv:
            if token in {"|", "||", "&&", ";", ">", ">>", "<", "&"}:
                raise CommandNotAllowed(
                    command,
                    "Shell operators are not supported; run one command at a time.",
                )
    return argv


def command_cwd(workspace_root: Path | str, subdir: str = "") -> Path:
    return safe_path(workspace_root, subdir) if subdir else Path(workspace_root).resolve()


__all__ = [
    "CommandNotAllowed",
    "allowed_commands",
    "check_command",
    "command_cwd",
    "parse_command",
]
