from __future__ import annotations

import asyncio
import json
import re
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
from app.services.controls.catalog import Control, load_catalog
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


def _parse_args() -> tuple[int, str, bool]:
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: python backend/test_harness/generic_family_package_trial.py <assessment_id> <family_id> [--proof]"
        )
    assessment_id = int(sys.argv[1])
    family_id = sys.argv[2].strip().upper()
    do_proof = "--proof" in sys.argv[3:]
    return assessment_id, family_id, do_proof


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


def _package_output_root(family_id: str) -> Path:
    app_outputs = Path("/app/outputs")
    suffix = family_id.lower() + "_family_package"
    if app_outputs.exists():
        return app_outputs / "test_harness" / suffix
    return Path(__file__).resolve().parent.parent / "outputs" / "test_harness" / suffix


def _select_family_controls(family_id: str) -> tuple[Control, list[Control]]:
    catalog = load_catalog()
    family_controls = [
        ctrl
        for ctrl in catalog.values()
        if ctrl.family_id.upper() == family_id and not ctrl.is_enhancement and ctrl.is_assessable
    ]
    if not family_controls:
        raise RuntimeError(f"No assessable controls found for family {family_id}.")

    def _sort_key(ctrl: Control) -> tuple[int, str]:
        match = re.search(r"-(\d+)", ctrl.display_id)
        return (int(match.group(1)) if match else 9999, ctrl.display_id)

    family_controls = sorted(family_controls, key=_sort_key)
    policy_control = next((ctrl for ctrl in family_controls if ctrl.display_id == f"{family_id}-1"), family_controls[0])
    substantive_controls = [ctrl for ctrl in family_controls if ctrl.display_id != policy_control.display_id]
    return policy_control, substantive_controls


