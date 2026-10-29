"""Adapter factory, provider health checks and model discovery."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bozii.model_adapters.base import (
    ModelAdapter,
    ModelError,
    ModelUnavailableError,
)
from bozii.model_adapters.mock import MockAdapter
from bozii.model_adapters.ollama import OllamaAdapter
from bozii.model_adapters.openai_compat import OpenAICompatAdapter
from bozii.models import ModelRecord, Provider

logger = logging.getLogger("bozii.models")

# Providers whose model capabilities we can actually verify.
KNOWN_KINDS = {"ollama", "openai_compat", "mock"}


def resolve_api_key(provider: Provider) -> str:
    """Resolve the provider secret without ever logging it.

    Preferred path: an environment variable name (`api_key_env`), so no secret
    is stored in the database at all. Fallback: the write-only stored value.
    """
    if provider.api_key_env:
        value = os.environ.get(provider.api_key_env, "")
        if not value:
            raise ModelUnavailableError(
                f"Provider '{provider.name}' expects the environment variable "
                f"'{provider.api_key_env}', which is not set."
            )
        return value
    return provider.api_key or ""


def adapter_for(provider: Provider) -> ModelAdapter:
    key = resolve_api_key(provider)
    if provider.kind == "ollama":
        return OllamaAdapter(base_url=provider.base_url or "http://127.0.0.1:11434", config=provider.config or {})
    if provider.kind == "openai_compat":
        return OpenAICompatAdapter(
            base_url=provider.base_url, api_key=key, config=provider.config or {}
        )
    if provider.kind == "mock":
        return MockAdapter(config=provider.config or {})
    raise ModelUnavailableError(f"Unknown provider kind '{provider.kind}'")


@dataclass
class ProviderHealth:
    ok: bool
    message: str
    models: int = 0


async def check_provider(db: AsyncSession, provider: Provider, discover: bool = True) -> ProviderHealth:
    """Ping a provider, refresh its model list and persist availability."""
    try:
        adapter = adapter_for(provider)
        ok, message = await adapter.ping()
    except ModelError as exc:
        ok, message = False, str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        ok, message = False, f"Unexpected provider error: {exc}"

    provider.last_health_at = datetime.now(timezone.utc)
    provider.last_health_ok = ok
    provider.last_health_error = None if ok else message[:2000]
    model_count = 0

    if ok and discover:
        try:
            infos = await adapter.list_models()
        except ModelError as exc:
            provider.last_health_ok = False
            provider.last_health_error = str(exc)[:2000]
            await db.flush()
            return ProviderHealth(False, str(exc), 0)
        # Ask Ollama for per-model capabilities where the API supports it.
        if isinstance(adapter, OllamaAdapter):
            for info in infos[:20]:
                try:
                    caps = await adapter.model_capabilities(info.name)
                    if caps:
                        info.capabilities = caps
                    ctx = await adapter.context_window(info.name)
                    if ctx:
                        info.context_window = ctx
                except Exception:  # capability probing is best effort
                    continue
        existing = {
            m.name: m
            for m in (
                await db.execute(select(ModelRecord).where(ModelRecord.provider_id == provider.id))
            ).scalars()
        }
        for info in infos:
            record = existing.get(info.name)
            if record is None:
                record = ModelRecord(provider_id=provider.id, name=info.name)
                db.add(record)
                existing[info.name] = record
            record.display_name = info.display_name or info.name
            record.context_window = info.context_window
            record.capabilities = info.capabilities
            record.available = True
            record.discovered_at = datetime.now(timezone.utc)
        for name, record in existing.items():
            if name not in {i.name for i in infos}:
                record.available = False
        model_count = len(infos)

    await db.flush()
    return ProviderHealth(bool(provider.last_health_ok), message, model_count)


async def discover_models(db: AsyncSession, provider: Provider) -> list[ModelRecord]:
    await check_provider(db, provider, discover=True)
    rows = await db.execute(select(ModelRecord).where(ModelRecord.provider_id == provider.id))
    return list(rows.scalars())


async def get_adapter_for_model(db: AsyncSession, model_id: str) -> tuple[ModelAdapter, ModelRecord, Provider]:
    record = await db.get(ModelRecord, model_id)
    if record is None:
        raise ModelUnavailableError("The selected model no longer exists; pick another model.")
    provider = await db.get(Provider, record.provider_id)
    if provider is None or not provider.enabled:
        raise ModelUnavailableError(
            f"The provider for model '{record.name}' is disabled or was removed."
        )
    return adapter_for(provider), record, provider


async def default_adapter(db: AsyncSession, user_id: str) -> tuple[ModelAdapter, ModelRecord, Provider]:
    """Resolve the platform default model, raising an actionable error when absent."""
    providers = (
        (
            await db.execute(
                select(Provider)
                .where(Provider.user_id == user_id, Provider.enabled.is_(True))
                .order_by(Provider.is_default.desc(), Provider.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not providers:
        raise ModelUnavailableError(
            "No model provider is configured. Add a free Ollama provider or an "
            "OpenAI-compatible endpoint in Settings -> Models."
        )
    for provider in providers:
        records = (
            (
                await db.execute(
                    select(ModelRecord)
                    .where(ModelRecord.provider_id == provider.id, ModelRecord.available.is_(True))
                    .order_by(ModelRecord.is_default.desc(), ModelRecord.discovered_at.asc())
                )
            )
            .scalars()
            .all()
        )
        if not records:
            continue
        chosen = next((r for r in records if r.is_default), records[0])
        return adapter_for(provider), chosen, provider
    raise ModelUnavailableError(
        "Providers are configured but no available model was discovered. "
        "Run a health check in Settings -> Models, or pull a model with `ollama pull <model>`."
    )


__all__ = [
    "ProviderHealth",
    "adapter_for",
    "check_provider",
    "default_adapter",
    "discover_models",
    "get_adapter_for_model",
    "resolve_api_key",
]
