"""
Multi-stage assessment engine for NIST 800-53 Rev 5 controls.

Stage 1 — Tag-based chunk retrieval (SQL, no LLM):
    Queries document_chunk_control_tags for chunks pre-indexed to this control.
    Falls back to RAG if fewer than 2 tagged chunks found.

Stage 2 — Per-objective gap analysis (LLM):
    For each assessment objective, evaluates evidence → returns structured JSON.

Verdict (code logic):
    Calculates status/confidence from Stage 2 gap matrix.
    Verdict is NOT made by the LLM — it's anchored to explicit scoring rules.

Stage 3 — Narrative writing (LLM):
    Given the pre-determined verdict + gap analysis, writes the SSP narrative.
    Returns LLMFinding with implementation_statement, gaps, evidence_citations, remediation_plan.
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.evidence_view import get_control_evidence_packets
from app.services.implementation_statements import (
    build_control_statement_generation_guidance,
    split_objective_reference,
    synthesize_control_implementation_statement,
)
from app.services.llm.base import LLMFinding

logger = logging.getLogger(__name__)

# ── Stage 2 system prompt ─────────────────────────────────────────────────────

GAP_ANALYSIS_SYSTEM_PROMPT = """You are a NIST 800-53 Rev 5 compliance assessor performing structured evidence analysis.

For each assessment objective provided, determine whether the evidence demonstrates compliance.

Return ONLY a valid JSON array. Each element corresponds to one assessment objective:
[
  {
    "objective_id": "<label exactly as listed, e.g. AC-01a.[01]>",
    "met": "yes" | "partial" | "no",
    "evidence_quote": "<verbatim quote from evidence max 60 words, or null>",
    "source": "<Document number from the header, e.g. 3, exact filename, or null>",
    "packet_id": "<Packet ID from the evidence header when a specific packet supports the decision, or null>",
    "gap": "<what is missing or insufficient, or null if fully met>"
  }
]

EVIDENCE EVALUATION RULES:
- "yes": Evidence clearly and specifically shows this objective is currently implemented
- "partial": Evidence mentions the topic but implementation details are vague, incomplete, or future-tense
- "no": No relevant evidence found, or evidence explicitly contradicts implementation
- Be specific in gap descriptions — they become POAM entries
- Do NOT mark "yes" just because a document mentions the topic area
- Return an entry for EVERY objective listed, even if no evidence exists
- When evidence supports a decision, return the exact Packet ID from the evidence header in packet_id
- Consider the full evidence set provided for the objective, including any evidence blocks labeled as contradictory or partial/future-state
- If contradictory evidence is stronger than the supporting evidence, do not mark the objective "yes"

DOCUMENT TYPE WEIGHTING — adjust your evaluation based on document headers:
- Type "policy": Establishes requirements and authority. Satisfies policy-level objectives ("yes"),
  but cannot alone satisfy procedural or technical implementation objectives ("partial" at best).
- Type "procedure": Operational how-to. Strong evidence for HOW controls are implemented.
  Good for both policy and implementation objectives if sufficiently detailed.
- Type "ssp": System Security Plan — authoritative, high-weight source for all objectives.
- Type "configuration" / "technical_evidence": Direct technical implementation proof.
  Strongest evidence for technical control objectives.
- Type "audit_finding" / "assessment_report" / "poam": These document GAPS and findings,
  NOT successful implementation. A finding that a control "is not implemented" or "failed
  testing" is NEGATIVE evidence — mark the objective "no" and quote the finding in the gap.
- Type "training_record": Evidence for AT-family and awareness objectives only.
- Type "contract": May establish inherited/third-party controls; use as supporting evidence.
- Type "other" / unknown: Evaluate on content merit alone.

DOCUMENT INTENT WEIGHTING:
- Intent "implements": Currently active — use at face value.
- Intent "plans": Future intent only. Mark "partial" at best; implementation is not yet confirmed.
- Intent "documents_gaps": Contains identified deficiencies. Read carefully — explicit gap
  statements are evidence of NON-COMPLIANCE for those objectives.
- Intent "evaluates": Assessment output — may contain both compliant and non-compliant findings.
  Do not treat a passing assessment finding as equivalent to implementation evidence.

RESPOND WITH ONLY THE JSON ARRAY. No explanation, no markdown."""


# ── Stage 3 system prompt ─────────────────────────────────────────────────────

NARRATIVE_SYSTEM_PROMPT = """You are a NIST 800-53 Rev 5 SSP writer. You are given a pre-determined compliance status and a structured gap analysis. Write the formal security documentation for this control, formatted for direct use in a System Security Plan.

Return ONLY valid JSON:
{
  "implementation_statement": "<SSP narrative in clean paragraph form — see format rules below>",
  "gaps": ["<specific gap referencing the objective ID, e.g. AC-01a.[02]: policy not disseminated>", ...],
  "evidence_citations": [
    {"source": "<exact document name from Source Inventory, or 'Assessment Evidence' if unknown>", "quote": "<verbatim, max 80 words>", "relevance": "<which objective this satisfies>"}
  ],
  "remediation_plan": "<for partially_compliant or non_compliant: numbered actionable steps; empty string if compliant>"
}

IMPLEMENTATION STATEMENT FORMAT (NIST SP 800-18 Rev 1 SSP structure):
Write the implementation_statement as a single integrated control-level narrative using normal SSP prose.
Use paragraph breaks when separate requirement clauses should be discussed distinctly.
Do NOT label paragraphs as "Part a", "Part b", or similar clause markers.
Objectives are source requirements for the narrative, not separate implementation statements.
If a requirement area has insufficient evidence, state that plainly in SSP prose and identify the missing information needed.

