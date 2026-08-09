"""LLM-driven first-pass screening for parsed document lines.

This replaces the old keyword-only gate with a reasoning-model batch screen.
The model does lightweight relevance detection only. It is intentionally
inclusive and does not make final assessment decisions.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from app.services.ingestion.http_retry import post_json_with_retry

from app.services.controls.catalog import load_catalog

logger = logging.getLogger(__name__)

SCREENING_SYSTEM_PROMPT = """You are a NIST SP 800-53 Rev. 5 evidence screener.

Your job is to perform a lightweight first-pass relevance screen across parsed
artifact text units. You are NOT making a compliance decision. You are deciding
whether each text unit is plausibly relevant to any NIST 800-53 control or
enhancement and should be promoted for context expansion.

Return ONLY a valid JSON array. One object per input item:
[
  {
    "item_id": 123,
    "relevance_score": 0.0,
    "candidate_controls": ["AC-2", "AT-4"],
    "candidate_enhancements": ["AC-2(1)"],
    "rationale": "Short explanation grounded in the supplied text."
  }
]

SCREENING RULES:
- Be inclusive. If there is plausible relevance, score it above 0.15.
- Do not require exact keyword matches.
- Use the supplied excerpt, provenance, headers, row context, and section path.
- Do not rely on filename, library name, or assumptions outside the provided text.
- A single item may map to multiple candidate controls.
- Only return control IDs that are plausible and grounded in the excerpt.
- Only return enhancement IDs when the text clearly points to enhancement-level detail.
- If an item has no meaningful control relevance, use a score below 0.15 and empty arrays.

SCORING GUIDE:
- 0.00 to 0.14: no meaningful relevance
- 0.15 to 0.34: weak but credible relevance worth expanding
- 0.35 to 0.64: moderate relevance to one or more likely controls
- 0.65 to 1.00: strong direct relevance to specific controls

Keep rationale concise and specific. Respond with JSON only."""


def _build_think_params(reasoning_effort: str) -> tuple[dict, dict]:
    effort_map = {
        "none": ({"think": False}, {"reasoning_effort": "none"}),
        "low": ({"think": False}, {"reasoning_effort": "low"}),
        "medium": ({"think": True}, {"reasoning_effort": "medium"}),
        "high": ({"think": True}, {"reasoning_effort": "high"}),
    }
    return effort_map.get(reasoning_effort, ({"think": True}, {"reasoning_effort": "high"}))


@lru_cache(maxsize=1)
def _control_label_sets() -> tuple[set[str], set[str]]:
    catalog = load_catalog()
    base = set()
    enhancements = set()
    for control in catalog.values():
        label = control.display_id.upper()
        if control.is_enhancement:
            enhancements.add(label)
        else:
            base.add(label)
    return base, enhancements


@lru_cache(maxsize=1)
def build_screening_reference() -> str:
    """Compact family/control reference for the screening prompt."""
    catalog = load_catalog()
    families: dict[str, dict] = {}
    for control in catalog.values():
        if control.is_enhancement:
            continue
        family = control.family_id.upper()
        bucket = families.setdefault(
            family,
            {
                "title": control.family_title,
                "controls": [],
            },
        )
        bucket["controls"].append((control.display_id.upper(), control.title))

    lines = []
    for family in sorted(families):
        bucket = families[family]
        controls = sorted(bucket["controls"], key=lambda item: item[0])
        sample = "; ".join(f"{cid} {title}" for cid, title in controls[:12])
        lines.append(f"{family} {bucket['title']}: {sample}")
    return "\n".join(lines)


def _sanitize_score(value) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _normalize_control_ids(raw_ids: list, allowed: set[str]) -> list[str]:
    seen: list[str] = []
    for raw in raw_ids or []:
        if not isinstance(raw, str):
            continue
        candidate = raw.strip().upper()
        if candidate in allowed and candidate not in seen:
            seen.append(candidate)
    return seen[:8]


def _fallback_results(items: list[dict]) -> list[dict]:
    from app.services.ingestion.corpus import screen_line

    out: list[dict] = []
    for item in items:
        excerpt = str(item.get("excerpt") or "").strip()
        heuristic = screen_line(excerpt, threshold=0.15)
        score = max(0.15, float(heuristic.get("relevance_score") or 0.0)) if excerpt else 0.0
        out.append(
            {
                "item_id": item["item_id"],
                "relevance_score": score,
                "candidate_controls": heuristic.get("candidate_controls") or [],
                "candidate_enhancements": heuristic.get("candidate_enhancements") or [],
                "rationale": "Heuristic fallback used after LLM screening failure",
            }
        )
    return out


def _parse_results(raw: str, items: list[dict]) -> list[dict]:
    base_controls, enhancement_controls = _control_label_sets()
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return _fallback_results(items)

    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return _fallback_results(items)

    if not isinstance(parsed, list):
        return _fallback_results(items)

    by_id = {item["item_id"]: item for item in items}
    out: dict[int, dict] = {}

    for row in parsed:
        if not isinstance(row, dict):
            continue
        item_id = row.get("item_id")
        if item_id not in by_id:
            continue
        out[item_id] = {
            "item_id": item_id,
            "relevance_score": _sanitize_score(row.get("relevance_score")),
            "candidate_controls": _normalize_control_ids(row.get("candidate_controls") or [], base_controls),
            "candidate_enhancements": _normalize_control_ids(row.get("candidate_enhancements") or [], enhancement_controls),
            "rationale": str(row.get("rationale") or "")[:300] or "No rationale provided",
        }

    return [
        out.get(
            item["item_id"],
            {
                "item_id": item["item_id"],
                "relevance_score": 0.0,
                "candidate_controls": [],
                "candidate_enhancements": [],
                "rationale": "No result returned for item",
            },
        )
        for item in items
    ]


async def screen_batch(
    items: list[dict],
    ollama_base_url: str,
    model: str,
    timeout_secs: int = 90,
    reasoning_effort: str = "medium",
    api_key: str = "",
    extra_headers: dict | None = None,
) -> list[dict]:
    """Run LLM screening over a batch of parsed text units."""
    if not items:
        return []

    from app.services.prompt_manager import get_prompt

    system_prompt = await get_prompt("ingestion_screening", SCREENING_SYSTEM_PROMPT)
    reference = build_screening_reference()
    item_blob = json.dumps(items, ensure_ascii=True)
    user_prompt = (
        "NIST family and representative control reference:\n"
        f"{reference}\n\n"
        "Screen the following parsed artifact items for possible relevance. "
        "Return one JSON object per item using the exact item_id values.\n\n"
        f"{item_blob}"
    )

    top_params, options_extra = _build_think_params(reasoning_effort)
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, **options_extra},
        **top_params,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    try:
        resp = await post_json_with_retry(
            f"{ollama_base_url.rstrip('/')}/api/chat",
            headers=headers,
            payload=body,
            timeout_secs=timeout_secs,
        )
        data = resp.json()
        raw = data.get("message", {}).get("content", "")
    except Exception as exc:
        logger.warning("Ollama screening call failed: %s", type(exc).__name__)
        return _fallback_results(items)

    return _parse_results(raw, items)
