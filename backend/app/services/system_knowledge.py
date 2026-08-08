"""Project-level system knowledge extraction from ingested evidence."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    CommonControlProvider,
    ProjectCommonProvider,
    ProjectProviderResponsibility,
    SystemKnowledgeAssertion,
    SystemKnowledgeRun,
    ToolInventory,
)
from app.services.evidence_view import get_all_evidence_text

TOOL_PATTERNS: dict[str, dict[str, Any]] = {
    "CrowdStrike Falcon": {
        "category": "endpoint",
        "vendor": "CrowdStrike",
        "patterns": ["crowdstrike", "falcon sensor", "falcon console", "crowdstrike falcon"],
    },
    "Splunk": {
        "category": "logging",
        "vendor": "Splunk",
        "patterns": ["splunk", "splunk cloud", "splunk enterprise", "splunk siem"],
    },
    "Tenable": {
        "category": "vulnerability_management",
        "vendor": "Tenable",
        "patterns": ["tenable", "tenable.io", "nessus"],
    },
    "Qualys": {
        "category": "vulnerability_management",
        "vendor": "Qualys",
        "patterns": ["qualys"],
    },
    "AWS Config": {
        "category": "configuration_monitoring",
        "vendor": "AWS",
        "patterns": ["aws config", "config rule", "config rules"],
    },
    "AWS CloudTrail": {
        "category": "logging",
        "vendor": "AWS",
        "patterns": ["cloudtrail", "aws cloudtrail"],
    },
    "Okta": {
        "category": "identity",
        "vendor": "Okta",
        "patterns": ["okta"],
    },
    "Microsoft Entra ID": {
        "category": "identity",
        "vendor": "Microsoft",
        "patterns": ["entra id", "azure ad", "microsoft entra"],
    },
    "ServiceNow": {
        "category": "workflow",
        "vendor": "ServiceNow",
        "patterns": ["servicenow"],
    },
    "Jamf": {
        "category": "device_management",
        "vendor": "Jamf",
        "patterns": ["jamf"],
    },
    "Microsoft Intune": {
        "category": "device_management",
        "vendor": "Microsoft",
        "patterns": ["intune", "microsoft intune"],
    },
}

ARCH_PATTERNS: dict[str, dict[str, Any]] = {
    "aws_govcloud": {
        "category": "hosting",
        "value": {"platform": "AWS GovCloud"},
        "patterns": ["aws govcloud", "govcloud"],
        "key": "hosting_platform",
    },
    "azure_government": {
        "category": "hosting",
        "value": {"platform": "Azure Government"},
        "patterns": ["azure government"],
        "key": "hosting_platform",
    },
    "waf": {
        "category": "boundary",
        "value": {"component": "Web Application Firewall"},
        "patterns": ["waf", "web application firewall"],
        "key": "boundary_component",
    },
    "vpn": {
        "category": "remote_access",
        "value": {"component": "VPN"},
        "patterns": ["vpn", "virtual private network"],
        "key": "remote_access_component",
    },
    "bastion": {
        "category": "remote_access",
        "value": {"component": "Bastion Host"},
        "patterns": ["bastion", "jump host"],
        "key": "remote_access_component",
    },
    "siem": {
        "category": "logging",
        "value": {"component": "SIEM"},
        "patterns": ["siem", "security information and event management"],
        "key": "logging_component",
    },
    "mdm": {
        "category": "endpoint",
        "value": {"component": "MDM"},
        "patterns": ["mdm", "mobile device management"],
        "key": "endpoint_component",
    },
}

PROVIDER_INHERITANCE_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "aws": {
        "PE": {
            "inheritance_type": "inherited",
            "provider_coverage_status": "supported",
            "system_responsibility": "Review AWS inherited controls and document only system-specific physical or media exceptions.",
            "rationale": "AWS commonly covers physical and environmental protections as a cloud common control provider.",
        },
        "SC": {
            "inheritance_type": "shared",
            "provider_coverage_status": "partial",
            "system_responsibility": "Document application, network, and encryption controls implemented above the AWS service boundary.",
            "rationale": "AWS provides platform and infrastructure protections, but system teams still own many communications protections.",
        },
        "CP": {
            "inheritance_type": "shared",
            "provider_coverage_status": "partial",
            "system_responsibility": "Show application recovery, backup validation, and tenant-specific continuity procedures.",
            "rationale": "AWS contributes resiliency capabilities, but system recovery procedures remain partly local.",
        },
        "CM": {
            "inheritance_type": "shared",
            "provider_coverage_status": "partial",
            "system_responsibility": "Provide tenant baseline, IaC, and workload configuration evidence.",
            "rationale": "AWS manages underlying platform configuration while tenant workloads remain system-specific.",
        },
        "AU": {
            "inheritance_type": "shared",
            "provider_coverage_status": "partial",
            "system_responsibility": "Show log collection, review, and alert handling for system-managed sources and applications.",
            "rationale": "AWS emits service logs, but the system must prove monitoring and review of its own audit events.",
        },
    },
    "azure": {
        "PE": {
            "inheritance_type": "inherited",
            "provider_coverage_status": "supported",
            "system_responsibility": "Document only system-managed physical exceptions and local handling processes.",
            "rationale": "Azure Government commonly covers datacenter physical protections as a shared provider.",
        },
        "SC": {
            "inheritance_type": "shared",
            "provider_coverage_status": "partial",
            "system_responsibility": "Show tenant network protections, segmentation, and encryption settings.",
            "rationale": "Azure provides platform protections while tenant network and application controls remain partly local.",
        },
    },
    "default_shared": {
        "AU": {
            "inheritance_type": "shared",
            "provider_coverage_status": "partial",
            "system_responsibility": "Confirm the system forwards relevant logs and show who reviews the resulting alerts.",
            "rationale": "Shared services often provide centralized logging but not complete system-specific monitoring responsibility.",
        },
    },
}


def _provider_template_key(provider: CommonControlProvider) -> str:
    haystack = " ".join(
        [
            provider.name or "",
            provider.description or "",
            provider.org_level or "",
            " ".join(provider.control_families or []),
        ]
    ).lower()
    if "aws" in haystack or "amazon web services" in haystack:
        return "aws"
    if "azure" in haystack:
        return "azure"
    return "default_shared"


def _build_snippets(text: str, pattern: str, *, limit: int = 2) -> list[str]:
    snippets: list[str] = []
    lower = text.lower()
    idx = 0
    while len(snippets) < limit:
        hit = lower.find(pattern, idx)
        if hit == -1:
            break
        start = max(0, hit - 90)
        end = min(len(text), hit + len(pattern) + 160)
        snippets.append(text[start:end].strip().replace("\n", " "))
        idx = hit + len(pattern)
    return snippets


async def extract_system_knowledge(
    db: AsyncSession,
    *,
    project_id: int,
    source_mode: str,
    source_run_id: int,
    document_ids: list[int] | None = None,
) -> dict:
    """Extract a lightweight, reviewable system knowledge summary."""
    run = SystemKnowledgeRun(
        project_id=project_id,
        source_mode=source_mode,
        source_run_id=source_run_id,
        status="running",
    )
    db.add(run)
    await db.flush()

    texts = await get_all_evidence_text(
        project_id,
        db,
        max_tokens=24000,
        scope_doc_ids=document_ids,
    )
    corpus = "\n\n".join(texts)
    corpus_lower = corpus.lower()

    assertions_payload: list[dict[str, Any]] = []
    detected_tools: list[dict[str, Any]] = []
    category_counts: dict[str, int] = defaultdict(int)

    for tool_name, spec in TOOL_PATTERNS.items():
        patterns = spec["patterns"]
        matched_pattern = next((p for p in patterns if p in corpus_lower), None)
        if not matched_pattern:
            continue
        snippets = _build_snippets(corpus, matched_pattern)
        payload = {
            "category": "tool",
            "key": spec["category"],
            "value_json": {
                "tool_name": tool_name,
                "tool_category": spec["category"],
                "vendor": spec["vendor"],
            },
            "normalized_value": tool_name.lower(),
            "confidence": 0.9 if len(snippets) > 1 else 0.76,
            "status": "proposed",
            "rationale": f"Detected {tool_name} from project evidence.",
            "provenance_json": {"snippets": snippets, "matched_pattern": matched_pattern},
        }
        assertions_payload.append(payload)
        detected_tools.append(payload["value_json"])
        category_counts["tool"] += 1

    for assertion_name, spec in ARCH_PATTERNS.items():
        patterns = spec["patterns"]
        matched_pattern = next((p for p in patterns if p in corpus_lower), None)
        if not matched_pattern:
            continue
        snippets = _build_snippets(corpus, matched_pattern)
        payload = {
            "category": spec["category"],
            "key": spec["key"],
            "value_json": spec["value"],
            "normalized_value": str(next(iter(spec["value"].values()), assertion_name)).lower(),
            "confidence": 0.84 if len(snippets) > 1 else 0.68,
            "status": "proposed",
            "rationale": f"Derived {spec['category']} assertion from project evidence.",
            "provenance_json": {"snippets": snippets, "matched_pattern": matched_pattern},
        }
        assertions_payload.append(payload)
        category_counts[spec["category"]] += 1

    if not assertions_payload:
        assertions_payload.append(
            {
                "category": "knowledge_gap",
                "key": "architecture_review_needed",
                "value_json": {"message": "No tool or architecture assertions were confidently extracted."},
                "normalized_value": "architecture_review_needed",
                "confidence": 0.2,
                "status": "missing_evidence",
                "rationale": "Project evidence did not yield strong architecture/tool matches.",
                "provenance_json": {"snippets": []},
            }
        )
        category_counts["knowledge_gap"] += 1

    for item in assertions_payload:
        db.add(
            SystemKnowledgeAssertion(
                run_id=run.id,
                project_id=project_id,
                category=item["category"],
                key=item["key"],
                value_json=item["value_json"],
                normalized_value=item["normalized_value"],
                confidence=item["confidence"],
                status=item["status"],
                rationale=item["rationale"],
                provenance_json=item["provenance_json"],
            )
        )

    for tool in detected_tools:
        stmt = insert(ToolInventory).values(
            project_id=project_id,
            tool_name=tool["tool_name"],
            tool_category=tool["tool_category"],
            vendor=tool["vendor"],
            deployment_scope="project",
            status="proposed",
            confidence=0.8,
            provenance_json={"source_mode": source_mode, "source_run_id": source_run_id},
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["project_id", "tool_name"],
            set_={
                "tool_category": stmt.excluded.tool_category,
                "vendor": stmt.excluded.vendor,
                "deployment_scope": stmt.excluded.deployment_scope,
                "confidence": stmt.excluded.confidence,
                "provenance_json": stmt.excluded.provenance_json,
                "updated_at": datetime.now(UTC),
            },
        )
        await db.execute(stmt)

    run.status = "complete"
    run.completed_at = datetime.now(UTC)
    run.summary_json = {
        "assertion_count": len(assertions_payload),
        "tool_count": len(detected_tools),
        "category_counts": dict(category_counts),
        "status": "complete",
    }
    await db.commit()

    return {
        "knowledge_run_id": run.id,
        **(run.summary_json or {}),
        "tools": detected_tools[:20],
    }


async def get_latest_system_knowledge(project_id: int, db: AsyncSession) -> dict:
    runs = (
        await db.execute(
            select(SystemKnowledgeRun)
            .where(SystemKnowledgeRun.project_id == project_id)
            .order_by(SystemKnowledgeRun.id.desc())
        )
    ).scalars().all()
    if not runs:
        return {"run": None, "assertions": [], "tools": []}

    latest_by_mode: dict[str, SystemKnowledgeRun] = {}
    for item in runs:
        if item.source_mode not in latest_by_mode:
            latest_by_mode[item.source_mode] = item
    selected_runs = list(latest_by_mode.values())
    selected_run_ids = [item.id for item in selected_runs]
    run = selected_runs[0]

    assertions = (
        await db.execute(
            select(SystemKnowledgeAssertion)
            .where(
                SystemKnowledgeAssertion.project_id == project_id,
                SystemKnowledgeAssertion.run_id.in_(selected_run_ids),
            )
            .order_by(SystemKnowledgeAssertion.category, SystemKnowledgeAssertion.key, SystemKnowledgeAssertion.id)
        )
    ).scalars().all()
    tools = (
        await db.execute(
            select(ToolInventory)
            .where(ToolInventory.project_id == project_id)
            .order_by(ToolInventory.tool_category, ToolInventory.tool_name)
        )
    ).scalars().all()

    return {
        "run": {
            "id": run.id,
            "source_mode": run.source_mode,
            "source_run_id": run.source_run_id,
            "status": run.status,
            "summary": run.summary_json or {},
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        },
        "runs": [
            {
                "id": item.id,
                "source_mode": item.source_mode,
                "source_run_id": item.source_run_id,
                "status": item.status,
                "summary": item.summary_json or {},
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            }
            for item in selected_runs
        ],
        "assertions": [
            {
                "id": item.id,
                "category": item.category,
                "key": item.key,
                "value": item.value_json,
                "normalized_value": item.normalized_value,
                "confidence": item.confidence,
                "status": item.status,
                "rationale": item.rationale,
                "provenance": item.provenance_json or {},
            }
            for item in assertions
        ],
        "tools": [
            {
                "id": tool.id,
                "tool_name": tool.tool_name,
                "tool_category": tool.tool_category,
                "vendor": tool.vendor,
                "deployment_scope": tool.deployment_scope,
                "status": tool.status,
                "confidence": tool.confidence,
                "provenance": tool.provenance_json or {},
            }
            for tool in tools
        ],
    }


async def review_system_assertion(
    db: AsyncSession,
    *,
    project_id: int,
    assertion_id: int,
    status: str,
    reviewer_id: int,
) -> dict | None:
    assertion = await db.get(SystemKnowledgeAssertion, assertion_id)
    if not assertion or assertion.project_id != project_id:
        return None
    assertion.status = status
    assertion.reviewed_by = reviewer_id
    assertion.reviewed_at = datetime.now(UTC)
    await db.commit()
    return {"id": assertion.id, "status": assertion.status}


async def suggest_provider_responsibilities(
    db: AsyncSession,
    *,
    project_id: int,
    reviewer_id: int,
    provider_id: int | None = None,
) -> dict:
    query = (
        select(ProjectCommonProvider, CommonControlProvider)
        .join(CommonControlProvider, ProjectCommonProvider.provider_id == CommonControlProvider.id)
        .where(ProjectCommonProvider.project_id == project_id)
    )
    if provider_id is not None:
        query = query.where(ProjectCommonProvider.provider_id == provider_id)
    rows = (await db.execute(query)).all()

    created = 0
    updated = 0
    suggestions: list[dict[str, Any]] = []

    for _link, provider in rows:
        template_key = _provider_template_key(provider)
        template = PROVIDER_INHERITANCE_TEMPLATES.get(template_key, {})
        families = sorted({*(provider.control_families or []), *template.keys()})
        for family in families:
            base = template.get(family) or {
                "inheritance_type": "shared",
                "provider_coverage_status": "partial",
                "system_responsibility": "Confirm what this provider covers and document the remaining local responsibility.",
                "rationale": f"{provider.name} appears to contribute to {family}, but local coverage still requires review.",
            }

            stmt = insert(ProjectProviderResponsibility).values(
                project_id=project_id,
                provider_id=provider.id,
                scope_type="family",
                scope_id=family.upper(),
                inheritance_type=base["inheritance_type"],
                provider_coverage_status=base["provider_coverage_status"],
                system_responsibility=base["system_responsibility"],
                rationale=base["rationale"],
                provenance_json={
                    "provider_name": provider.name,
                    "template": template_key,
                    "source": "provider_template",
                },
                status="proposed",
                reviewed_by=reviewer_id,
                reviewed_at=datetime.now(UTC),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["project_id", "provider_id", "scope_type", "scope_id"],
                set_={
                    "inheritance_type": stmt.excluded.inheritance_type,
                    "provider_coverage_status": stmt.excluded.provider_coverage_status,
                    "system_responsibility": stmt.excluded.system_responsibility,
                    "rationale": stmt.excluded.rationale,
                    "provenance_json": stmt.excluded.provenance_json,
                    "status": "proposed",
                    "reviewed_by": reviewer_id,
                    "reviewed_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                },
            )
            result = await db.execute(stmt.returning(ProjectProviderResponsibility.id))
            responsibility_id = result.scalar_one()
            existing = await db.get(ProjectProviderResponsibility, responsibility_id)
            if existing and existing.created_at and existing.updated_at and existing.created_at == existing.updated_at:
                created += 1
            else:
                updated += 1
            suggestions.append(
                {
                    "id": responsibility_id,
                    "provider_id": provider.id,
                    "provider_name": provider.name,
                    "scope_type": "family",
                    "scope_id": family.upper(),
                    "inheritance_type": base["inheritance_type"],
                    "provider_coverage_status": base["provider_coverage_status"],
                }
            )

    await db.commit()
    return {
        "provider_count": len(rows),
        "created_or_updated": len(suggestions),
        "created_estimate": created,
        "updated_estimate": updated,
        "suggestions": suggestions,
    }


async def get_project_provider_responsibilities(project_id: int, db: AsyncSession) -> dict:
    provider_rows = (
        await db.execute(
            select(ProjectCommonProvider, CommonControlProvider)
            .join(CommonControlProvider, ProjectCommonProvider.provider_id == CommonControlProvider.id)
            .where(ProjectCommonProvider.project_id == project_id)
            .order_by(CommonControlProvider.name)
        )
    ).all()

    responsibilities = (
        await db.execute(
            select(ProjectProviderResponsibility, CommonControlProvider)
            .join(CommonControlProvider, ProjectProviderResponsibility.provider_id == CommonControlProvider.id)
            .where(ProjectProviderResponsibility.project_id == project_id)
            .order_by(
                CommonControlProvider.name,
                ProjectProviderResponsibility.scope_type,
                ProjectProviderResponsibility.scope_id,
            )
        )
    ).all()

    provider_summary = []
    for link, provider in provider_rows:
        provider_summary.append(
            {
                "id": provider.id,
                "name": provider.name,
                "description": provider.description,
                "org_level": provider.org_level,
                "control_families": provider.control_families or [],
                "linked_at": link.linked_at.isoformat() if link.linked_at else None,
            }
        )

    responsibility_items = []
    inheritance_counts: dict[str, int] = defaultdict(int)
    for mapping, provider in responsibilities:
        inheritance_counts[mapping.inheritance_type] += 1
        responsibility_items.append(
            {
                "id": mapping.id,
                "provider_id": provider.id,
                "provider_name": provider.name,
                "scope_type": mapping.scope_type,
                "scope_id": mapping.scope_id,
                "inheritance_type": mapping.inheritance_type,
                "provider_coverage_status": mapping.provider_coverage_status,
                "system_responsibility": mapping.system_responsibility,
                "rationale": mapping.rationale,
                "status": mapping.status,
                "provenance": mapping.provenance_json or {},
            }
        )

    return {
        "providers": provider_summary,
        "responsibilities": responsibility_items,
        "summary": {
            "provider_count": len(provider_summary),
            "mapping_count": len(responsibility_items),
            "inheritance_counts": dict(inheritance_counts),
        },
    }


async def review_provider_responsibility(
    db: AsyncSession,
    *,
    project_id: int,
    responsibility_id: int,
    status: str,
    reviewer_id: int,
) -> dict | None:
    responsibility = await db.get(ProjectProviderResponsibility, responsibility_id)
    if not responsibility or responsibility.project_id != project_id:
        return None
    responsibility.status = status
    responsibility.reviewed_by = reviewer_id
    responsibility.reviewed_at = datetime.now(UTC)
    await db.commit()
    return {"id": responsibility.id, "status": responsibility.status}
