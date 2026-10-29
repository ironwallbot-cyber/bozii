"""Integration tests: capability library API and database migrations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2]

GOOD_TOOL = '''"""Word statistics capability."""


def execute(args: dict) -> dict:
    text = args.get("text")
    if not isinstance(text, str):
        raise ValueError("expected a string 'text' argument")
    words = text.split()
    return {"words": len(words), "characters": len(text)}
'''

GOOD_TEST = '''from tool import execute


def test_word_count():
    assert execute({"text": "one two three"})["words"] == 3


def test_characters():
    assert execute({"text": "abcd"})["characters"] == 4


def test_invalid_input():
    try:
        execute({})
    except ValueError:
        return
    raise AssertionError("expected ValueError")
'''

BAD_TOOL = "def execute(args):\n    return eval(args.get('code'))\n"
FAILING_TEST = "from tool import execute\n\ndef test_fails():\n    assert execute({'text': 'a'})['words'] == 99\n"


async def test_capability_lifecycle(user_client):
    created = await user_client.post(
        "/api/capabilities",
        json={
            "name": "Word Stats",
            "kind": "tool",
            "description": "Counts words in text",
            "category": "data",
            "permissions": [],
            "files": {"tool.py": GOOD_TOOL, "test_tool.py": GOOD_TEST},
            "activate": True,
        },
    )
    assert created.status_code == 201, created.text
    cap = created.json()
    assert cap["slug"] == "word-stats"
    assert cap["status"] == "active" and cap["is_active"] is True
    assert cap["test_results"]["passed"] is True
    assert cap["scan_results"]["passed"] is True

    # Second version supersedes the first.
    v2 = await user_client.post(
        "/api/capabilities",
        json={
            "name": "Word Stats",
            "kind": "tool",
            "description": "Counts words (v2)",
            "files": {"tool.py": GOOD_TOOL + "\n# v2\n", "test_tool.py": GOOD_TEST},
        },
    )
    assert v2.status_code == 201, v2.text
    assert v2.json()["version"] == 2

    listed = (await user_client.get("/api/capabilities")).json()["items"]
    versions = {item["version"]: item["is_active"] for item in listed if item["slug"] == "word-stats"}
    assert versions[2] is True and versions[1] is False

    # Rollback to v1.
    v1_id = next(i["id"] for i in listed if i["slug"] == "word-stats" and i["version"] == 1)
    activated = await user_client.post(f"/api/capabilities/{v1_id}/activate")
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True

    # Export / import round-trip.
    bundle = (await user_client.get(f"/api/capabilities/{v1_id}/export")).json()
    assert bundle["format"] == "bozii-capability"
    assert "tool.py" in bundle["files"]
    imported = await user_client.post("/api/capabilities/import", json={"bundle": bundle})
    assert imported.status_code == 201, imported.text
    assert imported.json()["ok"] is True

    # Disable and delete.
    active_id = next(i["id"] for i in listed if i["slug"] == "word-stats" and i["version"] == 2)
    disabled = await user_client.post(f"/api/capabilities/{active_id}/disable")
    assert disabled.json()["status"] == "disabled" and disabled.json()["is_active"] is False

    deleted = await user_client.delete(f"/api/capabilities/{active_id}")
    assert deleted.status_code == 200


async def test_capability_validation_rejects_dangerous_code(user_client):
    response = await user_client.post(
        "/api/capabilities",
        json={
            "name": "Evil",
            "kind": "tool",
            "description": "bad",
            "files": {"tool.py": BAD_TOOL, "test_tool.py": "def test_x():\n    assert True"},
        },
    )
    assert response.status_code == 422
    detail = " ".join(str(d) for d in response.json()["detail"])
    assert "eval" in detail or "dangerous" in detail.lower() or "not permitted" in detail


async def test_capability_validation_rejects_failing_tests(user_client):
    response = await user_client.post(
        "/api/capabilities",
        json={
            "name": "Failing",
            "kind": "tool",
            "description": "fails",
            "files": {"tool.py": GOOD_TOOL, "test_tool.py": FAILING_TEST},
        },
    )
    assert response.status_code == 422
    assert "test" in " ".join(str(d) for d in response.json()["detail"]).lower()


async def test_capability_public_visibility_and_reporting(user_client):
    created = await user_client.post(
        "/api/capabilities",
        json={
            "name": "Shareable",
            "kind": "tool",
            "description": "shared",
            "files": {"tool.py": GOOD_TOOL, "test_tool.py": GOOD_TEST},
        },
    )
    cap_id = created.json()["id"]
    published = await user_client.post(
        f"/api/capabilities/{cap_id}/publish", json={"visibility": "public"}
    )
    assert published.status_code == 200
    assert published.json()["visibility"] == "public"

    report = await user_client.post(
        f"/api/capabilities/{cap_id}/report",
        json={"reason": "does not work as documented", "severity": "moderate"},
    )
    assert report.status_code == 200 and report.json()["reports"] == 1


@pytest.mark.skipif(sys.platform == "win32", reason="alembic test is POSIX")
async def test_migrations_upgrade_and_no_drift(tmp_path):
    db_path = tmp_path / "migration.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "PYTHONPATH": str(API_ROOT),
    }
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=180,
    )
    assert upgrade.returncode == 0, upgrade.stderr + upgrade.stdout
    assert db_path.exists()

    drift = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert drift.returncode == 0, drift.stderr + drift.stdout
