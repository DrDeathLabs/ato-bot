"""Human assessment activities, tailoring, dissent resolution, approvals, and finalization."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_assessment_access, require_reviewer, require_viewer
from app.models.orm import (
    Assessment,
    AssessmentActivity,
    AssessmentApproval,
    AssessmentChallenge,
    AssessmentPlan,
    AssessmentTailoringDecision,
)
from app.services.assessment_governance import build_approval_snapshot_hash, build_finalization_readiness

router = APIRouter(
    prefix="/projects/{project_id}/assessments/{assessment_id}/governance",
    tags=["assessment-governance"],
    dependencies=[Depends(require_project_assessment_access)],
)


class ActivityCompleteRequest(BaseModel):
    result: str = Field(min_length=10)
    evidence_refs: list[dict[str, Any] | str] = Field(min_length=1)


class TailoringRequest(BaseModel):
    control_id: str
    decision_type: str
    parameter_id: str | None = None
    value: dict | list | str | None = None
    rationale: str = Field(min_length=10)
    evidence_refs: list[dict[str, Any] | str] = Field(default_factory=list)

    @field_validator("decision_type")
    @classmethod
    def validate_decision_type(cls, value: str) -> str:
        if value not in {"odp", "inherited", "compensating", "not_applicable"}:
            raise ValueError("decision_type must be odp, inherited, compensating, or not_applicable")
        return value


class TailoringReviewRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in {"approved", "rejected"}:
            raise ValueError("status must be approved or rejected")
        return value


class DissentResolutionRequest(BaseModel):
    resolution_status: str
    note: str = Field(min_length=10)

    @field_validator("resolution_status")
    @classmethod
    def validate_resolution(cls, value: str) -> str:
        if value not in {"resolved", "dismissed"}:
            raise ValueError("resolution_status must be resolved or dismissed")
        return value


class ApprovalRequest(BaseModel):
    approval_type: str
    statement: str = Field(min_length=20)

    @field_validator("approval_type")
    @classmethod
    def validate_approval_type(cls, value: str) -> str:
        if value not in {"assessor", "independent_reviewer"}:
            raise ValueError("approval_type must be assessor or independent_reviewer")
        return value


async def _require_mutable_assessment(assessment_id: int, db: AsyncSession) -> Assessment:
    assessment = await db.scalar(select(Assessment).where(Assessment.id == assessment_id))
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.finalization_status == "finalized":
        raise HTTPException(
            status_code=409,
            detail="The finalized assessment record is immutable. Start a new assessment to record changes.",
        )
    return assessment


@router.get("/plan")
async def get_plan(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    plan = await db.scalar(select(AssessmentPlan).where(AssessmentPlan.assessment_id == assessment_id))
    if not plan:
        raise HTTPException(status_code=404, detail="Assessment plan not found")
    return {
        "id": plan.id,
        "assessment_id": plan.assessment_id,
        "title": plan.title,
        "status": plan.status,
        "scope": plan.scope_json,
        "control_selection": plan.control_selection_json,
        "methods": plan.methods_json,
        "assessment_objects": plan.objects_json,
        "depth": plan.depth,
        "coverage": plan.coverage,
        "assessor_id": plan.assessor_id,
        "approved_by": plan.approved_by,
        "approved_at": plan.approved_at,
        "approval_note": plan.approval_note,
    }


@router.get("/activities")
async def list_activities(
    assessment_id: int,
    method: str | None = None,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    query = select(AssessmentActivity).where(AssessmentActivity.assessment_id == assessment_id)
    if method:
        query = query.where(AssessmentActivity.method == method.upper())
    if status_filter:
        query = query.where(AssessmentActivity.status == status_filter)
    rows = (await db.execute(query.order_by(AssessmentActivity.control_id, AssessmentActivity.method))).scalars().all()
    return [
        {
            "id": row.id,
            "control_id": row.control_id,
            "objective_id": row.objective_id,
            "method": row.method,
            "assessment_objects": row.assessment_objects,
            "description": row.description,
            "status": row.status,
            "result": row.result,
            "evidence_refs": row.evidence_refs or [],
            "performed_by": row.performed_by,
            "performed_at": row.performed_at,
            "reviewed_by": row.reviewed_by,
            "reviewed_at": row.reviewed_at,
        }
        for row in rows
    ]


@router.patch("/activities/{activity_id}/complete")
async def complete_activity(
    assessment_id: int,
    activity_id: int,
    body: ActivityCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    await _require_mutable_assessment(assessment_id, db)
    activity = await db.scalar(select(AssessmentActivity).where(
        AssessmentActivity.id == activity_id,
        AssessmentActivity.assessment_id == assessment_id,
    ))
    if not activity:
        raise HTTPException(status_code=404, detail="Assessment activity not found")
    was_performed = activity.status == "performed" and bool(activity.performed_by)
    activity.status = "completed"
    activity.result = body.result
    activity.evidence_refs = body.evidence_refs
    if not was_performed:
        activity.performed_by = current_user["id"]
        activity.performed_at = datetime.now(UTC)
    activity.reviewed_by = current_user["id"]
    activity.reviewed_at = datetime.now(UTC)
    await db.commit()
    return {"id": activity.id, "status": activity.status}


@router.get("/tailoring")
async def list_tailoring(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    rows = (
        await db.execute(
            select(AssessmentTailoringDecision)
            .where(AssessmentTailoringDecision.assessment_id == assessment_id)
            .order_by(AssessmentTailoringDecision.control_id, AssessmentTailoringDecision.id)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "control_id": row.control_id,
            "decision_type": row.decision_type,
            "parameter_id": row.parameter_id,
            "value": row.value_json,
            "rationale": row.rationale,
            "evidence_refs": row.evidence_refs or [],
            "status": row.status,
            "created_by": row.created_by,
            "approved_by": row.approved_by,
            "approved_at": row.approved_at,
        }
        for row in rows
    ]


@router.post("/tailoring", status_code=201)
async def create_tailoring(
    assessment_id: int,
    body: TailoringRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    await _require_mutable_assessment(assessment_id, db)
    row = AssessmentTailoringDecision(
        assessment_id=assessment_id,
        control_id=body.control_id.upper(),
        decision_type=body.decision_type,
        parameter_id=body.parameter_id,
        value_json=body.value,
        rationale=body.rationale,
        evidence_refs=body.evidence_refs,
        status="proposed",
        created_by=current_user["id"],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "status": row.status}


@router.patch("/tailoring/{decision_id}/review")
async def review_tailoring(
    assessment_id: int,
    decision_id: int,
    body: TailoringReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_reviewer),
) -> dict:
    await _require_mutable_assessment(assessment_id, db)
    row = await db.scalar(select(AssessmentTailoringDecision).where(
        AssessmentTailoringDecision.id == decision_id,
        AssessmentTailoringDecision.assessment_id == assessment_id,
    ))
    if not row:
        raise HTTPException(status_code=404, detail="Tailoring decision not found")
    row.status = body.status
    row.approved_by = current_user["id"] if body.status == "approved" else None
    row.approved_at = datetime.now(UTC) if body.status == "approved" else None
    await db.commit()
    return {"id": row.id, "status": row.status}


@router.patch("/dissents/{control_id}")
async def resolve_dissent(
    assessment_id: int,
    control_id: str,
    body: DissentResolutionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_reviewer),
) -> dict:
    await _require_mutable_assessment(assessment_id, db)
    challenge = await db.scalar(select(AssessmentChallenge).where(
        AssessmentChallenge.assessment_id == assessment_id,
        AssessmentChallenge.control_id == control_id.upper(),
        AssessmentChallenge.concur.is_(False),
    ))
    if not challenge:
        raise HTTPException(status_code=404, detail="Unresolved dissent not found")
    challenge.resolution_status = body.resolution_status
    challenge.resolution_note = body.note
    challenge.resolved_by = current_user["id"]
    challenge.resolved_at = datetime.now(UTC)
    await db.commit()
    return {"control_id": challenge.control_id, "resolution_status": challenge.resolution_status}


@router.get("/dissents")
async def list_dissents(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    rows = (
        await db.execute(
            select(AssessmentChallenge)
            .where(
                AssessmentChallenge.assessment_id == assessment_id,
                AssessmentChallenge.concur.is_(False),
            )
            .order_by(AssessmentChallenge.control_id, AssessmentChallenge.id)
        )
    ).scalars().all()
    return [
        {
            "control_id": row.control_id,
            "dissent_note": row.dissent_note,
            "challenged_objectives": row.challenged_objectives or [],
            "resolution_status": row.resolution_status,
            "resolution_note": row.resolution_note,
            "resolved_by": row.resolved_by,
            "resolved_at": row.resolved_at,
        }
        for row in rows
    ]


@router.get("/readiness")
async def finalization_readiness(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    return await build_finalization_readiness(assessment_id, db)


@router.get("/approvals")
async def list_approvals(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    rows = (
        await db.execute(
            select(AssessmentApproval)
            .where(AssessmentApproval.assessment_id == assessment_id)
            .order_by(AssessmentApproval.created_at, AssessmentApproval.id)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "approval_type": row.approval_type,
            "decision": row.decision,
            "statement": row.statement,
            "snapshot_hash": row.snapshot_hash,
            "user_id": row.user_id,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/approvals", status_code=201)
async def create_approval(
    assessment_id: int,
    body: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    await _require_mutable_assessment(assessment_id, db)
    if body.approval_type == "independent_reviewer" and current_user["role"] not in {"security_officer", "system_admin"}:
        raise HTTPException(status_code=403, detail="Independent approval requires security_officer or system_admin")
    readiness = await build_finalization_readiness(assessment_id, db, include_approvals=False)
    if not readiness["ready"]:
        raise HTTPException(status_code=409, detail={"message": "Assessment is not ready for approval", **readiness})
    if body.approval_type == "independent_reviewer":
        assessor_approval = await db.scalar(
            select(AssessmentApproval)
            .where(
                AssessmentApproval.assessment_id == assessment_id,
                AssessmentApproval.approval_type == "assessor",
                AssessmentApproval.decision == "approved",
            )
            .order_by(AssessmentApproval.created_at.desc(), AssessmentApproval.id.desc())
        )
        if not assessor_approval:
            raise HTTPException(status_code=409, detail="Assessor approval must be recorded first")
        if assessor_approval.user_id == current_user["id"]:
            raise HTTPException(status_code=409, detail="Independent reviewer must be a different user")
    snapshot_hash = await build_approval_snapshot_hash(assessment_id, db)
    row = AssessmentApproval(
        assessment_id=assessment_id,
        approval_type=body.approval_type,
        decision="approved",
        statement=body.statement,
        snapshot_hash=snapshot_hash,
        user_id=current_user["id"],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "snapshot_hash": row.snapshot_hash}


@router.post("/finalize")
async def finalize_assessment(
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    assessment = await _require_mutable_assessment(assessment_id, db)
    if current_user["role"] not in {"security_officer", "system_admin"}:
        raise HTTPException(status_code=403, detail="Finalization requires security_officer or system_admin")
    readiness = await build_finalization_readiness(assessment_id, db)
    if not readiness["ready"]:
        raise HTTPException(status_code=409, detail={"message": "Assessment cannot be finalized", **readiness})
    assessment.finalization_status = "finalized"
    assessment.finalized_by = current_user["id"]
    assessment.finalized_at = datetime.now(UTC)
    await db.commit()
    return {"assessment_id": assessment_id, "finalization_status": assessment.finalization_status}
