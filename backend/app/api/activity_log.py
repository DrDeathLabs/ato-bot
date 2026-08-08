"""Control activity log API — project-level and per-control audit trail."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_project_access, require_viewer
from app.models.orm import ControlActivityLog
from app.models.schemas import ControlActivityLogResponse

router = APIRouter(
    prefix="/projects/{project_id}/activity-log",
    tags=["activity-log"],
    dependencies=[Depends(require_project_access)],
)


@router.get("", response_model=list[ControlActivityLogResponse])
async def get_project_activity_log(
    project_id: int,
    control_id: str | None = Query(default=None, description="Filter to a single control (e.g. AC-2)"),
    control_family: str | None = Query(default=None, description="Filter by family (e.g. AC)"),
    action_type: str | None = Query(default=None, description="Filter by action type"),
    performed_by: str | None = Query(default=None, description="Filter by username"),
    since: datetime | None = Query(default=None, description="Only entries at or after this timestamp"),
    limit: int = Query(default=200, le=1000),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[ControlActivityLogResponse]:
    """
    Return the full activity log for a project, newest first.
    Optionally filter by control, family, action type, performer, or date.
    """
    q = (
        select(ControlActivityLog)
        .where(ControlActivityLog.project_id == project_id)
    )
    if control_id:
        q = q.where(ControlActivityLog.control_id == control_id.upper())
    if control_family:
        q = q.where(ControlActivityLog.control_family == control_family.upper())
    if action_type:
        q = q.where(ControlActivityLog.action_type == action_type)
    if performed_by:
        q = q.where(ControlActivityLog.performed_by == performed_by)
    if since:
        q = q.where(ControlActivityLog.performed_at >= since)

    q = q.order_by(ControlActivityLog.performed_at.desc()).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()
