"""
Shared control activity logger.

Call `log_action(db, ...)` from anywhere — assessment engine, overrides API,
assessments API — to write an immutable audit entry for a control action.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import ControlActivityLog


async def log_action(
    db: AsyncSession,
    *,
    project_id: int,
    control_id: str,
    control_family: str,
    control_title: str,
    action_type: str,
    action_summary: str,
    performed_by: str,
    assessment_id: int | None = None,
    details: dict | None = None,
) -> None:
    """Insert one immutable audit log entry. Caller is responsible for db.commit()."""
    entry = ControlActivityLog(
        project_id=project_id,
        assessment_id=assessment_id,
        control_id=control_id,
        control_family=control_family[:8],
        control_title=control_title[:512],
        action_type=action_type[:64],
        action_summary=action_summary[:509] + '...' if len(action_summary) > 512 else action_summary,
        details=details,
        performed_by=performed_by[:64],
        performed_at=datetime.now(UTC),
    )
    db.add(entry)


# ── Convenience wrappers for common actions ───────────────────────────────────

async def log_llm_assessed(
    db: AsyncSession, *, project_id: int, assessment_id: int,
    control_id: str, control_family: str, control_title: str,
    status: str, confidence: float, override_applied: str | None,
) -> None:
    label = {
        "compliant": "Compliant",
        "partially_compliant": "Partially Compliant",
        "non_compliant": "Non-Compliant",
        "not_applicable": "Not Applicable",
        "not_reviewed": "Failed to Parse",
    }.get(status, status)

    extra = f" [Override: {override_applied}]" if override_applied else ""
    await log_action(
        db,
        project_id=project_id, assessment_id=assessment_id,
        control_id=control_id, control_family=control_family, control_title=control_title,
        action_type="llm_assessed",
        action_summary=f"LLM assessment completed: {label} (confidence {confidence:.0%}){extra}",
        performed_by="system",
        details={"status": status, "confidence": confidence, "override_applied": override_applied},
    )


async def log_carried_forward(
    db: AsyncSession, *, project_id: int, assessment_id: int,
    control_id: str, control_family: str, control_title: str, status: str,
) -> None:
    label = {
        "compliant": "Compliant", "partially_compliant": "Partially Compliant",
        "non_compliant": "Non-Compliant", "not_applicable": "Not Applicable",
    }.get(status, status)
    await log_action(
        db,
        project_id=project_id, assessment_id=assessment_id,
        control_id=control_id, control_family=control_family, control_title=control_title,
        action_type="carried_forward",
        action_summary=f"Finding carried forward (Satisfied — no re-assessment). Status: {label}",
        performed_by="system",
        details={"status": status},
    )


async def log_override_applied(
    db: AsyncSession, *, project_id: int, assessment_id: int,
    control_id: str, control_family: str, control_title: str,
    override_type: str, rationale: str | None,
) -> None:
    summaries = {
        "not_applicable": "Assessor override applied: marked Not Applicable",
        "inherited":      "Assessor override applied: marked Inherited from provider",
        "applicable":     "Assessor override: LLM said N/A but control forced Applicable — set to Partially Compliant",
    }
    summary = summaries.get(override_type, f"Override applied: {override_type}")
    if rationale:
        summary += f". Rationale: {rationale}"
    await log_action(
        db,
        project_id=project_id, assessment_id=assessment_id,
        control_id=control_id, control_family=control_family, control_title=control_title,
        action_type=f"override_{override_type}",
        action_summary=summary,
        performed_by="system",
        details={"override_type": override_type, "rationale": rationale},
    )
