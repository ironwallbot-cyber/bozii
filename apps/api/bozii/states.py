"""Shared constants: task lifecycle states and permission vocabulary."""

from __future__ import annotations

# Task lifecycle -----------------------------------------------------------
QUEUED = "queued"
PLANNING = "planning"
RUNNING = "running"
WAITING_APPROVAL = "waiting_approval"
RECOVERING = "recovering"
PAUSED = "paused"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

ACTIVE_STATES = {QUEUED, PLANNING, RUNNING, WAITING_APPROVAL, RECOVERING, PAUSED}
TERMINAL_STATES = {COMPLETED, FAILED, CANCELLED}
ALL_STATES = [
    QUEUED, PLANNING, RUNNING, WAITING_APPROVAL, RECOVERING, PAUSED,
    COMPLETED, FAILED, CANCELLED,
]

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    QUEUED: {PLANNING, RUNNING, WAITING_APPROVAL, RECOVERING, CANCELLED, FAILED, COMPLETED, PAUSED},
    PLANNING: {RUNNING, WAITING_APPROVAL, RECOVERING, CANCELLED, FAILED, QUEUED, PAUSED},
    RUNNING: {WAITING_APPROVAL, RECOVERING, COMPLETED, FAILED, CANCELLED, PLANNING, QUEUED, PAUSED},
    WAITING_APPROVAL: {RUNNING, RECOVERING, CANCELLED, FAILED, QUEUED, PAUSED},
    RECOVERING: {QUEUED, RUNNING, FAILED, CANCELLED, PAUSED},
    PAUSED: {QUEUED, CANCELLED, FAILED, RUNNING},
    COMPLETED: {QUEUED},      # retry creates a fresh attempt
    FAILED: {QUEUED},         # retry
    CANCELLED: {QUEUED},      # retry
}

# Employee lifecycle -------------------------------------------------------
EMPLOYEE_ACTIVE = "active"
EMPLOYEE_PAUSED = "paused"
EMPLOYEE_ARCHIVED = "archived"

# Capability lifecycle -----------------------------------------------------
CAP_DRAFT = "draft"
CAP_VALIDATING = "validating"
CAP_ACTIVE = "active"
CAP_DISABLED = "disabled"
CAP_DEPRECATED = "deprecated"
CAP_FAILED = "failed"

# Approval -----------------------------------------------------------------
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_DENIED = "denied"

# Default permission policy (least privilege) -------------------------------
DEFAULT_PERMISSIONS: dict[str, object] = {
    "fs": "workspace",        # workspace | none
    "net": "search",          # search | fetch | none
    "exec": "sandbox",        # sandbox | none
    "delegation": True,       # may create child tasks for other employees
    "capability_create": True,  # may build new tools/skills in the sandbox
    "capability_install": True,  # may install public capabilities
    "publish": False,         # may publish artifacts/capabilities externally
    "secrets": False,         # may read provider secrets (never granted by default)
}

READONLY_PERMISSIONS: dict[str, object] = {
    "fs": "workspace",
    "net": "search",
    "exec": "none",
    "delegation": False,
    "capability_create": False,
    "capability_install": False,
    "publish": False,
    "secrets": False,
}

TOOL_RISK_SAFE = "safe"
TOOL_RISK_MUTATING = "mutating"
TOOL_RISK_CONSEQUENTIAL = "consequential"

__all__ = [
    "QUEUED",
    "PLANNING",
    "RUNNING",
    "WAITING_APPROVAL",
    "RECOVERING",
    "PAUSED",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "ACTIVE_STATES",
    "TERMINAL_STATES",
    "ALL_STATES",
    "ALLOWED_TRANSITIONS",
    "EMPLOYEE_ACTIVE",
    "EMPLOYEE_PAUSED",
    "EMPLOYEE_ARCHIVED",
    "CAP_DRAFT",
    "CAP_VALIDATING",
    "CAP_ACTIVE",
    "CAP_DISABLED",
    "CAP_DEPRECATED",
    "CAP_FAILED",
    "APPROVAL_PENDING",
    "APPROVAL_APPROVED",
    "APPROVAL_DENIED",
    "DEFAULT_PERMISSIONS",
    "READONLY_PERMISSIONS",
    "TOOL_RISK_SAFE",
    "TOOL_RISK_MUTATING",
    "TOOL_RISK_CONSEQUENTIAL",
]
