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
from app.services.controls.catalog import load_catalog
from app.services.human_artifact_generator import HumanAuthoringContext, build_human_authoring_context
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
            "Usage: python backend/test_harness/au_family_package_trial.py <assessment_id> [--proof]"
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
        return app_outputs / "test_harness" / "au_family_package"
    return Path(__file__).resolve().parent.parent / "outputs" / "test_harness" / "au_family_package"


def _au_policy_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This standard establishes the audit logging, audit record review, analysis, and reporting requirements used by {context.system_name} to support detection, investigation, response, and accountability."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"This standard applies to production services, administrative tooling, identity platforms, infrastructure components, security monitoring systems, retained audit records, and personnel who generate, review, analyze, or report audit information for {context.system_name}."
            ),
        },
        {"type": "heading", "level": 1, "text": "Authority and Governance"},
        {
            "type": "paragraph",
            "text": (
                "The System Owner approves this audit logging and review standard. The Security Operations Lead is designated to manage the development, documentation, dissemination, review, and update of audit logging procedures, review criteria, reporting rules, and retained records."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["Security Operations Lead", "Maintains event selection criteria, review thresholds, reporting rules, and change-in-risk adjustments."],
                ["ISSO", "Reviews audit findings, validates reporting, and tracks corrective actions."],
                ["Platform Administrator", "Implements logging settings and validates that required event types are logged."],
                ["System Owner", "Approves event logging rationale, risk-driven review adjustments, and retention exceptions."],
                ["Service Desk Lead", "Coordinates audit-related information needs tied to incident handling and user support workflows."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Policy Statements"},
        {
            "type": "bullet_list",
            "items": [
                "The event types that the system is capable of logging in support of the audit logging function are identified and documented.",
                "The event logging function is coordinated with security operations, incident response, identity management, infrastructure operations, privacy, and system ownership personnel who require audit-related information to guide the selection of events to be logged.",
                "Specified event types are selected for logging within the system and are configured to be logged in the production environment.",
                "A documented rationale is maintained to show why the selected event types are adequate to support after-the-fact investigations of incidents.",
                "Selected event types are reviewed and updated at least annually and after significant architecture, threat, tooling, regulatory, or incident-driven changes.",
                "System audit records are reviewed and analyzed each business day for indications of suspicious, inappropriate, unusual, or unauthorized activity and for the potential impact of that activity.",
                "Audit review findings are reported to the ISSO, Security Operations Lead, System Owner, and other designated response personnel.",
                "The level of audit record review, analysis, and reporting is adjusted when there is a change in risk based on law enforcement information, intelligence information, or other credible sources of information.",
                "When law enforcement information, intelligence information, or other credible sources indicate increased risk, the organization explicitly adjusts the level of audit record review, analysis, and reporting by increasing review frequency, expanding correlation rules, lowering alert thresholds, and broadening report distribution.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Defined Event Types"},
        {
            "type": "table",
            "headers": ["Event Type", "Purpose"],
            "rows": [
                ["Interactive logon and logoff events", "Support user accountability, session tracing, and incident investigation."],
                ["Privileged account use and administrative actions", "Support oversight of high-risk changes and after-the-fact investigation of misuse."],
                ["Account creation, modification, disablement, and removal", "Support user lifecycle validation and incident reconstruction."],
                ["Authentication failures and lockouts", "Support detection of brute-force and credential misuse activity."],
                ["Role, group, and entitlement changes", "Support investigation of inappropriate access changes."],
                ["Security configuration and audit setting changes", "Support validation of audit integrity and change accountability."],
                ["Network security alerts and anomalous access events", "Support incident detection, triage, and correlation."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Event Selection Rationale"},
        {
            "type": "paragraph",
            "text": (
                "The selected event types are deemed adequate to support after-the-fact investigations because they capture who performed an action, what action occurred, when it occurred, where it originated, what privileges were used, and what security-relevant changes or alerts were generated. Together, those records allow investigators to reconstruct user activity, administrative changes, authentication misuse, and incident response timelines."
            ),
        },
        {"type": "heading", "level": 1, "text": "Review and Update Requirements"},
        {
            "type": "bullet_list",
            "items": [
                "Selected event types are reviewed and updated at least annually.",
                "Selected event types are reviewed and updated following significant changes to the system, threat environment, logging infrastructure, or incident lessons learned.",
                "Daily audit review criteria, analysis thresholds, and reporting paths are updated when risk changes based on law enforcement information, intelligence information, or other credible sources of information.",
            ],
        },
    ]


def _au_technical_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "System Context"},
        {
            "type": "paragraph",
            "text": (
                f"{context.system_name} uses Microsoft Sentinel, Microsoft 365 audit logs, Active Directory security logs, Keycloak administrative events, firewall and VPN telemetry, and ServiceNow records to implement centralized audit logging and audit record review."
            ),
        },
        {"type": "heading", "level": 1, "text": "Event Logging Implementation"},
        {
            "type": "paragraph",
            "text": (
                "Interactive logon events, authentication failures, privileged actions, account lifecycle changes, entitlement changes, security configuration updates, and security alerts are configured for logging and forwarded to Microsoft Sentinel. Active Directory advanced audit settings, Keycloak event listeners, firewall telemetry export, and application security logs are enabled in production."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The event logging function is coordinated with other organizational entities requiring audit-related information. Security operations, incident response, identity management, privacy, platform engineering, and system ownership representatives review event selection criteria together during the annual logging review and after significant incidents."
            ),
        },
        {"type": "heading", "level": 1, "text": "Daily Review, Analysis, and Reporting"},
        {
            "type": "paragraph",
            "text": (
                "System audit records are reviewed and analyzed each business day for indications of suspicious, inappropriate, unusual, or unauthorized activity and for the potential impact of that activity. Analysts review Sentinel dashboards, alert queues, authentication anomaly reports, privileged action summaries, and account change reports."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Findings are reported through the daily security operations summary, immediate alert escalation tickets, and the weekly audit review package delivered to the ISSO, Security Operations Lead, System Owner, and designated response personnel."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "When there is a change in risk based on law enforcement information, intelligence information, or other credible sources of information, the level of audit record review, analysis, and reporting is adjusted by increasing review frequency, lowering alert thresholds, expanding correlation rules, and widening the set of events reported to leadership and response teams."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The level of audit record review, analysis, and reporting is explicitly adjusted when law enforcement information, intelligence information, or other credible sources indicate a change in risk. Adjustments include increased review frequency, expanded correlation content, lower alert thresholds, and broader reporting to designated officials."
            ),
        },
        {"type": "heading", "level": 1, "text": "Configured Audit Sources"},
        {
            "type": "table",
            "headers": ["Source", "Events Logged", "Review Use"],
            "rows": [
                ["Active Directory", "Logon, logoff, lockout, group membership change, privileged use", "Identity misuse review and account investigation"],
                ["Keycloak", "Authentication, token issuance, admin role assignment, session termination", "Federated identity monitoring and administrative review"],
                ["Microsoft Sentinel", "Correlated alerts, anomaly detections, incident queue events", "Daily analysis and risk-driven reporting"],
                ["Firewall and VPN telemetry", "Denied access, unusual network paths, remote access anomalies", "Threat triage and incident reconstruction"],
                ["ServiceNow", "Linked incident and change references for audit findings", "Reporting and corrective action tracking"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Event Selection Review"},
        {
            "type": "paragraph",
            "text": (
                "The event types selected for logging are reviewed and updated annually and after significant incidents, major platform changes, audit tooling changes, or threat intelligence updates. The review package records the participants, selected event types, rationale for adequacy, changes approved, and implementation verification."
            ),
        },
    ]


def _au_validation_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Review Objective"},
        {
            "type": "paragraph",
            "text": (
                f"This monthly validation review confirms that event logging, audit record review, analysis, reporting, and risk-driven review adjustments for {context.system_name} operate as designed."
            ),
        },
        {"type": "heading", "level": 1, "text": "Validation Method"},
        {
            "type": "numbered_list",
            "items": [
                "Review the current event logging standard, event selection rationale, and approved event type list.",
                "Verify that selected event types are configured and present in representative audit sources.",
                "Review daily audit analysis records for indications of suspicious, inappropriate, unusual, or unauthorized activity and the documented impact assessment.",
                "Confirm that findings were reported to the designated recipients and that risk-driven review adjustments were made when credible threat information changed the risk posture.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Representative Results"},
        {
            "type": "table",
            "headers": ["Sample", "Evidence Reviewed", "Observed Result"],
            "rows": [
                ["Privileged role assignment", "AD audit log, Keycloak admin event, Sentinel alert, ServiceNow ticket", "Specified event types were logged and supported review of the administrative change."],
                ["Authentication anomaly review", "Daily Sentinel dashboard export, analyst notes, weekly audit summary", "Audit records were reviewed and analyzed for suspicious activity and reported to designated personnel."],
                ["Risk-driven tuning update", "Threat intelligence bulletin, revised correlation rule, review notice", "Audit review frequency and alert thresholds were adjusted when credible threat information increased risk."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Conclusion"},
        {
            "type": "paragraph",
            "text": (
                "The reviewed samples confirm that loggable event types are identified, specified, configured, and reviewed on schedule; that daily audit records are reviewed and analyzed for suspicious, inappropriate, unusual, or unauthorized activity and potential impact; that findings are reported to designated recipients; and that audit review activities are adjusted when risk changes."
            ),
        },
        {"type": "heading", "level": 1, "text": "Records Retained"},
        {
            "type": "bullet_list",
            "items": [
                "Approved event type inventory and rationale worksheet",
                "Daily audit review and analysis records",
                "Weekly audit reporting package",
                "Risk-driven review adjustment approvals and implementation evidence",
            ],
        },
    ]


def _build_package_specs(context: HumanAuthoringContext) -> list[PackageDocumentSpec]:
    system_stem = _safe_stem(context.system_name.replace(" ", "_")) or "SYSTEM"
    return [
        PackageDocumentSpec(
            key="au_policy",
            title=f"{context.system_name} Audit Logging and Review Standard",
            filename=f"TEST_AUPKG_{system_stem}_Audit_Logging_and_Review_Standard.docx",
            document_type="policy",
            document_intent="implements",
            controls_addressed=["AU-2", "AU-6"],
            sections=_au_policy_sections(context),
        ),
        PackageDocumentSpec(
            key="au_technical",
            title=f"{context.system_name} Audit Logging Technical Implementation Record",
            filename=f"TEST_AUPKG_{system_stem}_Audit_Logging_Technical_Implementation_Record.docx",
            document_type="technical_artifact",
            document_intent="implements",
            controls_addressed=["AU-2", "AU-6"],
            sections=_au_technical_sections(context),
        ),
        PackageDocumentSpec(
            key="au_validation",
            title=f"{context.system_name} Audit Logging Monthly Validation Review",
            filename=f"TEST_AUPKG_{system_stem}_Audit_Logging_Monthly_Validation_Review.docx",
            document_type="technical_artifact",
            document_intent="verifies",
            controls_addressed=["AU-2", "AU-6"],
            sections=_au_validation_sections(context),
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
        name=f"AU family package trial for {', '.join(control_ids)}",
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
        "package_type": "au_family_shared_artifacts",
        "test_area": str(run_dir),
        "generated": generated,
    }

    if do_proof:
        output["proof"] = await _run_proof(
            source_assessment=assessment,
            system_context=system_context,
            control_ids=["AU-2", "AU-6"],
            evidence_doc_ids=[int(item["document_id"]) for item in generated if item.get("document_id")],
        )

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
