"""Test Dataset Generator API — project-level standalone endpoint.

Generates a complete, realistic ATO evidence package for all controls in
the project's baseline. Not tied to any specific assessment run.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_access, require_viewer
from app.models.orm import Assessment, ControlFinding, Document, Project, TestDatasetJob
from app.services.calibration_harness import (
    get_latest_calibration_for_job,
    run_test_dataset_calibration,
)
from app.services.package_generation import build_benchmark_result

router = APIRouter(
    prefix="/projects/{project_id}/test-dataset",
    tags=["test-dataset"],
    dependencies=[Depends(require_project_access)],
)


class TestDatasetGenerateRequest(BaseModel):
    package_style: str = "standard"
    evidence_mix: str = "balanced"
    target_profile: str = "passing_ato"
    expected_satisfied_pct: int | None = None
    expected_partial_pct: int | None = None
    expected_failed_pct: int | None = None
    family_overrides: dict | None = None
    control_overrides: dict | None = None


async def _get_project_or_404(project_id: int, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("")
async def get_latest_job(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    """Return the most recent test dataset job for this project."""
    await _get_project_or_404(project_id, db)
    result = await db.execute(
        select(TestDatasetJob)
        .where(TestDatasetJob.project_id == project_id)
        .order_by(TestDatasetJob.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if not job:
        return None
    return await _job_response(job, db)


@router.get("/history")
async def list_jobs(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    """List all test dataset jobs for this project (most recent first)."""
    await _get_project_or_404(project_id, db)
    result = await db.execute(
        select(TestDatasetJob)
        .where(TestDatasetJob.project_id == project_id)
        .order_by(TestDatasetJob.created_at.desc())
        .limit(10)
    )
    jobs = result.scalars().all()
    return [await _job_response(j, db) for j in jobs]


@router.post("/generate", status_code=status.HTTP_201_CREATED)
async def start_generation(
    project_id: int,
    payload: TestDatasetGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    """Start a new test dataset generation run.

    Any previously running job for this project is cancelled first.
    Generated documents from the previous completed run are deleted so the
    new run produces a clean, complete, self-consistent package.
    """
    project = await _get_project_or_404(project_id, db)

    # Cancel any currently running job
    from sqlalchemy import update as _upd
    await db.execute(
        _upd(TestDatasetJob)
        .where(
            TestDatasetJob.project_id == project_id,
            TestDatasetJob.status.in_(["running", "pending"]),
        )
        .values(
            status="cancelled",
            progress_detail=None,
            error_message="Superseded by a new generation run.",
        )
    )
    await db.commit()

    job = TestDatasetJob(
        project_id=project_id,
        status="pending",
        created_by=current_user["id"],
        content_json={"config": payload.model_dump(exclude_none=True)},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    return await _job_response(job, db)


@router.delete("/{job_id}", status_code=200)
async def delete_job(
    project_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    """Delete a test dataset job and all documents it generated."""
    result = await db.execute(
        select(TestDatasetJob).where(
            TestDatasetJob.id == job_id,
            TestDatasetJob.project_id == project_id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ("running", "pending"):
        raise HTTPException(
            status_code=400,
            detail="Job is still running. Cancel it first or wait for it to complete.",
        )

    # Delete generated documents
    doc_ids = job.generated_doc_ids or []
    if doc_ids:
        from pathlib import Path
        docs_result = await db.execute(
            select(Document).where(Document.id.in_(doc_ids))
        )
        for doc in docs_result.scalars().all():
            try:
                Path(doc.file_path).unlink(missing_ok=True)
            except Exception:
                pass
            await db.delete(doc)

    await db.delete(job)
    await db.commit()
    return {"deleted": True, "documents_removed": len(doc_ids)}


@router.post("/{job_id}/cancel", status_code=200)
async def cancel_job(
    project_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
):
    """Cancel a running or pending job."""
    from sqlalchemy import update as _upd
    result = await db.execute(
        select(TestDatasetJob).where(
            TestDatasetJob.id == job_id,
            TestDatasetJob.project_id == project_id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("running", "pending"):
        raise HTTPException(status_code=400, detail=f"Job is not running (status: {job.status})")

    await db.execute(
        _upd(TestDatasetJob)
        .where(TestDatasetJob.id == job_id)
        .values(status="cancelled", progress_detail=None, error_message="Cancelled by user.")
    )
    await db.commit()
    return {"cancelled": True}


@router.post("/{job_id}/calibrate", status_code=200)
async def calibrate_job(
    project_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    """Run a persistent calibration pass against the latest completed assessment after this job."""
    await _get_project_or_404(project_id, db)
    return await run_test_dataset_calibration(
        db,
        project_id=project_id,
        job_id=job_id,
        created_by=current_user["id"],
    )


@router.get("/{job_id}/calibration")
async def latest_calibration(
    project_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await get_latest_calibration_for_job(db, project_id=project_id, job_id=job_id)


# ── Response helper ───────────────────────────────────────────────────────────

async def _latest_benchmark_for_job(db: AsyncSession, job: TestDatasetJob) -> dict | None:
    content = job.content_json or {}
    expected_outcomes = content.get("expected_outcomes")
    if not expected_outcomes or not job.created_at:
        return None

    assessment_result = await db.execute(
        select(Assessment)
        .where(
            Assessment.project_id == job.project_id,
            Assessment.status == "complete",
            Assessment.completed_at.is_not(None),
            Assessment.completed_at >= job.created_at,
        )
        .order_by(Assessment.completed_at.desc())
        .limit(1)
    )
    assessment = assessment_result.scalar_one_or_none()
    if not assessment:
        return None

    findings_result = await db.execute(
        select(ControlFinding.control_id, ControlFinding.status)
        .where(ControlFinding.assessment_id == assessment.id)
    )
    actual = {control_id: status for control_id, status in findings_result.all()}
    benchmark = build_benchmark_result(expected_outcomes, actual)
    benchmark["assessment_id"] = assessment.id
    benchmark["assessment_completed_at"] = assessment.completed_at.isoformat() if assessment.completed_at else None
    return benchmark


async def _job_response(job: TestDatasetJob, db: AsyncSession) -> dict:
    summary = (job.content_json or {}).get("summary", {})
    benchmark = await _latest_benchmark_for_job(db, job)
    calibration = await get_latest_calibration_for_job(db, project_id=job.project_id, job_id=job.id)
    return {
        "id": job.id,
        "project_id": job.project_id,
        "status": job.status,
        "progress_detail": job.progress_detail,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "generated_doc_ids": job.generated_doc_ids or [],
        "config": (job.content_json or {}).get("config", {}),
        "summary": summary,
        "blueprint": (job.content_json or {}).get("blueprint"),
        "validation": (job.content_json or {}).get("validation"),
        "expected_outcomes": (job.content_json or {}).get("expected_outcomes"),
        "benchmark": benchmark,
        "calibration": calibration,
        "artifacts": (job.content_json or {}).get("artifacts", []),
    }