IMPLEMENTATION STATEMENT STYLE RULES:
- Write like a real SSP implementation statement, not an evidence inventory or validation report.
- Describe the CURRENT implemented behavior of the system/organization first.
- Target roughly 3 to 5 paragraphs unless the control is genuinely simple.
- Use the objective set to ensure full coverage of scope, roles, implemented process, retained records, review cadence, and any organization-defined values or recipients.
- Do not repeat the same generic evidence-coverage sentence for each objective.
- Do not restate objective IDs, objective counts, packet counts, or reviewer mechanics in the implementation_statement.
- Keep each paragraph concise: normally 2-4 sentences.
- Do NOT paste repository paths, storage locations, bucket names, document counts, user counts, validation record names, or repeated filenames into the implementation_statement.
- Do NOT write parenthetical source references inside the implementation_statement unless absolutely necessary for clarity.
- Reserve exact document names, quotes, and source tracing for the evidence_citations array.
- If evidence is partial, say what is currently implemented and then briefly note what remains undefined or insufficient.
- Do not mention confidence scores, scoring logic, objective IDs, or assessment mechanics in the implementation_statement.
- Prefer capability-oriented SSP prose over named products, module names, quoted role names, and tool branding.
- Describe implementation categories such as centralized identity and access management, database access control, application authorization controls, automated compliance monitoring, or infrastructure-as-code governance instead of copying vendor names unless the technology name is essential to understanding the control.
- Do NOT include individual IAM role names, Terraform module names, scanner product names, bucket names, repository names, or quoted implementation labels in the implementation_statement.

EVIDENCE CITATION RULES:
- Use the EXACT document name from the Source Inventory (e.g. "AccessControl_Policy_v2.docx"), NOT "Excerpt N" or "Document N"
- If the source inventory lists a document, use that name verbatim
- If no source name is available, write "Assessment Evidence"
- Map each citation to the specific objective ID it satisfies

REMEDIATION RULES:
- Address every SHALL Failure (explicitly unmet objective) first, numbered 1, 2, 3...
- If an AI Dissent Note is present, add a "Dissent Concerns" section addressing its specific issues
- Steps must be actionable: include specific evidence to collect (e.g., "Provide account management SOP with approval workflow dated within 12 months")
- No generic NIST boilerplate — tailor to the system context provided

DOCUMENT INTENT RULES:
- Documents with intent "plans" describe FUTURE state — do NOT cite them as satisfying a current SHALL requirement; note the future-only status explicitly
- Documents with intent "implements" describe CURRENT state — use at face value
- Documents with intent "documents_gaps" or "evaluates" may contain both compliant and non-compliant findings — read carefully

The compliance status has been pre-determined by code analysis — accept it, do not change it.
RESPOND WITH ONLY THE JSON OBJECT. No explanation, no markdown."""


# ── Stage 1: Tag-based chunk retrieval ───────────────────────────────────────

async def get_tagged_chunks(
    control_id: str,
    project_id: int,
    db: AsyncSession,
    max_tokens: int = 8000,
    min_confidence: float = 0.45,
) -> list[dict]:
    """Query evidence units mapped to this control, sorted by confidence descending."""
    return await get_control_evidence_packets(
        control_id=control_id,
        project_id=project_id,
        db=db,
        max_tokens=max_tokens,
        min_confidence=min_confidence,
    )


# ── Stage 2: Gap analysis ─────────────────────────────────────────────────────

def _format_chunks_for_llm(chunks: list[dict | str]) -> str:
    """Format enriched chunk dicts (or raw strings) into labelled evidence blocks for the LLM."""
    parts = []
    for i, chunk in enumerate(chunks[:10], start=1):
        if isinstance(chunk, str):
            # RAG fallback or legacy — no metadata available
            parts.append(f"[Document {i}: (source unknown)]\n{chunk}")
        else:
            filename = chunk.get("filename", "Unknown")
            doc_type = chunk.get("document_type") or "other"
            doc_intent = chunk.get("document_intent") or "other"
            date_str = chunk.get("date") or "unknown date"
            triage_role = chunk.get("triage_role") or "supporting"
            objective_score = chunk.get("objective_relevance_score")
            objective_hits = chunk.get("objective_keyword_hits") or []
            packet_id = chunk.get("packet_id") or f"Document-{i}"
            source_label = {
                "common_control": "Common Control Provider",
                "policy": "Enterprise Policy Library",
                "procedure": "Enterprise Procedure Library",
                "project": "Project Document",
            }.get(chunk.get("source_type", "project"), "Project Document")
            content = chunk.get("llm_excerpt") or chunk.get("content", "")
            role_label = {
                "supporting": "supporting",
                "contradictory": "contradictory",
                "partial": "partial/future-state",
                "irrelevant": "context",
            }.get(triage_role, triage_role)
            score_label = f" | Objective relevance: {objective_score:.2f}" if isinstance(objective_score, (int, float)) else ""
            hit_label = f" | Keyword hits: {', '.join(objective_hits[:6])}" if objective_hits else ""
            parts.append(
                f"[Document {i} | Packet ID: {packet_id} | {filename} | Type: {doc_type} | Intent: {doc_intent}"
                f" | Source: {source_label} | Role: {role_label}{score_label}{hit_label} | Date: {date_str}]\n{content}"
            )
    return "\n\n---\n\n".join(parts)


async def run_gap_analysis(
    control_id: str,
    control_title: str,
    objectives: list[str],
    chunks: list[dict | str],
    system_context: str,
    llm,
) -> list[dict]:
    """Call LLM to evaluate each assessment objective against the evidence."""
    chunks_text = _format_chunks_for_llm(chunks)
    objectives_text = "\n".join(f"  {obj}" for obj in objectives[:40])

    user_prompt = f"""## Control: {control_id} — {control_title}

## Assessment Objectives to Evaluate:
{objectives_text}

