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
            "Usage: python backend/test_harness/ac_family_package_trial.py <assessment_id> [--proof]"
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
        return app_outputs / "test_harness" / "ac_family_package"
    return Path(__file__).resolve().parent.parent / "outputs" / "test_harness" / "ac_family_package"


def _ac_policy_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This standard establishes the access control policy and supporting procedures used to govern how {context.system_name} grants, reviews, modifies, monitors, and removes access to organizational resources."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"This standard applies to user accounts, privileged accounts, service accounts, temporary and emergency accounts, group-based access, remote access approvals, and access governance activities supporting the {context.system_name} environment."
            ),
        },
        {"type": "heading", "level": 1, "text": "Authority and Governance"},
        {
            "type": "paragraph",
            "text": (
                "The System Owner approves this access control policy and procedure standard and provides management commitment for access governance, account lifecycle oversight, and corrective action tracking. The Access Control Manager is designated to manage development, documentation, dissemination, and annual review of this standard."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "This standard addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance with applicable laws, directives, regulations, policies, standards, and guidelines. It is disseminated to system owners, security staff, engineering leads, service desk personnel, and supervisors through the controlled policy repository, and distribution is recorded in the document acknowledgement log."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The access control policy aligns with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The access control policy is disseminated to the organization-defined audience, including system owners, security staff, engineering leads, service desk personnel, and supervisors. Dissemination is completed through the controlled policy repository and the document acknowledgement log."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["System Owner", "Approves policy exceptions, privileged access decisions, and corrective actions."],
                ["Access Control Manager", "Maintains this standard, coordinates reviews, and tracks dissemination."],
                ["Platform Administrator", "Serves as the primary account manager for directory and application accounts and executes approved lifecycle changes."],
                ["Service Desk Lead", "Serves as alternate account manager for fulfillment tracking, notification records, and closure verification."],
                ["ISSO", "Reviews account monitoring results, quarterly validations, and compliance evidence."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Policy Statements"},
        {
            "type": "bullet_list",
            "items": [
                "Only approved named user, privileged, service, temporary, emergency, and approved shared accounts may be used in the environment.",
                "Anonymous accounts, generic personal accounts, unsponsored vendor accounts, and unmanaged local administrator accounts are prohibited.",
                "Specific individuals and roles are assigned as account managers for account issuance, modification, monitoring, disablement, and removal.",
                "Access authorizations are granted only after approved requests, role alignment review, and documented business justification.",
                "Shared or group account authenticators are changed when membership changes.",
                "Account lifecycle actions are coordinated with onboarding, transfer, and termination workflows.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Account Lifecycle Procedures"},
        {
            "type": "paragraph",
            "text": (
                f"{context.system_name} maintains documented account lifecycle procedures for creating, enabling, modifying, disabling, and removing accounts in Active Directory, Keycloak, SailPoint IdentityIQ, ServiceNow workflows, and connected authorization services. Standard user accounts require supervisor approval and ISSO concurrence. Privileged account changes require System Owner approval."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Specific individuals and roles are assigned as account managers. The Platform Administrator is the assigned account manager for directory and application accounts, and the Service Desk Lead is the assigned alternate account manager for fulfillment tracking and closure verification."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Account managers and defined parties are notified within four business hours when accounts are no longer required. When personnel termination or transfer events occur, the HR workflow creates a linked access revocation task immediately, interactive access is disabled within thirty minutes, and the account manager and ISSO are notified the same business day."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Account managers and other organization-defined parties are notified within the defined timeframe of four business hours when accounts are no longer required. The notification time, recipients, and resulting account action are recorded in the ServiceNow ticket."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Account managers and other organization-defined parties are notified within the specified timeframe of the same business day when users are terminated or transferred. The Service Desk records the notification timestamp, recipients, and resulting access action in the linked ServiceNow ticket."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Account managers and defined parties are notified within one business day when system usage or need-to-know changes for an individual require privileges to be reduced or removed. Shared or group credentials are rotated within four hours of membership removal, and the updated secret is redistributed only to remaining authorized members."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Account managers and other organization-defined parties are notified within the defined timeframe of one business day when system usage or need-to-know changes for an individual require privileges to be reduced or removed. Notification and closure evidence are retained with the approved access change record."
            ),
        },
        {"type": "heading", "level": 1, "text": "Monitoring and Review"},
        {
            "type": "paragraph",
            "text": (
                "The use of accounts is monitored through Microsoft Sentinel, Active Directory sign-in logs, Keycloak administrative events, and monthly supervisory review of account status and usage history. Account usage is monitored through centralized logging, dashboard review, alert triage, and documented analysis of account activity."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Monthly account reviews measure account activity against defined account management requirements, including ownership, approval status, privilege alignment, inactivity thresholds, and unauthorized group membership changes. Documented follow-up actions are retained in the compliance repository."
            ),
        },
        {"type": "heading", "level": 1, "text": "Review and Document Control"},
        {
            "type": "bullet_list",
            "items": [
                "The access control policy is reviewed and updated at least annually and after significant architecture, staffing, supplier, or regulatory changes.",
                "The access control policy is reviewed and updated on the organization-defined schedule of at least annually and after significant change events.",
                "The Access Control Manager maintains the change log, acknowledgement records, and annual review package.",
                "Approved updates are redistributed through the controlled repository and prior versions are retained according to records management requirements.",
            ],
        },
    ]


def _ac_technical_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "System Context"},
        {
            "type": "paragraph",
            "text": (
                f"{context.system_name} uses Active Directory, Keycloak, SailPoint IdentityIQ, ServiceNow, Microsoft Sentinel, CyberArk, and role-based access groups to implement account provisioning, authorization, monitoring, and credential protection controls."
            ),
        },
        {"type": "heading", "level": 1, "text": "Implementation Overview"},
        {
            "type": "paragraph",
            "text": (
                "Access requests are submitted through ServiceNow, approved by supervisors and control owners, fulfilled through identity administration workflows, and reconciled nightly with authoritative group membership and account records. Privileged roles are limited to approved administrators and are linked to named owners."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Platform administrators enforce access through approved role-based groups, Keycloak realm roles, conditional access controls, and application-side authorization checks. Shared or group credentials are limited to approved operational support functions and are protected in CyberArk with issuance, rotation, and retrieval logging."
            ),
        },
        {"type": "heading", "level": 1, "text": "Configuration and Control Points"},
        {
            "type": "bullet_list",
            "items": [
                "ServiceNow approval workflow records authorized users, approved privileges, and ticket-linked closure evidence.",
                "SailPoint IdentityIQ governs provisioning, deprovisioning, attestation, and role reconciliation.",
                "Active Directory and Keycloak enforce account status, role membership, and session authorization.",
                "CyberArk stores shared and privileged secrets, records retrieval, and supports time-bounded rotation.",
                "Microsoft Sentinel ingests login activity, privileged events, and anomalous access alerts for monitoring and review.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Account Monitoring and Notifications"},
        {
            "type": "paragraph",
            "text": (
                "The use of accounts is monitored through Microsoft Sentinel, Active Directory sign-in logs, and the Keycloak administrative event stream. The ISSO reviews the monthly account activity report for inactive accounts, anomalous privileged use, unauthorized group membership changes, and stale entitlements."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Notification workflows send the account manager, ISSO, supervisor, and service desk a same-day alert for personnel transfer or termination events and a one-business-day alert for need-to-know changes requiring privilege reduction. Completion of the notification and resulting action is recorded in the ServiceNow ticket."
            ),
        },
        {"type": "heading", "level": 1, "text": "Verification Activities"},
        {
            "type": "bullet_list",
            "items": [
                "Monthly account compliance review for ownership, approvals, account status, and group alignment",
                "Quarterly validation sample of privileged account approvals and deprovisioning actions",
                "Quarterly validation sample of shared credential rotation after group membership changes",
                "Review of ServiceNow, Sentinel, and identity platform records for closure evidence",
            ],
        },
        {"type": "heading", "level": 1, "text": "Evidence Retention"},
        {
            "type": "paragraph",
            "text": (
                "ServiceNow tickets, approval records, monthly account review packages, Sentinel exports, CyberArk rotation evidence, and quarterly validation samples are retained in the compliance repository according to the records retention schedule."
            ),
        },
    ]


def _ac_validation_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Review Objective"},
        {
            "type": "paragraph",
            "text": (
                f"This quarterly validation review verifies that access governance, account lifecycle management, monitoring, and shared credential rotation controls for {context.system_name} operate as designed."
            ),
        },
        {"type": "heading", "level": 1, "text": "Validation Method"},
        {
            "type": "numbered_list",
            "items": [
                "Select a sample of standard, privileged, service, temporary, and shared accounts from the current quarter.",
                "Review ServiceNow requests for approvals, assigned account manager, authorized users, and recorded privileges.",
                "Verify that transfer and termination events generated timely notifications and disablement actions.",
                "Verify shared credential rotation after group membership changes by reviewing CyberArk and ServiceNow records.",
                "Review monthly account monitoring reports and documented follow-up actions for anomalies and stale accounts.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Representative Results"},
        {
            "type": "table",
            "headers": ["Sample", "Evidence Reviewed", "Observed Result"],
            "rows": [
                ["Privileged admin account", "ServiceNow approval, SailPoint attestation, AD group membership", "Approved owner, correct role alignment, current account manager assigned."],
                ["Terminated user account", "HR offboarding task, ServiceNow revocation ticket, Sentinel sign-in history", "Interactive access disabled within 30 minutes and same-day notifications recorded."],
                ["Shared support credential", "CyberArk rotation log, ServiceNow expedited ticket, group membership change record", "Secret rotated within four hours of member removal and redistributed only to remaining authorized members."],
                ["Monthly monitoring review", "Sentinel account activity report and ISSO follow-up notes", "Inactive account and anomalous privilege change reviewed and documented in the compliance repository."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Conclusion"},
        {
            "type": "paragraph",
            "text": (
                "The reviewed samples demonstrate that access control governance, account management procedures, monitoring activities, and shared credential handling are operating in accordance with the approved policy and procedure standard. Exceptions and follow-up actions, when identified, are tracked through the corrective action process."
            ),
        },
        {"type": "heading", "level": 1, "text": "Records Retained"},
        {
            "type": "bullet_list",
            "items": [
                "Quarterly validation worksheet",
                "Sampled ServiceNow approval and revocation tickets",
                "Sentinel monitoring export and ISSO follow-up record",
                "CyberArk credential rotation evidence",
            ],
        },
    ]


def _build_package_specs(context: HumanAuthoringContext) -> list[PackageDocumentSpec]:
    system_stem = _safe_stem(context.system_name.replace(" ", "_")) or "SYSTEM"
    return [
        PackageDocumentSpec(
            key="ac_policy",
            title=f"{context.system_name} Access Control Policy and Procedure Standard",
            filename=f"TEST_ACPKG_{system_stem}_Access_Control_Policy_and_Procedure_Standard.docx",
            document_type="policy",
            document_intent="implements",
            controls_addressed=["AC-1", "AC-2"],
            sections=_ac_policy_sections(context),
        ),
        PackageDocumentSpec(
            key="ac_technical",
            title=f"{context.system_name} Access Control Technical Implementation Record",
            filename=f"TEST_ACPKG_{system_stem}_Access_Control_Technical_Implementation_Record.docx",
            document_type="technical_artifact",
            document_intent="implements",
            controls_addressed=["AC-2"],
            sections=_ac_technical_sections(context),
        ),
        PackageDocumentSpec(
            key="ac_validation",
            title=f"{context.system_name} Access Control Quarterly Validation Review",
            filename=f"TEST_ACPKG_{system_stem}_Access_Control_Quarterly_Validation_Review.docx",
            document_type="technical_artifact",
            document_intent="verifies",
            controls_addressed=["AC-1", "AC-2"],
            sections=_ac_validation_sections(context),
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
        name=f"AC family package trial for {', '.join(control_ids)}",
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
        "package_type": "ac_family_shared_artifacts",
        "test_area": str(run_dir),
        "generated": generated,
    }

    if do_proof:
        output["proof"] = await _run_proof(
            source_assessment=assessment,
            system_context=system_context,
            control_ids=["AC-1", "AC-2"],
            evidence_doc_ids=[int(item["document_id"]) for item in generated if item.get("document_id")],
        )

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
