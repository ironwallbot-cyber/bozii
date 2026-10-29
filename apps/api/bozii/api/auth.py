"""Authentication routes: first-run setup, signup, login, logout, session."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from bozii.api.deps import ApiError, CurrentUser, DbSession, client_ip, enforce_rate_limit
from bozii.config import get_settings
from bozii.models import User
from bozii.schemas import AuthResponse, LoginRequest, SetupRequest, UserOut
from bozii.security import ratelimit
from bozii.security.audit import audit
from bozii.security.auth import (
    create_session,
    destroy_session,
    first_user_exists,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


@router.get("/setup-status")
async def setup_status(db: DbSession) -> dict:
    settings = get_settings()
    needs_setup = not await first_user_exists(db)
    return {
        "needs_setup": needs_setup,
        "allow_signup": settings.allow_signup,
        "app_name": settings.app_name,
        "environment": settings.environment,
    }


@router.post("/setup", response_model=AuthResponse)
async def setup(request: Request, response: Response, payload: SetupRequest, db: DbSession) -> AuthResponse:
    enforce_rate_limit("auth", get_settings().auth_rate_limit_per_minute, client_ip(request))
    if await first_user_exists(db):
        raise ApiError(403, "Setup has already been completed", code="already_setup")
    return await _register(db, response, payload, request, role="admin")


@router.post("/signup", response_model=AuthResponse)
async def signup(request: Request, response: Response, payload: SetupRequest, db: DbSession) -> AuthResponse:
    enforce_rate_limit("auth", get_settings().auth_rate_limit_per_minute, client_ip(request))
    if not get_settings().allow_signup:
        raise ApiError(403, "Signup is disabled on this instance", code="signup_disabled")
    return await _register(db, response, payload, request, role="admin")


@router.post("/login", response_model=AuthResponse)
async def login(request: Request, response: Response, payload: LoginRequest, db: DbSession) -> AuthResponse:
    enforce_rate_limit("auth", get_settings().auth_rate_limit_per_minute, client_ip(request))
    row = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = row.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        ratelimit.hit(f"auth-fail:{client_ip(request)}", 10, 300)
        await audit(
            db, action="auth.login_failed", actor="anonymous",
            detail={"email": payload.email}, ip=client_ip(request), commit=True,
        )
        raise ApiError(401, "Invalid email or password", code="invalid_credentials")
    if not user.is_active:
        raise ApiError(403, "This account is disabled", code="account_disabled")
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    token = await create_session(db, user, request.headers.get("user-agent"), client_ip(request))
    _set_cookie(response, token)
    await audit(
        db, action="auth.login", actor=f"user:{user.id}", user_id=user.id,
        resource_type="user", resource_id=user.id, ip=client_ip(request), commit=True,
    )
    return AuthResponse(user=UserOut.model_validate(user))


@router.post("/logout")
async def logout(request: Request, response: Response, db: DbSession) -> dict:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie, "")
    await destroy_session(db, token)
    response.delete_cookie(settings.session_cookie, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser, db: DbSession) -> UserOut:
    return UserOut.model_validate(user)


async def _register(db, response: Response, payload: SetupRequest, request: Request, role: str) -> AuthResponse:
    email = payload.email.lower().strip()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise ApiError(409, "An account with this email already exists", code="email_taken")
    user = User(email=email, name=payload.name or email.split("@")[0], password_hash=hash_password(payload.password), role=role)
    db.add(user)
    await db.flush()
    user.last_login_at = datetime.now(timezone.utc)
    await audit(
        db, action="auth.signup", actor=f"user:{user.id}", user_id=user.id,
        resource_type="user", resource_id=user.id, ip=client_ip(request),
    )
    await db.commit()
    token = await create_session(db, user, request.headers.get("user-agent"), client_ip(request))
    _set_cookie(response, token)
    return AuthResponse(user=UserOut.model_validate(user))


__all__ = ["router"]