## System Context:
{system_context or "No system context provided."}

## Evidence:
{chunks_text if chunks_text else "No evidence chunks available."}

## Task:
For each assessment objective listed above, evaluate the evidence and return the JSON array."""

    from app.services.prompt_manager import get_prompt
    system_prompt = await get_prompt("gap_analysis_system", GAP_ANALYSIS_SYSTEM_PROMPT)

    try:
        raw = await llm.complete(system_prompt, user_prompt)
        return _parse_gap_analysis(raw, objectives)
    except Exception as e:
        logger.warning("Gap analysis failed for %s: %s", control_id, e)
        return []


def _parse_gap_analysis(raw: str, objectives: list[str]) -> list[dict]:
    """Parse LLM gap analysis JSON response."""
    raw = raw.strip()
    # Extract JSON array
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group())
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            met = item.get("met", "no")
            if met not in ("yes", "partial", "no"):
                met = "no"
            result.append({
                "objective_id": str(item.get("objective_id", ""))[:64],
                "met": met,
                "evidence_quote": str(item.get("evidence_quote") or "")[:400] or None,
                "source": item.get("source"),
                "packet_id": str(item.get("packet_id") or "")[:128] or None,
                "gap": str(item.get("gap") or "")[:400] or None,
            })
        return result
    except (json.JSONDecodeError, TypeError):
        return []


# ── Code verdict calculation (Option A — SHALL-anchored) ──────────────────────

def calculate_verdict(gap_analysis: list[dict]) -> tuple[str, float, list[str]]:
    """
    Determine compliance status and confidence from per-objective gap analysis.

    Returns (status, confidence, shall_failures) where shall_failures is the list
    of objective IDs that scored "no" — representing explicitly unmet requirements.

    ALL NIST 800-53 Rev 5 baseline objectives are SHALL requirements (the OSCAL
    format removes the word "shall" from prose, but the mandate remains). Therefore:

      Option A — SHALL Rule: any objective scored "no" is an explicitly unmet SHALL
      requirement and PREVENTS compliant status regardless of overall score.

    Status rules:
      All yes                              → compliant (0.90)
      No "no" answers AND score >= 0.80    → compliant (0.78–0.88)
        (all partials — thin evidence but no identified gaps — still compliant)
      score >= 0.40                        → partially_compliant (0.55–0.75)
      some yes/partial but score < 0.40   → partially_compliant (0.50)
      all no                               → non_compliant (0.70–0.85)
    """
    if not gap_analysis:
        return "not_reviewed", 0.1, []

    yes = sum(1 for o in gap_analysis if o.get("met") == "yes")
    partial = sum(1 for o in gap_analysis if o.get("met") == "partial")
    no = sum(1 for o in gap_analysis if o.get("met") == "no")
    total = len(gap_analysis)

    score = (yes + 0.5 * partial) / total

    # SHALL Rule: collect every explicitly unmet objective
    shall_failures = [
        o["objective_id"]
        for o in gap_analysis
        if o.get("met") == "no" and o.get("objective_id")
    ]

    if yes == total:
        # Every objective satisfied
        return "compliant", 0.90, []

    elif not shall_failures and score >= 0.80:
        # No explicit gaps; some objectives are "partial" (thin evidence, not missing).
        # High overall score → compliant, but at lower confidence than all-yes.
        confidence = round(0.78 + 0.10 * (score - 0.80) / 0.20, 2)
        return "compliant", min(confidence, 0.88), []

    elif score >= 0.40:
        return "partially_compliant", round(0.55 + 0.20 * (score - 0.40) / 0.60, 2), shall_failures

    elif yes > 0 or partial > 0:
        return "partially_compliant", 0.50, shall_failures

    else:
        # All objectives unmet
        confidence = min(0.85, 0.70 + 0.15 * (no / total))
        return "non_compliant", round(confidence, 2), shall_failures


def build_gaps_from_analysis(gap_analysis: list[dict]) -> list[str]:
    """Build the gaps list from unmet objectives."""
    gaps = []
    for obj in gap_analysis:
        if obj.get("met") in ("no", "partial") and obj.get("gap"):
            obj_id = obj.get("objective_id", "")
            gap_text = obj["gap"]
            gaps.append(f"{obj_id}: {gap_text}" if obj_id else gap_text)
    return gaps


# ── Option C: Stage 2.5 — Verdict challenge ───────────────────────────────────

VERDICT_CHALLENGE_SYSTEM_PROMPT = """You are a senior NIST 800-53 Rev 5 assessor reviewing a preliminary compliance determination produced by automated scoring.

Your role is NOT to re-run the assessment — the evidence has already been evaluated objective by objective. Your role is to review whether the code-calculated verdict is reasonable, and flag clear errors in the gap analysis reasoning.

Return ONLY valid JSON:
{
  "concur": true | false,
  "dissent_note": "<If dissenting: cite the specific objective ID(s) and explain why the evidence quote directly contradicts the 'no' or 'yes' determination. Null if you concur.>",
  "challenged_objectives": ["<objective_id>", ...]
}

