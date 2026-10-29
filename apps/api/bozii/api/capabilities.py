"""Capability library routes: search, inspect, version, import/export, publish."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from bozii.api.deps import ApiError, CurrentUser, DbSession, not_found
from bozii.capability_engine import build_capability, export_bundle, import_bundle
from bozii.models import Capability, CapabilityReport, Employee, Task
from bozii.schemas import (
    CapabilityCreateManual,
    CapabilityOut,
    CapabilityReportIn,
    CapabilityVisibility,
    InstallCapability,
)
from bozii.security.audit import audit
from bozii.states import CAP_ACTIVE, CAP_DEPRECATED, CAP_DISABLED, CAP_FAILED

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


@router.get("")
async def list_capabilities(
    user: CurrentUser,
    db: DbSession,
    q: str = Query(""),
    kind: str = Query(""),
    category: str = Query(""),
    visibility: str = Query(""),
    mine: bool = Query(False),
    status: str = Query(""),
    limit: int = Query(100, le=500),
) -> dict:
    stmt = select(Capability).where(
        or_(Capability.created_by_user_id == user.id, Capability.visibility == "public")
    )
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Capability.name.ilike(pattern),
                Capability.description.ilike(pattern),
                Capability.slug.ilike(pattern),
                Capability.category.ilike(pattern),
            )
        )
    if kind:
        stmt = stmt.where(Capability.kind == kind)
    if category:
        stmt = stmt.where(Capability.category == category)
    if visibility:
        stmt = stmt.where(Capability.visibility == visibility)
    if status:
        stmt = stmt.where(Capability.status == status)
    if mine:
        stmt = stmt.where(Capability.created_by_user_id == user.id)
    rows = list(
        (await db.execute(stmt.order_by(Capability.created_at.desc()).limit(limit))).scalars()
    )
    return {
        "items": [CapabilityOut.model_validate(c).model_dump(mode="json") for c in rows],
        "count": len(rows),
    }


@router.get("/categories/list")
async def categories(user: CurrentUser, db: DbSession) -> list[str]:
    rows = (
        await db.execute(
            select(Capability.category)
            .where(
                or_(Capability.created_by_user_id == user.id, Capability.visibility == "public"),
                Capability.is_active.is_(True),
            )
            .distinct()
        )
    ).scalars()
    return sorted({c for c in rows if c})


@router.post("", response_model=CapabilityOut, status_code=201)
async def create_capability(
    payload: CapabilityCreateManual, user: CurrentUser, db: DbSession
) -> CapabilityOut:
    if not payload.files:
        raise ApiError(400, "At least one file is required", code="validation")
    employee = None
    task = None
    outcome = await build_capability(
        db,
        user_id=user.id,
        name=payload.name,
        kind=payload.kind,
        description=payload.description,
        category=payload.category,
        permissions=payload.permissions,
        tags=payload.tags,
        files=payload.files,
        activate=payload.activate,
        visibility=payload.visibility,
    )
    if not outcome.ok:
        raise ApiError(422, "Validation failed", code="capability_invalid", detail=outcome.errors)
    cap = await db.get(Capability, outcome.capability_id)
    await audit(
        db, action="capability.created", actor=f"user:{user.id}", user_id=user.id,
        resource_type="capability", resource_id=cap.id,
        detail={"slug": cap.slug, "version": cap.version},
    )
    await db.commit()
    return CapabilityOut.model_validate(cap)


@router.get("/{capability_id}", response_model=CapabilityOut)
async def get_capability(capability_id: str, user: CurrentUser, db: DbSession) -> CapabilityOut:
    cap = await _get(db, user.id, capability_id)
    return CapabilityOut.model_validate(cap)


@router.get("/{capability_id}/export")
async def export_capability(capability_id: str, user: CurrentUser, db: DbSession) -> dict:
    cap = await _get(db, user.id, capability_id)
    return export_bundle(cap)


@router.post("/import", response_model=dict, status_code=201)
async def import_capability(payload: dict, user: CurrentUser, db: DbSession) -> dict:
    bundle = payload.get("bundle") if isinstance(payload.get("bundle"), dict) else payload
    activate = bool(payload.get("activate", True))
    outcome = await import_bundle(db, user.id, bundle, activate=activate)
    if not outcome.ok:
        raise ApiError(422, "Import rejected", code="capability_invalid", detail=outcome.errors)
    await audit(
        db, action="capability.imported", actor=f"user:{user.id}", user_id=user.id,
        resource_type="capability", resource_id=outcome.capability_id or "",
        detail={"slug": outcome.slug, "version": outcome.version},
    )
    await db.commit()
    return outcome.as_dict()


@router.post("/{capability_id}/activate", response_model=CapabilityOut)
async def activate_version(capability_id: str, user: CurrentUser, db: DbSession) -> CapabilityOut:
    cap = await _get(db, user.id, capability_id)
    if cap.status == CAP_FAILED:
        raise ApiError(
            400,
            f"Version {cap.version} failed validation and cannot be activated",
            code="invalid_status",
        )
    if not (cap.test_results or {}).get("passed", False) and cap.kind == "tool":
        raise ApiError(400, "Only capabilities with passing tests can be activated", code="tests_failed")
    siblings = (
        await db.execute(select(Capability).where(Capability.slug == cap.slug, Capability.is_active.is_(True)))
    ).scalars().all()
    for sibling in siblings:
        sibling.is_active = False
        sibling.status = CAP_DEPRECATED if sibling.id != cap.id else sibling.status
    cap.is_active = True
    cap.status = CAP_ACTIVE
    cap.activated_at = datetime.now(timezone.utc)
    await audit(
        db, action="capability.activated", actor=f"user:{user.id}", user_id=user.id,
        resource_type="capability", resource_id=cap.id, detail={"slug": cap.slug, "version": cap.version},
    )
    await db.commit()
    return CapabilityOut.model_validate(cap)


@router.post("/{capability_id}/disable", response_model=CapabilityOut)
async def disable_capability(capability_id: str, user: CurrentUser, db: DbSession) -> CapabilityOut:
    cap = await _get(db, user.id, capability_id)
    cap.is_active = False
    cap.status = CAP_DISABLED
    await audit(
        db, action="capability.disabled", actor=f"user:{user.id}", user_id=user.id,
        resource_type="capability", resource_id=cap.id,
    )
    await db.commit()
    return CapabilityOut.model_validate(cap)


@router.post("/{capability_id}/publish", response_model=CapabilityOut)
async def publish_capability(
    capability_id: str, payload: CapabilityVisibility, user: CurrentUser, db: DbSession
) -> CapabilityOut:
    cap = await _get(db, user.id, capability_id)
    if payload.visibility == "public" and not cap.is_active:
        raise ApiError(400, "Only active capabilities can be published", code="inactive")
    if payload.visibility == "public" and cap.kind == "tool" and not (cap.test_results or {}).get("passed"):
        raise ApiError(400, "Only capabilities with passing tests can be published", code="tests_failed")
    cap.visibility = payload.visibility
    await audit(
        db, action="capability.published" if payload.visibility == "public" else "capability.unpublished",
        actor=f"user:{user.id}", user_id=user.id,
        resource_type="capability", resource_id=cap.id, detail={"visibility": cap.visibility},
    )
    await db.commit()
    return CapabilityOut.model_validate(cap)


@router.post("/{capability_id}/install", response_model=dict, status_code=201)
async def install_capability(
    capability_id: str, payload: InstallCapability, user: CurrentUser, db: DbSession
) -> dict:
    """Copy a public capability into this workspace as a private, validated copy."""
    cap = await db.get(Capability, capability_id)
    if cap is None or (cap.visibility != "public" and cap.created_by_user_id != user.id):
        raise not_found("Capability")
    bundle = export_bundle(cap)
    outcome = await import_bundle(db, user.id, bundle, activate=payload.activate)
    if not outcome.ok:
        raise ApiError(422, "Install rejected", code="capability_invalid", detail=outcome.errors)
    await db.execute(
        select(Capability).where(Capability.id == outcome.capability_id)
    )
    installed = await db.get(Capability, outcome.capability_id)
    if installed is not None and cap.id != installed.id:
        installed.downloads = cap.downloads + 1
    await audit(
        db, action="capability.installed", actor=f"user:{user.id}", user_id=user.id,
        resource_type="capability", resource_id=cap.id, detail={"slug": cap.slug},
    )
    await db.commit()
    return outcome.as_dict()


@router.post("/{capability_id}/report")
async def report_capability(
    capability_id: str, payload: CapabilityReportIn, user: CurrentUser, db: DbSession
) -> dict:
    cap = await _get(db, user.id, capability_id)
    db.add(
        CapabilityReport(
            capability_id=cap.id, reporter_user_id=user.id,
            reason=payload.reason, severity=payload.severity,
        )
    )
    cap.reports += 1
    await audit(
        db, action="capability.reported", actor=f"user:{user.id}", user_id=user.id,
        resource_type="capability", resource_id=cap.id,
        detail={"severity": payload.severity, "reason": payload.reason[:200]},
    )
    await db.commit()
    return {"recorded": True, "reports": cap.reports}


@router.delete("/{capability_id}")
async def delete_capability(capability_id: str, user: CurrentUser, db: DbSession) -> dict:
    cap = await _get(db, user.id, capability_id)
    if cap.visibility == "public":
        raise ApiError(400, "Unpublish the capability before deleting it", code="public")
    siblings = (
        await db.execute(
            select(Capability).where(
                Capability.slug == cap.slug, Capability.created_by_user_id == user.id
            )
        )
    ).scalars().all()
    for sibling in siblings:
        await db.delete(sibling)
    await audit(
        db, action="capability.deleted", actor=f"user:{user.id}", user_id=user.id,
        resource_type="capability", resource_id=capability_id,
        detail={"slug": cap.slug, "versions": len(siblings)},
    )
    await db.commit()
    return {"deleted": len(siblings)}


async def _get(db, user_id: str, capability_id: str) -> Capability:
    cap = await db.get(Capability, capability_id)
    if cap is None or (cap.created_by_user_id != user_id and cap.visibility != "public"):
        raise not_found("Capability")
    return cap


__all__ = ["router"]
