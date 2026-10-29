"""Model routing: pick a working model for a task and its tool requirements."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bozii.model_adapters.base import ModelAdapter, ModelUnavailableError
from bozii.model_adapters.factory import adapter_for, default_adapter, get_adapter_for_model
from bozii.models import Employee, ModelRecord, Provider

logger = logging.getLogger("bozii.router")


@dataclass
class SelectedModel:
    adapter: ModelAdapter
    model_name: str
    provider: Provider
    record: ModelRecord | None
    reason: str = ""


def supports_tools(record: ModelRecord | None) -> bool:
    if record is None:
        return True  # unknown -> try native tool calling and fall back on error
    caps = [str(c).lower() for c in (record.capabilities or [])]
    if not caps:
        return True
    if "tools" in caps or "tool_calling" in caps:
        return True
    # A model that only advertises completion has no native tool support.
    return "completion" in caps and len(caps) == 1


async def select_model(
    db: AsyncSession,
    user_id: str,
    employee: Employee | None = None,
    require_tools: bool = True,
) -> SelectedModel:
    """Choose a model honouring employee preference -> default -> fallback.

    Raises :class:`ModelUnavailableError` with an actionable message when no
    usable provider exists; the task then fails honestly instead of faking work.
    """
    if employee is not None and employee.model_id:
        try:
            adapter, record, provider = await get_adapter_for_model(db, employee.model_id)
            if not require_tools or supports_tools(record):
                return SelectedModel(adapter, record.name, provider, record, "employee preference")
            logger.info("Model %s lacks tool support, falling back", record.name)
        except ModelUnavailableError as exc:
            logger.warning("Employee model unavailable: %s", exc)

    adapter, record, provider = await default_adapter(db, user_id)
    if require_tools and not supports_tools(record):
        raise ModelUnavailableError(
            f"Model '{record.name}' does not support tool calling, which this task requires. "
            "Select a tool-capable model (for example llama3.1 or qwen2.5) in the employee settings."
        )
    return SelectedModel(adapter, record.name, provider, record, "default provider")


async def list_available_models(db: AsyncSession, user_id: str) -> list[ModelRecord]:
    rows = await db.execute(
        select(ModelRecord)
        .join(Provider, Provider.id == ModelRecord.provider_id)
        .where(Provider.user_id == user_id, Provider.enabled.is_(True), ModelRecord.available.is_(True))
        .order_by(ModelRecord.is_default.desc(), ModelRecord.display_name.asc())
    )
    return list(rows.scalars())


__all__ = ["SelectedModel", "list_available_models", "select_model", "supports_tools"]
