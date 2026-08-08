"""Knowledge-backed SSP composition helpers."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Project, SystemProfile
from app.services.system_knowledge import get_latest_system_knowledge


def _status_rank(status: str | None) -> int:
    order = {
        "confirmed": 0,
        "proposed": 1,
        "missing_evidence": 2,
        "rejected": 3,
    }
    return order.get((status or "").lower(), 9)


def _group_assertions(assertions: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for assertion in assertions:
        key = f"{assertion.get('category')}::{assertion.get('key')}"
        grouped[key].append(assertion)
    for items in grouped.values():
        items.sort(key=lambda item: (_status_rank(item.get("status")), -(item.get("confidence") or 0)))
    return grouped


def _pick_assertions(assertions: list[dict], *, category: str, key: str) -> list[dict]:
    grouped = _group_assertions(assertions)
    return grouped.get(f"{category}::{key}", [])


def _best_value(assertions: list[dict], *, category: str, key: str, fallback: str | None = None) -> str | None:
    matches = _pick_assertions(assertions, category=category, key=key)
    if not matches:
        return fallback
    value = matches[0].get("value")
    if isinstance(value, dict):
        first = next(iter(value.values()), None)
        return str(first) if first else fallback
    if value is None:
        return fallback
    return str(value)


def _build_section(section_id: str, title: str, body_lines: list[str], sources: list[dict]) -> dict:
    return {
        "section_id": section_id,
        "title": title,
        "content": "\n\n".join(line for line in body_lines if line and line.strip()),
        "source_count": len(sources),
        "sources": sources,
    }


async def compose_ssp_sections(
    db: AsyncSession,
    *,
    project_id: int,
    section_key: str | None = None,
) -> dict:
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalars().first()
    if not project:
        raise ValueError("Project not found")

    system_profile = (
        await db.execute(select(SystemProfile).where(SystemProfile.project_id == project_id))
    ).scalars().first()
    knowledge = await get_latest_system_knowledge(project_id, db)
    assertions = knowledge.get("assertions", [])
    tools = knowledge.get("tools", [])

    hosting_platform = _best_value(assertions, category="hosting", key="hosting_platform", fallback="platform not yet confirmed")
    boundary_component = _best_value(assertions, category="boundary", key="boundary_component", fallback="boundary protection not yet confirmed")
    remote_access_component = _best_value(assertions, category="remote_access", key="remote_access_component", fallback="remote access method not yet confirmed")
    logging_component = _best_value(assertions, category="logging", key="logging_component", fallback="central logging component not yet confirmed")
    endpoint_component = _best_value(assertions, category="endpoint", key="endpoint_component", fallback="endpoint management component not yet confirmed")

    tool_lines = [
        f"{tool['tool_name']} ({tool.get('tool_category') or 'tool'}; status: {tool.get('status') or 'proposed'})"
        for tool in tools
    ]
    deployment_model = getattr(system_profile, "deployment_model", None) or "not yet confirmed"
    infrastructure_ownership = getattr(system_profile, "infrastructure_ownership", None) or "not yet confirmed"
    user_population = getattr(system_profile, "user_population", None) or "not yet confirmed"

    section_map = {
        "system_overview": _build_section(
            "system_overview",
            "System Overview",
            [
                f"{project.name} is a {project.system_type or 'federal information system'} assessed against the {project.impact_baseline.upper()} baseline.",
                f"The current system profile indicates a deployment model of {deployment_model} with infrastructure ownership recorded as {infrastructure_ownership}.",
                "This SSP draft is grounded in project metadata plus the reviewed architecture and tool assertions extracted from the current evidence base.",
            ],
            [
                {
                    "type": "project",
                    "label": project.name,
                    "details": {
                        "system_type": project.system_type,
                        "impact_baseline": project.impact_baseline,
                        "description": project.description,
                    },
                },
                {
                    "type": "system_profile",
                    "label": "System profile",
                    "details": {
                        "deployment_model": deployment_model,
                        "infrastructure_ownership": infrastructure_ownership,
                        "user_population": user_population,
                    },
                },
            ],
        ),
        "architecture_and_hosting": _build_section(
            "architecture_and_hosting",
            "Architecture and Hosting",
            [
                f"The currently derived hosting platform is {hosting_platform}.",
                f"Boundary protection evidence currently points to {boundary_component}, while the remote access path appears to rely on {remote_access_component}.",
                f"Central logging is associated with {logging_component}, and endpoint management or protection evidence currently points to {endpoint_component}.",
                "The assessor should confirm these statements against the Architecture & Tools review page before treating them as authoritative SSP narrative.",
            ],
            [
                *[
                    {
                        "type": "assertion",
                        "label": f"{item.get('category')} / {item.get('key')}",
                        "status": item.get("status"),
                        "confidence": item.get("confidence"),
                        "details": item.get("value"),
                    }
                    for item in assertions
                    if item.get("key") in {"hosting_platform", "boundary_component", "remote_access_component", "logging_component", "endpoint_component"}
                ]
            ],
        ),
        "security_tooling": _build_section(
            "security_tooling",
            "Security Tooling and Defense in Depth",
            (
                ["The current evidence base suggests the following security tooling stack:"]
                + ([f"- {line}" for line in tool_lines] if tool_lines else ["- No tools have been confidently confirmed yet."])
                + ["These tool assertions should be reviewed and either confirmed or rejected so the SSP reflects the actual enforcement, monitoring, and response architecture."]
            ),
            [
                {
                    "type": "tool_inventory",
                    "label": tool.get("tool_name"),
                    "status": tool.get("status"),
                    "confidence": tool.get("confidence"),
                    "details": {
                        "tool_category": tool.get("tool_category"),
                        "vendor": tool.get("vendor"),
                    },
                }
                for tool in tools
            ],
        ),
        "roles_and_responsibilities": _build_section(
            "roles_and_responsibilities",
            "Roles and Responsibilities",
            [
                f"The project currently records the system as {project.name}, and the SSP should identify accountable roles for system ownership, security oversight, operations, and monitoring.",
                "At minimum, the SSP should confirm named responsibility for the system owner, ISSO, privileged administrators, logging/monitoring owners, and incident response coordination.",
                "If these roles are not yet explicit in the architecture knowledge base, the assessor should confirm them before finalizing SSP narrative.",
            ],
            [
                {
                    "type": "project",
                    "label": "Project metadata",
                    "details": {
                        "project_name": project.name,
                        "description": project.description,
                    },
                }
            ],
        ),
        "evidence_gaps_and_review_notes": _build_section(
            "evidence_gaps_and_review_notes",
            "Evidence Gaps and Review Notes",
            [
                "The current SSP draft is only as reliable as the reviewed system knowledge feeding it.",
                "Any assertion still marked proposed should be confirmed before this text is treated as final implementation narrative.",
                "Any assertion marked missing_evidence should trigger document search or artifact collection before the SSP is finalized.",
            ],
            [
                {
                    "type": "assertion_status",
                    "label": f"{item.get('category')} / {item.get('key')}",
                    "status": item.get("status"),
                    "confidence": item.get("confidence"),
                    "details": item.get("value"),
                }
                for item in assertions
                if item.get("status") in {"proposed", "missing_evidence"}
            ],
        ),
    }

    if section_key:
        if section_key not in section_map:
            raise ValueError("Unknown SSP section")
        sections = [section_map[section_key]]
    else:
        sections = list(section_map.values())

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "system_type": project.system_type,
            "impact_baseline": project.impact_baseline,
        },
        "knowledge_run": knowledge.get("run"),
        "section_count": len(sections),
        "sections": sections,
    }
