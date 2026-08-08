"""Assessment ATO-support rollup generation."""
from __future__ import annotations

import re

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    AssessmentChallenge,
    AssessmentEvidenceTriage,
    AssessmentRollup,
    ControlDetermination,
    ControlFinding,
)


def _manual_review_reasons_from_finding(finding: ControlFinding) -> list[str]:
    notes = finding.notes or ""
    match = re.search(r"Manual review reasons:\s*(.+)$", notes)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def _readiness_from_counts(non_compliant: int, partial: int, challenged: int, not_reviewed: int) -> str:
    if not_reviewed > 0:
        return "insufficient_evidence"
    if non_compliant >= 12 or (non_compliant >= 6 and challenged >= 8):
        return "significant_risk"
    if non_compliant > 0 or partial >= 10 or challenged >= 5:
        return "ready_with_risk"
    return "ready_for_review"


async def build_assessment_rollup(assessment_id: int, db: AsyncSession) -> AssessmentRollup:
    findings = (
        await db.execute(select(ControlFinding).where(ControlFinding.assessment_id == assessment_id))
    ).scalars().all()
    determinations = (
        await db.execute(select(ControlDetermination).where(ControlDetermination.assessment_id == assessment_id))
    ).scalars().all()
    challenges = (
        await db.execute(select(AssessmentChallenge).where(AssessmentChallenge.assessment_id == assessment_id))
    ).scalars().all()
    triage_rows = (
        await db.execute(select(AssessmentEvidenceTriage).where(AssessmentEvidenceTriage.assessment_id == assessment_id))
    ).scalars().all()

    finding_by_control = {f.control_id: f for f in findings}
    determination_by_control = {d.control_id: d for d in determinations}
    challenged_controls = [c.control_id for c in challenges if not c.concur]

    source_counts = {
        "project": 0,
        "common_control": 0,
        "policy": 0,
        "procedure": 0,
    }
    source_documents = {key: set() for key in source_counts}
    source_controls = {key: set() for key in source_counts}
    for row in triage_rows:
        if row.source_type in source_counts:
            source_counts[row.source_type] += 1
            if row.document_id:
                source_documents[row.source_type].add(row.document_id)
            if row.control_id:
                source_controls[row.source_type].add(row.control_id)

    corroboration_counts = {
        "multi_document_controls": 0,
        "multi_source_controls": 0,
        "multi_artifact_controls": 0,
    }
    for determination in determinations:
        summary = determination.objective_summary or {}
        corroboration = summary.get("corroboration") or {}
        if (corroboration.get("supporting_documents") or 0) >= 2:
            corroboration_counts["multi_document_controls"] += 1
        if len(corroboration.get("source_types") or []) >= 2:
            corroboration_counts["multi_source_controls"] += 1
        if len(corroboration.get("artifact_types") or []) >= 2:
            corroboration_counts["multi_artifact_controls"] += 1

    high_risk_controls = []
    manual_review_controls = []
    manual_review_reason_counts: dict[str, int] = {}
    for finding in findings:
        if finding.status not in {"non_compliant", "partially_compliant"}:
            summary = determination_by_control.get(finding.control_id)
            gap_count = len(finding.gaps or [])
            challenge_flag = finding.control_id in challenged_controls
            if finding.status == "non_compliant" or gap_count >= 4 or challenge_flag:
                high_risk_controls.append({
                    "control_id": finding.control_id,
                    "title": finding.control_title,
                    "status": finding.status,
                    "gap_count": gap_count,
                    "challenged": challenge_flag,
                    "confidence": finding.confidence_score,
                    "deficiency_summary": getattr(summary, "deficiency_summary", None),
                })

        if finding.needs_manual_review:
            manual_review_reasons = _manual_review_reasons_from_finding(finding)
            for reason in manual_review_reasons:
                manual_review_reason_counts[reason] = manual_review_reason_counts.get(reason, 0) + 1
            manual_review_controls.append({
                "control_id": finding.control_id,
                "title": finding.control_title,
                "status": finding.status,
                "confidence": finding.confidence_score,
                "reasons": manual_review_reasons,
            })

    high_risk_controls.sort(
        key=lambda item: (
            0 if item["status"] == "non_compliant" else 1,
            -item["gap_count"],
            item["control_id"],
        )
    )

    counts = {
        "total_controls": len(findings),
        "compliant": sum(1 for f in findings if f.status == "compliant"),
        "partially_compliant": sum(1 for f in findings if f.status == "partially_compliant"),
        "non_compliant": sum(1 for f in findings if f.status == "non_compliant"),
        "not_applicable": sum(1 for f in findings if f.status == "not_applicable"),
        "not_reviewed": sum(1 for f in findings if f.status == "not_reviewed"),
        "needs_review": len(manual_review_controls),
        "challenged": len(challenged_controls),
        "synthesized_narratives": sum(1 for f in findings if getattr(f, "synthesized_narrative", False)),
        "carried_forward": sum(1 for f in findings if getattr(f, "carried_forward", False)),
    }
    readiness = _readiness_from_counts(
        counts["non_compliant"],
        counts["partially_compliant"],
        counts["challenged"],
        counts["not_reviewed"],
    )

    residual_risk_themes = []
    if counts["non_compliant"]:
        residual_risk_themes.append(
            f"{counts['non_compliant']} control(s) remain non-compliant and require remediation before an authorization decision."
        )
    if counts["partially_compliant"]:
        residual_risk_themes.append(
            f"{counts['partially_compliant']} control(s) are only partially compliant and should be reviewed for compensating evidence or POA&M coverage."
        )
    if counts["challenged"]:
        residual_risk_themes.append(
            f"{counts['challenged']} control determination(s) have AI dissents where the review model disagreed with the automated verdict and warrant human review."
        )
    if counts["needs_review"]:
        residual_risk_themes.append(
            f"{counts['needs_review']} control(s) need assessor attention due to weak, inherited, or compensating evidence patterns."
        )
    if source_counts["project"] == 0 and sum(source_counts.values()) > 0:
        residual_risk_themes.append(
            "Assessment evidence is currently relying entirely on enterprise or inherited sources with no project-specific evidence."
        )
    if not residual_risk_themes:
        residual_risk_themes.append("No major residual risk themes were detected from the automated assessment rollup.")

    summary_json = {
        "counts": counts,
        "source_mix": source_counts,
        "source_documents": {key: len(value) for key, value in source_documents.items()},
        "source_controls": {key: len(value) for key, value in source_controls.items()},
        "corroboration": corroboration_counts,
        "high_risk_controls": high_risk_controls[:15],
        "challenged_controls": challenged_controls,
        "review_attention": {
            "count": len(manual_review_controls),
            "controls": manual_review_controls,
            "reason_counts": manual_review_reason_counts,
        },
    }

    await db.execute(delete(AssessmentRollup).where(AssessmentRollup.assessment_id == assessment_id))
    rollup = AssessmentRollup(
        assessment_id=assessment_id,
        readiness=readiness,
        summary_json=summary_json,
        residual_risk_summary=" ".join(residual_risk_themes),
    )
    db.add(rollup)
    await db.commit()
    await db.refresh(rollup)
    return rollup
