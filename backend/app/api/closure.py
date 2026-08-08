"""Control Closure Workflow API.

Provides endpoints for the interactive closure workflow that walks users through
closing partial and non-compliant NIST 800-53 Rev 5 controls.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_assessment_access, require_reviewer, require_viewer
from app.models.orm import ArtifactApproval, ControlClosureSession, Document
from app.services import closure_service
from app.core.config import get_settings

router = APIRouter(
    prefix="/projects/{project_id}/assessments/{assessment_id}/closure",
    tags=["closure"],
    dependencies=[Depends(require_project_assessment_access)],
)

settings = get_settings()


# ── Request / Response Schemas ─────────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    control_id: str


class AnswerRequest(BaseModel):
    answers: dict[str, Any]  # {question_id: value}


class GenerateArtifactsRequest(BaseModel):
    preparer_name: str = "System User"


class GenerateDraftPackageRequest(BaseModel):
    preparer_name: str = "System User"


class ApprovalActionRequest(BaseModel):
    approver_name: str
    approver_title: str = ""
    approver_org: str = ""
    action: str  # "approve" | "reject"
    comments: str = ""


class EvidenceEligibilityRequest(BaseModel):
    decision: str
    rationale: str


class CompleteSessionRequest(BaseModel):
    closure_notes: str = ""


class ProofControlRequest(BaseModel):
    persist_documents: bool = False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/sessions", summary="List closure sessions for an assessment")
async def list_sessions(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    result = await db.execute(
        select(ControlClosureSession)
        .where(
            ControlClosureSession.project_id == project_id,
            ControlClosureSession.assessment_id == assessment_id,
        )
        .order_by(ControlClosureSession.created_at.desc())
    )
    sessions = result.scalars().all()
    return [closure_service._session_to_dict(s) for s in sessions]


@router.post("/sessions", summary="Start a new control closure session")
async def start_session(
    project_id: int,
    assessment_id: int,
    body: StartSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    try:
        return await closure_service.start_session(
            project_id=project_id,
            assessment_id=assessment_id,
            control_id=body.control_id,
            created_by=current_user["id"],
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/sessions/{session_id}", summary="Get a closure session")
async def get_session(
    project_id: int,
    assessment_id: int,
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    result = await db.execute(
        select(ControlClosureSession)
        .where(
            ControlClosureSession.id == session_id,
            ControlClosureSession.project_id == project_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    approvals_result = await db.execute(
        select(ArtifactApproval).where(ArtifactApproval.session_id == session_id)
    )
    approvals = approvals_result.scalars().all()
    return closure_service._session_to_dict(session, approvals)


@router.get("/controls/{control_id}/guidance", summary="Get deterministic closure guidance for a control")
async def get_control_guidance(
    project_id: int,
    assessment_id: int,
    control_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    try:
        return await closure_service.get_closure_guidance(
            project_id=project_id,
            assessment_id=assessment_id,
            control_id=control_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/controls/{control_id}/draft-package", summary="Get the latest AI draft artifact package for a control")
async def get_control_draft_package(
    project_id: int,
    assessment_id: int,
    control_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    try:
        return await closure_service.get_control_draft_package(
            project_id=project_id,
            assessment_id=assessment_id,
            control_id=control_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/controls/{control_id}/draft-package", summary="Generate an AI draft artifact package for control-owner review")
async def generate_control_draft_package(
    project_id: int,
    assessment_id: int,
    control_id: str,
    body: GenerateDraftPackageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> dict:
    upload_dir = os.path.join(settings.upload_dir, str(project_id))
    os.makedirs(upload_dir, exist_ok=True)
    try:
        return await closure_service.generate_control_draft_package(
            project_id=project_id,
            assessment_id=assessment_id,
            control_id=control_id,
            created_by=current_user["id"],
            preparer_name=body.preparer_name,
            project_upload_dir=upload_dir,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/draft-packages/report", summary="Get the assessment-wide AI draft artifact remediation report")
async def get_draft_package_report(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    return await closure_service.get_assessment_draft_package_report(
        project_id=project_id,
        assessment_id=assessment_id,
        db=db,
    )


@router.post("/controls/{control_id}/prove", summary="Generate a deterministic proof artifact and reassess a single control")
async def prove_control(
    project_id: int,
    assessment_id: int,
    control_id: str,
    body: ProofControlRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    try:
        return await closure_service.prove_control_closure(
            project_id=project_id,
            assessment_id=assessment_id,
            control_id=control_id,
            persist_documents=body.persist_documents,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sessions/{session_id}/respond", summary="Submit interview answers")
async def submit_answers(
    project_id: int,
    assessment_id: int,
    session_id: int,
    body: AnswerRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    try:
        return await closure_service.submit_answers(
            session_id=session_id,
            answers=body.answers,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sessions/{session_id}/generate-artifacts", summary="Generate artifacts from session context")
async def generate_artifacts(
    project_id: int,
    assessment_id: int,
    session_id: int,
    body: GenerateArtifactsRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    upload_dir = os.path.join(settings.upload_dir, str(project_id))
    os.makedirs(upload_dir, exist_ok=True)
    try:
        return await closure_service.generate_artifacts(
            session_id=session_id,
            preparer_name=body.preparer_name,
            project_upload_dir=upload_dir,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/sessions/{session_id}/approvals", summary="List approval records for a session")
async def list_approvals(
    project_id: int,
    assessment_id: int,
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    result = await db.execute(
        select(ArtifactApproval).where(ArtifactApproval.session_id == session_id)
    )
    approvals = result.scalars().all()
    return [closure_service._approval_to_dict(a) for a in approvals]


@router.post("/sessions/{session_id}/approvals/{approval_id}/advance", summary="Approve or reject an artifact")
async def advance_approval(
    project_id: int,
    assessment_id: int,
    session_id: int,
    approval_id: int,
    body: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")
    try:
        return await closure_service.advance_approval(
            approval_id=approval_id,
            approver_name=body.approver_name,
            approver_title=body.approver_title,
            approver_org=body.approver_org,
            action=body.action,
            comments=body.comments,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/sessions/{session_id}/approvals/{approval_id}/evidence-eligibility",
    summary="Explicitly approve or reject an AI artifact for assessment evidence use",
)
async def decide_evidence_eligibility(
    project_id: int,
    assessment_id: int,
    session_id: int,
    approval_id: int,
    body: EvidenceEligibilityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_reviewer),
) -> dict:
    if body.decision not in {"eligible", "rejected"}:
        raise HTTPException(status_code=422, detail="decision must be eligible or rejected")
    if len(body.rationale.strip()) < 10:
        raise HTTPException(status_code=422, detail="A review rationale of at least 10 characters is required")
    approval = await db.scalar(
        select(ArtifactApproval).where(
            ArtifactApproval.id == approval_id,
            ArtifactApproval.session_id == session_id,
        )
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Artifact approval not found")
    if body.decision == "eligible" and approval.overall_status != "approved":
        raise HTTPException(status_code=409, detail="The artifact approval chain must be complete first")
    document = await db.scalar(
        select(Document).where(
            Document.id == approval.document_id,
            Document.project_id == project_id,
            Document.source_assessment_id == assessment_id,
        )
    )
    if not document:
        raise HTTPException(status_code=404, detail="Generated document not found")

    now = datetime.now(UTC)
    approval.evidence_eligibility = body.decision
    approval.eligibility_rationale = body.rationale.strip()
    approval.eligibility_decided_by = current_user["id"]
    approval.eligibility_decided_at = now
    document.artifact_status = "approved" if body.decision == "eligible" else "rejected"
    document.evidence_eligible = body.decision == "eligible"
    document.artifact_approved_by = current_user["id"]
    document.artifact_approved_at = now
    await db.commit()
    return {
        "approval_id": approval.id,
        "document_id": document.id,
        "evidence_eligibility": approval.evidence_eligibility,
        "rationale": approval.eligibility_rationale,
    }


@router.post("/sessions/{session_id}/complete", summary="Complete a closure session")
async def complete_session(
    project_id: int,
    assessment_id: int,
    session_id: int,
    body: CompleteSessionRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    try:
        return await closure_service.complete_session(
            session_id=session_id,
            closure_notes=body.closure_notes,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/sessions/{session_id}", summary="Delete a closure session")
async def delete_session(
    project_id: int,
    assessment_id: int,
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
) -> dict:
    result = await db.execute(
        select(ControlClosureSession)
        .where(
            ControlClosureSession.id == session_id,
            ControlClosureSession.project_id == project_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.commit()
    return {"deleted": True}
