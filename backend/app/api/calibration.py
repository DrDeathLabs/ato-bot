"""Project-level calibration suite APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_access, require_viewer
from app.models.orm import CalibrationCase, CalibrationSuite, Project
from app.services.calibration_harness import (
    get_calibration_run,
    list_calibration_suites,
    run_suite_calibration,
)

router = APIRouter(
    prefix="/projects/{project_id}/calibration",
    tags=["calibration"],
    dependencies=[Depends(require_project_access)],
)


class SuiteCreateRequest(BaseModel):
    name: str
    description: str | None = None


class CaseCreateRequest(BaseModel):
    control_id: str
    expected_status: str
    notes: str | None = None
    expected_objectives: dict | list | None = None
    expected_citations: dict | list | None = None


class SuiteRunRequest(BaseModel):
    assessment_id: int | None = None


async def _get_project_or_404(project_id: int, db: AsyncSession) -> None:
    project = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/suites")
async def suites(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    return await list_calibration_suites(db, project_id=project_id)


@router.post("/suites", status_code=status.HTTP_201_CREATED)
async def create_suite(
    project_id: int,
    payload: SuiteCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    suite = CalibrationSuite(
        project_id=project_id,
        name=payload.name.strip(),
        description=(payload.description or "").strip() or None,
        created_by=current_user["id"],
    )
    db.add(suite)
    await db.commit()
    await db.refresh(suite)
    return {
        "id": suite.id,
        "name": suite.name,
        "description": suite.description,
    }


@router.post("/suites/{suite_id}/cases", status_code=status.HTTP_201_CREATED)
async def create_case(
    project_id: int,
    suite_id: int,
    payload: CaseCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    suite = (
        await db.execute(
            select(CalibrationSuite).where(
                CalibrationSuite.id == suite_id,
                CalibrationSuite.project_id == project_id,
            )
        )
    ).scalars().first()
    if not suite:
        raise HTTPException(status_code=404, detail="Calibration suite not found")
    case = CalibrationCase(
        suite_id=suite_id,
        control_id=payload.control_id.strip().upper(),
        expected_status=payload.expected_status,
        expected_objectives_json=payload.expected_objectives,
        expected_citations_json=payload.expected_citations,
        notes=(payload.notes or "").strip() or None,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return {
        "id": case.id,
        "control_id": case.control_id,
        "expected_status": case.expected_status,
        "notes": case.notes,
    }


@router.delete("/suites/{suite_id}/cases/{case_id}", status_code=200)
async def delete_case(
    project_id: int,
    suite_id: int,
    case_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    case = (
        await db.execute(
            select(CalibrationCase)
            .join(CalibrationSuite, CalibrationSuite.id == CalibrationCase.suite_id)
            .where(
                CalibrationCase.id == case_id,
                CalibrationCase.suite_id == suite_id,
                CalibrationSuite.project_id == project_id,
            )
        )
    ).scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail="Calibration case not found")
    await db.delete(case)
    await db.commit()
    return {"deleted": True}


@router.post("/suites/{suite_id}/run", status_code=200)
async def run_suite(
    project_id: int,
    suite_id: int,
    payload: SuiteRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
):
    await _get_project_or_404(project_id, db)
    try:
        return await run_suite_calibration(
            db,
            project_id=project_id,
            suite_id=suite_id,
            created_by=current_user["id"],
            assessment_id=payload.assessment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/runs/{run_id}")
async def get_run(
    project_id: int,
    run_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
):
    await _get_project_or_404(project_id, db)
    run = await get_calibration_run(db, project_id=project_id, run_id=run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Calibration run not found")
    return run
