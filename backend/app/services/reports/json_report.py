"""JSON machine-readable report for GRC tool integration."""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.orm import Assessment, AssessmentRollup, ControlFinding, POAM, Project

settings = get_settings()


async def generate_json(assessment_id: int) -> str:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Assessment).where(Assessment.id == assessment_id))
        assessment = result.scalar_one()
        proj_result = await db.execute(select(Project).where(Project.id == assessment.project_id))
        project = proj_result.scalar_one()
        findings_result = await db.execute(
            select(ControlFinding)
            .where(ControlFinding.assessment_id == assessment_id)
            .order_by(ControlFinding.control_family, ControlFinding.control_id)
        )
        findings = findings_result.scalars().all()
        poam_result = await db.execute(
            select(POAM).where(POAM.assessment_id == assessment_id)
        )
        poams = poam_result.scalars().all()
        rollup = await db.scalar(
            select(AssessmentRollup).where(AssessmentRollup.assessment_id == assessment_id)
        )

    # Obs 8: import NIST 800-53A determination mapping
    from app.services.multistage_engine import nist_determination

    total = len(findings)
    counts = {
        "compliant": sum(1 for f in findings if f.status == "compliant"),
        "partially_compliant": sum(1 for f in findings if f.status == "partially_compliant"),
        "non_compliant": sum(1 for f in findings if f.status == "non_compliant"),
        "not_applicable": sum(1 for f in findings if f.status == "not_applicable"),
        "not_reviewed": sum(1 for f in findings if f.status == "not_reviewed"),
    }
    # NIST 800-53A formal determination counts for ATO package consumers
    nist_counts = {
        "satisfied": sum(1 for f in findings if f.status == "compliant"),
        "other_than_satisfied": sum(1 for f in findings if f.status in ("partially_compliant", "non_compliant")),
        "not_applicable": counts["not_applicable"],
        "not_reviewed": counts["not_reviewed"],
    }

    report = {
        "schema_version": "1.1",   # Obs 8: bumped — adds nist_determination, quality flags
        "assessment": {
            "id": assessment_id,
            "project_name": project.name,
            "impact_baseline": project.impact_baseline,
            "llm_provider": assessment.llm_provider,
            "llm_model": assessment.llm_model,
            "context_strategy": assessment.context_strategy,
            "status": assessment.status,
            "started_at": assessment.started_at.isoformat() if assessment.started_at else None,
            "completed_at": assessment.completed_at.isoformat() if assessment.completed_at else None,
        },
        "summary": {
            "total_controls": total,
            # Internal working counts
            **counts,
            "compliance_score_pct": round(
                (counts["compliant"] + counts["not_applicable"]) / max(total, 1) * 100, 1
            ),
            # NIST SP 800-53A formal determination counts
            "nist_determinations": nist_counts,
            # Assessment quality indicators
            "synthesized_narrative_count": sum(
                1 for f in findings if getattr(f, "synthesized_narrative", False)
            ),
            "ai_dissent_count": sum(
                1 for f in findings if getattr(f, "llm_challenge_note", None)
            ),
        },
        "ato_rollup": {
            "readiness": rollup.readiness if rollup else None,
            "summary": rollup.summary_json if rollup else {},
            "residual_risk_summary": rollup.residual_risk_summary if rollup else None,
        },
        "findings": [
            {
                "control_id": f.control_id,
                "control_family": f.control_family,
                "control_title": f.control_title,
                # Internal working status (for analyst tools and DB)
                "status": f.status,
                # NIST SP 800-53A formal determination (for ATO package, SAR, GRC tools)
                "nist_determination": nist_determination(f.status),
                "implementation_statement": f.implementation_statement,
                "gaps": f.gaps or [],
                "evidence_citations": f.evidence_citations or [],
                "remediation_plan": f.remediation_plan,
                "confidence_score": f.confidence_score,
                "rule_signal": f.rule_signal,
                "reviewer_status": f.reviewer_status,
                "reviewer_note": f.reviewer_note,
                # Quality flags
                "synthesized_narrative": getattr(f, "synthesized_narrative", False),
                "llm_challenge_note": getattr(f, "llm_challenge_note", None),
                "carried_forward": getattr(f, "carried_forward", False),
            }
            for f in findings
        ],
        "poam": [
            {
                "poam_id": p.poam_id,
                "control_id": p.control_id,
                "finding": p.finding,
                "risk_level": p.risk_level,
                "weakness": p.weakness,
                "remediation_plan": p.remediation_plan,
                "status": p.status,
                "due_date": p.due_date.isoformat() if p.due_date else None,
            }
            for p in poams
        ],
    }

    output_path = Path(settings.output_dir) / f"assessment_{assessment_id}.json"
    os.makedirs(settings.output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return str(output_path)