RULES:
- Concur if the verdict is defensible — even if you might personally shade it differently.
- Dissent ONLY for clear errors: an objective marked 'no' when the evidence quote plainly satisfies it, or 'yes' when the quote shows an explicit gap.
- SHALL failures (unmet required objectives) are recorded by the code — do not dispute those unless the underlying 'no' determination itself was wrong.
- The code verdict is FINAL and will not be changed by your review. Your note goes to the human assessor.
- RESPOND WITH ONLY THE JSON OBJECT. No explanation, no markdown."""


async def run_verdict_challenge(
    control_id: str,
    control_title: str,
    gap_analysis: list[dict],
    status: str,
    confidence: float,
    shall_failures: list[str],
    llm,
) -> str | None:
    """Stage 2.5 — LLM reviews the code-calculated verdict for obvious errors.

    Returns a dissent note string if the LLM disagrees with the verdict,
    or None if it concurs.  The code verdict is NOT changed regardless of outcome.
    """
    # Compact gap matrix — no evidence chunks needed, just the objective decisions
    matrix_lines = []
    for obj in gap_analysis[:40]:
        obj_id = obj.get("objective_id", "?")
        met = obj.get("met", "?")
        quote = obj.get("evidence_quote") or "(no quote)"
        gap = obj.get("gap") or ""
        line = f"  {obj_id}: {met}"
        if quote and quote != "(no quote)":
            line += f" — evidence: \"{quote[:120]}\""
        if met != "yes" and gap:
            line += f" | gap: {gap[:100]}"
        matrix_lines.append(line)

    shall_section = ""
    if shall_failures:
        shall_section = (
            f"\nSHALL FAILURES (unmet required objectives flagged by code): "
            f"{', '.join(shall_failures)}\n"
        )

    user_prompt = f"""Control: {control_id} — {control_title}

Code Verdict: {status.upper()} (confidence: {confidence:.0%})
{shall_section}
Gap Analysis Matrix (objective-by-objective):
{chr(10).join(matrix_lines)}

Review the verdict. Dissent only if a specific objective determination is clearly wrong given its evidence quote."""

    from app.services.prompt_manager import get_prompt
    system_prompt = await get_prompt("verdict_challenge", VERDICT_CHALLENGE_SYSTEM_PROMPT)

    try:
        raw = await llm.complete(system_prompt, user_prompt)
        raw = raw.strip()

        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            return None

        import json
        data = json.loads(match.group())
        if data.get("concur", True):
            return None

        note = data.get("dissent_note") or ""
        challenged = data.get("challenged_objectives") or []
        if not note:
            return None

        if challenged:
            note = f"[Challenged objectives: {', '.join(challenged)}] {note}"
        return note[:1000]  # cap length

    except Exception as e:
        logger.debug("Verdict challenge failed for %s (non-critical): %s", control_id, e)
        return None


# ── Option D: NIST 800-53A determination translation ─────────────────────────

_NIST_DETERMINATION_MAP: dict[str, dict] = {
    "compliant": {
        "determination": "Satisfied",
        "abbreviation": "S",
        "nist_category": "fully_implemented",
    },
    "partially_compliant": {
        "determination": "Other Than Satisfied",
        "abbreviation": "OTS",
        "nist_category": "partially_implemented",
    },
    "non_compliant": {
        "determination": "Other Than Satisfied",
        "abbreviation": "OTS",
        "nist_category": "not_implemented",
    },
    "not_applicable": {
        "determination": "Not Applicable",
        "abbreviation": "NA",
        "nist_category": "not_applicable",
    },
    "not_reviewed": {
        "determination": "Not Reviewed",
        "abbreviation": "NR",
        "nist_category": "not_reviewed",
    },
}


def nist_determination(status: str) -> dict:
    """Translate internal compliance status to NIST 800-53A formal determination language.

    Internal statuses (DB / working assessment views):
        compliant | partially_compliant | non_compliant | not_applicable | not_reviewed

    NIST 800-53A formal determinations (SAR, final ATO package output):
        Satisfied | Other Than Satisfied | Not Applicable | Not Reviewed

    The internal statuses are preserved in the DB. This function is applied at the
    API/report layer so working views remain unchanged while formal output is accurate.
    """
    return _NIST_DETERMINATION_MAP.get(
        status,
        {"determination": "Not Reviewed", "abbreviation": "NR", "nist_category": "not_reviewed"},
    )


# ── Stage 3: Narrative writing ────────────────────────────────────────────────

async def run_narrative(
    control_id: str,
    control_title: str,
    control_statement: str,
    status: str,
    confidence: float,
    gap_analysis: list[dict],
    chunks: list[dict | str],
    system_context: str,
    llm,
    shall_failures: list[str] | None = None,
    challenge_note: str | None = None,
    objectives: list[str] | None = None,
) -> LLMFinding:
    """Call LLM to write the SSP narrative given a pre-determined verdict.

    Issues 1, 2, 3, 4, 6:
    - Source Inventory injected so LLM knows document names and intent
    - Full objective matrix (no truncation) replaces the 2,000-char JSON dump
    - SHALL failures and AI dissent note passed through for remediation targeting
    - NARRATIVE_SYSTEM_PROMPT requires SSP part-structured output
    - chunk_map built for citation resolution in _parse_narrative
    """
    chunks_text = _format_chunks_for_llm(chunks[:8])
    statement_contract = build_control_statement_generation_guidance(
        control_id,
        control_title,
        objectives or [],
    )

    # Build chunk index map: document number (1-based) → filename for citation resolution
    chunk_map: dict[int, str] = {}
    for i, chunk in enumerate(chunks[:10], start=1):
        if isinstance(chunk, dict):
            chunk_map[i] = chunk.get("filename") or f"Document {i}"
        else:
            chunk_map[i] = f"Document {i}"

    # Issue 1 — Source Inventory: document names + intent so LLM avoids treating
    # "plans" docs as current implementation evidence
    source_inventory_lines: list[str] = []
    seen_sources: set[str] = set()
    for i, chunk in enumerate(chunks[:10], start=1):
        if isinstance(chunk, dict):
            fname = chunk.get("filename") or "Unknown"
            dtype = chunk.get("document_type") or "other"
            dintent = chunk.get("document_intent") or "other"
            if fname not in seen_sources:
                source_inventory_lines.append(
                    f"  {i}. {fname} — type: {dtype} | intent: {dintent}"
                )
                seen_sources.add(fname)
    source_inventory = "\n".join(source_inventory_lines) if source_inventory_lines else "  (no source metadata available)"

    # Issue 4 — Full objective matrix (no truncation), formatted as a scannable table
    _met_marker = {"yes": "[YES]", "partial": "[PARTIAL]", "no": "[NO]"}
    objective_text_map: dict[str, str] = {}
    for objective in objectives or []:
        obj_id, obj_text = split_objective_reference(str(objective))
        if obj_id:
            objective_text_map[obj_id] = obj_text
    matrix_lines: list[str] = []
    for obj in gap_analysis:
        obj_id = obj.get("objective_id", "?")
        met = obj.get("met", "?")
        marker = _met_marker.get(met, f"[{met.upper()}]")
        line = f"  {marker} {obj_id}"
        obj_text = objective_text_map.get(obj_id)
        if obj_text:
            line += f": {obj_text}"
        if met == "partial" and obj.get("gap"):
            line += f" — partial: {obj['gap'][:100]}"
        elif met == "no" and obj.get("gap"):
            line += f" — gap: {obj['gap'][:120]}"
        matrix_lines.append(line)
    objective_matrix = "\n".join(matrix_lines) if matrix_lines else "  (no objectives)"

    # Issue 3 — SHALL failures block (unmet required objectives — guide remediation priority)
    shall_section = ""
    if shall_failures:
        shall_section = (
            "\n## SHALL Failures (explicitly unmet required objectives — address FIRST in remediation):\n"
            + "\n".join(f"  • {f}" for f in shall_failures)
            + "\n"
        )

    # Issue 3 — AI dissent note (second-opinion concern — include as remediation sub-section)
    dissent_section = ""
    if challenge_note:
        dissent_section = (
            f"\n## AI Dissent Note (second-opinion concern — address in a 'Dissent Concerns' remediation sub-section):\n"
            f"  {challenge_note}\n"
        )

    user_prompt = f"""## Control: {control_id} — {control_title}

