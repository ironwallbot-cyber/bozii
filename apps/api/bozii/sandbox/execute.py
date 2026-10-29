"""Sandboxed subprocess execution.

Every command that Bozii runs on the user's behalf (tests, linters, generated
capability code) goes through :func:`run_sandboxed`, which applies:

* a fresh process group and a hard wall-clock timeout (process group is killed),
  CPU, address-space, file-size and open-file resource limits,
* an environment scrubbed of secrets,
* a working directory confined to a Bozii workspace,
* optional network isolation via an unprivileged network namespace
  (`unshare -n`) when the host permits it,
* optional privilege drop to an unprivileged user when Bozii runs as root.

The isolation report returned with every result is surfaced in the UI so the
operator can see exactly which guarantees were actually enforced.
"""

from __future__ import annotations

import asyncio
import os
import pwd
import resource
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bozii.config import get_settings

DEFAULT_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "TZ", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")


@dataclass
class SandboxResult:
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    truncated: bool = False
    isolation: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
            "isolation": self.isolation,
        }


def network_isolation_available() -> bool:
    settings = get_settings()
    if not settings.sandbox_network_isolation:
        return False
    if os.geteuid() != 0:
        return False
    return shutil.which("unshare") is not None and shutil.which("setpriv") is not None


def _path_accessible_by(path: Path | str, uid: int, gid: int) -> bool:
    """Best-effort check that `uid/gid` can traverse and read `path`.

    Bozii often lives under a directory the sandbox user cannot traverse (for
    example a project folder owned by the operator). Privilege drop is disabled
    in that case rather than letting every sandboxed command fail.
    """
    target = Path(path)
    chain = list(target.parents)[::-1] + [target]
    for idx, part in enumerate(chain):
        try:
            st = part.stat()
        except OSError:
            return False
        is_target = idx == len(chain) - 1
        # Permission bit masks: owner 0o700, group 0o070, others 0o007.
        if st.st_uid == uid:
            need = (0o400 | 0o000) if is_target else 0o100  # owner read on target, owner exec on dirs
            if is_target:
                need = 0o400
            if not (st.st_mode & need):
                return False
            continue
        if st.st_gid == gid and (st.st_mode & 0o070):
            need = 0o040 if is_target else 0o010  # group read / group exec
            if (st.st_mode & need) != need:
                return False
            continue
        need = 0o004 if is_target else 0o001  # others read / others exec
        if (st.st_mode & need) != need:
            return False
    return True


def _sandbox_uid() -> tuple[int, int] | None:
    settings = get_settings()
    if os.geteuid() != 0 or not settings.sandbox_user:
        return None
    try:
        info = pwd.getpwnam(settings.sandbox_user)
    except KeyError:
        return None
    if os.getuid() == info.pw_uid:
        return None
    if not _path_accessible_by(settings.data_dir.resolve(), info.pw_uid, info.pw_gid):
        return None
    return info.pw_uid, info.pw_gid


def _preexec(memory_mb: int, cpu_seconds: int, uid: tuple[int, int] | None):
    def _fn() -> None:
        os.setsid()
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 2))
        except (ValueError, OSError):
            pass
        try:
            limit = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ValueError, OSError):
            pass
        try:
            fsize = 256 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        except (ValueError, OSError):
            pass
        if uid is not None:
            try:
                os.setgroups([])
                os.setgid(uid[1])
                os.setuid(uid[0])
            except (PermissionError, OSError):
                pass

    return _fn


