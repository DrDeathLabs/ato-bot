"""LLM classification for evidence units using Ollama.

Stage 4 of the ingestion pipeline. Supports both single-unit and batch
classification so ingestion can amortize model overhead across multiple
evidence units in one request.
"""
from __future__ import annotations

import json
import logging
import re
from json import JSONDecodeError

from app.services.ingestion.http_retry import post_json_with_retry

logger = logging.getLogger(__name__)

CLASSIFICATION_SYSTEM_PROMPT = """You are a NIST 800-53 Rev 5 evidence analyst. You are given an excerpt from a document.

Your task is to classify this excerpt and identify which NIST 800-53 Rev 5 controls it provides evidence for.

Return ONLY valid JSON with this exact structure:
{
  "control_ids": ["AC-2", "AC-3"],
  "enhancement_ids": ["AC-2(1)", "AC-2(3)"],
  "artifact_type": "procedure",
  "evidence_strength": "moderate",
  "evidence_language_type": "procedural_language",
  "explanation": "Brief explanation of why these controls are relevant",
  "confidence": 0.75
}

ARTIFACT TYPE must be exactly one of:
  policy | procedure | implementation_statement | technical_config |
  operational | test_evidence | management | diagram_narrative | audit_artifact | other

EVIDENCE STRENGTH must be exactly one of:
  strong | moderate | weak | insufficient

EVIDENCE LANGUAGE TYPE must be exactly one of:
  policy_language | implementation_language | procedural_language | objective_evidence | mixed

RULES:
- Only include control IDs that are genuinely evidenced by the text.
- Do NOT invent implementations, mappings, or claims not in the text.
- control_ids must use NIST 800-53 Rev 5 format: "AC-2", "SC-28", etc.
- enhancement_ids use format: "AC-2(1)", "SC-28(1)", etc.
- If no controls are clearly evidenced, return empty arrays.
- confidence is 0.0-1.0 indicating your certainty in the classification.
- RESPOND WITH ONLY THE JSON OBJECT."""

BATCH_CLASSIFICATION_SYSTEM_PROMPT = """You are a NIST 800-53 Rev 5 evidence analyst. You are given multiple document excerpts.

For each excerpt, classify which NIST 800-53 Rev 5 controls it provides evidence for.

Return ONLY valid JSON as an array of objects with this exact structure:
[
  {
    "id": 101,
    "control_ids": ["AC-2", "AC-3"],
    "enhancement_ids": ["AC-2(1)", "AC-2(3)"],
    "artifact_type": "procedure",
    "evidence_strength": "moderate",
    "evidence_language_type": "procedural_language",
    "explanation": "Brief explanation of why these controls are relevant",
    "confidence": 0.75
  }
]

RULES:
- Return exactly one object for every provided id.
- Only include control IDs genuinely evidenced by the excerpt.
- Do NOT invent implementations, mappings, or claims not in the text.
- Keep explanations concise.
- RESPOND WITH ONLY THE JSON ARRAY."""


def _build_think_params(reasoning_effort: str) -> tuple[dict, dict]:
    effort_map = {
        "none": ({"think": False}, {"reasoning_effort": "none"}),
        "low": ({"think": False}, {"reasoning_effort": "low"}),
        "medium": ({"think": True}, {"reasoning_effort": "medium"}),
        "high": ({"think": True}, {"reasoning_effort": "high"}),
    }
    return effort_map.get(reasoning_effort, ({"think": True}, {"reasoning_effort": "high"}))


def _build_headers(api_key: str = "", extra_headers: dict | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)
    return headers


async def _post_chat(
    *,
    system_prompt: str,
    user_prompt: str,
    ollama_base_url: str,
    model: str,
    timeout_secs: int,
    reasoning_effort: str,
    api_key: str,
    extra_headers: dict | None,
) -> str:
    top_params, options_extra = _build_think_params(reasoning_effort)
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0, **options_extra},
        **top_params,
    }

    resp = await post_json_with_retry(
        f"{ollama_base_url.rstrip('/')}/api/chat",
        headers=_build_headers(api_key, extra_headers),
        payload=body,
        timeout_secs=timeout_secs,
    )
    data = resp.json()
    return data.get("message", {}).get("content", "")


async def classify_unit(
    content: str,
    candidate_controls: list[str],
    section_path: str | None,
    ollama_base_url: str,
    model: str,
    timeout_secs: int = 60,
    reasoning_effort: str = "medium",
    api_key: str = "",
    extra_headers: dict | None = None,
) -> dict:
    candidate_hint = ""
    if candidate_controls:
        candidate_hint = (
            f"\n\nScreening pre-identified these candidate controls (use as hints only, "
            f"do not blindly accept): {', '.join(candidate_controls[:10])}"
        )

    section_hint = f"\n\nSource section: {section_path}" if section_path else ""
    user_prompt = (
        f"Classify this document excerpt for NIST 800-53 Rev 5 control relevance:"
        f"{section_hint}{candidate_hint}\n\n"
        f"--- EXCERPT ---\n{content[:3000]}\n--- END EXCERPT ---"
    )

    try:
        raw = await _post_chat(
            system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            ollama_base_url=ollama_base_url,
            model=model,
            timeout_secs=timeout_secs,
            reasoning_effort=reasoning_effort,
            api_key=api_key,
            extra_headers=extra_headers,
        )
    except Exception as exc:
        logger.warning("Ollama classification call failed: %s", type(exc).__name__)
        return _fallback_classification(candidate_controls, model)

    return _parse_classification(raw, candidate_controls, model)


