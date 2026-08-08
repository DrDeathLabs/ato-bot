from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.orm import Assessment, AssessmentPolicy, Project, SystemProfile
from app.services.assessment_pipeline import assess_control_with_assessor_pipeline, preload_evidence_index
from app.services.assessment_policy import build_policy_runtime
from app.services.closure_service import _build_project_context, _wait_for_document_index
from app.services.human_artifact_generator import HumanAuthoringContext, build_human_authoring_context
from app.services.controls.catalog import load_catalog
from app.services.llm.runtime import build_provider_for_purpose
from app.services.parsers.dispatcher import dispatch_parse
from app.services.test_dataset_generator import _build_docx, _save_doc


@dataclass(slots=True)
class PackageDocumentSpec:
    key: str
    title: str
    filename: str
    document_type: str
    document_intent: str
    controls_addressed: list[str]
    sections: list[dict[str, Any]]


def _parse_args() -> tuple[int, bool]:
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python backend/test_harness/ir_family_package_trial.py <assessment_id> [--proof]"
        )
    assessment_id = int(sys.argv[1])
    do_proof = "--proof" in sys.argv[2:]
    return assessment_id, do_proof


async def _load_context(db: AsyncSession, assessment_id: int) -> tuple[Assessment, str]:
    assessment = await db.get(
        Assessment,
        assessment_id,
        options=[selectinload(Assessment.policy)],
    )
    if assessment is None:
        raise RuntimeError(f"Assessment {assessment_id} was not found.")
    project = await db.get(Project, assessment.project_id)
    profile_result = await db.execute(select(SystemProfile).where(SystemProfile.project_id == assessment.project_id))
    profile_obj = profile_result.scalars().first()
    _system_name, system_context = _build_project_context(project, profile_obj)
    return assessment, system_context


def _safe_stem(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text).strip("_")


def _package_output_root() -> Path:
    app_outputs = Path("/app/outputs")
    if app_outputs.exists():
        return app_outputs / "test_harness" / "ir_family_package"
    return Path(__file__).resolve().parent.parent / "outputs" / "test_harness" / "ir_family_package"


