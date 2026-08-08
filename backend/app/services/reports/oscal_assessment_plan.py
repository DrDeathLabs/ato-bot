"""OSCAL assessment-plan export from the approved pre-execution plan."""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.orm import Assessment, AssessmentActivity, AssessmentPlan, Document, Project, User
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

        plan = await db.scalar(select(AssessmentPlan).where(AssessmentPlan.assessment_id == assessment_id))
        if plan is None or plan.status != "approved":
            raise ValueError(f"Assessment {assessment_id} does not have an approved plan")
        activities = (
            await db.execute(
                select(AssessmentActivity)
                .where(AssessmentActivity.assessment_id == assessment_id)
                .order_by(AssessmentActivity.method, AssessmentActivity.control_id, AssessmentActivity.id)
            )
        ).scalars().all()
        users = {}
        user_ids = sorted({project.owner_id, assessment.started_by})
        if user_ids:
            user_rows = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
            users = {user.id: user for user in user_rows}

        document_ids = sorted(set(plan.scope_json.get("document_ids") or []))
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

    control_ids = list(plan.control_selection_json.get("control_ids") or [])
    reviewed_controls = {
        "description": plan.scope_json.get("statement") or f"Approved control scope for {project.name}.",
        "control-selections": [
            {
                "description": (
                    f"Approved {plan.control_selection_json.get('baseline', project.impact_baseline)} baseline "
                    f"selection containing {len(control_ids)} controls."
                ),
                "include-controls": [{"control-id": catalog_id(control_id)} for control_id in control_ids],
            }
        ],
    }

    methods = list(plan.methods_json or [])
    tasks = []
    for method in methods:
        method_activities = [row for row in activities if row.method == method]
        tasks.append({
            "uuid": stable_uuid("assessment-task", assessment.id, method.lower()),
            "type": "action",
            "title": f"{method.title()} approved assessment objects",
            "description": (
                f"Perform {len(method_activities)} planned {method} procedures across the approved control scope. "
                f"Record results and evidence references for assessor review."
            ),
            "props": [
                prop("assessment-method", method),
                prop("planned-activity-count", len(method_activities)),
            ],
            "responsible-roles": [{"role-id": "assessor", "party-uuids": [p["uuid"] for p in parties if p["type"] == "person"]}],
        })

    assessment_plan = {
        "uuid": stable_uuid("oscal-assessment-plan", assessment.id),
        "metadata": {
            "title": f"ATO Bot OSCAL assessment plan for {project.name}",
            "last-modified": iso(plan.approved_at or plan.updated_at or plan.created_at),
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
                prop("plan-status", plan.status),
                prop("assessment-depth", plan.depth),
                prop("assessment-coverage", plan.coverage),
                prop("assessment-methods", ",".join(methods)),
            ],
            "remarks": (
                f"Approved before execution by user {plan.approved_by}. {plan.approval_note or ''}"
            ).strip(),
        },
        "import-ssp": {
            "href": api_url(f"/api/projects/{project.id}/assessments/{assessment.id}/reports/oscal/ssp"),
            "remarks": "References the OSCAL SSP snapshot used as the basis for this assessment plan.",
        },
        "reviewed-controls": reviewed_controls,
        "assessment-subjects": [
            {
                "type": "component",
                "description": "; ".join(plan.objects_json or []) or f"Approved assessment objects for {project.name}.",
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
