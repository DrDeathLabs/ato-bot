"""
Control Tagger — Full-document LLM analysis against NIST 800-53 Rev 5.

ARCHITECTURE
============
Previous design (replaced):
  - Processed each chunk in isolation with a keyword/pattern scanner
  - Could not distinguish "AC-2 is not implemented" from "AC-2 is implemented"
  - Missed controls in documents that never used NIST identifiers
  - Allowed any framework's control IDs into the tag table

New design:
  Phase 1 — Full document analysis
    The LLM reads the complete document (section-by-section for large docs),
    classifies the document type and intent, then identifies every control from
    the project's NIST 800-53 Rev 5 baseline that the document provides
    implementation evidence for.  Matching is semantic and substantive — a
    firewall ruleset satisfies SC-7 even if it contains no NIST language.

  Phase 2 — Chunk-level mapping
    Key text excerpts returned by Phase 1 are matched back to specific database
    chunks via exact and fuzzy text search.  Chunks receive tags derived from
    full-document understanding, not from scanning in isolation.

ENFORCEMENT
===========
  - NIST 800-53 Rev 5 ONLY.  All LLM-returned control IDs are validated against
    the project baseline (itself loaded from the authoritative 800-53 Rev 5 JSON
    catalog).  Any ID not present in that catalog is silently discarded.
  - Confidence threshold 0.65 for evidence retrieval use (stored regardless;
    the retrieval query applies the threshold at query time).
  - Large documents processed section-by-section; document type/intent context
    is carried across sections so later sections are not assessed in isolation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from difflib import SequenceMatcher

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Global semaphore — max 5 concurrent document tagging jobs.
_DOC_SEMAPHORE: asyncio.Semaphore | None = None

# Token budget per document section sent to the LLM.
# 512-token chunks → ~12 chunks per section at this budget.
MAX_TOKENS_PER_SECTION = 6_000

# Minimum confidence to store a tag. Retrieval query uses 0.65 as its live
# threshold; storing from 0.40 lets admins adjust without re-indexing.
MIN_STORE_CONFIDENCE = 0.40

# Minimum ratio for fuzzy excerpt-to-chunk matching.
FUZZY_MATCH_THRESHOLD = 0.70


# ---------------------------------------------------------------------------
# LLM Prompt
# ---------------------------------------------------------------------------

DOCUMENT_ANALYSIS_SYSTEM_PROMPT = """You are a senior NIST 800-53 Rev 5 security assessor, cybersecurity engineer, and information systems architect. You are conducting a federal security authorization assessment under the NIST Risk Management Framework (RMF).

═══════════════════════════════════════════════════════════
ABSOLUTE REQUIREMENT — FRAMEWORK CONSTRAINT
═══════════════════════════════════════════════════════════
You MUST use ONLY NIST 800-53 Rev 5 control identifiers.
No other framework is permissible under any circumstance.

PROHIBITED: ISO 27001 controls, NIST CSF functions/subcategories, NIST SP 800-171 controls,
CMMC practices, CIS Controls, SOC 2 criteria, FedRAMP-specific identifiers, or any other
framework. Every control_id you return MUST appear in the baseline list provided below.

═══════════════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════════════
Read the document text provided and identify every NIST 800-53 Rev 5 control from the
project baseline that this document provides evidence for.

STEP 1 — Classify the document:
  document_type: policy | procedure | ssp | system_design | configuration |
                 training_record | contract | audit_finding | poam |
                 assessment_report | technical_evidence | other
  document_intent: implements | plans | documents_gaps | evaluates | other