def _ir_policy_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This standard establishes the incident response policy and supporting procedures used by {context.system_name} to prepare for, respond to, recover from, and learn from security incidents."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"This standard applies to production services, supporting infrastructure, administrative tooling, hosted data, vendor-supported components, incident responders, system owners, and operational teams responsible for restoring the {context.system_name} environment after a security incident."
            ),
        },
        {"type": "heading", "level": 1, "text": "Authority and Governance"},
        {
            "type": "paragraph",
            "text": (
                "The System Owner approves this incident response policy and procedure standard and provides management commitment for incident preparedness, response execution, recovery oversight, and corrective action tracking. The Incident Response Lead is designated to manage development, documentation, dissemination, and annual review of this standard."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Management commitment is explicitly demonstrated through formal approval of the incident response policy, assignment of accountable response roles, allocation of responder resources, and oversight of corrective actions and annual reviews."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "This incident response policy addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The incident response policy explicitly addresses coordination among organizational entities, including security operations, engineering, service desk, executive management, legal, privacy, continuity personnel, and supplier support contacts."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The incident response policy explicitly addresses responsibilities by assigning response governance, reporting, escalation, evidence handling, recovery approval, communication, and corrective action responsibilities to designated organizational roles."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The incident response policy explicitly addresses compliance requirements by requiring incident response activities, records, notifications, and retained evidence to follow applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The incident response policy addresses compliance requirements."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The incident response policy is consistent with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The incident response policy is disseminated to the organization-defined audience, including system owners, security staff, engineering leads, operations personnel, service desk personnel, and executive management. Dissemination is completed through the controlled policy repository and the document acknowledgement log."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Documented proof of dissemination is retained through the policy distribution list, recipient acknowledgement records, controlled repository publication history, and the annual review package maintained by the Incident Response Lead."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["System Owner", "Approves policy exceptions, restoration priorities, and residual risk acceptance."],
                ["Incident Response Lead", "Maintains this standard, coordinates incidents, and tracks dissemination and annual review."],
                ["ISSO", "Tracks evidence handling, reporting, and corrective action closure."],
                ["Infrastructure Lead", "Executes containment, restoration, and technical recovery activities."],
                ["Service Desk Lead", "Ensures incident intake, routing, communication records, and responder notifications are retained."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Policy Statements"},
        {
            "type": "bullet_list",
            "items": [
                "The incident response policy addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance.",
                "The incident response policy is consistent with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines.",
                "The incident response policy is disseminated to the organization-defined audience through the controlled policy repository, formal distribution list, and recipient acknowledgement process.",
                "Incident response procedures are developed, documented, and disseminated to facilitate the implementation of the incident response policy and associated incident response controls.",
                "An Incident Response Lead is designated to manage the development, documentation, dissemination, review, and update of the incident response policy and procedures.",
                "The incident response policy is reviewed and updated at least annually and following significant system, supplier, threat, regulatory, or incident-driven changes.",
                "The incident response procedures are reviewed and updated at least annually and following major incidents, tooling changes, or lessons learned requiring workflow revision.",
                "The incident response policy addresses compliance requirements and requires incident response activities, notifications, retained records, and corrective actions to follow applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines.",
                "Incident response activities are organized into preparation, detection and analysis, containment, eradication, recovery, and post-incident activity phases.",
                "Incident handling activities are coordinated with contingency planning activities and integrated with the contingency plan when incidents affect continuity operations.",
                "Incident response procedures define reporting, escalation, evidence handling, communication, recovery approval, and lessons learned requirements.",
                "Incident response records are retained and reviewed to support analysis, accountability, and corrective action closure.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Incident Response Procedures"},
        {
            "type": "paragraph",
            "text": (
                f"{context.system_name} maintains documented incident response procedures for preparation, event intake, triage, analysis, containment, eradication, recovery, reporting, and post-incident review. The procedures assign named roles, required evidence, decision points, and restoration approvals for each phase."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The incident response procedures are disseminated to the same organization-defined audience through the controlled procedure repository. Distribution and updated recipient acknowledgement are recorded when the procedures are issued or revised."
            ),
        },
        {"type": "heading", "level": 1, "text": "Review and Document Control"},
        {
            "type": "bullet_list",
            "items": [
                "The incident response policy is reviewed and updated at least annually and after significant system, supplier, threat, or regulatory changes.",
                "The incident response procedures are reviewed and updated at least annually and after major incidents, tooling changes, or lessons learned requiring workflow revision.",
                "The Incident Response Lead maintains the change log, acknowledgement records, annual review package, and distribution history.",
                "Approved updates are redistributed through the controlled repository and prior versions are retained according to records management requirements.",
            ],
        },
    ]


def _ir_handling_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This incident handling procedure defines how {context.system_name} prepares for, detects, analyzes, contains, eradicates, recovers from, and learns from security incidents."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"This procedure applies to production services, supporting infrastructure, administrative tooling, hosted data, incident response personnel, and operational teams responsible for restoring {context.system_name} after a security incident."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["Incident Response Lead", "Coordinates preparation, detection, analysis, containment, eradication, recovery, and post-incident activities."],
                ["System Owner", "Approves recovery priorities, restoration decisions, and residual risk acceptance."],
                ["Infrastructure Lead", "Executes containment, restoration, rebuild, and validation steps for affected platforms and services."],
                ["ISSO", "Tracks incident records, evidence handling, notification actions, and corrective action closure."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Incident Handling Procedure"},
        {
            "type": "paragraph",
            "text": (
                "Incident handling activities are organized into the preparation, detection and analysis, containment, eradication, recovery, and post-incident activity phases. The procedure defines required actions, decision points, approvals, and retained records for each phase."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Preparation activities establish contact rosters, response tooling, logging availability, evidence handling expectations, communication paths, and escalation criteria before an incident occurs. Detection and analysis activities validate reported events, determine scope and impact, assign severity, and create the authoritative incident record."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Incident handling activities are coordinated with contingency planning activities and integrated with the organization's contingency plan. Shared escalation criteria, synchronized communication paths, restoration priority alignment, contingency plan activation triggers, and joint decision-making are used when incidents affect continuity operations or require failover, rebuild, or service restoration."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Containment activities isolate affected hosts, accounts, sessions, or network paths to prevent additional harm while preserving evidence needed for investigation. Eradication activities remove malicious code, disable unauthorized persistence, revoke compromised credentials, correct exploited misconfigurations, and verify that the threat condition has been eliminated."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Recovery activities restore services to an approved operational state through rebuild, failover, credential reset, validation testing, data integrity checks, and staged return-to-service approvals. Recovery actions continue until affected capabilities are fully restored, monitoring confirms stable operation, and the System Owner approves closure of the recovery phase."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The intensity of incident handling activities is measured and standardized through severity criteria, response-time targets, escalation rules, and required actions for each incident category. Those standards make incident handling activities comparable and predictable across the organization because analysts, responders, and approving officials follow the same playbooks, timing thresholds, and restoration criteria."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The rigor, intensity, scope, and results of incident handling activities are comparable and predictable across the organization because all responders use the same incident categories, severity criteria, response-time targets, escalation rules, evidence requirements, recovery approvals, and closure standards."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Incident handling results are measured and analyzed each quarter by comparing severity assignment, response-time performance, containment timing, recovery timing, and corrective action closure across recent incidents. That analysis is used to demonstrate that incident handling activities are comparable and predictable across the organization."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Quarterly incident analysis specifically measures and analyzes the results of incident handling activities across the organization to confirm that outcomes are comparable and predictable."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Post-incident activities capture lessons learned, update procedures, assign corrective actions, and track completion through the incident improvement register. Significant changes to tooling, communication paths, or restoration steps are incorporated into the incident handling procedure within ten business days."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Lessons learned from incidents are incorporated into incident response procedures, responder training, and future testing activities. Corrective actions resulting from lessons learned are implemented, verified for effectiveness, and closed only after the Incident Response Lead confirms the required change has been enacted."
            ),
        },
        {"type": "heading", "level": 1, "text": "Records and Review"},
        {
            "type": "bullet_list",
            "items": [
                "Incident record with preparation, detection, analysis, containment, eradication, recovery, and closure timestamps",
                "Recovery approval and return-to-service validation record",
                "Evidence handling log and retained investigative artifacts",
                "Post-incident review summary with corrective actions and assigned owners",
            ],
        },
    ]


def _ir_validation_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Review Objective"},
        {
            "type": "paragraph",
            "text": (
                f"This quarterly validation review verifies that incident response governance, incident handling procedures, recovery coordination, and post-incident corrective action tracking for {context.system_name} operate as designed."
            ),
        },
        {"type": "heading", "level": 1, "text": "Validation Method"},
        {
            "type": "numbered_list",
            "items": [
                "Review the current incident response policy and procedure standard for dissemination, annual review, and assigned governance roles.",
                "Select recent incident tickets and validate phase execution across preparation, detection, containment, eradication, recovery, and post-incident activities.",
                "Verify that incidents affecting continuity operations used shared escalation criteria and coordinated with contingency planning activities.",
                "Confirm that recovery approvals, return-to-service checks, and lessons learned updates were documented and retained.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Representative Results"},
        {
            "type": "table",
            "headers": ["Sample", "Evidence Reviewed", "Observed Result"],
            "rows": [
                ["Major authentication outage", "Incident ticket, bridge notes, contingency coordination log", "Containment, recovery, and contingency coordination followed the approved workflow and restoration approvals were documented."],
                ["Malware investigation", "Incident record, forensic notes, eradication checklist, lessons learned summary", "Detection, containment, eradication, and post-incident actions were documented with retained evidence and assigned follow-up actions."],
                ["Policy annual review", "Policy acknowledgement log, review package, updated distribution record", "Policy and procedures were reviewed on schedule and redistributed to the defined audience with acknowledgement tracking."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Conclusion"},
        {
            "type": "paragraph",
            "text": (
                "The reviewed samples demonstrate that incident response governance, incident handling procedures, continuity coordination, recovery approvals, and post-incident improvements are operating in accordance with the approved policy and procedure standard. Exceptions and corrective actions, when identified, are tracked through the incident improvement register."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Validation confirmed that lessons learned from reviewed incidents were incorporated into updated responder procedures, training programs, and testing exercises, including tabletop scenarios, and that resulting corrective actions were implemented and verified before closure."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Validation also confirmed that lessons-learned recommendations were applied in practice: updated procedures were issued, responder briefing materials were revised, tabletop scenarios were updated, and the Incident Response Lead verified completion of each resulting corrective action before closure."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The corrective actions derived from lessons learned were fully implemented. Implementation evidence included updated procedures, completed action records, revised training materials, updated exercise scenarios, and verification by the Incident Response Lead before closure."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Quarterly incident response metrics and analysis are reported for severity assignment, response-time performance, containment timing, recovery timing, and corrective action closure across recent incidents. The resulting analysis demonstrates that incident handling results are comparable and predictable across the organization."
            ),
        },
        {"type": "heading", "level": 1, "text": "Records Retained"},
        {
            "type": "bullet_list",
            "items": [
                "Quarterly incident response validation worksheet",
                "Sampled incident tickets and bridge notes",
                "Recovery approval and return-to-service evidence",
                "Lessons learned and corrective action tracking records",
            ],
        },
    ]


def _build_package_specs(context: HumanAuthoringContext) -> list[PackageDocumentSpec]:
    system_stem = _safe_stem(context.system_name.replace(" ", "_")) or "SYSTEM"
    return [
        PackageDocumentSpec(
            key="ir_policy",
            title=f"{context.system_name} Incident Response Policy and Procedure Standard",
            filename=f"TEST_IRPKG_{system_stem}_Incident_Response_Policy_and_Procedure_Standard.docx",
            document_type="policy",
            document_intent="implements",
            controls_addressed=["IR-1", "IR-4"],
            sections=_ir_policy_sections(context),
        ),
        PackageDocumentSpec(
            key="ir_handling",
            title=f"{context.system_name} Incident Handling Standard Operating Procedure",
            filename=f"TEST_IRPKG_{system_stem}_Incident_Handling_Standard_Operating_Procedure.docx",
            document_type="procedure",
            document_intent="implements",
            controls_addressed=["IR-4"],
            sections=_ir_handling_sections(context),
        ),
        PackageDocumentSpec(
            key="ir_validation",
            title=f"{context.system_name} Incident Response Quarterly Validation Review",
            filename=f"TEST_IRPKG_{system_stem}_Incident_Response_Quarterly_Validation_Review.docx",
            document_type="technical_artifact",
            document_intent="verifies",
            controls_addressed=["IR-1", "IR-4"],
            sections=_ir_validation_sections(context),
        ),
    ]


async def _generate_package_documents(
    *,
    assessment: Assessment,
    context: HumanAuthoringContext,
    run_dir: Path,
) -> list[dict[str, Any]]:
    upload_dir = run_dir / "uploads" / str(assessment.project_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for spec in _build_package_specs(context):
        file_bytes = _build_docx(spec.title, spec.sections, context.project_name)
        doc_id = await _save_doc(
            file_bytes=file_bytes,
            filename=spec.filename,
            project_id=assessment.project_id,
            upload_dir=upload_dir,
            created_by=assessment.started_by,
            control_id=spec.controls_addressed[0],
            document_type=spec.document_type,
            document_intent=spec.document_intent,
            controls_addressed=spec.controls_addressed,
            source_assessment_id=assessment.id,
            trigger_parse=False,
        )
        parse_status = "queued"
        parse_attempts = 0
        while parse_attempts < 3:
            parse_attempts += 1
            await dispatch_parse(doc_id)
            parse_status = await _wait_for_document_index(doc_id, timeout_secs=180)
            if parse_status == "indexed":
                break

        results.append(
            {
                "key": spec.key,
                "document_id": doc_id,
                "title": spec.title,
                "filename": spec.filename,
                "document_type": spec.document_type,
                "document_intent": spec.document_intent,
                "controls_addressed": spec.controls_addressed,
                "parse_status": parse_status,
                "parse_attempts": parse_attempts,
                "storage_area": str(upload_dir),
            }
        )
    return results


async def _run_proof(
    *,
    source_assessment: Assessment,
    system_context: str,
    control_ids: list[str],
    evidence_doc_ids: list[int],
) -> dict[str, Any]:
    catalog = load_catalog()
    proof_assessment = Assessment(
        project_id=source_assessment.project_id,
        status="running",
        llm_provider=source_assessment.llm_provider,
        llm_model=source_assessment.llm_model,
        context_strategy=source_assessment.context_strategy,
        skip_stage3=source_assessment.skip_stage3,
        carry_forward_compliant=False,
        started_at=datetime.now(UTC),
        name=f"IR family package trial for {', '.join(control_ids)}",
        started_by=source_assessment.started_by,
        policy_id=source_assessment.policy_id,
        policy_version=source_assessment.policy_version,
        controls_total=len(control_ids),
        controls_complete=0,
    )

    async with AsyncSessionLocal() as db:
        db.add(proof_assessment)
        await db.flush()
        policy_record = None
        if source_assessment.policy_id:
            policy_record = await db.get(
                AssessmentPolicy,
                source_assessment.policy_id,
                options=[selectinload(AssessmentPolicy.buckets)],
            )
        policy_runtime = build_policy_runtime(policy_record)
        provider, _runtime = await build_provider_for_purpose(
            db,
            "assessment_reasoning",
            provider_name=source_assessment.llm_provider,
            model=source_assessment.llm_model,
        )
        evidence_index = await preload_evidence_index(source_assessment.project_id, evidence_doc_ids, db)

        results: list[dict[str, Any]] = []
        for control_id in control_ids:
            control = catalog[control_id.lower()]
            finding = await assess_control_with_assessor_pipeline(
                assessment_id=proof_assessment.id,
                project_id=source_assessment.project_id,
                control=control,
                system_context=system_context,
                llm=provider,
                db=db,
                evidence_index=evidence_index,
                skip_stage3=source_assessment.skip_stage3,
                policy_runtime=policy_runtime,
            )
            proof_assessment.controls_complete += 1
            await db.flush()
            results.append(
                {
                    "control_id": control_id,
                    "status": finding.status if finding else "not_reviewed",
                    "confidence": getattr(finding, "confidence", 0.0) if finding else 0.0,
                    "gaps": getattr(finding, "gaps", []) if finding else ["No result returned."],
                }
            )

        proof_assessment.status = "complete"
        proof_assessment.completed_at = datetime.now(UTC)
        await db.commit()
        return {"proof_assessment_id": proof_assessment.id, "results": results}


async def main() -> None:
    assessment_id, do_proof = _parse_args()

    async with AsyncSessionLocal() as db:
        assessment, system_context = await _load_context(db, assessment_id)
        context = await build_human_authoring_context(assessment.project_id, db)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = _package_output_root() / f"assessment_{assessment_id}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    generated = await _generate_package_documents(
        assessment=assessment,
        context=context,
        run_dir=run_dir,
    )

    output: dict[str, Any] = {
        "assessment_id": assessment_id,
        "package_type": "ir_family_shared_artifacts",
        "test_area": str(run_dir),
        "generated": generated,
    }

    if do_proof:
        output["proof"] = await _run_proof(
            source_assessment=assessment,
            system_context=system_context,
            control_ids=["IR-1", "IR-4"],
            evidence_doc_ids=[int(item["document_id"]) for item in generated if item.get("document_id")],
        )

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
