"""Knowledge-backed SSP composition APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_project_access, require_viewer
from app.models.orm import Project
from app.services.ssp_composer import compose_ssp_sections
from app.services.system_knowledge import get_latest_system_knowledge

router = APIRouter(
    prefix="/projects/{project_id}/ssp",
    tags=["ssp"],
    dependencies=[Depends(require_project_access)],
)


class ComposeSectionRequest(BaseModel):
    section_key: str


async def _get_project_or_404(project_id: int, db: AsyncSession) -> None:
    project = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/knowledge-sources")
async def knowledge_sources(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await get_latest_system_knowledge(project_id, db)


@router.post("/compose")
async def compose_ssp(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    try:
        return await compose_ssp_sections(db, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/export")
async def export_ssp(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    try:
        return await compose_ssp_sections(db, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/compose-section")
async def compose_one_section(
    project_id: int,
    payload: ComposeSectionRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    try:
        return await compose_ssp_sections(db, project_id=project_id, section_key=payload.section_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
