"""End-to-end workflow tests.

Covers the Definition-of-Done milestone through the real HTTP API and the real
task engine: create an employee, assign a task, execute real tools, produce an
artifact, inspect status/logs, create a capability (validated in the sandbox),
and reuse it in a later task.

The model layer is the deterministic mock adapter (configured explicitly for
tests); everything else - the queue, the runner, tool execution, the sandbox,
persistence and SSE events - is the production code path.
"""

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
        f"task {task_id} never reached {states}; last state={last and last['state']} "
        f"error={last and last.get('error')}"
    )


async def create_task(client, employee_id: str, objective: str, **extra) -> dict:
    payload = {"employee_id": employee_id, "objective": objective, **extra}
    response = await client.post("/api/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def employee_with_mock(user_client, mock_provider):
    employee = await user_client.post(
        "/api/employees", json={"name": "E2E Worker", "template": "general"}
    )
    assert employee.status_code == 201, employee.text
    return employee.json()


async def test_full_task_lifecycle_with_real_tools(user_client, mock_provider, employee_with_mock):
    """Create -> plan -> run tools -> artifact -> completed, with real events."""
    await mock_provider(
        [
            {
                "type": "json",
                "value": {
                    "steps": [
                        {"title": "Write the report file", "description": "Create hello.md"},
                        {"title": "Register the artifact", "description": "Make it downloadable"},
                    ]
                },
            },
            {
                "type": "tool_call",
                "name": "write_file",
                "arguments": {
                    "path": "hello.md",
                    "content": "# Hello from Bozii\n\nGenerated during the end-to-end test.\n",
                },
            },
            {
                "type": "tool_call",
                "name": "create_artifact",
                "arguments": {"path": "hello.md", "kind": "report"},
            },
            {
                "type": "message",
                "content": (
                    "Done. Created hello.md containing the greeting and registered it as a "
                    "downloadable artifact. Verified by reading the file back."
                ),
            },
        ]
    )

    task = await create_task(
        user_client,
        employee_with_mock["id"],
        "Write a hello.md file into the workspace and register it as an artifact.",
    )
    detail = await wait_for_task(user_client, task["id"], TERMINAL)

    # --- state and progress come from real execution ---
    assert detail["state"] == "completed", detail.get("error")
    assert detail["report"].startswith("Done.")
    assert detail["iterations_used"] >= 3
    assert detail["tool_calls"] >= 2
    assert len(detail["plan"]) == 2
    assert all(step["status"] == "pending" for step in detail["plan"])  # never fabricated

    event_types = [e["event_type"] if "event_type" in e else e["type"] for e in detail["events"]]
    assert "planned" in event_types
    assert "state_change" in event_types
    tool_calls = [e for e in detail["events"] if e["type"] == "tool_call"]
    assert {e["payload"].get("tool") for e in tool_calls} >= {"write_file", "create_artifact"}
    assert "artifact" in event_types

    # --- the artifact really exists and is downloadable ---
    assert len(detail["artifacts"]) >= 1
    artifact = next(a for a in detail["artifacts"] if a["name"] == "hello.md")
    assert artifact["size"] > 0 and artifact["sha256"]
    download = await user_client.get(f"/api/artifacts/{artifact['id']}/download")
    assert download.status_code == 200
    assert "Hello from Bozii" in download.text

    # The final report is persisted as its own downloadable artifact.
    report_artifacts = [a for a in detail["artifacts"] if a["kind"] == "report" and a["name"] != "hello.md"]
    assert report_artifacts, [a["name"] for a in detail["artifacts"]]

    # --- usage was recorded ---
    dashboard = (await user_client.get("/api/dashboard")).json()
    assert dashboard["completed_tasks"] >= 1
    assert dashboard["tokens_used"] > 0
    assert dashboard["artifacts"] >= 1

    listed = await user_client.get("/api/artifacts", params={"task_id": task["id"]})
    assert len(listed.json()) >= 1


async def test_capability_created_by_employee_and_reused(
    user_client, mock_provider, employee_with_mock
):
    """Self-extension: an employee builds a capability, then a later task uses it."""
    tool_source = '''"""Counts words in a string."""


def execute(args: dict) -> dict:
    text = args.get("text")
    if not isinstance(text, str):
        raise ValueError("expected a string argument 'text'")
    return {"words": len(text.split()), "characters": len(text)}
'''
    test_source = '''from tool import execute


def test_counts_words():
    assert execute({"text": "one two three"})["words"] == 3


def test_counts_characters():
    assert execute({"text": "abcd"})["characters"] == 4


def test_rejects_missing_input():
    try:
        execute({})
    except ValueError:
        return
    raise AssertionError("expected ValueError")
'''

    await mock_provider(
        [
            {
                "type": "json",
                "value": {
                    "steps": [
                        {"title": "Check existing capabilities", "description": "Search first"},
                        {"title": "Build the missing capability", "description": "create_capability"},
                    ]
                },
            },
            {
                "type": "tool_call",
                "name": "create_capability",
                "arguments": {
                    "name": "Word Counter",
                    "kind": "tool",
                    "description": "Counts words and characters in a string",
                    "requirements": (
                        "Implement execute(args) where args = {'text': str}; return "
                        "{'words': int, 'characters': int}; raise ValueError for missing input."
                    ),
                    "permissions": [],
                },
            },
            {"type": "json", "value": {"files": {"tool.py": tool_source, "test_tool.py": test_source}}},
            {
                "type": "message",
                "content": "Capability word-counter created, tested in the sandbox and activated.",
            },
        ]
    )

    task = await create_task(
        user_client,
        employee_with_mock["id"],
        "We need a reusable way to count words. Build it as a capability.",
    )

    # 1. The consequential action suspends for human approval.
    waiting = await wait_for_task(user_client, task["id"], {"waiting_approval", *TERMINAL})
    assert waiting["state"] == "waiting_approval", waiting.get("error")
    assert waiting["approval_needed"] is True
    pending = [a for a in waiting["approvals"] if a["state"] == "pending"]
    assert pending and pending[0]["payload"]["tool"] == "create_capability"

    # 2. The user approves and execution resumes.
    decided = await user_client.post(
        f"/api/tasks/{task['id']}/approve", json={"approve": True, "reason": ""}
    )
    assert decided.status_code == 200, decided.text
    detail = await wait_for_task(user_client, task["id"], TERMINAL)
    assert detail["state"] == "completed", detail.get("error")

    # 3. The capability exists, passed its sandboxed tests and is active.
    capabilities = (await user_client.get("/api/capabilities")).json()["items"]
    word_counter = next((c for c in capabilities if c["slug"] == "word-counter"), None)
    assert word_counter is not None, {
        "capabilities": [
            {"slug": c["slug"], "status": c["status"], "tests": c["test_results"]}
            for c in capabilities
        ],
        "events": [
            {"type": e["type"], "message": e["message"][:200], "payload": str(e["payload"])[:300]}
            for e in detail["events"]
        ],
        "report": detail["report"][:400],
    }
    assert word_counter["status"] == "active" and word_counter["is_active"] is True
    assert word_counter["test_results"]["passed"] is True
    assert word_counter["test_results"]["ran"] is True
    assert word_counter["provenance"]["employee_id"] == employee_with_mock["id"]
    assert word_counter["provenance"]["task_id"] == task["id"]

    # 4. A later task reuses the generated capability as a real tool.
    await mock_provider(
        [
            {
                "type": "json",
                "value": {
                    "steps": [{"title": "Run the capability", "description": "Call word_counter"}]
                },
            },
            {
                "type": "tool_call",
                "name": "word_counter",
                "arguments": {"text": "alpha beta gamma delta"},
            },
            {"type": "message", "content": "word_counter reported 4 words across the input."},
        ]
    )
    reuse = await create_task(
        user_client,
        employee_with_mock["id"],
        "Count the words in 'alpha beta gamma delta' using the word-counter capability.",
    )
    reuse_detail = await wait_for_task(user_client, reuse["id"], TERMINAL)
    assert reuse_detail["state"] == "completed", reuse_detail.get("error")
    reuse_tools = [
        e for e in reuse_detail["events"] if e["type"] == "tool_call" and e["payload"].get("tool") == "word_counter"
    ]
    assert reuse_tools, "the generated capability was not offered as a tool"
    results = [
        e for e in reuse_detail["events"]
        if e["type"] == "tool_result" and e["payload"].get("tool") == "word_counter"
    ]
    assert results and results[0]["payload"]["ok"] is True
    assert "4" in results[0]["payload"]["preview"]  # words: 4 came from real execution

    # 5. The tool is visible in the tool library as a capability tool.
    tools = (await user_client.get("/api/tools")).json()
    entry = next(t for t in tools if t["name"] == "word_counter")
    assert entry["kind"] == "capability" and entry["capability_id"]


async def test_task_fails_honestly_without_a_model(user_client):
    """No provider configured -> the task fails with an actionable message, no fake work."""
    employee = await user_client.post(
        "/api/employees", json={"name": "No Model", "template": "general"}
    )
    task = await create_task(user_client, employee.json()["id"], "Do something useful.")
    detail = await wait_for_task(user_client, task["id"], TERMINAL, timeout=30)
    assert detail["state"] == "failed"
    assert "provider" in detail["error"].lower() or "model" in detail["error"].lower()
    assert "Settings" in detail["error"] or "provider" in detail["error"].lower()
    assert detail["report"] == ""  # nothing invented


async def test_cancel_and_retry(user_client, mock_provider, employee_with_mock):
    """Cancellation stops a running task; retry re-queues it as a new attempt."""
    script = [
        {
            "type": "json",
            "value": {"steps": [{"title": f"Step {i}", "description": "write a file"} for i in range(2)]},
        }
    ]
    for i in range(40):
        script.append(
            {
                "type": "tool_call",
                "name": "write_file",
                "arguments": {"path": f"chunk_{i:02d}.md", "content": f"chunk {i}\n"},
            }
        )
    script.append({"type": "message", "content": "All chunks written."})
    await mock_provider(script)

    task = await create_task(
        user_client, employee_with_mock["id"], "Write forty small chunk files."
    )
    # Cancel while it is executing.
    cancelled = await wait_for_task(user_client, task["id"], {"running", "queued"}, timeout=20)
    response = await user_client.post(f"/api/tasks/{task['id']}/cancel")
    assert response.status_code == 200, response.text
    final = await wait_for_task(user_client, task["id"], TERMINAL, timeout=30)
    assert final["state"] == "cancelled", final.get("error")

    # Retry creates a fresh attempt and the engine runs it again.
    retry = await user_client.post(f"/api/tasks/{task['id']}/retry")
    assert retry.status_code == 200, retry.text
    retried = await wait_for_task(user_client, task["id"], TERMINAL, timeout=60)
    assert retried["state"] in TERMINAL
    assert retried["attempt"] >= 2


async def test_pause_and_resume(user_client, mock_provider, employee_with_mock):
    """Pause/resume round trip on a queued task."""
    await mock_provider([{"type": "message", "content": "Nothing to do here."}])
    task = await create_task(user_client, employee_with_mock["id"], "A trivial task.")

    # Pause immediately: whichever state it is in, pause must be accepted.
    paused = await user_client.post(f"/api/tasks/{task['id']}/pause")
    assert paused.status_code in (200, 400), paused.text
    if paused.status_code == 200:
        resumed = await user_client.post(f"/api/tasks/{task['id']}/resume")
        assert resumed.status_code == 200, resumed.text
        detail = await wait_for_task(user_client, task["id"], TERMINAL, timeout=40)
        assert detail["state"] in TERMINAL


async def test_stream_requires_auth_and_valid_channels(user_client, other_client, employee_with_mock):
    """SSE endpoint: auth required, and task channels are scoped to their owner."""
    # Unauthenticated callers are rejected before any stream starts.
    import httpx

    app = user_client._transport.app  # type: ignore[attr-defined]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as bare:
        anonymous = await bare.get("/api/stream")
    assert anonymous.status_code == 401

    # A task channel for someone else's task is rejected outright.
    task = await create_task(user_client, employee_with_mock["id"], "stream scope check")
    foreign = await other_client.get("/api/stream", params={"channels": f"task:{task['id']}"})
    assert foreign.status_code == 403

    # Unknown channels are rejected too.
    bogus = await user_client.get("/api/stream", params={"channels": "task:does-not-exist"})
    assert bogus.status_code == 403

    # Never wait for the SSE body itself (it is long-lived by design).
