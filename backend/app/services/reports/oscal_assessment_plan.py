"""OSCAL assessment-plan export for a completed assessment snapshot."""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.orm import Assessment, ControlFinding, Document, Project, User
from app.services.reports.oscal_common import (
    api_url,
    build_metadata_identities,
    catalog_id,
    frontend_url,
    iso,
    link,
    prop,
    resource_entry,
    stable_uuid,
)
from app.services.reports.oscal_validation import OSCAL_VERSION

settings = get_settings()


async def generate_oscal_assessment_plan(assessment_id: int) -> str:
    async with AsyncSessionLocal() as db:
        assessment = await db.scalar(select(Assessment).where(Assessment.id == assessment_id))
        if assessment is None:
            raise ValueError(f"Assessment {assessment_id} not found")

        project = await db.scalar(select(Project).where(Project.id == assessment.project_id))
        if project is None:
            raise ValueError(f"Project {assessment.project_id} not found")

        findings = (
            await db.execute(
                select(ControlFinding)
                .where(ControlFinding.assessment_id == assessment_id)
                .order_by(ControlFinding.control_family, ControlFinding.control_id)
            )
        ).scalars().all()
        users = {}
        user_ids = sorted({project.owner_id, assessment.started_by})
        if user_ids:
            user_rows = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
            users = {user.id: user for user in user_rows}

        document_ids = sorted(
            {
                doc_id
                for doc_id in (citation.get("document_id") for finding in findings for citation in (finding.evidence_citations or []))
                if doc_id
            }
        )
        documents = {}
        if document_ids:
            docs = (await db.execute(select(Document).where(Document.id.in_(document_ids)))).scalars().all()
            documents = {doc.id: doc for doc in docs}

    owner = users.get(project.owner_id)
    assessor = users.get(assessment.started_by)
    org_uuid, roles, parties, responsible_parties = build_metadata_identities(
        owner=owner,
        assessor=assessor,
        artifact_name="assessment-plan",
    )
    assessment_platform_uuid = stable_uuid("assessment-platform", assessment.id)

    reviewed_controls = {
        "description": f"Controls planned for review in assessment {assessment.project_run_number} for {project.name}.",
        "control-selections": [
            {
                "description": "Control set planned for assessment review.",
                "include-controls": [{"control-id": catalog_id(finding.control_id)} for finding in findings],
            }
        ],
    }

    tasks = [
        {
            "uuid": stable_uuid("assessment-task", assessment.id, "evidence-review"),
            "type": "action",
            "title": "Review assessment evidence",
            "description": "Review evidence records, triage citations, and implementation statements supporting the selected controls.",
            "responsible-roles": [{"role-id": "assessor", "party-uuids": [p["uuid"] for p in parties if p["type"] == "person"]}],
        },
        {
            "uuid": stable_uuid("assessment-task", assessment.id, "determine-results"),
            "type": "action",
            "title": "Determine control results",
            "description": "Evaluate selected controls and record control-level findings, objective determinations, and residual risks.",
            "responsible-roles": [{"role-id": "assessor", "party-uuids": [p["uuid"] for p in parties if p["type"] == "person"]}],
        },
    ]

    assessment_plan = {
        "uuid": stable_uuid("oscal-assessment-plan", assessment.id),
        "metadata": {
            "title": f"ATO Bot OSCAL assessment plan for {project.name}",
            "last-modified": iso(assessment.completed_at or assessment.started_at),
            "version": str(assessment.project_run_number),
            "oscal-version": OSCAL_VERSION,
            "roles": roles,
            "parties": parties,
            "responsible-parties": responsible_parties,
            "links": [
                link(api_url(f"/api/projects/{project.id}/assessments/{assessment.id}"), rel="source", text="Assessment API record"),
                link(frontend_url(f"/projects/{project.id}/assessments/{assessment.id}"), rel="reference", text="Assessment workspace"),
                link(api_url(f"/api/projects/{project.id}/assessments/{assessment.id}/reports/oscal/status"), rel="reference", text="OSCAL validation status"),
            ],
            "props": [
                prop("project-id", project.id),
                prop("assessment-id", assessment.id),
                prop("impact-baseline", project.impact_baseline),
            ],
            "remarks": "Generated by ATO Bot as the formal OSCAL assessment-plan snapshot for this completed assessment run.",
        },
        "import-ssp": {
            "href": api_url(f"/api/projects/{project.id}/assessments/{assessment.id}/reports/oscal/ssp"),
            "remarks": "References the OSCAL SSP snapshot used as the basis for this assessment plan.",
        },
        "reviewed-controls": reviewed_controls,
        "assessment-subjects": [
            {
                "type": "component",
                "description": f"All in-scope components for {project.name}.",
                "include-all": {},
            }
        ],
        "assessment-assets": {
            "assessment-platforms": [
                {
                    "uuid": assessment_platform_uuid,
                    "title": "ATO Bot assessment platform",
                    "remarks": f"Assessment executed by ATO Bot using provider {assessment.llm_provider} and model {assessment.llm_model}.",
                }
            ]
        },
        "tasks": tasks,
    }
    resources = [
        resource_entry(doc, description=f"Assessment-plan evidence resource for {doc.filename}")
        for doc in documents.values()
    ]
    if resources:
        assessment_plan["back-matter"] = {"resources": resources}

    payload = {
        "assessment-plan": {
            **assessment_plan,
        }
    }

    output_path = Path(settings.output_dir) / f"assessment_{assessment_id}_oscal_assessment_plan.json"
    os.makedirs(settings.output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return str(output_path)