## Pre-Determined Compliance Status: {status.upper()}
(Confidence: {confidence:.0%}) — This status is final. Write the SSP narrative to reflect it.

## Control Statement:
{control_statement[:600]}

## Source Inventory (documents evaluated — use these exact names in citations):
{source_inventory}

## Objective Matrix:
{objective_matrix}
{shall_section}{dissent_section}
## Control-Level Implementation Statement Contract:
{statement_contract}

## Evidence Detail (citation grounding only — do not copy product names, module names, filenames, or quoted labels into the implementation_statement unless essential):
{chunks_text if chunks_text else "No evidence available."}

## System Context:
{system_context or "No system context."}

## Task:
Write the formal SSP documentation JSON for this control. Structure implementation_statement by control part. The implementation_statement must read like final SSP prose, not like a list of evidence artifacts. Use exact document names only in evidence_citations — do not write "Excerpt N" or "Document N".""" 

    from app.services.prompt_manager import get_prompt
    system_prompt = await get_prompt("narrative_system", NARRATIVE_SYSTEM_PROMPT)

    try:
        raw = await llm.complete(system_prompt, user_prompt)
        return _parse_narrative(
            raw,
            status,
            confidence,
            gap_analysis,
            chunk_map,
            control_id=control_id,
            control_title=control_title,
            objectives=objectives or [],
        )
    except Exception as e:
        logger.warning("Narrative generation failed for %s: %s", control_id, e)
        # Fall back to synthesized narrative from gap analysis (Issue 5: marked synthesized=True)
        return _synthesize_narrative(
            status,
            confidence,
            gap_analysis,
            control_id,
            control_title,
            objectives=objectives or [],
        )


def _parse_narrative(
    raw: str,
    status: str,
    confidence: float,
    gap_analysis: list[dict],
    chunk_map: dict[int, str] | None = None,
    *,
    control_id: str = "",
    control_title: str = "",
    objectives: list[str] | None = None,
) -> LLMFinding:
    """Parse Stage 3 LLM narrative response into LLMFinding.

    Issue 2: chunk_map resolves any residual "Document N" / "Excerpt N" source labels
    that slipped through despite the prompt instruction to use actual document names.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return _synthesize_narrative(
            status,
            confidence,
            gap_analysis,
            control_id,
            control_title,
            objectives=objectives or [],
        )

    try:
        data = json.loads(raw[start:end])
        llm_citations = data.get("evidence_citations") or []

        # Resolve any residual "Document N" / "Excerpt N" labels using the chunk map.
        # Handles three LLM output patterns:
        #   prefix:  "Document 1: filename.pdf"  → strip prefix, map idx → filename
        #   suffix:  "filename.pdf (Document 1)" → strip suffix, use clean name
        #   bare:    "Document 1"                → map idx → filename
        if chunk_map and llm_citations:
            for cit in llm_citations:
                src = cit.get("source", "")
                # Suffix pattern: "filename (Document N)" — strip suffix, keep filename
                suffix_m = re.search(r'\s*\((?:Document|Excerpt)\s+(\d+)\)\s*$', src, re.IGNORECASE)
                if suffix_m:
                    clean = src[:suffix_m.start()].strip()
                    cit["source"] = clean if clean else chunk_map.get(int(suffix_m.group(1)), src)
                    continue
                # Prefix/bare pattern: "Document N" or "Document N: ..."
                prefix_m = re.match(r'(?:Document|Excerpt)\s+(\d+)', src, re.IGNORECASE)
                if prefix_m:
                    idx = int(prefix_m.group(1))
                    cit["source"] = chunk_map.get(idx, src)

        # Fall back to gap analysis citations if LLM returned none
        citations = llm_citations if llm_citations else _citations_from_gap_analysis(gap_analysis, chunk_map)
        implementation_statement = _clean_implementation_statement(
            data.get("implementation_statement", ""),
            gap_analysis=gap_analysis,
            control_id=control_id,
            control_title=control_title,
            status=status,
            objectives=objectives or [],
        )
        return LLMFinding(
            status=status,       # Always use code-determined status
            implementation_statement=implementation_statement,
            gaps=data.get("gaps", build_gaps_from_analysis(gap_analysis)),
            evidence_citations=citations,
            remediation_plan=data.get("remediation_plan", ""),
            confidence=confidence,  # Always use code-determined confidence
        )
    except (json.JSONDecodeError, Exception):
        return _synthesize_narrative(
            status,
            confidence,
            gap_analysis,
            control_id,
            control_title,
            objectives=objectives or [],
        )


