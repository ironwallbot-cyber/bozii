"""Capability tables: installed tools and versioned, self-authored capabilities."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bozii.db import Base
from bozii.models.core import new_id, utcnow
from bozii.states import CAP_DRAFT


class ToolRegistration(Base):
    """Per-user enable/ configuration of a registered tool (builtin or capability)."""

    __tablename__ = "tool_registrations"
    __table_args__ = (UniqueConstraint("user_id", "tool_name", name="uq_tool_user"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(120), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Capability(Base):
    """One row per capability version (import/export, rollback and provenance)."""

    __tablename__ = "capabilities"
    __table_args__ = (UniqueConstraint("slug", "version", name="uq_capability_slug_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(140), index=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(24), default="tool")  # tool | skill
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default=CAP_DRAFT, index=True)
    category: Mapped[str] = mapped_column(String(80), default="general")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    files: Mapped[dict] = mapped_column(JSON, default=dict)  # relative path -> content
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    test_results: Mapped[dict] = mapped_column(JSON, default=dict)
    scan_results: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), default="private")  # private | public
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    reports: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_by_employee_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CapabilityReport(Base):
    """User reports about broken or malicious public capabilities."""

    __tablename__ = "capability_reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    capability_id: Mapped[str] = mapped_column(String(32), ForeignKey("capabilities.id"), index=True)
    reporter_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(24), default="moderate")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


__all__ = ["ToolRegistration", "Capability", "CapabilityReport"]
