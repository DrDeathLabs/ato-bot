"""Prompt Manager — loads prompts from DB overrides, falls back to hardcoded defaults."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import AsyncSessionLocal

# ── In-memory cache (cleared on save) ────────────────────────────────────────
_cache: dict[str, str] = {}


# ── Default prompts registry ──────────────────────────────────────────────────
# Imported lazily to avoid circular deps with base.py

def _assessment_system_default() -> str:
    from app.services.llm.base import ASSESSMENT_SYSTEM_PROMPT
    return ASSESSMENT_SYSTEM_PROMPT


def _control_tagging_default() -> str:
    from app.services.control_tagger import CONTROL_TAGGING_SYSTEM_PROMPT
    return CONTROL_TAGGING_SYSTEM_PROMPT


def _ingestion_screening_default() -> str:
    from app.services.ingestion.llm_screener import SCREENING_SYSTEM_PROMPT
    return SCREENING_SYSTEM_PROMPT


def _gap_analysis_default() -> str:
    from app.services.multistage_engine import GAP_ANALYSIS_SYSTEM_PROMPT
    return GAP_ANALYSIS_SYSTEM_PROMPT


def _narrative_default() -> str:
    from app.services.multistage_engine import NARRATIVE_SYSTEM_PROMPT
    return NARRATIVE_SYSTEM_PROMPT


def _verdict_challenge_default() -> str:
    from app.services.multistage_engine import VERDICT_CHALLENGE_SYSTEM_PROMPT
    return VERDICT_CHALLENGE_SYSTEM_PROMPT


def _section_prompt_default(key: str) -> str:
    from app.api.ai_assist import SECTION_PROMPTS
    return SECTION_PROMPTS.get(key, "")


def _procedure_categorization_default() -> str:
    from app.services.procedure_categorizer import CATEGORIZE_SYSTEM_PROMPT
    return CATEGORIZE_SYSTEM_PROMPT


def _remediation_guide_default() -> str:
    from app.services.remediation_service import REMEDIATION_GUIDE_SYSTEM_PROMPT
    return REMEDIATION_GUIDE_SYSTEM_PROMPT


def _remediation_artifact_planner_default() -> str:
    from app.services.remediation_service import ARTIFACT_PLANNER_SYSTEM_PROMPT
    return ARTIFACT_PLANNER_SYSTEM_PROMPT


def _remediation_artifact_evidence_default() -> str:
    from app.services.remediation_service import EVIDENCE_COLLECTION_SYSTEM_PROMPT
    return EVIDENCE_COLLECTION_SYSTEM_PROMPT


def _remediation_artifact_content_default() -> str:
    from app.services.remediation_service import ARTIFACT_CONTENT_BASE_PROMPT
    return ARTIFACT_CONTENT_BASE_PROMPT


def _assistant_general_default() -> str:
    from app.services.assistant_service import GENERAL_ASSISTANT_SYSTEM_PROMPT
    return GENERAL_ASSISTANT_SYSTEM_PROMPT


def _assistant_control_default() -> str:
    from app.services.assistant_service import CONTROL_ASSISTANT_SYSTEM_PROMPT
    return CONTROL_ASSISTANT_SYSTEM_PROMPT


def _assistant_remediation_default() -> str:
    from app.services.assistant_service import REMEDIATION_ASSISTANT_SYSTEM_PROMPT
    return REMEDIATION_ASSISTANT_SYSTEM_PROMPT


PROMPT_REGISTRY: dict[str, dict] = {
    # ── Assessment ────────────────────────────────────────────────────────────
    "assessment_system": {
        "label": "Assessment System Prompt",
        "category": "Assessment",
        "runtime_purpose": "assessment_reasoning",
        "used_by": [
            "Primary control assessment and structured verdict generation",
        ],
        "description": (
            "Main system prompt sent to the LLM before every control assessment. "
            "Defines the decision framework, status criteria, output JSON schema, and rules."
        ),
        "default_fn": _assessment_system_default,
    },
    "control_tagging": {
        "label": "Control Tagging System Prompt",
        "category": "Ingestion",
        "runtime_purpose": "document_tagging",
        "used_by": [
            "Older full-document tagging and chunk-to-control mapping",
        ],
        "description": (
            "System prompt used when tagging document chunks with NIST 800-53 Rev 5 control IDs at ingestion time. "
            "Instructs the LLM to return a JSON array of {control_id, confidence, notes} for each chunk."
        ),
        "default_fn": lambda: _control_tagging_default(),
    },
    "ingestion_screening": {
        "label": "Ingestion Screening Prompt",
        "category": "Ingestion",
        "runtime_purpose": "ingestion_screening",
        "used_by": [
            "Stage 2 parsed-line and cell screening before expansion",
        ],
        "description": (
            "System prompt for Stage 2 of the ingestion pipeline. "
            "It asks the reasoning model to screen parsed text units for plausible NIST 800-53 relevance "
            "before context expansion."
        ),
        "default_fn": lambda: _ingestion_screening_default(),
    },
    "procedure_categorization": {
        "label": "Procedure Categorization System Prompt",
        "category": "Ingestion",
        "runtime_purpose": "procedure_categorization",
        "used_by": [
            "Enterprise procedure library auto-categorization",
        ],
        "description": (
            "System prompt used to classify an uploaded enterprise procedure document into one of the "
            "defined procedure categories (access_management, change_management, incident_management, etc.). "
            "Runs once per procedure document at upload time."
        ),
        "default_fn": lambda: _procedure_categorization_default(),
    },
    "gap_analysis_system": {
        "label": "Gap Analysis System Prompt (Stage 2)",
        "category": "Multi-Stage Assessment",
        "runtime_purpose": "assessment_reasoning",
        "used_by": [
            "Objective-by-objective evidence evaluation in the multi-stage assessment flow",
        ],
        "description": (
            "System prompt for Stage 2 of the multi-stage engine. "
            "Instructs the LLM to evaluate each NIST 800-53A assessment objective "
            "against the evidence and return a structured JSON gap matrix."
        ),
        "default_fn": lambda: _gap_analysis_default(),
    },
    "narrative_system": {
        "label": "Narrative Writing System Prompt (Stage 3)",
        "category": "Multi-Stage Assessment",
        "runtime_purpose": "assessment_reasoning",
        "used_by": [
            "SSP implementation statements, gaps, and remediation narratives",
        ],
        "description": (
            "System prompt for Stage 3 of the multi-stage engine. "
            "Given a pre-determined verdict and gap analysis, instructs the LLM "
            "to write the formal SSP implementation statement, gaps, and remediation plan."
        ),
        "default_fn": lambda: _narrative_default(),
    },
    "verdict_challenge": {
        "label": "Verdict Challenge System Prompt (Stage 2.5)",
        "category": "Multi-Stage Assessment",
        "runtime_purpose": "assessment_reasoning",
        "used_by": [
            "Challenge review that questions weak or inconsistent verdicts",
        ],
        "description": (
            "System prompt for the assessor challenge stage. "
            "It reviews the code-calculated verdict and flags only clear objective-level "
            "mistakes for human follow-up."
        ),
        "default_fn": lambda: _verdict_challenge_default(),
    },
    # ── Remediation ───────────────────────────────────────────────────────────
    "remediation_guide_system": {
        "label": "Remediation Guide System Prompt",
        "category": "Remediation",
        "runtime_purpose": "remediation_generation",
        "used_by": [
            "Post-assessment remediation guide generation",
        ],
        "description": (
            "System prompt used when generating post-assessment remediation guides. "
            "Instructs the LLM to return a JSON array of specific, actionable remediation steps "
            "with responsible roles, effort estimates, success criteria, and template language."
        ),
        "default_fn": lambda: _remediation_guide_default(),
    },
    "remediation_artifact_planner": {
        "label": "Artifact Planner System Prompt",
        "category": "Remediation",
        "runtime_purpose": "remediation_generation",
        "used_by": [
            "Artifact and supplement planning for remediation packages",
        ],
        "description": (
            "Phase 1 of artifact generation: determines which specific document types to create for each gap family. "
            "Returns a JSON array of planned artifacts (title, type, controls addressed, purpose, key sections). "
            "Types include: policy_procedure, completed_form, ssp_narrative, procedure, evidence_template, agreement_template."
        ),
        "default_fn": lambda: _remediation_artifact_planner_default(),
    },
    "remediation_artifact_evidence": {
        "label": "Artifact: Evidence Collection Prompt",
        "category": "Remediation",
        "runtime_purpose": "remediation_generation",
        "used_by": [
            "Evidence requirement planning for remediation artifacts",
        ],
        "description": (
            "Prompt used to gather and organize the evidence requirements that generated "
            "remediation artifacts must satisfy for the target control."
        ),
        "default_fn": lambda: _remediation_artifact_evidence_default(),
    },
    "remediation_artifact_policy_procedure": {
        "label": "Artifact: Policy & Procedure Generation",
        "category": "Remediation",
        "runtime_purpose": "remediation_generation",
        "used_by": [
            "Generated policy and procedure remediation documents",
        ],
        "description": (
            "Content generation prompt for formal policy and procedure documents. "
            "Used when the planner determines a policy_procedure artifact is needed."
        ),
        "default_fn": lambda: _remediation_artifact_content_default(),
    },
    "remediation_artifact_completed_form": {
        "label": "Artifact: Completed Form / Matrix Generation",
        "category": "Remediation",
        "runtime_purpose": "remediation_generation",
        "used_by": [
            "Generated completed forms, matrices, and registers",
        ],
        "description": (
            "Content generation prompt for completed forms, matrices, and registers "
            "(e.g., Engineering Principles Matrix, Authorized Software Register, RTM). "
            "Produces filled-in artifacts with representative data, not blank templates."
        ),
        "default_fn": lambda: _remediation_artifact_content_default(),
    },
    "remediation_artifact_ssp_narrative": {
        "label": "Artifact: SSP Narrative Generation",
        "category": "Remediation",
        "runtime_purpose": "remediation_generation",
        "used_by": [
            "Generated SSP addenda and implementation narratives",
        ],
        "description": (
            "Content generation prompt for System Security Plan implementation narratives. "
            "Produces implementation statements ready to insert into an SSP."
        ),
        "default_fn": lambda: _remediation_artifact_content_default(),
    },
    "remediation_artifact_procedure": {
        "label": "Artifact: Operational Procedure Generation",
        "category": "Remediation",
        "runtime_purpose": "remediation_generation",
        "used_by": [
            "Generated remediation procedures and operational supplements",
        ],
        "description": (
            "Content generation prompt for step-by-step operational procedures. "
            "Produces numbered, actionable procedures that technicians follow."
        ),
        "default_fn": lambda: _remediation_artifact_content_default(),
    },
    "remediation_artifact_evidence_template": {
        "label": "Artifact: Evidence Template Generation",
        "category": "Remediation",
        "runtime_purpose": "remediation_generation",
        "used_by": [
            "Generated evidence templates and sample records",
        ],
        "description": (
            "Content generation prompt for evidence record templates. "
            "Produces completed example evidence records (logs, checklists, test reports) "
            "showing what assessable evidence looks like."
        ),
        "default_fn": lambda: _remediation_artifact_content_default(),
    },
    "remediation_artifact_agreement_template": {
        "label": "Artifact: Agreement / Authorization Template Generation",
        "category": "Remediation",
        "runtime_purpose": "remediation_generation",
        "used_by": [
            "Generated agreements, authorizations, and interconnection artifacts",
        ],
        "description": (
            "Content generation prompt for inter-organizational agreements, MOUs, "
            "system connection authorizations, and similar bilateral documents."
        ),
        "default_fn": lambda: _remediation_artifact_content_default(),
    },
    # ── AI Assist notes ───────────────────────────────────────────────────────
    "control_notes": {
        "label": "Control Notes",
        "category": "AI Assist",
        "runtime_purpose": "ai_assist_notes",
        "used_by": [
            "Short analyst notes for individual control findings",
        ],
        "description": "System prompt for auto-generating analyst notes for a control finding.",
        "default_fn": lambda: _section_prompt_default("control_notes"),
    },
    "assessment_notes": {
        "label": "Assessment Notes",
        "category": "AI Assist",
        "runtime_purpose": "ai_assist_notes",
        "used_by": [
            "Assessment-level run summaries and wrap-up notes",
        ],
        "description": "System prompt for auto-generating an assessment run summary.",
        "default_fn": lambda: _section_prompt_default("assessment_notes"),
    },
    "applicability_rationale": {
        "label": "Applicability Rationale",
        "category": "AI Assist",
        "runtime_purpose": "ai_assist_notes",
        "used_by": [
            "Applicability rationale helpers for controls and profiles",
        ],
        "description": "System prompt for generating control applicability rationale text.",
        "default_fn": lambda: _section_prompt_default("applicability_rationale"),
    },
    "satisfied_rationale": {
        "label": "Satisfied Rationale",
        "category": "AI Assist",
        "runtime_purpose": "ai_assist_notes",
        "used_by": [
            "Rationale text when a control is marked satisfied",
        ],
        "description": "System prompt for generating rationale when a control is marked Satisfied.",
        "default_fn": lambda: _section_prompt_default("satisfied_rationale"),
    },
    "risk_rationale": {
        "label": "Risk Acceptance Rationale",
        "category": "AI Assist",
        "runtime_purpose": "ai_assist_notes",
        "used_by": [
            "Formal risk acceptance language helpers",
        ],
        "description": "System prompt for generating formal risk acceptance language.",
        "default_fn": lambda: _section_prompt_default("risk_rationale"),
    },
    "manual_status_rationale": {
        "label": "Manual Override Rationale",
        "category": "AI Assist",
        "runtime_purpose": "ai_assist_notes",
        "used_by": [
            "Manual override rationale and audit-ready explanation text",
        ],
        "description": "System prompt for generating rationale text for a manual status override.",
        "default_fn": lambda: _section_prompt_default("manual_status_rationale"),
    },
    "assistant_general": {
        "label": "Cyber Assistant: General",
        "category": "AI Assist",
        "runtime_purpose": "chat_general",
        "used_by": [
            "Global cyber and compliance chat from anywhere in the app",
        ],
        "description": "Base system prompt for the general Cyber Workspace Assistant.",
        "default_fn": lambda: _assistant_general_default(),
    },
    "assistant_workspace": {
        "label": "Cyber Assistant: Workspace",
        "category": "AI Assist",
        "runtime_purpose": "chat_workspace",
        "used_by": [
            "Project and assessment scoped chat sessions",
        ],
        "description": "Base system prompt for workspace-level project and assessment chat.",
        "default_fn": lambda: _assistant_general_default(),
    },
    "assistant_control": {
        "label": "Cyber Assistant: Control",
        "category": "AI Assist",
        "runtime_purpose": "chat_control",
        "used_by": [
            "Control, finding, and dissent conversations",
        ],
        "description": "System prompt for control-centric chat with evidence and finding context.",
        "default_fn": lambda: _assistant_control_default(),
    },
    "assistant_evidence": {
        "label": "Cyber Assistant: Evidence",
        "category": "AI Assist",
        "runtime_purpose": "chat_evidence",
        "used_by": [
            "Evidence and citation-specific conversations",
        ],
        "description": "System prompt for evidence-grounded chat around a selected artifact or excerpt.",
        "default_fn": lambda: _assistant_control_default(),
    },
    "assistant_remediation": {
        "label": "Cyber Assistant: Remediation",
        "category": "AI Assist",
        "runtime_purpose": "chat_remediation",
        "used_by": [
            "Remediation planning, package supplements, and test dataset guidance",
        ],
        "description": "System prompt for remediation-focused chat.",
        "default_fn": lambda: _assistant_remediation_default(),
    },
    "assistant_admin_explainer": {
        "label": "Cyber Assistant: Admin Explainer",
        "category": "AI Assist",
        "runtime_purpose": "chat_admin_explainer",
        "used_by": [
            "Explaining AI runtime and prompt settings in the admin experience",
        ],
        "description": "System prompt for admin/runtime explanation chat.",
        "default_fn": lambda: _assistant_general_default(),
    },
}


async def get_prompt(prompt_id: str, default: str) -> str:
    """Return DB override if present, else fall back to `default`."""
    if prompt_id in _cache:
        return _cache[prompt_id]
    try:
        from app.models.orm import PromptOverride
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PromptOverride).where(PromptOverride.id == prompt_id)
            )
            override = result.scalar_one_or_none()
            if override:
                _cache[prompt_id] = override.content
                return override.content
    except Exception:
        pass  # DB not ready yet — use default
    return default


async def save_prompt(prompt_id: str, content: str, updated_by: str) -> None:
    """Upsert a prompt override and invalidate cache."""
    from app.models.orm import PromptOverride
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PromptOverride).where(PromptOverride.id == prompt_id)
        )
        override = result.scalar_one_or_none()
        if override:
            override.content = content
            override.updated_at = datetime.now(UTC)
            override.updated_by = updated_by
        else:
            db.add(PromptOverride(
                id=prompt_id,
                content=content,
                updated_at=datetime.now(UTC),
                updated_by=updated_by,
            ))
        await db.commit()
    _cache[prompt_id] = content


async def reset_prompt(prompt_id: str) -> None:
    """Delete a prompt override and remove from cache."""
    from app.models.orm import PromptOverride
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PromptOverride).where(PromptOverride.id == prompt_id)
        )
        override = result.scalar_one_or_none()
        if override:
            await db.delete(override)
            await db.commit()
    _cache.pop(prompt_id, None)


async def list_prompts() -> list[dict]:
    """Return all prompts with current content (override or default) and metadata."""
    from app.models.orm import PromptOverride
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PromptOverride))
        overrides: dict[str, PromptOverride] = {o.id: o for o in result.scalars().all()}

    out = []
    for pid, meta in PROMPT_REGISTRY.items():
        override = overrides.get(pid)
        default_text = meta["default_fn"]()
        out.append({
            "id": pid,
            "label": meta["label"],
            "category": meta["category"],
            "description": meta["description"],
            "runtime_purpose": meta.get("runtime_purpose"),
            "used_by": meta.get("used_by", []),
            "content": override.content if override else default_text,
            "default": default_text,
            "is_overridden": override is not None,
            "updated_at": override.updated_at.isoformat() if override else None,
            "updated_by": override.updated_by if override else None,
        })
    return out