STEP 2 — Map controls using SUBSTANTIVE matching, not keyword matching:

  CORRECT — tag these:
    An HR onboarding document describing account creation and approval steps
    SATISFIES AC-2 even if it never mentions "AC-2" or "NIST"

    A firewall ruleset with ingress/egress rules SATISFIES SC-7 regardless
    of whether it contains any NIST language

    A backup job schedule showing daily incremental and weekly full backups
    SATISFIES CP-9 requirements regardless of terminology used

    A password complexity configuration showing minimum length, complexity,
    and expiration settings SATISFIES IA-5(1)

  INCORRECT — do not tag these:
    A document that says "AC-2 is not implemented" does NOT satisfy AC-2
    (tag it anyway — the assessor downstream will interpret the nature of the evidence)

    A table of contents entry "Section 4: Access Control" does NOT satisfy AC-1

    A future-tense plan "accounts will be reviewed quarterly" does NOT satisfy
    the control — it documents intent, not current implementation

TAG ALL DOCUMENT TYPES:
  Tag audit findings, POA&Ms, gap analyses, and assessment reports the same as
  any other document. The assessor evaluating evidence downstream will interpret
  whether the evidence supports or contradicts compliance. Your job is only to
  identify which controls are substantively referenced.

═══════════════════════════════════════════════════════════
CONFIDENCE SCALE
═══════════════════════════════════════════════════════════
  0.90-1.00  Document is the primary authoritative implementation record
             (e.g., the actual account management procedure for AC-2)
  0.75-0.89  Document clearly describes implementation with substantial detail
  0.65-0.74  Document describes relevant implementation aspects partially
             or indirectly
  0.50-0.64  Document touches on the control with limited implementation detail
  Below 0.50 Omit — connection too tenuous to contribute useful evidence

═══════════════════════════════════════════════════════════
PROJECT BASELINE — NIST 800-53 Rev 5
Evaluate against ONLY the controls listed here. Return no other control IDs.
═══════════════════════════════════════════════════════════
{baseline_controls}

═══════════════════════════════════════════════════════════
RESPONSE FORMAT
═══════════════════════════════════════════════════════════
Return ONLY valid JSON. No markdown fences, no explanation, nothing outside the JSON.

