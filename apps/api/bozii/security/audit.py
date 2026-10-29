"""Audit trail helper. Audit records are append-only and never contain secrets."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bozii.models import AuditEvent


async def audit(
    db: AsyncSession,
    *,
    action: str,
    actor: str = "system",
    user_id: str | None = None,
    resource_type: str = "",
    resource_id: str = "",
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
    commit: bool = False,
) -> AuditEvent:
    safe_detail = {k: v for k, v in (detail or {}).items() if "secret" not in k and "password" not in k}
    event = AuditEvent(
        user_id=user_id,
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=safe_detail,
        ip=ip,
    )
    db.add(event)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return event


__all__ = ["audit"]