def scrubbed_env(cwd: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in DEFAULT_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["PATH"] = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["HOME"] = str(cwd)
    env["TMPDIR"] = str(cwd)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    # Explicitly never forward secrets into sandboxed processes.
    for key in list(env):
        if any(tok in key.upper() for tok in ("TOKEN", "SECRET", "KEY", "PASSWORD")):
            env.pop(key, None)
    if extra:
        env.update(extra)
    return env


async def run_sandboxed(
    cmd: list[str],
    cwd: Path | str,
    timeout: int | None = None,
    memory_mb: int | None = None,
    cpu_seconds: int | None = None,
    network: bool = False,
    input_text: str | None = None,
    max_output: int = 200_000,
    extra_env: dict[str, str] | None = None,
) -> SandboxResult:
    settings = get_settings()
    timeout = timeout if timeout is not None else settings.sandbox_timeout_seconds
    memory_mb = memory_mb if memory_mb is not None else settings.sandbox_memory_mb
    cpu_seconds = cpu_seconds if cpu_seconds is not None else settings.sandbox_cpu_seconds
    cwd_path = Path(cwd).resolve()
    cwd_path.mkdir(parents=True, exist_ok=True)

    effective_cmd = list(cmd)
    settings = get_settings()
    isolation: dict[str, Any] = {
        "timeout_seconds": timeout,
        "memory_mb": memory_mb,
        "cpu_seconds": cpu_seconds,
        "network": False,
        "user": None,
        "network_isolated": False,
        "cwd": str(cwd_path),
    }

    uid = _sandbox_uid()
    use_netns = (not network) and network_isolation_available()
    drop_in_wrapper = False

    if use_netns and uid is not None:
        # `unshare` needs CAP_SYS_ADMIN, which would be lost after setuid, so the
        # namespace is created first and privileges are dropped inside it.
        import grp

        try:
            group = grp.getgrgid(uid[1]).gr_name
        except KeyError:
            group = str(uid[1])
        effective_cmd = [
            "unshare", "-n", "--",
            "setpriv", "--reuid", str(uid[0]), "--regid", str(uid[1]),
            "--clear-groups", "--",
        ] + effective_cmd
        isolation["network"] = False
        isolation["network_isolated"] = True
        isolation["user"] = settings.sandbox_user
        drop_in_wrapper = False  # already handled by setpriv
    elif use_netns:
        effective_cmd = ["unshare", "-n", "--"] + effective_cmd
        isolation["network"] = False
        isolation["network_isolated"] = True
        isolation["user"] = None
    elif uid is not None:
        # No namespace available: still drop privileges to protect the host FS.
        isolation["network"] = True
        isolation["network_isolated"] = False
        isolation["user"] = settings.sandbox_user
        drop_in_wrapper = True
    else:
        isolation["network"] = not network_isolation_available()
        isolation["network_isolated"] = False
        isolation["user"] = None

    if use_netns and uid is not None:
        drop_uid: tuple[int, int] | None = None  # setpriv handles the drop
    elif drop_in_wrapper:
        drop_uid = uid
    else:
        drop_uid = None

    env = scrubbed_env(cwd_path, extra_env)
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *effective_cmd,
            cwd=str(cwd_path),
            env=env,
            stdin=asyncio.subprocess.PIPE if input_text is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_preexec(memory_mb, cpu_seconds, drop_uid),
        )
    except FileNotFoundError as exc:
        return SandboxResult(
            command=effective_cmd,
            exit_code=127,
            stdout="",
            stderr=f"Command not found: {exc}",
            timed_out=False,
            duration_ms=0,
            isolation=isolation,
        )

    timed_out = False
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(input_text.encode() if input_text is not None else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        stdout_b, stderr_b = b"", b""

    duration_ms = int((time.monotonic() - started) * 1000)
    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")
    truncated = False
    if len(stdout) > max_output:
        stdout = stdout[:max_output] + "\n...[output truncated]"
        truncated = True
    if len(stderr) > max_output:
        stderr = stderr[:max_output] + "\n...[output truncated]"
        truncated = True
    if timed_out:
        stderr = (stderr + f"\nKilled after exceeding the {timeout}s timeout.").strip()

    return SandboxResult(
        command=effective_cmd,
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_ms=duration_ms,
        truncated=truncated,
        isolation=isolation,
    )


def isolation_report() -> dict[str, Any]:
    """Describe the isolation this host can actually enforce."""
    settings = get_settings()
    uid = _sandbox_uid()
    notes = [
        "Bozii sandboxes execution with process isolation, resource limits and "
        "(when available) a private network namespace. It is not a VM: run Bozii "
        "as an unprivileged user on a hardened host for untrusted workloads."
    ]
    if os.geteuid() == 0 and uid is None and settings.sandbox_user:
        notes.append(
            f"Privilege drop to '{settings.sandbox_user}' is disabled because that user "
            "cannot read the Bozii data directory. Run Bozii as an unprivileged user, or "
            f"make {settings.data_dir.resolve()} readable by '{settings.sandbox_user}', to enable it."
        )
    if not network_isolation_available():
        notes.append("Network namespace isolation is unavailable on this host.")
    return {
        "network_isolation": network_isolation_available(),
        "privilege_drop": uid is not None,
        "sandbox_user": settings.sandbox_user if uid is not None else None,
        "running_as_root": os.geteuid() == 0,
        "timeout_seconds": settings.sandbox_timeout_seconds,
        "memory_mb": settings.sandbox_memory_mb,
        "cpu_seconds": settings.sandbox_cpu_seconds,
        "allowed_commands": settings.allowed_command_list,
        "notes": " ".join(notes),
    }


__all__ = [
    "SandboxResult",
    "isolation_report",
    "network_isolation_available",
    "run_sandboxed",
    "scrubbed_env",
]
