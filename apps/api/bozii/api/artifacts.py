"""Artifact routes: list and download generated deliverables."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from sqlalchemy import select

from bozii.api.deps import CurrentUser, DbSession, not_found
from bozii.config import get_settings
from bozii.models import Artifact, Employee, Task
from bozii.schemas import ArtifactOut
from bozii.security.audit import audit

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("", response_model=list[ArtifactOut])
async def list_artifacts(
    user: CurrentUser,
    db: DbSession,
    task_id: str = Query(""),
    employee_id: str = Query(""),
    kind: str = Query(""),
    limit: int = Query(200, le=500),
) -> list[ArtifactOut]:
    stmt = select(Artifact).where(Artifact.user_id == user.id)
    if task_id:
        stmt = stmt.where(Artifact.task_id == task_id)
    if employee_id:
        stmt = stmt.where(Artifact.employee_id == employee_id)
    if kind:
        stmt = stmt.where(Artifact.kind == kind)
    rows = (await db.execute(stmt.order_by(Artifact.created_at.desc()).limit(limit))).scalars()
    return [ArtifactOut.model_validate(a) for a in rows]


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: str, user: CurrentUser, db: DbSession) -> FileResponse:
    artifact = await db.get(Artifact, artifact_id)
    if artifact is None or artifact.user_id != user.id:
        raise not_found("Artifact")
    # Locate the owning employee's workspace where the file was written.
    workspace = get_settings().workspace_dir / user.id
    path: Path | None = None
    if artifact.employee_id:
        candidate = workspace / artifact.employee_id / artifact.relative_path
        if candidate.exists():
            path = candidate
    if path is None:
        for employee_dir in workspace.glob("*") if workspace.exists() else []:
            candidate = employee_dir / artifact.relative_path
            if candidate.exists():
                path = candidate
                break
    if path is None:
        raise not_found("Artifact file (it may have been removed from the workspace)")
    return FileResponse(path, filename=artifact.name, media_type=artifact.mime_type)


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str, user: CurrentUser, db: DbSession) -> dict:
    artifact = await db.get(Artifact, artifact_id)
    if artifact is None or artifact.user_id != user.id:
        raise not_found("Artifact")
    await db.delete(artifact)
    await audit(
        db, action="artifact.deleted", actor=f"user:{user.id}", user_id=user.id,
        resource_type="artifact", resource_id=artifact_id,
    )
    await db.commit()
    return {"deleted": True}


__all__ = ["router"]