{{
  "document_type": "procedure",
  "document_intent": "implements",
  "document_summary": "IT account management procedure covering account creation, approval, role assignment, and quarterly review",
  "controls": [
    {{
      "control_id": "AC-2",
      "confidence": 0.91,
      "rationale": "Defines account types, requires manager approval via Access Request Form, scopes access to minimum required role, mandates quarterly account review by system owners",
      "key_excerpts": [
        "Accounts are classified as: standard user, privileged user, service account, and temporary account",
        "A manager must submit a completed Access Request Form prior to IT provisioning any account",
        "All active accounts are reviewed quarterly by the designated system owner"
      ]
    }}
  ]
}}"""

# Backward-compatibility alias — prompt_manager.py imports this name.
CONTROL_TAGGING_SYSTEM_PROMPT = DOCUMENT_ANALYSIS_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Semaphore helper
# ---------------------------------------------------------------------------

def _get_doc_semaphore() -> asyncio.Semaphore:
    global _DOC_SEMAPHORE
    if _DOC_SEMAPHORE is None:
        _DOC_SEMAPHORE = asyncio.Semaphore(5)
    return _DOC_SEMAPHORE


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def tag_document(document_id: int) -> None:
    """Background task: tag all chunks of a document with NIST 800-53 Rev 5 control IDs.

    Acquires a global semaphore (max 5 concurrent jobs) before starting so that
    bulk re-index operations do not saturate the LLM provider.
    """
    from app.models.orm import Document

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if doc and doc.parse_status not in ("pending", "processing"):
            doc.parse_status = "queued"
            await db.commit()

    async with _get_doc_semaphore():
        await _tag_document(document_id)


# ---------------------------------------------------------------------------
# Core implementation
# ---------------------------------------------------------------------------

async def _tag_document(document_id: int) -> None:
    """Full-document LLM tagging pipeline. Called only when the semaphore is held."""
    from app.core.config import get_settings
    from app.models.orm import Document, DocumentChunk, DocumentChunkControlTag, Project
    from app.services.controls.catalog import load_baseline, load_catalog
    from app.services.prompt_manager import get_prompt

    settings = get_settings()

    # ------------------------------------------------------------------
    # Load document, chunks, and project baseline
    # ------------------------------------------------------------------
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return

        doc.parse_status = "indexing"
        await db.commit()

        # Autogenerated artifacts use forced tags — skip LLM to prevent
        # incidental tag dilution across unrelated controls.
        if doc.autogenerated and doc.artifact_controls:
            await _apply_forced_tags(document_id, doc.artifact_controls)
            return

        # Load chunks ordered by position
        chunks_result = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        chunks = list(chunks_result.scalars().all())

        if not chunks:
            doc.parse_status = "indexed"
            await db.commit()
            return

        # Load project for baseline scoping
        project = None
        if doc.project_id:
            proj_result = await db.execute(
                select(Project).where(Project.id == doc.project_id)
            )
            project = proj_result.scalar_one_or_none()

    # Determine baseline — default to "high" (superset) for enterprise/non-project docs
    baseline_name = project.impact_baseline if project else "high"
    try:
        baseline_controls = load_baseline(baseline_name)
    except Exception:
        logger.warning(
            "Could not load baseline '%s' for document %d — using full catalog",
            baseline_name, document_id,
        )
        baseline_controls = list(load_catalog().values())

    # Build the valid control ID set from the 800-53 Rev 5 catalog labels
    valid_control_ids: set[str] = {c.label.upper() for c in baseline_controls}

    # ------------------------------------------------------------------
    # Phase 1 — Full document analysis via LLM
    # ------------------------------------------------------------------
    try:
        from app.services.llm.runtime import build_provider_for_purpose

        async with AsyncSessionLocal() as cfg_db:
            llm, _ = await build_provider_for_purpose(
                cfg_db,
                "document_tagging",
                provider_name=settings.default_llm_provider,
            )
        system_prompt_raw = await get_prompt("control_tagging", DOCUMENT_ANALYSIS_SYSTEM_PROMPT)

        # Inject the project baseline into the prompt
        baseline_text = _format_baseline_for_prompt(baseline_controls)
        if "{baseline_controls}" in system_prompt_raw:
            system_prompt = system_prompt_raw.format(baseline_controls=baseline_text)
        else:
            # Admin-overridden prompt without the placeholder — append baseline
            system_prompt = (
                system_prompt_raw
                + f"\n\nNIST 800-53 Rev 5 PROJECT BASELINE "
                  f"(ONLY these control IDs are valid):\n{baseline_text}"
            )

        control_mappings, doc_type, doc_intent = await _analyze_document(
            llm=llm,
            system_prompt=system_prompt,
            chunks=chunks,
            valid_control_ids=valid_control_ids,
        )

        logger.info(
            "Document %d Phase 1 complete: type=%s intent=%s %d controls across %d chunks",
            document_id, doc_type, doc_intent, len(control_mappings), len(chunks),
        )

        # ------------------------------------------------------------------
        # Phase 2 — Map control mappings back to specific chunks
        # ------------------------------------------------------------------
        async with AsyncSessionLocal() as db:
            chunk_ids = [c.id for c in chunks]
            await db.execute(
                delete(DocumentChunkControlTag).where(
                    DocumentChunkControlTag.chunk_id.in_(chunk_ids)
                )
            )
            total_tags = _apply_chunk_tags(db, chunks, control_mappings)
            await db.commit()

        # Mark indexed — store document_type and document_intent for Stage 2 context
        async with AsyncSessionLocal() as db:
            doc_result = await db.execute(
                select(Document).where(Document.id == document_id)
            )
            doc = doc_result.scalar_one_or_none()
            if doc:
                doc.parse_status = "indexed"
                doc.parse_error = None
                doc.document_type = doc_type
                doc.document_intent = doc_intent
            await db.commit()

        logger.info(
            "Indexed document %d: %d chunks → %d control tags (%d unique controls)",
            document_id, len(chunks), total_tags, len(control_mappings),
        )

    except Exception as e:
        logger.error("Tagging failed for document %d: %s", document_id, e, exc_info=True)
        async with AsyncSessionLocal() as db:
            doc_result = await db.execute(
                select(Document).where(Document.id == document_id)
            )
            doc = doc_result.scalar_one_or_none()
            if doc:
                doc.parse_status = "index_failed"
                doc.parse_error = f"Indexing failed: {str(e)[:500]}"
            await db.commit()


# ---------------------------------------------------------------------------
# Phase 1 — Document analysis
# ---------------------------------------------------------------------------

async def _analyze_document(
    llm,
    system_prompt: str,
    chunks: list,
    valid_control_ids: set[str],
) -> tuple[list[dict], str, str]:
    """Run the full document through the LLM in sections.

    Sections are processed sequentially. After the first section, the document
    type, intent, and summary are carried forward so subsequent sections are
    interpreted in the correct context — not as standalone fragments.

    Returns (control_mappings, doc_type, doc_intent).
    """
    sections = _split_into_sections(chunks, MAX_TOKENS_PER_SECTION)

    # control_id -> best mapping (highest confidence; excerpts merged across sections)
    best_mappings: dict[str, dict] = {}
    document_context: str = ""
    doc_type: str = "other"
    doc_intent: str = "other"

    for section_idx, section_chunks in enumerate(sections):
        section_text = "\n\n---\n\n".join(c.content for c in section_chunks)

        if section_idx == 0:
            user_prompt = (
                "Analyze the following document and identify all NIST 800-53 Rev 5 "
                "controls from the provided baseline that it provides evidence for.\n\n"
                f"{section_text}"
            )
        else:
            user_prompt = (
                f"Document context from earlier sections: {document_context}\n\n"
                "Continue analyzing the next section of this same document. "
                "Identify any NIST 800-53 Rev 5 controls evidenced in this section. "
                "Use the same document_type and document_intent established above.\n\n"
                f"{section_text}"
            )

        try:
            raw = await llm.complete(system_prompt, user_prompt)
            result = _parse_and_validate(raw, valid_control_ids)

            # Capture document context from the first section
            if section_idx == 0:
                doc_type = result.get("document_type") or "other"
                doc_intent = result.get("document_intent") or "other"
                doc_summary = result.get("document_summary", "")
                document_context = (
                    f"Type: {doc_type}, Intent: {doc_intent}. {doc_summary}"
                ).strip()

            # Merge — highest confidence wins; excerpts are unioned across sections
            for mapping in result.get("controls", []):
                ctrl_id = mapping["control_id"]
                existing = best_mappings.get(ctrl_id)

                if not existing:
                    best_mappings[ctrl_id] = mapping
                elif mapping["confidence"] > existing["confidence"]:
                    merged_excerpts = list({
                        *existing.get("key_excerpts", []),
                        *mapping.get("key_excerpts", []),
                    })[:5]
                    best_mappings[ctrl_id] = {**mapping, "key_excerpts": merged_excerpts}
                else:
                    # Keep existing confidence; union new excerpts
                    merged = set(existing.get("key_excerpts", []))
                    merged.update(mapping.get("key_excerpts", []))
                    existing["key_excerpts"] = list(merged)[:5]

        except Exception as e:
            logger.warning(
                "Section %d/%d analysis failed: %s",
                section_idx + 1, len(sections), e,
            )
            continue

    return list(best_mappings.values()), doc_type, doc_intent


def _parse_and_validate(raw: str, valid_control_ids: set[str]) -> dict:
    """Parse LLM JSON and enforce NIST 800-53 Rev 5 baseline compliance.

    Any control ID not present in valid_control_ids is discarded. This is the
    hard enforcement layer that prevents non-800-53-Rev-5 identifiers from
    entering the tag table regardless of what the LLM returns.
    """
    raw = raw.strip()

    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return {"controls": []}

    try:
        data = json.loads(match.group())
    except (json.JSONDecodeError, ValueError):
        return {"controls": []}

    if not isinstance(data, dict):
        return {"controls": []}

    validated: list[dict] = []
    rejected: list[str] = []

    for ctrl in data.get("controls", []):
        if not isinstance(ctrl, dict):
            continue

        raw_id = str(ctrl.get("control_id", "")).strip()
        control_id = _normalize_control_id(raw_id)

        # Hard enforcement: must be in the NIST 800-53 Rev 5 project baseline
        if control_id not in valid_control_ids:
            rejected.append(raw_id)
            continue

        try:
            confidence = float(ctrl.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5

        if confidence < MIN_STORE_CONFIDENCE:
            continue

        excerpts = [
            str(e).strip()
            for e in ctrl.get("key_excerpts", [])
            if isinstance(e, str) and len(str(e).strip()) >= 20
        ][:5]

        validated.append({
            "control_id": control_id,
            "confidence": min(1.0, max(0.0, confidence)),
            "rationale": str(ctrl.get("rationale", ""))[:1000],
            "key_excerpts": excerpts,
        })

    if rejected:
        logger.debug(
            "Discarded %d non-800-53-Rev-5 / out-of-baseline IDs from LLM response: %s",
            len(rejected), rejected[:10],
        )

    return {
        "document_type": str(data.get("document_type", "other")),
        "document_intent": str(data.get("document_intent", "other")),
        "document_summary": str(data.get("document_summary", ""))[:500],
        "controls": validated,
    }


def _normalize_control_id(raw: str) -> str:
    """Normalize a control ID string to standard NIST 800-53 Rev 5 format.

    Handles common LLM output variations:
      "ac-2"      -> "AC-2"
      "AC 2"      -> "AC-2"
      "AC2"       -> "AC-2"
      "AC-2 (1)"  -> "AC-2(1)"
      "ac-2(1)"   -> "AC-2(1)"
    """
    cid = raw.strip().upper()
    cid = re.sub(r'^([A-Z]{2,3})\s+(\d)', r'\1-\2', cid)   # "AC 2"  -> "AC-2"
    cid = re.sub(r'^([A-Z]{2,3})(\d)', r'\1-\2', cid)       # "AC2"   -> "AC-2"
    cid = re.sub(r'\s*\(\s*(\d+)\s*\)', r'(\1)', cid)        # "AC-2 ( 1 )" -> "AC-2(1)"
    return cid


# ---------------------------------------------------------------------------
# Phase 2 — Chunk-level tag application
# ---------------------------------------------------------------------------

def _apply_chunk_tags(db, chunks: list, control_mappings: list[dict]) -> int:
    """Map control mappings back to specific chunks and write tag rows.

    For each control:
      - If key excerpts match specific chunks → tag only those chunks at full confidence
      - If no excerpt matches → tag all chunks at slightly reduced confidence
        (document evidences the control but no specific section was pinpointed)

    Returns total number of tag rows written.
    """
    from app.models.orm import DocumentChunkControlTag

    total_tags = 0

    for mapping in control_mappings:
        control_id = mapping["control_id"]
        confidence = mapping["confidence"]
        rationale = mapping.get("rationale", "")
        key_excerpts = [e for e in mapping.get("key_excerpts", []) if len(e) >= 20]

        matched_chunk_ids: set[int] = set()

        for excerpt in key_excerpts:
            for chunk in chunks:
                if _excerpt_matches_chunk(excerpt, chunk.content):
                    matched_chunk_ids.add(chunk.id)

        if matched_chunk_ids:
            store_confidence = confidence
            notes = rationale
        else:
            # No specific chunk identified — tag the entire document
            matched_chunk_ids = {c.id for c in chunks}
            store_confidence = max(MIN_STORE_CONFIDENCE, confidence * 0.85)
            notes = (
                f"{rationale} "
                "[evidence distributed across document; no specific section isolated]"
            )

        for chunk_id in matched_chunk_ids:
            db.add(DocumentChunkControlTag(
                chunk_id=chunk_id,
                control_id=control_id,
                confidence=store_confidence,
                relevance_notes=notes[:500],
            ))
            total_tags += 1

    return total_tags


def _excerpt_matches_chunk(excerpt: str, chunk_content: str) -> bool:
    """Return True if excerpt appears in chunk_content via exact or fuzzy match."""
    exc_lower = excerpt.lower().strip()
    content_lower = chunk_content.lower()

    # Exact substring (fastest path)
    if exc_lower in content_lower:
        return True

    # Too short for reliable fuzzy matching
    if len(exc_lower) < 30:
        return False

    # Fuzzy — slide a window of excerpt-length across the chunk
    window_size = min(len(exc_lower) + 60, len(content_lower))
    if window_size >= len(content_lower):
        return SequenceMatcher(None, exc_lower, content_lower).ratio() >= FUZZY_MATCH_THRESHOLD

    step = max(1, len(exc_lower) // 5)
    for start in range(0, len(content_lower) - window_size + 1, step):
        window = content_lower[start: start + window_size]
        if SequenceMatcher(None, exc_lower, window).ratio() >= FUZZY_MATCH_THRESHOLD:
            return True

    return False


# ---------------------------------------------------------------------------
# Forced tags for autogenerated artifacts
# ---------------------------------------------------------------------------

async def _apply_forced_tags(document_id: int, forced_controls: list[str]) -> None:
    """Apply exact control tags for AI-generated artifacts without LLM tagging.

    Autogenerated artifacts are authored to address specific controls.
    We apply those controls at 0.95 confidence to every chunk, bypassing
    LLM interpretation to prevent dilution across unrelated controls.
    """
    from app.models.orm import Document, DocumentChunk, DocumentChunkControlTag
    from app.services.controls.catalog import load_catalog

    catalog = load_catalog()
    by_display_id = {control.display_id: control for control in catalog.values()}
    resolved_controls: list[str] = []
    for ctrl_id in forced_controls:
        control = by_display_id.get(str(ctrl_id).strip().upper())
        if control and not control.is_assessable:
            resolved_controls.extend(control.incorporated_into)
        elif control:
            resolved_controls.append(control.display_id)
        else:
            resolved_controls.append(str(ctrl_id).strip().upper())
    forced_controls = sorted({ctrl_id for ctrl_id in resolved_controls if ctrl_id})

    async with AsyncSessionLocal() as db:
        chunks_result = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        chunks = list(chunks_result.scalars().all())

        if chunks:
            chunk_ids = [c.id for c in chunks]
            await db.execute(
                delete(DocumentChunkControlTag).where(
                    DocumentChunkControlTag.chunk_id.in_(chunk_ids)
                )
            )
            for chunk in chunks:
                for ctrl_id in forced_controls:
                    db.add(DocumentChunkControlTag(
                        chunk_id=chunk.id,
                        control_id=ctrl_id,
                        confidence=0.95,
                        relevance_notes=(
                            f"Autogenerated artifact explicitly authored to address {ctrl_id}"
                        ),
                    ))

        doc_result = await db.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = doc_result.scalar_one_or_none()
        if doc:
            doc.parse_status = "indexed"
            doc.parse_error = None

        await db.commit()

    logger.info(
        "Forced-tagged autogenerated document %d: %d controls on %d chunks",
        document_id, len(forced_controls), len(chunks) if chunks else 0,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_into_sections(chunks: list, max_tokens: int) -> list[list]:
    """Group chunks into sections within the token budget.

    Tries to keep chunks from the same document section together by respecting
    the token limit as a soft boundary only when a natural split is available.
    """
    sections: list[list] = []
    current: list = []
    current_tokens: int = 0

    for chunk in chunks:
        chunk_tokens = getattr(chunk, "token_count", None) or (len(chunk.content) // 4)

        if current_tokens + chunk_tokens > max_tokens and current:
            sections.append(current)
            current = [chunk]
            current_tokens = chunk_tokens
        else:
            current.append(chunk)
            current_tokens += chunk_tokens

    if current:
        sections.append(current)

    return sections


def _format_baseline_for_prompt(baseline_controls: list) -> str:
    """Format baseline control list for the LLM prompt.

    Each line: "AC-2 (Account Management)"
    Compact enough to stay within token budget while giving the LLM the
    control title for semantic matching against document content.
    """
    return "\n".join(f"{c.label} ({c.title})" for c in baseline_controls)
