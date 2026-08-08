"""Abstract LLM provider interface."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMFinding:
    status: str  # compliant|partially_compliant|non_compliant|not_applicable
    implementation_statement: str
    gaps: list[str] = field(default_factory=list)
    evidence_citations: list[dict] = field(default_factory=list)
    remediation_plan: str = ""
    confidence: float = 0.5
    raw_response: str = ""   # populated on parse failure so it can be stored & shown in UI
    parse_failed: bool = False
    # Option C: populated when stage-2.5 LLM reviewer disputes the code verdict.
    # The code verdict remains authoritative — this is a recorded dissent for human review.
    llm_challenge_note: str = ""
    # Issue 5: True when _synthesize_narrative() was used instead of a full Stage 3 LLM call
    # (skip_stage3=True, or Stage 3 LLM call failed). Stored on the DB finding so the UI
    # and reports can flag the finding as auto-synthesized rather than fully written.
    synthesized: bool = False

    @classmethod
    def from_json(cls, raw: dict) -> "LLMFinding":
        return cls(
            status=raw.get("status", "not_applicable"),
            implementation_statement=raw.get("implementation_statement", ""),
            gaps=raw.get("gaps", []),
            evidence_citations=raw.get("evidence_citations", []),
            remediation_plan=raw.get("remediation_plan", ""),
            confidence=float(raw.get("confidence", 0.5)),
        )

    @classmethod
    def error(cls, message: str, raw: str = "") -> "LLMFinding":
        return cls(
            status="not_reviewed",
            implementation_statement=f"Assessment error: {message}",
            confidence=0.0,
            raw_response=raw,
            parse_failed=True,
        )


ASSESSMENT_SYSTEM_PROMPT = """You are an expert NIST 800-53 Rev 5 compliance assessor for federal information systems.

Your job is to read the provided document evidence and determine how well the system implements the stated control. Base your determination entirely on the substance and quality of the evidence — not on word counts or keyword presence.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DECISION FRAMEWORK:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — Applicability:
  If the control is structurally inapplicable to this type of system (e.g., a physical facility control for a fully cloud-hosted system) → "not_applicable" with clear rationale.
  If in doubt, assume applicable and assess the evidence.

STEP 2 — Evidence quality assessment (apply document type weighting):
  Read each document excerpt carefully. Document headers indicate type and intent — weight accordingly:

  DOCUMENT TYPE WEIGHTING:
  - Type "policy": Establishes requirements and authority. Satisfies policy-level objectives ("yes"),
    but cannot alone satisfy procedural or technical implementation objectives.
  - Type "procedure": Operational how-to. Strong evidence for HOW controls are implemented.
  - Type "ssp": System Security Plan — authoritative, high-weight source for all objectives.
  - Type "configuration" / "technical_evidence": Direct implementation proof. Strongest evidence for
    technical control objectives.
  - Type "audit_finding" / "assessment_report" / "poam": Documents GAPS — a finding that a control
    "failed testing" or "is not implemented" is NEGATIVE evidence; treat it as a gap, not compliance.
  - Type "other" / unknown: Evaluate on content merit alone.

  DOCUMENT INTENT WEIGHTING:
  - Intent "implements": Currently active — use at face value.
  - Intent "plans": Future intent only — does NOT satisfy a current requirement; note the gap.
  - Intent "documents_gaps": Contains identified deficiencies — read carefully as negative evidence.

STEP 3 — Status determination:
  "compliant"           → All or nearly all control requirements are explicitly evidenced. No significant gaps.
  "partially_compliant" → Some requirements evidenced, but notable gaps exist, OR evidence is vague/high-level.
  "non_compliant"       → Little or no credible evidence of implementation, OR evidence shows the control is not in place.
  "not_applicable"      → Control is structurally inapplicable to this system type (explain why).

STEP 4 — Confidence calibration:
  High confidence (0.75–1.0): Evidence is specific, detailed, and directly addresses requirements.
  Medium confidence (0.45–0.74): Evidence exists but is partial, vague, or indirect.
  Low confidence (0.1–0.44): Little relevant evidence; determination is an inference.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT — respond ONLY with this JSON (no other text):
{
  "status": "compliant" | "partially_compliant" | "non_compliant" | "not_applicable",
  "implementation_statement": "<specific narrative citing document names and quotes; describe what IS implemented, not just what exists>",
  "gaps": ["<specific unmet requirement>", ...],
  "evidence_citations": [
    {"source": "<exact document name from the document header, e.g. AccessControl_Policy.docx>", "quote": "<verbatim excerpt, max 80 words>", "relevance": "<which requirement this satisfies>"}
  ],
  "remediation_plan": "<for partially_compliant or non_compliant: numbered, actionable steps>",
  "confidence": <0.0 to 1.0>
}

