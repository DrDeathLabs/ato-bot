"""Assessment finalization gates and immutable approval snapshot helpers."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    Assessment,
    AssessmentActivity,
    AssessmentApproval,
    AssessmentChallenge,
    AssessmentCriteriaPackage,
    AssessmentPlan,
    AssessmentTailoringDecision,
    ControlFinding,
    POAM,
)


def _blocker(code: str, count: int, message: str, items: list[str] | None = None) -> dict[str, Any]:
    return {"code": code, "count": count, "message": message, "items": (items or [])[:50]}


async def build_finalization_readiness(
    assessment_id: int,
    db: AsyncSession,
    *,
    include_approvals: bool = True,
) -> dict[str, Any]:
    assessment = await db.scalar(select(Assessment).where(Assessment.id == assessment_id))
    if not assessment:
        raise ValueError("Assessment not found")

    plan = await db.scalar(select(AssessmentPlan).where(AssessmentPlan.assessment_id == assessment_id))
    findings = (
        await db.execute(select(ControlFinding).where(ControlFinding.assessment_id == assessment_id))
    ).scalars().all()
    activities = (
        await db.execute(select(AssessmentActivity).where(AssessmentActivity.assessment_id == assessment_id))
    ).scalars().all()
    challenges = (
        await db.execute(select(AssessmentChallenge).where(AssessmentChallenge.assessment_id == assessment_id))
    ).scalars().all()
    tailoring = (
        await db.execute(
            select(AssessmentTailoringDecision).where(AssessmentTailoringDecision.assessment_id == assessment_id)
        )
    ).scalars().all()
    criteria = (
        await db.execute(
            select(AssessmentCriteriaPackage).where(AssessmentCriteriaPackage.assessment_id == assessment_id)
        )
    ).scalars().all()
    poams = (
        await db.execute(select(POAM).where(POAM.assessment_id == assessment_id))
    ).scalars().all()
    approvals = (
        await db.execute(
            select(AssessmentApproval)
            .where(AssessmentApproval.assessment_id == assessment_id)
            .order_by(AssessmentApproval.created_at, AssessmentApproval.id)
        )
    ).scalars().all()

    blockers: list[dict[str, Any]] = []
    if assessment.status != "complete":
        blockers.append(_blocker("execution_incomplete", 1, "Assessment execution must be complete."))
    if not plan or plan.status != "approved" or not plan.approved_at:
        blockers.append(_blocker("plan_not_approved", 1, "An approved pre-execution assessment plan is required."))

    if len(findings) != int(assessment.controls_total or 0):
        blockers.append(_blocker(
            "finding_count_mismatch",
            abs(int(assessment.controls_total or 0) - len(findings)),
            "Every selected control must have one persisted finding.",
        ))
    unreviewed = [
        finding.control_id
        for finding in findings
        if finding.reviewer_status not in {"accepted", "override"} or not finding.reviewed_at
    ]
    if unreviewed:
        blockers.append(_blocker(
            "findings_unreviewed", len(unreviewed), "Every final finding requires explicit human review.", unreviewed
        ))

    unresolved_dissents = [
        challenge.control_id
        for challenge in challenges
        if not challenge.concur and challenge.resolution_status not in {"resolved", "dismissed"}
    ]
    if unresolved_dissents:
        blockers.append(_blocker(
            "dissents_unresolved", len(unresolved_dissents), "Every AI dissent must be resolved by a reviewer.", unresolved_dissents
        ))

    incomplete_activities = [
        f"{activity.control_id}:{activity.method}"
        for activity in activities
        if (
            activity.status != "completed"
            or not (activity.result or "").strip()
            or not activity.performed_by
            or not activity.performed_at
            or not activity.reviewed_by
            or not activity.reviewed_at
        )
    ]
    if incomplete_activities:
        blockers.append(_blocker(
            "activities_incomplete",
            len(incomplete_activities),
            "Every planned EXAMINE, INTERVIEW, and TEST activity must have a recorded result.",
            incomplete_activities,
        ))

    approved_tailoring = {
        (row.control_id, row.decision_type, row.parameter_id or "")
        for row in tailoring
        if row.status == "approved" and row.approved_at
    }
    unapproved_tailoring = [f"{row.control_id}:{row.decision_type}" for row in tailoring if row.status != "approved"]
    if unapproved_tailoring:
        blockers.append(_blocker(
            "tailoring_unapproved",
            len(unapproved_tailoring),
            "Every recorded tailoring decision must be approved.",
            unapproved_tailoring,
        ))

    missing_odps: list[str] = []
    for package in criteria:
        for parameter_id in (package.criteria_metadata or {}).get("organization_defined_parameters", []):
            if (package.control_id, "odp", parameter_id) not in approved_tailoring:
                missing_odps.append(f"{package.control_id}:{parameter_id}")
    if missing_odps:
        blockers.append(_blocker(
            "odp_values_missing",
            len(missing_odps),
            "Organization-defined parameters used by the assessment require approved values.",
            missing_odps,
        ))

    missing_applicability: list[str] = []
    for finding in findings:
        decision_type = None
        if finding.status == "not_applicable":
            decision_type = "not_applicable"
        elif finding.override_applied == "inherited":
            decision_type = "inherited"
        if decision_type and (finding.control_id, decision_type, "") not in approved_tailoring:
            missing_applicability.append(f"{finding.control_id}:{decision_type}")
    if missing_applicability:
        blockers.append(_blocker(
            "applicability_ungoverned",
            len(missing_applicability),
            "N/A and inherited-control decisions require assessment-specific approval.",
            missing_applicability,
        ))

    action_findings = {
        finding.control_id
        for finding in findings
        if finding.status in {"partially_compliant", "non_compliant"}
    }
    poam_by_control = {row.control_id: row for row in poams}
    incomplete_poams: list[str] = []
    for control_id in sorted(action_findings):
        row = poam_by_control.get(control_id)
        required_values = (
            row
            and (row.owner_id or row.owner_role)
            and row.scheduled_completion_date
            and row.likelihood
            and row.impact
            and row.residual_risk
            and row.response_strategy
            and row.milestones
        )
        if not required_values:
            incomplete_poams.append(control_id)
            continue
        if row.status == "accepted_risk" and not (
            row.acceptance_rationale and row.accepted_by and row.accepted_at
        ):
            incomplete_poams.append(control_id)
    if incomplete_poams:
        blockers.append(_blocker(
            "poam_incomplete",
            len(incomplete_poams),
            "Every partial or non-compliant finding requires an owned, scheduled, risk-characterized POA&M record.",
            incomplete_poams,
        ))

    latest_approved: dict[str, AssessmentApproval] = {}
    for approval in approvals:
        if approval.decision == "approved":
            latest_approved[approval.approval_type] = approval
    if include_approvals:
        assessor_approval = latest_approved.get("assessor")
        independent_approval = latest_approved.get("independent_reviewer")
        if not assessor_approval:
            blockers.append(_blocker("assessor_approval_missing", 1, "Assessor approval is required."))
        if not independent_approval:
            blockers.append(_blocker("independent_approval_missing", 1, "Independent reviewer approval is required."))
        if assessor_approval and independent_approval and assessor_approval.user_id == independent_approval.user_id:
            blockers.append(_blocker(
                "approval_separation_failed", 1, "Assessor and independent-reviewer approvals must be from different users."
            ))
        if assessor_approval or independent_approval:
            current_snapshot_hash = await build_approval_snapshot_hash(assessment_id, db)
            stale_approvals = [
                approval.approval_type
                for approval in (assessor_approval, independent_approval)
                if approval and approval.snapshot_hash != current_snapshot_hash
            ]
            if stale_approvals:
                blockers.append(_blocker(
                    "approvals_stale",
                    len(stale_approvals),
                    "Assessment content changed after approval; affected approvals must be recorded again.",
                    stale_approvals,
                ))

    return {
        "assessment_id": assessment_id,
        "ready": not blockers,
        "finalization_status": assessment.finalization_status,
        "counts": {
            "controls_total": int(assessment.controls_total or 0),
            "findings": len(findings),
            "activities": len(activities),
            "activities_complete": len(activities) - len(incomplete_activities),
            "dissents": sum(1 for challenge in challenges if not challenge.concur),
            "tailoring_decisions": len(tailoring),
            "approvals": len(approvals),
        },
        "blockers": blockers,
    }


async def build_approval_snapshot_hash(assessment_id: int, db: AsyncSession) -> str:
    assessment = await db.scalar(select(Assessment).where(Assessment.id == assessment_id))
    plan = await db.scalar(select(AssessmentPlan).where(AssessmentPlan.assessment_id == assessment_id))
    findings = (
        await db.execute(
            select(ControlFinding).where(ControlFinding.assessment_id == assessment_id).order_by(ControlFinding.control_id)
        )
    ).scalars().all()
    activities = (
        await db.execute(
            select(AssessmentActivity)
            .where(AssessmentActivity.assessment_id == assessment_id)
            .order_by(AssessmentActivity.control_id, AssessmentActivity.method, AssessmentActivity.id)
        )
    ).scalars().all()
    challenges = (
        await db.execute(
            select(AssessmentChallenge)
            .where(AssessmentChallenge.assessment_id == assessment_id)
            .order_by(AssessmentChallenge.control_id, AssessmentChallenge.id)
        )
    ).scalars().all()
    tailoring = (
        await db.execute(
            select(AssessmentTailoringDecision)
            .where(AssessmentTailoringDecision.assessment_id == assessment_id)
            .order_by(AssessmentTailoringDecision.control_id, AssessmentTailoringDecision.id)
        )
    ).scalars().all()
    poams = (
        await db.execute(
            select(POAM).where(POAM.assessment_id == assessment_id).order_by(POAM.control_id, POAM.id)
        )
    ).scalars().all()
    payload = {
        "assessment": {
            "id": assessment.id,
            "status": assessment.status,
            "controls_total": assessment.controls_total,
            "controls_complete": assessment.controls_complete,
            "policy_id": assessment.policy_id,
            "policy_version": assessment.policy_version,
        },
        "plan": {
            "status": plan.status,
            "scope": plan.scope_json,
            "control_selection": plan.control_selection_json,
            "methods": plan.methods_json,
            "objects": plan.objects_json,
            "depth": plan.depth,
            "coverage": plan.coverage,
            "approved_by": plan.approved_by,
            "approved_at": plan.approved_at.isoformat() if plan.approved_at else None,
        } if plan else None,
        "findings": [
            {
                "control_id": finding.control_id,
                "status": finding.status,
                "reviewer_status": finding.reviewer_status,
                "reviewed_by": finding.reviewed_by,
                "reviewed_at": finding.reviewed_at.isoformat() if finding.reviewed_at else None,
                "reviewer_note": finding.reviewer_note,
                "override_applied": finding.override_applied,
                "gaps": finding.gaps,
                "evidence_citations": finding.evidence_citations,
            }
            for finding in findings
        ],
        "activities": [
            {
                "control_id": row.control_id,
                "method": row.method,
                "objects": row.assessment_objects,
                "status": row.status,
                "result": row.result,
                "evidence_refs": row.evidence_refs,
                "performed_by": row.performed_by,
                "performed_at": row.performed_at.isoformat() if row.performed_at else None,
                "reviewed_by": row.reviewed_by,
                "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            }
            for row in activities
        ],
        "dissents": [
            {
                "control_id": row.control_id,
                "concur": row.concur,
                "resolution_status": row.resolution_status,
                "resolution_note": row.resolution_note,
                "resolved_by": row.resolved_by,
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
            }
            for row in challenges
        ],
        "tailoring": [
            {
                "control_id": row.control_id,
                "decision_type": row.decision_type,
                "parameter_id": row.parameter_id,
                "value": row.value_json,
                "rationale": row.rationale,
                "status": row.status,
                "approved_by": row.approved_by,
                "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            }
            for row in tailoring
        ],
        "poams": [
            {
                "control_id": row.control_id,
                "status": row.status,
                "owner_id": row.owner_id,
                "owner_role": row.owner_role,
                "scheduled_completion_date": row.scheduled_completion_date.isoformat() if row.scheduled_completion_date else None,
                "likelihood": row.likelihood,
                "impact": row.impact,
                "residual_risk": row.residual_risk,
                "response_strategy": row.response_strategy,
                "milestones": row.milestones,
                "acceptance_rationale": row.acceptance_rationale,
                "accepted_by": row.accepted_by,
                "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
            }
            for row in poams
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
