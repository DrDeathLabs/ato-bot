"""System knowledge and generated-package validation APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_access, require_viewer
from app.models.orm import (
    ArtifactValidationRun,
    PackageViabilityRun,
    Project,
)
from app.services.system_knowledge import (
    extract_system_knowledge,
    get_latest_system_knowledge,
    get_project_provider_responsibilities,
    review_system_assertion,
    review_provider_responsibility,
    suggest_provider_responsibilities,
)

router = APIRouter(
    prefix="/projects/{project_id}/system-knowledge",
    tags=["system-knowledge"],
    dependencies=[Depends(require_project_access)],
)


class AssertionReviewRequest(BaseModel):
    status: str


class KnowledgeExtractionRequest(BaseModel):
    source_mode: str = "manual_review"
    source_run_id: int = 0


class ResponsibilityReviewRequest(BaseModel):
    status: str


class ResponsibilitySuggestionRequest(BaseModel):
    provider_id: int | None = None


async def _get_project_or_404(project_id: int, db: AsyncSession) -> None:
    project = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("")
async def latest_knowledge(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await get_latest_system_knowledge(project_id, db)


@router.post("/extract")
async def run_extraction(
    project_id: int,
    payload: KnowledgeExtractionRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    summary = await extract_system_knowledge(
        db,
        project_id=project_id,
        source_mode=payload.source_mode,
        source_run_id=payload.source_run_id,
    )
    latest = await get_latest_system_knowledge(project_id, db)
    return {
        "summary": summary,
        "knowledge": latest,
    }


@router.patch("/assertions/{assertion_id}")
async def review_assertion(
    project_id: int,
    assertion_id: int,
    payload: AssertionReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    result = await review_system_assertion(
        db,
        project_id=project_id,
        assertion_id=assertion_id,
        status=payload.status,
        reviewer_id=current_user["id"],
    )
    if not result:
        raise HTTPException(status_code=404, detail="Assertion not found")
    return result


@router.get("/inheritance")
async def get_inheritance(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await get_project_provider_responsibilities(project_id, db)


@router.post("/inheritance/suggest")
async def suggest_inheritance(
    project_id: int,
    payload: ResponsibilitySuggestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    return await suggest_provider_responsibilities(
        db,
        project_id=project_id,
        reviewer_id=current_user["id"],
        provider_id=payload.provider_id,
    )


@router.patch("/inheritance/{responsibility_id}")
async def review_inheritance(
    project_id: int,
    responsibility_id: int,
    payload: ResponsibilityReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    result = await review_provider_responsibility(
        db,
        project_id=project_id,
        responsibility_id=responsibility_id,
        status=payload.status,
        reviewer_id=current_user["id"],
    )
    if not result:
        raise HTTPException(status_code=404, detail="Responsibility mapping not found")
    return result


@router.get("/validation")
async def latest_validation(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    validation_run = (
        await db.execute(
            select(ArtifactValidationRun)
            .where(ArtifactValidationRun.project_id == project_id)
            .order_by(ArtifactValidationRun.id.desc())
            .limit(1)
        )
    ).scalars().first()
    viability_run = (
        await db.execute(
            select(PackageViabilityRun)
            .where(PackageViabilityRun.project_id == project_id)
            .order_by(PackageViabilityRun.id.desc())
            .limit(1)
        )
    ).scalars().first()
    return {
        "validation_run": None
        if not validation_run
        else {
            "id": validation_run.id,
            "source_mode": validation_run.source_mode,
            "source_run_id": validation_run.source_run_id,
            "status": validation_run.status,
            "summary": validation_run.summary_json or {},
            "created_at": validation_run.created_at.isoformat() if validation_run.created_at else None,
        },
        "package_viability": None
        if not viability_run
        else {
            "id": viability_run.id,
            "source_mode": viability_run.source_mode,
            "source_run_id": viability_run.source_run_id,
            "status": viability_run.status,
            "viability_score": viability_run.viability_score,
            "summary": viability_run.summary_json or {},
            "created_at": viability_run.created_at.isoformat() if viability_run.created_at else None,
        },
    }