Rules:
- Use the EXACT document name from the document header — not "Excerpt N" or "Document N".
- Cite specific document excerpts. Do not make up or assume undocumented controls.
- Gaps become POAM entries — be precise about what is missing, not generic.
- Your output must be valid JSON parseable by Python json.loads(). No trailing commas, no comments.
"""


def build_control_prompt(
    control_id: str,
    control_title: str,
    control_statement: str,
    supplemental_guidance: str,
    chunks: list[str | dict],
    system_context: str = "",
    assessment_objectives: list[str] | None = None,
) -> str:
    # Option A: render enriched chunk dicts with metadata headers so the single-stage
    # path benefits from the same document type/intent weighting as the multistage path.
    evidence_parts = []
    for i, chunk in enumerate(chunks[:8], start=1):
        if isinstance(chunk, dict):
            filename = chunk.get("filename") or "Unknown"
            doc_type = chunk.get("document_type") or "other"
            doc_intent = chunk.get("document_intent") or "other"
            content = chunk.get("content", "")
            evidence_parts.append(
                f"[Document {i}: {filename} | Type: {doc_type} | Intent: {doc_intent}]\n{content}"
            )
        else:
            evidence_parts.append(f"[Document {i}]\n{chunk}")
    chunks_text = "\n\n---\n\n".join(evidence_parts)

    objectives_section = ""
    if assessment_objectives:
        obj_lines = "\n".join(f"  • {obj}" for obj in assessment_objectives[:40])
        objectives_section = f"""
## Assessment Objectives (NIST 800-53A Rev 5)
Each objective below is a specific requirement you must evaluate against the evidence.
Address gaps for any objective that is NOT fully evidenced:
{obj_lines}
"""

    return f"""## Control Under Assessment
**Control ID**: {control_id.upper()}
**Title**: {control_title}

**Control Statement**:
{control_statement}

**Supplemental Guidance**:
{supplemental_guidance[:400] if supplemental_guidance else "N/A"}
{objectives_section}
## System Context
{system_context or "No system context provided."}

## Document Evidence
{chunks_text if chunks_text else "No relevant document chunks retrieved."}

## Task
Assess the above control against the provided evidence. For each Assessment Objective listed above, determine whether the evidence demonstrates compliance. Return ONLY valid JSON per the schema.
"""


class LLMProvider(ABC):
    @abstractmethod
    async def assess_control(
        self,
        control_id: str,
        control_title: str,
        control_statement: str,
        supplemental_guidance: str,
        chunks: list[str | dict],
        system_context: str = "",
        assessment_objectives: list[str] | None = None,
    ) -> LLMFinding:
        ...

    @abstractmethod
    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Generic single-turn completion. Returns raw text response."""

    async def complete_multimodal(
        self,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[str],
    ) -> str:
        raise NotImplementedError("This provider does not support multimodal chat.")

    def _parse_response(self, text: str) -> LLMFinding:
        """Parse LLM JSON response into LLMFinding with multi-stage repair."""
        text = text.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # Find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            return self._extract_fields_fallback(text, original=text)

        raw = text[start:end]

        # Stage 1: direct parse
        try:
            return LLMFinding.from_json(json.loads(raw))
        except json.JSONDecodeError:
            pass

        # Stage 2: common repairs
        repaired = _repair_json(raw)
        try:
            return LLMFinding.from_json(json.loads(repaired))
        except (json.JSONDecodeError, Exception):
            pass

        # Stage 3: field-by-field regex extraction — mark as parse_failed so engine can store raw
        return self._extract_fields_fallback(text, original=text)

    @staticmethod
    def _extract_fields_fallback(text: str, original: str = "") -> LLMFinding:
        """Last-resort: extract key fields via regex when JSON is unrecoverable."""
        status = "not_reviewed"
        for s in ("compliant", "partially_compliant", "non_compliant", "not_applicable"):
            if s in text:
                status = s
                break

        stmt_match = re.search(r'"implementation_statement"\s*:\s*"([^"]{10,})"', text)
        stmt = stmt_match.group(1) if stmt_match else "LLM response could not be fully parsed — manual review required."

        conf_match = re.search(r'"confidence"\s*:\s*([\d.]+)', text)
        confidence = float(conf_match.group(1)) if conf_match else 0.1

        return LLMFinding(
            status=status,
            implementation_statement=stmt,
            confidence=confidence,
            raw_response=original,
            parse_failed=(status == "not_reviewed"),
        )


def _repair_json(text: str) -> str:
    """Attempt common JSON repairs."""
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # Replace Python-style None/True/False
    text = re.sub(r'\bNone\b', 'null', text)
    text = re.sub(r'\bTrue\b', 'true', text)
    text = re.sub(r'\bFalse\b', 'false', text)
    # If JSON is truncated (no closing brace), try to close it
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')
    if open_brackets > 0:
        text += ']' * open_brackets
    if open_braces > 0:
        text += '}' * open_braces
    return text