def _citations_from_gap_analysis(
    gap_analysis: list[dict],
    chunk_map: dict[int, str] | None = None,
) -> list[dict]:
    """Extract evidence citations from Stage 2 gap analysis results.

    Issue 2: chunk_map maps Stage 2 source numbers (1-based document index) to
    actual filenames so citations read "AccessControl_Policy.docx" not "Excerpt 3".
    """
    citations = []
    seen_quotes: set[str] = set()
    for obj in gap_analysis:
        quote = obj.get("evidence_quote") or ""
        source = obj.get("source")
        if not quote or quote in seen_quotes:
            continue
        seen_quotes.add(quote)

        # Resolve source number → filename via chunk_map
        if source is not None and chunk_map:
            try:
                resolved = chunk_map.get(int(source))
                source_label = resolved if resolved else f"Excerpt {source}"
            except (ValueError, TypeError):
                source_label = str(source) if source else "Assessment Evidence"
        elif source is not None:
            source_label = f"Excerpt {source}"
        else:
            source_label = "Assessment Evidence"

        citations.append({
            "source": source_label,
            "quote": quote,
            "relevance": obj.get("objective_id", ""),
        })
    return citations


def _synthesize_narrative(
    status: str,
    confidence: float,
    gap_analysis: list[dict],
    control_id: str,
    control_title: str = "",
    *,
    objectives: list[str] | None = None,
) -> LLMFinding:
    """Build a minimal LLMFinding from gap analysis without LLM narrative."""
    met_objs = [o for o in gap_analysis if o.get("met") == "yes"]
    partial_objs = [o for o in gap_analysis if o.get("met") == "partial"]
    unmet_objs = [o for o in gap_analysis if o.get("met") == "no"]
    implementation_statement = synthesize_control_implementation_statement(
        control_id=control_id,
        control_title=control_title or control_id,
        status=status,
        objectives=objectives or [],
        gap_analysis=gap_analysis,
    )
    gaps = build_gaps_from_analysis(gap_analysis)
    remediation = ""
    if unmet_objs and status != "compliant":
        remediation = "\n".join(
            f"{i+1}. Address {o['objective_id']}: {o.get('gap', 'implement the required control element')}"
            for i, o in enumerate(unmet_objs[:10])
        )

    return LLMFinding(
        status=status,
        implementation_statement=implementation_statement,
        gaps=gaps,
        evidence_citations=_citations_from_gap_analysis(gap_analysis),
        remediation_plan=remediation,
        confidence=confidence,
        synthesized=True,  # Issue 5: flag — no Stage 3 LLM call was made
    )


def _split_objective_reference(objective: str) -> tuple[str, str]:
    return split_objective_reference(objective)


def _part_key_from_objective_id(objective_id: str | None, fallback_index: int = 0) -> str:
    raw = str(objective_id or "").strip()
    match = re.search(r'([a-z])(?:[\.\[]|$)', raw, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return chr(ord('a') + min(max(fallback_index, 0), 25))


def _part_sort_key(part_key: str) -> tuple[int, str]:
    if len(part_key) == 1 and part_key.isalpha():
        return (0, part_key.lower())
    return (1, part_key.lower())


def _normalize_ssp_specificity(text: str) -> str:
    normalized = f" {text.strip()} "

    replacements = [
        (r'AWS Identity and Access Management\s*\(IAM\)\s*policies', ' centralized identity and access management mechanisms '),
        (r'AWS Identity and Access Management\s*\(IAM\)', ' centralized identity and access management '),
        (r'\bAWS IAM\b', ' centralized identity and access management '),
        (r'\bIAM policies\b', ' identity and access management policies '),
        (r'\bPostgreSQL role-based access control\b', ' database role-based access control '),
        (r'\bRedis ACLs\b', ' service-level access control lists '),
        (r'\bDjango permission classes\b', ' application authorization controls '),
        (r'\bautomated compliance scans in\s+Tenable(?:\.io)?\b', ' recurring automated compliance assessments '),
        (r'\bTenable(?:\.io)?\b', ' automated compliance tooling '),
        (r'\bTerraform module\s+"[^"]+"\b', ' approved infrastructure-as-code definitions '),
        (r'\bTerraform module\b', ' infrastructure-as-code definitions '),
        (r'\bGitLab\b', ' version-controlled repositories '),
        (r'\bS3 bucket\b', ' managed document repositories '),
        (r'\bcentral HR database\b', ' authoritative personnel source '),
        (r'\bIAM roles\b', ' access roles '),
        (r'\bnightly\b', ' on a scheduled basis '),
        (r'\bquarterly\b', ' periodically '),
        (r'\bfor example,\s*', ''),
    ]
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)

    normalized = re.sub(r'the\s+"[^"]+"\s+IAM role', 'a privileged access role', normalized, flags=re.IGNORECASE)
    normalized = re.sub(r'the\s+"[^"]+"\s+role', 'a role-specific account', normalized, flags=re.IGNORECASE)
    normalized = re.sub(r'"[^"]+"', '', normalized)
    normalized = re.sub(r'\s{2,}', ' ', normalized)
    normalized = re.sub(r'\s+([,.;:])', r'\1', normalized)
    return normalized.strip()