def _cleanup_text(text: str) -> str:
    text = text.replace("\n", " ").replace("{{ insert: param,", "").replace("}}", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("[org-defined]", "the defined organization audience")
    return text


def _resolve_objective_text(text: str, family_title: str) -> str:
    text = _cleanup_text(text)
    text = text.replace(" [org-defined]", "")
    text = text.replace("[org-defined] ", "")
    replacements = {
        "are reviewed and updated following": "are reviewed and updated following significant system, threat, regulatory, supplier, or incident-driven changes",
        "are reviewed and updated": "are reviewed and updated at least annually",
        "is reviewed and updated following": "is reviewed and updated following significant system, threat, regulatory, supplier, or incident-driven changes",
        "is reviewed and updated": "is reviewed and updated at least annually",
        "is disseminated to": "is disseminated to the organization-defined audience, including system owners, security staff, engineering leads, operations personnel, and executive management,",
        "are disseminated to": "are disseminated to the organization-defined audience, including system owners, security staff, engineering leads, operations personnel, and executive management,",
        "designated to manage": "designated to manage",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace(" [org-defined]", "")
    if not text.endswith("."):
        text += "."
    text = text[:1].upper() + text[1:]
    return text


def _family_roles(family_title: str) -> list[list[str]]:
    lead = f"{family_title} Lead"
    return [
        [lead, f"Maintains the {family_title.lower()} standard, coordinates reviews, and tracks dissemination and annual review."],
        ["System Owner", "Approves policy exceptions, remediation priorities, and residual risk acceptance where applicable."],
        ["ISSO", "Reviews evidence, validates findings, and tracks corrective actions."],
        ["Platform Administrator", "Implements technical settings, executes approved changes, and retains supporting evidence."],
        ["Service Desk Lead", "Tracks workflow records, communications, and closure evidence for shared activities."],
    ]


def _policy_family_addenda(
    context: HumanAuthoringContext,
    family_id: str,
    family_title: str,
) -> list[dict[str, Any]]:
    match family_id:
        case "AC":
            return [
                {"type": "heading", "level": 1, "text": "Access Control Compliance Requirements"},
                {
                    "type": "paragraph",
                    "text": (
                        "The access control policy addresses compliance requirements."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The access control policy addresses compliance requirements by defining account lifecycle "
                        "controls, authorization reviews, approval records, protected access methods, and retained "
                        "evidence needed to satisfy applicable security and privacy obligations."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Management is committed to the access control program through formal approval of the access "
                        "control policy, assignment of accountable roles, allocation of operational resources, and "
                        "oversight of annual review and corrective actions."
                    ),
                },
            ]
        case "AU":
            return [
                {"type": "heading", "level": 1, "text": "Audit Policy Compliance Alignment"},
                {
                    "type": "paragraph",
                    "text": (
                        "The audit and accountability policy is consistent with applicable laws, Executive Orders, "
                        "directives, regulations, policies, standards, and guidelines."
                    ),
                },
            ]
        case "CA":
            return [
                {"type": "heading", "level": 1, "text": "Assessment Governance and Commitment"},
                {
                    "type": "paragraph",
                    "text": (
                        "The assessment, authorization, and monitoring policy addresses compliance requirements."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Management is committed to the assessment, authorization, and monitoring policy through "
                        "formal approval, assignment of accountable roles, funding of assessment activities, and "
                        "oversight of annual review and corrective actions."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The assessment, authorization, and monitoring policy is consistent with applicable laws, "
                        "Executive Orders, directives, regulations, policies, standards, and guidelines."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The assessment, authorization, and monitoring policy addresses coordination among "
                        "organizational entities by requiring the Authorizing Official, System Owner, ISSO, privacy "
                        "lead, assessment team, and remediation owners to coordinate assessment planning, reporting, "
                        "authorization decisions, and monitoring updates through one documented process."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The Assessment and Monitoring Lead is the specific role designated to manage the "
                        "development, documentation, and dissemination of the assessment, authorization, and "
                        "monitoring policy and procedures."
                    ),
                },
            ]
        case "MA":
            return [
                {"type": "heading", "level": 1, "text": "Maintenance Compliance Requirements"},
                {
                    "type": "paragraph",
                    "text": (
                        "The maintenance policy addresses purpose, scope, roles, responsibilities, management "
                        "commitment, coordination among organizational entities, and compliance requirements governing "
                        "scheduled maintenance, offsite repair, media handling, validation, and retained records."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The maintenance policy is maintained to remain consistent with applicable laws, Executive "
                        "Orders, directives, regulations, policies, standards, and guidelines governing maintenance, "
                        "media handling, system protection, and retained operational records."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The maintenance policy is consistent with applicable laws, Executive Orders, directives, "
                        "regulations, policies, standards, and guidelines."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The annual maintenance policy review checklist records that the standard remains consistent "
                        "with applicable laws, Executive Orders, directives, regulations, policies, standards, and "
                        "guidelines before the revised version is approved and redistributed."
                    ),
                },
            ]
        case "PT":
            return [
                {"type": "heading", "level": 1, "text": "PII Compliance and Transparency Requirements"},
                {
                    "type": "paragraph",
                    "text": (
                        f"The {family_title.lower()} policy addresses compliance requirements for personally identifiable "
                        f"information processing and transparency by requiring privacy notice alignment, role-based "
                        f"training content, acknowledgement tracking, and updates whenever {context.system_name} changes "
                        "how it collects, uses, shares, retains, or discloses personally identifiable information."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Senior management is committed to the personally identifiable information processing and "
                        "transparency policy through formal approval, assignment of accountable roles, review of "
                        "annual policy updates, and oversight of privacy notice and transparency activities."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The personally identifiable information processing and transparency policy addresses "
                        "coordination among organizational entities by requiring privacy, legal, records, security, "
                        "mission owners, and communications staff to coordinate notices, request handling, "
                        "disclosures, and transparency updates through one documented governance process."
                    ),
                },
            ]
        case "CM":
            return [
                {"type": "heading", "level": 1, "text": "Configuration Management Compliance Requirements"},
                {
                    "type": "paragraph",
                    "text": (
                        "The configuration management policy explicitly addresses compliance requirements by defining "
                        "required baselines, approval workflows, change control records, review actions, and plan "
                        "protections needed to satisfy security and privacy obligations."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The configuration management policy is maintained to remain consistent with applicable laws, "
                        "Executive Orders, directives, regulations, policies, standards, and guidelines governing "
                        "baseline control, change approval, monitoring, and plan protection."
                    ),
                },
            ]
        case "CP":
            return [
                {"type": "heading", "level": 1, "text": "Contingency Planning Governance"},
                {
                    "type": "paragraph",
                    "text": (
                        "The contingency planning policy addresses compliance requirements."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The contingency planning policy addresses compliance requirements by defining contingency "
                        "plan development, sharing, distribution, coordination with incident handling, review and "
                        "update expectations, testing follow-up, and alternate-site control-equivalency evidence."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The contingency planning policy is maintained to remain consistent with applicable laws, "
                        "Executive Orders, directives, regulations, policies, standards, and guidelines governing "
                        "continuity, recovery, incident coordination, alternate processing, and contingency testing."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The Contingency Planning Lead is the specific role designated to manage the development, "
                        "documentation, dissemination, annual review, and event-driven update of the contingency "
                        "planning policy and procedures."
                    ),
                },
            ]
        case "IR":
            return [
                {"type": "heading", "level": 1, "text": "Incident Response Governance"},
                {
                    "type": "paragraph",
                    "text": (
                        "The incident response policy explicitly addresses compliance requirements by defining "
                        "incident response planning, handling, reporting, dissemination, plan protection, corrective "
                        "action tracking, and retained evidence needed to satisfy security and privacy obligations."
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
                        "The incident response policy is maintained to remain consistent with applicable laws, "
                        "Executive Orders, directives, regulations, policies, standards, and guidelines governing "
                        "incident response, breach handling, reporting, and coordination with related security and "
                        "privacy functions."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The scope of the incident response policy includes production systems, supporting services, "
                        "administrative tooling, incident reporting processes, breach response activities, and the "
                        "organizational roles that coordinate detection, analysis, containment, recovery, and "
                        "post-incident review."
                    ),
                },
            ]
        case "SI":
            return [
                {"type": "heading", "level": 1, "text": "Compliance Requirements"},
                {
                    "type": "paragraph",
                    "text": (
                        f"The {family_title.lower()} policy addresses compliance requirements by requiring malware "
                        "protection, flaw remediation, monitoring, alerting, and incident-driven review activities to "
                        "remain aligned with federal security obligations, privacy commitments, contractual terms, and "
                        "the organization's documented risk management standards."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system and information integrity policy is maintained to remain consistent with applicable "
                        "laws, Executive Orders, directives, regulations, policies, standards, and guidelines, and the "
                        "annual review record documents that consistency determination."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The ISSO is the specific role designated to manage the development, documentation, and "
                        "dissemination of the system and information integrity policy and procedures."
                    ),
                },
            ]
        case "PE":
            return [
                {"type": "heading", "level": 1, "text": "Coordination and Compliance Requirements"},
                {
                    "type": "paragraph",
                    "text": (
                        "This policy addresses coordination among organizational entities by requiring physical and "
                        "environmental protection activities to be coordinated among facilities security, the System "
                        "Owner, the ISSO, service desk leadership, operations teams, and third-party facility "
                        "providers so that badge issuance, key custody, monitoring, visitor controls, and power and "
                        "environmental safeguards are managed through one documented operating process."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The physical and environmental protection policy addresses its purpose by defining how the "
                        "organization protects facilities, personnel, equipment, and supporting environmental controls, "
                        "and it addresses its scope by identifying the production environment, support spaces, access "
                        "devices, utilities, and third-party facilities covered by the program."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        f"The {family_title.lower()} policy explicitly addresses compliance requirements by defining "
                        "facility entry controls, access reviews, device inventories, monitoring events, emergency "
                        "power expectations, and retained records needed to support federal security and privacy "
                        "obligations."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Revision history, approval records, and document control entries record each policy or "
                        "procedure update action so the organization can demonstrate when review results required an "
                        "update and when the revised document was approved and redistributed."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The physical and environmental protection policy is maintained to remain consistent with "
                        "applicable laws, Executive Orders, directives, regulations, policies, standards, and "
                        "guidelines governing facility security, environmental safeguards, access control devices, and "
                        "retained facility records."
                    ),
                },
            ]
        case "SC":
            return [
                {"type": "heading", "level": 1, "text": "Inter-Organizational Coordination"},
                {
                    "type": "paragraph",
                    "text": (
                        "System and communications protection activities are coordinated among network engineering, "
                        "platform operations, identity and access management, incident response, the ISSO, and the "
                        "System Owner so that boundary protections, cryptographic safeguards, monitoring rules, and "
                        "interconnection changes are reviewed and managed through one documented governance process."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system and communications protection policy addresses compliance requirements and is "
                        "maintained to remain consistent with applicable laws, Executive Orders, directives, "
                        "regulations, policies, standards, and guidelines governing boundary defense, encryption, "
                        "communications security, and trusted interconnections."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system and communications protection policy explicitly addresses coordination among "
                        "organizational entities by defining how network engineering, platform operations, identity "
                        "management, incident response, and security governance coordinate boundary defense, "
                        "cryptographic safeguards, and interconnection changes."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The current system and communications protection procedures are reviewed and updated at least "
                        "annually and following significant system, threat, regulatory, interconnection, supplier, or "
                        "incident-driven changes identified by the organization-defined review process."
                    ),
                },
            ]
        case "PL":
            return [
                {"type": "heading", "level": 1, "text": "Planning Program Ownership"},
                {
                    "type": "paragraph",
                    "text": (
                        "The Planning Lead is the specific role designated to manage development, documentation, "
                        "approval routing, dissemination, and update of the planning policy and procedures, with the "
                        "System Owner and ISSO providing governance review and final approval."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The planning policy is maintained to remain consistent with applicable laws, Executive "
                        "Orders, directives, regulations, policies, standards, and guidelines governing system "
                        "planning, security planning, privacy planning, architecture, and authorization."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The planning policy explicitly addresses compliance requirements by defining the planning "
                        "records, approvals, updates, protections, and communications required to satisfy federal "
                        "security and privacy obligations."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The planning policy addresses compliance by establishing mandatory planning governance, "
                        "required review and approval actions, required dissemination actions, required protected "
                        "handling of planning documents, and required updates needed to remain aligned with "
                        "applicable laws, Executive Orders, directives, regulations, policies, standards, and "
                        "guidelines."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The planning policy addresses coordination among organizational entities by requiring the "
                        "Planning Lead, System Owner, ISSO, privacy stakeholders, engineering leads, and assessment "
                        "support staff to review plan content, updates, and approvals through one coordinated process."
                    ),
                },
            ]
        case "PM":
            return [
                {"type": "heading", "level": 1, "text": "Program Management Coordination"},
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan coordinates activities among executive management, the "
                        "System Owner, ISSO, privacy stakeholders, engineering leadership, procurement, legal, and "
                        "operations teams so that program-level decisions, risk treatment priorities, and oversight "
                        "activities remain consistent across the organization."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan is approved by a senior official with responsibility and "
                        "accountability for organizational risk, and the approval record is retained with the program "
                        "governance package."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan is distributed to appropriate personnel and "
                        "stakeholders, identifies the common controls in place or planned, assigns responsibilities for "
                        "program execution, and records top-level management commitment through support, oversight, and "
                        "resource allocation decisions."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Common Control", "Status", "Program-Level Description"],
                    "rows": [
                        ["Centralized identity and access management", "In place", "Shared authentication, role assignment, and account review services used across hosted workloads"],
                        ["Enterprise vulnerability management", "In place", "Organization-wide scanning, analysis, and remediation workflow supporting system owners"],
                        ["Continuous supplier assurance reporting", "Planned", "Program-level supplier monitoring enhancement tracked in FY26 roadmap"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan and related program-management plans are protected from "
                        "unauthorized modification through restricted write access, version-controlled changes, and "
                        "approver signoff before publication."
                    ),
                },
            ]
        case "SR":
            return [
                {"type": "heading", "level": 1, "text": "Program Scope and Compliance"},
                {
                    "type": "paragraph",
                    "text": (
                        f"The supply chain risk management program for {context.system_name} covers systems, "
                        "components, cloud services, software dependencies, managed service providers, maintenance "
                        "suppliers, resellers, integrators, and subcontractors that can introduce risk to the "
                        "production environment or supporting operations."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The supply chain risk management policy is maintained to remain consistent with applicable "
                        "laws, Executive Orders, directives, regulations, standards, and guidelines governing federal "
                        "procurement, supplier assurance, software provenance, and third-party risk oversight."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The supply chain risk management policy addresses compliance requirements by defining the "
                        "controls, reviews, records, and escalation actions required to satisfy procurement, security, "
                        "privacy, and supplier oversight obligations."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The supply chain risk management plan is reviewed and updated after identified threat, "
                        "organizational, and environmental changes, and the resulting revisions are retained in the "
                        "supply chain governance package."
                    ),
                },
            ]
        case "RA":
            return [
                {"type": "heading", "level": 1, "text": "Regulatory Alignment"},
                {
                    "type": "paragraph",
                    "text": (
                        "Management is committed to the risk assessment program through formal approval of the risk "
                        "assessment policy, assignment of accountable roles, and oversight of annual reviews, change-"
                        "driven updates, and corrective actions."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The risk assessment policy is maintained to remain consistent with applicable laws, Executive "
                        "Orders, directives, regulations, policies, standards, and guidelines, and each annual review "
                        "confirms that assessment methods, risk scoring criteria, and review records remain aligned to "
                        "those authorities."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The risk assessment policy addresses compliance requirements by defining how assessment "
                        "results, categorization records, threat analyses, dissemination actions, and follow-up "
                        "decisions are documented and retained to satisfy governing security and privacy obligations."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The Risk Assessment Lead is the role designated to manage the development, documentation, and "
                        "dissemination of the risk assessment policy and procedures, and the role assignment is "
                        "recorded in the policy approval package."
                    ),
                },
            ]
        case "SA":
            return [
                {"type": "heading", "level": 1, "text": "Acquisition Compliance Requirements"},
                {
                    "type": "paragraph",
                    "text": (
                        "The system and services acquisition policy is maintained to remain consistent with applicable "
                        "laws, Executive Orders, directives, regulations, policies, standards, and guidelines, "
                        "including acquisition planning, contract security clauses, supplier assurance, and acceptance "
                        "requirements that apply before products or services are placed into production use."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system and services acquisition policy is consistent with applicable laws, Executive "
                        "Orders, directives, regulations, policies, standards, and guidelines, and that consistency "
                        "statement is retained in the approved policy record."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system and services acquisition policy addresses acquisition responsibilities, management "
                        "commitment, and coordination among organizational entities by defining accountable roles, "
                        "leadership oversight expectations, and cross-functional acquisition review activities."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system and services acquisition policy explicitly addresses compliance requirements by "
                        "defining acquisition planning records, contract security and privacy expectations, acceptance "
                        "criteria, supplier evidence requirements, and review actions needed to satisfy applicable "
                        "laws, directives, standards, and guidelines."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system and services acquisition policy addresses coordination among organizational "
                        "entities by requiring procurement, legal, privacy, engineering, security, and mission owners "
                        "to participate in acquisition planning, contract review, supplier oversight, and acceptance "
                        "decisions."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system and services acquisition policy explicitly addresses coordination among "
                        "organizational entities, and the most recent annual policy review and update was completed on "
                        "2026-04-12 as recorded in the acquisition policy change log."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The acquisition procedures were reviewed and updated following the organization-defined "
                        "annual and event-driven triggers, and the procedure change log, reviewer approvals, and "
                        "redistribution notices are retained in the acquisition governance package."
                    ),
                },
            ]
        case "PS":
            return [
                {"type": "heading", "level": 1, "text": "Personnel Security Review Record"},
                {
                    "type": "paragraph",
                    "text": (
                        "The personnel security policy was reviewed and updated on 2026-04-14, version 6.3 was "
                        "approved, and the revision history entry records the updated version date, reviewer, and "
                        "reason for change."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Management is committed to the personnel security program through formal policy approval, "
                        "assignment of accountable roles, oversight of transfer and termination controls, and annual "
                        "review of personnel security procedures."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The Personnel Security Lead is the specific role designated to manage the development, "
                        "documentation, and dissemination of the personnel security policy and procedures."
                    ),
                },
            ]
        case _:
            return []


def _implementation_detail_sections(
    context: HumanAuthoringContext,
    family_id: str,
    control: Control,
) -> list[dict[str, Any]]:
    match control.display_id:
        case "AC-2":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Accounts are removed in accordance with the organization-defined account management "
                        "procedure, which requires removal or disabling when accounts are no longer required, when "
                        "users are terminated or transferred, and when use or need-to-know changes."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Account managers, supervisors, Human Resources, and the identity and access management queue "
                        "are notified within four business hours when an account is no longer required, when a user "
                        "is terminated or transferred, or when mission use or need-to-know changes require access "
                        "changes."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The account management workflow is aligned with personnel termination and transfer "
                        "procedures so that termination notices automatically trigger account disabling, token "
                        "revocation, privileged-access review, and final account removal."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "When individuals are removed from a shared or group account, the documented account "
                        "management procedure requires changing the shared or group account authenticator, resetting "
                        "the shared password or token, and reissuing the new authenticator only to remaining "
                        "authorized members."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Account usage is continuously monitored through identity and access management audit logs, "
                        "privileged-account alerts, and SIEM correlation rules, and accounts are reviewed on the "
                        "organization-defined monthly schedule for compliance with account management requirements."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["AC-2 Account Lifecycle Event", "Required Notification or Removal Action", "Recorded Evidence"],
                    "rows": [
                        ["Account no longer required", "Account manager notified within four business hours and account removed according to procedure", "IAM closure record AC2-REM-2026-041"],
                        ["User terminated", "Account manager, HR, and IAM queue notified within four business hours and account disabled before removal", "Termination checklist AC2-TERM-2026-018"],
                        ["User transferred", "Account manager notified within four business hours and access adjusted or removed", "Transfer access review AC2-TRANS-2026-009"],
                        ["Need-to-know changed", "Account manager and mission owner notified within four business hours and permissions reduced", "Access change notice AC2-NTK-2026-014"],
                        ["Individual removed from shared account group", "Shared account password rotated and authenticator redistributed only to remaining approved members", "Shared account reset record AC2-SHARED-2026-006"],
                        ["Continuous account-usage monitoring and monthly compliance review", "SIEM alert AC2-MON-2026-04 and monthly account compliance review AC2-REV-2026-04", "Account monitoring dashboard and review record"],
                    ],
                },
            ]
        case "AU-2":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The auditable-event review updates the selected event types after each annual review and "
                        "after significant changes, and the updated event list is approved and published with the "
                        "review record."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Audit Event Review Date", "Updated Selected Event Type", "Recorded Update Evidence"],
                    "rows": [
                        ["2026-04-11", "Added API token creation and revocation events", "Audit event review record AU2-REV-2026-04"],
                        ["2026-04-11", "Added administrator export and bulk-download events", "Updated event catalog AU2-CAT-2026-04"],
                    ],
                },
            ]
        case "AU-3":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Audit records include the source of each event and the outcome of the event, including the "
                        "originating service, host, user interface, or administrative interface and whether the event "
                        "succeeded, failed, was denied, or was quarantined."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Audit records also capture the timestamp for each event so the records document when the "
                        "event occurred in addition to the event source and outcome."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Representative Audit Event", "Recorded Event Timestamp", "Recorded Event Source", "Recorded Event Outcome"],
                    "rows": [
                        ["Administrative sign-in", "2026-04-11T14:22:17Z", "admin-web-01 / privileged identity provider", "Success"],
                        ["Bulk export request", "2026-04-11T15:09:44Z", "case-management-ui / user workstation 10.24.8.19", "Denied"],
                        ["Inbound file upload", "2026-04-11T16:03:08Z", "external intake API gateway", "Quarantined"],
                    ],
                },
            ]
        case "CA-2":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Control assessments explicitly evaluate the extent to which selected controls satisfy "
                        "established privacy requirements, including notice, minimization, access, retention, "
                        "correction, and disclosure constraints."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Privacy Requirement Evaluated During Assessment", "Assessment Method", "Recorded Result"],
                    "rows": [
                        ["Notice and transparency requirement", "Reviewed notices and implementation artifacts", "Assessment worksheet CA2-PRIV-2026-01"],
                        ["Retention and disposal requirement", "Reviewed retention workflow and records", "Assessment worksheet CA2-PRIV-2026-02"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Assessment results are provided to the organization-defined recipients, including the "
                        "Authorizing Official, System Owner, ISSO, privacy lead, and remediation owners, through the "
                        "approved control assessment report distribution workflow."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["CA-2 Assessment Result Recipient", "Distribution Evidence"],
                    "rows": [
                        ["Authorizing Official and System Owner", "Control assessment report distribution record CA2-DIST-2026-01"],
                        ["ISSO and privacy lead", "Assessment report acknowledgement record CA2-DIST-2026-02"],
                        ["Remediation owners", "Corrective action release notice CA2-DIST-2026-03"],
                    ],
                },
            ]
        case "CA-7":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "System-level continuous monitoring includes response actions to address the results of "
                        "analysis of control assessment and monitoring information, including ticket creation, owner "
                        "assignment, due dates, escalation, and verification of corrective action closure."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Monitoring or Assessment Result", "Required Response Action", "Recorded Evidence"],
                    "rows": [
                        ["Control assessment identified logging gap", "Opened corrective action ticket and assigned owner", "Continuous monitoring response record CA7-RESP-2026-04"],
                        ["Monitoring trend showed recurring failed backups", "Escalated to platform team and tracked remediation milestone", "Response action log CA7-RESP-2026-05"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The continuous monitoring strategy reports the privacy status of the system to the "
                        "organization-defined recipients, including the Senior Agency Official for Privacy, System "
                        "Owner, ISSO, and privacy governance stakeholders, through the monthly monitoring status "
                        "package."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Privacy Status Reporting Recipient", "Recorded Evidence"],
                    "rows": [
                        ["Senior Agency Official for Privacy", "Monthly privacy status report CA7-PRIV-2026-04"],
                        ["System Owner and ISSO", "Continuous monitoring status package CA7-STAT-2026-04"],
                        ["Privacy governance stakeholders", "Monitoring distribution record CA7-DIST-2026-04"],
                    ],
                },
            ]
        case "CM-3":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The configuration control board convenes on the organization-defined weekly schedule, and "
                        "meeting minutes, attendance rosters, decisions, and deferred actions are retained with the "
                        "change-control package."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Configuration Control Element Meeting", "Schedule or Attendance Evidence", "Recorded Decision"],
                    "rows": [
                        ["Weekly configuration control board", "Meeting calendar CM3-CAL-2026 and attendance roster CM3-ATT-2026-04-18", "Approved baseline update for API gateway"],
                        ["Emergency change review", "Minutes CM3-MIN-2026-04-22", "Approved urgent patch and follow-up validation"],
                    ],
                },
            ]
        case "CM-9":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The configuration management plan is protected from unauthorized disclosure through "
                        "restricted repository permissions, encryption at rest, encrypted transmission, and controlled "
                        "distribution to authorized recipients."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["CM-9 Protection Control", "Recorded Evidence"],
                    "rows": [
                        ["Restricted repository access", "Configuration management plan access group CM9-ACCESS-01"],
                        ["Encrypted storage and transmission", "Plan storage and transfer safeguard record CM9-ENC-01"],
                        ["Controlled distribution", "Distribution list and handling instruction CM9-DIST-01"],
                    ],
                },
            ]
        case "CP-2":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The contingency plan includes provisions for sharing contingency information, is distributed "
                        "to the organization-defined audience and recipients, coordinates contingency planning "
                        "activities with incident handling activities, and is reviewed and updated to address changes "
                        "and problems encountered during implementation, execution, or testing."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The contingency plan addresses the sharing of contingency information, copies of the "
                        "contingency plan are distributed to the organization-defined recipients, contingency planning "
                        "activities are coordinated with incident handling activities, and contingency plan changes are "
                        "communicated to the organization-defined recipients."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Problems encountered during contingency plan implementation, execution, or testing are used "
                        "to update the contingency plan, and lessons learned from testing, training, or actual "
                        "contingency activities are incorporated into later contingency testing and training."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Lessons learned from contingency plan testing, training, and actual contingency activities "
                        "are incorporated into subsequent contingency testing and training through the contingency "
                        "improvement log."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system contingency plan is reviewed on the organization-defined annual schedule and after "
                        "major tests, disruptions, or environmental changes, and the documented review procedure "
                        "retains the reviewer, date, review outcome, and required updates."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["CP-2 Plan Governance Activity", "Recorded Evidence"],
                    "rows": [
                        ["Provision for sharing contingency information", "Contingency plan section CP2-INFO-SHARE and communications annex CP2-COMM-01"],
                        ["Distribution to organization-defined audience and recipients", "Contingency plan distribution record CP2-DIST-2026-04 and receipt acknowledgements"],
                        ["Coordination with incident handling activities", "Joint contingency and incident response coordination record CP2-IR-COORD-2026-04"],
                        ["Review and update for organizational or environmental changes", "Contingency plan review package CP2-REV-2026-04"],
                        ["Review according to organization-defined schedule", "Annual contingency plan review schedule and completed review record CP2-REV-SCHED-2026"],
                        ["Update for problems encountered during testing", "Contingency plan issue-driven revision record CP2-UPD-2026-03"],
                        ["Contingency plan changes communicated to organization-defined recipients", "Change communication record CP2-CHG-2026-04 and acknowledgement log"],
                        ["Lessons learned incorporated into later testing and training", "Contingency improvement log CP2-LL-2026-04"],
                    ],
                },
            ]
        case "CP-7":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Controls at the alternate processing site are documented as equivalent to those at the "
                        "primary site through an equivalency matrix covering access control, monitoring, backup, "
                        "encryption, logging, and environmental safeguards."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Primary Site Control", "Alternate Site Equivalent Control", "Recorded Equivalency Evidence"],
                    "rows": [
                        ["Privileged access control", "Inherited IAM with same MFA and role review controls", "Alternate site equivalency matrix CP7-EQ-2026-01"],
                        ["Central logging and alerting", "Forwarded to the same enterprise monitoring stack", "Alternate site equivalency matrix CP7-EQ-2026-01"],
                        ["Encrypted backup and recovery controls", "Same backup platform and encryption standard", "Alternate site equivalency matrix CP7-EQ-2026-01"],
                    ],
                },
            ]
        case "IR-4":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Incident handling results are made comparable and predictable across the organization by "
                        "using standard playbooks, shared severity criteria, common containment and escalation "
                        "checklists, and retained post-incident review templates."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Incident Handling Standardization Element", "Recorded Evidence"],
                    "rows": [
                        ["Common severity and response criteria", "Incident handling standard IR4-STANDARD-2026"],
                        ["Shared post-incident review template", "Review template IR4-PIR-2026 and completed sample reviews"],
                    ],
                },
            ]
        case "IR-8":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The incident response plan explicitly designates responsibility for incident response, is "
                        "distributed to the organization-defined audience and recipients, communicates plan changes to "
                        "the same audience, and is protected from unauthorized disclosure and unauthorized "
                        "modification through controlled access, encryption, version control, and signed releases."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The incident response plan defines metrics for measuring incident response capability, "
                        "including time to detect, time to contain, time to recover, reporting timeliness, and "
                        "completion of post-incident corrective actions."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["IR-8 Plan Governance Element", "Recorded Evidence"],
                    "rows": [
                        ["Designated incident response responsibility", "Incident response plan section IR8-ROLE-01 naming incident response lead, backup lead, communications lead, and privacy escalation lead"],
                        ["Distribution to defined audience and recipients", "Incident response plan distribution record IR8-DIST-2026-04 and receipt acknowledgements"],
                        ["Communication of plan changes", "Plan change notice IR8-CHG-2026-04 sent to the incident response distribution list"],
                        ["Protection from unauthorized disclosure", "Restricted repository access and encryption record IR8-PROT-01"],
                        ["Protection from unauthorized modification", "Version control and signed release record IR8-PROT-02"],
                        ["Incident response capability metrics", "Metrics dashboard definition IR8-METRICS-2026 listing detection, containment, recovery, reporting, and corrective-action completion measures"],
                    ],
                },
            ]
        case "MA-2":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Maintenance, repair, and replacement activities are scheduled according to manufacturer and "
                        "vendor specifications, warranty conditions, approved engineering standards, and organization-"
                        "defined maintenance windows documented in the maintenance calendar and change schedule."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Maintenance records are reviewed against manufacturer and vendor specifications before work is "
                        "authorized, and the maintenance record captures the applicable service bulletin, equipment "
                        "identifier, maintenance window, technician name, sanitization requirement, and approval "
                        "reference."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Before equipment is sent offsite for maintenance, repair, or replacement, media is sanitized "
                        "to remove organization-defined information and data from the device or associated media, and "
                        "the sanitization action is recorded in the work package and asset custody log before the "
                        "equipment leaves organizational control."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Equipment is not removed for offsite maintenance, repair, or replacement until the associated "
                        "media is sanitized to remove organization-defined data and the sanitization approval is "
                        "recorded on the removal authorization."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Procedure Step", "Required Action", "Recorded Evidence"],
                    "rows": [
                        ["Pre-removal sanitization check", "Verify associated media is sanitized to remove organization-defined data before off-site maintenance", "Removal authorization MA-REM-12 signed by custodian and ISSO"],
                        ["Custody release", "Confirm sanitization record is attached before equipment leaves site", "Chain-of-custody entry MA-CUST-12"],
                    ],
                },
                {
                    "type": "table",
                    "headers": [
                        "Asset",
                        "Offsite Event",
                        "Sanitization Action",
                        "Media Result",
                        "Custody Record",
                    ],
                    "rows": [
                        [
                            "APP-SRV-22",
                            "Vendor disk controller replacement",
                            "NIST 800-88 purge and configuration backup export review completed before shipment",
                            "Storage media sanitized and released",
                            "Custody log MA-2026-041 / Sanitization witness ISSO",
                        ],
                        [
                            "DB-NODE-07",
                            "Manufacturer warranty repair",
                            "Encrypted backup removed, local cache cleared, and maintenance image reloaded",
                            "Associated media sanitized before offsite repair",
                            "Work package MA-2026-044 / Chain of custody signed",
                        ],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "After maintenance is completed, the responsible technician identifies all potentially impacted "
                        "controls and revalidates logging, alerting, access restrictions, service availability, backup "
                        "operations, and media protection safeguards, and records the validation outcome in the "
                        "maintenance worksheet before the change is closed."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "All potentially impacted controls are checked following maintenance, repair, or replacement "
                        "actions to verify that the controls are still functioning properly before the maintenance task "
                        "is closed."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Equipment and associated media are sanitized to remove organization-defined data before "
                        "removal for offsite maintenance, repair, or replacement, and the sanitization is recorded in "
                        "the maintenance validation record."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The controlled maintenance procedure requires sanitizing equipment and associated media to "
                        "remove organization-defined data before offsite maintenance, repair, or replacement."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The documented sanitization procedure identifies the organization-defined information that "
                        "must be removed from associated media before offsite maintenance, including cached case data, "
                        "temporary exports, credentials, encryption material, and locally retained controlled "
                        "unclassified information."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Equipment is sanitized to remove organization-defined information from associated media prior "
                        "to removal from organizational facilities for offsite maintenance, repair, or replacement, "
                        "and the sanitization record is retained in the maintenance package."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Documented Procedure", "Procedure Requirement"],
                    "rows": [
                        ["Controlled maintenance procedure MA-PROC-04", "Sanitize equipment and associated media to remove organization-defined data before offsite maintenance, repair, or replacement"],
                        ["Sanitization checklist MA-SAN-04", "Remove cached case data, temporary exports, credentials, encryption material, and locally retained controlled unclassified information before offsite maintenance"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["Maintenance Validation Record", "Evidence"],
                    "rows": [
                        ["All potentially impacted controls checked after maintenance", "Maintenance worksheet MA-VAL-2026-044 signed by technician and ISSO"],
                        ["Equipment sanitized before offsite maintenance", "Sanitization record MA-SAN-2026-044 and release approval MA-REM-12"],
                    ],
                },
            ]
        case "PE-2":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The authorized-facility access list is reviewed at least quarterly and after personnel role "
                        "changes, facility reconfiguration, or incident-driven access adjustments, and each review is "
                        "documented with reviewer, date, changes made, and approval reference."
                    ),
                },
            ]
        case "PE-3":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Physical keys are stored in locked key cabinets and other access-controlled storage locations "
                        "under dual-control checkout procedures, lock combinations are secured in the approved "
                        "password vault with sealed emergency escrow, and badge readers, keypads, and other physical "
                        "access devices are protected against tampering by restricting administrative access to "
                        "designated facility security staff."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The organization inventories physical access devices and related assets, and the facility "
                        "security team records each issued key, lock, key card, badge reader, keypad, lock combination "
                        "custodian, assigned location, and last inspection date."
                    ),
                },
                {
                    "type": "table",
                    "headers": [
                        "Device Type",
                        "Identifier",
                        "Assigned Location",
                        "Custodian",
                        "Last Inventory Review",
                    ],
                    "rows": [
                        ["Badge", "BDG-1042", "Primary data center entrance", "Facilities Security", "2026-04-18"],
                        ["Physical key", "KEY-CAB-12", "Network room cabinet C12", "Shift supervisor", "2026-04-18"],
                        ["Keypad", "KP-OPS-04", "Operations bridge", "Facilities Security", "2026-04-18"],
                        ["Lock combination", "LC-VAULT-02", "Secure media vault", "ISSO emergency escrow", "2026-04-18"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Lock combinations are changed on the organization-defined schedule, whenever compromise is "
                        "suspected, and whenever individuals who possess the combinations are transferred or "
                        "terminated; lost keys trigger rekeying or lock replacement, and transferred or terminated key "
                        "holders trigger key recovery, key change, or reissue actions that are documented in the "
                        "access device register."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Event", "Key or Lock Action", "Documented Evidence"],
                    "rows": [
                        ["Lost key reported by contractor", "Affected door cylinder rekeyed and replacement key issued", "Access device register entry PE-2026-032"],
                        ["Administrator transferred to another office", "Suite master key recovered and new key set issued", "Transfer checklist and key custody update PE-2026-041"],
                        ["Badge holder termination", "Key return verified and fallback lock combination changed", "Termination access closure record PE-2026-044"],
                    ],
                },
            ]
        case "PE-6":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Physical access logs are reviewed on a recurring schedule and upon organization-defined "
                        "events, including forced-door alarms, after-hours entry to restricted spaces, badge misuse "
                        "alerts, visitor escort exceptions, and any personnel transfer or termination affecting physical "
                        "access privileges."
                    ),
                },
            ]
        case "PE-16":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Facility exits are monitored and controlled so that only organization-defined and authorized "
                        "personnel may remove system components, media, badges, keys, or other accountable assets from "
                        "the facility, and each approved exit is recorded in the exit authorization log."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The exit-control procedure requires facilities security or an authorized supervisor to verify "
                        "the identity and authority of personnel leaving restricted areas with accountable items, and "
                        "the verification record captures the individual, item removed, authorizing official, and "
                        "time of departure."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Exit Authorization Scenario", "Authorized Personnel or Approver", "Recorded Evidence"],
                    "rows": [
                        ["Replacement firewall removed for warranty service", "Facilities security verified platform lead authorization", "Exit authorization PE16-EXIT-2026-011"],
                        ["Encrypted backup media transferred to secure vault", "Media custodian and ISSO approved transfer", "Custody and exit log PE16-EXIT-2026-014"],
                        ["Terminated employee final property turn-in and escorted exit", "Facilities security and Human Resources witness record", "Departure control record PE16-EXIT-2026-017"],
                    ],
                },
            ]
        case "PL-2":
            return [
                {"type": "heading", "level": 2, "text": "Security and Privacy Plan Content"},
                {
                    "type": "paragraph",
                    "text": (
                        f"The system security and privacy plan for {context.system_name} records the security "
                        "categorization of the system and supporting rationale, including the moderate impact "
                        "determination, mission drivers, data sensitivity, and dependencies used to justify the "
                        "categorization."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The plan documents the threats relevant to the system, including unauthorized access, supply "
                        "chain compromise, insider misuse, service disruption, data exposure, and privacy harms "
                        "associated with processing personally identifiable information."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Privacy risk assessment results are summarized in the plan and linked to the current privacy "
                        "assessment record, including identified data uses, likely privacy harms, mitigation measures, "
                        "and residual risk acceptance decisions for personally identifiable information processing."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system security plan includes relevant privacy risk assessment results for personally "
                        "identifiable information processing so that security and privacy decisions are documented in "
                        "one plan set."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Privacy Risk Area", "Result Included in Plan", "Mitigation", "Residual Decision"],
                    "rows": [
                        [
                            "Excessive retention of applicant contact records",
                            "Plan excerpt notes moderate privacy risk if retention exceeds approved schedule",
                            "Automated retention enforcement and quarterly review",
                            "Residual risk accepted by privacy lead on 2026-04-09",
                        ],
                        [
                            "Role-based access to case notes containing PII",
                            "Plan excerpt records risk of overbroad access without supervisor review",
                            "Manager approval workflow and monthly entitlement review",
                            "Residual risk reduced to low after access review control validation",
                        ],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy plan includes documented privacy risk assessment results for personally "
                        "identifiable information processing, including the identified privacy risk, assessed impact, "
                        "selected mitigation, and residual-risk decision for each material processing activity."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy plan contains the results of a privacy risk assessment for systems processing "
                        "personally identifiable information, including the identified privacy risks, mitigations, and "
                        "residual-risk decisions."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The plan identifies the applicable control baseline and overlays used for implementation, "
                        "including the moderate baseline, privacy overlays applied to personally identifiable "
                        "information processing, and architecture-specific tailoring decisions."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Plan", "Baseline", "Overlay or Tailoring", "Recorded In"],
                    "rows": [
                        ["System Security Plan", "NIST SP 800-53 Moderate Baseline", "Cloud service tailoring set", "Plan section 3.2"],
                        ["Privacy Plan", "NIST SP 800-53 Moderate Baseline", "PII processing privacy overlay", "Plan section 4.1"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The current system security plan and privacy plan explicitly identify the relevant control "
                        "baselines and overlays used for implementation, including the moderate baseline, privacy "
                        "overlays, and any approved tailoring decisions reflected in the current authorization package."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system security plan identifies the relevant control baseline and overlays, including the "
                        "NIST SP 800-53 Moderate Baseline and the approved cloud-service tailoring overlay."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Copies of the system security plan and privacy plan are distributed to the organization-defined "
                        "recipients and the distribution record is retained with the plan package."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Security and privacy architecture and design decisions include documented risk determinations "
                        "that explain why selected controls, compensating measures, segmentation choices, logging "
                        "strategies, and data handling patterns were accepted for the production environment."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system security plan contains documented risk determinations for security architecture and "
                        "design decisions."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The authorizing official or designated representative reviews and approves the security and "
                        "privacy plan before implementation, and copies of the plans are distributed to organization-"
                        "defined recipients including the System Owner, ISSO, privacy stakeholders, engineering leads, "
                        "and assessment support staff. Subsequent plan updates are communicated to the same recipients "
                        "and recorded when system "
                        "changes occur, when implementation problems are identified, and when control assessments "
                        "produce findings requiring plan revisions or corrective actions."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Approval Record", "Approving Official", "Approval Timing", "Evidence"],
                    "rows": [
                        ["Security and privacy plan approval", "Authorizing Official delegate", "Approved before implementation on 2026-04-10", "Signed approval memo in authorization package"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system security plan was reviewed and approved by the authorizing official or designated "
                        "representative prior to implementation."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Recipient Group", "Plan Package Sent", "Latest Distribution", "Latest Change Notice"],
                    "rows": [
                        ["System Owner and ISSO", "Security plan and privacy plan", "2026-04-10 version 7.3", "2026-04-22 architecture update notice"],
                        ["Engineering leads", "Security plan implementation sections", "2026-04-10 version 7.3", "2026-04-22 control assessment revision notice"],
                        ["Privacy stakeholders", "Privacy plan and PRA excerpt", "2026-04-10 version 7.3", "2026-04-22 privacy plan change notice"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["Revision Trigger", "Plan Update Recorded", "Evidence of Corrective Action"],
                    "rows": [
                        ["Implementation issue: incomplete log retention deployment", "Security plan appendix updated 2026-03-28", "Updated logging architecture and ownership assignment"],
                        ["Control assessment finding: privacy notice mismatch", "Privacy plan section 6 revised 2026-04-22", "Distribution note and closure action attached to assessment record"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Subsequent changes to the system security plan and privacy plan are communicated through "
                        "versioned plan-change notices, approval workflow alerts, and retained distribution messages to "
                        "the organization-defined recipients."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Copies of the system security plan and privacy plan are distributed to the organization-defined "
                        "recipients through the controlled plan distribution list, and the distribution history is "
                        "retained with the plan package."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy plan identifies the relevant control baselines and overlays used for "
                        "implementation, and the annual review schedule, distribution record, change notification "
                        "record, implementation problem updates, and control assessment updates are retained with the "
                        "plan package."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system security plan and privacy plan are reviewed on the organization-defined annual "
                        "schedule and after significant changes, and the review record identifies the responsible "
                        "reviewer, review date, and approved follow-up actions."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The plans are updated specifically to address problems identified during control assessments, "
                        "and the assessment-driven changes are tracked in the plan revision history."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Security and privacy plans are updated to address problems identified during control "
                        "assessments, and the resulting corrective revisions are retained with the assessment package."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system security plan and privacy plan are updated to incorporate corrective actions for "
                        "problems identified during plan implementation and control assessments."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Control Assessment Finding", "Plan Update Evidence"],
                    "rows": [
                        ["Privacy notice mismatch identified in assessment", "Privacy plan revision entry PL2-REV-2026-04 with corrective action update"],
                        ["Logging architecture gap identified in assessment", "System security plan appendix update PL2-REV-2026-05 with corrective action update"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The plans are protected from unauthorized disclosure through role-based access controls, "
                        "restricted repository permissions, encryption at rest, and handling procedures that limit "
                        "distribution to authorized recipients."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The plans are protected from unauthorized modification through restricted write access, "
                        "version-controlled change workflows, approver signoff, and retention of read-only released "
                        "copies in the compliance repository."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Protection Measure", "How the Plans Are Protected from Unauthorized Disclosure"],
                    "rows": [
                        ["Restricted repository group", "Only authorized planning, assessment, and privacy personnel may open the authoritative plan files"],
                        ["Encrypted storage", "Plan packages are stored in encrypted repositories and transmitted only through approved channels"],
                        ["Controlled distribution", "Recipients receive versioned copies through approved distribution lists with handling restrictions"],
                    ],
                },
            ]
        case "PL-8":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Planned architecture changes are incorporated into procurement and acquisition activities by "
                        "updating statements of work, technical evaluation criteria, security requirements, and vendor "
                        "review checklists before new products, services, or engineering changes are approved for "
                        "purchase or implementation."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Planned architecture changes are documented in the privacy plan and reflected in the system "
                        "criticality analysis so that data handling impacts, mission dependencies, and risk decisions "
                        "remain aligned before implementation."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The enterprise architecture review process requires planned architecture changes to be "
                        "reviewed, approved, and reflected in updated diagrams, plan narratives, and supporting "
                        "criticality analysis records before implementation."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Procurement or Acquisition Record", "Planned Architecture Change Documented"],
                    "rows": [
                        ["Acquisition plan AP-2026-14", "API gateway adoption requirement and updated boundary protections documented before purchase"],
                        ["Purchase request PR-2026-088", "Managed queueing service architectural dependency and logging requirement documented"],
                        ["Statement of work revision SOW-2026-04", "Supplier integration change and criticality update included in acquisition language"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["Planned Change", "Security Plan Update", "Privacy Plan Update", "Criticality Analysis Update"],
                    "rows": [
                        [
                            "Move external intake service behind managed API gateway",
                            "Boundary diagram and inherited control narrative revised in SSP 2026-04-22",
                            "Data flow and notice impact section revised in privacy plan 2026-04-22",
                            "Gateway dependency and mission impact added to criticality worksheet 2026-04-22",
                        ],
                        [
                            "Adopt managed queueing service for document ingestion",
                            "Interconnection and resilience section revised in SSP 2026-04-15",
                            "Processing purpose and retention dependencies revised in privacy plan 2026-04-15",
                            "Supplier dependency added to criticality worksheet 2026-04-15",
                        ],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy architecture explicitly documents assumptions about and dependencies on external "
                        "systems and services, including shared identity providers, public cloud platforms, "
                        "notification gateways, records-management systems, and supplier-operated components that "
                        "support collection, processing, disclosure, or retention of personally identifiable "
                        "information."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Privacy Architecture Dependency or Assumption", "Documented Privacy Impact or Constraint"],
                    "rows": [
                        ["Shared identity provider dependency", "Access to applicant records depends on inherited identity proofing and role propagation controls"],
                        ["Cloud object storage service dependency", "Retention enforcement and disclosure logging depend on managed object lifecycle and audit services"],
                        ["Records-management export service dependency", "Approved disposition schedules and disclosure restrictions follow the external records platform interface"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Security and privacy architecture documentation identifies assumptions about and dependencies "
                        "on external systems and services, including shared identity providers, cloud platforms, "
                        "interconnected services, and supplier-operated components that support mission execution."
                    ),
                },
            ]
        case "PS-5":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "When individuals are reassigned or transferred, the organization reviews and confirms the "
                        "ongoing operational need for their current logical and physical access authorizations before "
                        "the transfer is finalized, modifies access as needed, and notifies the required parties "
                        "within the defined transfer timeline."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Personnel Transfer Review Activity", "Recorded Evidence"],
                    "rows": [
                        ["Logical and physical access reviewed and confirmed during reassignment", "Transfer access review PS5-TRN-2026-011"],
                        ["Access modified to match new operational need", "Privilege change record PS5-TRN-2026-011A"],
                        ["Required parties notified within defined timeline", "Transfer notification log PS5-TRN-2026-011B"],
                    ],
                },
            ]
        case "PS-8":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "When a formal sanctions process is initiated, designated parties including the System Owner, "
                        "Human Resources, ISSO, and the employee's management chain are notified within one business "
                        "day, and the notice identifies the individual sanctioned, the reason for the sanction, and any "
                        "required access or duty restrictions."
                    ),
                },
            ]
        case "SA-4":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Acquisition contracts and supporting statements of work explicitly identify the parties "
                        "responsible for implementing and validating privacy requirements, descriptions, and acceptance "
                        "criteria associated with the acquired system, component, or service."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Contract Requirement Area", "Responsible Party", "Recorded Obligation"],
                    "rows": [
                        ["Security requirements and acceptance criteria", "Supplier engineering lead", "Implements technical safeguards and provides evidence at delivery"],
                        ["Validation of contractual security criteria", "Organization security review team", "Performs acceptance review before production approval"],
                        ["Supply chain risk management requirements", "Procurement lead and supplier account manager", "Track provenance, subcontractor disclosures, and corrective actions"],
                        ["Privacy requirements and data handling terms", "Privacy office and supplier service owner", "Approve handling restrictions and required notifications"],
                    ],
                },
            ]
        case "SA-5":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "When required system, component, or service documentation is unavailable or incomplete, the "
                        "acquisition team documents each attempt to obtain the material from the developer, reseller, or "
                        "service provider, including the request date, contact, requested artifact, follow-up outcome, "
                        "and the evidence ticket used to track the request when documentation is unavailable or "
                        "nonexistent."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Attempts to obtain documentation when the documentation is unavailable or nonexistent are "
                        "documented in the acquisition evidence record."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "If documentation remains unavailable, the organization-defined actions include requiring "
                        "alternate evidence, escalating the issue to procurement and security leadership, delaying "
                        "acceptance, or restricting deployment until the documentation gap is resolved, and those "
                        "actions are recorded in the acquisition evidence record."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "When attempts to obtain documentation fail, the acquisition team actually takes the "
                        "organization-defined actions recorded in the evidence package, including placing an "
                        "acceptance hold, restricting deployment, requiring alternate evidence, and escalating the "
                        "issue to procurement and security leadership."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Approved system, component, and service documentation is distributed to the defined audience, "
                        "including engineering leads, security reviewers, operations staff, and acceptance authorities, "
                        "and the distribution record is retained with the acquisition evidence package."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system, component, or service documentation is distributed to organization-defined "
                        "recipients, and the distribution process and records are retained with the acquisition "
                        "evidence package."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Missing Documentation", "Request Attempt", "Response if Unavailable", "Distribution Evidence"],
                    "rows": [
                        [
                            "Third-party hardening guide",
                            "Initial vendor request 2026-03-11 and follow-up 2026-03-18",
                            "Compensating review, restricted deployment, and procurement escalation",
                            "Security review package sent to ISSO and platform lead 2026-03-21",
                        ],
                        [
                            "Developer architecture diagram",
                            "Reseller request 2026-03-25 and supplier meeting 2026-03-27",
                            "Acceptance hold until alternate diagram and interface inventory received",
                            "Distribution record to engineering leads and acceptance authority 2026-03-29",
                        ],
                    ],
                },
            ]
        case "SA-9":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Providers of external system services are required by contract and onboarding review to "
                        "comply with the organization's security and privacy requirements, and ongoing oversight "
                        "records retain provider attestations, audit reports, privacy addenda, and corrective action "
                        "tracking."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["External Service Provider Privacy Compliance Evidence", "Recorded Evidence"],
                    "rows": [
                        ["Provider privacy requirements incorporated into contract", "Executed privacy and security addendum SA9-CONTRACT-2026-03"],
                        ["Provider attestation of privacy requirement compliance", "Annual provider attestation SA9-ATTEST-2026-01"],
                        ["Independent audit or assessment evidence", "SOC 2 and privacy control review package SA9-AUDIT-2026-01"],
                    ],
                },
            ]
        case "SA-10":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The developer is required to track security flaws and flaw resolutions for systems, "
                        "components, and services by maintaining a flaw tracking record, assigning severity and "
                        "remediation targets, and updating resolution status until each security flaw is closed."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Security flaw findings and flaw resolution status are reported to the organization-defined "
                        "destination through the ServiceNow security queue, supplier assurance review package, and "
                        "acceptance review record before the affected component or service is approved for production "
                        "use."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The developer is required to report security flaw findings and resolution status to the "
                        "organization-defined recipient, including the supplier assurance lead and ServiceNow security "
                        "queue, as a condition of acceptance."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The developer is required to report findings to the organization-defined location, including "
                        "the supplier assurance review package and ServiceNow security queue."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The developer is required to report findings and flaw resolution status to the "
                        "organization-defined recipient, including the supplier assurance lead, the ServiceNow "
                        "security queue, and the acceptance authority before production approval."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The defined organization audience for developer flaw findings includes the supplier assurance "
                        "lead, ServiceNow security queue, acceptance authority, and ISSO, and developers are required "
                        "to report findings to that defined audience."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Flaw ID", "Affected Component", "Status", "Resolution Tracking Evidence"],
                    "rows": [
                        ["SUP-2418", "Inbound file parser library", "Closed", "Vendor hotfix received, tested, and closure recorded in supplier assurance log"],
                        ["SUP-2441", "Managed authentication connector", "In progress", "Developer milestone dates and weekly status updates retained in flaw tracker"],
                    ],
                },
            ]
        case "SA-21":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The developer is required to have appropriate access authorizations as determined by the "
                        "assigned organization-defined authority before performing development activities on the system "
                        "or service."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Developer Screening Requirement", "Recorded Evidence"],
                    "rows": [
                        ["Access authorization approved by assigned authority", "Developer access list approved by supplier assurance lead and ISSO"],
                        ["Additional screening criteria satisfied", "Background check and workforce eligibility attestation retained in acquisition file"],
                    ],
                },
            ]
        case "SA-22":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "When a system component becomes unsupported, the organization replaces the component or "
                        "provides alternative source options for continued support, including qualified third-party "
                        "maintenance, in-house support, or contracted replacement services."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Unsupported Component Option", "Documented Alternative Support Source"],
                    "rows": [
                        ["Legacy appliance firmware no longer vendor-supported", "Qualified third-party maintenance agreement"],
                        ["Unsupported middleware package", "In-house patch support plan until replacement is complete"],
                    ],
                },
            ]
        case "PE-11":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        f"{context.system_name} uses an uninterruptible power supply (UPS) to support system "
                        "components during primary power loss long enough to sustain orderly failover, controlled "
                        "shutdown, and monitoring visibility until generator or alternate power sources take over."
                    ),
                },
            ]
        case "PE-22":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Hardware components are marked with their assigned impact or classification level on asset "
                        "labels, rack inventories, or controlled asset records before installation in production or "
                        "restricted support spaces."
                    ),
                },
            ]
        case "PE-23":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Facility and site selection decisions are based on an analysis of physical and environmental "
                        "hazards, including flood exposure, utility reliability, fire suppression capability, access "
                        "control conditions, and other environmental risks documented before occupancy or major "
                        "expansion."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Physical and environmental hazard considerations are incorporated into the organization's risk "
                        "management strategy for existing facilities through periodic site reviews, risk register "
                        "entries, and facility improvement planning records."
                    ),
                },
            ]
        case "PM-1":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan identifies the common controls in place or planned, "
                        "assigns responsibilities for program execution, records top-level management commitment "
                        "through support and resource allocation decisions, and reflects coordination among the "
                        "organizational entities responsible for information security, including executive leadership, "
                        "the System Owner, ISSO, privacy stakeholders, engineering leadership, procurement, legal, and "
                        "operations."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan provides an overview of security program requirements, "
                        "describes the program management controls and common controls in place or planned, documents "
                        "coordination among organizational entities, and identifies applicable compliance requirements."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan includes a description of the common controls in place "
                        "or planned to meet security program requirements and documents coordination among the "
                        "organizational entities responsible for information security."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan is disseminated to the organization-defined audience of "
                        "executive management, the senior agency information security officer, System Owner, ISSO, "
                        "privacy stakeholders, engineering leadership, procurement, legal, and operations teams, and "
                        "the distribution record retains the recipient list, release date, and plan version."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan addresses compliance requirements and documents the "
                        "controls used to protect the plan from unauthorized disclosure and unauthorized modification."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Common Control in Place or Planned", "Status", "How It Supports the Program Plan"],
                    "rows": [
                        ["Identity and access management common control", "In place", "Provides shared account provisioning, MFA, and access review coverage"],
                        ["Central logging and alerting common control", "In place", "Provides enterprise monitoring, log retention, and incident visibility"],
                        ["Automated supplier assurance dashboard", "Planned", "Provides program-level visibility into supplier risk and inherited security obligations"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The program plan approval record identifies the senior official who is responsible and "
                        "accountable for organizational risk and who approves the plan on behalf of executive "
                        "management."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan is distributed to appropriate personnel and "
                        "stakeholders, and the distribution record identifies the recipients, distribution date, and "
                        "current version provided."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["PM-1 Stakeholder Group", "Dissemination Method", "Recorded Evidence"],
                    "rows": [
                        ["Executive management and risk-accountable senior official", "Approved release package and governance portal notice", "Program plan dissemination record PM1-DIST-EXEC-2026-04"],
                        ["System Owner, ISSO, and engineering leadership", "Controlled distribution list and acknowledgement workflow", "Program plan dissemination record PM1-DIST-OPS-2026-04"],
                        ["Privacy, procurement, legal, and operations teams", "Stakeholder distribution list and meeting release notice", "Program plan dissemination record PM1-DIST-STAKE-2026-04"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan is protected from unauthorized modification through "
                        "restricted repository write access, document version control, approval-based change workflows, "
                        "and integrity-preserving retention of signed program-plan releases."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The information security program plan is protected from unauthorized disclosure through "
                        "restricted access controls, encryption, handling procedures, and controlled distribution."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Protection Mechanism", "How Unauthorized Modification Is Prevented"],
                    "rows": [
                        ["Restricted write permissions", "Only program management maintainers may edit the authoritative plan repository"],
                        ["Version control and approval workflow", "Each plan revision requires reviewer approval before publication"],
                        ["Released copy retention", "Approved versions are retained as read-only signed releases in the compliance repository"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["Unauthorized Disclosure Safeguard", "Recorded Evidence"],
                    "rows": [
                        ["Restricted repository permissions and encryption", "Program plan access control and encryption record PM1-PROT-02"],
                        ["Controlled handling and distribution", "Program plan handling instruction and distribution record PM1-PROT-03"],
                    ],
                },
            ]
        case "PM-4":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Plans of action and milestones are reviewed for consistency with the organizational risk "
                        "management strategy and organization-wide priorities for risk response actions before "
                        "remediation schedules, ownership assignments, and funding decisions are approved."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Each POA&M review explicitly assesses consistency with the organizational risk management "
                        "strategy, including priority alignment, risk acceptance boundaries, and enterprise response "
                        "expectations, and the result is recorded in the review package."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Privacy POA&M information is reported in accordance with established reporting requirements, "
                        "including required recipients, reporting cadence, and escalation procedures for unresolved "
                        "privacy weaknesses."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Reporting Artifact", "Recipient", "Cadence", "Escalation Trigger"],
                    "rows": [
                        ["POA&M status report", "Risk executive and privacy lead", "Monthly", "Any overdue milestone or high-risk weakness"],
                        ["Quarterly summary", "Executive governance board", "Quarterly", "Persistent unresolved weaknesses affecting mission or privacy risk"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["POA&M Review Check", "Recorded Result"],
                    "rows": [
                        ["Consistency with organizational risk management strategy", "Verified in monthly POA&M governance review"],
                        ["Consistency with organization-wide priorities for risk response actions", "Verified in monthly POA&M governance review"],
                    ],
                },
            ]
        case "PM-5":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "An inventory of organizational systems is developed and updated on the organization-defined "
                        "monthly schedule and whenever new systems, major services, or decommissioning actions change "
                        "the authoritative system inventory."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["System Inventory Activity", "Recorded Evidence"],
                    "rows": [
                        ["Inventory of organizational systems developed", "Authoritative system inventory PM5-INV-BASE-2026 listing production, support, and inherited services"],
                        ["Monthly inventory update completed", "System inventory update log PM5-UPD-2026-04 with reviewer approval"],
                        ["New service entry added after architecture change", "Inventory change ticket PM5-CHG-2026-02 for managed queueing service"],
                    ],
                },
            ]
        case "PM-18":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan identifies the Senior Agency Official for Privacy and the governance "
                        "roles that support privacy oversight."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan includes the role of the Senior Agency Official for Privacy and "
                        "identifies the other privacy officials and staff responsible for privacy governance, notice, "
                        "records management, complaints, breach coordination, and control implementation."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan explicitly includes the senior agency official for privacy role and "
                        "the responsibilities assigned to that role for privacy governance, approvals, and risk "
                        "oversight."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan is updated when federal privacy laws or policies change, when "
                        "organizational structure or data handling responsibilities change, and when implementation or "
                        "assessment activities identify issues that require plan revisions or additional oversight."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan is reviewed and updated on the organization-defined annual schedule, "
                        "and the review record captures the reviewer, review date, version approved, and follow-up "
                        "actions taken in response to implementation issues or privacy control assessment findings."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan is updated to address problems identified during plan implementation "
                        "or privacy control assessments, and the resulting revisions are tracked in the plan change log."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan explicitly identifies the senior agency official for privacy and is "
                        "reviewed and updated on the organization-defined annual schedule and when organizational "
                        "changes occur."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan identifies the senior agency official for privacy, identifies the "
                        "roles and responsibilities of other privacy officials and staff, reflects coordination among "
                        "the organizational entities responsible for privacy functions, and is disseminated to the "
                        "appropriate stakeholders."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan is disseminated to appropriate personnel and stakeholders through the "
                        "privacy governance distribution list and retained posting record."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan contains a documented description of the privacy program's strategic "
                        "goals and objectives and the coordination process among privacy, legal, records, security, and "
                        "mission entities."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Privacy Program Plan Dissemination", "Recorded Evidence"],
                    "rows": [
                        ["Distributed to privacy officer, legal counsel, ISSO, records manager, and mission owners", "Stakeholder distribution record PM18-DIST-04"],
                        ["Posted to privacy governance portal for authorized stakeholders", "Portal publication log PM18-PUB-01"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The organization-wide privacy program plan describes the strategic goals and objectives of the "
                        "privacy program, including reduction of privacy risk, timely response to individual requests, "
                        "and oversight of PII processing."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan is updated on the organization-defined annual schedule, updated when "
                        "federal privacy laws and policies change, and updated when plan implementation or privacy "
                        "control assessments identify issues requiring corrective action."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The organization-wide privacy program plan is reviewed and updated on the organization-defined "
                        "annual schedule, updated when federal privacy laws and policies change, and updated when "
                        "problems are identified during plan implementation or privacy control assessments."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan is reviewed and updated on the organization-defined annual schedule "
                        "and is updated to address problems identified during plan implementation or privacy control "
                        "assessments."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The privacy program plan describes management commitment, compliance expectations, and the "
                        "strategic goals and objectives of the privacy program, including reduction of privacy risk, "
                        "timely response to individual requests, and sustained oversight of PII processing activities."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Privacy Role or Review Event", "Recorded Schedule or Responsibility", "Update Result"],
                    "rows": [
                        ["Senior Agency Official for Privacy", "Approves program direction and privacy risk decisions", "Role identified in privacy program plan section 2.1"],
                        ["Privacy officer and records manager", "Manage notices, records requests, and retention obligations", "Responsibilities assigned in privacy program plan section 2.2"],
                        ["Annual privacy program review", "2026-04-05 recurring annual review", "Version 5.2 approved by SAOP delegate"],
                        ["Implementation issue follow-up", "Data minimization workflow gap identified 2026-03-19", "Plan updated with revised oversight and reporting actions"],
                        ["Privacy assessment follow-up", "Control assessment findings issued 2026-04-17", "Plan updated with corrective action tracking and reassigned owners"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["Plan Dissemination or Coordination Item", "Recorded Evidence"],
                    "rows": [
                        ["Privacy program plan distributed to privacy officer, records manager, legal counsel, ISSO, and mission owners", "Stakeholder distribution record PM18-DIST-04"],
                        ["Coordination among privacy, legal, records, security, and mission entities", "Privacy governance meeting record PM18-COORD-02"],
                        ["Annual update and federal privacy law review", "Annual review package PM18-REV-2026"],
                        ["Corrective-action update from privacy assessment findings", "Plan revision log entry PM18-REV-2026-04"],
                    ],
                },
            ]
        case "PM-23":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "A Data Governance Body is established with representation from the chief information officer, "
                        "senior agency information security officer, senior agency official for privacy, and other data "
                        "governance stakeholders, and the body's charter defines its membership, roles, and "
                        "responsibilities."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Data Governance Body Element", "Recorded Evidence"],
                    "rows": [
                        ["Board membership and chartered responsibilities", "Data Governance Body charter PM23-CHARTER-01"],
                        ["Board meeting and decision record", "Data Governance Body minutes PM23-MTG-02"],
                    ],
                },
            ]
        case "PM-24":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "A Data Integrity Board is established to review proposals to conduct or participate in a "
                        "matching program and to conduct an annual review of all matching programs in which the agency "
                        "participates."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Data Integrity Board Activity", "Recorded Evidence"],
                    "rows": [
                        ["Review of proposal to participate in a matching program", "Data Integrity Board review record PM24-REV-01"],
                        ["Annual review of all matching programs", "Annual Data Integrity Board report PM24-ANNUAL-2026"],
                    ],
                },
            ]
        case "PM-21":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The organization develops and maintains an accurate accounting of disclosures of personally "
                        "identifiable information, retains the accounting for the required period, and makes the "
                        "accounting available to the individual to whom the information relates upon request."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Privacy quality-management policy requires reviewing the relevance and completeness of "
                        "personally identifiable information across the information life cycle."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Privacy quality-management procedures require reviewing the relevance and completeness of "
                        "personally identifiable information across the information life cycle."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Disclosure Accounting Activity", "Recorded Evidence"],
                    "rows": [
                        ["Accounting of disclosures made available upon individual request", "Privacy request response record PM21-REQ-02"],
                        ["Disclosure log retained with date, purpose, and recipient details", "Disclosure accounting ledger PM21-LEDGER-01"],
                    ],
                },
            ]
        case "PM-31":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The continuous monitoring program correlates and analyzes information generated by control "
                        "assessments and ongoing monitoring and records response actions taken to address the analysis "
                        "results."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The continuous monitoring program reports the privacy status of organizational systems to the "
                        "organization-defined recipients, including the senior agency official for privacy and privacy "
                        "governance stakeholders."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Monitoring Analysis Result", "Response Action"],
                    "rows": [
                        ["Repeated configuration drift on monitored workload", "Opened remediation action, increased monitoring frequency, and assigned owner"],
                        ["Control assessment identified recurring log-ingest failure", "Implemented corrective change, tracked closure milestone, and reported status in monitoring review"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["Privacy Status Report", "Recipient"],
                    "rows": [
                        ["Monthly privacy monitoring status dashboard", "Senior agency official for privacy"],
                        ["Quarterly privacy status summary", "Privacy governance stakeholders"],
                    ],
                },
            ]
        case "PM-32":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Mission-essential services and functions are analyzed on the organization-defined annual "
                        "schedule and after major service changes to confirm that the information resources supporting "
                        "those services are used in a manner consistent with their intended purpose."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Mission-Essential Service or Function", "Purpose-Use Analysis Evidence"],
                    "rows": [
                        ["Applicant case intake and adjudication workflow", "Mission-supporting information resource purpose analysis PM32-ANALYSIS-2026-01"],
                        ["Identity verification and access-decision support service", "Resource-purpose validation review PM32-ANALYSIS-2026-02"],
                        ["Document retention and records-disposition support function", "Mission-essential resource consistency review PM32-ANALYSIS-2026-03"],
                    ],
                },
            ]
        case "PM-22":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Organization-wide privacy quality management policy and procedures require reviewing the "
                        "accuracy, relevance, timeliness, and completeness of personally identifiable information "
                        "throughout the information life cycle, including collection, use, storage, disclosure, and "
                        "disposition activities."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The same policy and procedures require correction or deletion of inaccurate or outdated "
                        "personally identifiable information, dissemination of notice when corrected or deleted "
                        "information affects individuals or other appropriate entities, and an appeals process for "
                        "adverse decisions on correction or deletion requests."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["PII Quality Activity", "Policy Requirement", "Procedure Evidence"],
                    "rows": [
                        ["Accuracy, relevance, timeliness, and completeness review", "Quarterly review across the information life cycle", "Case-management data quality checklist and review log"],
                        ["Correction or deletion of outdated PII", "Request validation, correction, deletion, and record update", "Privacy request workflow with closure evidence"],
                        ["Notice of corrected or deleted PII", "Notify affected individual or downstream recipient when applicable", "Notification template and delivery record"],
                        ["Appeal of adverse decision", "Escalation to privacy review authority within defined timeframe", "Appeal intake and decision tracking record"],
                    ],
                },
            ]
        case "PM-17":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The PM-17 privacy awareness and accountability policy is reviewed and updated on the "
                        "organization-defined annual schedule and when privacy governance expectations, roles, or "
                        "reporting requirements change."
                    ),
                },
            ]
        case "PM-27":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Privacy reports are disseminated to the defined recipients to demonstrate accountability with "
                        "statutory, regulatory, and policy privacy mandates."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Privacy reports are reviewed and updated on the organization-defined annual schedule and when "
                        "reporting requirements change."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Privacy Reporting Activity", "Recorded Evidence"],
                    "rows": [
                        ["Dissemination of privacy report to defined recipients", "Privacy report distribution record PM27-DIST-2026"],
                        ["Annual review and update of privacy reporting", "Privacy report review schedule PM27-REV-2026"],
                    ],
                },
            ]
        case "PM-25":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Policies and procedures specifically address the authorized use of personally identifiable "
                        "information for internal testing, training, and research and require minimization of the "
                        "personally identifiable information used for each purpose."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Use of personally identifiable information for internal testing, training, or research is "
                        "permitted only through a formal authorization process that records the request, purpose, "
                        "approving authority, privacy conditions, minimization approach, and retention or disposal "
                        "requirements before the activity begins."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Data minimization procedures for testing, training, and research are reviewed on the "
                        "organization-defined annual schedule and after privacy findings, and the review record "
                        "captures the reviewer, date, decision, and follow-up actions."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["PII Use Case", "Policy or Procedure Requirement", "Recorded Evidence"],
                    "rows": [
                        ["Internal testing", "Use only minimized or masked PII and only when explicitly authorized", "Testing authorization and masking record PM25-TEST-01"],
                        ["Internal training", "Use minimized training data and approved privacy conditions", "Training dataset approval record PM25-TRAIN-01"],
                        ["Internal research", "Use minimized research data and approved privacy conditions", "Research authorization record PM25-RES-01"],
                        ["Annual review", "Review minimization procedures on defined annual schedule", "Annual minimization review PM25-REV-2026"],
                    ],
                },
            ]
        case "PM-7":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The maintained enterprise architecture incorporates consideration of risk to organizational "
                        "operations, assets, individuals, other organizations, and the Nation when architecture "
                        "decisions are developed and updated."
                    ),
                },
            ]
        case "RA-2":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        f"The system security plan contains the actual security categorization results for "
                        f"{context.system_name}, including confidentiality, integrity, and availability impact values, "
                        "the overall system categorization, and the supporting rationale used to justify those results."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Security Objective", "Impact Value in SSP", "Supporting Rationale Recorded in SSP"],
                    "rows": [
                        ["Confidentiality", "Moderate", "PII, case records, and operational data require protection against unauthorized disclosure"],
                        ["Integrity", "Moderate", "Unauthorized modification could affect case processing decisions and reporting accuracy"],
                        ["Availability", "Moderate", "Service outage would disrupt mission operations and time-sensitive processing"],
                    ],
                },
            ]
        case "RA-3":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Organization-level and mission-level risk assessment results and resulting risk management "
                        "decisions are incorporated into system-level risk assessments before the assessment package is "
                        "finalized."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The system-level risk assessment integrates organization-level and mission or business-process "
                        "risk results by referencing the enterprise risk register, mission dependency analysis, and "
                        "approved risk management decisions in the body of the assessment."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Risk assessment results are documented in the organization-defined location."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Risk assessment results are documented in the organization-defined location, namely the risk "
                        "assessment repository and linked risk register, and are disseminated to the organization-"
                        "defined audience including the System Owner, ISSO, executive management, privacy "
                        "stakeholders, and remediation owners."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The authoritative organization-defined location for risk assessment results is the risk "
                        "assessment repository linked to the enterprise risk register, and every final assessment "
                        "package records the repository location, version, approval date, and dissemination record."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The Risk Assessment Lead reviews the system-level risk assessment according to the "
                        "organization-defined annual procedure, confirms incorporation of organization-level and "
                        "mission-level risk decisions, approves dissemination to the organization-defined recipients, "
                        "and updates the assessment whenever significant changes occur."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Risk Assessment Result", "Recipient", "Dissemination Evidence"],
                    "rows": [
                        ["System-level risk assessment summary", "System Owner and ISSO", "Risk assessment distribution record RA-2026-017"],
                        ["Mission-impact and remediation decision summary", "Executive management and remediation owners", "Risk register notification RA-2026-018"],
                        ["Approved annual risk assessment package", "Privacy stakeholders and remediation owners", "Repository publication and acknowledgement RA-2026-019"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["RA-3 Review or Update Requirement", "Recorded Evidence"],
                    "rows": [
                        ["Integration of organization-level and mission-level risk decisions", "System risk assessment appendix RA3-INTEG-2026 referencing enterprise risk register items and mission dependency decisions"],
                        ["Annual review according to organization-defined procedure", "Risk assessment review record RA3-REV-2026 signed by Risk Assessment Lead and System Owner"],
                        ["Dissemination to organization-defined recipients", "Distribution package RA3-DIST-2026 sent to System Owner, ISSO, executive management, privacy stakeholders, and remediation owners"],
                        ["Update after significant change", "Risk assessment update log RA3-UPD-2026-02 after external interface expansion"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Risk assessment results are updated annually and whenever significant changes occur, including "
                        "major architecture changes, new external interfaces, material threat changes, or control "
                        "assessment findings that alter the risk picture."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The risk assessment is updated on the organization-defined annual schedule and whenever "
                        "significant changes occur to the system, its environment of operation, or other conditions "
                        "that affect risk."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Risk assessment results are reviewed and approved on the organization-defined annual schedule, "
                        "and the review approval is retained with the risk assessment record."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The risk assessment is updated on the organization-defined annual schedule and whenever "
                        "significant changes occur to the system or its environment of operation."
                    ),
                },
            ]
        case "RA-5":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Vulnerability scan reports are analyzed by reviewing severity, affected assets, exploitability, "
                        "environmental context, and compensating controls, and the findings are documented in the "
                        "vulnerability review worksheet and remediation tracker."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Identified legitimate vulnerabilities are remediated on the organization-defined schedule in "
                        "accordance with the organizational assessment of risk, including risk-based prioritization, "
                        "assigned owners, planned completion dates, and tracked remediation status."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The vulnerability analysis process is performed by the vulnerability management lead and the "
                        "assigned system administrator after each scheduled scan and when newly reported vulnerabilities "
                        "potentially affect the system, and the analysis frequency and responsibilities are retained in "
                        "the scan review record."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Information obtained from vulnerability monitoring and control assessments is shared with the "
                        "organization-defined audience, including system owners, platform administrators, and security "
                        "operations, to eliminate similar vulnerabilities in other systems."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Analysis Event", "Responsible Role", "Recorded Review Frequency or Trigger"],
                    "rows": [
                        ["Weekly authenticated vulnerability scan", "Vulnerability management lead", "Analyzed each Wednesday after scan completion"],
                        ["Emergency review for newly disclosed critical CVE", "System administrator and ISSO", "Analyzed within 24 hours of vendor alert"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["Shared Vulnerability Information", "Recipient Group", "Sharing Evidence"],
                    "rows": [
                        ["Recurring scan findings and mitigation guidance", "Platform administrators and system owners", "Weekly vulnerability digest RA-VM-22"],
                        ["Control assessment findings with reuse potential", "Security operations and peer system teams", "Cross-system remediation notice RA-VM-24"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["Legitimate Vulnerability", "Risk-Based Remediation Requirement", "Recorded Evidence"],
                    "rows": [
                        ["Critical internet-facing library flaw", "Remediate within 72 hours based on high organizational risk assessment", "Remediation tracker RA5-REM-2026-01"],
                        ["Moderate misconfiguration with compensating controls", "Remediate within 30 days based on moderate organizational risk assessment", "Remediation tracker RA5-REM-2026-02"],
                    ],
                },
            ]
        case "SA-2":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Mission and business process planning determines high-level information security and privacy "
                        "requirements for the system, documents the resources required to protect the service, and "
                        "allocates those resources through capital planning and investment control activities."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "A distinct information security budget line item is documented in the capital planning and "
                        "investment control package, and that line item funds security tooling, assessment support, "
                        "inherited control sustainment, and required implementation resources."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Budget Line Item", "Purpose", "Documentation"],
                    "rows": [
                        ["BLI-SEC-146-01 information security line item", "Security tooling, assessment support, and inherited control sustainment", "FY26 capital planning workbook section BLI-SEC-146-01"],
                        ["BLI-PRIV-146-02 privacy line item", "Privacy notices, request processing, and privacy control assessment support", "FY26 programming and budgeting workbook section BLI-PRIV-146-02"],
                    ],
                },
            ]
        case "SC-2":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "User functionality is separated from system management functionality by using distinct "
                        "administrative interfaces, separate privileged networks, dedicated bastion access paths, and "
                        "role-restricted management services that are unavailable from standard user-facing sessions."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Administrative management functionality is accessible only through the designated management "
                        "subnet and privileged access gateway, while user-facing application services are exposed "
                        "through separate production interfaces and cannot directly invoke system management "
                        "functions."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["SC-2 Separation Mechanism", "Representative Technical Evidence"],
                    "rows": [
                        ["Dedicated admin interface", "Administrative console exposed only on mgmt-admin.internal.example through privileged access gateway SC2-TECH-2026-01"],
                        ["Privileged network separation", "Management subnet ACL and bastion routing record SC2-TECH-2026-02"],
                        ["Role-restricted service accounts", "Administrative service-role mapping and denial of user-session access SC2-TECH-2026-03"],
                    ],
                },
            ]
        case "SI-3":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Malicious code protection mechanisms are configured to automatically send alerts to the "
                        "organization-defined recipients, "
                        "including the security operations mailbox, on-call incident responder, and platform operations "
                        "lead, whenever malicious code is detected, quarantined, blocked, or requires analyst review."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Procedures also address false positives by documenting analyst review steps, restoration "
                        "approval, exception handling, and explicit assessment of potential impact on system "
                        "availability before quarantined content or blocked services are returned to production use, "
                        "and the mitigation actions taken for each false-positive condition are recorded in the review "
                        "record."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Alert Condition", "Configured Recipient", "Triage or Mitigation Action"],
                    "rows": [
                        ["Malware detected on endpoint", "security-operations@agency.example", "Open incident ticket and isolate affected asset"],
                        ["Quarantine blocks production file", "On-call incident responder", "Review false positive, assess availability impact, approve restoration if safe"],
                        ["Gateway attachment blocked", "Platform operations lead", "Confirm business impact and apply approved mitigation or exception"],
                    ],
                },
            ]
        case "SC-21":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The system performs data origin authentication on name and address resolution responses "
                        "received from authoritative sources by using authenticated resolution services, signed "
                        "responses, and validation checks before the responses are trusted by production workloads."
                    ),
                },
            ]
        case "SR-2":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "The supply chain risk management plan is reviewed and updated at least annually and after "
                        "identified threat, organizational, supplier, or environmental changes, and each review "
                        "records the trigger, affected suppliers or dependencies, review decision, and approved "
                        "revision."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The supply chain risk management plan is protected from unauthorized modification through "
                        "restricted write access, version control, digital signatures on approved releases, and a "
                        "documented change-management workflow."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["SR-2 Review, Update, or Protection Requirement", "Recorded Evidence"],
                    "rows": [
                        ["Annual scheduled review", "SCRM plan review package SR2-REV-2026-04 with signed approval"],
                        ["New supplier dependency for document-ingestion service", "SCRM update record SR2-UPD-2026-02"],
                        ["Threat advisory affecting managed software component", "Threat-driven SCRM revision record SR2-UPD-2026-03"],
                        ["Restricted write access", "SCRM plan repository permission set SR2-PROT-ACCESS-01"],
                        ["Version-controlled changes and signed releases", "SCRM plan version-control and digital-signature record SR2-PROT-VC-01"],
                    ],
                },
            ]
        case "SI-4":
            return [
                {
                    "type": "paragraph",
                    "text": (
                        "Detected events and anomalies are analyzed to determine cause, scope, affected assets, and "
                        "required response actions before the event is closed, and the analysis results are recorded in "
                        "the monitoring review record."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Monitoring activity levels are increased when the risk to organizational operations, assets, "
                        "individuals, other organizations, or the Nation changes, including during active incidents, "
                        "heightened threat advisories, major architecture changes, or exposure of sensitive data or "
                        "externally facing services."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Risk Change Trigger", "Monitoring Adjustment", "Recorded Authority"],
                    "rows": [
                        ["Critical vulnerability in internet-facing service", "Increase log review frequency from daily to every four hours", "SOC manager change record"],
                        ["Major architecture change affecting data flows", "Enable additional API audit events and anomaly dashboards", "ISSO-approved monitoring change ticket"],
                    ],
                },
                {
                    "type": "paragraph",
                    "text": (
                        "The legal opinion governing system monitoring activities is documented in the system monitoring "
                        "legal opinion maintained with counsel-approved monitoring rules, user notice language, and "
                        "annual review records."
                    ),
                },
                {
                    "type": "paragraph",
                    "text": (
                        "Defined monitoring information, including notable anomalies, confirmed malicious activity, "
                        "monitoring changes, and recommended response actions, is provided to the System Owner, ISSO, "
                        "and security operations manager through the monitoring summary and incident escalation record."
                    ),
                },
                {
                    "type": "table",
                    "headers": ["Legal Review Record", "Subject", "Current Status"],
                    "rows": [
                        ["OGC-MON-2026-02", "System monitoring authority, user notice, and approved collection scope", "Approved by counsel and retained with annual review package"],
                    ],
                },
                {
                    "type": "table",
                    "headers": ["Monitoring Information Sent", "Recipient", "Delivery Evidence"],
                    "rows": [
                        ["Daily anomaly summary and notable monitoring changes", "System Owner and ISSO", "Monitoring summary distribution record SI-2026-018"],
                        ["Confirmed malicious activity requiring action", "Security operations manager", "Incident escalation ticket and notification log SI-2026-021"],
                    ],
                },
            ]
        case _:
            return []


def _validation_family_addenda(
    family_id: str,
    family_title: str,
) -> list[str]:
    match family_id:
        case "MA":
            return [
                "Verify that maintenance records cite the applicable manufacturer or vendor service procedure, scheduled window, validation checklist, and the organization-defined maintenance record fields for each completed activity.",
                "Confirm that offsite maintenance events include documented media sanitization and that the post-maintenance review identifies each potentially impacted control before the work item is closed.",
            ]
        case "PE":
            return [
                "Confirm that key inventories, lock combination custody records, physical access device inventories, and event-driven log review records are retained for the selected sample period.",
                "Verify that the authorized-facility access list review cadence, UPS coverage, and key or combination change actions are documented for the review period.",
            ]
        case "PL":
            return [
                "Confirm that the system security and privacy plan includes security categorization rationale, threat information, privacy risk assessment results, control baselines or overlays, approval before implementation, and documented updates tied to change and assessment events.",
                "Verify that planned architecture changes are reflected in procurement artifacts, acquisition requirements, or vendor evaluation records before implementation.",
            ]
        case "PM":
            return [
                "Verify that the information security program plan records coordination among organizational entities, common controls in place or planned, and protections against unauthorized modification.",
                "Confirm that POA&M reviews measure consistency with the organizational risk management strategy and enterprise risk response priorities, and that privacy quality-management procedures address review, correction or deletion, notice, and appeals.",
            ]
        case "RA":
            return [
                "Confirm that the risk assessment policy explicitly addresses compliance requirements and identifies the designated role that manages policy development, documentation, and dissemination.",
                "Verify that the security plan includes the actual categorization results and rationale and that vulnerability scan analysis records identify responsible roles, triggers, and review frequency.",
            ]
        case "PS":
            return [
                "Review sanction-notification records to confirm designated parties were notified within the defined timeframe and that the notice identified the sanctioned individual and reason for the action.",
            ]
        case "SA":
            return [
                "Review supplier documentation request records, compensating actions for unavailable documentation, documentation distribution records to the defined audience, and developer flaw tracking reports submitted to the organization-defined reporting destination.",
                "Confirm that acquisition planning records include discrete information security and privacy budget line items and that contract records identify responsible parties for security, privacy, and supply chain requirements.",
            ]
        case "SI":
            return [
                "Review malicious code alert routing, false-positive handling records, risk-triggered monitoring changes, the current legal opinion governing monitoring activities, and distribution of defined monitoring information to the specified recipients.",
            ]
        case "SR":
            return [
                "Confirm that the supply chain risk management scope explicitly covers systems, components, services, and suppliers and that annual reviews verify alignment to applicable laws, Executive Orders, directives, regulations, standards, and guidelines.",
            ]
        case _:
            return []


def _policy_sections(context: HumanAuthoringContext, family_id: str, policy_control: Control) -> list[dict[str, Any]]:
    family_title = policy_control.family_title
    objective_lines = []
    for obj in policy_control.assessment_objectives:
        _, _, text = obj.partition(":")
        objective_lines.append(_resolve_objective_text(text.strip(), family_title))
    statement_lines = [
        part.strip()
        for part in re.split(r";\s+|\n", _cleanup_text(policy_control.statement))
        if part.strip()
    ]
    bullets = []
    for sentence in objective_lines + statement_lines:
        sentence = sentence.strip()
        if sentence and sentence not in bullets:
            if not sentence.endswith("."):
                sentence += "."
            bullets.append(sentence[:1].upper() + sentence[1:])

    sections = [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This standard establishes the {family_title.lower()} policy and supporting procedures used by {context.system_name} to govern how the organization plans, implements, documents, monitors, and reviews {family_title.lower()} activities."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"This standard applies to production services, hosted applications, infrastructure components, administrative tooling, retained records, operational workflows, and personnel responsible for {family_title.lower()} activities in the {context.system_name} environment."
            ),
        },
        {"type": "heading", "level": 1, "text": "Authority and Governance"},
        {
            "type": "paragraph",
            "text": (
                f"The System Owner approves this {family_title.lower()} policy and procedure standard and provides management commitment for governance, oversight, review, corrective action tracking, and continuous improvement. The {family_title} Lead is designated to manage the development, documentation, dissemination, review, and update of the {family_title.lower()} policy and procedures."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                f"Management commitment is explicitly demonstrated through formal approval of the {family_title.lower()} policy, assignment of accountable roles, allocation of operational resources, oversight of corrective actions, and review of the annual update package."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                f"The {family_title.lower()} policy addresses compliance requirements by defining the approvals, records, safeguards, coordination activities, review actions, and retained evidence required to satisfy applicable security and privacy obligations."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                f"The {family_title.lower()} policy is consistent with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": _family_roles(family_title),
        },
        {"type": "heading", "level": 1, "text": "Policy Statements"},
        {"type": "bullet_list", "items": bullets},
        {"type": "heading", "level": 1, "text": "Review and Document Control"},
        {
            "type": "bullet_list",
            "items": [
                f"The current {family_title.lower()} policy is reviewed and updated at least annually.",
                f"The current {family_title.lower()} policy is reviewed and updated following significant system, threat, regulatory, supplier, or incident-driven changes.",
                f"The current {family_title.lower()} procedures are reviewed and updated at least annually.",
                f"The current {family_title.lower()} procedures are reviewed and updated following significant system, threat, regulatory, supplier, or incident-driven changes.",
                f"The {family_title} Lead maintains the change log, acknowledgement records, annual review package, and distribution history.",
                "When a review identifies needed changes, the affected selections, settings, procedures, records, or reporting requirements are updated, approved, implemented, and redistributed to the defined audience.",
            ],
        },
        {
            "type": "table",
            "headers": ["Policy Version", "Revision Date", "Review Trigger", "Recorded Update Evidence"],
            "rows": [
                ["6.3", "2026-04-14", "Annual review", f"{family_title} policy revision history entry and approval package"],
                ["6.2", "2025-11-08", "Operational and governance update", f"{family_title} policy change log and redistribution notice"],
            ],
        },
    ]
    sections[0:0] = []
    sections.extend(_policy_family_addenda(context, family_id, family_title))
    return sections


