"""Shared helpers for control-level implementation statement generation."""
from __future__ import annotations

import re
from typing import Iterable


_OBJECTIVE_PREFIX_RE = re.compile(
    r"^\s*([A-Z]{2}-\d+[a-z]?(?:\(\d+\))?(?:[a-z])?(?:\.\d+)?(?:\[\d+\])?)[:.\s-]*",
    re.IGNORECASE,
)
_LEADING_MARKER_RE = re.compile(
    r"^\s*(?:\[\s*\d+[a-z]?\s*\]|\(\s*\d+[a-z]?\s*\)|0\d+[a-z]?|\d+[a-z]?[.)\]-])\s*",
    re.IGNORECASE,
)
_ORG_DEFINED_RE = re.compile(r"\[org-defined(?:[^\]]*)\]", re.IGNORECASE)
_ASSIGNMENT_RE = re.compile(r"\[(?:assignment|selection)(?::[^\]]*)?\]", re.IGNORECASE)

_GOVERNANCE_KEYWORDS = (
    "policy",
    "procedure",
    "roles",
    "responsibilities",
    "management commitment",
    "coordination",
    "disseminated",
    "dissemination",
    "review",
    "update",
    "authority",
    "laws",
    "directives",
    "regulations",
    "standards",
    "guidelines",
)
_OPERATIONS_KEYWORDS = (
    "approve",
    "authorized",
    "provision",
    "disable",
    "remove",
    "monitor",
    "enforce",
    "record",
    "retain",
    "verify",
    "configure",
    "log",
    "track",
    "audit",
    "access",
)
_CADENCE_KEYWORDS = (
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "annually",
    "annual",
    "within",
    "at least",
    "frequency",
    "cadence",
    "reviewed",
)


def split_objective_reference(objective: str) -> tuple[str, str]:
    text = str(objective or "").strip()
    if ":" in text:
        objective_id, body = text.split(":", 1)
        return objective_id.strip(), body.strip()
    match = _OBJECTIVE_PREFIX_RE.match(text)
    if match:
        objective_id = match.group(1).strip()
        body = text[match.end():].strip(" -:.")
        return objective_id, body or text.strip()
    return text, text


