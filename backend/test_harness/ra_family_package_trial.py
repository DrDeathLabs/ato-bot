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
            "Usage: python backend/test_harness/ra_family_package_trial.py <assessment_id> [--proof]"
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
        return app_outputs / "test_harness" / "ra_family_package"
    return Path(__file__).resolve().parent.parent / "outputs" / "test_harness" / "ra_family_package"


def _ra_policy_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This standard establishes the risk assessment policy and supporting procedures used by {context.system_name} to identify, analyze, prioritize, communicate, and track system risk, including vulnerability monitoring and scanning activities."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"This standard applies to production services, hosted applications, infrastructure components, vulnerability monitoring tools, assessment records, remediation planning, and personnel responsible for assessing and managing risk in the {context.system_name} environment."
            ),
        },
        {"type": "heading", "level": 1, "text": "Authority and Governance"},
        {
            "type": "paragraph",
            "text": (
                "The System Owner approves this risk assessment policy and procedure standard and provides management commitment for risk identification, vulnerability analysis, remediation prioritization, and periodic review. The Risk Assessment Lead is designated to manage the development, documentation, dissemination, review, and update of the risk assessment policy and procedures."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The risk assessment policy addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The risk assessment policy explicitly addresses coordination among organizational entities, including security operations, engineering, infrastructure operations, privacy, compliance, supplier management, and system ownership personnel who contribute to risk identification, vulnerability analysis, and remediation planning."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The risk assessment policy explicitly addresses compliance requirements by requiring risk assessment activities, vulnerability monitoring records, remediation decisions, and retained evidence to follow applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The risk assessment policy is consistent with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The risk assessment policy is disseminated to the organization-defined audience, including system owners, security staff, engineering leads, platform administrators, remediation owners, and executive management. Dissemination is completed through the controlled policy repository, distribution list, and recipient acknowledgement process."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Documented proof of dissemination is retained through the policy distribution list, recipient acknowledgement records, controlled repository publication history, and annual review package maintained by the Risk Assessment Lead."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["Risk Assessment Lead", "Maintains this standard, coordinates assessments, and tracks dissemination and annual review."],
                ["System Owner", "Approves risk acceptance, remediation priorities, and exceptions."],
                ["ISSO", "Reviews vulnerability analysis, retained evidence, and remediation closure records."],
                ["Infrastructure Lead", "Owns platform scanning coverage, analysis support, and remediation execution."],
                ["Service Desk Lead", "Tracks remediation tickets, communications, and closure evidence for shared findings."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Policy Statements"},
        {
            "type": "bullet_list",
            "items": [
                "The risk assessment policy addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance.",
                "The risk assessment policy is consistent with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines.",
                "The risk assessment policy is disseminated to the organization-defined audience through the controlled policy repository, formal distribution list, and recipient acknowledgement process.",
                "Risk assessment procedures are developed, documented, and disseminated to facilitate the implementation of the risk assessment policy and associated risk assessment controls.",
                "A Risk Assessment Lead is designated to manage the development, documentation, dissemination, review, and update of the risk assessment policy and procedures.",
                "The risk assessment policy is reviewed and updated at least annually and following significant system, supplier, threat, regulatory, or incident-driven changes.",
                "The risk assessment procedures are reviewed and updated at least annually and following major vulnerability discoveries, tooling changes, remediation lessons learned, or threat-driven changes.",
                "Systems and hosted applications are monitored and scanned for vulnerabilities at least weekly and when new vulnerabilities potentially affecting the system are identified and reported.",
                "Vulnerability monitoring tools and techniques are employed to automate parts of the vulnerability management process by using standards for enumerating platforms, software flaws, improper configurations, formatting checklists and test procedures, and measuring vulnerability impact.",
                "Vulnerability scan reports and results from vulnerability monitoring are analyzed.",
                "Legitimate vulnerabilities are remediated within defined timeframes in accordance with an organizational assessment of risk.",
                "Information obtained from the vulnerability monitoring process and control assessments is shared with designated personnel to help eliminate similar vulnerabilities in other systems.",
                "Vulnerability monitoring tools that include the capability to readily update the vulnerabilities to be scanned are employed.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Review and Document Control"},
        {
            "type": "bullet_list",
            "items": [
                "The risk assessment policy is reviewed and updated at least annually and after significant system, threat, supplier, or regulatory changes.",
                "The risk assessment procedures are reviewed and updated at least annually and after significant vulnerability findings, tooling changes, or lessons learned requiring workflow revision.",
                "The Risk Assessment Lead maintains the change log, acknowledgement records, annual review package, and distribution history.",
                "Approved updates are redistributed through the controlled repository and prior versions are retained according to records management requirements.",
            ],
        },
    ]


def _ra_technical_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "System Context"},
        {
            "type": "paragraph",
            "text": (
                f"{context.system_name} uses Tenable, Microsoft Defender, container image scanning, software composition analysis, configuration compliance checks, ServiceNow remediation workflows, and retained risk analysis records to implement vulnerability monitoring and scanning."
            ),
        },
        {"type": "heading", "level": 1, "text": "Vulnerability Monitoring and Scanning Implementation"},
        {
            "type": "paragraph",
            "text": (
                "Systems and hosted applications are monitored and scanned for vulnerabilities at least weekly and when new vulnerabilities potentially affecting the system are identified and reported. Internal infrastructure scanning, external perimeter scanning, authenticated host scanning, web application scanning, and image scanning are performed on the defined schedule and after significant changes."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The vulnerability monitoring process uses standards for enumerating platforms, software flaws, and improper configurations; formatting checklists and test procedures; and measuring vulnerability impact. Tool outputs are normalized using common platform, checklist, and severity formats to support automation and interoperability among tools."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Vulnerability monitoring tools use standardized enumeration schemas to automate parts of the vulnerability management process, including Common Platform Enumeration (CPE) for platforms, Common Vulnerabilities and Exposures (CVE) for software flaws, and Common Configuration Enumeration (CCE) for improper configurations."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The vulnerability monitoring process uses standardized formats for checklists and test procedures, including Security Content Automation Protocol (SCAP) content, Extensible Configuration Checklist Description Format (XCCDF), and Open Vulnerability and Assessment Language (OVAL), to facilitate interoperability among tools and automate checklist execution and test evaluation."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Vulnerability impact is measured using the Common Vulnerability Scoring System (CVSS), and that standardized impact measure is used across the monitoring toolset to support interoperable analysis, prioritization, and automated remediation workflows."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Vulnerability scan reports and results from vulnerability monitoring are analyzed by the Security Operations Lead, ISSO, and platform owners. Analysis determines legitimacy, potential impact, exploitability, affected assets, existing compensating controls, and remediation priority."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Legitimate vulnerabilities are remediated within defined timeframes in accordance with organizational risk assessment criteria: critical vulnerabilities within seven calendar days, high vulnerabilities within fifteen calendar days, moderate vulnerabilities within thirty calendar days, and low vulnerabilities within ninety calendar days unless risk acceptance is approved."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Information obtained from vulnerability monitoring and control assessments is shared with other system owners, engineering teams, and governance stakeholders through the weekly risk review, vulnerability advisory notices, and cross-system remediation bulletins to help eliminate similar vulnerabilities in other systems."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The employed vulnerability monitoring tools include the capability to readily update the vulnerabilities to be scanned through daily feed updates, plugin updates, advisory synchronization, and automated content refresh for new CVEs, configuration checks, and application signatures."
            ),
        },
        {"type": "heading", "level": 1, "text": "Configured Monitoring Sources"},
        {
            "type": "table",
            "headers": ["Source", "Coverage", "Review Use"],
            "rows": [
                ["Tenable host scanning", "Servers, network appliances, and authenticated host configurations", "Weekly vulnerability discovery and remediation prioritization"],
                ["Microsoft Defender vulnerability management", "Endpoints and platform exposure data", "Continuous monitoring and change-driven analysis"],
                ["Container and dependency scanning", "Images, packages, and software components", "Application release review and vulnerability triage"],
                ["Configuration compliance checks", "Baseline deviation and insecure settings", "Improper configuration analysis and remediation planning"],
                ["ServiceNow risk and remediation records", "Assigned remediation tasks and closure evidence", "Tracking, reporting, and cross-system sharing"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Risk-Based Review and Remediation"},
        {
            "type": "paragraph",
            "text": (
                "Weekly risk review meetings compare scan findings, exploit intelligence, asset criticality, exposure context, and compensating controls to determine remediation order, escalation needs, and risk acceptance decisions. Significant findings are entered into the risk register and tracked through closure."
            ),
        },
    ]


def _ra_validation_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Review Objective"},
        {
            "type": "paragraph",
            "text": (
                f"This monthly validation review verifies that risk assessment governance, vulnerability monitoring and scanning, analysis, remediation prioritization, and cross-system information sharing for {context.system_name} operate as designed."
            ),
        },
        {"type": "heading", "level": 1, "text": "Validation Method"},
        {
            "type": "numbered_list",
            "items": [
                "Review the current risk assessment policy and procedure standard for dissemination, annual review, and assigned governance roles.",
                "Verify that systems and hosted applications were monitored and scanned on schedule and when new potentially relevant vulnerabilities were identified.",
                "Review vulnerability scan analysis records, remediation prioritization decisions, and closure evidence.",
                "Confirm that vulnerability information was shared with designated recipients and that tools were updated with current vulnerability content.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Representative Results"},
        {
            "type": "table",
            "headers": ["Sample", "Evidence Reviewed", "Observed Result"],
            "rows": [
                ["Weekly authenticated host scan", "Tenable report, analysis notes, ServiceNow remediation record", "Vulnerabilities were detected, analyzed, prioritized, and assigned according to risk criteria."],
                ["Critical CVE advisory response", "Threat bulletin, on-demand scan, remediation escalation record", "New vulnerabilities potentially affecting the system triggered additional scanning and expedited remediation actions."],
                ["Cross-system sharing review", "Weekly risk review agenda, advisory bulletin, acknowledgement notes", "Findings were shared with designated recipients to help remove similar weaknesses from related systems."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Conclusion"},
        {
            "type": "paragraph",
            "text": (
                "The reviewed samples confirm that the risk assessment policy and procedures are approved, disseminated, and reviewed on schedule; that systems and hosted applications are monitored and scanned for vulnerabilities on the defined schedule and when new vulnerabilities are identified; that scan reports and monitoring results are analyzed; that legitimate vulnerabilities are remediated according to risk-based timeframes; that relevant information is shared with designated recipients; and that employed tools are kept current with updated vulnerability content."
            ),
        },
        {"type": "heading", "level": 1, "text": "Records Retained"},
        {
            "type": "bullet_list",
            "items": [
                "Approved risk assessment policy acknowledgement records",
                "Weekly scan reports and vulnerability analysis worksheets",
                "Risk-based remediation tickets and closure evidence",
                "Cross-system advisory notices and weekly risk review records",
            ],
        },
    ]


def _build_package_specs(context: HumanAuthoringContext) -> list[PackageDocumentSpec]:
    system_stem = _safe_stem(context.system_name.replace(" ", "_")) or "SYSTEM"
    return [
        PackageDocumentSpec(
            key="ra_policy",
            title=f"{context.system_name} Risk Assessment Policy and Procedure Standard",
            filename=f"TEST_RAPKG_{system_stem}_Risk_Assessment_Policy_and_Procedure_Standard.docx",
            document_type="policy",
            document_intent="implements",
            controls_addressed=["RA-1", "RA-5"],
            sections=_ra_policy_sections(context),
        ),
        PackageDocumentSpec(
            key="ra_technical",
            title=f"{context.system_name} Vulnerability Monitoring and Scanning Technical Implementation Record",
            filename=f"TEST_RAPKG_{system_stem}_Vulnerability_Monitoring_and_Scanning_Technical_Implementation_Record.docx",
            document_type="technical_artifact",
            document_intent="implements",
            controls_addressed=["RA-5"],
            sections=_ra_technical_sections(context),
        ),
        PackageDocumentSpec(
            key="ra_validation",
            title=f"{context.system_name} Risk Assessment Monthly Validation Review",
            filename=f"TEST_RAPKG_{system_stem}_Risk_Assessment_Monthly_Validation_Review.docx",
            document_type="technical_artifact",
            document_intent="verifies",
            controls_addressed=["RA-1", "RA-5"],
            sections=_ra_validation_sections(context),
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
        name=f"RA family package trial for {', '.join(control_ids)}",
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
        "package_type": "ra_family_shared_artifacts",
        "test_area": str(run_dir),
        "generated": generated,
    }

    if do_proof:
        output["proof"] = await _run_proof(
            source_assessment=assessment,
            system_context=system_context,
            control_ids=["RA-1", "RA-5"],
            evidence_doc_ids=[int(item["document_id"]) for item in generated if item.get("document_id")],
        )

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