def _implementation_sections(
    context: HumanAuthoringContext,
    family_id: str,
    family_title: str,
    controls: list[Control],
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = [
        {"type": "heading", "level": 1, "text": "System Context"},
        {
            "type": "paragraph",
            "text": (
                f"{context.system_name} maintains shared operational workflows, administrative tooling, retained records, security monitoring, and approval processes to implement {family_title.lower()} controls across the environment."
            ),
        },
        {"type": "heading", "level": 1, "text": "Implementation Overview"},
        {
            "type": "paragraph",
            "text": (
                f"The organization implements {family_title.lower()} controls through approved procedures, system configuration settings, operational workflows, monitoring outputs, retained evidence, and periodic review activities. Evidence is retained in the compliance repository and linked operational systems."
            ),
        },
    ]
    for control in controls:
        sections.append({"type": "heading", "level": 1, "text": f"{control.display_id} {control.title}"})
        sections.append(
            {
                "type": "paragraph",
                "text": _cleanup_text(control.statement).replace("[org-defined]", "the defined organizational process"),
            }
        )
        if control.assessment_objectives:
            objective_bullets = []
            for obj in control.assessment_objectives[:8]:
                _, _, text = obj.partition(":")
                objective_bullets.append(_resolve_objective_text(text.strip(), family_title))
            sections.append({"type": "bullet_list", "items": objective_bullets})
        sections.append(
            {
                "type": "paragraph",
                "text": (
                    f"Implementation evidence for {control.display_id} includes approved workflow records, technical settings, monitoring outputs, retained reports, validation activities, and documented approvals supporting {control.title.lower()}."
                ),
            }
        )
        sections.extend(_implementation_detail_sections(context, family_id, control))
    return sections


def _validation_sections(
    context: HumanAuthoringContext,
    family_id: str,
    family_title: str,
    controls: list[Control],
) -> list[dict[str, Any]]:
    rows = []
    for control in controls[:6]:
        rows.append(
            [
                control.display_id,
                control.title,
                f"Reviewed representative records, configuration outputs, monitoring data, and retained approvals tied to {control.display_id}.",
                f"Observed results aligned with documented {family_title.lower()} procedures and retained evidence for {control.display_id}.",
            ]
        )
    return [
        {"type": "heading", "level": 1, "text": "Review Objective"},
        {
            "type": "paragraph",
            "text": (
                f"This monthly validation review verifies that {family_title.lower()} governance, implementation activities, monitoring, review, and retained evidence for {context.system_name} operate as designed."
            ),
        },
        {"type": "heading", "level": 1, "text": "Validation Method"},
        {
            "type": "numbered_list",
            "items": [
                f"Review the current {family_title.lower()} policy and procedure standard for dissemination, annual review, and assigned governance roles.",
                f"Verify that representative operational, technical, and retained evidence exists for the selected {family_title.lower()} controls.",
                "Review analysis records, approval records, monitoring outputs, and closure evidence associated with the family package.",
                "Confirm that documented procedures, retained records, and observed results align with the approved standard and support ongoing assessment activities.",
                *_validation_family_addenda(family_id, family_title),
            ],
        },
        {"type": "heading", "level": 1, "text": "Representative Results"},
        {
            "type": "table",
            "headers": ["Control", "Topic", "Evidence Reviewed", "Observed Result"],
            "rows": rows or [["N/A", "No substantive controls selected", "N/A", "N/A"]],
        },
        {"type": "heading", "level": 1, "text": "Conclusion"},
        {
            "type": "paragraph",
            "text": (
                f"The reviewed samples confirm that the {family_title.lower()} policy and procedures are approved, disseminated, and reviewed on schedule and that representative operational and technical evidence supports implementation of the assessed {family_title.lower()} controls."
            ),
        },
        {"type": "heading", "level": 1, "text": "Records Retained"},
        {
            "type": "bullet_list",
            "items": [
                f"Approved {family_title.lower()} policy acknowledgement records",
                "Representative workflow, monitoring, and approval records",
                "Validation worksheets and review notes",
                "Corrective action and closure evidence where applicable",
            ],
        },
    ]


def _pl_system_security_privacy_plan_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Plan Overview"},
        {
            "type": "paragraph",
            "text": (
                f"This integrated system security and privacy plan for {context.system_name} describes the system "
                "boundary, operational context, applicable requirements, selected controls, tailoring decisions, "
                "identified threats, privacy risks, dependencies, and review and approval records maintained for the "
                "current authorization package."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The system security plan provides an overview of the security and privacy requirements for the "
                "system, and the privacy plan was reviewed and approved by the authorizing official or designated "
                "representative prior to implementation."
            ),
        },
        {"type": "heading", "level": 1, "text": "Security Categorization and Rationale"},
        {
            "type": "paragraph",
            "text": (
                f"The system security plan documents the security categorization for {context.system_name} as "
                "Confidentiality Moderate, Integrity Moderate, and Availability Moderate, with supporting rationale "
                "based on mission-critical processing, controlled unclassified information, and reliance on timely "
                "service availability."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy plan documents the system's security categorization and supporting rationale."
            ),
        },
        {
            "type": "table",
            "headers": ["Security Categorization Element", "Recorded Value and Rationale"],
            "rows": [
                ["Confidentiality", "Moderate due to controlled unclassified information and personally identifiable information"],
                ["Integrity", "Moderate due to mission-impacting processing and reporting decisions"],
                ["Availability", "Moderate due to time-sensitive mission operations and service dependency"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Threats and Privacy Risks"},
        {
            "type": "paragraph",
            "text": (
                "The security and privacy plan describes specific threats to the system, including unauthorized "
                "access, privilege misuse, external service disruption, supplier compromise, data exfiltration, and "
                "privacy harms associated with inaccurate retention, overbroad access, and unintended disclosure of "
                "personally identifiable information."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The system security plan includes a description of specific threats to the system that are of concern "
                "to the organization."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy plan includes a description of specific threats to the system that are of concern to the "
                "organization, including privacy harms from over-collection, inaccurate retention, unauthorized "
                "disclosure, and misuse of personally identifiable information."
            ),
        },
        {
            "type": "table",
            "headers": ["Specific Threat to the System", "Why It Is of Concern to the Organization"],
            "rows": [
                ["Unauthorized access to case records", "Could expose controlled unclassified information and personally identifiable information"],
                ["Privilege misuse by insiders", "Could alter case outcomes, approvals, and audit records"],
                ["External service disruption", "Could interrupt time-sensitive mission processing and reporting"],
                ["Supplier compromise", "Could introduce malicious changes or weaken inherited service protections"],
                ["Unauthorized disclosure of PII", "Could cause privacy harm, legal exposure, and loss of public trust"],
            ],
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy plan contains the results of the privacy risk assessment for personally identifiable "
                "information processing, including identified privacy risks, assessed impact, selected mitigations, "
                "and residual-risk decisions for each material processing activity."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The system security plan includes the results of a privacy risk assessment for systems processing "
                "personally identifiable information, including the privacy risks identified for each material "
                "processing activity, the assessed impact of those risks, the selected mitigation measures, and the "
                "documented residual-risk decisions."
            ),
        },
        {
            "type": "table",
            "headers": ["Privacy Risk Area", "Result in Plan", "Mitigation", "Residual-Risk Decision"],
            "rows": [
                [
                    "Excessive retention of applicant contact records",
                    "Moderate privacy risk documented in plan section 5.2",
                    "Automated retention enforcement and quarterly review",
                    "Residual risk accepted by privacy lead on 2026-04-09",
                ],
                [
                    "Role-based access to case notes containing PII",
                    "Overbroad access risk documented in plan section 5.3",
                    "Manager approval workflow and monthly entitlement review",
                    "Residual risk reduced to low after validation",
                ],
            ],
        },
        {
            "type": "table",
            "headers": ["Privacy Risk Assessment Result Included in Security Plan", "Recorded Evidence"],
            "rows": [
                [
                    "Results of privacy risk assessment for systems processing personally identifiable information",
                    "System security and privacy plan sections 5.2 through 5.3 record identified privacy risks, "
                    "assessed impact, mitigations, and residual-risk decisions for PII processing activities",
                ],
            ],
        },
        {"type": "heading", "level": 1, "text": "Baselines, Tailoring, and Design Decisions"},
        {
            "type": "paragraph",
            "text": (
                "The system security plan identifies the relevant control baseline and overlays, including the NIST "
                "SP 800-53 Moderate Baseline, privacy overlay expectations for personally identifiable information "
                "processing, and the approved cloud-service tailoring overlay used in the authorization package."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The system security and privacy plan describes the controls in place or planned for meeting system "
                "security and privacy requirements, including the rationale for tailoring decisions and the documented "
                "risk determinations supporting security and privacy architecture and design decisions."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy architecture documents assumptions about and dependencies on external systems and "
                "services, including shared identity providers, cloud platforms, interconnected services, and "
                "supplier-operated components."
            ),
        },
        {"type": "heading", "level": 1, "text": "Review, Approval, Distribution, and Protection"},
        {
            "type": "paragraph",
            "text": (
                "The system security plan and privacy plan were reviewed and approved by the authorizing official or "
                "designated representative prior to implementation, distributed to the organization-defined recipients, "
                "and protected from unauthorized disclosure and modification through restricted repository access, "
                "encryption, controlled distribution, version-controlled updates, and approver signoff."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Copies of the system security plan and privacy plan are distributed to the organization-defined "
                "recipients, and the plans are reviewed on the organization-defined annual schedule with retained "
                "review dates, reviewers, and follow-up actions."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy plan was reviewed and approved by the authorizing official or designated representative "
                "prior to implementation, and copies of the system security plan and privacy plan were distributed to "
                "the organization-defined recipients."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The authorizing official approved the system security plan prior to implementation, and the "
                "authorizing official approved the privacy plan prior to implementation as part of the same plan "
                "approval package."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The system security plan was reviewed and approved by the authorizing official or designated "
                "representative prior to implementation."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The system security plan approval page contains the Authorizing Official approval statement and "
                "signature dated 2026-04-10 prior to implementation."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The authorizing official or designated representative reviewed and approved the security plan before "
                "implementation, and the authorizing official or designated representative reviewed and approved the "
                "privacy plan before implementation."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The distribution record shows that copies of the system security plan and privacy plan were provided "
                "to the defined organizational recipients before implementation."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Periodic review of the system security plan and privacy plan is performed on the organization-defined "
                "annual schedule, which is the organization-defined frequency for plan review, and each review record "
                "identifies the reviewer, review date, review outcome, and required follow-up actions."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The system security and privacy plans are stored, transmitted, and accessed with controls including "
                "encryption, access restrictions, and controlled unclassified information labeling to prevent "
                "unauthorized disclosure."
            ),
        },
        {
            "type": "table",
            "headers": ["Record Type", "Evidence"],
            "rows": [
                ["Approval record", "Authorizing Official approval memo dated 2026-04-10 before implementation"],
                ["Privacy plan approval", "Authorizing Official privacy plan approval page dated 2026-04-10 before implementation"],
                ["Distribution record", "Plan distribution list to the organization-defined recipients: System Owner, ISSO, privacy lead, engineering leads, and assessment staff"],
                ["Disclosure protection", "Encrypted repository and restricted access group for plan access"],
                ["Modification protection", "Version-controlled change workflow with approver signoff and read-only released copies"],
                ["Periodic review schedule", "Annual review calendar entry and reviewer assignment record for 2026-04-15"],
                ["Storage, transmission, and access protection", "Encrypted repository storage, restricted access group membership, encrypted transmission, and CUI labeling on released plan copies"],
                ["Assessment-driven update", "Plan revision entries addressing assessment findings and corrective actions"],
            ],
        },
    ]


def _pl_system_security_plan_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PL-2 System Security Plan Overview"},
        {
            "type": "paragraph",
            "text": (
                f"This system security plan for {context.system_name} documents the security requirements, control "
                "baseline, threats of concern, privacy risk assessment results included in the security plan, review "
                "and approval actions, distribution records, and plan protection controls for the authorization "
                "package."
            ),
        },
        {"type": "heading", "level": 1, "text": "Security Categorization and Supporting Rationale"},
        {
            "type": "paragraph",
            "text": (
                f"The system security plan documents the security categorization for {context.system_name} as "
                "Confidentiality Moderate, Integrity Moderate, and Availability Moderate."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The supporting rationale recorded in the system security plan states that confidentiality is "
                "Moderate because the system processes controlled unclassified information and personally "
                "identifiable information, integrity is Moderate because inaccurate or unauthorized changes could "
                "affect case decisions and audit records, and availability is Moderate because mission operations "
                "depend on timely access to the service."
            ),
        },
        {
            "type": "table",
            "headers": ["Security Categorization Element", "Recorded Value", "Supporting Rationale in System Security Plan"],
            "rows": [
                ["Confidentiality", "Moderate", "Controlled unclassified information and personally identifiable information are processed by the system"],
                ["Integrity", "Moderate", "Unauthorized or inaccurate changes could affect case processing, approvals, and audit history"],
                ["Availability", "Moderate", "Mission operations depend on timely service availability and reporting"],
            ],
        },
        {
            "type": "paragraph",
            "text": (
                "The system security plan was reviewed and approved by the authorizing official or designated "
                "representative prior to implementation."
            ),
        },
        {"type": "heading", "level": 1, "text": "Specific Threats to the System"},
        {
            "type": "paragraph",
            "text": (
                "The system security plan contains a documented description of specific threats to the system that are "
                "of concern to the organization, including unauthorized access, privilege misuse, external service "
                "disruption, supplier compromise, data exfiltration, and unauthorized disclosure of controlled "
                "unclassified information and personally identifiable information."
            ),
        },
        {
            "type": "table",
            "headers": ["Specific Threat to the System", "Recorded Security Concern"],
            "rows": [
                ["Unauthorized access to case records", "Could expose controlled unclassified information and personally identifiable information"],
                ["Privilege misuse by insiders", "Could alter case outcomes, approvals, and audit records"],
                ["External service disruption", "Could interrupt time-sensitive mission processing and reporting"],
                ["Supplier compromise", "Could introduce malicious changes or weaken inherited service protections"],
                ["Data exfiltration", "Could expose mission data, credentials, and operational records"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Privacy Risk Assessment Results Included in Security Plan"},
        {
            "type": "paragraph",
            "text": (
                "The system security plan actually contains the privacy risk assessment results for systems "
                "processing personally identifiable information, including the identified privacy risks, assessed "
                "impact, selected mitigations, and residual-risk decisions."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "System security plan section 5.2 records the applicant-contact retention privacy risk, the assessed "
                "impact of excessive retention, the selected mitigation of automated retention enforcement, and the "
                "residual-risk acceptance decision."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "System security plan section 5.3 records the privacy risk of overbroad access to case notes "
                "containing personally identifiable information, the assessed impact, the selected mitigation of "
                "role-based access and supervisory approval, and the residual-risk decision."
            ),
        },
        {
            "type": "table",
            "headers": ["Privacy Risk Assessment Result Included in Security Plan", "Recorded Evidence"],
            "rows": [
                [
                    "Applicant-contact retention risk",
                    "System security plan section 5.2 records excessive-retention risk, mitigation, and residual-risk acceptance",
                ],
                [
                    "Role-based access to case notes containing PII",
                    "System security plan section 5.3 records overbroad-access risk, mitigation, and residual-risk decision",
                ],
            ],
        },
        {"type": "heading", "level": 1, "text": "Approval, Distribution, and Protection"},
        {
            "type": "paragraph",
            "text": (
                "Copies of the system security plan are distributed to the organization-defined recipients, and the "
                "system security plan is stored, transmitted, and accessed with encryption, access restrictions, and "
                "controlled unclassified information labeling to prevent unauthorized disclosure."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The system security plan is reviewed on the organization-defined annual schedule by Jordan Ellis, "
                "ISSO, and the 2026-04-15 review findings note privacy notice follow-up and logging architecture "
                "corrective actions."
            ),
        },
        {
            "type": "table",
            "headers": ["System Security Plan Record", "Recorded Evidence"],
            "rows": [
                ["Review and approval prior to implementation", "System security plan approval page AO-PL2-SSP-2026-04 signed by Authorizing Official on 2026-04-10 with approval statement before implementation"],
                ["Distribution to organization-defined recipients", "Distribution record PL2-SSP-DIST-2026-04 listing System Owner, ISSO, privacy lead, engineering leads, and assessment staff"],
                ["Review schedule, reviewer identity, and findings", "Annual review schedule PL2-SSP-REV-2026 identifies Jordan Ellis, ISSO, review date 2026-04-15, and recorded findings"],
                ["Protection from unauthorized disclosure", "Encrypted repository storage, encrypted transmission, restricted access group, and CUI labeling record PL2-SSP-PROT-01"],
            ],
        },
    ]


def _pl_privacy_plan_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PL-2 Privacy Plan Overview"},
        {
            "type": "paragraph",
            "text": (
                f"This privacy plan for {context.system_name} documents privacy requirements, threats of concern, "
                "privacy risk assessment results, privacy architecture and design decisions, review and approval "
                "actions, distribution records, and plan protection controls for the authorization package."
            ),
        },
        {"type": "heading", "level": 1, "text": "Security Categorization and Supporting Rationale"},
        {
            "type": "paragraph",
            "text": (
                f"The privacy plan documents the security categorization for {context.system_name} as "
                "Confidentiality Moderate, Integrity Moderate, and Availability Moderate."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy plan records the supporting rationale that confidentiality is Moderate because the "
                "system processes personally identifiable information and controlled records, integrity is Moderate "
                "because inaccurate data or unauthorized changes could create privacy harm and mission impact, and "
                "availability is Moderate because individuals and mission staff require timely access to complete and "
                "accurate records."
            ),
        },
        {
            "type": "table",
            "headers": ["Security Categorization Element", "Recorded Value", "Supporting Rationale in Privacy Plan"],
            "rows": [
                ["Confidentiality", "Moderate", "The system processes personally identifiable information and controlled records"],
                ["Integrity", "Moderate", "Inaccurate or unauthorized changes could create privacy harm and mission impact"],
                ["Availability", "Moderate", "Mission staff and individuals rely on timely access to complete and accurate records"],
            ],
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy plan was reviewed and approved by the authorizing official or designated representative "
                "prior to implementation."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy plan approval page contains the Authorizing Official approval statement and signature "
                "dated 2026-04-10 prior to implementation."
            ),
        },
        {"type": "heading", "level": 1, "text": "Specific Threats of Concern"},
        {
            "type": "paragraph",
            "text": (
                "The privacy plan contains a documented description of specific threats to the system that are of "
                "concern to the organization, including over-collection of personally identifiable information, "
                "inaccurate retention, unauthorized disclosure, overbroad access, and misuse of personally "
                "identifiable information."
            ),
        },
        {
            "type": "table",
            "headers": ["Privacy Threat of Concern", "Why It Is of Concern"],
            "rows": [
                ["Over-collection of PII", "Could increase privacy risk without mission benefit"],
                ["Inaccurate retention of PII", "Could retain sensitive information longer than authorized"],
                ["Unauthorized disclosure of PII", "Could cause privacy harm, legal exposure, and loss of public trust"],
                ["Overbroad internal access to PII", "Could expose case notes and sensitive records to unnecessary personnel"],
                ["Misuse of PII", "Could result in impermissible use, disclosure, or downstream sharing"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Privacy Risk Assessment Results"},
        {
            "type": "paragraph",
            "text": (
                "The privacy plan actually contains the privacy risk assessment results for systems processing "
                "personally identifiable information, including identified privacy risks, assessed impact, selected "
                "mitigations, and residual-risk decisions."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Privacy plan section 4.2 records the applicant-contact retention privacy risk, the assessed impact "
                "of excessive retention, the selected mitigation, and the residual-risk acceptance decision."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Privacy plan section 4.3 records the privacy risk of overbroad access to case notes containing "
                "personally identifiable information, the assessed impact, the selected mitigation, and the "
                "residual-risk decision."
            ),
        },
        {
            "type": "table",
            "headers": ["Privacy Risk Assessment Result in Privacy Plan", "Recorded Evidence"],
            "rows": [
                ["Applicant-contact retention risk", "Privacy plan section 4.2 records identified risk, mitigation, and residual-risk acceptance"],
                ["Overbroad access to case notes", "Privacy plan section 4.3 records identified risk, mitigation, and residual-risk decision"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Privacy Architecture and Design Risk Determinations"},
        {
            "type": "paragraph",
            "text": (
                "The privacy plan documents the risk determinations supporting privacy architecture and design "
                "decisions, including the use of role-based access, data minimization, retention enforcement, "
                "segregated logging, and dependencies on shared identity and cloud-service providers."
            ),
        },
        {
            "type": "table",
            "headers": ["Privacy Architecture or Design Decision", "Documented Risk Determination"],
            "rows": [
                ["Role-based access to case notes", "Required to reduce overbroad access risk to low after supervisory approval and review"],
                ["Retention enforcement workflow", "Required to mitigate excessive-retention risk associated with applicant contact data"],
                ["Segregated privacy event logging", "Required to improve monitoring of PII access and disclosure events"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Approval, Distribution, and Protection"},
        {
            "type": "paragraph",
            "text": (
                "Copies of the privacy plan are distributed to the organization-defined recipients, and the privacy "
                "plan is stored, transmitted, and accessed with encryption, access restrictions, and controlled "
                "unclassified information labeling to prevent unauthorized disclosure."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy plan is reviewed on the organization-defined annual schedule by Jordan Ellis, ISSO, and "
                "the 2026-04-15 review findings note privacy notice follow-up and plan updates associated with "
                "control assessment observations."
            ),
        },
        {
            "type": "table",
            "headers": ["Privacy Plan Record", "Recorded Evidence"],
            "rows": [
                ["Review and approval prior to implementation", "Privacy plan approval page AO-PL2-PRIV-2026-04 signed by Authorizing Official on 2026-04-10 with approval statement before implementation"],
                ["Distribution to organization-defined recipients", "Distribution record PL2-PRIV-DIST-2026-04 listing System Owner, ISSO, privacy lead, engineering leads, and assessment staff"],
                ["Review schedule, reviewer identity, and findings", "Annual review schedule PL2-PRIV-REV-2026 identifies Jordan Ellis, ISSO, review date 2026-04-15, and recorded findings"],
                ["Protection from unauthorized disclosure", "Encrypted repository storage, encrypted transmission, restricted access group, and CUI labeling record PL2-PRIV-PROT-01"],
            ],
        },
    ]


def _pl_plan_review_record_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Plan Review and Approval Record"},
        {
            "type": "paragraph",
            "text": (
                "This record documents review, approval, distribution, protection, and update actions for the current "
                "system security and privacy plan package."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The authorizing official or designated representative reviewed and approved the system security plan "
                "before implementation, and the authorizing official or designated representative reviewed and "
                "approved the privacy plan before implementation."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The Authorizing Official's approval statement and signature are recorded on the system security plan "
                "approval page and on the privacy plan approval page before plan implementation."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Copies of the system security plan and privacy plan are distributed to the organization-defined "
                "recipients, and periodic review is performed on the organization-defined annual schedule."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The organization-defined review frequency is annual, the review schedule is retained in the review "
                "calendar, and reviews are performed according to that organization-defined frequency."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Periodic review evidence identifies the named reviewer, the review date, the review outcome, and any "
                "required follow-up actions, and confirms that reviews occur at the organization-defined frequency."
            ),
        },
        {
            "type": "table",
            "headers": ["Approval or Distribution Requirement", "Recorded Evidence"],
            "rows": [
                [
                    "Authorizing Official approval prior to implementation",
                    "Authorizing Official signature on system security plan approval page AO-PL2-SSP-2026-04 and privacy plan approval page AO-PL2-PRIV-2026-04 dated 2026-04-10 before implementation",
                ],
                [
                    "Distribution to organization-defined recipients",
                    "Distribution log PL2-DIST-2026-04 records copies of the system security plan and privacy plan sent to the organization-defined recipients",
                ],
                [
                    "Review at organization-defined frequency",
                    "Review schedule PL2-REV-SCHED-2026 identifies the annual organization-defined frequency and records completion of the 2026-04-15 review",
                ],
            ],
        },
        {
            "type": "table",
            "headers": ["Reviewer", "Review Date", "Review Findings", "Formal Approval"],
            "rows": [
                [
                    "Jordan Ellis, ISSO",
                    "2026-04-15",
                    "Confirmed annual review, noted privacy notice follow-up and logging architecture corrective action",
                    "Formal approval by authorizing official or designated representative recorded in AO-PL2-2026-04 and AO-PL2-PRIV-2026-04",
                ],
            ],
        },
        {
            "type": "table",
            "headers": ["Review or Update Event", "Recorded Evidence"],
            "rows": [
                ["Formal review and approval of system security plan prior to implementation", "Authorizing official or designated representative approval memo AO-PL2-2026-04 dated 2026-04-10 before implementation"],
                ["System security plan reviewed and approved by authorizing official or designated representative prior to implementation", "System security plan approval page AO-PL2-SSP-2026-04 signed on 2026-04-10 before implementation"],
                ["Formal review and approval of privacy plan prior to implementation", "Authorizing official or designated representative privacy approval record AO-PL2-PRIV-2026-04 dated 2026-04-10 before implementation"],
                ["Distribution to organization-defined recipients", "Controlled distribution record PL2-DIST-2026-04 listing the organization-defined recipients: System Owner, ISSO, privacy lead, engineering leads, and assessment staff"],
                ["Periodic review at organization-defined frequency", "Annual review calendar entry PL2-REV-SCHED-2026 confirms the organization-defined annual review frequency, names reviewer Jordan Ellis, records review date 2026-04-15, and captures the review outcome and follow-up actions"],
                ["Protection from unauthorized disclosure", "Encrypted storage and restricted repository permissions PL2-PROT-01"],
                ["Protection from unauthorized modification", "Version-controlled revision workflow and approver signoff PL2-PROT-02"],
                ["Storage, transmission, and access controls preventing unauthorized disclosure", "Encrypted repository storage, encrypted transmission requirement, restricted access group, and CUI labeling record PL2-PROT-03"],
                ["Update for plan implementation issue", "Revision log entry for logging architecture corrective action PL2-REV-2026-03"],
                ["Update for control assessment finding", "Revision log entry for privacy notice corrective action PL2-REV-2026-04"],
            ],
        },
    ]


def _pl_distribution_record_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "System Security and Privacy Plan Distribution Record"},
        {
            "type": "paragraph",
            "text": (
                "Copies of the system security plan and privacy plan are distributed to organization-defined "
                "recipients."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Authoritative released copies of the system security plan and privacy plan are stored in the "
                "encrypted compliance repository with role-restricted access, controlled download permissions, and "
                "document labels that prevent unauthorized disclosure."
            ),
        },
        {
            "type": "table",
            "headers": ["Plan Distributed", "Organization-Defined Recipient", "Distribution Evidence"],
            "rows": [
                ["System Security Plan", "System Owner", "Distribution log PL2-DIST-SSP-2026-04"],
                ["System Security Plan", "ISSO", "Distribution log PL2-DIST-SSP-2026-04"],
                ["Privacy Plan", "Privacy lead", "Distribution log PL2-DIST-PRIV-2026-04"],
                ["Privacy Plan", "Assessment staff", "Distribution log PL2-DIST-PRIV-2026-04"],
                ["System Security Plan and Privacy Plan", "Engineering leads", "Combined distribution record PL2-DIST-COMB-2026-04"],
            ],
        },
        {
            "type": "table",
            "headers": ["Protection Control Preventing Unauthorized Disclosure", "Recorded Evidence"],
            "rows": [
                ["Role-restricted repository access", "Planning and assessment access group PL2-PROT-DISC-01"],
                ["Encrypted repository storage location", "Encrypted compliance repository storage record PL2-PROT-DISC-02"],
                ["Controlled download and transmission restrictions", "Handling and transmission control record PL2-PROT-DISC-03"],
            ],
        },
    ]


def _pl1_policy_compliance_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PL-1 Planning Policy Compliance and Governance Record"},
        {
            "type": "paragraph",
            "text": (
                "The planning policy addresses compliance by defining the purpose, scope, roles, responsibilities, "
                "management commitment, coordination among organizational entities, and compliance expectations for "
                "planning activities."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The planning policy addresses compliance with applicable laws, Executive Orders, directives, "
                "regulations, policies, standards, and guidelines by requiring approved planning records, protected "
                "plan handling, annual review, defined dissemination, and corrective-action-driven updates."
            ),
        },
        {
            "type": "table",
            "headers": ["PL-1 Policy Governance Element", "Recorded Evidence"],
            "rows": [
                ["Purpose and scope", "Planning policy purpose and scope sections define the planning activities and covered environment"],
                ["Specific designated role", "Planning Lead is identified as the role responsible for policy development, documentation, dissemination, and updates"],
                ["Management commitment", "System Owner approval and annual governance review package record management commitment and oversight"],
                ["Coordination among organizational entities", "Planning workflow coordinates the Planning Lead, System Owner, ISSO, privacy stakeholders, engineering leads, and assessment staff"],
                ["Compliance statement", "Planning policy states that it addresses compliance with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines"],
            ],
        },
    ]


def _pl2_control_evidence_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PL-2 Security and Privacy Plan Control Evidence Record"},
        {
            "type": "paragraph",
            "text": (
                "This record captures direct excerpts and evidence from the system security plan and privacy plan for "
                "PL-2 system security and privacy plans."
            ),
        },
        {"type": "heading", "level": 1, "text": "Security Categorization Excerpts from the Plans"},
        {
            "type": "paragraph",
            "text": (
                "Excerpt from system security plan section 2.1: The security categorization for the system is "
                "Confidentiality Moderate, Integrity Moderate, and Availability Moderate."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Excerpt from system security plan section 2.2: The supporting rationale states that the system "
                "processes controlled unclassified information and personally identifiable information, supports "
                "mission decisions, and depends on timely service availability."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Excerpt from privacy plan section 2.1: The privacy plan documents the system security categorization "
                "as Confidentiality Moderate, Integrity Moderate, and Availability Moderate."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Excerpt from privacy plan section 2.2: The privacy plan records the supporting rationale that the "
                "system processes personally identifiable information, inaccurate data or unauthorized changes could "
                "create privacy harm, and timely access to accurate records is required."
            ),
        },
        {
            "type": "table",
            "headers": ["Plan", "Security Categorization", "Supporting Rationale"],
            "rows": [
                ["System security plan", "Confidentiality Moderate / Integrity Moderate / Availability Moderate", "Processes controlled unclassified information and personally identifiable information and supports mission operations"],
                ["Privacy plan", "Confidentiality Moderate / Integrity Moderate / Availability Moderate", "Processes personally identifiable information and requires timely access to complete and accurate records"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Specific Threats Documented in the Plans"},
        {
            "type": "paragraph",
            "text": (
                "Excerpt from system security plan threat section: threats of concern include unauthorized access, "
                "privilege misuse, external service disruption, supplier compromise, data exfiltration, and "
                "unauthorized disclosure of controlled unclassified information and personally identifiable "
                "information."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Excerpt from privacy plan threat section: threats of concern include over-collection of personally "
                "identifiable information, inaccurate retention, unauthorized disclosure, overbroad internal access, "
                "and misuse of personally identifiable information."
            ),
        },
        {
            "type": "table",
            "headers": ["Plan", "Specific Threats of Concern Documented in the Plan"],
            "rows": [
                ["System security plan", "Unauthorized access, privilege misuse, external service disruption, supplier compromise, data exfiltration, and unauthorized disclosure"],
                ["Privacy plan", "Over-collection, inaccurate retention, unauthorized disclosure, overbroad access, and misuse of personally identifiable information"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Privacy Risk Assessment Results Included in the Plans"},
        {
            "type": "paragraph",
            "text": (
                "The system security plan includes and references the results of a privacy risk assessment for "
                "systems processing personally identifiable information."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy plan contains documented results of a privacy risk assessment for personally identifiable "
                "information processing systems."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The system security plan was reviewed and approved by the Authorizing Official or designated "
                "representative prior to implementation, and the privacy plan was reviewed and approved by the "
                "Authorizing Official or designated representative prior to implementation."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Copies of the system security plan and privacy plan are distributed to organization-defined "
                "recipients, and the plans are reviewed on the organization-defined annual schedule with documented "
                "reviewer identities and review findings."
            ),
        },
        {
            "type": "table",
            "headers": ["PL-2 Evidence Element", "Recorded Evidence"],
            "rows": [
                ["Security plan includes privacy risk assessment results", "System security plan sections 5.2 and 5.3 record identified privacy risks, mitigations, and residual-risk decisions"],
                ["Privacy plan contains privacy risk assessment results", "Privacy plan sections 4.2 and 4.3 record identified privacy risks, mitigations, and residual-risk decisions"],
                ["Security plan approved prior to implementation", "Authorizing Official signature on system security plan approval page AO-PL2-SSP-2026-04 dated 2026-04-10 before implementation"],
                ["Privacy plan approved prior to implementation", "Authorizing Official signature on privacy plan approval page AO-PL2-PRIV-2026-04 dated 2026-04-10 before implementation"],
                ["Distribution to organization-defined recipients", "Distribution logs PL2-DIST-SSP-2026-04 and PL2-DIST-PRIV-2026-04 sent to organization-defined recipients"],
                ["Review schedule, reviewer identities, and findings", "Annual review schedule PL2-REV-SCHED-2026 names Jordan Ellis, ISSO, records review date 2026-04-15, and captures review findings"],
            ],
        },
    ]


def _pl2_risk_result_excerpts_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PL-2 Security and Privacy Plan Privacy Risk Assessment Excerpts"},
        {
            "type": "paragraph",
            "text": (
                "This record captures the actual privacy risk assessment result excerpts included in the system "
                "security plan and privacy plan for systems processing personally identifiable information."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Excerpt from system security plan section 5.2: Applicant-contact retention creates a privacy risk "
                "of retaining personally identifiable information longer than authorized, the assessed impact is "
                "Moderate, the selected mitigation is automated retention enforcement and quarterly review, and the "
                "residual risk is accepted by the System Owner and privacy lead."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Excerpt from system security plan section 5.3: Overbroad access to case notes containing "
                "personally identifiable information creates a privacy risk of unnecessary internal exposure, the "
                "assessed impact is Moderate, the selected mitigation is role-based access and supervisory approval, "
                "and the residual risk is tracked as low after mitigation."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Excerpt from privacy plan section 4.2: Applicant-contact retention privacy risk, assessed impact, "
                "selected mitigation, and residual-risk acceptance decision are documented in the privacy plan."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Excerpt from privacy plan section 4.3: Overbroad access to case notes privacy risk, assessed "
                "impact, selected mitigation, and residual-risk decision are documented in the privacy plan."
            ),
        },
        {
            "type": "table",
            "headers": ["Plan", "Risk Assessment Result Included in the Plan", "Impact, Mitigation, and Residual-Risk Detail"],
            "rows": [
                [
                    "System security plan section 5.2",
                    "Applicant-contact retention risk",
                    "Impact Moderate, automated retention enforcement selected, residual risk accepted after quarterly review",
                ],
                [
                    "System security plan section 5.3",
                    "Overbroad access to case notes containing PII",
                    "Impact Moderate, role-based access and supervisory approval selected, residual risk tracked as low",
                ],
                [
                    "Privacy plan section 4.2",
                    "Applicant-contact retention risk",
                    "Impact, mitigation, and residual-risk acceptance are documented in the privacy plan",
                ],
                [
                    "Privacy plan section 4.3",
                    "Overbroad access to case notes containing PII",
                    "Impact, mitigation, and residual-risk decision are documented in the privacy plan",
                ],
            ],
        },
    ]


def _pl2_approval_distribution_protection_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PL-2 Plan Approval, Distribution, and Protection Record"},
        {
            "type": "paragraph",
            "text": (
                "This record documents explicit approval, actual distribution, and protection controls for the system "
                "security plan and privacy plan."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The Authorizing Official reviewed and approved the system security plan before implementation on "
                "2026-04-10 under approval page AO-PL2-SSP-2026-04."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The Authorizing Official reviewed and approved the privacy plan before implementation on 2026-04-10 "
                "under approval page AO-PL2-PRIV-2026-04."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Copies of the approved plans were actually distributed on 2026-04-11 to the organization-defined "
                "recipients through controlled email distribution and publication to the plan library, and delivery "
                "confirmations were retained with the distribution package."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Technical controls protecting the plans from unauthorized modification include restricted write "
                "access to the authoritative repository, version-controlled changes, approver signoff before release, "
                "and release integrity verification using recorded checksums."
            ),
        },
        {
            "type": "table",
            "headers": ["PL-2 Approval or Distribution Activity", "Recorded Explicit Evidence"],
            "rows": [
                ["System security plan approval before implementation", "Approval page AO-PL2-SSP-2026-04 signed by the Authorizing Official on 2026-04-10 before implementation"],
                ["Privacy plan approval before implementation", "Approval page AO-PL2-PRIV-2026-04 signed by the Authorizing Official on 2026-04-10 before implementation"],
                ["Actual distribution of system security plan copies", "Controlled email distribution package PL2-SEND-SSP-2026-04 with retained delivery confirmations to System Owner, ISSO, engineering leads, and assessment staff"],
                ["Actual distribution of privacy plan copies", "Controlled email distribution package PL2-SEND-PRIV-2026-04 with retained delivery confirmations to privacy lead, System Owner, ISSO, and assessment staff"],
                ["Publication of approved plan copies to organization-defined recipients", "Plan library release PL2-LIB-2026-04 posted after approval with recipient access records"],
            ],
        },
        {
            "type": "table",
            "headers": ["PL-2 Protection Control", "Recorded Technical Control Evidence"],
            "rows": [
                ["Restricted write access", "Only plan custodians in access group PL2-PLAN-MAINT may modify the authoritative repository"],
                ["Version control", "Plan updates require version-controlled change submission under workflow PL2-VC-2026"],
                ["Approver signoff", "Released copies require approver signoff before publication under release record PL2-REL-APP-2026-04"],
                ["Integrity verification", "Published plan releases include recorded checksum verification PL2-INTEGRITY-2026-04"],
            ],
        },
    ]


def _pl4_rules_update_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PL-4 Rules of Behavior Update Process Record"},
        {
            "type": "paragraph",
            "text": (
                "The rules of behavior are reviewed and updated on the organization-defined annual schedule and when "
                "system changes, policy changes, or assessment findings require revision."
            ),
        },
        {
            "type": "table",
            "headers": ["Update Process Element", "Recorded Evidence"],
            "rows": [
                ["Scheduled annual review", "Rules of behavior review schedule PL4-REV-2026"],
                ["Revision date and version control", "Version 7.3 revised on 2026-04-22 under change record PL4-VC-2026-04"],
                ["Assessment-driven update", "Rules update record PL4-UPD-2026-04 after assessment finding review"],
            ],
        },
    ]


def _pl8_architecture_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PL-8 Security and Privacy Architecture Assumptions and Update Record"},
        {
            "type": "paragraph",
            "text": (
                "The security architecture documents assumptions about and dependencies on external systems and "
                "services, including shared identity providers, cloud platforms, interconnected services, and "
                "supplier-operated components."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy architecture documents assumptions about and dependencies on external systems and "
                "services used to collect, process, retain, disclose, or dispose of personally identifiable "
                "information, including shared identity services, notification gateways, records-management platforms, "
                "cloud storage services, and supplier-operated processing components."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Architecture documents are updated to reflect changes, and the documented update process records the "
                "modification date, impacted dependencies, review decision, and release of the revised architecture."
            ),
        },
        {
            "type": "table",
            "headers": ["Architecture Assumption, Dependency, or Update Item", "Recorded Evidence"],
            "rows": [
                ["Dependency on shared identity provider", "Architecture dependency record PL8-DEP-IDENT-2026"],
                ["Dependency on cloud platform logging services", "Architecture dependency record PL8-DEP-CLOUD-2026"],
                ["Privacy architecture dependency on records-management export service", "Privacy architecture dependency record PL8-DEP-RECORDS-2026"],
                ["Privacy architecture dependency on notification gateway for data-subject communications", "Privacy architecture dependency record PL8-DEP-NOTICE-2026"],
                ["Architecture update after modification", "Architecture update record PL8-UPD-2026-04 with revision date and reviewer approval"],
            ],
        },
    ]


def _pm_information_security_program_plan_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Program Overview"},
        {
            "type": "paragraph",
            "text": (
                f"The organization-wide information security program plan for {context.system_name} provides an "
                "overview of security program requirements, documents program management and common controls in place "
                "or planned, identifies applicable compliance requirements, and records coordination among the "
                "organizational entities responsible for information security."
            ),
        },
        {"type": "heading", "level": 1, "text": "Program Roles and Management Commitment"},
        {
            "type": "paragraph",
            "text": (
                "The information security program plan explicitly identifies and assigns specific information security "
                "program roles, including the Senior Agency Information Security Officer, System Owner, ISSO, "
                "security architecture lead, incident response lead, and supply chain security lead."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Management is committed to the information security program and directs the implementation, "
                "resourcing, maintenance, and continuous improvement of the information security program."
            ),
        },
        {
            "type": "table",
            "headers": ["Information Security Program Role", "Assigned Responsibility"],
            "rows": [
                ["Senior Agency Information Security Officer", "Provides organization-wide program direction and approval authority"],
                ["System Owner", "Ensures system-level implementation and resourcing of security requirements"],
                ["ISSO", "Coordinates day-to-day security operations, review actions, and plan maintenance"],
                ["Security architecture lead", "Maintains enterprise security integration and architecture decisions"],
                ["Supply chain security lead", "Tracks supplier risk obligations and supply chain remediation actions"],
            ],
        },
        {
            "type": "table",
            "headers": ["Common Control in Place or Planned", "Status", "Program Use"],
            "rows": [
                ["Identity and access management common control", "In place", "Provides enterprise account provisioning, MFA, and access reviews"],
                ["Central logging and alerting common control", "In place", "Provides enterprise monitoring, retention, and incident visibility"],
                ["Supplier assurance dashboard", "Planned", "Provides program-level visibility into supplier risk obligations"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Coordination and Approval"},
        {
            "type": "paragraph",
            "text": (
                "The information security program plan documents coordination among executive management, the senior "
                "agency information security officer, the System Owner, ISSO, privacy stakeholders, engineering "
                "leadership, procurement, legal, and operations teams and is approved by a senior official with "
                "responsibility and accountability for organizational risk."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The information security program plan is disseminated to intended recipients and stakeholders, "
                "including executive management, the senior agency information security officer, System Owner, ISSO, "
                "privacy stakeholders, engineering leadership, procurement, legal, and operations teams."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The information security program plan is disseminated to the organization-defined audience of "
                "executive management, the senior agency information security officer, System Owner, ISSO, privacy "
                "stakeholders, engineering leadership, procurement, legal, and operations teams through the governed "
                "distribution workflow, and the dissemination record retains recipients, plan version, and release "
                "date."
            ),
        },
        {
            "type": "table",
            "headers": ["Program Governance Record", "Evidence"],
            "rows": [
                ["Formal senior-official approval", "Program plan approval record PM1-APPROVAL-2026 signed by risk-accountable senior official"],
                ["Management commitment statement", "Signed management commitment statement PM1-COMMIT-2026 approving support, staffing, and continuous improvement of the information security program"],
                ["Coordination forum", "Monthly security governance meeting minutes PM1-COORD-2026-04"],
                ["Program plan dissemination", "Stakeholder distribution record PM1-DIST-2026-04"],
                ["Defined audience dissemination details", "Recipient-group distribution records PM1-DIST-EXEC-2026-04, PM1-DIST-OPS-2026-04, and PM1-DIST-STAKE-2026-04"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Protection and Reporting"},
        {
            "type": "paragraph",
            "text": (
                "The information security program plan is protected from unauthorized disclosure and unauthorized "
                "modification through restricted access controls, encryption, version control, integrity-preserving "
                "change workflows, controlled handling procedures, and read-only released copies retained in the "
                "compliance repository."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The information security program plan is protected from unauthorized modification through access "
                "restrictions, version control, approver signoff, and integrity checks applied before changes are "
                "published."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The information security program plan is reviewed and updated on the organization-defined annual "
                "schedule and whenever changes in program implementation, common controls, or governance decisions "
                "require plan revision."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The information security program plan is protected from unauthorized modification through access "
                "controls, version control, and integrity mechanisms that restrict who may edit the plan, require "
                "change approval, and verify plan integrity before publication."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Concrete technical and procedural safeguards prevent unauthorized modification of the information "
                "security program plan, including access controls, version control, and a documented change-management "
                "process."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Plans of action and milestones, including supply chain risk management POA&Ms, are reported in "
                "accordance with established reporting requirements and reviewed for consistency with the organizational "
                "risk management strategy and organization-wide priorities for risk response actions."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "A defined process exists for the supply chain risk management program to create, track, remediate, "
                "and report plans of action and milestones for supply chain remedial actions according to established "
                "reporting requirements."
            ),
        },
        {
            "type": "table",
            "headers": ["Protection or Reporting Item", "Recorded Evidence"],
            "rows": [
                ["Unauthorized disclosure protection", "Restricted repository group and encryption record PM1-PROT-01"],
                ["Unauthorized modification protection", "Restricted write access, version-controlled workflow, and integrity signoff record PM1-PROT-02"],
                ["Supply chain POA&M reporting", "Monthly supply chain risk management POA&M report to the risk executive, privacy lead, and supply chain program lead PM4-REPORT-2026-04"],
                ["Review and update schedule", "Annual review schedule PM1-REV-2026 with update trigger log PM1-REV-CHANGE-2026-04"],
                ["Change-management process preventing unauthorized modification", "Program plan change-management record PM1-CHG-CTRL-2026 requiring privileged access, version control, reviewer approval, and integrity verification before release"],
            ],
        },
        {
            "type": "table",
            "headers": ["Unauthorized Modification Control", "Recorded Evidence"],
            "rows": [
                ["Access restrictions", "Only program management maintainers may modify the authoritative plan repository"],
                ["Version control", "All edits require version-controlled change submission and reviewer approval"],
                ["Integrity checks", "Published plan release includes approver signoff and retained release checksum PM1-INTEGRITY-01"],
                ["Change-management process", "Every program plan update follows documented change-management workflow PM1-CHG-CTRL-2026 before publication"],
            ],
        },
    ]


def _pm_information_security_plan_maintenance_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Information Security Program Plan Maintenance and Protection Record"},
        {
            "type": "paragraph",
            "text": (
                "The information security program plan is periodically reviewed and updated on the organization-defined "
                "annual schedule and when organizational requirements or program changes require revision."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The current approved plan release is disseminated to the organization-defined audience of executive "
                "management, the senior agency information security officer, System Owner, ISSO, privacy "
                "stakeholders, engineering leadership, procurement, legal, and operations teams, and the release log "
                "retains the distribution date, version, and acknowledgement status."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The information security program plan is protected from unauthorized modification through access "
                "controls, version control, digital signatures, and read-only storage of approved plan releases."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Controls to prevent unauthorized modification of the information security program plan include access "
                "controls, version control, approval workflow requirements, digital signatures, and read-only storage "
                "of approved plan releases."
            ),
        },
        {
            "type": "table",
            "headers": ["Maintenance or Protection Control", "Recorded Evidence"],
            "rows": [
                ["Periodic review and update schedule", "Annual review schedule PM1-REV-2026 and update record PM1-UPD-2026-04"],
                ["Access controls", "Restricted edit permissions for plan maintainers PM1-PROT-ACCESS-01"],
                ["Version control", "Version-controlled repository and reviewer approval record PM1-PROT-VC-01"],
                ["Digital signatures", "Digitally signed approved release PM1-SIGN-2026-04"],
                ["Read-only storage", "Read-only released-copy retention record PM1-RO-STORE-01"],
                ["Defined audience dissemination", "Release log and acknowledgement records PM1-DIST-EXEC-2026-04 through PM1-DIST-STAKE-2026-04"],
            ],
        },
    ]


def _pm_privacy_program_plan_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PM-18 Privacy Program Overview"},
        {
            "type": "paragraph",
            "text": (
                f"The organization-wide privacy program plan for {context.system_name} identifies the Senior Agency "
                "Official for Privacy, assigns the roles and responsibilities of other privacy officials and staff, "
                "documents strategic goals and objectives, reflects coordination among privacy-related organizational "
                "entities, and records dissemination, review, and update actions."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan is disseminated to relevant personnel and stakeholders, reviewed and updated "
                "on the organization-defined annual schedule, updated when federal privacy laws and policies change, "
                "and updated when implementation issues or privacy control assessments identify corrective actions."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan is distributed to and made available for relevant personnel, stakeholders, "
                "and the organization through the privacy governance site, internal plan library, and stakeholder "
                "distribution list."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan is distributed and made available to the intended audience, including privacy "
                "officials, legal counsel, records personnel, mission owners, security staff, and other relevant "
                "stakeholders."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan has been distributed to the appropriate personnel and stakeholders and made "
                "available to the organization's personnel through the privacy governance portal and distribution list."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan has been updated to address changes in federal privacy laws and policies "
                "and has been updated to address problems identified during plan implementation or privacy control "
                "assessments."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan includes a documented description of the strategic goals and objectives of "
                "the privacy program and has been distributed to required personnel and stakeholders."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan has been disseminated to relevant personnel and stakeholders, including "
                "privacy officials, legal counsel, records personnel, mission owners, security staff, and personnel "
                "responsible for monitoring privacy program compliance."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan contains a description of the strategic goals and objectives of the privacy "
                "program, and the privacy program plan is disseminated to relevant personnel, posted to the privacy "
                "governance portal, and otherwise made available to organizational personnel and stakeholders who have "
                "privacy governance, legal, records, mission, security, or oversight responsibilities."
            ),
        },
        {"type": "heading", "level": 1, "text": "PM-18 Privacy Program Plan Requirements"},
        {
            "type": "paragraph",
            "text": (
                "This privacy program plan contains the documented strategic goals and objectives of the privacy "
                "program required for PM-18 and records dissemination of the privacy program plan to relevant "
                "personnel and stakeholders."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan includes a description of the program's strategic goals and objectives."
            ),
        },
        {"type": "heading", "level": 1, "text": "Strategic Goals and Objectives of the Privacy Program"},
        {
            "type": "paragraph",
            "text": (
                "This section contains a documented description of the strategic goals and objectives of the privacy "
                "program. The privacy program plan describes the strategic goals and objectives of the privacy program, "
                "including reduction of privacy risk, timely response to individual requests, ongoing oversight of PII "
                "processing, and coordinated privacy governance across the organization."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan includes a description of the strategic goals and objectives of the privacy "
                "program, including privacy risk reduction, individual participation support, oversight of personally "
                "identifiable information processing, and organization-wide privacy governance."
            ),
        },
        {
            "type": "table",
            "headers": ["Strategic Goal or Objective of the Privacy Program", "Recorded Description"],
            "rows": [
                ["Reduce privacy risk", "Use governance, assessments, and corrective action tracking to reduce privacy risk"],
                ["Support individual participation", "Provide timely responses to privacy requests, complaints, and correction requests"],
                ["Oversee PII processing", "Maintain ongoing oversight of collection, use, retention, disclosure, and disposal of PII"],
                ["Sustain privacy governance", "Coordinate privacy roles, reporting, and program improvements across the organization"],
            ],
        },
        {
            "type": "table",
            "headers": ["Privacy Program Strategic Goal", "Recorded Description"],
            "rows": [
                ["Reduce privacy risk", "Lower privacy risk through governance, assessment, and corrective action tracking"],
                ["Respond to individual requests", "Provide timely and consistent handling of privacy inquiries and requests"],
                ["Sustain oversight of PII processing", "Maintain ongoing visibility into collection, retention, use, and disclosure of PII"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Dissemination and Availability"},
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan is disseminated to required stakeholders and made available to appropriate "
                "personnel. Required stakeholders include privacy officials, legal counsel, records personnel, mission "
                "owners, security staff, and other organizational personnel with privacy governance responsibilities."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan is disseminated to the appropriate personnel or stakeholders, including "
                "privacy officials, legal counsel, records personnel, mission owners, security staff, and other "
                "organizational personnel with privacy governance or oversight responsibilities."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan is posted to the privacy governance portal, distributed through the privacy "
                "distribution list, and otherwise made available to appropriate personnel through the internal plan "
                "library."
            ),
        },
        {
            "type": "table",
            "headers": ["Privacy Program Plan Item", "Recorded Evidence"],
            "rows": [
                ["Senior Agency Official for Privacy role and responsibilities", "Privacy program plan section 2.1"],
                ["Other privacy officials and staff roles", "Privacy program plan section 2.2"],
                ["Strategic goals and objectives", "Privacy program plan section 3.1"],
                ["Coordination among privacy, legal, records, security, and mission entities", "Privacy governance coordination section 4.2"],
                ["Dissemination to stakeholders", "Stakeholder distribution record PM18-DIST-04 and portal publication PM18-PUB-01"],
                ["Annual review and update cadence", "Annual review package PM18-REV-2026"],
                ["Assessment-driven update", "Plan revision log entry PM18-REV-2026-04"],
            ],
        },
        {
            "type": "table",
            "headers": ["Plan Dissemination and Availability Activity", "Recorded Evidence"],
            "rows": [
                [
                    "Privacy program plan disseminated to relevant personnel",
                    "Stakeholder distribution record PM18-DIST-04 sent to privacy officials, legal counsel, records "
                    "manager, mission owners, security staff, and governance leads",
                ],
                [
                    "Privacy program plan disseminated to the appropriate personnel or stakeholders",
                    "Distribution confirmation PM18-DIST-05 listing privacy officials, legal counsel, records "
                    "personnel, mission owners, security staff, and governance stakeholders",
                ],
                [
                    "Privacy program plan posted to the privacy governance portal",
                    "Portal publication PM18-PUB-01 with controlled internal access for organizational personnel",
                ],
                [
                    "Privacy program plan otherwise made available to personnel and stakeholders",
                    "Privacy governance site notice and plan library index PM18-LIB-01",
                ],
                [
                    "Privacy program plan distributed to and made available for relevant personnel, stakeholders, and the organization",
                    "Distribution log PM18-DIST-ORG-2026 and privacy governance site publication PM18-ORG-2026",
                ],
            ],
        },
        {"type": "heading", "level": 1, "text": "Review and Update Trigger Record"},
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan is reviewed and updated on the organization-defined annual schedule and is "
                "updated to address changes in federal privacy laws and policies, implementation issues, and privacy "
                "control assessment findings."
            ),
        },
        {
            "type": "table",
            "headers": ["Update Trigger", "Recorded Evidence"],
            "rows": [
                [
                    "Annual scheduled review and update",
                    "Annual review package PM18-REV-2026 completed on 2026-04-05 with approved version 5.2",
                ],
                [
                    "Change in federal privacy laws and policies",
                    "Plan revision log PM18-LAW-2026-02 updating the privacy program plan after revised federal privacy policy guidance issued 2026-02-14",
                ],
                [
                    "Implementation issue requiring corrective action",
                    "Plan revision log PM18-REV-2026-03 documenting oversight workflow updates after implementation issue review",
                ],
                [
                    "Privacy control assessment finding",
                    "Plan revision log PM18-REV-2026-04 documenting corrective action assignments after privacy control assessment results",
                ],
            ],
        },
        {"type": "heading", "level": 1, "text": "Privacy Governance Bodies"},
        {
            "type": "paragraph",
            "text": (
                "A Data Governance Body is established with chartered membership and responsibilities, and a Data "
                "Integrity Board is established to review matching-program proposals and conduct annual reviews of all "
                "matching programs in which the agency participates."
            ),
        },
        {
            "type": "table",
            "headers": ["Governance Body", "Recorded Evidence"],
            "rows": [
                ["Data Governance Body", "Charter PM23-CHARTER-01 and meeting minutes PM23-MTG-02"],
                ["Data Integrity Board", "Review record PM24-REV-01 and annual report PM24-ANNUAL-2026"],
            ],
        },
    ]


def _pm_privacy_program_distribution_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Privacy Program Plan Distribution and Public Availability Record"},
        {
            "type": "paragraph",
            "text": (
                "This record documents that the privacy program plan is disseminated to required stakeholders and "
                "made publicly available as required."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan includes the strategic goals and objectives of the privacy program and is "
                "disseminated to appropriate personnel and stakeholders."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan has been disseminated to relevant personnel and stakeholders and made "
                "available through the privacy governance site and public privacy resources page."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Distribution records, communication logs, and acknowledgement receipts are retained to demonstrate "
                "that the privacy program plan has been disseminated to the required stakeholders."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan is disseminated to required stakeholders, including privacy officials, "
                "legal counsel, records personnel, mission owners, security staff, and personnel responsible for "
                "monitoring privacy program compliance."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan is made publicly available as required through the agency privacy "
                "governance site and public privacy resources page."
            ),
        },
        {
            "type": "table",
            "headers": ["Distribution or Availability Activity", "Recorded Evidence"],
            "rows": [
                ["Dissemination to relevant personnel and stakeholders", "Distribution record PM18-DIST-06 sent to privacy officials, legal counsel, records personnel, mission owners, security staff, and compliance monitors"],
                ["Public availability as required", "Privacy governance site publication PM18-PUBLIC-01 and public privacy resources page index PM18-PUBLIC-02"],
                ["Strategic goals and objectives included in disseminated plan", "Disseminated privacy program plan version 5.2 includes strategic goals and objectives section 3.1"],
                ["Acknowledgement receipts retained", "Stakeholder acknowledgement log PM18-ACK-2026-01 through PM18-ACK-2026-06"],
            ],
        },
    ]


def _pm_data_integrity_board_review_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Data Integrity Board Matching Program Proposal Review Record"},
        {
            "type": "paragraph",
            "text": (
                "The Data Integrity Board reviews proposals to conduct or participate in a matching program before "
                "the organization conducts or participates in the matching program."
            ),
        },
        {
            "type": "table",
            "headers": ["Data Integrity Board Proposal Review Activity", "Recorded Evidence"],
            "rows": [
                [
                    "Review of proposal to conduct a matching program",
                    "Data Integrity Board proposal review record PM24-PROP-2026-01 with board decision and approval conditions",
                ],
                [
                    "Review of proposal to participate in a matching program",
                    "Data Integrity Board proposal review record PM24-PROP-2026-02 with board concurrence and participation authorization",
                ],
            ],
        },
    ]


def _pm_required_audience_dissemination_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Privacy Program Plan Required Audience Dissemination Record"},
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan has been disseminated to the required audience and stakeholders, including "
                "relevant personnel, privacy officials, legal counsel, records personnel, mission owners, security "
                "staff, and personnel responsible for monitoring privacy program compliance."
            ),
        },
        {
            "type": "table",
            "headers": ["Required Audience or Stakeholder", "Distribution Evidence"],
            "rows": [
                ["Privacy officials", "Distribution record PM18-AUD-2026-01 and acknowledgement receipt PM18-ACK-2026-01"],
                ["Legal counsel", "Distribution record PM18-AUD-2026-02 and acknowledgement receipt PM18-ACK-2026-02"],
                ["Records personnel", "Distribution record PM18-AUD-2026-03 and acknowledgement receipt PM18-ACK-2026-03"],
                ["Mission owners", "Distribution record PM18-AUD-2026-04 and acknowledgement receipt PM18-ACK-2026-04"],
                ["Security staff", "Distribution record PM18-AUD-2026-05 and acknowledgement receipt PM18-ACK-2026-05"],
                ["Privacy compliance monitoring personnel", "Distribution record PM18-AUD-2026-06 and acknowledgement receipt PM18-ACK-2026-06"],
            ],
        },
    ]


def _pm18_control_evidence_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PM-18 Privacy Program Plan Strategic Goals, Dissemination, and Update Record"},
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan contains a description of the strategic goals and objectives of the "
                "privacy program."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan is distributed to and made available for relevant personnel, stakeholders, "
                "and the organization."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The privacy program plan has been updated to address changes in federal privacy laws and policies "
                "and has been updated to address problems identified during plan implementation or privacy control "
                "assessments."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Excerpt from privacy program plan section 3.1: the strategic goals and objectives of the privacy "
                "program are to reduce privacy risk, support individual participation, sustain oversight of "
                "personally identifiable information processing, and coordinate privacy governance across the "
                "organization."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Excerpt from privacy program plan dissemination section 4.1: the privacy program plan is "
                "distributed to privacy officials, legal counsel, records personnel, mission owners, security staff, "
                "and personnel responsible for monitoring privacy program compliance and is made available through the "
                "privacy governance portal and plan library."
            ),
        },
        {
            "type": "table",
            "headers": ["PM-18 Evidence Element", "Recorded Evidence"],
            "rows": [
                ["Strategic goals and objectives in privacy program plan", "Privacy program plan section 3.1 describes privacy risk reduction, individual participation support, PII oversight, and privacy governance"],
                ["Distribution to relevant personnel and stakeholders", "Distribution log PM18-DIST-ORG-2026 and required audience records PM18-AUD-2026-01 through PM18-AUD-2026-06"],
                ["Availability to the organization", "Privacy governance site publication PM18-ORG-2026 and internal plan library listing PM18-LIB-01"],
                ["Update for federal privacy law and policy changes", "Plan revision log PM18-LAW-2026-02"],
                ["Update for implementation or assessment problems", "Plan revision logs PM18-REV-2026-03 and PM18-REV-2026-04"],
            ],
        },
    ]


def _pm_enterprise_architecture_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Enterprise Architecture Security Integration Record"},
        {
            "type": "paragraph",
            "text": (
                f"The maintained enterprise architecture for {context.system_name} includes concrete architecture "
                "artifacts, security integration analyses, and ongoing maintenance records demonstrating that "
                "information security considerations are integrated into the enterprise architecture."
            ),
        },
        {
            "type": "table",
            "headers": ["Enterprise Architecture Artifact", "Recorded Security Consideration"],
            "rows": [
                ["Reference architecture diagram EA-SEC-2026-01", "Shows trust boundaries, shared identity services, logging path, and protected data stores"],
                ["Security integration analysis EA-SEC-AN-2026-02", "Maps security services and common controls into the enterprise architecture"],
                ["Architecture maintenance review EA-SEC-REV-2026-03", "Records ongoing maintenance updates and security-impact analysis for architecture changes"],
            ],
        },
    ]


def _pm_supply_chain_poam_reporting_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Supply Chain Risk Management POA&M Reporting Procedure"},
        {
            "type": "paragraph",
            "text": (
                "A defined process exists for reporting plans of action and milestones for the supply chain risk "
                "management program in accordance with established reporting requirements."
            ),
        },
        {
            "type": "table",
            "headers": ["Supply Chain Risk Management POA&M Reporting Step", "Recorded Evidence"],
            "rows": [
                ["Capture supply chain remedial action", "Supply chain POA&M intake record PM4-SCRM-STEP-01"],
                ["Assign owner and milestone", "Supply chain POA&M assignment record PM4-SCRM-STEP-02"],
                ["Prepare report according to reporting requirements", "Supply chain POA&M reporting procedure PM4-SCRM-STEP-03"],
                ["Submit report to required governance recipients", "Submitted supply chain POA&M report PM4-SCRM-STEP-04"],
            ],
        },
    ]


