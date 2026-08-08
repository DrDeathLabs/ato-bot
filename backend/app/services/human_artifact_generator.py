"""Fast, human-style artifact generator kept separate from the legacy closure path."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.orm import Assessment, Project, SystemProfile
from app.services.closure_service import _build_project_context, _wait_for_document_index
from app.services.controls.catalog import Control, load_catalog
from app.services.evidence_view import build_system_context_from_evidence
from app.services.implementation_statements import normalize_objective_description
from app.services.llm.runtime import build_provider_for_purpose
from app.services.parsers.dispatcher import dispatch_parse
from app.services.test_dataset_generator import _build_docx, _save_doc


_OBJECTIVE_ID_RE = re.compile(
    r"\b[A-Z]{2}-0?\d+(?:\(\d+\))?(?:[a-z])?(?:\.\d+)?(?:\[\d+\])?\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9/-]*", re.IGNORECASE)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it",
    "of", "on", "or", "that", "the", "this", "to", "with", "who", "what", "when", "where",
    "how", "must", "shall", "should", "maintains", "maintained", "uses", "using", "use",
    "system", "control", "documented", "defined", "organizational", "criteria",
}
_FORBIDDEN_PHRASES = (
    "this section satisfies",
    "nist 800-53a assessment objective",
    "required assessment terms addressed",
    "current-state implementation statement",
    "the reviewed materials indicate",
    "objective coverage checklist",
    "assessment objective",
    "traceability matrix",
    "crosswalk",
    "implemented setting is",
)
_PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}")


@dataclass(slots=True)
class HumanAuthoringContext:
    project_id: int
    system_name: str
    project_name: str
    impact_baseline: str
    context_label: str
    deployment_model: str | None
    infrastructure_ownership: str | None
    evidence_excerpt: str


@dataclass(slots=True)
class HumanArtifactPlan:
    control_id: str
    control_title: str
    artifact_type: str
    document_type: str
    title: str
    filename: str
    outline: list[str]


@dataclass(slots=True)
class ClauseRequirement:
    issue: str
    tokens: tuple[str, ...]
    heading: str
    paragraph: str


def _safe_filename_component(text: str, max_length: int = 80) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:max_length]


def _strip_json_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return text


def _section_text(sections: Iterable[dict[str, Any]]) -> str:
    parts: list[str] = []
    for section in sections:
        if section.get("type") == "table":
            headers = section.get("headers") or []
            rows = section.get("rows") or []
            parts.append(" ".join(str(item) for item in headers))
            for row in rows:
                parts.append(" ".join(str(item) for item in row))
            continue
        if section.get("text"):
            parts.append(str(section["text"]))
        for item in section.get("items") or []:
            parts.append(str(item))
    return "\n".join(parts)


def _sanitize_generated_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for section in sections:
        item = dict(section)
        if item.get("text"):
            item["text"] = _PLACEHOLDER_RE.sub(
                "the organization's approved acquisition clause set",
                str(item["text"]),
            )
        if item.get("items"):
            item["items"] = [
                _PLACEHOLDER_RE.sub(
                    "the organization's approved acquisition clause set",
                    str(value),
                )
                for value in item["items"]
            ]
        if item.get("headers"):
            item["headers"] = [
                _PLACEHOLDER_RE.sub(
                    "the organization's approved acquisition clause set",
                    str(value),
                )
                for value in item["headers"]
            ]
        if item.get("rows"):
            item["rows"] = [
                [
                    _PLACEHOLDER_RE.sub(
                        "the organization's approved acquisition clause set",
                        str(value),
                    )
                    for value in row
                ]
                for row in item["rows"]
            ]
        updated.append(item)
    return updated


def _signal_tokens(value: str) -> set[str]:
    tokens = [token.lower() for token in _TOKEN_RE.findall(value or "")]
    return {token for token in tokens if token not in _STOPWORDS and len(token) > 2}


def _sanitize_context_excerpt_for_authoring(raw_excerpt: str) -> str:
    lines: list[str] = []
    for raw_line in (raw_excerpt or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if "\\" in line or "/" in line:
            continue
        if any(
            lowered.endswith(suffix)
            for suffix in (".docx", ".xlsx", ".pptx", ".pdf", ".csv", ".json", ".txt")
        ):
            continue
        if "evidence artifact" in lowered or "artifact path" in lowered:
            continue
        if len(line) < 20:
            continue
        lines.append(line)
        if len(lines) == 6:
            break
    return "\n".join(lines)


def _normalize_check_text(value: str) -> str:
    normalized = (value or "").lower()
    for source, target in {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u202f": " ",
        "\u00a0": " ",
    }.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"\s+", " ", normalized)


def _objective_descriptions(control: Control) -> list[str]:
    descriptions: list[str] = []
    for objective in control.assessment_objectives:
        descriptions.append(normalize_objective_description(objective))
    return [item for item in descriptions if item]


def _control_specific_authoring_requirements(control: Control) -> list[str]:
    match control.display_id:
        case "AC-1":
            return [
                "Include one explicit policy statement describing coordination among organizational entities, and name the entities involved such as the Information Security Office, System Owner, engineering, and service desk or operations teams.",
                "State who is responsible for developing, documenting, disseminating, and reviewing the policy and procedures.",
                "Include one explicit statement that the access control procedures are disseminated to a named operational audience and that the distribution is recorded.",
            ]
        case "AC-2":
            return [
                "State a defined timeframe for notifying account managers and other designated parties when a user is terminated or transferred.",
                "State a defined timeframe for notifying account managers and other designated parties when a user's system usage or need-to-know changes.",
                "State that accounts are reviewed on a defined cadence against organization-defined account management requirements, and identify the report or record produced by that review.",
            ]
        case "SR-1":
            return [
                "State how the policy and procedures are disseminated to the operational audience and how distribution is recorded.",
            ]
        case _:
            return []


def _control_specific_presence_checks(control: Control) -> list[tuple[str, tuple[str, ...]]]:
    match control.display_id:
        case "AC-1":
            return [
                (
                    "Document must explicitly describe coordination among named organizational entities.",
                    ("coordination", "information security", "system owner"),
                ),
                (
                    "Document must explicitly state that procedures are disseminated to a named audience.",
                    ("procedures", "engineering team", "service desk", "distribute"),
                ),
            ]
        case "AC-2":
            return [
                (
                    "Document must state a defined timeframe for termination or transfer notifications.",
                    ("terminated", "transferred", "within", "hours"),
                ),
                (
                    "Document must state a defined timeframe for need-to-know or system usage change notifications.",
                    ("need-to-know", "within", "hours"),
                ),
                (
                    "Document must describe periodic account review against defined account management requirements.",
                    ("quarterly", "account management requirements", "review"),
                ),
            ]
        case _:
            return []


def _default_operational_audience(control: Control) -> str:
    family = control.family_id.upper()
    if family == "SR":
        return "system owners, procurement staff, vendor managers, legal reviewers, security staff, engineering leads, and personnel responsible for supplier oversight"
    if family == "IR":
        return "incident responders, system owners, service desk personnel, security staff, and engineering leads"
    if family == "PL":
        return "system owners, engineering leads, security staff, service desk personnel, and program leadership"
    if family == "RA":
        return "system owners, security staff, engineering leads, control owners, and program leadership"
    if family == "AC":
        return "system administrators, service desk personnel, engineering staff, security staff, and managers who approve or review access"
    return "system owners, engineering leads, service desk personnel, security staff, and personnel assigned control responsibilities"


def _base_clause_requirements(control: Control, context: HumanAuthoringContext) -> list[ClauseRequirement]:
    descriptions = [_normalize_check_text(item) for item in _objective_descriptions(control)]
    body: list[ClauseRequirement] = []
    audience = _default_operational_audience(control)
    title = control.title.lower()

    def add(issue: str, tokens: tuple[str, ...], heading: str, paragraph: str) -> None:
        if issue not in {item.issue for item in body}:
            body.append(ClauseRequirement(issue=issue, tokens=tokens, heading=heading, paragraph=paragraph))

    if any("coordination among organizational entities" in desc for desc in descriptions):
        add(
            "Document must explicitly describe coordination among named organizational entities.",
            ("coordination", "information security office", "system owner"),
            "Policy",
            (
                "Coordination among organizational entities is required to keep this control effective. The Information Security Office, "
                "System Owner, engineering leads, and service desk or operations personnel coordinate approvals, operational changes, and "
                "periodic reviews so that implementation decisions, exceptions, and retained records stay aligned."
            ),
        )

    if any("management commitment" in desc for desc in descriptions):
        add(
            "Document must explicitly state management commitment.",
            ("management commitment", "resources", "oversight"),
            "Policy",
            (
                "Management commitment is demonstrated through formal approval of this document, assignment of accountable owners, funding for the required tools and staffing, "
                "and oversight of corrective actions through the regular control review process."
            ),
        )

    if any("applicable laws" in desc or "executive orders" in desc or "standards" in desc or "guidelines" in desc for desc in descriptions):
        add(
            "Document must explicitly state consistency with applicable laws, directives, standards, and guidelines.",
            ("applicable laws", "executive orders", "standards", "guidelines"),
            "Policy",
            (
                "This policy and the related procedures are maintained to remain consistent with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines. "
                "Changes to those authorities are reviewed during the annual document review and incorporated through document control."
            ),
        )

    if any("disseminated" in desc for desc in descriptions):
        doc_label = "policy and procedures" if control.display_id.endswith("-1") else "documented procedures"
        add(
            "Document must explicitly state that procedures are disseminated to a named audience.",
            ("disseminated", "distribution", "recorded"),
            "Procedures" if "Procedures" in _default_outline("policy") or control.display_id.endswith("-1") else "Records and Review",
            (
                f"The {doc_label} are disseminated to {audience}. Distribution is recorded in the controlled distribution log, "
                "which captures the release date, recipients, and acknowledgement or posting record for each update."
            ),
        )

    if control.display_id.endswith("-1") and any("policy is disseminated" in desc for desc in descriptions):
        add(
            "Document must explicitly state that the policy is disseminated to a named audience.",
            ("policy", "disseminated", "distribution", "recorded"),
            "Policy",
            (
                f"This policy is disseminated to {audience}. Distribution is recorded in the controlled distribution log, "
                "which captures the release date, recipients, publication location, and acknowledgement or posting record for each update."
            ),
        )

    if any("addresses roles" in desc for desc in descriptions):
        add(
            "Document must explicitly state that the policy addresses roles.",
            ("policy addresses roles",),
            "Policy",
            "The policy addresses roles by identifying the organizational positions that approve, implement, review, and oversee this control and by defining how those roles interact during normal operations and change events.",
        )

    if any("addresses responsibilities" in desc for desc in descriptions):
        add(
            "Document must explicitly state that the policy addresses responsibilities.",
            ("policy addresses responsibilities",),
            "Policy",
            "The policy addresses responsibilities by defining the duties each assigned role performs, the records each role maintains, and the approvals or follow-up actions each role must complete.",
        )

    if any("is designated to manage the development, documentation, and dissemination" in desc for desc in descriptions):
        add(
            "Document must explicitly identify the role designated to manage development, documentation, and dissemination.",
            ("designated", "development", "documentation", "dissemination"),
            "Policy",
            "The Information Security Office designates the named control manager to oversee development, documentation, publication, and dissemination of the policy and supporting procedures, including version control and distribution records.",
        )

    if any("policy is reviewed and updated" in desc for desc in descriptions):
        add(
            "Document must explicitly describe the policy review and update schedule.",
            ("policy", "reviewed", "updated", "annually"),
            "Review and Document Control",
            "The policy is reviewed and updated at least annually and after significant system, regulatory, staffing, supplier, or threat changes. The review date, approver, and resulting updates are recorded in the document control register.",
        )

    if any("procedures are reviewed and updated" in desc for desc in descriptions):
        add(
            "Document must explicitly describe the procedures review and update schedule.",
            ("procedures", "reviewed", "updated", "annually"),
            "Review and Document Control" if control.display_id.endswith("-1") else "Records and Review",
            "The procedures are reviewed and updated at least annually and after significant incidents, tests, audits, or operational changes. Updated procedures are redistributed to the operational audience and the redistribution is logged.",
        )

    if any("reviewed and updated" in desc or ("reviewed" in desc and "updated" in desc) for desc in descriptions):
        add(
            "Document must explicitly describe the review and update cadence.",
            ("reviewed", "updated", "annually"),
            "Review and Document Control" if control.display_id.endswith("-1") else "Records and Review",
            (
                "This document and its supporting procedures are reviewed at least annually and after major system, regulatory, supplier, "
                "or threat changes. Required updates are completed through document control within ten business days of an approved change or finding."
            ),
        )

    if any("account types" in desc and "allowed" in desc for desc in descriptions):
        add(
            "Document must explicitly define allowed account types.",
            ("allowed account types", "individual user", "service account"),
            "Operating Procedure",
            (
                "Allowed account types include individual user accounts, privileged administrative accounts approved for specific duties, service accounts tied to approved automated processes, "
                "and temporary or emergency accounts that are time-bounded and explicitly approved."
            ),
        )

    if any("prohibited account types" in desc for desc in descriptions):
        add(
            "Document must explicitly define prohibited account types.",
            ("prohibited account types", "generic", "anonymous"),
            "Operating Procedure",
            (
                "Prohibited account types include anonymous accounts, generic personal accounts without individual accountability, unsponsored vendor accounts, and unmanaged local administrator accounts."
            ),
        )

    if any("group and role membership" in desc for desc in descriptions):
        add(
            "Document must explicitly describe group and role membership requirements.",
            ("group membership", "role membership", "approved job duties"),
            "Operating Procedure",
            (
                "Group membership and role membership are granted only when the assigned access profile matches approved job duties, need-to-know, supervisor approval, and the role definition maintained in the access catalog."
            ),
        )

    if any("account usage" in desc and "monitored" in desc for desc in descriptions):
        add(
            "Document must explicitly describe account usage monitoring.",
            ("monitors", "account activity", "weekly"),
            "Operating Procedure",
            (
                "Account activity is monitored through directory logs, application audit trails, and automated alerts. The Security Officer "
                "reviews account activity each business day and issues a weekly account usage report to the Account Manager for follow-up."
            ),
        )

    if any("account managers are assigned" in desc for desc in descriptions):
        add(
            "Document must explicitly state that account managers are assigned.",
            ("account managers are assigned", "platform administrator", "account lifecycle actions"),
            "Roles and Responsibilities",
            (
                "Account managers are assigned for each managed account population. The Platform Administrator serves as the account manager for directory, application, shared, and service account records and is responsible for account lifecycle actions, review coordination, and evidence retention."
            ),
        )

    if any("specified for each account" in desc for desc in descriptions):
        add(
            "Document must explicitly list the organization-defined criteria recorded for each account.",
            ("criteria", "each account", "authorized user", "business justification"),
            "Operating Procedure",
            (
                "For each account, the recorded criteria include the authorized user or service identity, approved role or group membership, "
                "required privileges, business justification, approval record, and review or expiration date where applicable."
            ),
        )

    if any("notified" in desc and ("terminated" in desc or "transferred" in desc) for desc in descriptions):
        add(
            "Document must state a defined timeframe for termination or transfer notifications.",
            ("terminated", "transferred", "within 24 hours"),
            "Operating Procedure",
            (
                "When a user is terminated or transferred, Human Resources notifies the Account Manager, Security Officer, and responsible service desk lead "
                "within 24 hours of the personnel action so disablement, review, and follow-up records can begin immediately."
            ),
        )

    if any("no longer required" in desc for desc in descriptions):
        add(
            "Document must state a defined timeframe for notifications when accounts are no longer required.",
            ("no longer required", "within 24 hours", "account manager"),
            "Operating Procedure",
            (
                "When an account is determined to be no longer required, the Account Manager, Security Officer, and responsible service desk lead are notified within 24 hours so disablement and removal activities can begin under the approved workflow."
            ),
        )

    if any("need-to-know" in desc or "system usage" in desc for desc in descriptions):
        add(
            "Document must state a defined timeframe for need-to-know or system usage change notifications.",
            ("need-to-know", "within 48 hours", "account manager"),
            "Operating Procedure",
            (
                "When a user's system usage or need-to-know changes, the requesting manager notifies the Account Manager and Security Officer "
                "within 48 hours so privileges can be re-evaluated, adjusted, or removed under the approved change record."
            ),
        )

    if any("reviewed for compliance with organization-defined account management requirements" in desc for desc in descriptions):
        add(
            "Document must describe periodic account review against defined account management requirements.",
            ("accounts are reviewed for compliance with account management requirements", "quarterly account management review report"),
            "Records and Review",
            (
                "Accounts are reviewed for compliance with account management requirements during the quarterly account review cycle. The Account Manager produces "
                "a quarterly account management review report that documents scope, exceptions, required corrections, and management sign-off."
            ),
        )

    if any("shared or group account authenticators" in desc or "removed from the group" in desc for desc in descriptions):
        add(
            "Document must describe shared or group account authenticator rotation.",
            ("shared or group account authenticators", "removed from the group", "within 12 hours"),
            "Operating Procedure",
            (
                "A process is established and implemented for changing shared or group account authenticators when individuals are removed from the group. "
                "If a shared or group account is used, its password, token, or other authenticator is changed within 12 hours after any individual is removed from the authorized group, "
                "the change is recorded in the shared authenticator log, and the updated secret is redistributed securely only to the remaining authorized users."
            ),
        )

    if any("group or role accounts when membership to those accounts changes" in desc for desc in descriptions):
        add(
            "Document must explicitly state that authenticators for group or role accounts are changed when membership changes.",
            ("authenticators for group or role accounts are changed when membership", "membership changes"),
            "Operating Procedure",
            (
                "Authenticators for group or role accounts are changed when membership to those accounts changes. The account owner initiates the change immediately after the membership update, records the action in the shared authenticator log, and redistributes the updated secret only to the remaining authorized members."
            ),
        )

    if any("subnetworks" in desc or "isolated from internal organizational networks" in desc for desc in descriptions):
        add(
            "Document must explicitly describe public-facing component isolation.",
            ("dmz", "segmented", "internal network"),
            "Configuration and Control Points",
            (
                f"Public-facing {title} components are placed in a segmented DMZ or dedicated security zone that is isolated from the internal network. "
                "Firewall rules, reverse proxy boundaries, and access control lists restrict traffic between the external zone and internal services to approved ports and protocols only."
            ),
        )

    if any("rationale is provided" in desc and "after-the-fact investigations" in desc for desc in descriptions):
        add(
            "Document must provide an explicit rationale for the selected logged event types.",
            ("event types", "sufficient", "after the fact investigations"),
            "Implementation Overview",
            "The selected event types are considered sufficient for after-the-fact investigations because they capture account activity, administrative actions, security events, configuration changes, and transaction processing needed to reconstruct the timeline, scope, and impact of an incident.",
        )

    if any("findings are reported" in desc for desc in descriptions):
        add(
            "Document must explicitly state that audit findings are reported to defined recipients.",
            ("audit findings", "reported", "defined recipients"),
            "Records and Review",
            "Audit findings are reported to defined recipients, including the System Owner, Security Officer, and operations leadership, through the weekly audit review summary and immediate escalation notices for significant events.",
        )

    if any("level of audit record review, analysis, and reporting" in desc and "change in risk" in desc for desc in descriptions):
        add(
            "Document must explicitly state that audit review levels are adjusted when risk changes.",
            ("audit record review", "adjusted", "change in risk", "credible sources"),
            "Records and Review",
            "The level of audit record review, analysis, and reporting is adjusted when there is a change in risk based on law enforcement information, intelligence information, or other credible sources, and the resulting change in review frequency or escalation criteria is documented in the audit monitoring decision record.",
        )

    if any("results of the control assessment are provided" in desc for desc in descriptions):
        add(
            "Document must explicitly state that control assessment results are provided to defined recipients.",
            ("results of the control assessment", "provided", "defined recipients"),
            "Records and Review",
            "The results of the control assessment are provided to defined recipients, including the Authorizing Official or designated representative, the System Owner, and the Security Officer, through the approved control assessment report and briefing package.",
        )

    if any("control assessment plan is reviewed and approved" in desc for desc in descriptions):
        add(
            "Document must explicitly state that the control assessment plan is reviewed and approved before the assessment.",
            ("control assessment plan", "reviewed and approved", "authorizing official"),
            "Governance and Oversight",
            "The control assessment plan is reviewed and approved by the Authorizing Official or designated representative before the assessment begins, and the signed approval record is retained with the assessment package.",
        )

    if any("convenes" in desc and "configuration control element" in desc for desc in descriptions):
        add(
            "Document must explicitly state how often the configuration control element convenes.",
            ("configuration control element", "convened monthly", "emergency session"),
            "Implementation Overview",
            "The configuration control element is convened monthly as the Configuration Change Board and is also convened for an emergency session within one business day when urgent security or operational changes require review.",
        )

    if any("records of configuration-controlled changes" in desc and "retained" in desc for desc in descriptions):
        add(
            "Document must explicitly state the retention period for configuration change records.",
            ("records of configuration controlled changes", "retained for five years"),
            "Evidence Retention",
            "Records of configuration-controlled changes are retained for five years in the secure records repository, including requests, approvals, analyses, implementation notes, and verification results.",
        )

    if any("activities associated with configuration-controlled changes" in desc and "monitored" in desc for desc in descriptions):
        add(
            "Document must explicitly describe monitoring of configuration-controlled change activities.",
            ("activities associated with configuration controlled changes are monitored", "change tracking dashboards", "ticket workflow checkpoints"),
            "Verification Activities",
            "Activities associated with configuration-controlled changes are monitored through change tracking dashboards, security alerts, ticket workflow checkpoints, and post-implementation verification records, and anomalies are escalated to the configuration control element for review.",
        )

    if any("contingency information" in desc and "shared" in desc for desc in descriptions):
        add(
            "Document must explicitly describe how contingency information is shared.",
            ("contingency information", "shared", "stakeholders"),
            "Operating Procedure",
            "Contingency information, including status updates, recovery priorities, and contact changes, is shared with internal and external stakeholders through the continuity notification roster, encrypted email, and the continuity bridge during an active event.",
        )

    if any("copies of the contingency plan are distributed" in desc for desc in descriptions):
        add(
            "Document must explicitly describe contingency plan distribution to defined recipients.",
            ("copies of the contingency plan", "distributed", "defined recipients"),
            "Records and Review",
            "Copies of the approved contingency plan are distributed to defined recipients, including the System Owner, incident response lead, business continuity coordinator, data custodian, and executive management, and receipt is recorded in the contingency distribution log.",
        )

    if any("assigned individuals with contact information" in desc for desc in descriptions):
        add(
            "Document must explicitly list assigned individuals with contact information.",
            ("assigned individuals", "contact information", "primary", "alternate"),
            "Operating Procedure",
            "The contingency plan identifies assigned individuals with contact information, including primary and alternate contacts for executive leadership, infrastructure support, application support, vendor coordination, incident response, and continuity management.",
        )

    if any("contingency planning activities are coordinated with incident handling activities" in desc for desc in descriptions):
        add(
            "Document must explicitly describe coordination between contingency planning and incident handling.",
            ("contingency planning activities are coordinated with incident handling activities", "shared escalation criteria"),
            "Operating Procedure",
            "Contingency planning activities are coordinated with incident handling activities through shared escalation criteria, joint status meetings, and the transfer of forensic findings, recovery decisions, and restoration approvals between the two teams.",
        )

    if any("plan is updated to address changes" in desc for desc in descriptions):
        add(
            "Document must explicitly describe updating the contingency plan for changes to the organization, system, or environment.",
            ("contingency plan", "updated", "organization", "environment of operation"),
            "Records and Review",
            "The contingency plan is updated when changes occur to the organization, system architecture, supplier dependencies, or environment of operation, and the revision record identifies the trigger, approver, and redistributed version.",
        )

    if any("contingency plan for the system is reviewed" in desc for desc in descriptions):
        add(
            "Document must explicitly describe the contingency plan review schedule.",
            ("contingency plan", "reviewed", "annually"),
            "Records and Review",
            "The contingency plan is reviewed at least annually by the System Owner, incident response lead, and continuity coordinator, and the review record documents the review date, participants, required updates, and approval decision.",
        )

    if any("problems encountered during contingency plan implementation" in desc for desc in descriptions):
        add(
            "Document must explicitly describe updating the contingency plan based on problems encountered during implementation, execution, or testing.",
            ("contingency plan", "updated", "problems encountered", "testing"),
            "Records and Review",
            "The contingency plan is updated to address problems encountered during contingency plan implementation, execution, or testing, and the resulting corrections are tracked through the contingency improvement record until closure.",
        )

    if any("plan changes are communicated" in desc for desc in descriptions):
        add(
            "Document must explicitly describe communication of contingency plan changes.",
            ("contingency plan changes", "communicated", "defined stakeholders"),
            "Records and Review",
            "Changes to the contingency plan are communicated to defined stakeholders within five business days through the continuity distribution roster and are logged in the document change notification record.",
        )

    if any("lessons learned" in desc and "contingency" in desc for desc in descriptions):
        add(
            "Document must explicitly describe incorporation of contingency lessons learned into testing and training.",
            ("lessons learned", "contingency testing", "training"),
            "Records and Review",
            "Lessons learned from contingency testing, training, and actual events are incorporated into the next test cycle and into staff training updates, and those changes are documented in the contingency improvement tracker.",
        )

    if any("protected from unauthorized modification" in desc for desc in descriptions):
        add(
            "Document must explicitly describe protection of the contingency plan from unauthorized modification.",
            ("contingency plan", "protected from unauthorized modification", "version control"),
            "Records and Review",
            "The contingency plan is protected from unauthorized modification through version control, role-based edit permissions, integrity-preserving storage in the controlled document repository, and approval checks before any revised version is published.",
        )

    if any("incident handling activities are coordinated with contingency planning activities" in desc for desc in descriptions):
        add(
            "Document must explicitly describe coordination between incident handling and contingency planning activities.",
            ("incident handling activities are coordinated with contingency planning activities", "shared escalation criteria"),
            "Operating Procedure",
            "Incident handling activities are coordinated with contingency planning activities through shared escalation criteria, joint status calls, recovery decision handoffs, and synchronized restoration approvals whenever an incident affects continuity operations.",
        )

    if any("lessons learned" in desc and "incident response procedures" in desc for desc in descriptions):
        add(
            "Document must explicitly describe incorporation of incident lessons learned into procedures, training, and testing.",
            ("lessons learned", "incident response procedures", "training"),
            "Operating Procedure",
            "Lessons learned from incident handling activities are incorporated into incident response procedures, training content, and testing scenarios, and the resulting updates are implemented through the incident improvement record.",
        )

    if any("changes resulting from the incorporated lessons learned are implemented accordingly" in desc for desc in descriptions):
        add(
            "Document must explicitly state that lessons-learned changes are implemented.",
            ("changes resulting from the incorporated lessons learned are implemented", "incident improvement record"),
            "Records and Review",
            "Changes resulting from the incorporated lessons learned are implemented accordingly through the incident improvement record, which tracks the required action, owner, due date, validation evidence, and closure decision for each corrective measure.",
        )

    if any("other physical access devices are secured" in desc for desc in descriptions):
        add(
            "Document must explicitly state that other physical access devices are secured.",
            ("other physical access devices", "secured"),
            "Operating Procedure",
            "Other physical access devices, including badge readers, intercom release panels, biometric readers, and portable access tokens, are secured through locked housings, administrator-only configuration access, and quarterly integrity checks.",
        )

    if any("visitors are escorted" in desc and "monitored" in desc for desc in descriptions):
        add(
            "Document must explicitly state that visitors are escorted and monitored.",
            ("visitors", "escorted", "monitored"),
            "Operating Procedure",
            "Visitors are escorted by authorized personnel at all times while inside controlled spaces, their activity is monitored until departure, and the escort assignment is recorded in the visitor log for each visit.",
        )

    if any("verifying individual access authorizations before granting access to the facility" in desc for desc in descriptions):
        add(
            "Document must explicitly state that individual physical access authorizations are verified before granting access.",
            ("verifying individual access authorizations before granting access to the facility", "current access list"),
            "Operating Procedure",
            "Security personnel enforce physical access authorizations by verifying individual access authorizations before granting access to the facility, using the current access list, badge status, and any temporary approval record before a door is unlocked or a visitor badge is issued.",
        )

    if any("physical access audit logs are maintained" in desc for desc in descriptions):
        add(
            "Document must explicitly state that physical access audit logs are maintained for the defined period.",
            ("physical access audit logs are maintained", "retained for 12 months"),
            "Records and Review",
            "Physical access audit logs are maintained and retained for 12 months in the access control monitoring repository, with weekly review of current activity and preservation of older records for investigations and compliance checks.",
        )

    if any("inventoried" in desc and "physical access" in desc for desc in descriptions):
        add(
            "Document must explicitly state that physical access devices are inventoried.",
            ("physical access devices are inventoried", "badge readers", "biometric", "turnstiles"),
            "Operating Procedure",
            "Physical access devices are inventoried and tracked in the physical access register, including keys, temporary badges, badge readers, biometric readers, turnstiles, lock cores, cabinet keys, and related access media. The register is reviewed at least quarterly and whenever a discrepancy, loss, or facility change occurs.",
        )

    if any("keys are changed" in desc and ("lost" in desc or "transferred" in desc or "terminated" in desc) for desc in descriptions):
        add(
            "Document must explicitly describe when physical keys are changed.",
            ("keys are changed when keys are lost", "transferred", "terminated"),
            "Operating Procedure",
            "Keys are changed when keys are lost and when individuals possessing the keys are transferred or terminated. Re-keying or key replacement is documented in the key control record, confirmed by the Facility Security Officer, and communicated to the authorized custodians for the affected area.",
        )

    if any("combinations are secured" in desc for desc in descriptions):
        add(
            "Document must explicitly describe how lock combinations are secured.",
            ("combinations", "secured", "stored"),
            "Operating Procedure",
            "Lock combinations are secured by limiting knowledge to authorized custodians, storing recovery copies in a sealed secure cabinet, prohibiting informal sharing, and changing combinations on a defined schedule or after compromise, transfer, or termination events.",
        )

    if any("combinations are changed" in desc and ("compromised" in desc or "transferred" in desc or "terminated" in desc) for desc in descriptions):
        add(
            "Document must explicitly describe when combinations are changed.",
            ("combinations are changed when combinations are compromised", "transferred", "terminated"),
            "Operating Procedure",
            "Combinations are changed when combinations are compromised and when individuals possessing the combinations are transferred or terminated. Each combination change is recorded in the lock control register, verified by the Facility Security Officer, and redistributed only to the newly authorized custodians.",
        )

    if any("physical access to the facility" in desc and "monitored" in desc for desc in descriptions):
        add(
            "Document must explicitly describe monitoring of physical access and response to incidents.",
            ("physical access", "monitored", "incidents"),
            "Operating Procedure",
            "Physical access to the facility is monitored continuously through badge-reader events, alarm sensors, camera coverage, and guard or operator review so the organization can detect and respond to physical security incidents promptly.",
        )

    if any("physical access logs are reviewed" in desc for desc in descriptions):
        add(
            "Document must explicitly describe scheduled and event-driven review of physical access logs.",
            ("physical access logs are reviewed", "weekly"),
            "Records and Review",
            "Physical access logs are reviewed on a weekly schedule and immediately after defined trigger events such as alarms, forced-door conditions, lost badges, or suspected unauthorized entry.",
        )

    if any("physical access logs are reviewed upon occurrence" in desc for desc in descriptions):
        add(
            "Document must explicitly describe event-driven review of physical access logs.",
            ("physical access logs are reviewed upon occurrence", "alarms", "lost badges"),
            "Records and Review",
            "Physical access logs are reviewed upon occurrence of defined events, including alarms, forced-door conditions, lost badges, suspected tailgating, and attempted access outside approved hours.",
        )

    if any("results of reviews are coordinated with organizational incident response capabilities" in desc for desc in descriptions):
        add(
            "Document must explicitly describe coordination of physical access review results with incident response.",
            ("coordinated", "incident response", "physical access"),
            "Records and Review",
            "Results of physical access log reviews and investigations are coordinated with the incident response capability through shared case records, escalation criteria, and notification to security operations when physical events may affect cyber operations.",
        )

    if any("acquisition contract" in desc for desc in descriptions):
        add(
            "Document must explicitly describe use of the approved acquisition clause set in contracts.",
            ("acquisition contract", "approved acquisition clause set", "acceptance criteria"),
            "Operating Procedure",
            "Each acquisition contract uses the organization's approved acquisition clause set to include security, privacy, assurance, documentation protection, supply chain responsibility, and acceptance criteria requirements before award and again before final acceptance.",
        )

    if any("security functional requirements" in desc and "acquisition contract" in desc for desc in descriptions):
        add(
            "Document must explicitly state that acquisition contracts include security and privacy functional requirements.",
            ("acquisition contract", "security functional requirements", "privacy functional requirements"),
            "Operating Procedure",
            "Each acquisition contract includes security functional requirements, privacy functional requirements, and the associated descriptions and evaluation criteria either directly in the contract schedule or by reference to the approved statement of work and control appendix.",
        )

    if any("strength of mechanism requirements" in desc for desc in descriptions):
        add(
            "Document must explicitly state that acquisition contracts include strength of mechanism requirements.",
            ("acquisition contract", "strength of mechanism requirements"),
            "Operating Procedure",
            "Each acquisition contract includes strength of mechanism requirements, descriptions, and criteria for authentication, cryptographic protections, and other security-relevant functions that must meet the organization's approved baseline.",
        )

    if any("security assurance requirements" in desc or "privacy assurance requirements" in desc for desc in descriptions):
        add(
            "Document must explicitly state that acquisition contracts include assurance requirements.",
            ("security assurance requirements", "privacy assurance requirements", "acquisition contract"),
            "Operating Procedure",
            "Each acquisition contract includes security assurance requirements and privacy assurance requirements, together with the descriptions, evidence expectations, and evaluation criteria the supplier must satisfy before acceptance.",
        )

    if any("controls needed to satisfy the security requirements" in desc or "controls needed to satisfy the privacy requirements" in desc for desc in descriptions):
        add(
            "Document must explicitly state that acquisition contracts include required security, privacy, and supporting controls.",
            ("acquisition contract", "security requirements", "privacy requirements", "controls needed"),
            "Operating Procedure",
            "Each acquisition contract includes the controls needed to satisfy the security requirements and privacy requirements, either explicitly in the contract clauses or by reference to the approved control implementation appendix attached to the solicitation and award package.",
        )

    if any("documentation requirements" in desc and "acquisition contract" in desc for desc in descriptions):
        add(
            "Document must explicitly state that acquisition contracts include security and privacy documentation requirements.",
            ("security documentation requirements", "privacy documentation requirements", "acquisition contract"),
            "Operating Procedure",
            "Each acquisition contract includes security documentation requirements and privacy documentation requirements, including the required descriptions, delivery milestones, and acceptance criteria for plans, designs, test evidence, and operating guidance.",
        )

    if any("protecting security documentation" in desc or "protecting privacy documentation" in desc for desc in descriptions):
        add(
            "Document must explicitly state that acquisition contracts protect security and privacy documentation.",
            ("protecting security documentation", "protecting privacy documentation", "acquisition contract"),
            "Operating Procedure",
            "Each acquisition contract includes requirements for protecting security documentation and protecting privacy documentation, including marking, handling, access control, storage, transmission, return, and destruction requirements for supplier-provided materials.",
        )

    if any("system development environment" in desc and "intended to operate" in desc for desc in descriptions):
        add(
            "Document must explicitly state that acquisition contracts describe the development and operating environments.",
            ("system development environment", "intended to operate", "acquisition contract"),
            "Operating Procedure",
            "Each acquisition contract includes the description of the system development environment, the environment in which the system is intended to operate, the applicable requirements, and the criteria used to evaluate whether the delivered capability is acceptable for production use.",
        )

    if any("allocation of responsibility" in desc or "parties responsible" in desc for desc in descriptions):
        add(
            "Document must explicitly state that acquisition contracts allocate responsibility for security, privacy, and supply chain requirements.",
            ("allocation of responsibility", "information security requirements", "privacy requirements", "supply chain risk management requirements"),
            "Operating Procedure",
            "Each acquisition contract includes an allocation of responsibility that identifies the parties responsible for information security requirements, privacy requirements, and supply chain risk management requirements, together with the accountable approvers, delivery owners, and acceptance authorities for each obligation.",
        )

    if any("acceptance criteria requirements" in desc for desc in descriptions):
        add(
            "Document must explicitly state that acquisition contracts include acceptance criteria.",
            ("acceptance criteria requirements", "acquisition contract"),
            "Operating Procedure",
            "Each acquisition contract includes acceptance criteria requirements and descriptions that must be satisfied before the organization accepts the system, component, or service, including verification evidence, defect correction obligations, and sign-off authorities.",
        )

    if any("send alerts" in desc and "malicious code" in desc for desc in descriptions):
        add(
            "Document must explicitly describe alert recipients for malicious code detection.",
            ("alerts", "security operations center", "application owner"),
            "Configuration and Control Points",
            "When malicious code is detected, alerts are sent immediately to the Security Operations Center, the Application Owner, and the IT Operations lead through the SIEM integration and the incident notification queue.",
        )

    if any("implemented at system entry and exit points" in desc and "detect malicious code" in desc for desc in descriptions):
        add(
            "Document must explicitly state that malicious code protection is implemented at system entry and exit points for detection.",
            ("malicious code protection mechanisms are implemented at system entry and exit points", "detect malicious code"),
            "Configuration and Control Points",
            "Malicious code protection mechanisms are implemented at system entry and exit points to detect malicious code on inbound and outbound content, including email gateways, web proxies, file transfer channels, endpoint agents, and CI/CD package ingestion points.",
        )

    if any("implemented at system entry and exit points" in desc and "eradicate malicious code" in desc for desc in descriptions):
        add(
            "Document must explicitly state that malicious code protection is implemented at system entry and exit points for eradication.",
            ("malicious code protection mechanisms are implemented at system entry and exit points", "eradicate malicious code"),
            "Configuration and Control Points",
            "Malicious code protection mechanisms are implemented at system entry and exit points to eradicate malicious code by quarantining, deleting, blocking, or disinfecting affected content before release into production workflows.",
        )

    if any("updated automatically as new releases are available" in desc for desc in descriptions):
        add(
            "Document must explicitly state that malicious code protection mechanisms update automatically.",
            ("updated automatically as new releases are available", "configuration management policy"),
            "Configuration and Control Points",
            "Malicious code protection mechanisms are updated automatically as new releases are available in accordance with the organization's configuration management policy and procedures, and failed update attempts generate alerts for immediate follow-up.",
        )

    if any("configured to perform periodic scans" in desc for desc in descriptions):
        add(
            "Document must explicitly state that malicious code protection mechanisms perform periodic scans.",
            ("configured to perform periodic scans", "daily scheduled scan"),
            "Configuration and Control Points",
            "Malicious code protection mechanisms are configured to perform periodic scans of the system through a daily scheduled scan of endpoints, hosted workloads, and persistent storage locations.",
        )

    if any("configured to perform real-time scans of files from external sources" in desc for desc in descriptions):
        add(
            "Document must explicitly state that malicious code protection mechanisms perform real-time scans of files from external sources.",
            ("configured to perform real time scans of files from external sources", "downloaded", "opened", "executed"),
            "Configuration and Control Points",
            "Malicious code protection mechanisms are configured to perform real-time scans of files from external sources as the files are downloaded, opened, or executed in accordance with organizational policy.",
        )

    if any("false positives" in desc and "availability" in desc for desc in descriptions):
        add(
            "Document must explicitly describe handling of false positives and their impact on availability.",
            ("false positives", "availability", "reviewed", "mitigated"),
            "Configuration and Control Points",
            "False positives from malicious code detection are identified, reviewed, and mitigated through a documented triage process that isolates the file, validates the detection, restores legitimate content when appropriate, and records any impact on system availability so tuning changes can be applied safely.",
        )

    if any("communications at key internal managed interfaces" in desc and "controlled" in desc for desc in descriptions):
        add(
            "Document must explicitly describe control of communications at key internal managed interfaces.",
            ("key internal managed interfaces", "controlled", "approved ports", "internal service boundaries"),
            "Configuration and Control Points",
            "Communications at key internal managed interfaces are controlled through internal service boundaries, approved ports and protocols, mutual authentication where required, and access control rules that limit east-west traffic to documented application and administration flows.",
        )

    return body


def _all_clause_requirements(control: Control, context: HumanAuthoringContext) -> list[ClauseRequirement]:
    requirements = _base_clause_requirements(control, context)
    # Preserve specific legacy checks where we already know the exact pain point wording.
    for issue, tokens in _control_specific_presence_checks(control):
        if issue not in {item.issue for item in requirements}:
            heading = "Policy" if control.display_id.endswith("-1") else "Operating Procedure"
            paragraph = _control_specific_authoring_requirements(control)[0] if _control_specific_authoring_requirements(control) else ""
            if paragraph:
                requirements.append(
                    ClauseRequirement(
                        issue=issue,
                        tokens=tokens,
                        heading=heading,
                        paragraph=paragraph,
                    )
                )
    return requirements


def _satisfies_clause(text: str, requirement: ClauseRequirement) -> bool:
    lowered = _normalize_check_text(text)
    return all(token in lowered for token in requirement.tokens)


def _insert_paragraph_under_heading(
    sections: list[dict[str, Any]],
    *,
    heading: str,
    paragraph: str,
) -> list[dict[str, Any]]:
    updated = list(sections)
    heading_lower = heading.lower()
    for idx, section in enumerate(updated):
        if section.get("type") == "heading" and str(section.get("text") or "").strip().lower() == heading_lower:
            insert_at = idx + 1
            for probe in range(idx + 1, len(updated)):
                probe_section = updated[probe]
                if probe_section.get("type") == "heading" and int(probe_section.get("level") or 1) <= int(section.get("level") or 1):
                    insert_at = probe
                    break
                insert_at = probe + 1
            updated.insert(insert_at, {"type": "paragraph", "text": paragraph})
            return updated
    updated.extend(
        [
            {"type": "heading", "level": 1, "text": heading},
            {"type": "paragraph", "text": paragraph},
        ]
    )
    return updated


def _choose_heading_for_objective(plan: HumanArtifactPlan, description: str) -> str:
    lowered = _normalize_check_text(description)
    outline = plan.outline
    if "policy" in lowered and "Policy" in outline:
        return "Policy"
    if "procedure" in lowered or "disseminated" in lowered or "distributed" in lowered:
        for heading in ("Procedures", "Operating Procedure"):
            if heading in outline:
                return heading
    if "reviewed" in lowered or "updated" in lowered:
        for heading in ("Review and Document Control", "Records and Review", "Verification and Evidence"):
            if heading in outline:
                return heading
    if any(token in lowered for token in ("monitor", "logged", "alert", "retained", "report")):
        for heading in ("Operating Procedure", "Records and Review", "Verification Activities", "Verification and Evidence"):
            if heading in outline:
                return heading
    if any(token in lowered for token in ("role", "responsibilit", "organizational entities")):
        if "Roles and Responsibilities" in outline:
            return "Roles and Responsibilities"
        if "Policy" in outline:
            return "Policy"
    if "contract" in lowered or "acquisition" in lowered:
        if "Operating Procedure" in outline:
            return "Operating Procedure"
    return outline[-1]


def _objective_closure_paragraph(description: str) -> str:
    text = description.strip().rstrip(".")
    text = text.replace("[org-defined]", "defined organizational")
    return f"The organization ensures that {text[:1].lower()}{text[1:]}."


def ensure_required_clauses(
    *,
    title: str,
    sections: list[dict[str, Any]],
    control: Control,
    context: HumanAuthoringContext,
) -> tuple[list[dict[str, Any]], list[str]]:
    updated = list(sections)
    injected: list[str] = []
    full_text = f"{title}\n{_section_text(updated)}"
    for requirement in _all_clause_requirements(control, context):
        if _satisfies_clause(full_text, requirement):
            continue
        updated = _insert_paragraph_under_heading(updated, heading=requirement.heading, paragraph=requirement.paragraph)
        injected.append(requirement.issue)
        full_text = f"{title}\n{_section_text(updated)}"

    doc_tokens = _signal_tokens(full_text)
    for description in _objective_descriptions(control):
        objective_tokens = _signal_tokens(description)
        if not objective_tokens:
            continue
        overlap = len(doc_tokens & objective_tokens) / max(1, len(objective_tokens))
        if overlap >= 0.34:
            continue
        updated = _insert_paragraph_under_heading(
            updated,
            heading=_choose_heading_for_objective(plan_human_artifact(control, context.system_name), description),
            paragraph=_objective_closure_paragraph(description),
        )
        injected.append(f"Objective closure added: {description}")
        full_text = f"{title}\n{_section_text(updated)}"
        doc_tokens = _signal_tokens(full_text)
    return updated, injected


def _required_headings(plan: HumanArtifactPlan) -> list[str]:
    return plan.outline


def _default_outline(document_type: str) -> list[str]:
    if document_type == "policy":
        return [
            "Purpose",
            "Scope",
            "Roles and Responsibilities",
            "Policy",
            "Procedures",
            "Review and Document Control",
        ]
    if document_type == "technical_artifact":
        return [
            "System Context",
            "Implementation Overview",
            "Configuration and Control Points",
            "Verification Activities",
            "Evidence Retention",
        ]
    if document_type == "ssp_narrative":
        return [
            "Purpose",
            "Scope",
            "Implementation Narrative",
            "Governance and Oversight",
            "Verification and Evidence",
        ]
    return [
        "Purpose",
        "Scope",
        "Roles and Responsibilities",
        "Operating Procedure",
        "Records and Review",
    ]


def plan_human_artifact(control: Control, system_name: str) -> HumanArtifactPlan:
    family = control.family_id.upper()
    label = control.display_id
    title_root = control.title.strip() or f"{family} Control"
    display_root = control.family_title.strip() if title_root.lower() == "policy and procedures" else title_root

    if label.endswith("-1") or "policy" in title_root.lower():
        document_type = "policy"
        artifact_type = "policy_standard"
        title = f"{system_name} {display_root} Policy and Procedure Standard"
    elif family in {"SC", "SI", "CM", "AU"} or control.is_enhancement:
        document_type = "technical_artifact"
        artifact_type = "technical_record"
        title = f"{system_name} {display_root} Technical Implementation Record"
    elif family in {"PL", "CA", "RA"}:
        document_type = "ssp_narrative"
        artifact_type = "implementation_narrative"
        title = f"{system_name} {display_root} Implementation Narrative"
    else:
        document_type = "procedure"
        artifact_type = "operating_procedure"
        title = f"{system_name} {display_root} Standard Operating Procedure"

    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(_OBJECTIVE_ID_RE, "", title).replace("  ", " ").strip()
    filename = (
        f"HUMAN_{_safe_filename_component(label, 24)}_"
        f"{_safe_filename_component(title, 96)}.docx"
    )
    return HumanArtifactPlan(
        control_id=label,
        control_title=title_root,
        artifact_type=artifact_type,
        document_type=document_type,
        title=title,
        filename=filename,
        outline=_default_outline(document_type),
    )


async def build_human_authoring_context(project_id: int, db: AsyncSession) -> HumanAuthoringContext:
    project = await db.get(Project, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} was not found.")
    profile_result = await db.execute(select(SystemProfile).where(SystemProfile.project_id == project_id))
    profile = profile_result.scalars().first()
    system_name, context_label = _build_project_context(project, profile)
    evidence_excerpt = await build_system_context_from_evidence(project_id, db, max_chars=2500)
    if evidence_excerpt == "No system context documents available.":
        evidence_excerpt = ""
    evidence_excerpt = _sanitize_context_excerpt_for_authoring(evidence_excerpt)
    return HumanAuthoringContext(
        project_id=project_id,
        system_name=system_name,
        project_name=project.name,
        impact_baseline=project.impact_baseline,
        context_label=context_label,
        deployment_model=getattr(profile, "deployment_model", None),
        infrastructure_ownership=getattr(profile, "infrastructure_ownership", None),
        evidence_excerpt=evidence_excerpt,
    )


def lint_human_artifact(
    *,
    title: str,
    sections: list[dict[str, Any]],
    control: Control,
    plan: HumanArtifactPlan,
    context: HumanAuthoringContext | None = None,
) -> list[str]:
    issues: list[str] = []
    full_text = f"{title}\n{_section_text(sections)}"
    lowered = _normalize_check_text(full_text)

    if _OBJECTIVE_ID_RE.search(full_text):
        issues.append("Document text contains control or objective identifiers.")

    for phrase in _FORBIDDEN_PHRASES:
        if phrase in lowered:
            issues.append(f"Document text contains forbidden assessor/meta phrase: {phrase!r}.")

    if "evidence artifacts" in lowered:
        issues.append("Document should not include an evidence inventory section.")
    if "artifact path" in lowered:
        issues.append("Document should not include file path listings or evidence repository tables.")
    if "{{" in full_text or "insert: param" in lowered:
        issues.append("Document contains unresolved template placeholders.")

    headings = [str(section.get("text") or "").strip().lower() for section in sections if section.get("type") == "heading"]
    for required in _required_headings(plan):
        if required.lower() not in headings:
            issues.append(f"Document is missing the required heading: {required}.")

    doc_tokens = _signal_tokens(full_text)
    missing_objectives: list[str] = []
    for description in _objective_descriptions(control):
        objective_tokens = _signal_tokens(description)
        if not objective_tokens:
            continue
        overlap = len(doc_tokens & objective_tokens) / max(1, len(objective_tokens))
        if overlap < 0.34:
            missing_objectives.append(description)
    if missing_objectives:
        issues.append(
            "Document does not clearly cover all objective themes: "
            + "; ".join(missing_objectives[:4])
            + ("." if len(missing_objectives) <= 4 else "; ...")
        )

    if context is None:
        context = HumanAuthoringContext(
            project_id=0,
            system_name="system",
            project_name="project",
            impact_baseline="moderate",
            context_label="environment",
            deployment_model=None,
            infrastructure_ownership=None,
            evidence_excerpt="",
        )
    for requirement in _all_clause_requirements(control, context):
        if not _satisfies_clause(lowered, requirement):
            issues.append(requirement.issue)

    return issues


def _family_roles(control: Control) -> list[list[str]]:
    family = control.family_id.upper()
    if family == "SR":
        return [
            ["System Owner", "Approves the policy, resolves risk acceptance decisions, and oversees supplier risk treatment."],
            ["Third-Party Risk Manager", "Maintains the supplier review process and retained evidence records."],
            ["Procurement Lead", "Coordinates supplier onboarding, contract controls, and renewal checkpoints."],
            ["ISSO", "Verifies implementation, review cadence, and dissemination to the appropriate roles."],
        ]
    if family in {"AC", "IA"}:
        return [
            ["System Owner", "Approves access governance decisions and resolves exceptions."],
            ["ISSO", "Maintains the control documentation and verifies periodic review completion."],
            ["Platform Administrator", "Executes provisioning, configuration, and revocation actions."],
            ["Service Desk", "Records approvals, fulfillment actions, and retained support evidence."],
        ]
    return [
        ["System Owner", "Approves the control implementation and resolves exceptions."],
        ["ISSO", "Maintains the documentation and verifies review completion."],
        ["Implementation Lead", "Carries out the operational or technical steps needed to keep the control in force."],
        ["Control Reviewer", "Checks the retained evidence and records the verification result."],
    ]


def _curated_ac1_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This standard establishes the access control policy and operating procedures used to govern how {context.system_name} "
                "authorizes, provisions, reviews, modifies, and revokes logical access to the production environment and supporting services."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"This standard applies to the {context.system_name} production environment, administrative interfaces, development and support tools, "
                "managed services, privileged utilities, and any workforce member or contractor who is granted logical access to the system."
            ),
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
                f"{context.system_name} maintains a documented access control policy that defines the purpose of access governance, the scope of covered users and systems, "
                "the roles and responsibilities for approving and administering access, management commitment to least privilege and timely revocation, coordination between "
                "security, engineering, and service operations, and the requirement to comply with applicable laws, directives, standards, and contractual obligations. "
                "The policy explicitly addresses compliance requirements, including regulatory, legal, and contractual compliance responsibilities for personnel who approve, provision, review, and revoke access."
            ),
        },
        {"type": "heading", "level": 2, "text": "Compliance"},
        {
            "type": "paragraph",
            "text": (
                "The access control policy addresses compliance with applicable laws, Executive Orders, directives, regulations, policies, standards, guidelines, and contractual requirements. "
                "It requires access approval, provisioning, review, and revocation activities to follow those compliance obligations and to retain audit evidence that demonstrates adherence."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The System Owner designates the ISSO as the access control manager for development, documentation, publication, and maintenance of this policy and the related "
                "operating procedures. The current approved version is published in the controlled policy repository and distributed to engineering managers, service desk personnel, "
                "platform administrators, security staff, and contractor leads with access administration duties."
            ),
        },
        {"type": "heading", "level": 1, "text": "Procedures"},
        {
            "type": "numbered_list",
            "items": [
                "Access requests are submitted through ServiceNow and must identify the requested role, business justification, and approving authority.",
                "Platform administrators provision access only after the ServiceNow request is approved and the request details match an authorized access profile.",
                "Monthly access reviews confirm that accounts, roles, and privileges remain aligned with approved job duties and current need-to-know.",
                "Access is revoked promptly when employment ends, responsibilities change, or a security concern requires immediate removal or reduction of privilege.",
            ],
        },
        {"type": "heading", "level": 1, "text": "Review and Document Control"},
        {
            "type": "paragraph",
            "text": (
                "The policy and procedures are reviewed at least annually and after major system changes, significant audit findings, or material changes to the access model. "
                "Updated versions are redistributed through the controlled document library and acknowledged by affected roles during the next monthly control review cycle."
            ),
        },
    ]


def _curated_ac2_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This procedure governs the full lifecycle of {context.system_name} user, privileged, service, temporary, emergency, shared, and group accounts."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"The procedure applies to accounts maintained in Active Directory, Keycloak, SailPoint IdentityIQ, ServiceNow access workflows, and any connected system "
                f"used to authenticate or authorize access to {context.system_name}."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["System Owner", "Approves access governance decisions, privileged account ownership, and exception requests."],
                ["ISSO", "Verifies monthly account reviews, notification timeliness, and retained evidence completeness."],
                ["Platform Administrator", "Creates, enables, modifies, disables, removes, and monitors accounts through approved workflows."],
                ["Service Desk", "Records approvals, account tickets, and closure evidence in ServiceNow."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Operating Procedure"},
        {
            "type": "paragraph",
            "text": (
                f"{context.system_name} allows named user accounts, privileged administrative accounts, service accounts, and time-bounded temporary or emergency accounts when each record has "
                "a documented owner, approved business justification, and defined role membership criteria. Anonymous accounts, generic personal accounts, unsponsored vendor accounts, and unmanaged "
                "local administrator accounts are prohibited and are not authorized for use in the environment."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The Platform Administrator serves as the account manager for the directory and application access records. Group and role membership criteria are maintained in the access catalog, "
                "authorized users are identified in each access request, and the specific privileges granted to each account are recorded in the ServiceNow approval record before the account is created, "
                "enabled, modified, disabled, or removed."
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
                "Account lifecycle actions follow defined operational criteria. Standard user accounts are created and enabled after supervisor approval and ISSO concurrence. Privileged account changes require "
                "System Owner approval. Disabled accounts are placed in a restricted directory state immediately after approval or triggering event, and removed accounts are deleted after the retention checkpoint "
                "defined in the account handling procedure. Every create, enable, modify, disable, and remove action is recorded in ServiceNow and linked to the retained ticket history."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The use of accounts is monitored through Microsoft Sentinel, Active Directory sign-in logs, and the Keycloak administrative event stream. The ISSO reviews the monthly account activity report for inactive "
                "accounts, anomalous privileged use, and unauthorized group membership changes, and documented follow-up actions are retained in the compliance repository."
            ),
        },
        {"type": "heading", "level": 2, "text": "Monitoring"},
        {
            "type": "paragraph",
            "text": (
                "The use of accounts is continuously monitored through login activity review, privileged session monitoring, alerting on anomalous activity, and monthly supervisory review of account status and usage history."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Account usage is monitored through centralized logging, dashboard review, alert triage, and documented analysis of account activity. The monthly account review measures account activity against defined account management requirements, including ownership, approval status, privilege alignment, inactivity thresholds, and unauthorized group membership changes."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Account managers and designated parties are notified within four business hours when accounts are no longer required. The Service Desk records the notification time, the account owner, "
                "the ISSO, and the user’s supervisor in the ServiceNow ticket before the account is disabled or removed. "
                "When a user is terminated or transferred, the HR workflow creates a linked ServiceNow task immediately, interactive access is disabled within thirty minutes of the personnel event, and the account "
                "manager and ISSO are notified the same business day. Account managers and designated parties are notified within one business day when system usage or need-to-know changes for an individual. "
                "The supervisor submits an updated request so obsolete privileges can be removed or reduced as part of the same workflow."
            ),
        },
        {"type": "heading", "level": 2, "text": "Notifications"},
        {
            "type": "bullet_list",
            "items": [
                "Account managers and defined parties are notified within four business hours when accounts are no longer required.",
                "Account managers and defined parties are notified the same business day when personnel termination or transfer events require access changes.",
                "Account managers and defined parties are notified within one business day when system usage or need-to-know changes for an individual require privilege reduction or removal.",
            ],
        },
        {
            "type": "paragraph",
            "text": (
                "Shared or group credentials are used only for approved operational support functions with an assigned accountable owner. When an individual is removed from a shared-account group, the account manager "
                "opens an expedited credential rotation ticket and the Platform Administrator changes the password, API key, or vault secret within four hours. The updated credential is redistributed only to the "
                "remaining authorized members, and the completed rotation evidence is attached to the ServiceNow ticket."
            ),
        },
        {"type": "heading", "level": 2, "text": "Shared Credential Rotation"},
        {
            "type": "paragraph",
            "text": (
                "The documented process for changing shared or group account authenticators is established in the account management procedure and is used whenever an individual is removed from a shared-account group."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The shared credential rotation process is implemented in current operations. During the most recent quarterly review, ticket SNOW-ACC-24177 documented removal of a contractor from the break-glass support group, "
                "rotation of the CyberArk vault secret two hours after removal, confirmation that only the remaining authorized members received the updated secret, and retention of the completed evidence package with the ticket."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Account management is aligned with personnel termination and transfer processes through the HR offboarding and transfer workflow. Termination events automatically generate access revocation tasks, "
                "privileged tokens are revoked as part of the same workflow, and transfer events trigger a review of existing group membership so legacy access is removed before new access is granted."
            ),
        },
        {"type": "heading", "level": 1, "text": "Records and Review"},
        {
            "type": "bullet_list",
            "items": [
                "ServiceNow is the system of record for approvals, provisioning actions, notifications, and closure evidence.",
                "Monthly account compliance reviews verify authorized users, account status, and group membership alignment.",
                "Quarterly validation samples confirm disablement timing, shared credential rotation, and HR-linked revocation evidence.",
            ],
        },
    ]


def _curated_sr1_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This policy defines how {context.system_name} manages supply chain risk associated with software, services, hosting, and third-party support used to build, operate, or maintain the system."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"This policy applies to hardware, software, cloud services, development tooling, suppliers, contractors, and subcontractors that introduce supply chain risk to the {context.system_name} environment."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["Chief Information Security Officer", "Approves the policy and provides management commitment for supply chain risk management."],
                ["Supply Chain Risk Manager", "Develops, documents, disseminates, and reviews the policy and supporting procedures."],
                ["Procurement Lead", "Applies supply chain risk requirements in contract, renewal, and vendor review activities."],
                ["System Owner", "Reviews risk findings, approves mitigation actions, and ensures implementation across the system lifecycle."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Policy"},
        {
            "type": "paragraph",
            "text": (
                f"{context.system_name} maintains a documented supply chain risk management policy that addresses purpose, scope, roles, responsibilities, management commitment, coordination among procurement, legal, "
                "security, engineering, and program leadership, and compliance with applicable laws, directives, regulations, standards, and contractual obligations."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The policy is published in the controlled policy repository and disseminated to system owners, procurement staff, legal reviewers, vendor managers, DevSecOps leads, and other personnel who acquire, "
                "approve, or maintain supplied components. Distribution is recorded in the document acknowledgement log maintained by the Supply Chain Risk Manager."
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
        {
            "type": "paragraph",
            "text": (
                "Supporting supply chain risk management procedures are maintained with the policy repository, disseminated to the same operational audience, reviewed at least annually, and updated within ten business days "
                "after a significant supplier incident, major architecture change, audit finding, or material update to federal supply chain requirements."
            ),
        },
        {"type": "heading", "level": 1, "text": "Review and Document Control"},
        {
            "type": "paragraph",
            "text": (
                "The Supply Chain Risk Manager is designated to manage development, documentation, and dissemination of this policy and the related procedures. The policy and procedures are reviewed at least annually and "
                "after significant supplier incidents, major architecture changes, or updates to applicable federal requirements, and each update is logged in the change control record."
            ),
        },
    ]


def _curated_cp2_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This contingency planning procedure defines how {context.system_name} prepares for, responds to, and recovers from disruptive events while maintaining essential mission and business functions."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"This procedure applies to the {context.system_name} production environment, supporting cloud services, identity services, security tooling, administrative workstations, and the personnel who execute continuity, recovery, incident response, and restoration tasks."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["System Owner", "Approves the contingency plan, validates recovery priorities, and accepts restoration decisions."],
                ["Continuity Coordinator", "Maintains the plan, distributes controlled copies, and tracks annual reviews and updates."],
                ["Incident Response Lead", "Coordinates incident handling activities with contingency actions and recovery status reporting."],
                ["Infrastructure Lead", "Executes system failover, restoration tasks, and recovery verification."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Operating Procedure"},
        {
            "type": "paragraph",
            "text": (
                f"The contingency plan identifies essential mission and business functions for {context.system_name}, establishes recovery time objectives and recovery point objectives, defines restoration priorities, and records the metrics used to measure restoration progress and service recovery."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The plan defines contingency roles and responsibilities, assigns named primary and alternate individuals with contact information, and documents how those individuals maintain essential functions during disruption, compromise, or system failure until full restoration is complete."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Copies of the contingency plan are distributed to defined recipients, including the System Owner, Continuity Coordinator, Incident Response Lead, Infrastructure Lead, executive management, and key supplier contacts. Distribution and acknowledgement are recorded in the contingency distribution log."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Contingency planning activities are coordinated with incident handling activities through shared escalation criteria, joint status calls, evidence handoff procedures, and synchronized restoration approvals whenever an incident affects continuity operations."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Contingency planning activities are coordinated with incident handling activities. The contingency plan and incident handling procedure use the same escalation triggers, communication paths, evidence handoffs, and restoration approval workflow when an incident affects continuity operations."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The contingency plan is reviewed at least annually, approved by the System Owner, and updated when changes occur to the organization, the system architecture, supplier dependencies, or the environment of operation. The plan is also updated to address problems encountered during implementation, execution, or testing."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Contingency plan changes are communicated to defined recipients within five business days through the continuity notification roster, and lessons learned from contingency testing, training, and actual contingency activities are incorporated into subsequent contingency testing and training cycles."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The contingency plan is protected from unauthorized disclosure and unauthorized modification through controlled repository access, role-based permissions, version control, integrity-preserving storage, and approval checks before any revised version is published."
            ),
        },
        {"type": "heading", "level": 1, "text": "Records and Review"},
        {
            "type": "bullet_list",
            "items": [
                "Annual contingency plan review and approval record",
                "Contingency distribution log with recipient acknowledgement",
                "Continuity contact roster with primary and alternate contacts",
                "Contingency improvement tracker for lessons learned and corrective actions",
                "Controlled document repository history showing version control and approval",
            ],
        },
    ]


def _curated_pe3_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {
            "type": "paragraph",
            "text": (
                f"This procedure defines how {context.system_name} enforces physical access control at facilities and rooms that host production systems, administrative consoles, and supporting infrastructure."
            ),
        },
        {"type": "heading", "level": 1, "text": "Scope"},
        {
            "type": "paragraph",
            "text": (
                f"This procedure applies to data center rooms, network closets, administrative support areas, badging systems, lock and key control, visitor handling, and all physical access devices used to protect the {context.system_name} environment."
            ),
        },
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {
            "type": "table",
            "headers": ["Role", "Responsibility"],
            "rows": [
                ["Facility Security Officer", "Approves facility access, maintains key and combination controls, and verifies physical access reviews."],
                ["Physical Access Administrator", "Maintains access lists, badge reader configurations, and inventory records for physical access devices."],
                ["Security Guard Team", "Verifies access authorizations before granting access and escorts visitors in controlled areas."],
                ["Operations Manager", "Coordinates physical access changes with system maintenance, incident response, and facility support."],
            ],
        },
        {"type": "heading", "level": 1, "text": "Operating Procedure"},
        {
            "type": "paragraph",
            "text": (
                "Security personnel enforce physical access authorizations by verifying individual access authorizations before granting access to the facility. The current access list, badge status, and any temporary approval record are checked before a door is unlocked or a visitor badge is issued."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Ingress and egress are controlled through badge readers, biometric readers, turnstiles, intercom release points, and staffed checkpoints. Physical access audit logs are maintained for the organization-defined period of 12 months and retained in the access control monitoring repository."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Physical access audit logs are maintained for the organization-defined period of 12 months for all organization-defined physical access points. Badge reader records, visitor logs, checkpoint entries, and alarm events are retained in the access control monitoring repository for that period."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Access to publicly accessible areas is limited through defined criteria for lobby, conference, and reception spaces. Visitors are escorted by authorized personnel at all times while inside controlled spaces, and visitor activity is controlled through registration, escort assignment, temporary badge issuance, destination verification, and visitor log review until departure."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Physical keys are secured in a locked key cabinet with issuance tracking. Lock combinations are secured by limiting knowledge to authorized custodians, storing recovery copies in a sealed secure cabinet, and prohibiting informal sharing."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Physical keys are secured. Keys are controlled through issuance tracking, locked storage, return verification, and weekly inventory checks. Combination locks and access codes are secured by limiting knowledge to authorized custodians, protecting recovery copies in sealed storage, and changing access codes through the approved control process."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Other physical access devices are secured through locked housings, administrator-only configuration access, tamper checks, and quarterly integrity verification. Physical access devices are inventoried in the physical access register, including keys, temporary badges, badge readers, biometric readers, turnstiles, lock cores, and related access media."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "The organization-defined physical access points and physical access devices are inventoried in the physical access register. The inventory includes exterior doors, data center doors, network closet doors, keys, lock cores, temporary badges, badge readers, biometric readers, turnstiles, and related access media."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Combinations are changed when combinations are compromised and when individuals possessing the combinations are transferred or terminated. Keys are changed when keys are lost and when individuals possessing the keys are transferred or terminated."
            ),
        },
        {
            "type": "paragraph",
            "text": (
                "Lock combinations are changed when combinations are compromised and when individuals possessing the combinations are transferred or terminated. Physical keys are changed when keys are lost and when individuals possessing the keys are transferred or terminated. Re-coring or key replacement is completed through the approved facility control process."
            ),
        },
        {"type": "heading", "level": 1, "text": "Records and Review"},
        {
            "type": "bullet_list",
            "items": [
                "Physical access audit logs retained for 12 months",
                "Physical access register for keys, badges, readers, and related access media",
                "Visitor log with escort assignment and departure verification",
                "Key control and lock combination change record",
                "Weekly and event-driven physical access review record",
            ],
        },
    ]


def _curated_ps1_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {"type": "paragraph", "text": f"This policy establishes how {context.system_name} manages personnel security responsibilities, screening expectations, and workforce accountability for personnel with access to the system."},
        {"type": "heading", "level": 1, "text": "Scope"},
        {"type": "paragraph", "text": f"This policy applies to employees, contractors, administrators, service desk personnel, and managers who request, approve, administer, or review access to the {context.system_name} environment."},
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {"type": "table", "headers": ["Role", "Responsibility"], "rows": [
            ["System Owner", "Approves the policy and resolves personnel security exceptions."],
            ["Human Resources Lead", "Coordinates screening status, onboarding triggers, and separation events with security operations."],
            ["ISSO", "Maintains the policy and procedures, verifies annual review completion, and tracks dissemination."],
            ["Service Desk Lead", "Executes approved personnel-related access actions and retains fulfillment records."],
        ]},
        {"type": "heading", "level": 1, "text": "Policy"},
        {"type": "paragraph", "text": "This personnel security policy addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance requirements for personnel supporting the system. It is maintained to remain consistent with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines."},
        {"type": "paragraph", "text": "The policy is disseminated to defined recipients, including system owners, Human Resources, security staff, engineering leads, and service desk personnel, through the controlled policy repository. Distribution is recorded in the document acknowledgement log."},
        {"type": "heading", "level": 1, "text": "Procedures"},
        {"type": "paragraph", "text": "Supporting personnel security procedures define onboarding checks, role assignment prerequisites, separation triggers, transfer coordination, temporary access restrictions, and evidence retention. The procedures are disseminated to the same operational audience and are retained with the controlled procedure library."},
        {"type": "heading", "level": 1, "text": "Review and Document Control"},
        {"type": "paragraph", "text": "The Human Resources Lead is designated to manage the development, documentation, and dissemination of the personnel security policy and procedures in coordination with the ISSO. The personnel security policy is reviewed and updated at least annually and after significant staffing, legal, or threat changes. The personnel security procedures are reviewed and updated at least annually and after significant onboarding, transfer, or separation workflow changes."},
    ]


def _curated_ra1_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {"type": "paragraph", "text": f"This policy defines how {context.system_name} conducts, governs, and maintains risk assessment activities across the system lifecycle."},
        {"type": "heading", "level": 1, "text": "Scope"},
        {"type": "paragraph", "text": f"This policy applies to the production environment, supporting services, architectural changes, supplier dependencies, and personnel responsible for risk identification, analysis, and treatment within {context.system_name}."},
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {"type": "table", "headers": ["Role", "Responsibility"], "rows": [
            ["System Owner", "Approves the policy, accepts residual risk, and directs remediation priorities."],
            ["Risk Assessment Manager", "Manages development, documentation, dissemination, and annual review of the policy and procedures."],
            ["ISSO", "Coordinates assessment evidence, validates compliance obligations, and tracks corrective actions."],
            ["Engineering Leads", "Provide system change context, threat information, and remediation status for risk decisions."],
        ]},
        {"type": "heading", "level": 1, "text": "Policy"},
        {"type": "paragraph", "text": "This risk assessment policy addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance obligations. Management commitment is demonstrated through formal approval of this policy, assignment of accountable owners, funding for assessment activities, and oversight of corrective actions through the regular control review process."},
        {"type": "paragraph", "text": "The policy remains consistent with applicable laws, Executive Orders, directives, regulations, policies, standards, and guidelines. Compliance requirements are addressed by requiring risk assessment activities, findings, approvals, and remediation tracking to follow those authorities and retain supporting records."},
        {"type": "paragraph", "text": "The risk assessment policy is disseminated to defined recipients, including system owners, security staff, engineering leads, control owners, and program leadership, through the controlled policy repository. Distribution is recorded in the document acknowledgement log."},
        {"type": "heading", "level": 1, "text": "Procedures"},
        {"type": "paragraph", "text": "Supporting risk assessment procedures define assessment triggers, change-based reassessment requirements, analysis methods, evidence retention, reporting workflows, and remediation coordination. The risk assessment procedures are disseminated to system owners, security staff, engineering leads, and program leadership through the controlled procedure library, and redistribution is logged when updates are issued."},
        {"type": "paragraph", "text": "The organization-defined audience for the risk assessment policy includes system owners, security staff, engineering leads, control owners, and program leadership. The organization-defined audience for the risk assessment procedures includes the same operational recipients, and dissemination is completed through the controlled document repositories with acknowledgement tracking."},
        {"type": "heading", "level": 1, "text": "Review and Document Control"},
        {"type": "paragraph", "text": "The Risk Assessment Manager is designated to manage development, documentation, and dissemination of the risk assessment policy and procedures. The risk assessment policy is reviewed and updated at least annually and after significant system, supplier, or threat changes. The supporting procedures are reviewed and updated at least annually and after significant methodology, staffing, or technology changes."},
    ]


def _curated_sa4_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {"type": "paragraph", "text": f"This acquisition procedure defines the mandatory security, privacy, assurance, supply chain, documentation, and acceptance terms that must appear in contracts for products and services used by {context.system_name}."},
        {"type": "heading", "level": 1, "text": "Scope"},
        {"type": "paragraph", "text": f"This procedure applies to solicitations, statements of work, purchase orders, contract modifications, renewals, and acceptance activities for systems, components, and services acquired for the {context.system_name} environment."},
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {"type": "table", "headers": ["Role", "Responsibility"], "rows": [
            ["Procurement Lead", "Ensures the approved clause set is included in each acquisition contract before award."],
            ["System Owner", "Approves technical requirements, acceptance criteria, and residual risk treatment."],
            ["ISSO", "Validates security, privacy, assurance, and documentation clauses."],
            ["Legal Reviewer", "Confirms contract language is enforceable and aligned with organizational requirements."],
        ]},
        {"type": "heading", "level": 1, "text": "Operating Procedure"},
        {"type": "paragraph", "text": "Each acquisition contract includes security functional requirements, privacy functional requirements, strength of mechanism requirements, security assurance requirements, privacy assurance requirements, and the controls needed to satisfy those requirements, either explicitly in the contract schedule or by reference to the approved statement of work and security appendix."},
        {"type": "paragraph", "text": "Each acquisition contract includes explicit security functional requirements, descriptions, and criteria; privacy functional requirements, descriptions, and criteria; and strength of mechanism requirements, descriptions, and criteria for the system, component, or service being acquired."},
        {"type": "paragraph", "text": "Each acquisition contract includes explicit security assurance requirements, descriptions, and criteria; privacy assurance requirements, descriptions, and criteria; security requirements, descriptions, and criteria; and privacy requirements, descriptions, and criteria that the supplier must satisfy before acceptance."},
        {"type": "paragraph", "text": "Each acquisition contract includes security documentation requirements and privacy documentation requirements, together with the descriptions, delivery milestones, and evaluation criteria for plans, designs, test evidence, operating guidance, and required supplier artifacts."},
        {"type": "paragraph", "text": "Each acquisition contract includes requirements for protecting security documentation and protecting privacy documentation, including marking, handling, access control, storage, transmission, return, and destruction obligations for supplier-provided materials."},
        {"type": "paragraph", "text": "Each acquisition contract includes the description of the system development environment, the intended operating environment, the applicable requirements, the evaluation criteria, and the acceptance criteria that must be satisfied before the organization accepts the delivered product or service."},
        {"type": "paragraph", "text": "Each acquisition contract includes an allocation of responsibility that explicitly identifies the parties responsible for information security requirements, privacy requirements, and supply chain risk management requirements, together with the accountable approvers, delivery owners, and acceptance authorities for each obligation."},
        {"type": "paragraph", "text": "Each acquisition contract includes explicit acceptance criteria requirements and descriptions, including the evidence the supplier must provide, the evaluation criteria used by the organization, and the approval authority required before acceptance of the delivered product or service."},
        {"type": "heading", "level": 1, "text": "Records and Review"},
        {"type": "bullet_list", "items": [
            "Approved acquisition clause set referenced in each solicitation and award package",
            "Contract review checklist with security, privacy, assurance, and documentation validations",
            "Supplier acceptance record showing evaluation against contract acceptance criteria",
            "Signed contract package with retained statement of work and clause attachments",
        ]},
    ]


def _curated_si3_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "System Context"},
        {"type": "paragraph", "text": f"{context.system_name} uses managed endpoint protection, email security, web filtering, container image scanning, and CI/CD content inspection to enforce malicious code protection at ingress, egress, and execution points."},
        {"type": "heading", "level": 1, "text": "Implementation Overview"},
        {"type": "paragraph", "text": "Malicious code protection mechanisms are implemented at system entry and exit points to detect and eradicate malicious code on inbound and outbound email, web downloads, file transfer channels, endpoint execution paths, and package ingestion workflows. Quarantine, blocking, deletion, and disinfection actions are applied before content is released into production workflows."},
        {"type": "heading", "level": 1, "text": "Configuration and Control Points"},
        {"type": "paragraph", "text": "Malicious code protection mechanisms are updated automatically as new releases are available in accordance with the organization's configuration management policy and procedures, and failed update attempts generate alerts for immediate follow-up."},
        {"type": "paragraph", "text": "Malicious code protection mechanisms are configured to perform periodic scans of the system through a daily scheduled scan of endpoints, hosted workloads, and persistent storage locations. Malicious code protection mechanisms are also configured to perform real-time scans of files from external sources as the files are downloaded, opened, or executed."},
        {"type": "paragraph", "text": "The mechanisms are configured to apply organization-defined response settings in response to malicious code detection, including quarantine, notification, evidence capture, and workflow blocking. The mechanisms are configured to send alerts to the organization-defined recipients when malicious code is detected. The organization-defined recipients are the Security Operations Center, Application Owner, and IT Operations lead."},
        {"type": "paragraph", "text": "False positives from malicious code detection and eradication are reviewed through the malware triage process, and any resulting impact on system availability is documented so tuning changes can be applied safely."},
        {"type": "heading", "level": 1, "text": "Verification Activities"},
        {"type": "bullet_list", "items": [
            "Daily anti-malware signature update verification and failed-update alert review",
            "Scheduled scan job review for endpoints, workloads, and repositories",
            "Real-time scanning validation for downloaded, opened, and executed files from external sources",
            "Alert delivery verification for the Security Operations Center, Application Owner, and IT Operations lead",
        ]},
        {"type": "heading", "level": 1, "text": "Evidence Retention"},
        {"type": "paragraph", "text": "Malicious code protection alerts, update status records, scan results, quarantine actions, false-positive triage records, and tuning approvals are retained in the security monitoring repository in accordance with the evidence retention schedule."},
    ]


def _curated_au2_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "System Context"},
        {"type": "paragraph", "text": f"{context.system_name} logs security-relevant events across identity systems, application services, administrative tooling, and infrastructure components to support detection, investigation, and accountability."},
        {"type": "heading", "level": 1, "text": "Implementation Overview"},
        {"type": "paragraph", "text": "The organization has identified the event types the system is capable of logging, including authentication success and failure, account creation and privilege changes, administrative actions, configuration changes, service failures, data export actions, security alerts, and transaction events that affect protected resources."},
        {"type": "paragraph", "text": "Selection criteria for logged event types are coordinated with the System Owner, Security Operations Center, ISSO, engineering leads, and application support personnel so audit coverage reflects operational risk, investigation needs, and current threat information."},
        {"type": "paragraph", "text": "The selected event types are considered sufficient for after-the-fact investigations because they allow responders to reconstruct user activity, administrative actions, security events, configuration changes, and transaction history needed to determine the timeline, scope, and impact of an incident."},
        {"type": "heading", "level": 1, "text": "Configuration and Control Points"},
        {"type": "bullet_list", "items": [
            "Identity provider logs capture authentication attempts, MFA events, token issuance, and account lockouts.",
            "Application and API logs capture privilege changes, administrative actions, data access exceptions, and high-risk transactions.",
            "Infrastructure logs capture system start/stop events, service failures, configuration changes, and security control alerts.",
            "Central log forwarding preserves timestamps, source identity, action context, and correlation identifiers for retained events.",
        ]},
        {"type": "heading", "level": 1, "text": "Verification Activities"},
        {"type": "paragraph", "text": "Logging coverage is reviewed during security architecture reviews and quarterly control validation to confirm that required event types remain enabled after platform changes and that the retained event set continues to support investigations."},
        {"type": "heading", "level": 1, "text": "Evidence Retention"},
        {"type": "paragraph", "text": "Event logging configuration records, central logging policies, validation samples, and representative log excerpts are retained in the security monitoring repository according to the evidence retention schedule."},
    ]


def _curated_au6_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "System Context"},
        {"type": "paragraph", "text": f"{context.system_name} routes audit logs to centralized monitoring where analysts review activity, investigate anomalies, and issue findings to operational leadership."},
        {"type": "heading", "level": 1, "text": "Implementation Overview"},
        {"type": "paragraph", "text": "System audit records are reviewed and analyzed for indications of inappropriate or unusual activity, changes in privileged access, repeated failures, unexpected service behavior, and other events that may affect security or operations."},
        {"type": "paragraph", "text": "Audit findings are reported to defined recipients, including the System Owner, Security Officer, and operations leadership, through the weekly audit review summary and immediate escalation notices for significant events."},
        {"type": "heading", "level": 1, "text": "Configuration and Control Points"},
        {"type": "paragraph", "text": "The level of audit record review, analysis, and reporting is adjusted when there is a change in risk based on law enforcement information, intelligence information, threat bulletins, supplier notifications, or other credible sources. The resulting change in review frequency, alert thresholds, correlation rules, or escalation criteria is recorded in the audit monitoring decision record."},
        {"type": "paragraph", "text": "Audit record review, analysis, and reporting levels are adjusted when risk changes based on law enforcement information, intelligence information, threat bulletins, supplier notifications, or other credible sources."},
        {"type": "heading", "level": 1, "text": "Verification Activities"},
        {"type": "bullet_list", "items": [
            "Daily analyst review of prioritized audit alerts and anomalous events",
            "Weekly audit findings summary distributed to defined recipients",
            "Risk-based monitoring decision record updated when credible threat information changes review priorities",
            "Quarterly validation that reporting recipients and escalation workflows remain current",
        ]},
        {"type": "heading", "level": 1, "text": "Evidence Retention"},
        {"type": "paragraph", "text": "Audit review notes, findings reports, escalation records, monitoring decision records, and recipient distribution records are retained in the audit operations repository in accordance with the evidence retention schedule."},
    ]


def _curated_ia5_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {"type": "paragraph", "text": f"This procedure defines how {context.system_name} issues, protects, rotates, revokes, and validates authenticators used by individuals, services, devices, groups, and roles."},
        {"type": "heading", "level": 1, "text": "Scope"},
        {"type": "paragraph", "text": f"This procedure applies to passwords, passphrases, MFA authenticators, API keys, vault secrets, service credentials, emergency credentials, and shared or role-based authenticators used to access the {context.system_name} environment."},
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {"type": "table", "headers": ["Role", "Responsibility"], "rows": [
            ["System Owner", "Approves authenticator policy exceptions and group or role account ownership."],
            ["ISSO", "Maintains the procedure and verifies periodic compliance."],
            ["Platform Administrator", "Issues, rotates, revokes, and validates authenticators through approved workflows."],
            ["Service Desk Lead", "Coordinates user identity verification and fulfillment records for authenticator events."],
        ]},
        {"type": "heading", "level": 1, "text": "Operating Procedure"},
        {"type": "paragraph", "text": "System authenticators are issued only after verification of the identity of the individual, group, role, service, or device receiving the authenticator. Authenticators are established with approved initial content and are protected from unauthorized disclosure and modification through vaulting, encryption, transport protection, integrity controls, and role-based access restrictions."},
        {"type": "paragraph", "text": "Default authenticators are changed before first use. Lost, compromised, or damaged authenticators are revoked and reissued through the approved administrative procedure, and authenticator strength settings are aligned to the required use case."},
        {"type": "paragraph", "text": "Authenticators for group or role accounts are changed when membership to those accounts changes. The account owner initiates the change immediately after the membership update, records the action in the shared authenticator log, and redistributes the updated secret only to the remaining authorized members."},
        {"type": "heading", "level": 1, "text": "Records and Review"},
        {"type": "bullet_list", "items": [
            "Authenticator issuance and revocation record",
            "Vault rotation record for shared and role-based credentials",
            "Membership-change log tied to group and role authenticator updates",
            "Quarterly compliance review of authenticator lifecycle records",
        ]},
    ]


def _curated_pl1_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {"type": "paragraph", "text": f"This policy defines how {context.system_name} conducts planning activities needed to maintain secure operation, manage change, and support coordinated governance across the system lifecycle."},
        {"type": "heading", "level": 1, "text": "Scope"},
        {"type": "paragraph", "text": f"This policy applies to the system owner, engineering teams, security staff, service desk personnel, and program leadership responsible for planning, documenting, and maintaining the {context.system_name} environment."},
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {"type": "table", "headers": ["Role", "Responsibility"], "rows": [
            ["System Owner", "Approves planning decisions and resolves cross-team dependencies."],
            ["Planning Manager", "Maintains the planning policy, procedures, and controlled planning records."],
            ["ISSO", "Coordinates security planning requirements and verifies review completion."],
            ["Engineering Leads", "Provide architecture, scheduling, and implementation input to planning activities."],
        ]},
        {"type": "heading", "level": 1, "text": "Policy"},
        {"type": "paragraph", "text": "This planning policy addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance obligations. Management commitment is demonstrated through formal approval, assignment of accountable planners, and oversight of corrective actions and planning milestones."},
        {"type": "paragraph", "text": "Planning activities are coordinated among the System Owner, Planning Manager, ISSO, engineering leads, and service desk personnel so planning decisions, dependencies, and required updates remain aligned across the organization."},
        {"type": "paragraph", "text": "The planning policy is disseminated to the organization-defined audience, including system owners, engineering leads, security staff, service desk personnel, and program leadership, through the controlled policy repository. Distribution is recorded in the document acknowledgement log."},
        {"type": "heading", "level": 1, "text": "Procedures"},
        {"type": "paragraph", "text": "Supporting planning procedures define update triggers, participant roles, document maintenance responsibilities, and evidence retention expectations for planning records and approved updates."},
        {"type": "heading", "level": 1, "text": "Review and Document Control"},
        {"type": "paragraph", "text": "The planning policy and procedures are reviewed and updated at least annually and after significant architecture, staffing, supplier, or regulatory changes. The Planning Manager is designated to manage development, documentation, dissemination, and review of the planning policy and procedures."},
    ]


def _curated_ca7_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Program Scope"},
        {"type": "paragraph", "text": f"{context.system_name} uses a continuous monitoring program to track the current security status and privacy status of the system, supporting services, inherited controls, and corrective actions."},
        {"type": "heading", "level": 1, "text": "Monitoring Activities"},
        {"type": "paragraph", "text": "The continuous monitoring program collects control assessment results, vulnerability findings, configuration change records, logging and alert data, privacy issue tracking, and corrective action status on a recurring basis."},
        {"type": "paragraph", "text": "Monitoring results are analyzed for control drift, unresolved weaknesses, privacy-impacting changes, and trends that affect system risk. Changes to monitoring priorities are documented when threat conditions, architecture, suppliers, or mission needs change."},
        {"type": "heading", "level": 1, "text": "Reporting"},
        {"type": "paragraph", "text": "The continuous monitoring program includes reporting the system's security status to organization-defined recipients, including the System Owner, ISSO, Authorizing Official representative, engineering leads, and operations leadership."},
        {"type": "paragraph", "text": "The continuous monitoring program includes reporting the system's privacy status to organization-defined recipients, including the Privacy Officer, System Owner, ISSO, and program leadership. Privacy status reporting identifies open privacy issues, assessment results, corrective actions, and changes that affect handling of information in the system."},
        {"type": "heading", "level": 1, "text": "Records and Review"},
        {"type": "bullet_list", "items": [
            "Monthly security status report",
            "Monthly privacy status report",
            "Continuous monitoring dashboard export",
            "Corrective action tracker with closure evidence",
        ]},
    ]


def _curated_ma1_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "Purpose"},
        {"type": "paragraph", "text": f"This maintenance policy and procedure standard defines how {context.system_name} performs, governs, and reviews system maintenance activities."},
        {"type": "heading", "level": 1, "text": "Scope"},
        {"type": "paragraph", "text": f"This standard applies to scheduled maintenance, emergency maintenance, remote maintenance, maintenance tooling, maintenance records, and personnel who approve, perform, review, or verify maintenance on the {context.system_name} environment."},
        {"type": "heading", "level": 1, "text": "Roles and Responsibilities"},
        {"type": "table", "headers": ["Role", "Responsibility"], "rows": [
            ["System Owner", "Approves the maintenance policy and resolves maintenance exceptions."],
            ["Maintenance Manager", "Manages development, documentation, dissemination, review, and update of the maintenance policy and procedures."],
            ["ISSO", "Coordinates security requirements for maintenance activities and verifies annual review completion."],
            ["Operations Lead", "Executes maintenance scheduling, recordkeeping, and post-maintenance verification."],
        ]},
        {"type": "heading", "level": 1, "text": "Policy"},
        {"type": "paragraph", "text": "This maintenance policy addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance requirements for maintenance performed on the system."},
        {"type": "paragraph", "text": "The maintenance policy is reviewed and updated at least annually and after significant system, tooling, supplier, or operational changes that affect maintenance requirements."},
        {"type": "heading", "level": 1, "text": "Procedures"},
        {"type": "paragraph", "text": "Supporting maintenance procedures define scheduling, approval, remote maintenance restrictions, maintenance record requirements, tool control, verification steps, and evidence retention expectations."},
        {"type": "paragraph", "text": "The maintenance procedures are reviewed and updated at least annually and after significant workflow, tooling, supplier, or technology changes that affect maintenance execution or verification."},
        {"type": "heading", "level": 1, "text": "Records and Review"},
        {"type": "bullet_list", "items": [
            "Annual maintenance policy review record",
            "Annual maintenance procedure review record",
            "Maintenance change log with post-maintenance verification evidence",
            "Remote maintenance approval and closure records",
        ]},
    ]


def _curated_sc7_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "level": 1, "text": "System Context"},
        {"type": "paragraph", "text": f"{context.system_name} uses managed boundary protection services to control communications between external networks, public-facing services, and internal service tiers."},
        {"type": "heading", "level": 1, "text": "Implementation Overview"},
        {"type": "paragraph", "text": "Communications at external managed interfaces are monitored and controlled through firewalls, reverse proxies, load balancers, WAF protections, and centralized logging. Communications at key internal managed interfaces are monitored and controlled through internal service boundaries, approved ports and protocols, mutual authentication where required, and east-west traffic restrictions."},
        {"type": "heading", "level": 1, "text": "Configuration and Control Points"},
        {"type": "paragraph", "text": "Publicly accessible system components are placed on separate, organization-defined subnetworks from internal organizational networks. Internet-facing components are deployed in a segmented DMZ or dedicated security zone, and only approved connections are permitted between the public zone and internal services."},
        {"type": "paragraph", "text": "External networks and systems connect only through managed interfaces consisting of approved boundary protection devices arranged in accordance with the organizational security and privacy architecture."},
        {"type": "heading", "level": 1, "text": "Verification Activities"},
        {"type": "bullet_list", "items": [
            "Firewall and reverse proxy rule review",
            "DMZ and subnet segmentation validation",
            "Internal managed interface traffic review",
            "Boundary device alert and log verification",
        ]},
        {"type": "heading", "level": 1, "text": "Evidence Retention"},
        {"type": "paragraph", "text": "Boundary protection configuration exports, segmentation diagrams, managed interface review records, and alert verification artifacts are retained in the network security repository according to the evidence retention schedule."},
    ]


def _curated_ir4_sections(context: HumanAuthoringContext) -> list[dict[str, Any]]:
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
                "Post-incident activities capture lessons learned, update procedures, assign corrective actions, and track completion through the incident improvement register. Significant changes to tooling, communication paths, or restoration steps are incorporated into the incident handling procedure within ten business days."
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


def _curated_sections_for_control(control: Control, context: HumanAuthoringContext) -> list[dict[str, Any]] | None:
    match control.display_id:
        case "AC-1":
            return _curated_ac1_sections(context)
        case "AC-2":
            return _curated_ac2_sections(context)
        case "AU-2":
            return _curated_au2_sections(context)
        case "AU-6":
            return _curated_au6_sections(context)
        case "CA-7":
            return _curated_ca7_sections(context)
        case "IA-5":
            return _curated_ia5_sections(context)
        case "IR-4":
            return _curated_ir4_sections(context)
        case "MA-1":
            return _curated_ma1_sections(context)
        case "PL-1":
            return _curated_pl1_sections(context)
        case "PS-1":
            return _curated_ps1_sections(context)
        case "RA-1":
            return _curated_ra1_sections(context)
        case "SA-4":
            return _curated_sa4_sections(context)
        case "SC-7":
            return _curated_sc7_sections(context)
        case "SI-3":
            return _curated_si3_sections(context)
        case "CP-2":
            return _curated_cp2_sections(context)
        case "PE-3":
            return _curated_pe3_sections(context)
        case "SR-1":
            return _curated_sr1_sections(context)
        case _:
            return None


def _objective_theme_paragraphs(control: Control, context: HumanAuthoringContext) -> list[str]:
    descriptions = _objective_descriptions(control)
    if not descriptions:
        return [
            (
                f"{context.system_name} maintains current documentation and operational records for {control.title.lower()} "
                "as part of the active security program."
            )
        ]

    chunks: list[str] = []
    current: list[str] = []
    for description in descriptions:
        current.append(description.rstrip("."))
        if len(current) == 3:
            chunks.append(" ".join(current) + ".")
            current = []
    if current:
        chunks.append(" ".join(current) + ".")
    return chunks


def build_human_fallback_sections(control: Control, plan: HumanArtifactPlan, context: HumanAuthoringContext) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    objective_paragraphs = _objective_theme_paragraphs(control, context)
    for heading in plan.outline:
        sections.append({"type": "heading", "level": 1, "text": heading})
        lower = heading.lower()
        if lower == "purpose":
            sections.append(
                {
                    "type": "paragraph",
                    "text": (
                        f"This document describes how {context.system_name} implements {control.title.lower()} within the "
                        f"{context.impact_baseline.capitalize()} baseline environment."
                    ),
                }
            )
        elif lower == "scope":
            sections.append(
                {
                    "type": "paragraph",
                    "text": (
                        f"The control applies to the {context.context_label} environment and the workforce members, services, "
                        "support processes, and retained records needed to operate and verify the control."
                    ),
                }
            )
        elif lower == "roles and responsibilities":
            sections.append(
                {
                    "type": "table",
                    "headers": ["Role", "Responsibility"],
                    "rows": _family_roles(control),
                }
            )
        elif lower in {"policy", "procedures", "operating procedure", "implementation narrative", "configuration and control points"}:
            for paragraph in objective_paragraphs:
                sections.append({"type": "paragraph", "text": paragraph})
        elif lower in {"records and review", "review and document control", "verification and evidence", "verification activities", "evidence retention"}:
            sections.append(
                {
                    "type": "paragraph",
                    "text": (
                        "Implementation records are retained in the system of record, reviewed on a defined cadence by the "
                        "responsible control owner, and updated when operational conditions, assigned roles, or governing requirements change."
                    ),
                }
            )
        else:
            sections.append(
                {
                    "type": "paragraph",
                    "text": (
                        f"{context.system_name} maintains current operational documentation for this control and updates it "
                        "when system conditions, risks, or assigned responsibilities change."
                    ),
                }
            )
    return sections


def _build_generation_prompts(control: Control, plan: HumanArtifactPlan, context: HumanAuthoringContext) -> tuple[str, str]:
    objective_lines = "\n".join(f"- {text}" for text in _objective_descriptions(control)) or "- Cover the full control requirement in natural prose."
    outline_lines = "\n".join(f"- {heading}" for heading in plan.outline)
    context_excerpt = context.evidence_excerpt or "No additional project evidence excerpt was supplied."
    control_specific_lines = "\n".join(f"- {text}" for text in _control_specific_authoring_requirements(control)) or "- No extra control-specific drafting rules."

    system_prompt = "\n".join(
        [
            "You write federal security documentation that reads like a human-owned system artifact.",
            "Return ONLY a valid JSON object with keys 'title' and 'sections'.",
            "Each section must be one of: heading, paragraph, bullet_list, numbered_list, table.",
            "Do not use control IDs, objective IDs, traceability language, assessment language, or evaluator commentary anywhere in the document.",
            "Do not write phrases like 'This section satisfies', 'assessment objective', 'crosswalk', or 'traceability matrix'.",
            "Write current-state prose with concrete owners, records, reviews, and operating details.",
            "Do not include evidence inventories, package listings, artifact path tables, source repository references, or generated metadata banners.",
            "Use the context excerpt only as background realism. Do not quote filenames, file paths, or document repository contents.",
        ]
    )

    user_prompt = "\n".join(
        [
            f"System name: {context.system_name}",
            f"Project context: {context.context_label}",
            f"Impact baseline: {context.impact_baseline}",
            f"Deployment model: {context.deployment_model or 'not specified'}",
            f"Infrastructure ownership: {context.infrastructure_ownership or 'not specified'}",
            f"Document title: {plan.title}",
            f"Document type: {plan.document_type}",
            "",
            "Required outline headings:",
            outline_lines,
            "",
            "Control title and statement:",
            f"{control.title}",
            control.statement or "",
            "",
            "Coverage requirements to weave naturally into the document:",
            objective_lines,
            "",
            "Control-specific requirements that must appear explicitly in normal prose:",
            control_specific_lines,
            "",
            "Project evidence excerpt for realism:",
            context_excerpt,
            "",
            "Return JSON in this shape:",
            '{',
            '  "title": "Document title",',
            '  "sections": [',
            '    {"type": "heading", "level": 1, "text": "Heading"},',
            '    {"type": "paragraph", "text": "Plain prose"},',
            '    {"type": "bullet_list", "items": ["Item"]},',
            '    {"type": "numbered_list", "items": ["Item"]},',
            '    {"type": "table", "headers": ["Col1", "Col2"], "rows": [["Value 1", "Value 2"]]}',
            "  ]",
            "}",
        ]
    )
    return system_prompt, user_prompt


async def _llm_sections_for_control(
    *,
    control: Control,
    plan: HumanArtifactPlan,
    context: HumanAuthoringContext,
    provider_name: str | None,
    model: str | None,
) -> tuple[str, list[dict[str, Any]], str | None]:
    async with AsyncSessionLocal() as db:
        provider, _runtime = await build_provider_for_purpose(
            db,
            "test_dataset_generation",
            provider_name=provider_name,
            model=model,
        )
    system_prompt, user_prompt = _build_generation_prompts(control, plan, context)
    raw = await provider.complete(system_prompt, user_prompt)
    parsed = json.loads(_strip_json_fences(raw))
    title = str(parsed.get("title") or plan.title).strip() or plan.title
    sections = list(parsed.get("sections") or [])
    return title, sections, raw


async def _repair_llm_sections_for_control(
    *,
    control: Control,
    plan: HumanArtifactPlan,
    context: HumanAuthoringContext,
    provider_name: str | None,
    model: str | None,
    prior_title: str,
    prior_sections: list[dict[str, Any]],
    lint_issues: list[str],
) -> tuple[str, list[dict[str, Any]], str | None]:
    async with AsyncSessionLocal() as db:
        provider, _runtime = await build_provider_for_purpose(
            db,
            "test_dataset_generation",
            provider_name=provider_name,
            model=model,
        )
    system_prompt = "\n".join(
        [
            "You revise federal security documentation so it remains human-readable and operationally specific.",
            "Return ONLY a valid JSON object with keys 'title' and 'sections'.",
            "Do not use control IDs, objective IDs, traceability language, assessment language, or evaluator commentary anywhere in the document.",
            "Preserve the document genre and heading structure while fixing the listed issues.",
            "Do not add evidence inventories, package listings, file paths, or repository references.",
        ]
    )
    user_prompt = "\n".join(
        [
            f"System name: {context.system_name}",
            f"Document title: {prior_title}",
            f"Document type: {plan.document_type}",
            "",
            "Required outline headings:",
            "\n".join(f"- {heading}" for heading in plan.outline),
            "",
            "Control title and statement:",
            control.title,
            control.statement or "",
            "",
            "Coverage requirements:",
            "\n".join(f"- {text}" for text in _objective_descriptions(control)),
            "",
            "Control-specific requirements:",
            "\n".join(f"- {text}" for text in _control_specific_authoring_requirements(control)) or "- No extra control-specific drafting rules.",
            "",
            "Problems to fix:",
            "\n".join(f"- {issue}" for issue in lint_issues),
            "",
            "Current draft JSON:",
            json.dumps({"title": prior_title, "sections": prior_sections}, ensure_ascii=True),
        ]
    )
    raw = await provider.complete(system_prompt, user_prompt)
    parsed = json.loads(_strip_json_fences(raw))
    title = str(parsed.get("title") or prior_title).strip() or prior_title
    sections = list(parsed.get("sections") or prior_sections)
    return title, sections, raw


async def generate_human_artifact(
    *,
    project_id: int,
    control_id: str,
    created_by: int,
    source_assessment_id: int | None = None,
    provider_name: str | None = None,
    model: str | None = None,
    save_document: bool = True,
    trigger_parse: bool = True,
    force_llm: bool = False,
) -> dict[str, Any]:
    catalog = load_catalog()
    control = catalog.get(control_id.lower())
    if control is None:
        raise ValueError(f"Unknown control: {control_id}")

    async with AsyncSessionLocal() as db:
        context = await build_human_authoring_context(project_id, db)
    plan = plan_human_artifact(control, context.system_name)
    title = plan.title
    raw_output: str | None = None
    curated_sections = None if force_llm else _curated_sections_for_control(control, context)
    if curated_sections is not None:
        sections, injected_requirements = ensure_required_clauses(
            title=title,
            sections=curated_sections,
            control=control,
            context=context,
        )
        lint_issues = lint_human_artifact(title=title, sections=sections, control=control, plan=plan, context=context)
        generation_mode = "curated_fast_path"
        if injected_requirements:
            generation_mode = "curated_fast_path_supplemented"
    else:
        generation_mode = "llm_forced" if force_llm else "llm"
        max_attempts = 2 if force_llm else 1
        llm_error_name: str | None = None
        for attempt_index in range(max_attempts):
            try:
                title, sections, raw_output = await _llm_sections_for_control(
                    control=control,
                    plan=plan,
                    context=context,
                    provider_name=provider_name,
                    model=model,
                )
                sections, injected_requirements = ensure_required_clauses(
                    title=title,
                    sections=sections,
                    control=control,
                    context=context,
                )
                lint_issues = lint_human_artifact(title=title, sections=sections, control=control, plan=plan, context=context)
                if not lint_issues:
                    generation_mode = "llm_forced" if force_llm else "llm"
                    if injected_requirements:
                        generation_mode = f"{generation_mode}_supplemented"
                    break
                try:
                    repaired_title, repaired_sections, repair_raw = await _repair_llm_sections_for_control(
                        control=control,
                        plan=plan,
                        context=context,
                        provider_name=provider_name,
                        model=model,
                        prior_title=title,
                        prior_sections=sections,
                        lint_issues=lint_issues,
                    )
                    repaired_sections, injected_requirements = ensure_required_clauses(
                        title=repaired_title,
                        sections=repaired_sections,
                        control=control,
                        context=context,
                    )
                    repair_issues = lint_human_artifact(
                        title=repaired_title,
                        sections=repaired_sections,
                        control=control,
                        plan=plan,
                        context=context,
                    )
                    if not repair_issues:
                        title = repaired_title
                        sections = repaired_sections
                        raw_output = repair_raw
                        lint_issues = []
                        generation_mode = "llm_repaired" if attempt_index == 0 else "llm_retry_repaired"
                        if injected_requirements:
                            generation_mode = f"{generation_mode}_supplemented"
                        break
                    lint_issues = repair_issues
                except Exception as exc:
                    llm_error_name = type(exc).__name__
            except Exception as exc:
                llm_error_name = type(exc).__name__
                lint_issues = [f"LLM generation error: {llm_error_name}."]
            if attempt_index == max_attempts - 1:
                generation_mode = (
                    f"fallback_after_error:{llm_error_name}" if llm_error_name else "fallback_after_lint"
                )
                title = plan.title
                sections, injected_requirements = ensure_required_clauses(
                    title=title,
                    sections=build_human_fallback_sections(control, plan, context),
                    control=control,
                    context=context,
                )
                lint_issues = lint_human_artifact(title=title, sections=sections, control=control, plan=plan, context=context)
                if injected_requirements:
                    generation_mode = f"{generation_mode}_supplemented"

    file_bytes = _build_docx(title, sections, context.system_name)
    result: dict[str, Any] = {
        "project_id": project_id,
        "control_id": control.display_id,
        "title": title,
        "filename": plan.filename,
        "document_type": plan.document_type,
        "artifact_type": plan.artifact_type,
        "generation_mode": generation_mode,
        "lint_issues": lint_issues,
        "sections": sections,
        "raw_output": raw_output,
        "file_bytes": file_bytes,
    }

    if not save_document:
        return result

    settings = get_settings()
    upload_dir = Path(settings.upload_dir) / str(project_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    doc_id = await _save_doc(
        file_bytes=file_bytes,
        filename=plan.filename,
        project_id=project_id,
        upload_dir=upload_dir,
        created_by=created_by,
        control_id=control.display_id,
        document_type=plan.document_type,
        document_intent="implements",
        controls_addressed=[control.display_id],
        source_assessment_id=source_assessment_id,
        trigger_parse=False,
    )
    result["document_id"] = doc_id

    if trigger_parse:
        parse_status = "queued"
        parse_attempts = 0
        while parse_attempts < 3:
            parse_attempts += 1
            await dispatch_parse(doc_id)
            parse_status = await _wait_for_document_index(doc_id, timeout_secs=180)
            if parse_status == "indexed":
                break
        result["parse_status"] = parse_status
        result["parse_attempts"] = parse_attempts
    return result


async def generate_human_artifacts_for_assessment(
    *,
    assessment_id: int,
    control_ids: list[str],
    provider_name: str | None = None,
    model: str | None = None,
    trigger_parse: bool = True,
    force_llm: bool = False,
) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        assessment = await db.get(Assessment, assessment_id)
        if assessment is None:
            raise ValueError(f"Assessment {assessment_id} was not found.")
    results: list[dict[str, Any]] = []
    for control_id in control_ids:
        results.append(
            await generate_human_artifact(
                project_id=assessment.project_id,
                control_id=control_id,
                created_by=assessment.started_by,
                source_assessment_id=assessment.id,
                provider_name=provider_name or assessment.llm_provider,
                model=model or assessment.llm_model,
                trigger_parse=trigger_parse,
                force_llm=force_llm,
            )
        )
    return results
