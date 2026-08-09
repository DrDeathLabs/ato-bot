"""Remediation Reports API — post-assessment gap closure generation."""
from __future__ import annotations

import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pathlib import Path

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_assessment_access, require_viewer
from app.models.orm import Assessment, ControlFinding, Document, RemediationReport
from app.services.package_generation import build_benchmark_result

router = APIRouter(
    prefix="/projects/{project_id}/assessments/{assessment_id}/remediation",
    tags=["remediation"],
    dependencies=[Depends(require_project_assessment_access)],
)


class ArtifactGenerationRequest(BaseModel):
    package_style: str = "standard"


class TestDatasetGenerationRequest(BaseModel):
    package_style: str = "standard"
    evidence_mix: str = "balanced"
    target_profile: str = "passing_ato"
    expected_satisfied_pct: int | None = None
    expected_partial_pct: int | None = None
    expected_failed_pct: int | None = None


async def _get_assessment_or_404(project_id: int, assessment_id: int, db: AsyncSession) -> Assessment:
    result = await db.execute(
        select(Assessment).where(
            Assessment.id == assessment_id,
            Assessment.project_id == project_id,
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return a


@router.get("")
async def list_reports(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_viewer),
):
    """List all remediation reports for an assessment."""
    await _get_assessment_or_404(project_id, assessment_id, db)
    result = await db.execute(
        select(RemediationReport)
        .where(RemediationReport.assessment_id == assessment_id)
        .order_by(RemediationReport.created_at.desc())
    )
    reports = result.scalars().all()
    return [
        {
            "id": r.id,
            "report_type": r.report_type,
            "status": r.status,
            "progress_detail": r.progress_detail,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "summary": r.content_json.get("summary") if r.content_json else None,
            "generated_doc_ids": r.generated_doc_ids or [],
        }
        for r in reports
    ]


@router.post("/guide", status_code=status.HTTP_201_CREATED)
async def start_guide(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    """Start generating a remediation guide for this assessment."""
    assessment = await _get_assessment_or_404(project_id, assessment_id, db)
    if assessment.status != "complete":
        raise HTTPException(status_code=400, detail="Assessment must be complete to generate remediation guide")

    report = RemediationReport(
        assessment_id=assessment_id,
        report_type="guide",
        status="pending",
        created_by=current_user["id"],
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return {"id": report.id, "report_type": "guide", "status": "pending"}


@router.post("/test-dataset", status_code=status.HTTP_201_CREATED)
async def start_test_dataset(
    project_id: int,
    assessment_id: int,
    payload: TestDatasetGenerationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    """Generate a complete ATO test dataset — one realistic document per control in the baseline.
    Documents are saved to the project library and indexed so the next assessment run
    can evaluate them and produce 100% compliant results."""
    assessment = await _get_assessment_or_404(project_id, assessment_id, db)
    if assessment.status != "complete":
        raise HTTPException(status_code=400, detail="Assessment must be complete to generate test dataset")

    report = RemediationReport(
        assessment_id=assessment_id,
        report_type="test_dataset",
        status="pending",
        created_by=current_user["id"],
        content_json={"config": payload.model_dump(exclude_none=True)},
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return {"id": report.id, "report_type": "test_dataset", "status": "pending"}


@router.post("/artifacts", status_code=status.HTTP_201_CREATED)
async def start_artifacts(
    project_id: int,
    assessment_id: int,
    payload: ArtifactGenerationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    """Start generating reassessment-ready remediation artifacts for this assessment."""
    assessment = await _get_assessment_or_404(project_id, assessment_id, db)
    if assessment.status != "complete":
        raise HTTPException(status_code=400, detail="Assessment must be complete to generate artifacts")

    report = RemediationReport(
        assessment_id=assessment_id,
        report_type="artifacts",
        status="pending",
        created_by=current_user["id"],
        content_json={
            "config": {
                **payload.model_dump(exclude_none=True),
                "target_profile": "passing_ato",
            }
        },
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return {"id": report.id, "report_type": "artifacts", "status": "pending"}


@router.post("/{report_id}/cancel", status_code=200)
async def cancel_report(
    project_id: int,
    assessment_id: int,
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    """Cancel a running or pending remediation report."""
    from sqlalchemy import update as _upd
    result = await db.execute(
        select(RemediationReport).where(
            RemediationReport.id == report_id,
            RemediationReport.assessment_id == assessment_id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status not in ("running", "pending"):
        raise HTTPException(status_code=400, detail=f"Report is not running (status: {report.status})")
    await db.execute(
        _upd(RemediationReport)
        .where(RemediationReport.id == report_id)
        .values(
            status="failed",
            error_message="Cancelled by user.",
            progress_detail=None,
        )
    )
    await db.commit()
    return {"cancelled": True}


@router.delete("/{report_id}", status_code=200)
async def reset_report(
    project_id: int,
    assessment_id: int,
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    """Delete a failed remediation report so a clean generation can be started."""
    result = await db.execute(
        select(RemediationReport).where(
            RemediationReport.id == report_id,
            RemediationReport.assessment_id == assessment_id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status in ("running", "pending"):
        raise HTTPException(
            status_code=400,
            detail="Cannot reset a report that is currently running. Cancel it first."
        )
    await db.delete(report)
    await db.commit()
    return {"reset": True}


@router.get("/docs")
async def list_autogenerated_docs(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_viewer),
):
    """List all auto-generated documents for this assessment."""
    result = await db.execute(
        select(Document).where(
            Document.source_assessment_id == assessment_id,
            Document.autogenerated == True,  # noqa: E712
        ).order_by(Document.created_at)
    )
    docs = result.scalars().all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "file_type": d.file_type,
            "parse_status": d.parse_status,
            "source_remediation_report_id": d.source_remediation_report_id,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "file_size_bytes": d.file_size_bytes,
        }
        for d in docs
    ]


@router.delete("/docs", status_code=200)
async def delete_all_autogenerated_docs(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    """Delete all auto-generated documents for this assessment."""
    result = await db.execute(
        select(Document).where(
            Document.source_assessment_id == assessment_id,
            Document.autogenerated == True,  # noqa: E712
        )
    )
    docs = result.scalars().all()
    deleted = 0
    for doc in docs:
        try:
            if doc.file_path and Path(doc.file_path).exists():
                Path(doc.file_path).unlink()
        except Exception:
            pass
        await db.delete(doc)
        deleted += 1
    await db.commit()
    return {"deleted": deleted}


@router.delete("/docs/{doc_id}", status_code=200)
async def delete_autogenerated_doc(
    project_id: int,
    assessment_id: int,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    """Delete a single auto-generated document."""
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.source_assessment_id == assessment_id,
            Document.autogenerated == True,  # noqa: E712
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        if doc.file_path and Path(doc.file_path).exists():
            Path(doc.file_path).unlink()
    except Exception:
        pass
    await db.delete(doc)
    await db.commit()
    return {"deleted": 1}


@router.get("/{report_id}")
async def get_report(
    project_id: int,
    assessment_id: int,
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_viewer),
):
    """Get a single remediation report with full content."""
    result = await db.execute(
        select(RemediationReport).where(
            RemediationReport.id == report_id,
            RemediationReport.assessment_id == assessment_id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    content = report.content_json or {}
    if report.report_type == "test_dataset":
        assessment_result = await db.execute(
            select(Assessment)
            .where(
                Assessment.project_id == project_id,
                Assessment.status == "complete",
                Assessment.completed_at.is_not(None),
                Assessment.completed_at >= report.created_at,
            )
            .order_by(Assessment.completed_at.desc())
            .limit(1)
        )
        benchmark_assessment = assessment_result.scalar_one_or_none()
        if benchmark_assessment and content.get("expected_outcomes"):
            findings_result = await db.execute(
                select(ControlFinding.control_id, ControlFinding.status)
                .where(ControlFinding.assessment_id == benchmark_assessment.id)
            )
            actual = {control_id: finding_status for control_id, finding_status in findings_result.all()}
            content = {
                **content,
                "benchmark": {
                    **build_benchmark_result(content["expected_outcomes"], actual),
                    "assessment_id": benchmark_assessment.id,
                    "assessment_completed_at": benchmark_assessment.completed_at.isoformat() if benchmark_assessment.completed_at else None,
                },
            }

    return {
        "id": report.id,
        "report_type": report.report_type,
        "status": report.status,
        "progress_detail": report.progress_detail,
        "error_message": report.error_message,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "content": content,
        "generated_doc_ids": report.generated_doc_ids or [],
    }


@router.get("/{report_id}/download")
async def download_report(
    project_id: int,
    assessment_id: int,
    report_id: int,
    fmt: str = "docx",
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_viewer),
):
    """Download the report — guide as Word or Excel, artifacts as Word."""
    from app.services.remediation_service import (
        _build_artifact_package_docx,
        _build_guide_docx,
        _build_guide_xlsx,
    )

    result = await db.execute(
        select(RemediationReport).where(
            RemediationReport.id == report_id,
            RemediationReport.assessment_id == assessment_id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status != "complete":
        raise HTTPException(status_code=400, detail="Report is not complete yet")

    content = report.content_json or {}
    date_str = datetime.now().strftime("%B %d, %Y")

    if report.report_type == "guide":
        summary = content.get("summary", {})
        sections = content.get("sections", [])
        system_name = "System"

        if fmt == "xlsx":
            file_bytes = _build_guide_xlsx(sections, summary, system_name)
            filename = f"Remediation_Action_Tracker_assessment_{assessment_id}.xlsx"
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            file_bytes = _build_guide_docx(sections, summary, system_name, date_str)
            filename = f"Remediation_Guide_assessment_{assessment_id}.docx"
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        file_bytes = _build_artifact_package_docx(content, date_str)
        filename = f"Remediation_Artifacts_assessment_{assessment_id}.docx"
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
