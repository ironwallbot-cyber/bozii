"""ORM models. Importing this module registers every table on the metadata."""

from bozii.models.caps import Capability, CapabilityReport, ToolRegistration
from bozii.models.core import (
    AppSetting,
    AuditEvent,
    ModelRecord,
    Provider,
    RateLimitCounter,
    SessionToken,
    UsageRecord,
    User,
    new_id,
    utcnow,
)
from bozii.models.work import (
    Approval,
    Artifact,
    Employee,
    EmployeeMemory,
    SubTask,
    Task,
    TaskEvent,
    Team,
    TeamMember,
    TeamMessage,
)

__all__ = [
    "AppSetting",
    "Approval",
    "Artifact",
    "AuditEvent",
    "Capability",
    "CapabilityReport",
    "Employee",
    "EmployeeMemory",
    "ModelRecord",
    "Provider",
    "RateLimitCounter",
    "SessionToken",
    "SubTask",
    "Task",
    "TaskEvent",
    "Team",
    "TeamMember",
    "TeamMessage",
    "ToolRegistration",
    "UsageRecord",
    "User",
    "new_id",
    "utcnow",
]
