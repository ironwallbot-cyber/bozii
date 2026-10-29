"""Register every builtin tool with the registry."""

from __future__ import annotations

from bozii.tool_registry.builtins import (
    artifacts,
    capabilities,
    data,
    delegation,
    dev,
    files,
    memory,
    utility,
    web,
)
from bozii.tool_registry.registry import ToolRegistry

BUILTIN_MODULES = [files, dev, web, data, utility, artifacts, delegation, capabilities, memory]


def install_builtin_tools(registry: ToolRegistry) -> int:
    count = 0
    for module in BUILTIN_MODULES:
        for tool in module.TOOLS:
            registry.register(tool)
            count += 1
    return count


def builtin_tools():
    for module in BUILTIN_MODULES:
        yield from module.TOOLS


__all__ = ["BUILTIN_MODULES", "builtin_tools", "install_builtin_tools"]
