"""Artifact generation endpoints — CP, IRP, SAR."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_assessment_access
from app.models.orm import Assessment, ControlFinding, Project
from app.services.evidence_view import build_system_context_from_evidence

router = APIRouter(
    prefix="/projects/{project_id}/assessments/{assessment_id}/artifacts",
    tags=["artifacts"],
    dependencies=[Depends(require_project_assessment_access)],
)


async def _load_assessment(assessment_id: int, project_id: int, db: AsyncSession) -> Assessment:
    result = await db.execute(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.project_id == project_id)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.status != "complete":
        raise HTTPException(status_code=400, detail="Assessment not yet complete")
    return assessment


@router.get("/contingency-plan")
async def generate_cp(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> FileResponse:
    assessment = await _load_assessment(assessment_id, project_id, db)
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one()

    findings_result = await db.execute(
        select(ControlFinding).where(
            ControlFinding.assessment_id == assessment_id,
            ControlFinding.control_family == "CP",
        )
    )
    cp_findings = [
        {"control_id": f.control_id, "status": f.status, "gaps": f.gaps, "remediation_plan": f.remediation_plan}
        for f in findings_result.scalars().all()
    ]

    system_context = await _get_system_context(project_id, db)

    from app.services.artifact_generator.contingency_plan import generate_contingency_plan
    path = await generate_contingency_plan(project.name, system_context, cp_findings, assessment_id)
    return FileResponse(path, filename=f"contingency_plan_{project_id}.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/incident-response-plan")
async def generate_irp(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> FileResponse:
    assessment = await _load_assessment(assessment_id, project_id, db)
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one()

    findings_result = await db.execute(
        select(ControlFinding).where(
            ControlFinding.assessment_id == assessment_id,
            ControlFinding.control_family == "IR",
        )
    )
    ir_findings = [
        {"control_id": f.control_id, "status": f.status, "gaps": f.gaps}
        for f in findings_result.scalars().all()
    ]
    system_context = await _get_system_context(project_id, db)

    from app.services.artifact_generator.incident_response import generate_incident_response_plan
    path = await generate_incident_response_plan(project.name, system_context, ir_findings, assessment_id)
    return FileResponse(path, filename=f"incident_response_plan_{project_id}.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/sar")
async def generate_sar_endpoint(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> FileResponse:
    assessment = await _load_assessment(assessment_id, project_id, db)
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one()

    findings_result = await db.execute(
        select(ControlFinding)
        .where(ControlFinding.assessment_id == assessment_id)
        .order_by(ControlFinding.control_family, ControlFinding.control_id)
    )
    findings = findings_result.scalars().all()

    from app.services.artifact_generator.sar import generate_sar
    path = await generate_sar(project.name, project.impact_baseline, findings, assessment_id)
    return FileResponse(path, filename=f"sar_{assessment_id}.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


async def _get_system_context(project_id: int, db: AsyncSession) -> str:
    return await build_system_context_from_evidence(project_id, db, max_chars=3000)