def _pm_pii_quality_management_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PII Quality Management and Appeals Procedure"},
        {
            "type": "paragraph",
            "text": (
                "Policy and procedures require reviewing the accuracy, relevance, timeliness, and completeness of "
                "personally identifiable information across the information life cycle."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Procedures require correction or deletion of inaccurate or outdated personally identifiable "
                "information, notification where appropriate, and appeals of adverse decisions on correction or "
                "deletion requests."
            ),
        },
        {
            "type": "table",
            "headers": ["PII Quality or Appeals Requirement", "Recorded Procedure Evidence"],
            "rows": [
                ["Review relevance of PII across the information life cycle", "PII quality review procedure PM22-REL-2026"],
                ["Review timeliness of PII across the information life cycle", "PII timeliness review procedure PM22-TIME-2026"],
                ["Review completeness of PII across the information life cycle", "PII completeness review procedure PM22-COMP-2026"],
                ["Appeals of adverse correction or deletion decisions", "Appeals handling procedure PM22-APPEAL-2026"],
            ],
        },
    ]


def _pm_privacy_report_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Privacy Report Dissemination and Review Record"},
        {
            "type": "paragraph",
            "text": (
                "Privacy reports are disseminated to defined recipients to demonstrate accountability with statutory, "
                "regulatory, and policy privacy mandates."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The defined recipients for privacy reports include the Senior Agency Official for Privacy, legal "
                "counsel, records management leadership, mission owners, executive management, and personnel "
                "responsible for monitoring privacy program compliance."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Privacy reports are reviewed and updated on the organization-defined annual schedule and whenever "
                "reporting requirements change."
            ),
        },
        {
            "type": "table",
            "headers": ["Privacy Reporting Activity", "Recorded Evidence"],
            "rows": [
                ["Dissemination of privacy report to defined recipients", "Privacy report distribution record PM27-DIST-2026 issued to SAOP, legal counsel, records leadership, mission owners, executive management, and compliance monitors"],
                ["Identification of specific organizational recipients", "Recipient roster PM27-RECIP-2026 naming the organizational recipients for privacy reports"],
                ["Dissemination to compliance monitoring personnel", "Distribution copy PM27-COMP-2026 sent to privacy program compliance monitoring staff"],
                ["Review and update on organization-defined annual schedule", "Annual privacy report review package PM27-REV-2026 completed on 2026-04-08 with updated version approval"],
            ],
        },
    ]


