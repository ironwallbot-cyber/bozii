"""Shared API dependencies: authentication, rate limiting, error handling."""

from __future__ import annotations

from typing import Any, Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from bozii.config import get_settings
from bozii.db import get_session
from bozii.models import User
from bozii.security import ratelimit
from bozii.security.auth import load_user_for_token


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str = "error", detail: Any = None):
        self.status = status
        self.message = message
        self.code = code
        self.detail = detail
        super().__init__(message)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def get_current_user(
    request: Request, db: Annotated[AsyncSession, Depends(get_session)]
) -> User:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie, "")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    if not token:
        raise ApiError(401, "Authentication required", code="unauthenticated")
    user = await load_user_for_token(db, token)
    if user is None:
        raise ApiError(401, "Session expired or invalid", code="unauthenticated")
    return user


async def get_optional_user(
    request: Request, db: Annotated[AsyncSession, Depends(get_session)]
) -> User | None:
    try:
        return await get_current_user(request, db)
    except ApiError:
        return None


def enforce_rate_limit(bucket: str, limit: int, key: str | None = None) -> None:
    settings = get_settings()
    allowed, remaining = ratelimit.hit(f"{bucket}:{key or 'global'}", limit)
    if not allowed:
        raise ApiError(
            429,
            "Too many requests for this endpoint. Please wait a moment and try again.",
            code="rate_limited",
        )


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


def not_found(resource: str = "Resource") -> ApiError:
    return ApiError(404, f"{resource} not found", code="not_found")


__all__ = [
    "ApiError",
    "CurrentUser",
    "DbSession",
    "client_ip",
    "enforce_rate_limit",
    "get_current_user",
    "get_optional_user",
    "not_found",
]
