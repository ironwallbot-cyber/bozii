"""Application settings, advertising configuration and health."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from bozii import __version__
from bozii.api.deps import ApiError, CurrentUser, DbSession
from bozii.config import get_settings
from bozii.models import AppSetting
from bozii.sandbox import isolation_report
from bozii.schemas import AdsOut, SettingsOut, SettingsUpdate
from bozii.security.audit import audit

router = APIRouter(prefix="/api", tags=["settings"])

EDITABLE_KEYS = {
    "allow_signup",
    "enable_ads",
    "ads_provider",
    "ads_slot_id",
    "ads_placement",
    "ads_snippet",
}


async def _overrides(db) -> dict:
    rows = (await db.execute(select(AppSetting))).scalars().all()
    return {row.key: row.value for row in rows}


def _effective(settings, overrides: dict, key: str):
    if key in overrides:
        return overrides[key]
    return getattr(settings, key, None)


async def settings_out(db) -> SettingsOut:
    settings = get_settings()
    overrides = await _overrides(db)
    from bozii.models import User

    first_user = (await db.execute(select(User.id).limit(1))).first()
    needs_setup = first_user is None
    ads_provider = _effective(settings, overrides, "ads_provider") or ""
    ads_snippet = _effective(settings, overrides, "ads_snippet") or ""
    enable_ads = bool(_effective(settings, overrides, "enable_ads"))
    return SettingsOut(
        app_name=settings.app_name,
        environment=settings.environment,
        allow_signup=bool(_effective(settings, overrides, "allow_signup")),
        enable_ads=enable_ads,
        ads_configured=bool(enable_ads and ads_provider and (ads_snippet or settings.ads_slot_id)),
        ads_placement=str(_effective(settings, overrides, "ads_placement") or settings.ads_placement),
        ads_provider=ads_provider,
        task_workers=settings.task_workers,
        max_iterations=settings.max_iterations,
        task_timeout_seconds=settings.task_timeout_seconds,
        sandbox=isolation_report(),
        version=__version__,
        needs_setup=needs_setup,
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings_view(user: CurrentUser, db: DbSession) -> SettingsOut:
    return await settings_out(db)


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(payload: SettingsUpdate, user: CurrentUser, db: DbSession) -> SettingsOut:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise ApiError(400, "No settings supplied", code="validation")
    for key, value in data.items():
        if key not in EDITABLE_KEYS:
            continue
        row = await db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    await audit(
        db, action="settings.updated", actor=f"user:{user.id}", user_id=user.id,
        resource_type="settings", resource_id="app", detail={"fields": sorted(data)},
    )
    await db.commit()
    return await settings_out(db)


@router.post("/settings/ads", response_model=SettingsOut)
async def update_ads(payload: dict, user: CurrentUser, db: DbSession) -> SettingsOut:
    """Update advertising configuration (provider, slot, placement, snippet)."""
    if not isinstance(payload, dict):
        raise ApiError(400, "Expected an object", code="validation")
    for key, value in payload.items():
        if key not in EDITABLE_KEYS:
            raise ApiError(400, f"Setting '{key}' is not editable", code="validation")
        row = await db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    await audit(
        db, action="settings.updated", actor=f"user:{user.id}", user_id=user.id,
        resource_type="settings", resource_id="ads", detail={"fields": sorted(payload)},
    )
    await db.commit()
    return await settings_out(db)


@router.get("/ads", response_model=AdsOut)
async def ads_placement(user: CurrentUser, db: DbSession) -> AdsOut:
    """Advertising placement payload.

    Ad content is rendered in a sandboxed iframe, is clearly labelled, and is
    never placed into any model prompt or agent context.
    """
    settings = get_settings()
    overrides = await _overrides(db)
    enabled = bool(_effective(settings, overrides, "enable_ads"))
    provider = str(_effective(settings, overrides, "ads_provider") or "")
    snippet = str(_effective(settings, overrides, "ads_snippet") or "")
    slot = str(_effective(settings, overrides, "ads_slot_id") or settings.ads_slot_id)
    placement = str(_effective(settings, overrides, "ads_placement") or settings.ads_placement)
    if not enabled or not provider:
        return AdsOut(enabled=False, placement=placement, provider=provider, html="")
    html = snippet or ""
    return AdsOut(
        enabled=True,
        placement=placement,
        provider=provider,
        label="Sponsored",
        html=html,
    )


@router.get("/health")
async def health(db: DbSession) -> dict:
    settings = get_settings()
    queue_state = {"queued": 0, "running": 0, "workers": settings.task_workers}
    try:
        from bozii.engine.queue import get_queue

        queue_state = await get_queue().pending_count()
    except Exception:  # pragma: no cover
        pass
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment,
        "queue": queue_state,
        "database": settings.database_url.split("://")[0] if "://" in settings.database_url else "sqlite",
    }


__all__ = ["router", "settings_out"]