def _pm27_control_evidence_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PM-27 Privacy Report Dissemination and Review Control Record"},
        {
            "type": "paragraph",
            "text": (
                "Privacy reports are disseminated to the organization-defined audience and to organization-defined "
                "recipients to demonstrate accountability with statutory, regulatory, and policy privacy mandates."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Privacy reports are reviewed and updated on the organization-defined annual schedule."
            ),
        },
        {
            "type": "table",
            "headers": ["PM-27 Evidence Element", "Recorded Evidence"],
            "rows": [
                ["Dissemination to organization-defined audience", "Privacy report distribution record PM27-DIST-2026 issued to the organization-defined audience"],
                ["Dissemination to organization-defined recipients", "Recipient roster PM27-RECIP-2026 listing the organization-defined recipients for privacy reports"],
                ["Review and update on organization-defined schedule", "Annual privacy report review package PM27-REV-2026 completed on 2026-04-08"],
            ],
        },
    ]


def _pm_public_privacy_contact_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PM-20 Central Privacy Resource Webpage"},
        {
            "type": "paragraph",
            "text": (
                "The organization's principal public website at https://agency.example maintains a central privacy "
                "resource webpage at https://agency.example/privacy that provides a mechanism for contacting the "
                "Senior Agency Official for Privacy and the privacy office."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The PM-20 public privacy resource webpage is publicly accessible without authentication, is linked "
                "from the principal public website, and was verified on 2026-05-04 from an unauthenticated browser "
                "session."
            ),
        },
        {"type": "heading", "level": 1, "text": "How the Public Communicates with the Senior Agency Official Responsible for Privacy"},
        {
            "type": "paragraph",
            "text": (
                "Members of the public may communicate with the senior agency official responsible for privacy by "
                "using the published senior agency official for privacy email address, direct phone number, or web "
                "contact form listed on the public-facing privacy webpage."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The public-facing privacy webpage provides a mechanism for the public to communicate with the senior "
                "agency official responsible for privacy directly through email, telephone, and a web contact form."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The public-facing webpage specifically lists direct contact information for the Senior Agency "
                "Official for Privacy so members of the public can communicate directly with that official."
            ),
        },
        {
            "type": "table",
            "headers": ["PM-20 Public Webpage Attribute", "Recorded Publicly Available Evidence"],
            "rows": [
                ["Principal public website", "https://agency.example"],
                ["Central privacy resource webpage URL", "https://agency.example/privacy"],
                ["Public access verification", "Unauthenticated browser verification completed on 2026-05-04 with page available on the public website"],
                ["Published Senior Agency Official for Privacy email", "saop@agency.example"],
                ["Published Senior Agency Official for Privacy phone", "202-555-0146"],
                ["Published privacy office support email", "privacy.office@agency.example"],
                ["Published web contact form", "https://agency.example/privacy/contact"],
                ["Public webpage content", "Privacy office contact details, privacy resources, and instructions for contacting the Senior Agency Official for Privacy"],
            ],
        },
        {
            "type": "table",
            "headers": ["Public Webpage Contact Mechanism for the Senior Agency Official Responsible for Privacy", "Publicly Available Detail"],
            "rows": [
                ["Direct SAOP email", "saop@agency.example"],
                ["Direct SAOP phone", "202-555-0146"],
                ["Privacy office support email", "privacy.office@agency.example"],
                ["Web form", "https://agency.example/privacy/contact"],
            ],
        },
    ]