def _looks_too_implementation_specific(text: str) -> bool:
    markers = [
        r'\baws\b',
        r'\bpostgresql\b',
        r'\bredis\b',
        r'\bdjango\b',
        r'\bterraform\b',
        r'\btenable(?:\.io)?\b',
        r'"[^"]+"',
        r'\biam role\b',
        r'\bmodule\b',
    ]
    hits = sum(1 for pattern in markers if re.search(pattern, text, re.IGNORECASE))
    return hits >= 2


def _clean_implementation_statement(
    text: str,
    *,
    gap_analysis: list[dict],
    control_id: str = "",
    control_title: str = "",
    status: str = "",
    objectives: list[str] | None = None,
) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return _synthesize_narrative(
            status="partially_compliant" if any(obj.get("met") in {"yes", "partial"} for obj in gap_analysis) else "not_reviewed",
            confidence=0.5,
            gap_analysis=gap_analysis,
            control_id=control_id,
            control_title=control_title,
            objectives=objectives or [],
        ).implementation_statement

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return cleaned

    suspicious_filename_count = len(re.findall(r'\b[^\s()]+\.(?:docx|pdf|xlsx|pptx|txt)\b', cleaned, re.IGNORECASE))
    suspicious_repo_markers = len(re.findall(r'\b(?:s3 bucket|gitlab|repo|portal access logs|validation record)\b', cleaned, re.IGNORECASE))
    word_count = len(re.findall(r"\b\w+\b", cleaned))
    duplicate_sentence_count = len(
        re.findall(r"Reviewed (?:evidence|documentation) indicates", cleaned, re.IGNORECASE)
    )
    if (
        suspicious_filename_count >= 3
        or suspicious_repo_markers >= 2
        or (len(gap_analysis) >= 3 and word_count < 70)
        or duplicate_sentence_count >= 2
    ):
        return synthesize_control_implementation_statement(
            control_id=control_id or "Control",
            control_title=control_title or control_id or "Implementation",
            status=status or ("partially_compliant" if any(obj.get("met") in {"yes", "partial"} for obj in gap_analysis) else "not_reviewed"),
            objectives=objectives or [],
            gap_analysis=gap_analysis,
        )

    normalized_lines: list[str] = []
    for line in lines:
        if line.lower().startswith("part "):
            label, sep, rest = line.partition(":")
            if sep:
                rest = _normalize_ssp_specificity(rest)
                if _looks_too_implementation_specific(rest):
                    rest = _normalize_ssp_specificity(rest)
                line = rest.strip()
        else:
            line = _normalize_ssp_specificity(line)
        if line:
            normalized_lines.append(line)

    return "\n\n".join(normalized_lines)


# ── Option B: Synthetic objectives for no-objective controls ──────────────────

def _derive_objectives_from_statement(control_id: str, statement: str) -> list[str]:
    """Parse lettered parts (a., b., c.) from a control statement as synthetic objectives.

    NIST 800-53 Rev 5 controls whose OSCAL `assessment-objective` parts are absent
    (common in PE, CP, MA, MP, PS families) still have structured statements with
    lettered parts.  Parsing these lets the full multistage pipeline run — including
    SHA anchoring, verdict challenge, and part-structured SSP output — instead of
    silently degrading to single-stage.

    Handles both common formats:
      "a. Do X;\\nb. Do Y;"     — newline-separated
      "a. Do X; b. Do Y;"       — semicolon-inline
      "a. Do X\\n\\nb. Do Y"    — blank-line-separated
    """
    objectives: list[str] = []

    # Locate all "x. " part markers (single lowercase letter + period + whitespace)
    # anchored after start-of-string, semicolons, or newlines
    pattern = re.compile(r'(?:^|[;\n])\s*([a-z])\.\s+', re.MULTILINE)
    positions = [(m.group(1), m.start(), m.end()) for m in pattern.finditer(statement)]

    if len(positions) >= 2:
        for idx, (letter, _, end) in enumerate(positions):
            next_start = positions[idx + 1][1] if idx + 1 < len(positions) else len(statement)
            text = statement[end:next_start].strip().rstrip(';').strip()
            # Strip trailing sub-parts that leaked in
            text = re.split(r'\n\s*[a-z]\.\s', text)[0].strip()
            if len(text) > 10:
                objectives.append(f"{control_id}({letter}): {text[:150]}")
    elif len(positions) == 1:
        letter, _, end = positions[0]
        text = statement[end:].strip().rstrip(';').strip()
        if len(text) > 10:
            objectives.append(f"{control_id}({letter}): {text[:150]}")

    # Fallback: split by semicolons when no lettered parts exist
    if not objectives:
        clauses = [
            c.strip().rstrip(';').strip()
            for c in re.split(r';\s*', statement)
            if len(c.strip()) > 20
        ]
        for i, clause in enumerate(clauses[:8], start=1):
            objectives.append(f"{control_id}(clause-{i}): {clause[:150]}")

    # Last resort: whole statement as a single objective
    if not objectives and len(statement.strip()) > 20:
        objectives.append(f"{control_id}: {statement.strip()[:200]}")

    return objectives


# ── Main entry point ──────────────────────────────────────────────────────────