def normalize_objective_description(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    _objective_id, text = split_objective_reference(text)
    previous = None
    while text and text != previous:
        previous = text
        text = _LEADING_MARKER_RE.sub("", text).strip(" -:.")
    text = _ORG_DEFINED_RE.sub("defined organizational criteria", text)
    text = _ASSIGNMENT_RE.sub("defined organizational values", text)
    text = re.sub(r"\s+", " ", text).strip(" .;:")
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text


def build_control_statement_generation_guidance(
    control_id: str,
    control_title: str,
    objectives: Iterable[str | dict],
) -> str:
    coverage_lines: list[str] = []
    for raw in objectives:
        if isinstance(raw, dict):
            objective_id = str(raw.get("objective_id") or raw.get("id") or control_id).strip()
            description = normalize_objective_description(
                raw.get("description") or raw.get("text") or raw.get("full_text") or objective_id
            )
        else:
            objective_id, description = split_objective_reference(str(raw))
            description = normalize_objective_description(description)
        if objective_id and description:
            coverage_lines.append(f"- {objective_id}: {description}")

    checklist = "\n".join(coverage_lines) if coverage_lines else "- Cover the full control requirement in coherent prose."
    return "\n".join(
        [
            f"CONTROL-LEVEL IMPLEMENTATION STATEMENT STANDARD FOR {control_id} - {control_title}",
            "- Write one integrated control-level implementation statement, not one mini-statement per objective.",
            "- Length target: 3 to 5 paragraphs and roughly 220 to 420 words unless the control is genuinely simpler.",
            "- Use the objectives below as coverage requirements for the control-level statement. Every objective concept must be reflected at least once in narrative form.",
            "- Cover, in natural prose: scope and purpose; responsible and approving roles; implemented process or enforcement; retained evidence or records; review or update cadence; and any organization-defined values, recipients, thresholds, or timing requirements.",
            "- Do not mention objective counts, objective IDs, evidence packet counts, or assessment mechanics in the implementation statement.",
            "- If status is compliant, write affirmative current-state prose. If status is partial or non-compliant, state what is implemented today first, then clearly state what remains undefined, missing, or unsupported.",
            "",
            "OBJECTIVE COVERAGE CHECKLIST:",
            checklist,
        ]
    )


def synthesize_control_implementation_statement(
    *,
    control_id: str,
    control_title: str,
    status: str,
    objectives: Iterable[str | dict] | None,
    gap_analysis: list[dict],
) -> str:
    objective_map: dict[str, str] = {}
    for raw in objectives or []:
        if isinstance(raw, dict):
            objective_id = str(raw.get("objective_id") or raw.get("id") or control_id).strip()
            description = normalize_objective_description(
                raw.get("description") or raw.get("text") or raw.get("full_text") or objective_id
            )
        else:
            objective_id, description = split_objective_reference(str(raw))
            description = normalize_objective_description(description)
        if objective_id and description and objective_id not in objective_map:
            objective_map[objective_id] = description

    met_topics: list[str] = []
    partial_topics: list[str] = []
    unmet_topics: list[str] = []
    missing_details: list[str] = []

    for row in gap_analysis or []:
        objective_id = str(row.get("objective_id") or "").strip()
        description = objective_map.get(objective_id) or normalize_objective_description(objective_id)
        row_status = row.get("met")
        if row_status == "yes":
            if description:
                met_topics.append(description)
        elif row_status == "partial":
            if description:
                partial_topics.append(description)
            if row.get("gap"):
                missing_details.append(str(row.get("gap")).strip().rstrip(".") + ".")
        elif row_status == "no":
            if description:
                unmet_topics.append(description)
            if row.get("gap"):
                missing_details.append(str(row.get("gap")).strip().rstrip(".") + ".")

    if not met_topics and not partial_topics and not unmet_topics:
        return "Insufficient evidence was available to describe the current implementation for this control."

    def _dedupe(values: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            text = str(value or "").strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                ordered.append(text)
        return ordered

    def _join(values: list[str], limit: int = 3) -> str:
        trimmed = [value.rstrip(".") for value in _dedupe(values)[:limit]]
        if not trimmed:
            return ""
        if len(trimmed) == 1:
            return trimmed[0]
        if len(trimmed) == 2:
            return f"{trimmed[0]} and {trimmed[1]}"
        return f"{', '.join(trimmed[:-1])}, and {trimmed[-1]}"

    def _pick(values: list[str], keywords: tuple[str, ...], limit: int = 2) -> list[str]:
        selected: list[str] = []
        for value in _dedupe(values):
            lower = value.lower()
            if any(keyword in lower for keyword in keywords):
                selected.append(value.rstrip("."))
            if len(selected) >= limit:
                break
        return selected

    implemented_topics = _dedupe(met_topics + partial_topics)
    governance_topics = _pick(implemented_topics, _GOVERNANCE_KEYWORDS)
    operational_topics = _pick(implemented_topics, _OPERATIONS_KEYWORDS)
    cadence_topics = _pick(implemented_topics, _CADENCE_KEYWORDS)

    paragraphs: list[str] = []
    coverage_summary = _join(implemented_topics or unmet_topics, limit=3)
    if coverage_summary:
        paragraphs.append(
            f"For {control_id}, {control_title} is addressed through the current control implementation. "
            f"The reviewed materials indicate that {coverage_summary}."
        )

    detail_parts: list[str] = []
    if governance_topics:
        detail_parts.append(
            "Governance and ownership are established through "
            + _join(governance_topics, limit=2)
            + "."
        )
    if operational_topics:
        detail_parts.append(
            "Operationally, the control is carried out through "
            + _join(operational_topics, limit=2)
            + "."
        )
    if cadence_topics:
        detail_parts.append(
            "Review and maintenance expectations are reflected in "
            + _join(cadence_topics, limit=2)
            + "."
        )
    if detail_parts:
        paragraphs.append(" ".join(detail_parts))

    if status == "compliant":
        paragraphs.append(
            "Taken together, the reviewed evidence indicates that the control is implemented in current-state practice and is supported by documented governance, operational activity, and retained review records."
        )
    else:
        unresolved = _join(_dedupe(unmet_topics + partial_topics), limit=3)
        if unresolved:
            paragraphs.append(
                "Current evidence does not yet fully demonstrate "
                + unresolved
                + "."
            )
        if missing_details:
            paragraphs.append(
                "Additional detail is still needed regarding "
                + _join(_dedupe(missing_details), limit=2)
                + "."
            )

    return "\n\n".join(paragraphs)