def _pm20_webpage_verification_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PM-20 Central Privacy Resource Webpage Verification Record"},
        {
            "type": "paragraph",
            "text": (
                "This record documents that a central resource webpage is maintained on the organization's principal "
                "public website and provides the public with a mechanism to communicate with the Senior Agency "
                "Official for Privacy."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Verification performed on 2026-05-04 confirmed that the principal public website "
                "https://agency.example links to the public privacy resource page https://agency.example/privacy and "
                "that the page is publicly accessible without authentication."
            ),
        },
        {
            "type": "table",
            "headers": ["PM-20 Verification Element", "Recorded Evidence"],
            "rows": [
                ["Principal public website URL", "https://agency.example"],
                ["Central privacy resource webpage URL", "https://agency.example/privacy"],
                ["Public access verification", "Unauthenticated browser check on 2026-05-04 confirmed page availability and public access"],
                ["Published contact email", "privacy.office@agency.example"],
                ["Published contact phone", "202-555-0188"],
                ["Published web contact form", "https://agency.example/privacy/contact"],
                ["Recorded page content", "Privacy office contact details, privacy resources, and public instructions for contacting the Senior Agency Official for Privacy"],
            ],
        },
    ]


def _pm_supply_chain_strategy_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Supply Chain Strategy Review and POA&M Reporting"},
        {
            "type": "paragraph",
            "text": (
                "The supply chain risk management strategy is reviewed and updated to address organizational changes, "
                "and supply chain risk management POA&Ms are reported in accordance with established reporting "
                "requirements."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The supply chain risk management program uses a defined POA&M process to record supply chain "
                "remedial actions, assign owners, track milestone dates, monitor completion status, and report supply "
                "chain POA&Ms according to established reporting requirements."
            ),
        },
        {
            "type": "table",
            "headers": ["Supply Chain Governance Item", "Recorded Evidence"],
            "rows": [
                ["Annual strategy review and update for organizational changes", "Supply chain strategy review record PM30-REV-2026"],
                ["Supply chain POA&M process for remedial actions", "Supply chain POA&M register PM4-SCRM-TRACK-2026 with remedial action owners, milestones, and status"],
                ["Supply chain POA&M reporting process", "Monthly supply chain POA&M report PM4-SCRM-2026-04 submitted according to established reporting requirements"],
            ],
        },
    ]


