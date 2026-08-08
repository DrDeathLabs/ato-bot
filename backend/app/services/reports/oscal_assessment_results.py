"""OSCAL assessment-results export built from completed assessments."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.orm import (
    Assessment,
    AssessmentChallenge,
    AssessmentEvidenceTriage,
    AssessmentRollup,
    ControlDetermination,
    ControlFinding,
    Document,
    ObjectiveDetermination,
    Project,
    User,
)
from app.services.multistage_engine import nist_determination
from app.services.reports.oscal_common import (
    api_url,
    build_metadata_identities,
    catalog_id,
    iso,
    link,
    oscal_token,
    prop,
    resource_entry,
    stable_uuid,
)
from app.services.reports.oscal_validation import OSCAL_VERSION

settings = get_settings()


async def generate_oscal_assessment_results(assessment_id: int) -> str:
    async with AsyncSessionLocal() as db:
        assessment = await db.scalar(select(Assessment).where(Assessment.id == assessment_id))
        if assessment is None:
            raise ValueError(f"Assessment {assessment_id} not found")

        project = await db.scalar(select(Project).where(Project.id == assessment.project_id))
        if project is None:
            raise ValueError(f"Project {assessment.project_id} not found")

        user_ids = sorted({project.owner_id, assessment.started_by})
        users = {}
        if user_ids:
            user_rows = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
            users = {user.id: user for user in user_rows}

        findings = (
            await db.execute(
                select(ControlFinding)
                .where(ControlFinding.assessment_id == assessment_id)
                .order_by(ControlFinding.control_family, ControlFinding.control_id)
            )
        ).scalars().all()
        rollup = await db.scalar(
            select(AssessmentRollup).where(AssessmentRollup.assessment_id == assessment_id)
        )
        determinations = (
            await db.execute(
                select(ControlDetermination).where(ControlDetermination.assessment_id == assessment_id)
            )
        ).scalars().all()
        objective_rows = (
            await db.execute(
                select(ObjectiveDetermination).where(ObjectiveDetermination.assessment_id == assessment_id)
            )
        ).scalars().all()
        challenges = (
            await db.execute(
                select(AssessmentChallenge).where(AssessmentChallenge.assessment_id == assessment_id)
            )
        ).scalars().all()
        triage_rows = (
            await db.execute(
                select(AssessmentEvidenceTriage)
                .where(AssessmentEvidenceTriage.assessment_id == assessment_id)
                .order_by(
                    AssessmentEvidenceTriage.control_id,
                    AssessmentEvidenceTriage.sort_order,
                    AssessmentEvidenceTriage.id,
                )
            )
        ).scalars().all()

        document_ids = sorted({row.document_id for row in triage_rows if row.document_id})
        documents = {}
        if document_ids:
            docs = (
                await db.execute(select(Document).where(Document.id.in_(document_ids)))
            ).scalars().all()
            documents = {doc.id: doc for doc in docs}

    determination_by_control = {row.control_id: row for row in determinations}
    challenge_by_control = {row.control_id: row for row in challenges}
    objectives_by_control: dict[str, list[ObjectiveDetermination]] = defaultdict(list)
    triage_by_control: dict[str, list[AssessmentEvidenceTriage]] = defaultdict(list)

    for row in objective_rows:
        objectives_by_control[row.control_id].append(row)
    for row in triage_rows:
        triage_by_control[row.control_id].append(row)

    reviewed_controls = {
        "description": f"Controls reviewed in assessment {assessment.project_run_number} for {project.name}.",
        "control-selections": [
            {
                "description": "Controls evaluated by ATO Bot for this completed assessment.",
                "include-controls": [
                    {"control-id": catalog_id(finding.control_id)}
                    for finding in findings
                ],
            }
        ],
    }
    objective_ids = sorted(
        {
            row.objective_id
            for row in objective_rows
            if row.objective_id
        }
    )
    if objective_ids:
        reviewed_controls["control-objective-selections"] = [
            {
                "description": "Assessment objectives evaluated in this completed assessment.",
                "include-objectives": [{"objective-id": oscal_token(objective_id)} for objective_id in objective_ids],
            }
        ]

    observations = []
    findings_out = []
    risk_entries = []

    for finding in findings:
        control_observation_uuid = stable_uuid("assessment-observation", assessment.id, finding.control_id)
        control_determination = determination_by_control.get(finding.control_id)
        challenge = challenge_by_control.get(finding.control_id)
        triage = triage_by_control.get(finding.control_id, [])
        objectives = objectives_by_control.get(finding.control_id, [])

        relevant_evidence = []
        for row in triage:
            if not row.document_id or row.document_id not in documents:
                continue
            relevant_evidence.append(
                {
                    "href": f"#{stable_uuid('document-resource', row.document_id)}",
                    "description": row.citation_label or documents[row.document_id].filename,
                }
            )

        observation_remarks: list[str] = []
        if finding.implementation_statement:
            observation_remarks.append(f"Implementation statement: {finding.implementation_statement}")
        if control_determination and control_determination.evidence_summary:
            observation_remarks.append(f"Evidence summary: {control_determination.evidence_summary}")
        if objectives:
            objective_lines = [
                f"{row.objective_id}: {row.status} - {row.rationale or 'No rationale provided.'}"
                for row in objectives[:12]
            ]
            observation_remarks.append("Objective determinations:\n" + "\n".join(objective_lines))

        observation = {
                "uuid": control_observation_uuid,
                "title": f"{finding.control_id} assessment observation",
                "description": f"{finding.control_title}",
                "methods": ["EXAMINE"],
                "types": ["control-assessment"],
                "collected": iso(finding.tested_at or assessment.completed_at or assessment.started_at),
                "props": [
                    prop("control-id", finding.control_id),
                    prop("control-family", finding.control_family),
                    prop("status", finding.status),
                    prop("nist-determination", nist_determination(finding.status).get("label", "unknown")),
                    prop("confidence-score", finding.confidence_score or 0),
                    prop("evidence-record-count", len(triage)),
                    prop("objective-count", len(objectives)),
                    prop("challenge-concur", challenge.concur if challenge else True),
                ],
                "remarks": "\n\n".join(part for part in observation_remarks if part),
            }
        if relevant_evidence:
            observation["relevant-evidence"] = relevant_evidence
        observations.append(observation)

        if finding.status in {"partially_compliant", "non_compliant", "not_reviewed"}:
            target_row = objectives[0] if objectives else None
            target_state = "satisfied" if finding.status == "compliant" else "not-satisfied"
            target_reason = "pass" if target_state == "satisfied" else "fail"
            description_parts = []
            if finding.gaps:
                description_parts.append("Gaps:\n" + "\n".join(f"- {gap}" for gap in finding.gaps))
            if control_determination and control_determination.deficiency_summary:
                description_parts.append(control_determination.deficiency_summary)
            if challenge and not challenge.concur and challenge.dissent_note:
                description_parts.append(f"Challenge note: {challenge.dissent_note}")
            if finding.remediation_plan:
                description_parts.append(f"Suggested remediation: {finding.remediation_plan}")

            target_status = {
                "state": target_state,
                "reason": target_reason,
            }
            target_remarks = target_row.rationale if target_row else (control_determination.deficiency_summary if control_determination else None)
            if target_remarks:
                target_status["remarks"] = target_remarks

            findings_out.append(
                {
                    "uuid": stable_uuid("oscal-finding", assessment.id, finding.control_id),
                    "title": f"{finding.control_id} {finding.control_title}",
                    "description": "\n\n".join(
                        part for part in description_parts if part
                    ) or f"{finding.control_id} is currently {finding.status}.",
                    "target": {
                        "type": "objective-id" if target_row else "statement-id",
                        "target-id": oscal_token(target_row.objective_id) if target_row else catalog_id(finding.control_id),
                        "title": target_row.objective_id if target_row else finding.control_id,
                        "description": target_row.objective_text if target_row and target_row.objective_text else f"Assessment target for {finding.control_id}.",
                        "status": target_status,
                    },
                    "props": [
                        prop("control-id", finding.control_id),
                        prop("status", finding.status),
                        prop("reviewer-status", finding.reviewer_status or "unreviewed"),
                        prop("needs-manual-review", finding.needs_manual_review),
                        prop("carried-forward", finding.carried_forward),
                    ],
                    "related-observations": [
                        {"observation-uuid": control_observation_uuid}
                    ],
                    "remarks": finding.reviewer_note or finding.notes or "",
                }
            )

        if finding.status in {"partially_compliant", "non_compliant"}:
            risk_level = "moderate" if finding.status == "partially_compliant" else "high"
            risk_entries.append(
                {
                    "uuid": stable_uuid("oscal-risk", assessment.id, finding.control_id),
                    "title": f"Residual risk for {finding.control_id}",
                    "description": finding.remediation_plan
                    or (control_determination.deficiency_summary if control_determination else None)
                    or f"{finding.control_id} remains {finding.status}.",
                    "statement": finding.implementation_statement or "",
                    "status": "open",
                    "characterizations": [
                        {
                            "system": f"{settings.oscal_namespace}:risk-level",
                            "categories": [
                                {
                                    "name": "risk-level",
                                    "values": [{"name": risk_level}],
                                }
                            ],
                        }
                    ],
                    "related-observations": [{"observation-uuid": control_observation_uuid}],
                    "remarks": "Derived from the current control finding and determination state.",
                }
            )

    resources = [resource_entry(doc, description=f"Assessment evidence document {doc.filename}") for doc in documents.values()]
    owner = users.get(project.owner_id)
    assessor = users.get(assessment.started_by)
    _, roles, parties, responsible_parties = build_metadata_identities(
        owner=owner,
        assessor=assessor,
        artifact_name="assessment-results",
    )

    doc_uuid = stable_uuid("oscal-assessment-results", assessment.id)
    result_uuid = stable_uuid("oscal-assessment-result-record", assessment.id)
    now_iso = iso(assessment.completed_at or assessment.started_at)

    payload = {
        "assessment-results": {
            "uuid": doc_uuid,
            "metadata": {
                "title": f"ATO Bot OSCAL assessment results for {project.name}",
                "last-modified": now_iso,
                "version": str(assessment.project_run_number),
                "oscal-version": OSCAL_VERSION,
                "roles": roles,
                "parties": parties,
                "responsible-parties": responsible_parties,
                "links": [
                    link(api_url(f"/api/projects/{project.id}/assessments/{assessment.id}"), rel="source", text="Assessment API record"),
                    link(api_url(f"/api/projects/{project.id}/assessments/{assessment.id}/reports/oscal/assessment-plan"), rel="reference", text="Assessment plan export"),
                    link(
                        api_url(f"/api/projects/{project.id}/assessments/{assessment.id}/reports/oscal/status"),
                        rel="reference",
                        text="OSCAL validation status",
                    ),
                ],
                "props": [
                    prop("project-id", project.id),
                    prop("assessment-id", assessment.id),
                    prop("impact-baseline", project.impact_baseline),
                    prop("llm-provider", assessment.llm_provider),
                    prop("llm-model", assessment.llm_model),
                    prop("context-strategy", assessment.context_strategy),
                    prop("readiness", rollup.readiness if rollup else "unknown"),
                ],
                "remarks": (
                    "Generated by ATO Bot from stored assessment findings, control determinations, "
                    "objective determinations, evidence triage, and rollup data."
                ),
            },
            "import-ap": {
                "href": api_url(f"/api/projects/{project.id}/assessments/{assessment.id}/reports/oscal/assessment-plan"),
                "remarks": "References the OSCAL assessment plan snapshot used for this completed assessment.",
            },
            "results": [
                {
                    "uuid": result_uuid,
                    "title": assessment.name or f"Assessment {assessment.project_run_number}",
                    "description": assessment.notes
                    or f"Assessment results for {project.name} ({project.impact_baseline} baseline).",
                    "start": iso(assessment.started_at),
                    "end": iso(assessment.completed_at),
                    "reviewed-controls": reviewed_controls,
                    "props": [
                        prop("assessment-status", assessment.status),
                        prop("controls-total", len(findings)),
                        prop(
                            "non-compliant-count",
                            sum(1 for finding in findings if finding.status == "non_compliant"),
                        ),
                        prop(
                            "partially-compliant-count",
                            sum(1 for finding in findings if finding.status == "partially_compliant"),
                        ),
                    ],
                    "observations": observations,
                    "findings": findings_out,
                    "remarks": rollup.residual_risk_summary if rollup else "",
                }
            ],
            "back-matter": {
                "resources": resources,
            },
        }
    }

    output_path = Path(settings.output_dir) / f"assessment_{assessment_id}_oscal_assessment_results.json"
    os.makedirs(settings.output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return str(output_path)