async def classify_units_batch(
    items: list[dict],
    ollama_base_url: str,
    model: str,
    timeout_secs: int = 60,
    reasoning_effort: str = "medium",
    api_key: str = "",
    extra_headers: dict | None = None,
) -> list[dict]:
    payload_items = []
    for item in items:
        payload_items.append(
            {
                "id": item["unit_id"],
                "section_path": item.get("section_path") or "",
                "candidate_controls": item.get("candidate_controls") or [],
                "excerpt": (item.get("content") or "")[:1800],
            }
        )

    user_prompt = (
        "Classify these document excerpts for NIST 800-53 Rev 5 control relevance.\n\n"
        f"{json.dumps(payload_items, ensure_ascii=False)}"
    )

    try:
        raw = await _post_chat(
            system_prompt=BATCH_CLASSIFICATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            ollama_base_url=ollama_base_url,
            model=model,
            timeout_secs=timeout_secs,
            reasoning_effort=reasoning_effort,
            api_key=api_key,
            extra_headers=extra_headers,
        )
    except Exception as exc:
        logger.warning("Ollama batch classification call failed: %s", type(exc).__name__)
        return [_fallback_classification(item.get("candidate_controls") or [], model) for item in items]

    return _parse_batch_classification(raw, items, model)


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'```\s*$', '', raw, flags=re.MULTILINE)
    return raw


def _parse_classification(raw: str, candidate_controls: list[str], model: str) -> dict:
    raw = _strip_fences(raw)
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return _fallback_classification(candidate_controls, model)

    try:
        data = json.loads(match.group())
    except JSONDecodeError:
        return _fallback_classification(candidate_controls, model)

    return _sanitize_classification_payload(data, candidate_controls, model)


def _parse_batch_classification(raw: str, items: list[dict], model: str) -> list[dict]:
    raw = _strip_fences(raw)
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not match:
        return [_fallback_classification(item.get("candidate_controls") or [], model) for item in items]

    try:
        data = json.loads(match.group())
    except JSONDecodeError:
        return [_fallback_classification(item.get("candidate_controls") or [], model) for item in items]

    if not isinstance(data, list):
        return [_fallback_classification(item.get("candidate_controls") or [], model) for item in items]

    by_id: dict[int, dict] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            row_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        by_id[row_id] = row

    results: list[dict] = []
    for item in items:
        row = by_id.get(item["unit_id"])
        if row is None:
            results.append(_fallback_classification(item.get("candidate_controls") or [], model))
            continue
        results.append(_sanitize_classification_payload(row, item.get("candidate_controls") or [], model))
    return results


def _sanitize_classification_payload(data: dict, candidate_controls: list[str], model: str) -> dict:
    valid_control_pattern = re.compile(r'^[A-Z]{2}-\d+$')
    valid_enhancement_pattern = re.compile(r'^[A-Z]{2}-\d+\(\d+\)$')

    control_ids = [
        c for c in (data.get("control_ids") or [])
        if isinstance(c, str) and valid_control_pattern.match(c.strip().upper())
    ]
    enhancement_ids = [
        c for c in (data.get("enhancement_ids") or [])
        if isinstance(c, str) and valid_enhancement_pattern.match(c.strip().upper())
    ]

    valid_artifact_types = {
        "policy", "procedure", "implementation_statement", "technical_config",
        "operational", "test_evidence", "management", "diagram_narrative",
        "audit_artifact", "other",
    }
    valid_strengths = {"strong", "moderate", "weak", "insufficient"}
    valid_language_types = {
        "policy_language", "implementation_language", "procedural_language",
        "objective_evidence", "mixed",
    }

    artifact_type = data.get("artifact_type", "other")
    if artifact_type not in valid_artifact_types:
        artifact_type = "other"

    evidence_strength = data.get("evidence_strength", "weak")
    if evidence_strength not in valid_strengths:
        evidence_strength = "weak"

    evidence_language_type = data.get("evidence_language_type", "mixed")
    if evidence_language_type not in valid_language_types:
        evidence_language_type = "mixed"

    confidence = data.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        confidence = None

    return {
        "control_ids": control_ids or candidate_controls[:5],
        "enhancement_ids": enhancement_ids,
        "artifact_type": artifact_type,
        "evidence_strength": evidence_strength,
        "evidence_language_type": evidence_language_type,
        "explanation": str(data.get("explanation", ""))[:500],
        "confidence": confidence,
        "model_name": model,
    }


def _fallback_classification(candidate_controls: list[str], model: str) -> dict:
    return {
        "control_ids": candidate_controls[:5] if candidate_controls else [],
        "enhancement_ids": [],
        "artifact_type": "other",
        "evidence_strength": "weak",
        "evidence_language_type": "mixed",
        "explanation": "Classification unavailable - using screening candidates as fallback.",
        "confidence": None,
        "model_name": model,
    }
