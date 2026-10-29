"""Unit tests: capability manifest, security scanner, dependency policy."""

from __future__ import annotations

import pytest

from bozii.capability_engine.codegen import (
    CapabilityGenerationError,
    extract_json_bundle,
    sanitise_files,
)
from bozii.capability_engine.manifest import CapabilityManifest, slugify
from bozii.capability_engine.scanner import check_dependencies, scan_capability

GOOD_TOOL = '''"""Example capability."""
import json


def execute(args: dict) -> dict:
    text = args.get("text")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return {"words": len(text.split()), "json": json.dumps({"ok": True})}
'''

GOOD_TEST = '''
from tool import execute


def test_execute_counts_words():
    assert execute({"text": "one two three"})["words"] == 3


def test_execute_requires_text():
    try:
        execute({})
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_execute_empty():
    assert execute({"text": ""})["words"] == 0
'''


def test_slugify():
    assert slugify("Weather Lookup!") == "weather-lookup"
    assert slugify("  Multiple   Spaces ") == "multiple-spaces"
    assert slugify("") == "capability"


def test_manifest_autoslug_and_permission_validation():
    manifest = CapabilityManifest(name="Weather Lookup", permissions=["net_fetch", "fs_read"])
    assert manifest.slug == "weather-lookup"
    assert manifest.permissions == ["fs_read", "net_fetch"]
    with pytest.raises(Exception):
        CapabilityManifest(name="x", permissions=["root_access"])
    with pytest.raises(Exception):
        CapabilityManifest(name="x", dependencies=["bad name; rm -rf"])


def test_scanner_allows_clean_tool():
    manifest = CapabilityManifest(name="word counter", permissions=[])
    report = scan_capability(manifest, {"tool.py": GOOD_TOOL, "test_tool.py": GOOD_TEST})
    assert report.passed, report.as_dict()


def test_scanner_blocks_dangerous_calls():
    manifest = CapabilityManifest(name="bad", permissions=[])
    files = {"tool.py": "def execute(args):\n    return eval(args.get('x'))\n", "test_tool.py": "def test_x():\n    assert True"}
    report = scan_capability(manifest, files)
    assert not report.passed
    rules = {f.rule for f in report.findings if f.level == "block"}
    assert "dangerous_call" in rules


def test_scanner_requires_declared_permissions():
    manifest = CapabilityManifest(name="net tool", permissions=[])
    files = {
        "tool.py": "import socket\n\ndef execute(args):\n    return {'ok': True}\n",
        "test_tool.py": "def test_x():\n    assert True",
    }
    report = scan_capability(manifest, files)
    assert not report.passed
    assert any(f.rule == "undeclared_permission" for f in report.findings)

    allowed = CapabilityManifest(name="net tool", permissions=["net_fetch"])
    assert scan_capability(allowed, files).passed


def test_scanner_blocks_secret_access_and_syntax_errors():
    manifest = CapabilityManifest(name="x", permissions=[])
    report = scan_capability(
        manifest,
        {"tool.py": "import os\ndef execute(a):\n    return os.environ\n", "test_tool.py": "def test_a():\n    assert 1"},
    )
    assert not report.passed
    assert any(f.rule == "secret_access" for f in report.findings)

    broken = scan_capability(manifest, {"tool.py": "def execute(:\n  pass", "test_tool.py": "def test_a():\n    assert 1"})
    assert not broken.passed
    assert any(f.rule == "syntax_error" for f in broken.findings)


def test_dependency_allowlist():
    manifest = CapabilityManifest(name="x", dependencies=["requests"])
    errors = check_dependencies(manifest, [])
    assert errors and "requests" in errors[0]
    assert check_dependencies(manifest, ["requests"]) == []


def test_json_bundle_extraction():
    payload = {"files": {"tool.py": "def execute(a):\n    return a"}}
    fenced = f"Sure!\n```json\n{__import__('json').dumps(payload)}\n```"
    assert extract_json_bundle(fenced)["files"].keys() == payload["files"].keys()
    assert extract_json_bundle(__import__("json").dumps(payload))["files"]
    with pytest.raises(CapabilityGenerationError):
        extract_json_bundle("I could not do it.")
    with pytest.raises(CapabilityGenerationError):
        sanitise_files({"../../etc/passwd": "x"})
