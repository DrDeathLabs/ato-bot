from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.orm import Assessment, AssessmentPolicy, Project, SystemProfile
from app.services.assessment_pipeline import assess_control_with_assessor_pipeline, preload_evidence_index
from app.services.assessment_policy import build_policy_runtime
from app.services.closure_service import _build_project_context, _wait_for_document_index
from app.services.controls.catalog import load_catalog
from app.services.llm.runtime import build_provider_for_purpose
from app.services.parsers.dispatcher import dispatch_parse
from app.services.test_dataset_generator import _build_docx, _save_doc


PROJECT_ID = 1
SOURCE_ASSESSMENT_ID = 146
CONTROL_IDS = ["AC-1", "AC-2", "SR-1"]


def _ac1_sections() -> list[dict]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                "This standard establishes the access control policy and the operating procedures used to govern how "
                "ATO BOT authorizes, provisions, reviews, and revokes access to the production environment and supporting services."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                "This standard applies to the ATO BOT production environment, administrative interfaces, development and support tools, "
                "managed cloud services, privileged utilities, and any workforce member or contractor who is granted logical access to the system."
            ),
        },
        {"type": "heading", "level": 1, "text": "Authority and References"},
        {
            "type": "bullet_list",
            "items": [
                "FISMA, OMB Circular A-130, and the agency system authorization requirements.",
                "NIST SP 800-53 Rev. 5 and NIST SP 800-53A Rev. 5.",
                "FedRAMP Moderate baseline requirements adopted for the ATO BOT authorization package.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["System Owner", "Approves the policy, assigns accountable managers, and resolves access exceptions."],
                ["ISSO", "Maintains the policy and procedures, coordinates dissemination, and verifies annual review completion."],
                ["Platform Administrator", "Executes provisioning and revocation steps through approved workflows and maintains technical enforcement settings."],
                ["Service Desk", "Receives access requests, validates required approvals, and records fulfillment tickets and closure evidence."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Policy"},
        {
            "type": "paragraph",
            "text": (
                "ATO BOT maintains a documented access control policy that defines the purpose of access governance, the scope of covered users and systems, "
                "the roles and responsibilities for approving and administering access, management commitment to least privilege and timely revocation, "
                "coordination between security, engineering, and service operations, and the requirement to comply with applicable laws, directives, standards, "
                "and contractual obligations."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The System Owner designates the ISSO as the access control manager for development, documentation, publication, and maintenance of this policy "
                "and the related operating procedures. The current approved version is published in the controlled SharePoint policy library and distributed to "
                "engineering managers, service desk personnel, platform administrators, security staff, and contractor leads with access administration duties."
            ),
        },
        {"type": "heading", "level": 1, "text": "Operating Procedures"},
        {
            "type": "paragraph",
            "text": (
                "The access control operating procedures define how access requests are submitted, approved, provisioned, reviewed, modified, disabled, and removed. "
                "The procedures also describe how privileged access is approved, how role memberships are reviewed, how emergency access is documented, and how evidence "
                "records are retained for audit and reassessment."
            ),
        },
        {
            "type": "numbered_list",
            "items": [
                "Access requests are submitted through ServiceNow and must identify the requested role, business justification, and approving authority.",
                "Platform administrators provision access only after the ServiceNow request is approved and the request details match an authorized access profile.",
                "Monthly access reviews confirm that accounts, roles, and privileges remain aligned with approved job duties and current need-to-know.",
                "Access is revoked promptly when employment ends, responsibilities change, or a security concern requires immediate removal or reduction of privilege.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Distribution and Review"},
        {
            "type": "paragraph",
            "text": (
                "The policy and procedures are reviewed at least annually and after major system changes, significant audit findings, or material changes to the access model. "
                "Updated versions are redistributed through the controlled document library and acknowledged by affected roles during the next monthly control review cycle."
            ),
        },
        {"type": "heading", "level": 1, "text": "Document Control"},
        {
            "type": "table",
            "headers": ["Version", "Approved By", "Review Cadence", "Last Revision Trigger"],
            "rows": [
                ["4.2", "Michael Okonkwo, System Owner; Priya Venkataraman, ISSO", "Annual and after significant change", "Privilege model update for Keycloak administrative roles"],
            ],
        },
    ]


def _ac2_procedure_sections() -> list[dict]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                "This procedure governs the full lifecycle of ATO BOT user, privileged, service, temporary, emergency, shared, and group accounts."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                "The procedure applies to accounts maintained in Active Directory, Keycloak, SailPoint IdentityIQ, ServiceNow access workflows, and any connected system "
                "used to authenticate or authorize access to ATO BOT."
            ),
        },
        {"type": "heading", "level": 1, "text": "Account Types and Ownership"},
        {
            "type": "table",
            "headers": ["Category", "Status", "Owner", "Notes"],
            "rows": [
                ["Standard user accounts", "Allowed", "Business manager and platform administrator", "Assigned to named workforce members with approved duties."],
                ["Privileged administrative accounts", "Allowed", "System Owner with ISSO concurrence", "Provisioned only for designated administrators and reviewed monthly."],
                ["Service accounts", "Allowed", "Application Lead", "Mapped to documented services and stored in the service inventory."],
                ["Temporary and emergency accounts", "Allowed with conditions", "Service Desk and Platform Administrator", "Time-bounded and automatically disabled when the approved period ends."],
                ["Anonymous, generic personal, and unsponsored vendor accounts", "Prohibited", "Not applicable", "These account types are not permitted in the ATO BOT environment."],
                ["Persistent local administrator accounts outside the managed baseline", "Prohibited", "Not applicable", "Administrative access must use managed directory-backed identities."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Approval and Provisioning Workflow"},
        {
            "type": "paragraph",
            "text": (
                "The platform administrator serves as the account manager for system access records. Group and role membership must be based on documented job function, "
                "approved need-to-know, and separation-of-duties rules defined in the access catalog."
            ),
        },
        {
            "type": "numbered_list",
            "items": [
                "The requester or supervisor submits a ServiceNow access request identifying the authorized user, requested role, intended system usage, and business justification.",
                "The business owner and designated approving authority review the request before any account is created, enabled, modified, disabled, or removed.",
                "The platform administrator provisions or updates access in Active Directory, Keycloak, and SailPoint only after the approved request is recorded.",
                "The completed record is retained in ServiceNow and referenced in the monthly account compliance review.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Notifications and Periodic Review"},
        {
            "type": "paragraph",
            "text": (
                "Account managers, the ISSO, and the user’s supervisor are notified when an account is no longer required, when a user is terminated or transferred, "
                "or when a change in duties affects current need-to-know. A monthly access review verifies authorized users, group membership, privileges, and account status."
            ),
        },
        {"type": "heading", "level": 1, "text": "Shared and Group Credentials"},
        {
            "type": "paragraph",
            "text": (
                "Shared or group credentials are used only when a documented operational need has been approved and an accountable owner has been assigned. "
                "When an individual is removed from a shared-account group, the account manager opens an expedited credential rotation ticket and the platform administrator "
                "changes the password, API key, or vault secret within four hours. The updated credential is reissued only to remaining authorized members, and the completed "
                "rotation record is attached to the ServiceNow ticket and retained with the account administration evidence set."
            ),
        },
        {"type": "heading", "level": 1, "text": "Termination and Transfer Coordination"},
        {
            "type": "paragraph",
            "text": (
                "Account management is coordinated with personnel termination and transfer processes through the HR offboarding and transfer workflow. "
                "When HR records a termination in the personnel action queue, ServiceNow creates a linked access revocation task, interactive access is disabled within 30 minutes, "
                "privileged access tokens are revoked, and the system owner is notified the same business day. When a workforce member transfers roles, the current account is reviewed, "
                "obsolete group memberships are removed, new approvals are obtained for any retained access, and the completed changes are recorded in the transfer ticket."
            ),
        },
        {"type": "heading", "level": 1, "text": "Monitoring and Records"},
        {
            "type": "bullet_list",
            "items": [
                "Microsoft Sentinel monitors account activity and alerts on anomalous use of privileged and service accounts.",
                "ServiceNow is the system of record for approvals, provisioning actions, and closure evidence.",
                "Monthly review records are retained in the compliance repository for reassessment and audit support.",
            ],
        },
    ]


def _ac2_validation_sections() -> list[dict]:
    return [
        {"type": "heading", "level": 1, "text": "Review Scope"},
        {
            "type": "paragraph",
            "text": (
                "This review validates that account administration activities were completed in accordance with the approved account management procedure during Q2 FY2026."
            ),
        },
        {"type": "heading", "level": 1, "text": "Method"},
        {
            "type": "numbered_list",
            "items": [
                "Reviewed approved ServiceNow access records for account creation, modification, disabling, and removal actions.",
                "Validated three personnel action events against Active Directory disable timestamps and Keycloak role changes.",
                "Confirmed one shared credential rotation record after a group member was removed from an operational support group.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Transactions Reviewed"},
        {
            "type": "table",
            "headers": ["Record", "Event", "Observed Result", "Reviewer Conclusion"],
            "rows": [
                ["SNOW-ACC-24018", "Employee termination on 2026-03-14", "Active Directory and Keycloak access disabled 18 minutes after HR termination notice.", "Termination workflow operated within the required response window."],
                ["SNOW-ACC-24102", "Support engineer transfer to reporting team", "Legacy administrator group removed, reporting access approved and added on the same day.", "Transfer review aligned account privileges to the new role."],
                ["SNOW-SEC-11877", "Removal of contractor from shared break-glass support group", "Vault secret rotated within 2 hours and redistributed only to remaining authorized members.", "Shared credential change process was implemented as documented."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Conclusion"},
        {
            "type": "paragraph",
            "text": (
                "The reviewed records show that account lifecycle actions, separation events, transfer updates, and shared credential changes were executed through the approved workflow "
                "and retained in the system of record. No overdue revocation or unrotated shared credential was identified in the review sample."
            ),
        },
    ]


def _sr1_sections() -> list[dict]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                "This policy defines how ATO BOT manages supply chain risk associated with software, services, hosting, and third-party support used to build, operate, or maintain the system."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                "This policy applies to cloud hosting providers, managed security services, third-party software libraries, container images, build and deployment tooling, source code hosting, "
                "subcontractor support, hardware supporting the production environment, and any external supplier that can affect the confidentiality, integrity, availability, or provenance of ATO BOT."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["System Owner", "Approves the policy and accepts residual supply chain risk."],
                ["ISSO", "Coordinates policy maintenance, review, and evidence retention."],
                ["Third-Party Risk Manager", "Maintains supplier due diligence records and coordinates reassessments."],
                ["Procurement Lead", "Ensures supplier onboarding and renewal decisions include security review requirements."],
                ["DevSecOps Lead", "Reviews software component provenance, build tooling integrity, and repository controls."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Policy Statements"},
        {
            "type": "paragraph",
            "text": (
                "Management commits to identifying, evaluating, and monitoring supply chain risk before introducing new suppliers, components, or hosted services into the ATO BOT environment. "
                "Supply chain activities are coordinated among procurement, legal, security, engineering, and program leadership so that contracting actions, architecture decisions, and operational changes use the same risk criteria."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Supplier decisions and control activities must comply with applicable laws, directives, standards, contractual obligations, and agency guidance governing federal information systems. "
                "The policy is published in the controlled policy library and disseminated to procurement staff, program managers, DevSecOps personnel, legal counsel, and supplier relationship owners."
            ),
        },
        {"type": "heading", "level": 1, "text": "Procedures"},
        {
            "type": "numbered_list",
            "items": [
                "New suppliers and material service changes require documented due diligence before use in production.",
                "Critical suppliers are reassessed annually and when a significant security incident, ownership change, or service model change occurs.",
                "Software components and container images are reviewed for provenance and approved source before they are promoted into the release pipeline.",
                "Exceptions and residual risks are documented and approved by the System Owner with ISSO concurrence.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Review and Document Control"},
        {
            "type": "paragraph",
            "text": (
                "The Third-Party Risk Manager is designated to manage development, documentation, and dissemination of this policy and the related procedures. "
                "The policy is reviewed annually and after significant supplier incidents, major architecture changes, or updates to applicable federal requirements."
            ),
        },
    ]


def _human_documents() -> list[dict]:
    return [
        {
            "control_id": "AC-1",
            "title": "ATO BOT Access Control Policy and Procedure Standard",
            "filename": "HUMANPROOF_AC1_Access_Control_Policy_and_Procedure_Standard.docx",
            "document_type": "policy",
            "sections": _ac1_sections(),
        },
        {
            "control_id": "AC-2",
            "title": "ATO BOT Account Management Standard and Operating Procedure",
            "filename": "HUMANPROOF_AC2_Account_Management_Standard_and_Operating_Procedure.docx",
            "document_type": "procedure",
            "sections": _ac2_procedure_sections(),
        },
        {
            "control_id": "AC-2",
            "title": "ATO BOT Quarterly Account Administration Validation Review",
            "filename": "HUMANPROOF_AC2_Quarterly_Account_Administration_Validation_Review.docx",
            "document_type": "technical_artifact",
            "sections": _ac2_validation_sections(),
        },
        {
            "control_id": "SR-1",
            "title": "ATO BOT Supply Chain Risk Management Policy",
            "filename": "HUMANPROOF_SR1_Supply_Chain_Risk_Management_Policy.docx",
            "document_type": "policy",
            "sections": _sr1_sections(),
        },
    ]


async def _fetch_context(db: AsyncSession) -> tuple[Assessment, Project, SystemProfile | None, str, str]:
    assessment = await db.get(
        Assessment,
        SOURCE_ASSESSMENT_ID,
        options=[selectinload(Assessment.policy)],
    )
    if assessment is None:
        raise RuntimeError(f"Assessment {SOURCE_ASSESSMENT_ID} was not found.")
    if assessment.project_id != PROJECT_ID:
        raise RuntimeError("Assessment/project mismatch for shadow proof.")

    project = await db.get(Project, PROJECT_ID)
    if project is None:
        raise RuntimeError(f"Project {PROJECT_ID} was not found.")

    profile_result = await db.execute(select(SystemProfile).where(SystemProfile.project_id == PROJECT_ID))
    profile = profile_result.scalars().first()
    system_name, system_context = _build_project_context(project, profile)
    return assessment, project, profile, system_name, system_context


async def _create_documents(system_name: str, started_by: int) -> list[dict]:
    settings = get_settings()
    upload_dir = Path(settings.upload_dir) / str(PROJECT_ID)
    upload_dir.mkdir(parents=True, exist_ok=True)
    created: list[dict] = []

    for doc_spec in _human_documents():
        file_bytes = _build_docx(doc_spec["title"], doc_spec["sections"], system_name)
        doc_id = await _save_doc(
            file_bytes=file_bytes,
            filename=doc_spec["filename"],
            project_id=PROJECT_ID,
            upload_dir=upload_dir,
            created_by=started_by,
            control_id=doc_spec["control_id"],
            document_type=doc_spec["document_type"],
            document_intent="implements",
            controls_addressed=[doc_spec["control_id"]],
            source_assessment_id=SOURCE_ASSESSMENT_ID,
            trigger_parse=False,
        )
        await dispatch_parse(doc_id)
        status = await _wait_for_document_index(doc_id, timeout_secs=180)
        created.append(
            {
                "document_id": doc_id,
                "control_id": doc_spec["control_id"],
                "filename": doc_spec["filename"],
                "document_type": doc_spec["document_type"],
                "parse_status": status,
            }
        )
    return created


async def _run_shadow_assessment(
    assessment: Assessment,
    system_context: str,
    evidence_doc_ids: list[int],
) -> list[dict]:
    catalog = load_catalog()
    proof_assessment = Assessment(
        project_id=PROJECT_ID,
        status="running",
        llm_provider=assessment.llm_provider,
        llm_model=assessment.llm_model,
        context_strategy=assessment.context_strategy,
        skip_stage3=assessment.skip_stage3,
        carry_forward_compliant=False,
        started_at=datetime.now(UTC),
        name="Human-style shadow proof",
        started_by=assessment.started_by,
        policy_id=assessment.policy_id,
        policy_version=assessment.policy_version,
        controls_total=len(CONTROL_IDS),
        controls_complete=0,
    )

    async with AsyncSessionLocal() as db:
        db.add(proof_assessment)
        await db.flush()
        policy_record = None
        if assessment.policy_id:
            policy_record = await db.get(
                AssessmentPolicy,
                assessment.policy_id,
                options=[selectinload(AssessmentPolicy.buckets)],
            )
        policy_runtime = build_policy_runtime(policy_record)

        provider, _runtime = await build_provider_for_purpose(
            db,
            "assessment_reasoning",
            provider_name=assessment.llm_provider,
            model=assessment.llm_model,
        )
        evidence_index = await preload_evidence_index(PROJECT_ID, evidence_doc_ids, db)

        results: list[dict] = []
        for control_id in CONTROL_IDS:
            control = catalog[control_id.lower()]
            finding = await assess_control_with_assessor_pipeline(
                assessment_id=proof_assessment.id,
                project_id=PROJECT_ID,
                control=control,
                system_context=system_context,
                llm=provider,
                db=db,
                evidence_index=evidence_index,
                skip_stage3=assessment.skip_stage3,
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
                    "implementation_statement": getattr(finding, "implementation_statement", None) if finding else None,
                }
            )

        proof_assessment.status = "complete"
        proof_assessment.completed_at = datetime.now(UTC)
        await db.commit()
        return [
            {"proof_assessment_id": proof_assessment.id},
            *results,
        ]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        assessment, _project, _profile, system_name, system_context = await _fetch_context(db)

    created_docs = await _create_documents(system_name, assessment.started_by)
    failed = [doc for doc in created_docs if doc["parse_status"] not in {"indexed", "complete"}]
    if failed:
        print(json.dumps({"error": "One or more generated documents failed to ingest.", "documents": created_docs}, indent=2))
        return

    evidence_doc_ids = [doc["document_id"] for doc in created_docs]
    results = await _run_shadow_assessment(assessment, system_context, evidence_doc_ids)
    output = {
        "source_assessment_id": SOURCE_ASSESSMENT_ID,
        "documents": created_docs,
        "results": results,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
