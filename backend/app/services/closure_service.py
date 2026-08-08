"""Control Closure Workflow service.

Drives the interactive AI interview → artifact generation → approval workflow
that walks a user through closing a partial or non-compliant NIST 800-53 Rev 5 control.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, UTC
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.orm import (
    ArtifactApproval,
    Assessment,
    AssessmentPolicy,
    AssessmentCriteriaPackage,
    ControlClosureSession,
    ControlFinding,
    Document,
    Project,
    SystemProfile,
)
from app.services.assessment_pipeline import (
    assess_control_with_assessor_pipeline,
    build_scope_document_ids,
    preload_evidence_index,
)
from app.services.assessment_policy import build_policy_runtime
from app.services.closure_guidance import (
    build_control_closure_guidance,
    build_contract_sections,
    format_contracts_for_prompt,
    sections_satisfy_contracts,
)
from app.services.controls.catalog import load_catalog
from app.services.llm.runtime import build_provider_for_purpose
from app.services.parsers.dispatcher import dispatch_parse
from app.services.system_knowledge import get_latest_system_knowledge
from app.services.test_dataset_generator import _build_docx, _save_doc
from app.services.tool_guidance import build_action_collection_guidance

logger = logging.getLogger(__name__)

# ── LLM Prompts ────────────────────────────────────────────────────────────────

INTERVIEW_SYSTEM_PROMPT = """You are a NIST 800-53 Rev 5 compliance closure specialist conducting a structured interview.

Your goal: gather the specific facts needed to generate evidence artifacts that will satisfy all unmet assessment objectives for the control being evaluated.

Ask 3–5 TARGETED questions that establish:
- What is ACTUALLY implemented (tools, systems, processes)
- WHO is responsible (role/name)
- HOW compliance is verified (logs, reports, audits)
- WHAT specific procedures exist
- WHERE evidence can be found

Offer concrete answer options wherever predictable. Keep questions grounded in the specific NIST 800-53A objectives listed in the gaps.

Return ONLY valid JSON:
{
  "intro": "One sentence framing what you need to establish",
  "questions": [
    {
      "id": "q1",
      "text": "Question text",
      "type": "dropdown|text|multiselect|boolean",
      "options": ["option1", "option2"],
      "placeholder": "hint text for text inputs",
      "nist_context": "Why this matters — reference specific objective ID"
    }
  ]
}"""

ANALYSIS_SYSTEM_PROMPT = """You are a NIST 800-53 Rev 5 compliance closure specialist.

You have received answers from the system owner/ISSO about a partially or non-compliant control.
Based on those answers and the original compliance gaps, determine:
1. Whether enough information has been gathered to generate artifacts
2. What specific artifacts will close the remaining gaps
3. Whether any critical follow-up is needed

Return ONLY valid JSON:
{
  "ready_to_generate": true|false,
  "implementation_summary": "2–3 sentence plain-English summary of what was described",
  "follow_up_questions": [],
  "recommended_artifacts": [
    {
      "title": "Exact document title",
      "artifact_type": "policy_procedure|completed_form|ssp_narrative|procedure|evidence_template|agreement_template",
      "purpose": "How this specific artifact closes the identified gap",
      "controls_addressed": ["XX-N"],
      "key_content_from_interview": "Specific facts from the answers to bake into this artifact"
    }
  ]
}"""

ARTIFACT_GEN_SYSTEM_PROMPT = """You are a NIST 800-53 Rev 5 compliance author creating an official security artifact.

This document will be indexed by an AI assessment system. It MUST contain explicit language that satisfies the NIST 800-53A assessment objectives listed as gaps. The interview context below contains REAL information from the system owner — incorporate it precisely.

Return ONLY valid JSON:
{
  "title": "Document title",
  "sections": [
    {"type": "heading", "level": 1, "text": "Section title"},
    {"type": "paragraph", "text": "Plain prose — no markdown symbols"},
    {"type": "numbered_list", "items": ["Step text"]},
    {"type": "bullet_list", "items": ["Item text"]},
    {"type": "table", "headers": ["Col1", "Col2"], "rows": [["val", "val"]]}
  ]
}

WRITING RULES:
- Cite each control ID in the relevant section: "This procedure satisfies [XX-N] by..."
- Use NIST 800-53A assessment objective language so the assessor AI matches the text
- Incorporate all facts gathered in the interview — do NOT invent information not provided
- Be specific: name the tools, roles, systems, and processes described in the interview
- Plain prose only — no # headings, no ** bold, no | tables | in text fields"""


# ── Session helpers ────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _session_to_dict(session: ControlClosureSession, approvals: list[ArtifactApproval] | None = None) -> dict:
    return {
        "id": session.id,
        "project_id": session.project_id,
        "assessment_id": session.assessment_id,
        "control_id": session.control_id,
        "control_family": session.control_family,
        "control_title": session.control_title,
        "current_status": session.current_status,
        "session_status": session.session_status,
        "steps": session.steps or [],
        "context_summary": session.context_summary,
        "implementation_summary": session.implementation_summary,
        "recommended_artifacts": session.recommended_artifacts or [],
        "generated_artifact_ids": session.generated_artifact_ids or [],
        "closure_notes": session.closure_notes,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "approvals": [_approval_to_dict(a) for a in (approvals or [])],
    }


