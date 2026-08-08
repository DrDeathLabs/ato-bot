"""Report generation and download."""
from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_project_assessment_access, require_viewer
from app.models.orm import Assessment, AssessmentPlan, OscalExportRun

router = APIRouter(
    prefix="/projects/{project_id}/assessments/{assessment_id}/reports",
    tags=["reports"],
    dependencies=[Depends(require_project_assessment_access)],
)


@router.get("/excel")
async def download_excel(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> FileResponse:
    assessment = await _get_finalized_assessment(assessment_id, project_id, db)
    from app.services.reports.excel_report import generate_excel
    path = await generate_excel(assessment_id)
    return FileResponse(path, filename=f"assessment_{assessment_id}_controls.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/word")
async def download_word(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> FileResponse:
    await _get_finalized_assessment(assessment_id, project_id, db)
    from app.services.reports.word_report import generate_word
    path = await generate_word(assessment_id)
    return FileResponse(path, filename=f"assessment_{assessment_id}_findings.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/pptx")
async def download_pptx(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> FileResponse:
    await _get_finalized_assessment(assessment_id, project_id, db)
    from app.services.reports.pptx_report import generate_pptx
    path = await generate_pptx(assessment_id)
    return FileResponse(path, filename=f"assessment_{assessment_id}_executive.pptx",
                        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


@router.get("/json")
async def download_json(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> FileResponse:
    await _get_finalized_assessment(assessment_id, project_id, db)
    from app.services.reports.json_report import generate_json
    path = await generate_json(assessment_id)
    return FileResponse(path, filename=f"assessment_{assessment_id}.json", media_type="application/json")


@router.get("/oscal/assessment-results")
async def download_oscal_assessment_results(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> FileResponse:
    await _get_finalized_assessment(assessment_id, project_id, db)
    from app.services.reports.oscal_assessment_results import generate_oscal_assessment_results
    from app.services.reports.oscal_validation import (
        ASSESSMENT_RESULTS_SCHEMA_SOURCE,
        OSCAL_VERSION,
        summarize_validation_errors,
        validate_assessment_results_payload,
    )

    path = await generate_oscal_assessment_results(assessment_id)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    errors = validate_assessment_results_payload(payload)
    run = OscalExportRun(
        project_id=project_id,
        assessment_id=assessment_id,
        export_kind="assessment-results",
        oscal_version=OSCAL_VERSION,
        schema_source=ASSESSMENT_RESULTS_SCHEMA_SOURCE,
        output_path=path,
        status="valid" if not errors else "invalid",
        validation_errors=errors or None,
        summary=summarize_validation_errors(errors, artifact_name="assessment-results"),
        validated_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()

    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": run.summary,
                "error_count": len(errors),
                "errors": errors[:20],
            },
        )

    return FileResponse(
        path,
        filename=f"assessment_{assessment_id}_oscal_assessment_results.json",
        media_type="application/json",
    )


@router.get("/oscal/assessment-plan")
async def download_oscal_assessment_plan(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> FileResponse:
    await _get_assessment_with_approved_plan(assessment_id, project_id, db)
    from app.services.reports.oscal_assessment_plan import generate_oscal_assessment_plan
    from app.services.reports.oscal_validation import (
        ASSESSMENT_PLAN_SCHEMA_SOURCE,
        OSCAL_VERSION,
        summarize_validation_errors,
        validate_assessment_plan_payload,
    )

    path = await generate_oscal_assessment_plan(assessment_id)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    errors = validate_assessment_plan_payload(payload)
    run = OscalExportRun(
        project_id=project_id,
        assessment_id=assessment_id,
        export_kind="assessment-plan",
        oscal_version=OSCAL_VERSION,
        schema_source=ASSESSMENT_PLAN_SCHEMA_SOURCE,
        output_path=path,
        status="valid" if not errors else "invalid",
        validation_errors=errors or None,
        summary=summarize_validation_errors(errors, artifact_name="assessment-plan"),
        validated_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()

    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": run.summary,
                "error_count": len(errors),
                "errors": errors[:20],
            },
        )

    return FileResponse(
        path,
        filename=f"assessment_{assessment_id}_oscal_assessment_plan.json",
        media_type="application/json",
    )


@router.get("/oscal/ssp")
async def download_oscal_ssp(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> FileResponse:
    await _get_finalized_assessment(assessment_id, project_id, db)
    from app.services.reports.oscal_ssp import generate_oscal_ssp
    from app.services.reports.oscal_validation import (
        OSCAL_VERSION,
        SSP_SCHEMA_SOURCE,
        summarize_validation_errors,
        validate_ssp_payload,
    )

    path = await generate_oscal_ssp(assessment_id)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    errors = validate_ssp_payload(payload)
    run = OscalExportRun(
        project_id=project_id,
        assessment_id=assessment_id,
        export_kind="ssp",
        oscal_version=OSCAL_VERSION,
        schema_source=SSP_SCHEMA_SOURCE,
        output_path=path,
        status="valid" if not errors else "invalid",
        validation_errors=errors or None,
        summary=summarize_validation_errors(errors, artifact_name="ssp"),
        validated_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()

    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": run.summary,
                "error_count": len(errors),
                "errors": errors[:20],
            },
        )

    return FileResponse(
        path,
        filename=f"assessment_{assessment_id}_oscal_ssp.json",
        media_type="application/json",
    )


@router.get("/oscal/poam")
async def download_oscal_poam(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> FileResponse:
    await _get_finalized_assessment(assessment_id, project_id, db)
    from app.services.reports.oscal_poam import generate_oscal_poam
    from app.services.reports.oscal_validation import (
        OSCAL_VERSION,
        POAM_SCHEMA_SOURCE,
        summarize_validation_errors,
        validate_poam_payload,
    )

    path = await generate_oscal_poam(assessment_id)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    errors = validate_poam_payload(payload)
    run = OscalExportRun(
        project_id=project_id,
        assessment_id=assessment_id,
        export_kind="poam",
        oscal_version=OSCAL_VERSION,
        schema_source=POAM_SCHEMA_SOURCE,
        output_path=path,
        status="valid" if not errors else "invalid",
        validation_errors=errors or None,
        summary=summarize_validation_errors(errors, artifact_name="poam"),
        validated_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()

    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": run.summary,
                "error_count": len(errors),
                "errors": errors[:20],
            },
        )

    return FileResponse(
        path,
        filename=f"assessment_{assessment_id}_oscal_poam.json",
        media_type="application/json",
    )


@router.get("/oscal/status")
async def get_oscal_export_status(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    await _get_finalized_assessment(assessment_id, project_id, db)
    rows = (
        await db.execute(
            select(OscalExportRun)
            .where(
                OscalExportRun.project_id == project_id,
                OscalExportRun.assessment_id == assessment_id,
            )
            .order_by(OscalExportRun.generated_at.desc(), OscalExportRun.id.desc())
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "export_kind": row.export_kind,
            "oscal_version": row.oscal_version,
            "status": row.status,
            "summary": row.summary,
            "schema_source": row.schema_source,
            "output_path": row.output_path,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            "validated_at": row.validated_at.isoformat() if row.validated_at else None,
            "error_count": len(row.validation_errors or []),
        }
        for row in rows
    ]


async def _get_assessment(assessment_id: int, project_id: int, db: AsyncSession) -> Assessment:
    result = await db.execute(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.project_id == project_id)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return assessment


async def _get_assessment_with_approved_plan(
    assessment_id: int, project_id: int, db: AsyncSession
) -> Assessment:
    assessment = await _get_assessment(assessment_id, project_id, db)
    plan = await db.scalar(select(AssessmentPlan).where(
        AssessmentPlan.assessment_id == assessment_id,
        AssessmentPlan.status == "approved",
    ))
    if not plan:
        raise HTTPException(status_code=409, detail="Assessment plan is not approved")
    return assessment


async def _get_finalized_assessment(assessment_id: int, project_id: int, db: AsyncSession) -> Assessment:
    assessment = await _get_assessment(assessment_id, project_id, db)
    if assessment.status != "complete":
        raise HTTPException(status_code=409, detail="Assessment execution is not complete")
    if assessment.finalization_status != "finalized":
        raise HTTPException(
            status_code=409,
            detail="Assessment is not finalized; complete human review, activities, dissent resolution, and approvals first",
        )
    return assessment
