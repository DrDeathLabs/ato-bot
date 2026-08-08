"""OSCAL SSP export for a completed assessment snapshot."""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.orm import (
    Assessment,
    AssessmentCriteriaPackage,
    AssessmentEvidenceTriage,
    ControlFinding,
    Document,
    Project,
    SystemProfile,
    User,
)
from app.services.reports.oscal_common import (
    api_url,
    build_metadata_identities,
    catalog_id,
    frontend_url,
    iso,
    link,
    nist_baseline_profile_url,
    prop,
    resource_entry,
    stable_uuid,
)
from app.services.reports.oscal_validation import OSCAL_VERSION
from app.services.ssp_composer import compose_ssp_sections
from app.services.system_knowledge import get_latest_system_knowledge

settings = get_settings()


def _impact_value(baseline: str) -> str:
    mapping = {"low": "low", "moderate": "moderate", "high": "high"}
    return mapping.get((baseline or "").lower(), "moderate")


async def generate_oscal_ssp(assessment_id: int) -> str:
    async with AsyncSessionLocal() as db:
        assessment = await db.scalar(select(Assessment).where(Assessment.id == assessment_id))
        if assessment is None:
            raise ValueError(f"Assessment {assessment_id} not found")

        project = await db.scalar(select(Project).where(Project.id == assessment.project_id))
        if project is None:
            raise ValueError(f"Project {assessment.project_id} not found")

        system_profile = await db.scalar(select(SystemProfile).where(SystemProfile.project_id == project.id))
        findings = (
            await db.execute(
                select(ControlFinding)
                .where(ControlFinding.assessment_id == assessment_id)
                .order_by(ControlFinding.control_family, ControlFinding.control_id)
            )
        ).scalars().all()
        criteria_packages = (
            await db.execute(
                select(AssessmentCriteriaPackage)
                .where(AssessmentCriteriaPackage.assessment_id == assessment_id)
                .order_by(AssessmentCriteriaPackage.control_family, AssessmentCriteriaPackage.control_id)
            )
        ).scalars().all()
        triage_rows = (
            await db.execute(select(AssessmentEvidenceTriage).where(AssessmentEvidenceTriage.assessment_id == assessment_id))
        ).scalars().all()
        user_ids = sorted({project.owner_id, assessment.started_by})
        users = {}
        if user_ids:
            user_rows = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
            users = {user.id: user for user in user_rows}

        document_ids = sorted({row.document_id for row in triage_rows if row.document_id})
        documents = {}
        if document_ids:
            docs = (await db.execute(select(Document).where(Document.id.in_(document_ids)))).scalars().all()
            documents = {doc.id: doc for doc in docs}

        ssp_sections = await compose_ssp_sections(db, project_id=project.id)
        system_knowledge = await get_latest_system_knowledge(project.id, db)

    owner = users.get(project.owner_id)
    assessor = users.get(assessment.started_by)
    _, roles, parties, responsible_parties = build_metadata_identities(
        owner=owner,
        assessor=assessor,
        artifact_name="ssp",
    )

    tools = system_knowledge.get("tools", [])
    sections = {section["section_id"]: section for section in ssp_sections.get("sections", [])}
    architecture_section = sections.get("architecture_and_hosting", {})
    overview_section = sections.get("system_overview", {})

    system_component_uuid = stable_uuid("ssp-component", project.id, "system")
    components = [
        {
            "uuid": system_component_uuid,
            "type": "this-system",
            "title": project.name,
            "description": overview_section.get("content") or project.description or f"{project.name} assessed by ATO Bot.",
            "status": {"state": "operational"},
            "responsible-roles": [{"role-id": "system-owner", "party-uuids": [p["uuid"] for p in parties if p["type"] == "person"]}],
        }
    ]
    for index, tool in enumerate(tools[:8], start=1):
        components.append(
            {
                "uuid": stable_uuid("ssp-component", project.id, "tool", index, tool.get("tool_name")),
                "type": "service",
                "title": tool.get("tool_name") or f"Tool {index}",
                "description": f"{tool.get('tool_category') or 'Security tool'} identified through project knowledge with status {tool.get('status') or 'proposed'}.",
                "status": {"state": "operational" if tool.get("status") == "confirmed" else "other"},
                "remarks": f"Vendor: {tool.get('vendor') or 'unknown'}",
            }
        )

    findings_by_control = {finding.control_id: finding for finding in findings}
    control_sources = criteria_packages or findings
    implemented_requirements = []
    for row in control_sources:
        control_id = row.control_id
        finding = findings_by_control.get(control_id)
        description = (
            (finding.implementation_statement if finding else None)
            or getattr(row, "control_statement", None)
            or f"Implementation details for {control_id} are maintained in the assessment evidence set."
        )
        requirement = {
            "uuid": stable_uuid("ssp-implemented-requirement", assessment.id, control_id),
            "control-id": catalog_id(control_id),
            "responsible-roles": [{"role-id": "system-owner"}],
            "by-components": [
                {
                    "uuid": stable_uuid("ssp-by-component", assessment.id, control_id),
                    "component-uuid": system_component_uuid,
                    "description": description,
                }
            ],
        }
        if finding:
            requirement["props"] = [
                prop("original-control-id", control_id),
                prop("assessment-status", finding.status),
            ]
            if finding.remediation_plan:
                requirement["remarks"] = f"Current remediation plan: {finding.remediation_plan}"
        implemented_requirements.append(requirement)

    system_characteristics = {
        "system-ids": [
            {
                "identifier-type": "https://ietf.org/rfc/rfc4122",
                "id": stable_uuid("system-id", project.id),
            }
        ],
        "system-name": project.name,
        "system-name-short": project.name,
        "description": project.description or f"{project.name} is a {project.system_type or 'federal information system'} managed in ATO Bot.",
        "system-information": {
            "information-types": [
                {
                    "uuid": stable_uuid("ssp-information-type", project.id),
                    "title": f"{project.name} operational information",
                    "description": "Assessment evidence, system configuration data, and operational documentation used to support authorization decisions.",
                }
            ]
        },
        "status": {"state": "operational"},
        "authorization-boundary": {
            "description": architecture_section.get("content")
            or f"The authorization boundary includes {project.name} and its supporting assessed services.",
        },
        "responsible-parties": [rp for rp in responsible_parties if rp["role-id"] == "system-owner"],
    }
    if system_profile and system_profile.notes:
        system_characteristics["remarks"] = system_profile.notes

    system_implementation = {
        "components": components,
    }
    if sections.get("security_tooling", {}).get("content"):
        system_implementation["remarks"] = sections.get("security_tooling", {}).get("content")

    payload = {
        "system-security-plan": {
            "uuid": stable_uuid("oscal-ssp", assessment.id),
            "metadata": {
                "title": f"ATO Bot OSCAL SSP for {project.name}",
                "last-modified": iso(assessment.completed_at or assessment.started_at),
                "version": str(assessment.project_run_number),
                "oscal-version": OSCAL_VERSION,
                "roles": roles,
                "parties": parties,
                "responsible-parties": responsible_parties,
                "links": [
                    link(frontend_url(f"/projects/{project.id}/ssp-workbench"), rel="reference", text="SSP workbench"),
                    link(api_url(f"/api/projects/{project.id}/assessments/{assessment.id}/reports/oscal/status"), rel="reference", text="OSCAL validation status"),
                ],
                "props": [
                    prop("project-id", project.id),
                    prop("assessment-id", assessment.id),
                    prop("impact-baseline", project.impact_baseline),
                ],
                "remarks": "Generated by ATO Bot from project metadata, system knowledge, assessment criteria, findings, and evidence triage records.",
            },
            "import-profile": {
                "href": nist_baseline_profile_url(project.impact_baseline),
                "remarks": f"References the official NIST OSCAL baseline profile for the project's {project.impact_baseline} impact baseline.",
            },
            "system-characteristics": system_characteristics,
            "system-implementation": system_implementation,
            "control-implementation": {
                "description": "Current control implementation statements derived from the latest completed assessment and associated evidence triage.",
                "implemented-requirements": implemented_requirements,
            },
            "back-matter": {
                "resources": [
                    resource_entry(doc, description=f"SSP evidence resource for {doc.filename}")
                    for doc in documents.values()
                ]
            },
        }
    }

    output_path = Path(settings.output_dir) / f"assessment_{assessment_id}_oscal_ssp.json"
    os.makedirs(settings.output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return str(output_path)