async def assess_control_multistage(
    control,
    project_id: int,
    system_context: str,
    llm,
    db: AsyncSession,
    max_chunk_tokens: int = 8000,
    rag_fallback_fn=None,
    skip_stage3: bool = False,
) -> LLMFinding:
    """
    Run the 3-stage assessment pipeline for a single control.

    Returns LLMFinding. Falls back to single-stage if stages fail.
    When skip_stage3=True, uses synthesized narrative (Stage 2 only) — ~2x faster.
    """
    # ── Stage 1: Tag-based chunk retrieval ──────────────────────────────────
    chunks = await get_tagged_chunks(
        control_id=control.display_id,
        project_id=project_id,
        db=db,
        max_tokens=max_chunk_tokens,
    )

    # Supplement with RAG if fewer than 2 tagged chunks
    if len(chunks) < 2 and rag_fallback_fn is not None:
        try:
            rag_chunks = await rag_fallback_fn()
            seen_content = {c["content"] if isinstance(c, dict) else c for c in chunks}
            for c in rag_chunks:
                content = c["content"] if isinstance(c, dict) else c
                if content not in seen_content:
                    # Wrap raw strings from RAG into enriched dict format
                    if isinstance(c, str):
                        chunks.append({
                            "content": c,
                            "filename": "RAG Result",
                            "document_type": "other",
                            "document_intent": "other",
                            "date": None,
                            "confidence": 0.5,
                            "source_type": "project",
                        })
                    else:
                        chunks.append(c)
                    seen_content.add(content)
        except Exception:
            pass

    if not chunks:
        # Option C: no evidence found in any source (tagged chunks + RAG fallback both empty).
        # Indexed documents exist for this project but none are relevant to this control.
        # Return a deterministic non_compliant finding — absence of evidence IS a finding.
        # High confidence because we specifically searched and found nothing.
        logger.info(
            "Multistage: %s — no evidence found in any source (tagged + RAG). "
            "Returning deterministic non_compliant.",
            control.display_id,
        )
        return LLMFinding(
            status="non_compliant",
            implementation_statement=(
                f"No documentation addressing {control.display_id} — {control.title} was found "
                "in the uploaded project documents, common control libraries, or enterprise "
                "policy/procedure libraries. A compliance determination cannot be made without evidence."
            ),
            gaps=[
                f"{control.display_id}: No evidence found in any reviewed documentation source. "
                "Upload relevant policies, procedures, configurations, or SSP sections and re-run."
            ],
            evidence_citations=[],
            remediation_plan=(
                f"1. Identify and upload documentation that addresses {control.display_id} "
                f"({control.title}) — e.g., relevant policy sections, procedures, system "
                "configurations, or SSP implementation statements.\n"
                "2. Ensure uploaded documents are fully indexed (parse_status = 'indexed') "
                "before re-running.\n"
                "3. Re-run the assessment for this control after uploading."
            ),
            confidence=0.92,
            synthesized=True,
        )

    objectives = control.assessment_objectives
    if not objectives:
        # Option B: no formal OSCAL objectives — derive synthetic ones from the control
        # statement so the full multistage pipeline can still run (SHA anchoring,
        # verdict challenge, part-structured SSP output).
        objectives = _derive_objectives_from_statement(control.display_id, control.statement or "")
        if objectives:
            logger.info(
                "Multistage: %s — no OSCAL objectives; derived %d synthetic objectives from statement.",
                control.display_id, len(objectives),
            )
        else:
            # Control statement too sparse to parse — fall back to single-stage
            logger.info(
                "Multistage: %s — no objectives and statement too sparse; falling back to single-stage.",
                control.display_id,
            )
            return None

    # ── Stage 2: Gap analysis (LLM) ─────────────────────────────────────────
    gap_analysis = await run_gap_analysis(
        control_id=control.display_id,
        control_title=control.title,
        objectives=objectives,
        chunks=chunks,
        system_context=system_context,
        llm=llm,
    )

    if not gap_analysis:
        # Stage 2 failed — fall back to single-stage
        return None

    # ── Code verdict calculation (Option A — SHALL-anchored) ────────────────
    status, confidence, shall_failures = calculate_verdict(gap_analysis)

    if shall_failures:
        logger.info(
            "Multistage: %s SHALL failures in %d objectives: %s",
            control.display_id, len(shall_failures), ", ".join(shall_failures[:5]),
        )

    # ── Stage 2.5: Verdict challenge (Option C) ──────────────────────────────
    challenge_note = await run_verdict_challenge(
        control_id=control.display_id,
        control_title=control.title,
        gap_analysis=gap_analysis,
        status=status,
        confidence=confidence,
        shall_failures=shall_failures,
        llm=llm,
    )
    if challenge_note:
        logger.info(
            "Multistage: %s — LLM challenge dissent: %s",
            control.display_id, challenge_note[:120],
        )

    # ── Stage 3: Narrative writing (LLM) ────────────────────────────────────
    if skip_stage3:
        # Synthesize narrative from Stage 2 data — no extra LLM call, ~2x faster
        finding = _synthesize_narrative(
            control_id=control.display_id,
            control_title=control.title,
            status=status,
            confidence=confidence,
            gap_analysis=gap_analysis,
        )
    else:
        finding = await run_narrative(
            control_id=control.display_id,
            control_title=control.title,
            control_statement=control.statement,
            status=status,
            confidence=confidence,
            gap_analysis=gap_analysis,
            chunks=chunks,
            system_context=system_context,
            llm=llm,
            shall_failures=shall_failures,   # Issue 3: guide remediation priority
            challenge_note=challenge_note,   # Issue 3: surface dissent in remediation
        )

    # Attach challenge note to finding (Option C — recorded, does not alter verdict)
    if challenge_note:
        finding.llm_challenge_note = challenge_note

    logger.info(
        "Multistage: %s → %s (%.0f%%) | %d objectives: %d met, %d partial, %d unmet%s",
        control.display_id, status, confidence * 100,
        len(gap_analysis),
        sum(1 for o in gap_analysis if o["met"] == "yes"),
        sum(1 for o in gap_analysis if o["met"] == "partial"),
        sum(1 for o in gap_analysis if o["met"] == "no"),
        f" | SHALL failures: {len(shall_failures)}" if shall_failures else "",
    )

    return finding
