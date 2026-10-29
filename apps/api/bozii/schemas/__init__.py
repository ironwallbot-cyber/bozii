"""Pydantic request/response schemas for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------- auth
class SetupRequest(BaseModel):
    email: EmailStr
    name: str = ""
    password: str = Field(min_length=8, max_length=128)


class SignupRequest(SetupRequest):
    pass


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: str
    email: str
    name: str
    role: str
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserOut
    mfa_required: bool = False


class ErrorOut(BaseModel):
    error: str
    detail: Any = None
    code: str = "error"


# ----------------------------------------------------------------- employees
class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    template: str | None = None
    role: str = ""
    description: str = ""
    system_prompt: str = ""
    model_id: str | None = None
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    permissions: dict[str, Any] | None = None
    memory_enabled: bool = True
    max_iterations: int = Field(default=12, ge=1, le=100)
    timeout_seconds: int = Field(default=600, ge=30, le=7200)


class EmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    model_id: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    permissions: dict[str, Any] | None = None
    tools_allowlist: list[str] | None = None
    tools_denylist: list[str] | None = None
    status: Literal["active", "paused", "archived"] | None = None
    memory_enabled: bool | None = None
    max_iterations: int | None = Field(default=None, ge=1, le=100)
    timeout_seconds: int | None = Field(default=None, ge=30, le=7200)


class EmployeeOut(ORMModel):
    id: str
    name: str
    slug: str
    role: str
    description: str
    system_prompt: str
    template_key: str | None
    avatar_seed: str
    avatar_color: str
    model_id: str | None
    model_name: str
    temperature: float
    status: str
    memory_enabled: bool
    permissions: dict
    tools_allowlist: list
    tools_denylist: list
    max_iterations: int
    timeout_seconds: int
    created_at: datetime
    updated_at: datetime
    last_active_at: datetime | None
    active_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0


class MemoryOut(ORMModel):
    id: str
    employee_id: str
    kind: str
    key: str
    content: str
    pinned: bool
    source_task_id: str | None
    created_at: datetime
    updated_at: datetime


class MemoryCreate(BaseModel):
    kind: str = "fact"
    key: str = ""
    content: str = Field(min_length=1)
    pinned: bool = False


# -------------------------------------------------------------------- tasks
class TaskCreate(BaseModel):
    employee_id: str
    objective: str = Field(min_length=1, max_length=20000)
    title: str = ""
    team_id: str | None = None
    priority: int = Field(default=5, ge=1, le=9)
    input: dict[str, Any] = Field(default_factory=dict)
    plan_enabled: bool | None = None
    max_iterations: int | None = Field(default=None, ge=1, le=100)
    timeout_seconds: int | None = Field(default=None, ge=30, le=7200)


class SubTaskOut(ORMModel):
    id: str
    title: str
    description: str
    status: str
    order_index: int
    assignee_employee_id: str | None
    output: str
    created_at: datetime


class TaskEventOut(ORMModel):
    id: str
    task_id: str
    seq: int
    type: str
    message: str
    payload: dict
    created_at: datetime


class ApprovalOut(ORMModel):
    id: str
    task_id: str
    employee_id: str | None
    kind: str
    title: str
    description: str
    payload: dict
    state: str
    reason: str | None
    created_at: datetime
    decided_at: datetime | None


class ApprovalDecision(BaseModel):
    approve: bool
    reason: str = ""


class TaskOut(ORMModel):
    id: str
    user_id: str
    employee_id: str
    team_id: str | None
    parent_task_id: str | None
    title: str
    objective: str
    state: str
    priority: int
    plan: list
    result: dict
    report: str
    error: str | None
    approval_needed: bool
    attempt: int
    max_iterations: int
    iterations_used: int
    tool_calls: int
    delegation_depth: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class TaskDetailOut(TaskOut):
    subtasks: list[SubTaskOut] = []
    events: list[TaskEventOut] = []
    approvals: list[ApprovalOut] = []
    artifacts: list["ArtifactOut"] = []
    employee_name: str = ""
    messages: list = []


class TaskActionOut(BaseModel):
    ok: bool
    state: str
    detail: str = ""


# ---------------------------------------------------------------- artifacts
class ArtifactOut(ORMModel):
    id: str
    user_id: str
    task_id: str | None
    employee_id: str | None
    name: str
    kind: str
    relative_path: str
    mime_type: str
    size: int
    sha256: str
    created_at: datetime


# -------------------------------------------------------------------- tools
class ToolOut(BaseModel):
    name: str
    title: str
    description: str
    category: str
    kind: str  # builtin | capability
    risk: str
    required_permissions: dict
    parameters: dict
    enabled: bool = True
    version: str = "1.0.0"
    capability_id: str | None = None


class ToolToggle(BaseModel):
    enabled: bool


# -------------------------------------------------------------- capabilities
class CapabilityOut(ORMModel):
    id: str
    slug: str
    name: str
    kind: str
    version: int
    status: str
    category: str
    description: str
    tags: list
    manifest: dict
    input_schema: dict
    permissions: list
    dependencies: list
    test_results: dict
    scan_results: dict
    provenance: dict
    checksum: str
    is_active: bool
    visibility: str
    downloads: int
    reports: int
    created_by_employee_id: str | None
    source_task_id: str | None
    created_at: datetime
    activated_at: datetime | None


class CapabilityCreateManual(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["tool", "skill"] = "tool"
    description: str = ""
    category: str = "general"
    permissions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)  # path -> content
    activate: bool = True
    visibility: Literal["private", "public"] = "private"


class CapabilityVisibility(BaseModel):
    visibility: Literal["private", "public"]


class CapabilityReportIn(BaseModel):
    reason: str = Field(min_length=3)
    severity: Literal["minor", "moderate", "severe"] = "moderate"


class InstallCapability(BaseModel):
    activate: bool = True


# -------------------------------------------------------------------- teams
class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    objective: str = ""
    lead_employee_id: str | None = None
    member_ids: list[str] = Field(default_factory=list)


class TeamUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    objective: str | None = None
    lead_employee_id: str | None = None


class TeamMemberOut(ORMModel):
    id: str
    team_id: str
    employee_id: str
    role: str
    created_at: datetime
    employee_name: str = ""


class TeamOut(ORMModel):
    id: str
    name: str
    description: str
    objective: str
    lead_employee_id: str | None
    created_at: datetime
    members: list[TeamMemberOut] = []
    task_count: int = 0


class TeamMessageIn(BaseModel):
    content: str = Field(min_length=1)
    to_employee_id: str | None = None
    task_id: str | None = None


class TeamMessageOut(ORMModel):
    id: str
    team_id: str | None
    from_employee_id: str | None
    to_employee_id: str | None
    task_id: str | None
    content: str
    kind: str
    created_at: datetime


# ---------------------------------------------------------------- providers
class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["ollama", "openai_compat", "mock"]
    base_url: str = ""
    api_key_env: str = ""
    api_key: str = ""
    config: dict = Field(default_factory=dict)
    is_default: bool = False


class ProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class ProviderOut(ORMModel):
    id: str
    name: str
    kind: str
    base_url: str
    api_key_env: str
    enabled: bool
    is_default: bool
    config: dict
    created_at: datetime
    last_health_at: datetime | None
    last_health_ok: bool | None
    last_health_error: str | None
    has_api_key: bool = False
    models: list["ModelOut"] = []


class ModelOut(ORMModel):
    id: str
    provider_id: str
    name: str
    display_name: str
    context_window: int | None
    capabilities: list
    available: bool
    is_default: bool
    discovered_at: datetime


# ------------------------------------------------------------------ settings
class DashboardStats(BaseModel):
    employees: int
    active_tasks: int
    queued_tasks: int
    completed_tasks: int
    failed_tasks: int
    cancelled_tasks: int
    waiting_approval: int
    artifacts: int
    capabilities: int
    public_capabilities: int
    tools: int
    providers_ok: int
    providers_total: int
    tokens_used: int
    tasks_last_7d: int


class ActivityOut(BaseModel):
    id: str
    source: str  # audit | task_event
    actor: str
    action: str
    message: str
    resource_type: str
    resource_id: str
    detail: dict
    created_at: datetime


class SettingsOut(BaseModel):
    app_name: str
    environment: str
    allow_signup: bool
    enable_ads: bool
    ads_configured: bool
    ads_placement: str
    ads_provider: str
    task_workers: int
    max_iterations: int
    task_timeout_seconds: int
    sandbox: dict
    version: str
    needs_setup: bool


class SettingsUpdate(BaseModel):
    allow_signup: bool | None = None
    enable_ads: bool | None = None
    ads_provider: str | None = None
    ads_slot_id: str | None = None
    ads_placement: str | None = None
    task_workers: int | None = Field(default=None, ge=1, le=16)


class AdsOut(BaseModel):
    enabled: bool
    placement: str
    provider: str
    label: str = "Sponsored"
    html: str = ""


__all__ = [name for name in dir() if not name.startswith("_")]