def _pm_risk_framing_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Risk Framing Communication Record"},
        {
            "type": "paragraph",
            "text": (
                "The results of risk framing activities, including documented assumptions, constraints, tradeoffs, and "
                "risk tolerance decisions, are communicated and distributed to the organization-defined recipients."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Documented assumptions affecting risk assessments and risk responses include mission dependency "
                "assumptions, external-service availability assumptions, shared-control inheritance assumptions, and "
                "organizational tolerance assumptions retained in the risk framing package."
            ),
        },
        {
            "type": "table",
            "headers": ["Risk Framing Result", "Recipient Group", "Recorded Evidence"],
            "rows": [
                ["Assumptions, constraints, and risk tolerance summary", "Executive management, system owners, and security governance stakeholders", "Risk framing communication record PM28-COMMS-2026-04"],
                ["Results distributed to organization-defined recipients", "Distribution record PM28-DIST-2026-04 sent to executive management, system owners, ISSO, and privacy governance stakeholders"],
            ],
        },
    ]


def _cp_contingency_plan_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Contingency Plan Overview"},
        {
            "type": "paragraph",
            "text": (
                f"This contingency plan for {context.system_name} identifies essential mission and business functions, "
                "recovery objectives, restoration priorities, contingency roles and responsibilities, assigned "
                "individuals with contact information, and the actions required to maintain essential operations "
                "during a system disruption, compromise, or failure."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Specific contingency roles and responsibilities are assigned for plan activation, incident "
                "coordination, communications, platform recovery, backup restoration, facilities coordination, and "
                "executive decision support, and those assignments are retained in the approved contingency plan."
            ),
        },
        {
            "type": "table",
            "headers": ["Contingency Role", "Assigned Individual and Contact Information", "Recorded Responsibility"],
            "rows": [
                ["Contingency planning lead", "Jordan Ellis, jordan.ellis@agency.example, 202-555-0141", "Coordinates plan maintenance and plan activation decisions"],
                ["Platform recovery lead", "Riley Chen, riley.chen@agency.example, 202-555-0142", "Leads system restoration and recovery sequencing"],
                ["Incident response coordination lead", "Morgan Patel, morgan.patel@agency.example, 202-555-0143", "Coordinates with incident handling activities and escalation"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Sharing and Distribution of Contingency Information"},
        {
            "type": "paragraph",
            "text": (
                "The contingency plan addresses the sharing of contingency information with internal and external "
                "stakeholders, including executive management, the System Owner, ISSO, incident response lead, "
                "platform operations, facilities support, and approved service providers."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Copies of the contingency plan are distributed to the organization-defined recipients through the "
                "controlled contingency-plan distribution workflow, and delivery confirmations are retained with the "
                "plan package."
            ),
        },
        {
            "type": "table",
            "headers": ["Contingency Plan Distribution Recipient", "Recorded Evidence"],
            "rows": [
                ["System Owner and ISSO", "Contingency plan distribution record CP2-DIST-2026-04"],
                ["Incident response lead and platform operations lead", "Contingency plan distribution record CP2-DIST-2026-05"],
                ["Approved service providers and facilities support", "Contingency plan distribution record CP2-DIST-2026-06"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Coordination with Incident Handling"},
        {
            "type": "paragraph",
            "text": (
                "Contingency planning activities are coordinated with incident handling activities through a joint "
                "response annex, common escalation contacts, shared decision criteria, and retained joint exercise and "
                "after-action records."
            ),
        },
        {
            "type": "table",
            "headers": ["Coordination Activity", "Recorded Evidence"],
            "rows": [
                ["Joint contingency and incident response annex", "Coordination annex CP2-IR-COORD-2026-04"],
                ["Shared exercise and after-action review", "Joint exercise report CP2-IR-EX-2026-01"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Review, Update, and Change Communication"},
        {
            "type": "paragraph",
            "text": (
                "The contingency plan is reviewed on the organization-defined annual schedule and updated to address "
                "changes to the organization, system, or environment of operation and problems encountered during "
                "implementation, execution, or testing."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Problems identified during implementation, execution, or testing of the contingency plan are entered "
                "into the issue-driven revision workflow, used to update the approved plan text, and verified during "
                "the follow-up review before the updated plan is redistributed."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Changes to the contingency plan are communicated to the organization-defined recipients through the "
                "contingency-plan change workflow, and acknowledgement receipts are retained."
            ),
        },
        {
            "type": "table",
            "headers": ["Review, Update, or Communication Activity", "Recorded Evidence"],
            "rows": [
                ["Annual review on organization-defined schedule", "Review schedule and signed review package CP2-REV-SCHED-2026"],
                ["Update for environmental or system change", "Contingency plan revision record CP2-UPD-2026-02"],
                ["Update for implementation, execution, or testing problem", "Issue-driven contingency plan revision CP2-UPD-2026-03 documenting the exercise finding, required text changes, approval, and redistributed release"],
                ["Communication of contingency plan changes", "Change notice and acknowledgement log CP2-CHG-2026-04"],
            ],
        },
        {"type": "heading", "level": 1, "text": "Lessons Learned and Plan Protection"},
        {
            "type": "paragraph",
            "text": (
                "Lessons learned from contingency plan testing, training, or actual contingency activities are "
                "incorporated into subsequent contingency testing and training through the contingency improvement log."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Lessons learned from contingency plan training and actual contingency activities are incorporated "
                "into subsequent contingency testing and training records."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The contingency plan is protected from unauthorized disclosure and unauthorized modification through "
                "restricted repository permissions, version control, approver signoff, and controlled release of "
                "approved plan copies."
            ),
        },
        {
            "type": "table",
            "headers": ["Protection or Improvement Control", "Recorded Evidence"],
            "rows": [
                ["Lessons learned incorporated into later testing and training", "Contingency improvement log CP2-LL-2026-04"],
                ["Restricted access and controlled release", "Contingency plan protection record CP2-PROT-2026-01"],
                ["Version-controlled change workflow and approver signoff", "Contingency plan modification control record CP2-PROT-2026-02"],
                ["Alternate processing site control equivalency", "Alternate site equivalency matrix CP7-EQ-2026-01"],
            ],
        },
    ]


def _cp_contingency_plan_governance_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Contingency Plan Governance and Distribution Record"},
        {
            "type": "paragraph",
            "text": (
                "This record captures explicit approval, distribution, coordination, review, update, change "
                "communication, and protection evidence for the contingency plan."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Contingency planning activities are explicitly coordinated with incident handling activities through "
                "a joint notification tree, shared activation thresholds, integrated after-action reviews, and a "
                "retained coordination record tying contingency-plan execution to incident-response escalation and "
                "recovery decision points."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The contingency plan is reviewed according to the organization-defined annual review schedule and is "
                "also reviewed after major exercises, actual contingency activations, significant changes to the "
                "system or environment of operation, and problems identified during implementation, execution, or "
                "testing."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Approved plan updates explicitly address organizational changes, system changes, environmental "
                "changes, and problems encountered during implementation, execution, or testing, and every approved "
                "revision is redistributed to the organization-defined recipients with retained acknowledgement "
                "evidence."
            ),
        },
        {
            "type": "table",
            "headers": ["CP-2 Governance Requirement", "Recorded Explicit Evidence"],
            "rows": [
                ["Plan addresses sharing of contingency information", "Contingency plan section CP2-INFO-SHARE and communications annex CP2-COMM-01"],
                ["Copies distributed to organization-defined recipients", "Distribution packages CP2-DIST-2026-04 through CP2-DIST-2026-06 with delivery confirmations"],
                ["Specific contingency roles and responsibilities documented in the plan", "Approved contingency plan roles table CP2-ROLE-2026-01 naming activation, communications, incident coordination, recovery, and facilities responsibilities"],
                ["Coordination with incident handling activities", "Joint coordination record CP2-IR-COORD-2026-04"],
                ["Annual review on organization-defined schedule", "Review package CP2-REV-SCHED-2026 signed by System Owner and ISSO"],
                ["Update for changes or testing problems", "Revision logs CP2-UPD-2026-02 and CP2-UPD-2026-03 showing issue-driven updates after implementation, execution, and testing findings"],
                ["Changes communicated to organization-defined recipients", "Change communication record CP2-CHG-2026-04"],
                ["Lessons learned incorporated into testing and training", "Contingency improvement log CP2-LL-2026-04"],
                ["Protection from unauthorized modification", "Modification-control record CP2-PROT-2026-02 with restricted write access, version control, and approver signoff"],
            ],
        },
        {
            "type": "table",
            "headers": ["Review or Update Trigger", "Recorded Explicit Evidence"],
            "rows": [
                ["Organization-defined annual review schedule", "Signed annual review package CP2-REV-SCHED-2026 completed on 2026-04-09"],
                ["System or environmental change", "Approved contingency plan revision CP2-UPD-2026-02 addressing architecture and hosting changes"],
                ["Problem encountered during testing or execution", "Issue-driven revision CP2-UPD-2026-03 opened from exercise finding and closed after plan update"],
                ["Coordination with incident handling activities", "Joint contingency and incident response coordination package CP2-IR-COORD-2026-04"],
                ["Redistribution of approved changes", "Change notice and recipient acknowledgement log CP2-CHG-2026-04"],
            ],
        },
    ]


def _ac2_account_management_record_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "AC-2 Account Management Procedure and Monitoring Record"},
        {
            "type": "paragraph",
            "text": (
                "This record documents account creation, enabling, modification, disabling, removal, notification "
                "timeframes, shared-account authenticator changes, continuous monitoring, and alignment with "
                "personnel transfer and termination procedures."
            ),
        },
        {
            "type": "table",
            "headers": ["AC-2 Process Requirement", "Recorded Explicit Evidence"],
            "rows": [
                ["Accounts are disabled within four business hours when termination or urgent removal criteria are met", "Account disabling procedure AC2-DIS-2026-01 and termination workflow AC2-TERM-2026-018"],
                ["Accounts are removed within one business day after disabling and final approval", "Account removal procedure AC2-REM-2026-01 and IAM closure record AC2-REM-2026-041"],
                ["Account managers and defined parties are notified within four business hours for no-longer-required, terminated, transferred, or need-to-know changes", "Notification workflow AC2-NOTIFY-2026 and notices AC2-TERM-2026-018, AC2-TRANS-2026-009, AC2-NTK-2026-014"],
                ["Use of accounts is monitored through logs, alerts, and monthly review", "SIEM alert package AC2-MON-2026-04 and monthly account review AC2-REV-2026-04"],
                ["Shared or group account authenticators are changed when individuals are removed from the group", "Shared account authenticator reset record AC2-SHARED-2026-006"],
                ["Account management is aligned with personnel termination and transfer procedures", "Integrated HR/IAM deprovisioning workflow AC2-HR-ALIGN-2026-01"],
            ],
        },
    ]


def _ca2_assessment_plan_approval_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "CA-2 Control Assessment Plan Approval Record"},
        {
            "type": "paragraph",
            "text": (
                "This record documents that the control assessment plan was reviewed and approved by the "
                "Authorizing Official or designated representative prior to conducting the assessment."
            ),
        },
        {
            "type": "table",
            "headers": ["CA-2 Assessment Plan Governance Requirement", "Recorded Explicit Evidence"],
            "rows": [
                ["Control assessment plan developed with scope, procedures, environment, team, and roles", "Assessment plan CA2-PLAN-2026-04 sections 1 through 5"],
                ["Assessment plan reviewed before assessment", "Reviewer signoff record CA2-REVIEW-2026-04 dated 2026-04-08"],
                ["Assessment plan approved by Authorizing Official or designated representative prior to assessment", "Approval memo CA2-APPROVAL-2026-04 signed on 2026-04-09 before assessment start on 2026-04-12"],
            ],
        },
    ]


def _ca7_monitoring_correlation_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "CA-7 Continuous Monitoring Correlation and Analysis Record"},
        {
            "type": "paragraph",
            "text": (
                "This record documents that the system-level continuous monitoring program explicitly correlates and "
                "analyzes information generated by control assessments with information generated by ongoing "
                "monitoring activities before response actions are assigned, escalated, and tracked."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Control assessment findings, automated security monitoring results, configuration-drift alerts, "
                "vulnerability-scan trends, privacy monitoring observations, and incident-response observations are "
                "reviewed together in one system-level monitoring workflow to determine whether multiple evidence "
                "sources point to the same control weakness, recurring condition, or elevated risk."
            ),
        },
        {
            "type": "table",
            "headers": ["Correlated Evidence Sources", "System-Level Analysis Performed", "Recorded Response Action"],
            "rows": [
                [
                    "CA-2 assessment finding on incomplete log review plus recurring SIEM delayed-ingest alerts",
                    "Monitoring analysts correlated the assessment result with ongoing telemetry to confirm a recurring weakness affecting centralized monitoring coverage",
                    "Corrective action ticket CA7-CORR-2026-04 opened, owner assigned, and milestone tracked in the monthly monitoring package",
                ],
                [
                    "Configuration baseline assessment variance plus continuous drift-monitoring alerts on the same workload set",
                    "System-level monitoring dashboard correlated the assessment variance with ongoing drift telemetry to identify a common root cause in deployment sequencing",
                    "Engineering remediation plan CA7-CORR-2026-05 approved and elevated for change-control follow-up",
                ],
                [
                    "Privacy control assessment observation plus recurring monitoring evidence gap for notice-delivery records",
                    "Privacy monitoring review correlated the assessment observation with ongoing reporting gaps to validate the issue and define compensating follow-up tasks",
                    "Privacy remediation action CA7-CORR-2026-06 recorded and tracked to closure in the privacy status package",
                ],
            ],
        },
        {
            "type": "table",
            "headers": ["Monthly Monitoring Review Element", "Recorded Evidence"],
            "rows": [
                ["Correlation of assessment findings with monitoring telemetry", "Continuous monitoring review package CA7-ANALYSIS-2026-04"],
                ["Analysis of recurring conditions and common root cause", "System-level monitoring dashboard extract CA7-DASH-2026-04"],
                ["Assigned response actions and due dates", "Response action tracker CA7-RESP-2026-04"],
                ["Privacy status reporting to defined recipients", "Privacy status distribution record CA7-PRIV-2026-04"],
            ],
        },
    ]


def _pm26_complaint_management_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "PM-26 Public Complaint Management Process"},
        {
            "type": "paragraph",
            "text": (
                "The complaint management process provides easy-to-use and publicly accessible mechanisms for "
                "individuals to submit complaints, concerns, or questions about organizational security and privacy "
                "practices through a public web form, direct email address, phone line, and mailing address."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The complaint process requires the complainant contact method, description of the concern, affected "
                "service or information, desired resolution, and any relevant dates or supporting details needed for "
                "successful filing."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Complaints are tracked to ensure review within five business days, addressed within thirty calendar "
                "days, acknowledged within two business days, and responded to through the complaint-response "
                "workflow."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The public complaint page at https://agency.example/privacy/complaints is publicly accessible and "
                "lists the required complaint fields, submission instructions, direct contact details, review "
                "timeframe, acknowledgement timeframe, and response timeframe."
            ),
        },
        {
            "type": "table",
            "headers": ["PM-26 Complaint Process Element", "Recorded Evidence"],
            "rows": [
                ["Public web form, direct email, phone line, and mailing address", "Public complaint channels PM26-PUBLIC-2026-01"],
                ["Required complaint submission information", "Complaint intake template PM26-INTAKE-2026-01"],
                ["Tracking and defined review/response timelines", "Complaint tracker PM26-TRACK-2026-04"],
                ["Acknowledgement of receipt within defined timeframe", "Complaint acknowledgement workflow PM26-ACK-2026-01"],
                ["Response to complaints, concerns, or questions", "Complaint response procedure PM26-RESP-2026-01"],
                ["Public complaint page with filing fields and instructions", "Public complaint webpage PM26-PUBLIC-2026-02"],
            ],
        },
    ]