def _approval_to_dict(a: ArtifactApproval) -> dict:
    return {
        "id": a.id,
        "session_id": a.session_id,
        "document_id": a.document_id,
        "control_id": a.control_id,
        "artifact_title": a.artifact_title,
        "artifact_type": a.artifact_type,
        "approval_chain": a.approval_chain,
        "current_step": a.current_step,
        "overall_status": a.overall_status,
        "evidence_eligibility": a.evidence_eligibility,
        "eligibility_rationale": a.eligibility_rationale,
        "eligibility_decided_by": a.eligibility_decided_by,
        "eligibility_decided_at": a.eligibility_decided_at.isoformat() if a.eligibility_decided_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _parse_objective_entry(raw_value: str, fallback_control_id: str) -> tuple[str, str]:
    value = str(raw_value or "").strip()
    match = __import__("re").match(
        r'^([A-Z]{2}-\d+(?:\([0-9a-zA-Z]+\))*(?:[a-z])?(?:\.\d+)?(?:\[\d+\])?)[\s:\.]+',
        value,
    )
    if match:
        return match.group(1), value[len(match.group(0)):].strip() or value
    return fallback_control_id, value


def _merge_finding_and_criteria_objectives(
    *,
    control_id: str,
    gaps: list[Any] | None,
    assessment_objectives: list[Any] | None,
) -> list[dict[str, Any]]:
    gap_map: dict[str, dict[str, Any]] = {}
    for gap in gaps or []:
        objective_id, description = _parse_objective_entry(str(gap), control_id)
        gap_map[objective_id] = {
            "objective_id": objective_id,
            "description": description or str(gap),
            "full_text": str(gap),
        }

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_objective in assessment_objectives or []:
        if isinstance(raw_objective, dict):
            objective_id = str(raw_objective.get("id") or raw_objective.get("objective_id") or control_id).strip()
            description = str(
                raw_objective.get("description")
                or raw_objective.get("prose")
                or raw_objective.get("text")
                or objective_id
            ).strip()
        else:
            objective_id, description = _parse_objective_entry(str(raw_objective), control_id)
        if objective_id in seen:
            continue
        seen.add(objective_id)
        gap_entry = gap_map.pop(objective_id, None)
        merged.append({
            "objective_id": objective_id,
            "description": (gap_entry or {}).get("description") or description,
            "full_text": (gap_entry or {}).get("full_text") or f"{objective_id}: {description}",
        })

    for objective_id, gap_entry in gap_map.items():
        if objective_id in seen:
            continue
        seen.add(objective_id)
        merged.append(gap_entry)
    return merged


def _normalize_generated_sections(
    *,
    content_json: str,
    title: str,
    system_name: str,
    control_guidance: dict[str, Any],
) -> str:
    try:
        parsed = _parse_json_safe(content_json)
    except Exception:
        parsed = {}

    sections = parsed.get("sections") if isinstance(parsed, dict) else []
    sections = sections if isinstance(sections, list) else []
    contracts = control_guidance.get("objective_contracts") or []
    contracts_ok, _ = sections_satisfy_contracts(sections, contracts)
    substantive_sections = sum(
        1
        for section in sections
        if section.get("type") in {"heading", "paragraph", "bullet_list", "numbered_list", "table"}
        and any(section.get(key) for key in ("text", "items", "rows"))
    )
    if substantive_sections < 4 or not contracts_ok:
        fallback = {
            "title": title,
            "sections": build_contract_sections(
                contracts=contracts,
                system_name=system_name,
                document_type=control_guidance.get("document_type"),
                intro_title=title,
                intro_text=(
                    f"This control-closure artifact for {control_guidance['control_id']} provides current-state "
                    "implementation evidence that satisfies the closure contract for reassessment."
                ),
            ),
        }
        return json.dumps(fallback)
    parsed["title"] = parsed.get("title") or title
    parsed["sections"] = sections
    return json.dumps(parsed)


def _prepend_draft_review_sections(
    *,
    content_json: str,
    control_id: str,
    control_title: str,
    gaps: list[str] | None,
) -> str:
    try:
        parsed = _parse_json_safe(content_json)
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {"title": f"{control_id} Draft Artifact", "sections": []}
    sections = parsed.get("sections") if isinstance(parsed.get("sections"), list) else []
    review_sections: list[dict[str, Any]] = [
        {"type": "heading", "level": 1, "text": "Draft Review Notice"},
        {
            "type": "paragraph",
            "text": (
                f"This AI-generated draft addresses {control_id} ({control_title}) and is provided for control-owner review. "
                "It is not approved evidence of record and must be validated, edited, and supported with real operational records before reassessment."
            ),
        },
    ]
    if gaps:
        review_sections.append(
            {
                "type": "bullet_list",
                "items": [f"Gap to address: {str(gap)}" for gap in gaps[:6]],
            }
        )
    parsed["sections"] = review_sections + sections
    return json.dumps(parsed)


def _proof_document_type(control_id: str, guidance: dict[str, Any]) -> str:
    hints = set(guidance.get("recommended_artifact_types") or [])
    if "policy" in hints and "technical_artifact" in hints:
        return "policy"
    if "technical_artifact" in hints:
        return "technical_artifact"
    if "policy" in hints:
        return "policy"
    if "procedure" in hints or "agreement_template" in hints:
        return "procedure"
    family = control_id.split("-", 1)[0].upper()
    if family in {"AC", "CM", "IA", "SC", "SI", "AU"}:
        return "technical_artifact"
    if family in {"PL", "PM", "CA", "RA"}:
        return "policy"
    return "procedure"


def _proof_document_types(control_id: str, guidance: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    for hint in guidance.get("recommended_artifact_types") or []:
        normalized = "procedure" if hint in {"agreement_template"} else str(hint)
        if normalized not in {"policy", "procedure", "technical_artifact", "ssp_narrative"}:
            continue
        if normalized not in ordered:
            ordered.append(normalized)
    if not ordered:
        ordered.append(_proof_document_type(control_id, guidance))
    return ordered


def _build_initial_interview_data(control_id: str, guidance: dict[str, Any]) -> dict[str, Any]:
    contracts = list(guidance.get("objective_contracts") or [])
    artifact_types = list(guidance.get("recommended_artifact_types") or [])

    required_text = " ".join(
        str(item)
        for contract in contracts
        for item in (contract.get("required_facts") or [])
    ).lower()
    response_text = " ".join(
        str(item)
        for contract in contracts
        for item in (contract.get("response_elements") or [])
    ).lower()

    questions: list[dict[str, Any]] = [
        {
            "id": "implementation_surface",
            "text": "Which system, service, tool, or manual process currently implements this control?",
            "type": "text",
            "placeholder": "Name the exact platform, system component, or process in use today.",
            "nist_context": f"Establishes the current-state implementation for {control_id}.",
        },
        {
            "id": "responsible_role",
            "text": "Who is the responsible role that owns this control and its evidence?",
            "type": "dropdown",
            "options": [
                "ISSO",
                "System Owner",
                "System Administrator",
                "Security Operations",
                "IT Operations",
                "Privacy Officer",
                "Compliance Team",
                "Other",
            ],
            "nist_context": "Identifies the accountable role and evidence owner.",
        },
        {
            "id": "verification_record",
            "text": "What record, log, report, ticket, or repository proves this control is operating today?",
            "type": "text",
            "placeholder": "Name the specific record or repository the assessor should rely on.",
            "nist_context": "Anchors the closure package to retained evidence the assessor can verify.",
        },
        {
            "id": "verification_cadence",
            "text": "How is this control verified, by whom, and on what review cadence?",
            "type": "text",
            "placeholder": "Describe the reviewer, method, and cadence in plain language.",
            "nist_context": "Captures the review mechanism and frequency required for closure.",
        },
    ]

    if any(token in required_text for token in ("organization-defined", "threshold", "duration", "limit", "timeout", "minutes", "value")):
        questions.append(
            {
                "id": "defined_values",
                "text": "What exact organization-defined value, threshold, duration, or timeout applies here?",
                "type": "text",
                "placeholder": "State the exact value and units, not a generic description.",
                "nist_context": "This control requires a concrete value the assessor can verify.",
            }
        )

    if any(token in required_text or token in response_text for token in ("policy", "procedure", "ssp", "documented", "approval", "dissemination")) or any(
        artifact in {"policy", "procedure", "ssp_narrative"} for artifact in artifact_types
    ):
        questions.append(
            {
                "id": "document_sources",
                "text": "Which document or section should carry this requirement, and who approves it?",
                "type": "text",
                "placeholder": "Name the document, section, and approving authority.",
                "nist_context": "Determines where the closure facts belong and who formally approves them.",
            }
        )

    if any(token in required_text or token in response_text for token in ("alert", "monitoring", "audit", "logged", "detection", "unauthorized")):
        questions.append(
            {
                "id": "monitoring_details",
                "text": "What alert, monitoring, or logging behavior proves this control is active, and where is that recorded?",
                "type": "text",
                "placeholder": "State the trigger, destination, reviewer, and retained record.",
                "nist_context": "Captures the monitoring evidence the assessor expects to see.",
            }
        )

    return {
        "intro": (
            f"Let's gather the exact current-state facts needed to close {control_id}. "
            "Answer with the real implementation, evidence source, owner, and any required values."
        ),
        "questions": questions[:5],
    }


async def _wait_for_document_index(document_id: int, *, timeout_secs: int = 120) -> str:
    deadline = asyncio.get_running_loop().time() + timeout_secs
    last_status = "pending"
    while asyncio.get_running_loop().time() < deadline:
        async with AsyncSessionLocal() as db:
            doc = await db.get(Document, document_id)
            if not doc:
                return "missing"
            last_status = doc.parse_status or "pending"
            if last_status in {"indexed", "complete"}:
                return last_status
            if last_status in {"failed", "index_failed"}:
                return last_status
        await asyncio.sleep(1.0)
    return last_status


def _build_control_namespace(*, control_id: str, finding: ControlFinding, criteria: AssessmentCriteriaPackage | None):
    catalog = load_catalog()
    control = catalog.get(control_id)
    if control is not None:
        return control
    family = (finding.control_family or control_id.split("-", 1)[0]).lower()
    return SimpleNamespace(
        id=control_id.lower(),
        label=control_id.upper(),
        family_id=family,
        family_title=finding.control_family or family.upper(),
        title=finding.control_title,
        statement=(criteria.control_statement if criteria else "") or "",
        supplemental_guidance=(criteria.supplemental_guidance if criteria else "") or "",
        assessment_objectives=(criteria.assessment_objectives if criteria else []) or [],
        is_enhancement="(" in control_id,
        parent_id=control_id.split("(")[0] if "(" in control_id else None,
        display_id=control_id.upper(),
    )


def _build_project_context(project: Project | None, profile: SystemProfile | None) -> tuple[str, str]:
    system_name = (project.name if project else None) or "Federal Information System"
    parts = [system_name]
    if project and project.impact_baseline:
        parts.append(f"{project.impact_baseline.capitalize()} baseline")
    if profile and profile.deployment_model:
        parts.append(f"{profile.deployment_model.replace('_', ' ')} deployment")
    if profile and profile.infrastructure_ownership:
        parts.append(f"{profile.infrastructure_ownership.replace('_', ' ')} infrastructure")
    return system_name, " | ".join(parts)


def _normalize_display_status(status: str | None) -> str:
    return {
        "non_compliant": "Non-Compliant",
        "partially_compliant": "Partial",
        "compliant": "Compliant",
        "not_reviewed": "Needs review",
    }.get(str(status or "").lower(), str(status or "Needs review").replace("_", " ").title())


def _primary_artifact_type(guidance: dict[str, Any], control_id: str) -> str:
    hints = [str(item) for item in (guidance.get("recommended_artifact_types") or []) if item]
    priority = [
        "policy_procedure",
        "procedure",
        "ssp_narrative",
        "technical_artifact",
        "evidence_template",
        "completed_form",
        "agreement_template",
        "policy",
    ]
    for preferred in priority:
        if preferred in hints:
            return preferred
    if control_id.startswith(("CM", "SC", "SI", "IA", "AU")):
        return "technical_artifact"
    if control_id.startswith(("PL", "PM", "PT")):
        return "ssp_narrative"
    return hints[0] if hints else "policy_procedure"


def _artifact_type_label(artifact_type: str) -> str:
    return {
        "policy_procedure": "Policy and Procedure Draft",
        "procedure": "Procedure Draft",
        "ssp_narrative": "Narrative Control Draft",
        "technical_artifact": "Technical Evidence Draft",
        "evidence_template": "Evidence Collection Draft",
        "completed_form": "Completed Record Draft",
        "agreement_template": "Agreement Draft",
        "policy": "Policy Draft",
    }.get(artifact_type, "Control Draft")


def _build_draft_package_artifacts(
    *,
    control_id: str,
    control_title: str,
    remediation_plan: str,
    guidance: dict[str, Any],
) -> list[dict[str, Any]]:
    primary_type = _primary_artifact_type(guidance, control_id)
    return [
        {
            "title": f"{control_id} {control_title} - {_artifact_type_label(primary_type)}",
            "artifact_type": primary_type,
            "purpose": "Operational draft artifact that addresses the identified gaps for control-owner review before reassessment.",
            "controls_addressed": [control_id],
            "key_content_from_interview": remediation_plan or f"Address all documented {control_id} gaps with a control-owner review draft.",
        },
        {
            "title": f"{control_id} {control_title} - Control Owner Review Memo",
            "artifact_type": "completed_form",
            "purpose": "Review memo for the control owner covering assumptions, unresolved fields, and the approval-needed facts before the draft can become evidence of record.",
            "controls_addressed": [control_id],
            "key_content_from_interview": remediation_plan or f"Summarize unresolved facts and review checkpoints for {control_id}.",
        },
    ]


def _draft_package_approval_chain(preparer_name: str = "System User") -> list[dict]:
    return [
        {
            "step": 0,
            "role": "preparer",
            "label": "Preparer",
            "name": preparer_name,
            "title": "",
            "organization": "",
            "status": "approved",
            "comments": "AI draft package prepared for control-owner review.",
            "completed_at": _now_iso(),
        },
        {
            "step": 1,
            "role": "control_owner",
            "label": "Control Owner Review",
            "name": "",
            "title": "Control Owner",
            "organization": "",
            "status": "pending",
            "comments": "",
            "completed_at": None,
        },
        {
            "step": 2,
            "role": "reviewer",
            "label": "Technical Reviewer",
            "name": "",
            "title": "",
            "organization": "",
            "status": "pending",
            "comments": "",
            "completed_at": None,
        },
        {
            "step": 3,
            "role": "isso",
            "label": "Information System Security Officer (ISSO)",
            "name": "",
            "title": "ISSO",
            "organization": "",
            "status": "pending",
            "comments": "",
            "completed_at": None,
        },
    ]


def _draft_owner_review_instructions(control_id: str) -> list[str]:
    return [
        f"Confirm the draft accurately describes how {control_id} operates today, not how it should operate in the future.",
        "Replace any assumptions, placeholders, or inferred platform names with the actual system, tool, owner, and repository details.",
        "Attach or point to the real supporting records that prove the implementation, approvals, cadence, and retained evidence.",
        "Do not treat the AI draft as evidence of record until the control owner and reviewer accept the content and attach the supporting records.",
    ]


def _coverage_map_from_guidance(
    *,
    control_id: str,
    guidance: dict[str, Any],
    artifact_titles: list[str],
) -> list[dict[str, Any]]:
    gaps = [str(item) for item in (guidance.get("gaps") or []) if str(item).strip()]
    contracts = list(guidance.get("objective_contracts") or [])
    collection = list(guidance.get("collection_guidance") or [])
    coverage: list[dict[str, Any]] = []
    for index, gap in enumerate(gaps):
        contract = next((entry for entry in contracts if str(entry.get("objective_id") or "") in gap), None)
        if contract is None and index < len(contracts):
            contract = contracts[index]
        if contract is None:
            contract = {}
        guidance_item = collection[index] if index < len(collection) else (collection[0] if collection else {})
        coverage.append(
            {
                "gap": gap,
                "objective_id": contract.get("objective_id") or control_id,
                "short_title": contract.get("short_title") or control_id,
                "addressed_by": artifact_titles,
                "passing_evidence_expectations": list(contract.get("required_facts") or [])[:6],
                "strong_evidence_examples": list(contract.get("evidence_examples") or [])[:4],
                "owner_must_confirm": [
                    "Exact system, application, or platform names",
                    "Responsible role and approving authority",
                    "Record location, ticket, log, report, or repository proving implementation",
                    "Current cadence, review date, and retention practice",
                ],
                "likely_collection_locations": list(guidance_item.get("where_to_go") or [])[:4],
            }
        )
    return coverage


async def _load_documents(document_ids: list[int], db: AsyncSession) -> list[Document]:
    if not document_ids:
        return []
    result = await db.execute(select(Document).where(Document.id.in_(document_ids)))
    docs = result.scalars().all()
    doc_map = {doc.id: doc for doc in docs}
    return [doc_map[doc_id] for doc_id in document_ids if doc_id in doc_map]


def _draft_package_state(session: ControlClosureSession | None, approvals: list[ArtifactApproval]) -> str:
    if not session:
        return "not_started"
    if any(approval.overall_status == "rejected" for approval in approvals):
        return "changes_requested"
    if approvals and all(approval.overall_status == "approved" for approval in approvals):
        return "approved"
    if approvals:
        first_pending = next(
            (
                step
                for approval in approvals
                for step in approval.approval_chain
                if step.get("status") == "pending"
            ),
            None,
        )
        if first_pending and first_pending.get("role") == "control_owner":
            return "owner_review"
        return "in_review"
    if session.generated_artifact_ids:
        return "draft_generated"
    return session.session_status


def _document_download_url(project_id: int, document_id: int) -> str:
    return f"/projects/{project_id}/documents/{document_id}/download"


async def get_closure_guidance(
    *,
    project_id: int,
    assessment_id: int,
    control_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    result = await db.execute(
        select(ControlFinding).where(
            ControlFinding.assessment_id == assessment_id,
            ControlFinding.control_id == control_id,
        )
    )
    finding = result.scalar_one_or_none()
    if not finding:
        raise ValueError(f"No finding for control {control_id} in assessment {assessment_id}")

    gaps = finding.gaps or []
    if isinstance(gaps, str):
        gaps = [gaps]
    criteria_result = await db.execute(
        select(AssessmentCriteriaPackage.assessment_objectives).where(
            AssessmentCriteriaPackage.assessment_id == assessment_id,
            AssessmentCriteriaPackage.control_id == control_id,
        )
    )
    assessment_objectives = criteria_result.scalar_one_or_none() or []

    guidance = build_control_closure_guidance(
        control_id=control_id,
        control_title=finding.control_title or control_id,
        gaps=_merge_finding_and_criteria_objectives(
            control_id=control_id,
            gaps=gaps,
            assessment_objectives=assessment_objectives,
        ),
        system_name="the system",
        current_status=finding.status,
        mode="live",
    )
    detected_tools = []
    try:
        system_knowledge = await get_latest_system_knowledge(project_id, db)
        detected_tools = list(system_knowledge.get("tools", []))
    except Exception:
        logger.exception("Failed to load system knowledge for closure guidance", extra={
            "project_id": project_id,
            "assessment_id": assessment_id,
            "control_id": control_id,
        })

    gap_lines = gaps if isinstance(gaps, list) else [gaps]
    action_seed = {
        "control_id": control_id,
        "control_title": finding.control_title or control_id,
        "gap": "; ".join(str(g) for g in gap_lines[:3]) if gap_lines else f"Implement {control_id} requirements",
        "action": finding.remediation_plan or f"Close the documented {control_id} gaps with evidence that satisfies the listed objective contracts.",
    }
    collection_guidance = build_action_collection_guidance(action_seed, detected_tools)

    guidance["status"] = finding.status
    guidance["gaps"] = gaps
    guidance["remediation_plan"] = finding.remediation_plan or ""
    guidance["implementation_statement"] = finding.implementation_statement or ""
    guidance["collection_guidance"] = collection_guidance
    return guidance


async def get_control_draft_package(
    *,
    project_id: int,
    assessment_id: int,
    control_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    finding_result = await db.execute(
        select(ControlFinding).where(
            ControlFinding.assessment_id == assessment_id,
            ControlFinding.control_id == control_id,
        )
    )
    finding = finding_result.scalar_one_or_none()
    if not finding:
        raise ValueError(f"No finding for control {control_id} in assessment {assessment_id}")

    guidance = await get_closure_guidance(
        project_id=project_id,
        assessment_id=assessment_id,
        control_id=control_id,
        db=db,
    )

    session_result = await db.execute(
        select(ControlClosureSession)
        .where(
            ControlClosureSession.project_id == project_id,
            ControlClosureSession.assessment_id == assessment_id,
            ControlClosureSession.control_id == control_id,
        )
        .order_by(ControlClosureSession.created_at.desc())
    )
    latest_session = session_result.scalars().first()

    approvals: list[ArtifactApproval] = []
    generated_documents: list[dict[str, Any]] = []
    if latest_session:
        approvals_result = await db.execute(
            select(ArtifactApproval)
            .where(ArtifactApproval.session_id == latest_session.id)
            .order_by(ArtifactApproval.id.asc())
        )
        approvals = list(approvals_result.scalars().all())
        docs = await _load_documents(list(latest_session.generated_artifact_ids or []), db)
        generated_documents = [
            {
                "document_id": doc.id,
                "filename": doc.filename,
                "document_type": doc.document_type,
                "download_url": _document_download_url(project_id, doc.id),
                "artifact_title": next(
                    (
                        approval.artifact_title
                        for approval in approvals
                        if approval.document_id == doc.id
                    ),
                    doc.filename,
                ),
                "artifact_type": next(
                    (
                        approval.artifact_type
                        for approval in approvals
                        if approval.document_id == doc.id
                    ),
                    doc.document_type or "draft",
                ),
                "approval_status": next(
                    (
                        approval.overall_status
                        for approval in approvals
                        if approval.document_id == doc.id
                    ),
                    "pending_review",
                ),
            }
            for doc in docs
        ]

    artifact_titles = [doc["artifact_title"] for doc in generated_documents] or [
        artifact["title"] for artifact in _build_draft_package_artifacts(
            control_id=control_id,
            control_title=finding.control_title or control_id,
            remediation_plan=finding.remediation_plan or "",
            guidance=guidance,
        )
    ]
    next_step = next(
        (
            {
                "role": step.get("role"),
                "label": step.get("label"),
                "status": step.get("status"),
            }
            for approval in approvals
            for step in approval.approval_chain
            if step.get("status") == "pending"
        ),
        None,
    )

    return {
        "control_id": control_id,
        "control_title": finding.control_title,
        "determination": finding.status,
        "confidence": finding.confidence_score,
        "state": _draft_package_state(latest_session, approvals),
        "recommended_artifact_types": guidance.get("recommended_artifact_types") or [],
        "generated_artifacts": generated_documents,
        "latest_session": _session_to_dict(latest_session, approvals) if latest_session else None,
        "owner_review_instructions": _draft_owner_review_instructions(control_id),
        "coverage_map": _coverage_map_from_guidance(
            control_id=control_id,
            guidance=guidance,
            artifact_titles=artifact_titles,
        ),
        "source_provenance": {
            "gaps": "control_finding.gaps",
            "remediation_plan": "control_finding.remediation_plan",
            "closure_recommendations": "closure_guidance.objective_contracts",
            "collection_guidance": "tool_guidance + system_knowledge",
        },
        "next_approval_step": next_step,
        "safety": {
            "draft_label": "AI-generated draft for control-owner review",
            "not_evidence_of_record": True,
            "requires_human_review": True,
            "requires_supporting_records": True,
        },
    }


async def generate_control_draft_package(
    *,
    project_id: int,
    assessment_id: int,
    control_id: str,
    created_by: int,
    preparer_name: str,
    project_upload_dir: str,
    db: AsyncSession,
) -> dict[str, Any]:
    finding_result = await db.execute(
        select(ControlFinding).where(
            ControlFinding.assessment_id == assessment_id,
            ControlFinding.control_id == control_id,
        )
    )
    finding = finding_result.scalar_one_or_none()
    if not finding:
        raise ValueError(f"No finding for control {control_id} in assessment {assessment_id}")
    if finding.status == "compliant":
        raise ValueError(f"Control {control_id} is already compliant")

    guidance = await get_closure_guidance(
        project_id=project_id,
        assessment_id=assessment_id,
        control_id=control_id,
        db=db,
    )
    artifacts = _build_draft_package_artifacts(
        control_id=control_id,
        control_title=finding.control_title or control_id,
        remediation_plan=finding.remediation_plan or "",
        guidance=guidance,
    )
    session = ControlClosureSession(
        project_id=project_id,
        assessment_id=assessment_id,
        control_id=control_id,
        control_family=control_id.split("-")[0],
        control_title=finding.control_title,
        current_status=finding.status,
        session_status="artifact_pending",
        steps=[
            {
                "role": "ai",
                "step_type": "summary",
                "content": {
                    "mode": "draft_package",
                    "message": "Generated a draft artifact package for control-owner review.",
                },
                "timestamp": _now_iso(),
            }
        ],
        context_summary=(
            f"Control owner draft package for {control_id}. "
            f"Current determination: {finding.status}. "
            f"Gaps: {'; '.join(str(g) for g in (finding.gaps or [])[:6]) or 'No explicit gap text recorded.'}"
        ),
        implementation_summary=finding.implementation_statement or "",
        recommended_artifacts=artifacts,
        closure_notes=(
            "AI-generated draft package. For control-owner review only. "
            "Do not treat as evidence of record until approved and backed by supporting records."
        ),
        created_by=created_by,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    await generate_artifacts(
        session_id=session.id,
        preparer_name=preparer_name,
        project_upload_dir=project_upload_dir,
        db=db,
        approval_chain=_draft_package_approval_chain(preparer_name),
        draft_package_meta={
            "control_id": control_id,
            "control_title": finding.control_title,
            "gaps": list(finding.gaps or []),
            "recommended_artifact_types": guidance.get("recommended_artifact_types") or [],
        },
    )
    return await get_control_draft_package(
        project_id=project_id,
        assessment_id=assessment_id,
        control_id=control_id,
        db=db,
    )


async def get_assessment_draft_package_report(
    *,
    project_id: int,
    assessment_id: int,
    db: AsyncSession,
) -> dict[str, Any]:
    findings_result = await db.execute(
        select(ControlFinding).where(ControlFinding.assessment_id == assessment_id)
    )
    findings = list(findings_result.scalars().all())
    action_needed = [
        finding
        for finding in findings
        if finding.status in {"non_compliant", "partially_compliant"} or finding.needs_manual_review
    ]
    controls: list[dict[str, Any]] = []
    for finding in sorted(action_needed, key=lambda item: item.control_id):
        package = await get_control_draft_package(
            project_id=project_id,
            assessment_id=assessment_id,
            control_id=finding.control_id,
            db=db,
        )
        controls.append(
            {
                "control_id": finding.control_id,
                "control_title": finding.control_title,
                "family": finding.control_family,
                "determination": finding.status,
                "state": package["state"],
                "generated_artifact_count": len(package["generated_artifacts"]),
                "next_approval_step": package["next_approval_step"],
                "gaps": list(finding.gaps or []),
                "coverage_map": package["coverage_map"],
                "generated_artifacts": package["generated_artifacts"],
            }
        )
    return {
        "assessment_id": assessment_id,
        "summary": {
            "controls_needing_action": len(action_needed),
            "drafts_generated": sum(1 for item in controls if item["generated_artifact_count"] > 0),
            "awaiting_owner_review": sum(1 for item in controls if item["state"] == "owner_review"),
            "approved_drafts": sum(1 for item in controls if item["state"] == "approved"),
        },
        "controls": controls,
    }


async def prove_control_closure(
    *,
    project_id: int,
    assessment_id: int,
    control_id: str,
    persist_documents: bool,
    db: AsyncSession,
) -> dict[str, Any]:
    assessment = (
        await db.execute(
            select(Assessment)
            .options(selectinload(Assessment.policy).selectinload(AssessmentPolicy.buckets))
            .where(
                Assessment.id == assessment_id,
                Assessment.project_id == project_id,
            )
        )
    ).scalars().first()
    if not assessment:
        raise ValueError("Assessment not found")

    finding = (
        await db.execute(
            select(ControlFinding).where(
                ControlFinding.assessment_id == assessment_id,
                ControlFinding.control_id == control_id,
            )
        )
    ).scalars().first()
    if not finding:
        raise ValueError("Control finding not found in this assessment")

    criteria = (
        await db.execute(
            select(AssessmentCriteriaPackage).where(
                AssessmentCriteriaPackage.assessment_id == assessment_id,
                AssessmentCriteriaPackage.control_id == control_id,
            )
        )
    ).scalars().first()
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalars().first()
    profile = (
        await db.execute(select(SystemProfile).where(SystemProfile.project_id == project_id))
    ).scalars().first()

    merged_objectives = _merge_finding_and_criteria_objectives(
        control_id=control_id,
        gaps=finding.gaps or [],
        assessment_objectives=(criteria.assessment_objectives if criteria else []) or [],
    )
    system_name, system_context = _build_project_context(project, profile)
    guidance = build_control_closure_guidance(
        control_id=control_id,
        control_title=finding.control_title,
        gaps=merged_objectives,
        system_name=system_name,
        current_status=finding.status,
        mode="synthetic",
    )

    proof_document_types = _proof_document_types(control_id, guidance)
    upload_dir = Path("C:/temp")
    # Use the real configured upload directory tree under the project so ingestion works normally.
    from app.core.config import get_settings
    settings = get_settings()
    upload_dir = Path(settings.upload_dir) / str(project_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    proof_documents: list[dict[str, Any]] = []
    timestamp = datetime.now(UTC).strftime('%Y%m%d%H%M%S')
    for idx, document_type in enumerate(proof_document_types, start=1):
        artifact_label = {
            "policy": "Policy Closure Proof Artifact",
            "ssp_narrative": "System Documentation Closure Proof Artifact",
            "technical_artifact": "Technical Closure Proof Artifact",
            "procedure": "Procedure Closure Proof Artifact",
        }.get(document_type, "Closure Proof Artifact")
        artifact_title = f"{control_id} {artifact_label}"
        sections = build_contract_sections(
            contracts=guidance["objective_contracts"],
            system_name=system_name,
            document_type=document_type,
            intro_title=artifact_title,
            intro_text=(
                f"This deterministic proof artifact targets {control_id} for {system_name}. "
                "It is generated specifically to satisfy the full assessment objective set and is used to validate whether "
                "ATO Bot can close the control under the current engine."
            ),
        )
        doc_bytes = _build_docx(artifact_title, sections, system_name)
        proof_filename = (
            f"PROOF_{assessment_id}_{control_id.replace('(', '').replace(')', '').replace('/', '_')}_{document_type}_{idx}_{timestamp}.docx"
        )
        proof_doc_id = await _save_doc(
            file_bytes=doc_bytes,
            filename=proof_filename,
            project_id=project_id,
            upload_dir=upload_dir,
            created_by=assessment.started_by,
            control_id=control_id,
            document_type=document_type,
            document_intent="implements",
            controls_addressed=[control_id],
            source_assessment_id=assessment_id,
            trigger_parse=False,
        )
        await dispatch_parse(proof_doc_id)
        parse_status = await _wait_for_document_index(proof_doc_id)
        proof_documents.append(
            {
                "id": proof_doc_id,
                "filename": proof_filename,
                "document_type": document_type,
                "parse_status": parse_status,
            }
        )

    failed_parse = next((doc for doc in proof_documents if doc["parse_status"] not in {"indexed", "complete"}), None)
    if failed_parse:
        if not persist_documents:
            for proof_document in proof_documents:
                proof_doc = await db.get(Document, proof_document["id"])
                if proof_doc:
                    try:
                        Path(proof_doc.file_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                    await db.delete(proof_doc)
            await db.commit()
        return {
            "assessment_id": assessment_id,
            "control_id": control_id,
            "passed": False,
            "parse_status": failed_parse["parse_status"],
            "error": "Proof document failed to ingest cleanly.",
            "proof_documents": proof_documents,
            "guidance": guidance,
        }

    proof_assessment = Assessment(
        project_id=project_id,
        status="running",
        llm_provider=assessment.llm_provider,
        llm_model=assessment.llm_model,
        context_strategy=assessment.context_strategy,
        skip_stage3=assessment.skip_stage3,
        carry_forward_compliant=False,
        started_at=datetime.now(UTC),
        name=f"Proof - {control_id}",
        started_by=assessment.started_by,
        policy_id=assessment.policy_id,
        policy_version=assessment.policy_version,
    )
    db.add(proof_assessment)
    await db.flush()

    provider, _runtime = await build_provider_for_purpose(
        db,
        "assessment_reasoning",
        provider_name=assessment.llm_provider,
        model=assessment.llm_model,
    )
    scope_doc_ids = await build_scope_document_ids(project_id, db)
    evidence_index = await preload_evidence_index(project_id, scope_doc_ids, db)
    control = _build_control_namespace(control_id=control_id, finding=finding, criteria=criteria)
    result = await assess_control_with_assessor_pipeline(
        assessment_id=proof_assessment.id,
        project_id=project_id,
        control=control,
        system_context=system_context,
        llm=provider,
        db=db,
        evidence_index=evidence_index,
        skip_stage3=assessment.skip_stage3,
        policy_runtime=build_policy_runtime(assessment.policy),
    )

    proof_assessment.status = "complete"
    proof_assessment.completed_at = datetime.now(UTC)
    await db.commit()

    response = {
        "assessment_id": assessment_id,
        "control_id": control_id,
        "source_status": finding.status,
        "proof_assessment_id": proof_assessment.id,
        "proof_document_id": proof_documents[0]["id"] if proof_documents else None,
        "proof_document_filename": proof_documents[0]["filename"] if proof_documents else None,
        "parse_status": proof_documents[0]["parse_status"] if proof_documents else "missing",
        "proof_documents": proof_documents,
        "passed": bool(result and result.status == "compliant"),
        "result_status": result.status if result else "not_reviewed",
        "confidence": result.confidence if result else 0.0,
        "remaining_gaps": result.gaps if result else ["No result returned from assessment pipeline."],
        "llm_dissent": result.llm_challenge_note if result else "",
        "guidance": guidance,
    }

    if not persist_documents:
        for proof_document in proof_documents:
            proof_doc = await db.get(Document, proof_document["id"])
            if proof_doc:
                try:
                    Path(proof_doc.file_path).unlink(missing_ok=True)
                except Exception:
                    pass
                await db.delete(proof_doc)
        await db.execute(delete(Assessment).where(Assessment.id == proof_assessment.id))
        await db.commit()

    return response


def _default_approval_chain(preparer_name: str = "System User") -> list[dict]:
    """Build the default four-step RMF approval chain."""
    return [
        {
            "step": 0,
            "role": "preparer",
            "label": "Preparer",
            "name": preparer_name,
            "title": "",
            "organization": "",
            "status": "approved",   # auto-approved — the user who started the session
            "comments": "Artifact prepared as part of control closure workflow.",
            "completed_at": _now_iso(),
        },
        {
            "step": 1,
            "role": "reviewer",
            "label": "Technical Reviewer",
            "name": "",
            "title": "",
            "organization": "",
            "status": "pending",
            "comments": "",
            "completed_at": None,
        },
        {
            "step": 2,
            "role": "isso",
            "label": "Information System Security Officer (ISSO)",
            "name": "",
            "title": "ISSO",
            "organization": "",
            "status": "pending",
            "comments": "",
            "completed_at": None,
        },
        {
            "step": 3,
            "role": "system_owner",
            "label": "System Owner",
            "name": "",
            "title": "System Owner",
            "organization": "",
            "status": "pending",
            "comments": "",
            "completed_at": None,
        },
    ]


# ── LLM call wrapper ───────────────────────────────────────────────────────────

async def _llm_call(system_prompt: str, user_message: str, assessment_id: int, db: AsyncSession) -> str:
    result = await db.execute(
        select(Assessment.llm_provider, Assessment.llm_model)
        .where(Assessment.id == assessment_id)
    )
    row = result.one_or_none()
    provider = row[0] if row else "ollama"
    model = row[1] if row else "llama3"
    llm, _runtime = await build_provider_for_purpose(
        db,
        "assessment_reasoning",
        provider_name=provider,
        model=model,
    )
    return await llm.complete(system_prompt, user_message)


def _parse_json_safe(text: str) -> dict | list:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    start = text.find("{")
    if start == -1:
        start = text.find("[")
    end = max(text.rfind("}"), text.rfind("]")) + 1
    if start != -1 and end > start:
        text = text[start:end]
    return json.loads(text)


# ── Public service functions ───────────────────────────────────────────────────

async def start_session(
    project_id: int,
    assessment_id: int,
    control_id: str,
    created_by: int,
    db: AsyncSession,
) -> dict:
    """Create a new closure session and generate the AI opening interview."""
    # Load the control finding
    result = await db.execute(
        select(ControlFinding)
        .where(
            ControlFinding.assessment_id == assessment_id,
            ControlFinding.control_id == control_id,
        )
    )
    finding = result.scalar_one_or_none()
    if not finding:
        raise ValueError(f"No finding for control {control_id} in assessment {assessment_id}")
    if finding.status == "compliant":
        raise ValueError(f"Control {control_id} is already compliant")

    # Format gaps for prompt
    gaps = finding.gaps or []
    if isinstance(gaps, str):
        gaps = [gaps]
    gaps_text = "\n".join(f"- {g}" for g in gaps[:20]) if gaps else "- No specific gaps documented"
    criteria_result = await db.execute(
        select(AssessmentCriteriaPackage.assessment_objectives).where(
            AssessmentCriteriaPackage.assessment_id == assessment_id,
            AssessmentCriteriaPackage.control_id == control_id,
        )
    )
    assessment_objectives = criteria_result.scalar_one_or_none() or []

    rem_plan = finding.remediation_plan or "No remediation plan documented yet."
    guidance = build_control_closure_guidance(
        control_id=control_id,
        control_title=finding.control_title or control_id,
        gaps=_merge_finding_and_criteria_objectives(
            control_id=control_id,
            gaps=gaps,
            assessment_objectives=assessment_objectives,
        ),
        system_name="the system",
        current_status=finding.status,
        mode="live",
    )

    user_msg = f"""Control: {control_id} — {finding.control_title}
Current Status: {finding.status}
Implementation Statement: {finding.implementation_statement or 'Not documented'}

Identified Compliance Gaps:
{gaps_text}

Existing Remediation Plan:
{rem_plan}

Use the following closure guidance to ask only for facts that will make the control pass:
{format_contracts_for_prompt(guidance["objective_contracts"])}

Generate your opening interview questions."""

    interview_data = _build_initial_interview_data(control_id, guidance)

    # Legacy LLM interview generation is disabled on session start for performance.
    """
    if False:
        raw = await _llm_call(INTERVIEW_SYSTEM_PROMPT, user_msg, assessment_id, db)
        interview_data = _parse_json_safe(raw)
    except Exception as exc:
        logger.warning("Interview LLM call failed: %s", exc)
        interview_data = {
            "intro": f"Let's gather information to close the gaps for {control_id}.",
            "questions": [
                {
                    "id": "q1",
                    "text": "What tools or systems are currently used to implement this control?",
                    "type": "text",
                    "placeholder": "e.g., Active Directory, Okta, manual process...",
                    "nist_context": "Establishes what implementation evidence is available",
                },
                {
                    "id": "q2",
                    "text": "Is there a documented procedure or policy covering this control?",
                    "type": "dropdown",
                    "options": ["Yes — fully documented", "Yes — partially documented", "No — undocumented"],
                    "nist_context": "Determines whether a procedure artifact is needed",
                },
                {
                    "id": "q3",
                    "text": "Who is the responsible role for this control?",
                    "type": "dropdown",
                    "options": ["ISSO", "System Administrator", "System Owner", "HR", "IT Operations", "Security Operations"],
                    "nist_context": "Identifies the responsible role for the implementation statement",
                },
            ],
        }

    """

    # Build initial steps
    steps = [
        {
            "role": "ai",
            "step_type": "question",
            "content": interview_data,
            "timestamp": _now_iso(),
        }
    ]

    session = ControlClosureSession(
        project_id=project_id,
        assessment_id=assessment_id,
        control_id=control_id,
        control_family=control_id.split("-")[0],
        control_title=finding.control_title,
        current_status=finding.status,
        session_status="active",
        steps=steps,
        created_by=created_by,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _session_to_dict(session)


async def submit_answers(
    session_id: int,
    answers: dict[str, Any],
    db: AsyncSession,
) -> dict:
    """Process user answers and either ask follow-up questions or return artifact plan."""
    result = await db.execute(select(ControlClosureSession).where(ControlClosureSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise ValueError("Session not found")

    steps = list(session.steps or [])
    steps.append({
        "role": "user",
        "step_type": "answer",
        "content": answers,
        "timestamp": _now_iso(),
    })

    # Build context from all Q&A so far
    all_qa = []
    for step in steps:
        if step["role"] == "ai" and step["step_type"] == "question":
            q_data = step["content"]
            all_qa.append(f"AI: {q_data.get('intro', '')}")
            for q in q_data.get("questions", []):
                all_qa.append(f"  Q ({q['id']}): {q['text']}")
        elif step["role"] == "user" and step["step_type"] == "answer":
            for qid, ans in step["content"].items():
                all_qa.append(f"  A ({qid}): {ans}")

    qa_text = "\n".join(all_qa)

    # Load finding for gaps
    result2 = await db.execute(
        select(ControlFinding)
        .where(
            ControlFinding.assessment_id == session.assessment_id,
            ControlFinding.control_id == session.control_id,
        )
    )
    finding = result2.scalar_one_or_none()
    gaps = finding.gaps or [] if finding else []
    if isinstance(gaps, str):
        gaps = [gaps]
    gaps_text = "\n".join(f"- {g}" for g in gaps[:20]) if gaps else "- No specific gaps documented"
    criteria_result = await db.execute(
        select(AssessmentCriteriaPackage.assessment_objectives).where(
            AssessmentCriteriaPackage.assessment_id == session.assessment_id,
            AssessmentCriteriaPackage.control_id == session.control_id,
        )
    )
    assessment_objectives = criteria_result.scalar_one_or_none() or []
    guidance = build_control_closure_guidance(
        control_id=session.control_id,
        control_title=session.control_title,
        gaps=_merge_finding_and_criteria_objectives(
            control_id=session.control_id,
            gaps=gaps,
            assessment_objectives=assessment_objectives,
        ),
        system_name="the system",
        current_status=session.current_status,
        mode="live",
    )

    user_msg = f"""Control: {session.control_id} — {session.control_title}
Status: {session.current_status}

Identified Compliance Gaps:
{gaps_text}

Interview Exchange So Far:
{qa_text}

Use this closure contract when deciding whether enough facts have been gathered and what the artifact should contain:
{format_contracts_for_prompt(guidance["objective_contracts"])}

Analyze the answers and determine next steps."""

    try:
        raw = await _llm_call(ANALYSIS_SYSTEM_PROMPT, user_msg, session.assessment_id, db)
        analysis = _parse_json_safe(raw)
    except Exception as exc:
        logger.warning("Analysis LLM call failed: %s", exc)
        analysis = {
            "ready_to_generate": True,
            "implementation_summary": f"Implementation information gathered for {session.control_id}.",
            "follow_up_questions": [],
            "recommended_artifacts": [
                {
                    "title": f"{session.control_id} — Implementation Procedure",
                    "artifact_type": "procedure",
                    "purpose": "Documents the step-by-step implementation procedure for the control",
                    "controls_addressed": [session.control_id],
                    "key_content_from_interview": qa_text[:500],
                }
            ],
        }

    ready = analysis.get("ready_to_generate", False)

    if ready:
        steps.append({
            "role": "ai",
            "step_type": "plan",
            "content": analysis,
            "timestamp": _now_iso(),
        })
        session.session_status = "artifact_pending"
        session.implementation_summary = analysis.get("implementation_summary", "")
        session.recommended_artifacts = analysis.get("recommended_artifacts", [])
        session.context_summary = qa_text
    else:
        # Need more info — ask follow-up questions
        follow_ups = analysis.get("follow_up_questions", [])
        follow_up_data = {
            "intro": "A few more details are needed:",
            "questions": follow_ups,
        }
        steps.append({
            "role": "ai",
            "step_type": "question",
            "content": follow_up_data,
            "timestamp": _now_iso(),
        })

    session.steps = steps
    await db.commit()
    await db.refresh(session)
    approvals_result = await db.execute(
        select(ArtifactApproval).where(ArtifactApproval.session_id == session_id)
    )
    approvals = approvals_result.scalars().all()
    return _session_to_dict(session, approvals)


async def generate_artifacts(
    session_id: int,
    preparer_name: str,
    project_upload_dir: str,
    db: AsyncSession,
    approval_chain: list[dict] | None = None,
    draft_package_meta: dict[str, Any] | None = None,
) -> dict:
    """Generate Word artifacts for all recommended artifacts in the session."""
    from app.services.remediation_service import (
        _json_to_docx,
        _save_document,
        _build_artifact_content_prompt,
        _strip_md_fences,
    )

    result = await db.execute(select(ControlClosureSession).where(ControlClosureSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise ValueError("Session not found")
    upload_dir = Path(project_upload_dir)

    artifacts = session.recommended_artifacts or []
    if not artifacts:
        raise ValueError("No recommended artifacts — complete the interview first")

    generated_ids: list[int] = list(session.generated_artifact_ids or [])
    approvals: list[dict] = []
    date_str = datetime.now(UTC).strftime("%B %d, %Y")

    for art in artifacts:
        art_title = art.get("title", f"{session.control_id} Artifact")
        art_type = art.get("artifact_type", "policy_procedure")
        key_content = art.get("key_content_from_interview", "")
        purpose = art.get("purpose", "")
        controls = art.get("controls_addressed", [session.control_id])

        # Build system prompt
        content_system_prompt = _build_artifact_content_prompt(art_type)

        # Build user message with interview context baked in
        user_msg = f"""Generate artifact: {art_title}
Artifact Type: {art_type}
Controls Addressed: {', '.join(controls)}
Purpose: {purpose}

INTERVIEW CONTEXT — incorporate these specific facts:
{session.context_summary or ''}

Key Implementation Details:
{key_content}

Implementation Summary:
{session.implementation_summary or ''}

Identified Gaps to Close:
"""
        # Add gaps from finding
        finding_result = await db.execute(
            select(ControlFinding)
            .where(
                ControlFinding.assessment_id == session.assessment_id,
                ControlFinding.control_id == session.control_id,
            )
        )
        finding = finding_result.scalar_one_or_none()
        gaps = []
        if finding:
            gaps = finding.gaps or []
            if isinstance(gaps, str):
                gaps = [gaps]
            user_msg += "\n".join(f"- {g}" for g in gaps[:20])
        criteria_result = await db.execute(
            select(AssessmentCriteriaPackage.assessment_objectives).where(
                AssessmentCriteriaPackage.assessment_id == session.assessment_id,
                AssessmentCriteriaPackage.control_id == session.control_id,
            )
        )
        assessment_objectives = criteria_result.scalar_one_or_none() or []
        control_guidance = build_control_closure_guidance(
            control_id=session.control_id,
            control_title=session.control_title,
            gaps=_merge_finding_and_criteria_objectives(
                control_id=session.control_id,
                gaps=gaps,
                assessment_objectives=assessment_objectives,
            ),
            system_name="the system",
            current_status=session.current_status,
            mode="live",
        )
        user_msg += (
            "\n\nUse this objective closure contract. The artifact must explicitly satisfy these facts and should resemble "
            "the concrete example response for each objective:\n"
            f"{format_contracts_for_prompt(control_guidance['objective_contracts'])}"
        )

        # Call LLM
        try:
            raw_content = await _llm_call(ARTIFACT_GEN_SYSTEM_PROMPT, user_msg, session.assessment_id, db)
            content_json = _strip_md_fences(raw_content)
        except Exception as exc:
            logger.warning("Artifact generation failed for %s: %s", art_title, exc)
            content_json = json.dumps({
                "title": art_title,
                "sections": [{"type": "paragraph", "text": f"Generation error — retry. {exc}"}],
            })
        content_json = _normalize_generated_sections(
            content_json=content_json,
            title=art_title,
            system_name="the system",
            control_guidance=control_guidance,
        )
        if draft_package_meta:
            content_json = _prepend_draft_review_sections(
                content_json=content_json,
                control_id=draft_package_meta.get("control_id") or session.control_id,
                control_title=draft_package_meta.get("control_title") or session.control_title,
                gaps=list(draft_package_meta.get("gaps") or []),
            )

        # Build Word document
        import re
        safe_name = re.sub(r"[^\w\s-]", "", art_title).strip().replace(" ", "_")[:60] + ".docx"
        try:
            docx_bytes = _json_to_docx(
                title=art_title,
                subtitle=session.control_title,
                json_content=content_json,
                generated_date=date_str,
            )
            doc_id = await _save_document(
                file_bytes=docx_bytes,
                filename=safe_name,
                file_ext="docx",
                project_id=session.project_id,
                assessment_id=session.assessment_id,
                report_id=None,
                created_by=session.created_by,
                upload_dir=upload_dir,
                controls_addressed=[session.control_id],
                document_type="docx",
                document_intent="ai_draft_control_owner_review",
            )
            generated_ids.append(doc_id)

            # Create approval record
            approval = ArtifactApproval(
                session_id=session_id,
                document_id=doc_id,
                control_id=session.control_id,
                artifact_title=art_title,
                artifact_type=art_type,
                approval_chain=list(approval_chain or _default_approval_chain(preparer_name)),
                current_step=1,  # Reviewer is up next
                overall_status="pending_review",
                evidence_eligibility="draft",
            )
            db.add(approval)
            approvals.append(approval)
        except Exception as exc:
            logger.error("Failed to save artifact %s: %s", art_title, exc)

    session.generated_artifact_ids = generated_ids
    session.session_status = "in_approval"
    await db.commit()
    await db.refresh(session)

    approvals_result = await db.execute(
        select(ArtifactApproval).where(ArtifactApproval.session_id == session_id)
    )
    all_approvals = approvals_result.scalars().all()
    return _session_to_dict(session, all_approvals)


async def advance_approval(
    approval_id: int,
    approver_name: str,
    approver_title: str,
    approver_org: str,
    action: str,          # "approve" | "reject"
    comments: str,
    db: AsyncSession,
) -> dict:
    """Record an approver's decision and advance the chain."""
    result = await db.execute(select(ArtifactApproval).where(ArtifactApproval.id == approval_id))
    approval = result.scalar_one_or_none()
    if not approval:
        raise ValueError("Approval not found")

    chain = list(approval.approval_chain)
    current_step = approval.current_step

    if current_step >= len(chain):
        raise ValueError("All approval steps already complete")

    step = chain[current_step]
    step["name"] = approver_name
    step["title"] = approver_title
    step["organization"] = approver_org
    step["status"] = "approved" if action == "approve" else "rejected"
    step["comments"] = comments
    step["completed_at"] = _now_iso()
    chain[current_step] = step

    if action == "reject":
        approval.approval_chain = chain
        approval.overall_status = "rejected"
        await db.commit()
        return _approval_to_dict(approval)

    # Advance to next step
    next_step = current_step + 1
    approval.current_step = next_step
    approval.approval_chain = chain

    if next_step >= len(chain):
        approval.overall_status = "approved"
    else:
        approval.overall_status = "in_review"

    await db.commit()
    await db.refresh(approval)
    return _approval_to_dict(approval)


async def complete_session(
    session_id: int,
    closure_notes: str,
    db: AsyncSession,
) -> dict:
    """Mark a session as closed and return the final summary."""
    result = await db.execute(
        select(ControlClosureSession).where(ControlClosureSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise ValueError("Session not found")

    session.session_status = "closed"
    session.closure_notes = closure_notes
    await db.commit()
    await db.refresh(session)

    approvals_result = await db.execute(
        select(ArtifactApproval).where(ArtifactApproval.session_id == session_id)
    )
    approvals = approvals_result.scalars().all()
    return _session_to_dict(session, approvals)
