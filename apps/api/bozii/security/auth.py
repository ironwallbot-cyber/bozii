"""Password hashing and session management.

Uses the standard library's scrypt (memory-hard) so no extra dependency is
required. Session tokens are random, stored only as a SHA-256 digest, delivered
as an HttpOnly cookie and expire after `SESSION_TTL_HOURS`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bozii.config import get_settings
from bozii.models import SessionToken, User

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 64


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(digest_hex) // 2,
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(
    db: AsyncSession,
    user: User,
    user_agent: str | None = None,
    ip: str | None = None,
) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    session = SessionToken(
        token_hash=hash_token(token),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours),
        user_agent=(user_agent or "")[:255] or None,
        ip=ip,
    )
    db.add(session)
    await db.commit()
    return token


async def load_user_for_token(db: AsyncSession, token: str) -> User | None:
    if not token:
        return None
    result = await db.execute(
        select(User)
        .join(SessionToken, SessionToken.user_id == User.id)
        .where(SessionToken.token_hash == hash_token(token))
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    row = await db.execute(select(SessionToken).where(SessionToken.token_hash == hash_token(token)))
    session = row.scalar_one_or_none()
    if session is None:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        await db.delete(session)
        await db.commit()
        return None
    return user


async def destroy_session(db: AsyncSession, token: str) -> None:
    if not token:
        return
    await db.execute(delete(SessionToken).where(SessionToken.token_hash == hash_token(token)))
    await db.commit()


async def destroy_all_sessions(db: AsyncSession, user_id: str) -> None:
    await db.execute(delete(SessionToken).where(SessionToken.user_id == user_id))
    await db.commit()


async def first_user_exists(db: AsyncSession) -> bool:
    row = await db.execute(select(User.id).limit(1))
    return row.scalar_one_or_none() is not None


__all__ = [
    "hash_password",
    "verify_password",
    "create_session",
    "load_user_for_token",
    "destroy_session",
    "destroy_all_sessions",
    "first_user_exists",
    "hash_token",
]