def _sa5_documentation_response_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "SA-5 Documentation Acquisition and Response Record"},
        {
            "type": "paragraph",
            "text": (
                "This record documents attempts to obtain unavailable or nonexistent system documentation, the "
                "response actions taken when documentation cannot be obtained, and distribution of obtained or "
                "developed documentation to organization-defined recipients."
            ),
        },
        {
            "type": "table",
            "headers": ["SA-5 Documentation Requirement", "Recorded Explicit Evidence"],
            "rows": [
                ["Attempts to obtain unavailable or nonexistent documentation are documented", "Vendor request and follow-up log SA5-REQ-2026-01 and SA5-REQ-2026-02"],
                ["Defined response actions are taken when documentation is unavailable", "Response action record SA5-ACT-2026-01 showing acceptance hold, alternate evidence request, and procurement escalation"],
                ["Documentation distributed to organization-defined recipients", "Distribution package SA5-DIST-2026-01 sent to engineering leads, security reviewers, operations staff, and acceptance authority"],
            ],
        },
    ]


def _sa5_admin_privacy_documentation_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "SA-5 Administrator Security and Privacy Documentation Excerpts"},
        {
            "type": "paragraph",
            "text": (
                "Administrator documentation describes the effective use and maintenance of privacy functions and "
                "mechanisms and records known vulnerabilities regarding administrative or privileged functions."
            ),
        },
        {
            "type": "table",
            "headers": ["Administrator Documentation Requirement", "Recorded Documentation Evidence"],
            "rows": [
                ["Effective use of privacy functions and mechanisms", "Administrator guide SA5-ADMIN-PRIV-2026 section 4.1"],
                ["Effective maintenance of privacy functions and mechanisms", "Administrator guide SA5-ADMIN-PRIV-2026 section 4.2"],
                ["Known vulnerabilities regarding configuration of administrative or privileged functions", "Administrator vulnerability appendix SA5-ADMIN-VULN-2026 section 6.1"],
                ["Known vulnerabilities regarding use of administrative or privileged functions", "Administrator vulnerability appendix SA5-ADMIN-VULN-2026 section 6.2"],
            ],
        },
    ]


def _sa10_reporting_requirement_sections() -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "SA-10 Developer Findings Reporting Requirement Record"},
        {
            "type": "paragraph",
            "text": (
                "Developers are required to report findings to the organization-defined recipient, including the "
                "supplier assurance lead, ServiceNow security queue, ISSO, and acceptance authority."
            ),
        },
        {
            "type": "table",
            "headers": ["Organization-Defined Recipient for Developer Findings", "Recorded Requirement Evidence"],
            "rows": [
                ["Supplier assurance lead", "Developer reporting requirement SA10-REPORT-2026 section 2.1"],
                ["ServiceNow security queue", "Developer reporting requirement SA10-REPORT-2026 section 2.2"],
                ["ISSO and acceptance authority", "Developer reporting requirement SA10-REPORT-2026 section 2.3"],
            ],
        },
    ]


def _build_package_specs(context: HumanAuthoringContext, family_id: str) -> tuple[list[PackageDocumentSpec], list[str]]:
    policy_control, substantive_controls = _select_family_controls(family_id)
    family_title = policy_control.family_title
    system_stem = _safe_stem(context.system_name.replace(" ", "_")) or "SYSTEM"
    controls_addressed = [policy_control.display_id] + [ctrl.display_id for ctrl in substantive_controls]
    policy_slug = _safe_stem(family_title.replace(" ", "_"))
    base_policy = PackageDocumentSpec(
        key="policy",
        title=f"{context.system_name} {family_title} Policy and Procedure Standard",
        filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Policy_and_Procedure_Standard.docx",
        document_type="policy",
        document_intent="implements",
        controls_addressed=controls_addressed,
        sections=_policy_sections(context, family_id, policy_control),
    )

    if family_id == "AC":
        specs = [
            base_policy,
            PackageDocumentSpec(
                key="implementation",
                title=f"{context.system_name} {family_title} Technical Implementation Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Technical_Implementation_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=controls_addressed,
                sections=_implementation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="validation",
                title=f"{context.system_name} {family_title} Monthly Validation Review",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Monthly_Validation_Review.docx",
                document_type="technical_artifact",
                document_intent="verifies",
                controls_addressed=controls_addressed,
                sections=_validation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="ac2_account_management_record",
                title=f"{context.system_name} AC-2 Account Management Procedure and Monitoring Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_AC2_Account_Management_Procedure_and_Monitoring_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["AC-2"],
                sections=_ac2_account_management_record_sections(),
            ),
        ]
        return specs, controls_addressed

    if family_id == "CA":
        specs = [
            base_policy,
            PackageDocumentSpec(
                key="implementation",
                title=f"{context.system_name} {family_title} Technical Implementation Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Technical_Implementation_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=controls_addressed,
                sections=_implementation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="validation",
                title=f"{context.system_name} {family_title} Monthly Validation Review",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Monthly_Validation_Review.docx",
                document_type="technical_artifact",
                document_intent="verifies",
                controls_addressed=controls_addressed,
                sections=_validation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="ca2_assessment_plan_approval",
                title=f"{context.system_name} CA-2 Control Assessment Plan Approval Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_CA2_Control_Assessment_Plan_Approval_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["CA-2"],
                sections=_ca2_assessment_plan_approval_sections(),
            ),
            PackageDocumentSpec(
                key="ca7_monitoring_correlation_record",
                title=f"{context.system_name} CA-7 Continuous Monitoring Correlation and Analysis Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_CA7_Continuous_Monitoring_Correlation_and_Analysis_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["CA-7"],
                sections=_ca7_monitoring_correlation_sections(),
            ),
        ]
        return specs, controls_addressed

    if family_id == "CP":
        specs = [
            base_policy,
            PackageDocumentSpec(
                key="implementation",
                title=f"{context.system_name} {family_title} Technical Implementation Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Technical_Implementation_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=controls_addressed,
                sections=_implementation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="validation",
                title=f"{context.system_name} {family_title} Monthly Validation Review",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Monthly_Validation_Review.docx",
                document_type="technical_artifact",
                document_intent="verifies",
                controls_addressed=controls_addressed,
                sections=_validation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="contingency_plan",
                title=f"{context.system_name} Contingency Plan",
                filename=f"TEST_{family_id}PKG_{system_stem}_Contingency_Plan.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["CP-2", "CP-7"],
                sections=_cp_contingency_plan_sections(context),
            ),
            PackageDocumentSpec(
                key="contingency_plan_governance",
                title=f"{context.system_name} Contingency Plan Governance and Distribution Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_Contingency_Plan_Governance_and_Distribution_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["CP-2"],
                sections=_cp_contingency_plan_governance_sections(),
            ),
        ]
        return specs, controls_addressed

    if family_id == "PL":
        specs = [
            base_policy,
            PackageDocumentSpec(
                key="implementation",
                title=f"{context.system_name} {family_title} Technical Implementation Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Technical_Implementation_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=controls_addressed,
                sections=_implementation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="validation",
                title=f"{context.system_name} {family_title} Monthly Validation Review",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Monthly_Validation_Review.docx",
                document_type="technical_artifact",
                document_intent="verifies",
                controls_addressed=controls_addressed,
                sections=_validation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="pl1_policy_record",
                title=f"{context.system_name} PL-1 Planning Policy Compliance and Governance Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_PL1_Planning_Policy_Compliance_and_Governance_Record.docx",
                document_type="policy",
                document_intent="implements",
                controls_addressed=["PL-1"],
                sections=_pl1_policy_compliance_sections(),
            ),
            PackageDocumentSpec(
                key="system_security_plan",
                title=f"{context.system_name} PL-2 System Security Plan",
                filename=f"TEST_{family_id}PKG_{system_stem}_System_Security_Plan.docx",
                document_type="ssp_narrative",
                document_intent="implements",
                controls_addressed=["PL-2", "PL-8"],
                sections=_pl_system_security_plan_sections(context),
            ),
            PackageDocumentSpec(
                key="privacy_plan",
                title=f"{context.system_name} PL-2 Privacy Plan",
                filename=f"TEST_{family_id}PKG_{system_stem}_Privacy_Plan.docx",
                document_type="ssp_narrative",
                document_intent="implements",
                controls_addressed=["PL-2", "PL-8"],
                sections=_pl_privacy_plan_sections(context),
            ),
            PackageDocumentSpec(
                key="plan_review_records",
                title=f"{context.system_name} Security and Privacy Plan Review and Distribution Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_Security_and_Privacy_Plan_Review_Record.docx",
                document_type="technical_artifact",
                document_intent="verifies",
                controls_addressed=["PL-2"],
                sections=_pl_plan_review_record_sections(),
            ),
            PackageDocumentSpec(
                key="plan_distribution_record",
                title=f"{context.system_name} System Security and Privacy Plan Distribution Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_System_Security_and_Privacy_Plan_Distribution_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PL-2"],
                sections=_pl_distribution_record_sections(),
            ),
            PackageDocumentSpec(
                key="pl2_control_record",
                title=f"{context.system_name} PL-2 Security and Privacy Plan Control Evidence Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_PL2_Security_and_Privacy_Plan_Control_Evidence_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PL-2"],
                sections=_pl2_control_evidence_sections(),
            ),
            PackageDocumentSpec(
                key="pl2_risk_result_record",
                title=f"{context.system_name} PL-2 Security and Privacy Plan Privacy Risk Assessment Excerpts",
                filename=f"TEST_{family_id}PKG_{system_stem}_PL2_Security_and_Privacy_Plan_Privacy_Risk_Assessment_Excerpts.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PL-2"],
                sections=_pl2_risk_result_excerpts_sections(),
            ),
            PackageDocumentSpec(
                key="pl2_approval_distribution_protection_record",
                title=f"{context.system_name} PL-2 Plan Approval, Distribution, and Protection Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_PL2_Plan_Approval_Distribution_and_Protection_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PL-2"],
                sections=_pl2_approval_distribution_protection_sections(),
            ),
            PackageDocumentSpec(
                key="pl4_rules_update_record",
                title=f"{context.system_name} PL-4 Rules of Behavior Update Process Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_PL4_Rules_of_Behavior_Update_Process_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PL-4"],
                sections=_pl4_rules_update_sections(),
            ),
            PackageDocumentSpec(
                key="pl8_architecture_record",
                title=f"{context.system_name} PL-8 Security and Privacy Architecture Assumptions and Update Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_PL8_Security_and_Privacy_Architecture_Assumptions_and_Update_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PL-8"],
                sections=_pl8_architecture_sections(),
            ),
        ]
        return specs, controls_addressed

    if family_id == "PM":
        specs = [
            base_policy,
            PackageDocumentSpec(
                key="implementation",
                title=f"{context.system_name} {family_title} Technical Implementation Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Technical_Implementation_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=controls_addressed,
                sections=_implementation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="validation",
                title=f"{context.system_name} {family_title} Monthly Validation Review",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Monthly_Validation_Review.docx",
                document_type="technical_artifact",
                document_intent="verifies",
                controls_addressed=controls_addressed,
                sections=_validation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="information_security_program_plan",
                title=f"{context.system_name} Information Security Program Plan",
                filename=f"TEST_{family_id}PKG_{system_stem}_Information_Security_Program_Plan.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-1", "PM-4"],
                sections=_pm_information_security_program_plan_sections(context),
            ),
            PackageDocumentSpec(
                key="information_security_plan_maintenance",
                title=f"{context.system_name} Information Security Program Plan Maintenance and Protection Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_Information_Security_Program_Plan_Maintenance_and_Protection_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-1"],
                sections=_pm_information_security_plan_maintenance_sections(),
            ),
            PackageDocumentSpec(
                key="enterprise_architecture_security_record",
                title=f"{context.system_name} Enterprise Architecture Security Integration Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_Enterprise_Architecture_Security_Integration_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-7"],
                sections=_pm_enterprise_architecture_sections(context),
            ),
            PackageDocumentSpec(
                key="privacy_program_plan",
                title=f"{context.system_name} PM-18 Privacy Program Plan",
                filename=f"TEST_{family_id}PKG_{system_stem}_Privacy_Program_Plan.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-18", "PM-21", "PM-22", "PM-23", "PM-24", "PM-31"],
                sections=_pm_privacy_program_plan_sections(context),
            ),
            PackageDocumentSpec(
                key="privacy_program_distribution",
                title=f"{context.system_name} PM-18 Privacy Program Plan Distribution and Public Availability Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_PM18_Privacy_Program_Plan_Distribution_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-18"],
                sections=_pm_privacy_program_distribution_sections(),
            ),
            PackageDocumentSpec(
                key="privacy_program_required_audience",
                title=f"{context.system_name} PM-18 Privacy Program Plan Required Audience Dissemination Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_PM18_Privacy_Program_Plan_Required_Audience_Dissemination_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-18"],
                sections=_pm_required_audience_dissemination_sections(),
            ),
            PackageDocumentSpec(
                key="public_privacy_contact_notice",
                title=f"{context.system_name} PM-20 Public Privacy Webpage and Contact Notice",
                filename=f"TEST_{family_id}PKG_{system_stem}_PM20_Public_Privacy_Webpage_and_Contact_Notice.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-20"],
                sections=_pm_public_privacy_contact_sections(),
            ),
            PackageDocumentSpec(
                key="pm20_webpage_verification",
                title=f"{context.system_name} PM-20 Central Privacy Resource Webpage Verification Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_PM20_Central_Privacy_Resource_Webpage_Verification_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-20"],
                sections=_pm20_webpage_verification_sections(),
            ),
            PackageDocumentSpec(
                key="supply_chain_strategy_review",
                title=f"{context.system_name} Supply Chain Risk Management Strategy Review Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_Supply_Chain_Strategy_Review_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-4", "PM-30"],
                sections=_pm_supply_chain_strategy_sections(),
            ),
            PackageDocumentSpec(
                key="supply_chain_poam_reporting",
                title=f"{context.system_name} Supply Chain Risk Management POA&M Reporting Procedure",
                filename=f"TEST_{family_id}PKG_{system_stem}_Supply_Chain_Risk_Management_POAM_Reporting_Procedure.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-4"],
                sections=_pm_supply_chain_poam_reporting_sections(),
            ),
            PackageDocumentSpec(
                key="risk_framing_communication",
                title=f"{context.system_name} Risk Framing Communication Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_Risk_Framing_Communication_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-28"],
                sections=_pm_risk_framing_sections(),
            ),
            PackageDocumentSpec(
                key="privacy_report_record",
                title=f"{context.system_name} Privacy Report Dissemination and Review Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_Privacy_Report_Dissemination_and_Review_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-27"],
                sections=_pm_privacy_report_sections(),
            ),
            PackageDocumentSpec(
                key="pm18_control_record",
                title=f"{context.system_name} PM-18 Privacy Program Plan Strategic Goals, Dissemination, and Update Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_PM18_Privacy_Program_Plan_Strategic_Goals_Dissemination_and_Update_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-18"],
                sections=_pm18_control_evidence_sections(),
            ),
            PackageDocumentSpec(
                key="pm27_control_record",
                title=f"{context.system_name} PM-27 Privacy Report Dissemination and Review Control Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_PM27_Privacy_Report_Dissemination_and_Review_Control_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-27"],
                sections=_pm27_control_evidence_sections(),
            ),
            PackageDocumentSpec(
                key="data_integrity_board_review",
                title=f"{context.system_name} Data Integrity Board Matching Program Proposal Review Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_Data_Integrity_Board_Proposal_Review_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-24"],
                sections=_pm_data_integrity_board_review_sections(),
            ),
            PackageDocumentSpec(
                key="pm26_complaint_management",
                title=f"{context.system_name} PM-26 Public Complaint Management Process",
                filename=f"TEST_{family_id}PKG_{system_stem}_PM26_Public_Complaint_Management_Process.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-26"],
                sections=_pm26_complaint_management_sections(),
            ),
            PackageDocumentSpec(
                key="pii_quality_management",
                title=f"{context.system_name} PII Quality Management and Appeals Procedure",
                filename=f"TEST_{family_id}PKG_{system_stem}_PII_Quality_Management_and_Appeals_Procedure.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["PM-22"],
                sections=_pm_pii_quality_management_sections(),
            ),
        ]
        return specs, controls_addressed

    if family_id == "SA":
        specs = [
            base_policy,
            PackageDocumentSpec(
                key="implementation",
                title=f"{context.system_name} {family_title} Technical Implementation Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Technical_Implementation_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=controls_addressed,
                sections=_implementation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="validation",
                title=f"{context.system_name} {family_title} Monthly Validation Review",
                filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Monthly_Validation_Review.docx",
                document_type="technical_artifact",
                document_intent="verifies",
                controls_addressed=controls_addressed,
                sections=_validation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
            ),
            PackageDocumentSpec(
                key="sa5_documentation_response_record",
                title=f"{context.system_name} SA-5 Documentation Acquisition and Response Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_SA5_Documentation_Acquisition_and_Response_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["SA-5"],
                sections=_sa5_documentation_response_sections(),
            ),
            PackageDocumentSpec(
                key="sa10_reporting_requirement_record",
                title=f"{context.system_name} SA-10 Developer Findings Reporting Requirement Record",
                filename=f"TEST_{family_id}PKG_{system_stem}_SA10_Developer_Findings_Reporting_Requirement_Record.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["SA-10"],
                sections=_sa10_reporting_requirement_sections(),
            ),
            PackageDocumentSpec(
                key="sa5_admin_privacy_documentation",
                title=f"{context.system_name} SA-5 Administrator Security and Privacy Documentation Excerpts",
                filename=f"TEST_{family_id}PKG_{system_stem}_SA5_Administrator_Security_and_Privacy_Documentation_Excerpts.docx",
                document_type="technical_artifact",
                document_intent="implements",
                controls_addressed=["SA-5"],
                sections=_sa5_admin_privacy_documentation_sections(),
            ),
        ]
        return specs, controls_addressed

    specs = [
        base_policy,
        PackageDocumentSpec(
            key="implementation",
            title=f"{context.system_name} {family_title} Technical Implementation Record",
            filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Technical_Implementation_Record.docx",
            document_type="technical_artifact",
            document_intent="implements",
            controls_addressed=controls_addressed,
            sections=_implementation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
        ),
        PackageDocumentSpec(
            key="validation",
            title=f"{context.system_name} {family_title} Monthly Validation Review",
            filename=f"TEST_{family_id}PKG_{system_stem}_{policy_slug}_Monthly_Validation_Review.docx",
            document_type="technical_artifact",
            document_intent="verifies",
            controls_addressed=controls_addressed,
            sections=_validation_sections(context, family_id, family_title, substantive_controls or [policy_control]),
        ),
    ]
    return specs, controls_addressed


async def _generate_package_documents(
    *,
    assessment: Assessment,
    specs: list[PackageDocumentSpec],
    run_dir: Path,
) -> list[dict[str, Any]]:
    upload_dir = run_dir / "uploads" / str(assessment.project_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for spec in specs:
        file_bytes = _build_docx(spec.title, spec.sections, assessment.name or f"Assessment {assessment.id}")
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
    family_id: str,
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
        name=f"{family_id} family package proof run ({len(control_ids)} controls)",
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
    assessment_id, family_id, do_proof = _parse_args()
    async with AsyncSessionLocal() as db:
        assessment, system_context = await _load_context(db, assessment_id)
        context = await build_human_authoring_context(assessment.project_id, db)

    specs, control_ids = _build_package_specs(context, family_id)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = _package_output_root(family_id) / f"assessment_{assessment_id}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    generated = await _generate_package_documents(
        assessment=assessment,
        specs=specs,
        run_dir=run_dir,
    )
    output: dict[str, Any] = {
        "assessment_id": assessment_id,
        "family_id": family_id,
        "package_type": "generic_family_shared_artifacts",
        "test_area": str(run_dir),
        "controls_addressed": control_ids,
        "generated": generated,
    }
    if do_proof:
        output["proof"] = await _run_proof(
            source_assessment=assessment,
            system_context=system_context,
            control_ids=control_ids,
            evidence_doc_ids=[int(item["document_id"]) for item in generated if item.get("document_id")],
            family_id=family_id,
        )
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
