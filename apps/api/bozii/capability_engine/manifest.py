"""Capability manifest: the import/export format for tools and skills.

This JSON document is the contract for everything that shares capabilities:
the library, the versioning system, the security scanner and the sandbox
runner. See docs/tools-and-skills.md for the written specification.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MANIFEST_VERSION = 1

KNOWN_PERMISSIONS = {
    "fs_read",
    "fs_write",
    "net_search",
    "net_fetch",
    "exec",
    "delegation",
}

DEFAULT_INPUT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "required": []}


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "capability"


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(validate_default=True)

    manifest_version: int = MANIFEST_VERSION
    name: str = Field(min_length=1, max_length=160)
    slug: str = ""
    kind: Literal["tool", "skill"] = "tool"
    version: int = Field(default=1, ge=1)
    description: str = ""
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    entry: str = "tool.py"
    test_file: str = "test_tool.py"
    input_schema: dict[str, Any] = Field(default_factory=lambda: dict(DEFAULT_INPUT_SCHEMA))
    permissions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    author: str = "bozii"
    license: str = "MIT"
    min_bozii_version: str = "0.1.0"

    @field_validator("slug", mode="before")
    @classmethod
    def _auto_slug(cls, value: str, info) -> str:
        if value:
            return slugify(value)
        return slugify(str(info.data.get("name", "")))

    @field_validator("permissions")
    @classmethod
    def _known_permissions(cls, value: list[str]) -> list[str]:
        for perm in value:
            if perm not in KNOWN_PERMISSIONS:
                raise ValueError(
                    f"Unknown permission '{perm}'. Allowed: {', '.join(sorted(KNOWN_PERMISSIONS))}"
                )
        return sorted(set(value))

    @field_validator("dependencies")
    @classmethod
    def _deps(cls, value: list[str]) -> list[str]:
        for dep in value:
            if not re.match(r"^[A-Za-z0-9._-]+$", dep):
                raise ValueError(f"Invalid dependency name: {dep}")
        return value


def manifest_from_dict(data: dict[str, Any]) -> CapabilityManifest:
    return CapabilityManifest(**{k: v for k, v in data.items() if k in CapabilityManifest.model_fields})


__all__ = [
    "CapabilityManifest",
    "DEFAULT_INPUT_SCHEMA",
    "KNOWN_PERMISSIONS",
    "MANIFEST_VERSION",
    "manifest_from_dict",
    "slugify",
]
