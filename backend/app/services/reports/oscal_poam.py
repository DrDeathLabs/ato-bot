"""OSCAL POA&M export built from completed assessments and tracked POA&M entries."""
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
    AssessmentEvidenceTriage,
    ControlFinding,
    Document,
    POAM,
    Project,
    User,
)
from app.services.reports.oscal_common import (
    actor_origin,
    api_url,
    build_metadata_identities,
    catalog_id,
    iso,
    link,
    prop,
    resource_entry,
    stable_uuid,
)
from app.services.reports.oscal_validation import OSCAL_VERSION

settings = get_settings()


def _poam_status_summary(status: str | None) -> str:
    mapping = {
        "open": "planned",
        "in_progress": "partial",
        "completed": "implemented",
        "accepted_risk": "alternative",
        "closed": "implemented",
    }
    return mapping.get((status or "").lower(), "planned")


def _risk_level(rank: str | None) -> str:
    mapping = {
        "critical": "critical",
        "high": "high",
        "medium": "moderate",
        "low": "low",
    }
    return mapping.get((rank or "").lower(), "moderate")


async def generate_oscal_poam(assessment_id: int) -> str:
    async with AsyncSessionLocal() as db:
        assessment = await db.scalar(select(Assessment).where(Assessment.id == assessment_id))
        if assessment is None:
            raise ValueError(f"Assessment {assessment_id} not found")

        project = await db.scalar(select(Project).where(Project.id == assessment.project_id))
        if project is None:
            raise ValueError(f"Project {assessment.project_id} not found")

        poam_entries = (
            await db.execute(
                select(POAM)
                .where(POAM.assessment_id == assessment_id)
                .order_by(POAM.created_at.asc(), POAM.id.asc())
            )
        ).scalars().all()
        user_ids = sorted({project.owner_id, assessment.started_by, *[row.owner_id for row in poam_entries if row.owner_id]})
        users = {}
        if user_ids:
            user_rows = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
            users = {user.id: user for user in user_rows}
        findings = (
            await db.execute(
                select(ControlFinding).where(ControlFinding.assessment_id == assessment_id)
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

    findings_by_control = {row.control_id: row for row in findings}
    triage_by_control: dict[str, list[AssessmentEvidenceTriage]] = defaultdict(list)
    for row in triage_rows:
        triage_by_control[row.control_id].append(row)

    org_uuid, roles, parties, responsible_parties = build_metadata_identities(
        owner=users.get(project.owner_id),
        assessor=users.get(assessment.started_by),
        artifact_name="poam",
    )
    poam_findings = []
    poam_items = []
    observations = []

    for item in poam_entries:
        control_finding = findings_by_control.get(item.control_id)
        finding_uuid = stable_uuid("oscal-poam-finding", assessment.id, item.poam_id)
        observation_uuid = stable_uuid("oscal-poam-observation", assessment.id, item.poam_id)
        control_triage = triage_by_control.get(item.control_id, [])

        relevant_evidence = []
        for row in control_triage:
            if not row.document_id or row.document_id not in documents:
                continue
            relevant_evidence.append(
                {
                    "href": f"#{stable_uuid('document-resource', row.document_id)}",
                    "description": row.citation_label or documents[row.document_id].filename,
                }
            )

        weakness = item.weakness or (control_finding.gaps[0] if control_finding and control_finding.gaps else None)
        remediation = item.remediation_plan or (control_finding.remediation_plan if control_finding else None)

        observation_parts = []
        if item.finding:
            observation_parts.append(f"Tracked POA&M finding: {item.finding}")
        if weakness:
            observation_parts.append(f"Weakness: {weakness}")
        if remediation:
            observation_parts.append(f"Remediation plan: {remediation}")

        observation = {
            "uuid": observation_uuid,
            "title": f"{item.poam_id} supporting observation",
            "description": "\n\n".join(observation_parts) or f"Observation for {item.poam_id}.",
            "methods": ["EXAMINE"],
            "types": ["finding"],
            "collected": iso(item.updated_at or item.created_at or assessment.completed_at or assessment.started_at),
            "props": [
                prop("poam-id", item.poam_id),
                prop("control-id", item.control_id),
                prop("status", item.status),
                prop("risk-level", item.risk_level),
            ],
        }
        if relevant_evidence:
            observation["relevant-evidence"] = relevant_evidence
        observations.append(observation)

        target_status = {
            "state": "not-satisfied" if item.status != "completed" else "satisfied",
            "reason": "fail" if item.status != "completed" else "pass",
        }
        if weakness:
            target_status["remarks"] = weakness

        finding_description_parts = [
            item.finding,
            f"POA&M risk level: {item.risk_level}.",
        ]
        if weakness:
            finding_description_parts.append(f"Weakness summary: {weakness}")
        if remediation:
            finding_description_parts.append(f"Planned remediation: {remediation}")

        poam_findings.append(
            {
                "uuid": finding_uuid,
                "title": item.poam_id,
                "description": "\n\n".join(part for part in finding_description_parts if part),
                "origins": actor_origin(org_uuid),
                "target": {
                    "type": "statement-id",
                    "target-id": catalog_id(item.control_id),
                    "title": item.control_id,
                    "description": (
                        control_finding.control_title
                        if control_finding and control_finding.control_title
                        else f"Control target for {item.control_id}."
                    ),
                    "status": target_status,
                    "implementation-status": {
                        "state": _poam_status_summary(item.status),
                    },
                },
                "related-observations": [{"observation-uuid": observation_uuid}],
                "remarks": remediation or "",
            }
        )

        item_props = [
            prop("poam-id", item.poam_id),
            prop("control-id", item.control_id),
            prop("status", item.status),
            prop("risk-level", item.risk_level),
        ]
        if item.due_date:
            item_props.append(prop("due-date", item.due_date.isoformat()))
        if item.owner_id and item.owner_id in users:
            owner = users[item.owner_id]
            item_props.append(prop("owner-id", owner.id))
            item_props.append(prop("owner-username", owner.username))

        poam_item_description_parts = []
        if weakness:
            poam_item_description_parts.append(f"Weakness: {weakness}")
        if remediation:
            poam_item_description_parts.append(f"Remediation plan: {remediation}")
        else:
            poam_item_description_parts.append("Remediation planning is still required for this open item.")

        poam_item = {
            "uuid": stable_uuid("oscal-poam-item", assessment.id, item.poam_id),
            "title": f"{item.poam_id} for {item.control_id}",
            "description": "\n\n".join(poam_item_description_parts),
            "props": item_props,
            "origins": actor_origin(org_uuid),
            "related-findings": [{"finding-uuid": finding_uuid}],
            "related-observations": [{"observation-uuid": observation_uuid}],
            "remarks": item.finding,
        }
        poam_items.append(poam_item)

    resources = [resource_entry(doc, description=f"Evidence resource for {doc.filename}") for doc in documents.values()]
    doc_uuid = stable_uuid("oscal-poam", assessment.id)
    now_iso = iso(assessment.completed_at or assessment.started_at)
    payload = {
        "plan-of-action-and-milestones": {
            "uuid": doc_uuid,
            "metadata": {
                "title": f"ATO Bot OSCAL POA&M for {project.name}",
                "last-modified": now_iso,
                "version": str(assessment.project_run_number),
                "oscal-version": OSCAL_VERSION,
                "roles": roles,
                "parties": parties,
                "responsible-parties": responsible_parties,
                "links": [
                    link(api_url(f"/api/projects/{project.id}/assessments/{assessment.id}/reports/oscal/ssp"), rel="source", text="Current SSP export"),
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
                    prop("poam-count", len(poam_entries)),
                ],
                "remarks": (
                    "Generated by ATO Bot from tracked POA&M records created during assessment execution."
                ),
            },
            "import-ssp": {
                "href": api_url(f"/api/projects/{project.id}/assessments/{assessment.id}/reports/oscal/ssp"),
                "remarks": "References the OSCAL SSP snapshot associated with this assessment.",
            },
            "system-id": {
                "identifier-type": "https://ietf.org/rfc/rfc4122",
                "id": f"ato-bot-project-{project.id}",
            },
            "observations": observations,
            "findings": poam_findings,
            "poam-items": poam_items,
            "back-matter": {
                "resources": resources,
            },
        }
    }

    output_path = Path(settings.output_dir) / f"assessment_{assessment_id}_oscal_poam.json"
    os.makedirs(settings.output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return str(output_path)
