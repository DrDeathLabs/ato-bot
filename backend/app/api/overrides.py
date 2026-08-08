"""Control override API — persistent per-project control lifecycle decisions."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_assessor, require_project_access, require_viewer
from app.models.orm import ControlFinding, ControlOverride
from app.models.schemas import ControlOverrideRequest, ControlOverrideResponse
from app.services.activity_log import log_action
from app.services.controls.catalog import load_catalog

router = APIRouter(
    prefix="/projects/{project_id}/overrides",
    tags=["overrides"],
    dependencies=[Depends(require_project_access)],
)


@router.get("", response_model=list[ControlOverrideResponse])
async def list_overrides(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[ControlOverrideResponse]:
    result = await db.execute(
        select(ControlOverride).where(ControlOverride.project_id == project_id)
    )
    return result.scalars().all()


@router.put("/{control_id}", response_model=ControlOverrideResponse)
async def upsert_override(
    project_id: int,
    control_id: str,
    body: ControlOverrideRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> ControlOverrideResponse:
    """Create or update the override for a control. All fields are optional — only provided fields are changed."""
    # Load control title for log messages (best-effort)
    ctrl_title, ctrl_family = await _get_control_meta(project_id, control_id, db)

    catalog_control = _resolve_catalog_control(control_id)
    if catalog_control and not catalog_control.is_assessable:
        target = ", ".join(catalog_control.incorporated_into) or "the incorporated control"
        raise HTTPException(
            status_code=409,
            detail=(
                f"{catalog_control.display_id} is withdrawn by NIST and is not user-overridable. "
                f"Assess the requirement under {target}."
            ),
        )

    result = await db.execute(
        select(ControlOverride).where(
            ControlOverride.project_id == project_id,
            ControlOverride.control_id == control_id,
        )
    )
    override = result.scalar_one_or_none()
    if not override:
        override = ControlOverride(project_id=project_id, control_id=control_id)
        db.add(override)

    username = current_user.get("username", "unknown")
    now = datetime.now(UTC)

    if body.applicability is not None or "applicability" in body.model_fields_set:
        old_app = override.applicability
        override.applicability = body.applicability
        override.applicability_rationale = body.applicability_rationale
        override.applicability_set_by = username
        override.applicability_set_at = now

        # Log the applicability change
        if body.applicability is None:
            summary = "Applicability override cleared — control returned to auto-assessment"
            atype = "override_cleared"
        elif body.applicability == "not_applicable":
            summary = "Marked Not Applicable by assessor"
            if body.applicability_rationale:
                summary += f". Rationale: {body.applicability_rationale}"
            atype = "override_not_applicable"
        elif body.applicability == "inherited":
            summary = "Marked as Inherited from provider/platform"
            if body.applicability_rationale:
                summary += f". Rationale: {body.applicability_rationale}"
            atype = "override_inherited"
        else:  # applicable
            summary = "Marked as Applicable (overriding prior N/A determination)"
            if body.applicability_rationale:
                summary += f". Rationale: {body.applicability_rationale}"
            atype = "override_applicable"

        await log_action(
            db, project_id=project_id, control_id=control_id,
            control_family=ctrl_family, control_title=ctrl_title,
            action_type=atype, action_summary=summary, performed_by=username,
            details={"old_applicability": old_app, "new_applicability": body.applicability,
                     "rationale": body.applicability_rationale},
        )

    if body.satisfied is not None:
        old_satisfied = override.satisfied
        if body.satisfied and not override.satisfied:
            snap = await _get_latest_finding_snapshot(project_id, control_id, db)
            override.satisfied_finding_snapshot = snap
        override.satisfied = body.satisfied
        override.satisfied_rationale = body.satisfied_rationale
        override.satisfied_set_by = username
        override.satisfied_set_at = now

        if body.satisfied and not old_satisfied:
            summary = "Marked as Satisfied — LLM will skip this control in future assessments, finding will carry forward"
            if body.satisfied_rationale:
                summary += f". Rationale: {body.satisfied_rationale}"
            atype = "marked_satisfied"
        else:
            summary = "Satisfied flag removed — control will be re-assessed by LLM in future runs"
            atype = "satisfied_removed"

        await log_action(
            db, project_id=project_id, control_id=control_id,
            control_family=ctrl_family, control_title=ctrl_title,
            action_type=atype, action_summary=summary, performed_by=username,
            details={"rationale": body.satisfied_rationale},
        )

    if body.risk_accepted is not None:
        old_risk = override.risk_accepted
        override.risk_accepted = body.risk_accepted
        override.risk_acceptance_rationale = body.risk_acceptance_rationale
        override.risk_accepted_by = username
        override.risk_accepted_at = now
        override.risk_acceptance_expiry = body.risk_acceptance_expiry

        if body.risk_accepted and not old_risk:
            summary = f"Risk formally accepted by {username}"
            if body.risk_acceptance_rationale:
                summary += f". Rationale: {body.risk_acceptance_rationale}"
            if body.risk_acceptance_expiry:
                summary += f". Expires: {body.risk_acceptance_expiry.strftime('%Y-%m-%d')}"
            atype = "risk_accepted"
        else:
            summary = "Risk acceptance removed"
            atype = "risk_acceptance_removed"

        await log_action(
            db, project_id=project_id, control_id=control_id,
            control_family=ctrl_family, control_title=ctrl_title,
            action_type=atype, action_summary=summary, performed_by=username,
            details={"rationale": body.risk_acceptance_rationale,
                     "expiry": body.risk_acceptance_expiry.isoformat() if body.risk_acceptance_expiry else None},
        )

    if body.clear_manual_status:
        if override.manual_status:
            old_status = override.manual_status
            override.manual_status = None
            override.manual_status_rationale = None
            override.manual_status_set_by = username
            override.manual_status_set_at = now
            await log_action(
                db, project_id=project_id, control_id=control_id,
                control_family=ctrl_family, control_title=ctrl_title,
                action_type="manual_status_cleared",
                action_summary=f"Manual status override cleared — control will be determined by LLM again (was: {old_status})",
                performed_by=username,
                details={"cleared_status": old_status},
            )
    elif body.manual_status is not None:
        old_status = override.manual_status
        override.manual_status = body.manual_status
        override.manual_status_rationale = body.manual_status_rationale
        override.manual_status_set_by = username
        override.manual_status_set_at = now
        summary = f"Status manually set to '{body.manual_status}'"
        if body.manual_status_rationale:
            summary += f". Evidence: {body.manual_status_rationale}"
        await log_action(
            db, project_id=project_id, control_id=control_id,
            control_family=ctrl_family, control_title=ctrl_title,
            action_type="manual_status_set",
            action_summary=summary,
            performed_by=username,
            details={"old_status": old_status, "new_status": body.manual_status,
                     "rationale": body.manual_status_rationale},
        )

    override.updated_at = now
    await db.commit()
    await db.refresh(override)
    return override


@router.delete("/{control_id}", status_code=204)
async def delete_override(
    project_id: int,
    control_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> None:
    """Remove all overrides for a control — returns it to auto-assessment."""
    ctrl_title, ctrl_family = await _get_control_meta(project_id, control_id, db)
    username = current_user.get("username", "unknown")

    result = await db.execute(
        select(ControlOverride).where(
            ControlOverride.project_id == project_id,
            ControlOverride.control_id == control_id,
        )
    )
    override = result.scalar_one_or_none()
    if override:
        await log_action(
            db, project_id=project_id, control_id=control_id,
            control_family=ctrl_family, control_title=ctrl_title,
            action_type="override_cleared",
            action_summary="All overrides cleared — control returned to fully automatic assessment",
            performed_by=username,
        )
        await db.delete(override)
        await db.commit()


async def _get_control_meta(project_id: int, control_id: str, db: AsyncSession) -> tuple[str, str]:
    """Return (title, family) for the most recent finding of this control, or defaults."""
    from app.models.orm import Assessment
    result = await db.execute(
        select(ControlFinding.control_title, ControlFinding.control_family)
        .join(Assessment, Assessment.id == ControlFinding.assessment_id)
        .where(Assessment.project_id == project_id, ControlFinding.control_id == control_id)
        .order_by(ControlFinding.id.desc())
        .limit(1)
    )
    row = result.first()
    if row:
        return row[0], row[1]
    catalog_control = _resolve_catalog_control(control_id)
    if catalog_control:
        return catalog_control.title, catalog_control.family_id.upper()
    family = control_id.split("-")[0].upper() if "-" in control_id else control_id[:2].upper()
    return control_id, family


def _resolve_catalog_control(control_id: str):
    normalized = (control_id or "").strip()
    if not normalized:
        return None
    catalog = load_catalog()
    by_display_id = {control.display_id: control for control in catalog.values()}
    return by_display_id.get(normalized.upper()) or catalog.get(normalized.lower())


async def _get_latest_finding_snapshot(project_id: int, control_id: str, db: AsyncSession) -> dict | None:
    """Get the most recent completed finding for a control to use as carry-forward snapshot."""
    from app.models.orm import Assessment, AssessmentPlan
    result = await db.execute(
        select(ControlFinding, AssessmentPlan.scope_json)
        .join(Assessment, Assessment.id == ControlFinding.assessment_id)
        .outerjoin(AssessmentPlan, AssessmentPlan.assessment_id == Assessment.id)
        .where(
            Assessment.project_id == project_id,
            ControlFinding.control_id == control_id,
            ControlFinding.status.notin_(["not_reviewed"]),
        )
        .order_by(ControlFinding.tested_at.desc().nullslast(), ControlFinding.id.desc())
        .limit(1)
    )
    row = result.first()
    if not row:
        return None
    finding, scope_json = row
    return {
        "status": finding.status,
        "implementation_statement": finding.implementation_statement,
        "gaps": finding.gaps,
        "evidence_citations": finding.evidence_citations,
        "remediation_plan": finding.remediation_plan,
        "confidence_score": finding.confidence_score,
        "notes": finding.notes,
        "evidence_scope_fingerprint": (scope_json or {}).get("fingerprint"),
    }
