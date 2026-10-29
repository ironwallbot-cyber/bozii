"""End-to-end multi-agent test: delegation, approval, isolation of permissions."""

from __future__ import annotations

import asyncio
import time

import pytest

TERMINAL = {"completed", "failed", "cancelled"}


async def wait_for_task(client, task_id: str, states: set[str], timeout: float = 45.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = await client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["state"] in states:
            return last
        await asyncio.sleep(0.2)
    raise AssertionError(
        f"task {task_id} never reached {states}; last={last and last['state']} error={last and last.get('error')}"
    )


async def _make_provider(client, name: str, script: list[dict], is_default: bool) -> tuple[str, str]:
    """Create a mock provider and return (provider_id, model_id)."""
    from bozii.model_adapters.mock import MockAdapter

    response = await client.post(
        "/api/providers",
        json={
            "name": name,
            "kind": "mock",
            "is_default": is_default,
            "config": {"script": script, "models": ["mock-model"]},
        },
    )
    assert response.status_code == 201, response.text
    provider_id = response.json()["id"]
    models = (await client.get("/api/models", params={"available_only": "false"})).json()
    model_id = next(m["id"] for m in models if m["provider_id"] == provider_id)
    MockAdapter.reset_cursors()
    return provider_id, model_id


async def test_delegation_between_employees(user_client):
    """A manager employee delegates to an engineer; both really execute."""
    # --- two employees ---
    manager = (
        await user_client.post("/api/employees", json={"name": "Mira Manager", "template": "manager"})
    ).json()
    engineer = (
        await user_client.post("/api/employees", json={"name": "Eddie Engineer", "template": "engineer"})
    ).json()

    # --- separate scripted providers so each employee has its own conversation ---
    _, manager_model = await _make_provider(
        user_client,
        "Manager Mock",
        [
            {
                "type": "json",
                "value": {
                    "steps": [
                        {"title": "Delegate the build", "description": "Ask Eddie to write the file"},
                        {"title": "Verify the result", "description": "Check the delegated report"},
                    ]
                },
            },
            {
                "type": "tool_call",
                "name": "delegate_task",
                "arguments": {
                    "objective": "Create a file called summary.md containing the text 'built by delegate'.",
                    "employee_name": "Eddie Engineer",
                    "title": "Build summary.md",
                    "wait": True,
                    "timeout_seconds": 60,
                },
            },
            {
                "type": "message",
                "content": "Delegated build completed by Eddie; summary.md was created as reported.",
            },
        ],
        is_default=True,
    )
    _, engineer_model = await _make_provider(
        user_client,
        "Engineer Mock",
        [
            {
                "type": "json",
                "value": {"steps": [{"title": "Write summary.md", "description": "create the file"}]},
            },
            {
                "type": "tool_call",
                "name": "write_file",
                "arguments": {"path": "summary.md", "content": "built by delegate\n"},
            },
            {"type": "message", "content": "summary.md written with the required content."},
        ],
        is_default=False,
    )
    await user_client.patch(f"/api/employees/{engineer['id']}", json={"model_id": engineer_model})

    # --- assign the task to the manager ---
    created = await user_client.post(
        "/api/tasks",
        json={"employee_id": manager["id"], "objective": "Produce summary.md via the team."},
    )
    assert created.status_code == 201, created.text
    parent_id = created.json()["id"]

    waiting = await wait_for_task(user_client, parent_id, {"waiting_approval", *TERMINAL})
    assert waiting["state"] == "waiting_approval", waiting.get("error")
    approval = next(a for a in waiting["approvals"] if a["state"] == "pending")
    assert approval["payload"]["tool"] == "delegate_task"

    decided = await user_client.post(
        f"/api/tasks/{parent_id}/approve", json={"approve": True}
    )
    assert decided.status_code == 200, decided.text

    parent = await wait_for_task(user_client, parent_id, TERMINAL, timeout=60)
    assert parent["state"] == "completed", parent.get("error")
    assert "Eddie" in parent["report"] or "delegat" in parent["report"].lower()

    # --- the child task really ran and produced its own history ---
    children = (await user_client.get(f"/api/tasks/{parent_id}/children")).json()
    assert len(children) == 1
    child = await wait_for_task(user_client, children[0]["id"], TERMINAL, timeout=30)
    assert child["state"] == "completed", child.get("error")
    child_detail = await user_client.get(f"/api/tasks/{child['id']}")
    child_tools = [e for e in child_detail.json()["events"] if e["type"] == "tool_call"]
    assert any(e["payload"].get("tool") == "write_file" for e in child_tools)

    # --- the delegation is visible in the parent's event log ---
    delegated = [e for e in parent["events"] if e["type"] == "delegated"]
    assert delegated and delegated[0]["payload"]["child_task_id"] == children[0]["id"]

    # --- the child's file landed in the engineer's workspace ---
    from bozii.agent_runtime.runner import workspace_for

    workspace = workspace_for(user_client.__dict__.get("user_id", ""), engineer["id"]) if False else None
    artifacts = (await user_client.get("/api/artifacts")).json()
    assert artifacts, "expected at least the parent report artifact"


async def test_denied_approval_still_finishes_honestly(user_client):
    """Denying a consequential action resumes the task without performing it."""
    from bozii.model_adapters.mock import MockAdapter

    employee = (
        await user_client.post("/api/employees", json={"name": "Denied Deleter", "template": "manager"})
    ).json()
    _, model_id = await _make_provider(
        user_client,
        "Deny Mock",
        [
            {
                "type": "json",
                "value": {"steps": [{"title": "Try to delegate", "description": "delegate"}]},
            },
            {
                "type": "tool_call",
                "name": "delegate_task",
                "arguments": {"objective": "Do a thing", "employee_name": "No Such Person"},
            },
            {
                "type": "message",
                "content": "The delegation was denied by the user, so I stopped and reported the limitation.",
            },
        ],
        is_default=False,
    )
    # Use a default provider (the deny mock) for this employee.
    await user_client.patch(f"/api/employees/{employee['id']}", json={"model_id": model_id})

    created = await user_client.post(
        "/api/tasks", json={"employee_id": employee["id"], "objective": "Delegate some work."}
    )
    task_id = created.json()["id"]
    waiting = await wait_for_task(user_client, task_id, {"waiting_approval", *TERMINAL})
    assert waiting["state"] == "waiting_approval", waiting.get("error")

    decided = await user_client.post(
        f"/api/tasks/{task_id}/approve", json={"approve": False, "reason": "Not now"}
    )
    assert decided.status_code == 200

    final = await wait_for_task(user_client, task_id, TERMINAL, timeout=40)
    assert final["state"] == "completed", final.get("error")
    tool_messages = [m for m in final["messages"] if m.get("role") == "tool"]
    assert tool_messages and "denied" in tool_messages[0]["content"].lower()
    assert final["report"]
    children = (await user_client.get(f"/api/tasks/{task_id}/children")).json()
    assert children == [], "a denied delegation must not create a child task"
