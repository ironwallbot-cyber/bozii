"""Integration tests: authentication, access boundaries, employee management."""

from __future__ import annotations

import pytest


async def test_setup_status_and_first_user(client, app):
    status = await client.get("/api/auth/setup-status")
    assert status.status_code == 200
    body = status.json()
    assert set(body) >= {"needs_setup", "allow_signup", "app_name"}


async def test_signup_login_logout_me(client):
    email = "flow@test.dev"
    signup = await client.post(
        "/api/auth/signup", json={"email": email, "password": "long-enough-pw", "name": "Flow"}
    )
    assert signup.status_code == 200, signup.text

    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == email

    # Duplicate signup is rejected.
    dup = await client.post(
        "/api/auth/signup", json={"email": email, "password": "long-enough-pw", "name": "Flow"}
    )
    assert dup.status_code == 409

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 401

    login = await client.post("/api/auth/login", json={"email": email, "password": "long-enough-pw"})
    assert login.status_code == 200, login.text
    assert (await client.get("/api/auth/me")).status_code == 200

    bad = await client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
    assert bad.status_code == 401


async def test_requires_authentication(client):
    for path in ("/api/employees", "/api/tasks", "/api/dashboard", "/api/tools", "/api/capabilities"):
        response = await client.get(path)
        assert response.status_code == 401, f"{path} should require auth"


async def test_employee_crud_and_templates(user_client):
    templates = await user_client.get("/api/employees/templates")
    assert templates.status_code == 200
    keys = {t["key"] for t in templates.json()}
    assert {"general", "engineer", "researcher", "analyst", "designer", "qa", "writer", "manager", "security"} <= keys

    created = await user_client.post(
        "/api/employees", json={"name": "Ada", "template": "engineer"}
    )
    assert created.status_code == 201, created.text
    employee = created.json()
    assert employee["role"] == "Software Engineer"
    assert employee["permissions"]["exec"] == "sandbox"
    assert employee["slug"]

    listed = await user_client.get("/api/employees")
    assert any(e["id"] == employee["id"] for e in listed.json())

    patched = await user_client.patch(
        f"/api/employees/{employee['id']}",
        json={"description": "Handles backend work", "max_iterations": 5},
    )
    assert patched.status_code == 200
    assert patched.json()["description"] == "Handles backend work"
    assert patched.json()["max_iterations"] == 5

    fetched = await user_client.get(f"/api/employees/{employee['id']}")
    assert fetched.json()["system_prompt"].strip()

    deleted = await user_client.delete(f"/api/employees/{employee['id']}")
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True


async def test_employee_access_boundaries(user_client, other_client):
    created = await user_client.post("/api/employees", json={"name": "Private", "template": "general"})
    employee_id = created.json()["id"]

    # A different user must not see or edit it.
    assert (await other_client.get(f"/api/employees/{employee_id}")).status_code == 404
    assert (await other_client.patch(f"/api/employees/{employee_id}", json={"name": "Hacked"})).status_code == 404
    assert (await other_client.delete(f"/api/employees/{employee_id}")).status_code == 404
    assert all(e["id"] != employee_id for e in (await other_client.get("/api/employees")).json())


async def test_memory_crud_and_credential_refusal(user_client):
    created = await user_client.post("/api/employees", json={"name": "Memory User", "template": "general"})
    employee_id = created.json()["id"]

    stored = await user_client.post(
        f"/api/employees/{employee_id}/memory",
        json={"kind": "preference", "key": "report format", "content": "Markdown with tables"},
    )
    assert stored.status_code == 201, stored.text

    listed = await user_client.get(f"/api/employees/{employee_id}/memory")
    assert len(listed.json()) == 1

    refused = await user_client.post(
        f"/api/employees/{employee_id}/memory",
        json={"key": "api key", "content": "sk-12345"},
    )
    assert refused.status_code == 400

    deleted = await user_client.delete(
        f"/api/employees/{employee_id}/memory/{listed.json()[0]['id']}"
    )
    assert deleted.status_code == 200
    assert (await user_client.get(f"/api/employees/{employee_id}/memory")).json() == []


async def test_dashboard_reports_real_counts(user_client):
    before = (await user_client.get("/api/dashboard")).json()
    await user_client.post("/api/employees", json={"name": "Counted", "template": "general"})
    after = (await user_client.get("/api/dashboard")).json()
    assert after["employees"] == before["employees"] + 1
    assert after["tools"] > 10
    assert isinstance(after["tokens_used"], int)


async def test_settings_and_ads_are_disabled_by_default(user_client):
    settings = (await user_client.get("/api/settings")).json()
    assert settings["enable_ads"] is False
    assert settings["sandbox"]["notes"]
    ads = (await user_client.get("/api/ads")).json()
    assert ads["enabled"] is False and ads["html"] == ""

    updated = await user_client.patch("/api/settings", json={"allow_signup": False})
    assert updated.status_code == 200 and updated.json()["allow_signup"] is False
    await user_client.patch("/api/settings", json={"allow_signup": True})
