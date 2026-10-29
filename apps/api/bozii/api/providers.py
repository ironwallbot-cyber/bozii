"""Model provider routes: configure, health-check and discover models."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from bozii.api.deps import ApiError, CurrentUser, DbSession, not_found
from bozii.model_adapters import check_provider, list_available_models
from bozii.models import ModelRecord, Provider
from bozii.schemas import ModelOut, ProviderCreate, ProviderOut, ProviderUpdate
from bozii.security.audit import audit

router = APIRouter(prefix="/api", tags=["models"])


def _to_out(provider: Provider, models: list[ModelRecord] | None = None) -> ProviderOut:
    out = ProviderOut.model_validate(provider)
    out.has_api_key = bool(provider.api_key)
    out.models = [ModelOut.model_validate(m) for m in (models or [])]
    # Never expose stored secrets in the API response.
    out.config = {k: v for k, v in (provider.config or {}).items() if "secret" not in k.lower()}
    return out


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(user: CurrentUser, db: DbSession) -> list[ProviderOut]:
    providers = (
        await db.execute(
            select(Provider).where(Provider.user_id == user.id).order_by(Provider.created_at.asc())
        )
    ).scalars().all()
    out = []
    for provider in providers:
        models = (
            await db.execute(
                select(ModelRecord).where(ModelRecord.provider_id == provider.id).order_by(ModelRecord.name.asc())
            )
        ).scalars().all()
        out.append(_to_out(provider, models))
    return out


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def create_provider(payload: ProviderCreate, user: CurrentUser, db: DbSession) -> ProviderOut:
    if payload.kind == "ollama" and not payload.base_url:
        payload.base_url = "http://127.0.0.1:11434"
    if payload.kind == "openai_compat" and not payload.base_url:
        raise ApiError(400, "A base URL is required for OpenAI-compatible providers", code="validation")
    if payload.is_default:
        await _clear_default(db, user.id)
    provider = Provider(
        user_id=user.id,
        name=payload.name.strip(),
        kind=payload.kind,
        base_url=payload.base_url.rstrip("/"),
        api_key_env=payload.api_key_env,
        api_key=payload.api_key,
        config=payload.config,
        is_default=payload.is_default,
    )
    db.add(provider)
    await db.flush()
    await check_provider(db, provider, discover=True)
    await audit(
        db, action="provider.created", actor=f"user:{user.id}", user_id=user.id,
        resource_type="provider", resource_id=provider.id,
        detail={"name": provider.name, "kind": provider.kind, "base_url": provider.base_url},
    )
    await db.commit()
    models = (
        await db.execute(select(ModelRecord).where(ModelRecord.provider_id == provider.id))
    ).scalars().all()
    return _to_out(provider, models)


@router.post("/providers/{provider_id}/check", response_model=ProviderOut)
async def check(provider_id: str, user: CurrentUser, db: DbSession) -> ProviderOut:
    provider = await _get(db, user.id, provider_id)
    health = await check_provider(db, provider, discover=True)
    await audit(
        db, action="provider.checked", actor=f"user:{user.id}", user_id=user.id,
        resource_type="provider", resource_id=provider.id,
        detail={"ok": health.ok, "message": health.message[:200]},
    )
    await db.commit()
    if not health.ok:
        # Surfaced in the response body rather than as an HTTP error, so the UI
        # can show exactly what is wrong with the provider.
        pass
    models = (
        await db.execute(select(ModelRecord).where(ModelRecord.provider_id == provider.id).order_by(ModelRecord.name))
    ).scalars().all()
    return _to_out(provider, models)


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: str, payload: ProviderUpdate, user: CurrentUser, db: DbSession
) -> ProviderOut:
    provider = await _get(db, user.id, provider_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_default"):
        await _clear_default(db, user.id)
    for field in ("name", "base_url", "api_key_env", "api_key", "config", "enabled", "is_default"):
        if field in data and data[field] is not None:
            setattr(provider, field, data[field])
    if provider.kind == "ollama" and not provider.base_url:
        provider.base_url = "http://127.0.0.1:11434"
    await audit(
        db, action="provider.updated", actor=f"user:{user.id}", user_id=user.id,
        resource_type="provider", resource_id=provider.id, detail={"fields": sorted(data)},
    )
    await db.commit()
    models = (
        await db.execute(select(ModelRecord).where(ModelRecord.provider_id == provider.id))
    ).scalars().all()
    return _to_out(provider, models)


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str, user: CurrentUser, db: DbSession) -> dict:
    provider = await _get(db, user.id, provider_id)
    for model in (
        await db.execute(select(ModelRecord).where(ModelRecord.provider_id == provider.id))
    ).scalars().all():
        await db.delete(model)
    await db.delete(provider)
    await audit(
        db, action="provider.deleted", actor=f"user:{user.id}", user_id=user.id,
        resource_type="provider", resource_id=provider_id,
    )
    await db.commit()
    return {"deleted": True}


@router.get("/models", response_model=list[ModelOut])
async def available_models(
    user: CurrentUser, db: DbSession, available_only: bool = Query(True)
) -> list[ModelOut]:
    rows = (
        await db.execute(
            select(ModelRecord)
            .join(Provider, Provider.id == ModelRecord.provider_id)
            .where(Provider.user_id == user.id)
            .order_by(ModelRecord.available.desc(), ModelRecord.display_name.asc())
        )
    ).scalars()
    models = [ModelOut.model_validate(m) for m in rows]
    if available_only:
        models = [m for m in models if m.available]
    return models


async def _clear_default(db, user_id: str) -> None:
    rows = (
        await db.execute(select(Provider).where(Provider.user_id == user_id, Provider.is_default.is_(True)))
    ).scalars().all()
    for row in rows:
        row.is_default = False


async def _get(db, user_id: str, provider_id: str) -> Provider:
    provider = await db.get(Provider, provider_id)
    if provider is None or provider.user_id != user_id:
        raise not_found("Provider")
    return provider


__all__ = ["router"]
