"""Sliding-window rate limiter (in-process, per key)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

_lock = Lock()
_windows: dict[str, deque[float]] = defaultdict(deque)


def hit(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    """Record an attempt. Returns (allowed, remaining)."""
    now = time.monotonic()
    with _lock:
        window = _windows[key]
        cutoff = now - window_seconds
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) >= limit:
            return False, 0
        window.append(now)
        return True, limit - len(window)


def reset() -> None:
    with _lock:
        _windows.clear()


def peek(key: str, limit: int, window_seconds: int = 60) -> int:
    now = time.monotonic()
    with _lock:
        window = _windows[key]
        cutoff = now - window_seconds
        while window and window[0] <= cutoff:
            window.popleft()
        return max(0, limit - len(window))


__all__ = ["hit", "reset", "peek"]
