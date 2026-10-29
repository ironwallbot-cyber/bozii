"""Shared pytest fixtures.

Tests run against the real FastAPI app with a temporary SQLite database and a
temporary data directory. The task queue is the real in-process queue, so
end-to-end tests exercise actual execution.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
import uuid

# Environment must be configured before bozii.config is first imported.
_TEST_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="bozii-tests-"))
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_ROOT}/test.db")
os.environ.setdefault("DATA_DIR", str(_TEST_ROOT / "data"))
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("TASK_WORKERS", "2")
os.environ.setdefault("ENABLE_ADS", "false")
os.environ.setdefault("ALLOW_SIGNUP", "true")

import httpx  # noqa: E402
import pytest  # noqa: E402

from bozii.config import get_settings, reset_settings  # noqa: E402

reset_settings()
get_settings().ensure_dirs()


@pytest.fixture
def settings():
    reset_settings()
    return get_settings()


@pytest.fixture
async def app():
    from bozii.main import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    from bozii.security import ratelimit

    ratelimit.reset()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def user_client(client):
    """An authenticated client with a brand-new user account."""
    email = f"user-{uuid.uuid4().hex[:10]}@test.dev"
    response = await client.post(
        "/api/auth/signup",
        json={"email": email, "password": "test-password-1", "name": "Tester"},
    )
    assert response.status_code == 200, response.text
    client.user_email = email  # type: ignore[attr-defined]
    return client


@pytest.fixture
async def other_client(app):
    """A second, unrelated user with its own session cookie jar."""
    from bozii.security import ratelimit

    ratelimit.reset()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        email = f"other-{uuid.uuid4().hex[:10]}@test.dev"
        response = await c.post(
            "/api/auth/signup",
            json={"email": email, "password": "other-password-1", "name": "Other"},
        )
        assert response.status_code == 200, response.text
        yield c


@pytest.fixture
async def mock_provider(user_client):
    """Register a deterministic mock model provider and return its id."""
    from bozii.model_adapters.mock import MockAdapter

    MockAdapter.reset_cursors()
    response = await user_client.post(
        "/api/providers",
        json={
            "name": "Test Mock",
            "kind": "mock",
            "is_default": True,
            "config": {"script": [], "models": ["mock-model"]},
        },
    )
    assert response.status_code == 201, response.text
    provider_id = response.json()["id"]

    async def set_script(script: list[dict]) -> None:
        patch = await user_client.patch(
            f"/api/providers/{provider_id}", json={"config": {"script": script, "models": ["mock-model"]}}
        )
        assert patch.status_code == 200, patch.text
        MockAdapter.reset_cursors()

    set_script.provider_id = provider_id  # type: ignore[attr-defined]
    return set_script


@pytest.fixture
async def employee(user_client):
    """Create a default employee and return its payload."""
    response = await user_client.post(
        "/api/employees",
        json={"name": f"Emp {uuid.uuid4().hex[:6]}", "template": "general"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def workspace_root():
    from bozii.config import get_settings

    return get_settings().workspace_dir


def pytest_sessionfinish(session, exitstatus):  # pragma: no cover
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
