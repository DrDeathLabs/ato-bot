"""Connector framework scaffolding for live telemetry and cATO readiness."""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    Assessment,
    AuditLog,
    ControlTelemetryPosture,
    Document,
    DriftRecord,
    IngestionConfigAudit,
    IngestionRun,
    IntegrationAccount,
    IntegrationRun,
    POAM,
    SecurityEvent,
    SystemKnowledgeAssertion,
    SystemKnowledgeRun,
    TelemetrySnapshot,
    User,
)

CONNECTOR_CATALOG: dict[str, dict[str, Any]] = {
    "ato_bot": {
        "label": "ATO Bot",
        "category": "application",
        "auth_modes": ["internal"],
        "description": "Internal self-monitoring for the ATO Bot application, including identity, audit, job health, and drift telemetry.",
        "evidence_types": ["service_health", "identity", "audit", "job_health", "security_events", "configuration_drift"],
    },
    "aws": {
        "label": "AWS",
        "category": "cloud",
        "auth_modes": ["dry_run", "assume_role", "access_key"],
        "description": "Cloud configuration, security findings, audit events, and inherited provider telemetry.",
        "evidence_types": ["configuration", "audit", "security_findings", "asset_inventory"],
    },
    "azure": {
        "label": "Azure",
        "category": "cloud",
        "auth_modes": ["dry_run", "service_principal"],
        "description": "Azure Policy, activity logs, Defender signals, and tenant configuration posture.",
        "evidence_types": ["configuration", "audit", "security_findings", "asset_inventory"],
    },
    "entra_id": {
        "label": "Microsoft Entra ID",
        "category": "identity",
        "auth_modes": ["dry_run", "oauth_client_credentials"],
        "description": "Directory, MFA, conditional access, and privileged identity posture.",
        "evidence_types": ["identity", "mfa", "privileged_access", "audit"],
    },
    "okta": {
        "label": "Okta",
        "category": "identity",
        "auth_modes": ["dry_run", "api_token"],
        "description": "Directory, MFA, policy, and authentication event evidence.",
        "evidence_types": ["identity", "mfa", "policy", "audit"],
    },
    "crowdstrike": {
        "label": "CrowdStrike Falcon",
        "category": "endpoint",
        "auth_modes": ["dry_run", "api_client"],
        "description": "Endpoint protection posture, policy coverage, detections, and deployment scope.",
        "evidence_types": ["endpoint_protection", "detections", "policy_assignment", "asset_inventory"],
    },
    "defender": {
        "label": "Microsoft Defender",
        "category": "endpoint",
        "auth_modes": ["dry_run", "oauth_client_credentials"],
        "description": "Endpoint detections, antivirus posture, exposure insights, and deployment coverage.",
        "evidence_types": ["endpoint_protection", "detections", "vulnerability", "asset_inventory"],
    },
    "splunk": {
        "label": "Splunk",
        "category": "logging",
        "auth_modes": ["dry_run", "api_token"],
        "description": "Search heads, saved searches, alerting, and source onboarding posture.",
        "evidence_types": ["logging", "alerts", "audit", "coverage"],
    },
    "sentinel": {
        "label": "Microsoft Sentinel",
        "category": "logging",
        "auth_modes": ["dry_run", "oauth_client_credentials"],
        "description": "Security analytics rules, incidents, and data connector coverage.",
        "evidence_types": ["logging", "alerts", "incidents", "coverage"],
    },
}

CONNECTOR_CONTROL_MAP: dict[str, list[dict[str, str]]] = {
    "ato_bot": [
        {"control_id": "AC-2", "support_status": "partial", "focus": "local account lifecycle and user administration"},
        {"control_id": "IA-2", "support_status": "partial", "focus": "MFA coverage for privileged users"},
        {"control_id": "AU-2", "support_status": "partial", "focus": "selection and generation of application audit events"},
        {"control_id": "AU-6", "support_status": "partial", "focus": "audit review and security-event backlog"},
        {"control_id": "AU-12", "support_status": "partial", "focus": "audit generation for application activity"},
        {"control_id": "CA-7", "support_status": "partial", "focus": "continuous monitoring of application security and operations"},
        {"control_id": "CM-3", "support_status": "partial", "focus": "tracked configuration changes"},
        {"control_id": "SI-4", "support_status": "partial", "focus": "application monitoring and pipeline failure visibility"},
    ],
    "aws": [
        {"control_id": "CM-2", "support_status": "planned", "focus": "baseline configuration telemetry"},
        {"control_id": "CM-6", "support_status": "planned", "focus": "cloud configuration enforcement"},
        {"control_id": "AU-12", "support_status": "planned", "focus": "audit event generation and service logging"},
        {"control_id": "SC-7", "support_status": "planned", "focus": "boundary and network protection telemetry"},
    ],
    "azure": [
        {"control_id": "CM-2", "support_status": "planned", "focus": "tenant baseline and policy telemetry"},
        {"control_id": "CM-6", "support_status": "planned", "focus": "configuration policy enforcement"},
        {"control_id": "AU-12", "support_status": "planned", "focus": "activity logging and audit coverage"},
        {"control_id": "SC-7", "support_status": "planned", "focus": "network and boundary monitoring"},
    ],
    "entra_id": [
        {"control_id": "IA-2", "support_status": "planned", "focus": "MFA and authentication policy evidence"},
        {"control_id": "AC-2", "support_status": "planned", "focus": "account lifecycle and directory telemetry"},
        {"control_id": "AC-3", "support_status": "planned", "focus": "access enforcement and conditional access"},
        {"control_id": "AU-2", "support_status": "planned", "focus": "authentication audit telemetry"},
    ],
    "okta": [
        {"control_id": "IA-2", "support_status": "planned", "focus": "MFA and authenticator policy evidence"},
        {"control_id": "AC-2", "support_status": "planned", "focus": "account lifecycle telemetry"},
        {"control_id": "AC-3", "support_status": "planned", "focus": "policy enforcement and group controls"},
        {"control_id": "AU-2", "support_status": "planned", "focus": "authentication audit events"},
    ],
    "crowdstrike": [
        {"control_id": "SI-3(1)", "support_status": "planned", "focus": "centrally managed anti-malware evidence"},
        {"control_id": "SI-3(2)", "support_status": "planned", "focus": "automatic update and signature posture"},
        {"control_id": "CM-8", "support_status": "planned", "focus": "endpoint inventory coverage"},
        {"control_id": "SI-4", "support_status": "planned", "focus": "detection and monitoring telemetry"},
    ],
    "defender": [
        {"control_id": "SI-3(1)", "support_status": "planned", "focus": "centrally managed anti-malware evidence"},
        {"control_id": "SI-3(2)", "support_status": "planned", "focus": "automatic update and signature posture"},
        {"control_id": "CM-8", "support_status": "planned", "focus": "endpoint inventory coverage"},
        {"control_id": "SI-4", "support_status": "planned", "focus": "detection and monitoring telemetry"},
    ],
    "splunk": [
        {"control_id": "AU-6", "support_status": "planned", "focus": "audit review and alert handling"},
        {"control_id": "AU-12", "support_status": "planned", "focus": "centralized logging coverage"},
        {"control_id": "SI-4", "support_status": "planned", "focus": "monitoring and detection rules"},
        {"control_id": "SI-8(1)", "support_status": "planned", "focus": "centralized alert management"},
    ],
    "sentinel": [
        {"control_id": "AU-6", "support_status": "planned", "focus": "audit review and analytic rules"},
        {"control_id": "AU-12", "support_status": "planned", "focus": "centralized logging coverage"},
        {"control_id": "SI-4", "support_status": "planned", "focus": "monitoring and incident detections"},
        {"control_id": "SI-8(1)", "support_status": "planned", "focus": "centralized alert management"},
    ],
}


def _probe_http_service(name: str, url: str, *, timeout: float = 2.5) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with urlopen(url, timeout=timeout) as response:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            return {
                "name": name,
                "kind": "http",
                "target": url,
                "status": "healthy" if response.status < 400 else "degraded",
                "latency_ms": elapsed_ms,
                "detail": f"HTTP {response.status}",
            }
    except Exception as exc:  # noqa: BLE001 - best-effort runtime health probe
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "name": name,
            "kind": "http",
            "target": url,
            "status": "unreachable",
            "latency_ms": elapsed_ms,
            "detail": str(exc),
        }


def _probe_tcp_service(name: str, host: str, port: int, *, timeout: float = 2.5) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            return {
                "name": name,
                "kind": "tcp",
                "target": f"{host}:{port}",
                "status": "healthy",
                "latency_ms": elapsed_ms,
                "detail": "TCP reachable",
            }
    except OSError as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "name": name,
            "kind": "tcp",
            "target": f"{host}:{port}",
            "status": "unreachable",
            "latency_ms": elapsed_ms,
            "detail": str(exc),
        }


def _parse_host_port_from_url(url: str | None, *, default_host: str, default_port: int) -> tuple[str, int]:
    if not url:
        return default_host, default_port
    try:
        parsed = urlparse(url)
        return parsed.hostname or default_host, parsed.port or default_port
    except Exception:  # noqa: BLE001 - safe fallback for malformed URLs
        return default_host, default_port


def _collect_runtime_services() -> list[dict[str, Any]]:
    db_host, db_port = _parse_host_port_from_url(
        os.getenv("DATABASE_URL"),
        default_host="postgres",
        default_port=5432,
    )
    redis_host, redis_port = _parse_host_port_from_url(
        os.getenv("REDIS_URL"),
        default_host="redis",
        default_port=6379,
    )
    return [
        _probe_http_service("Backend API", "http://backend:8000/health"),
        _probe_http_service("Frontend UI", "http://frontend"),
        _probe_tcp_service("PostgreSQL", db_host, db_port),
        _probe_tcp_service("Redis", redis_host, redis_port),
    ]


def _collect_docker_runtime_snapshot() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError:
        return {
            "available": False,
            "detail": "docker CLI is not available from the current backend runtime.",
            "containers": [],
        }
    except Exception as exc:  # noqa: BLE001 - best-effort runtime inspection
        return {
            "available": False,
            "detail": f"Docker inspection failed: {exc}",
            "containers": [],
        }

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "docker ps failed").strip()
        return {
            "available": False,
            "detail": detail,
            "containers": [],
        }

    containers: list[dict[str, Any]] = []
    for raw_line in result.stdout.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        if len(parts) != 4:
            continue
        name, status, image, ports = parts
        if not name.startswith("atobot_"):
            continue
        containers.append(
            {
                "name": name,
                "status": status,
                "image": image,
                "ports": ports,
                "healthy": "Up" in status and "unhealthy" not in status.lower(),
            }
        )
    return {
        "available": True,
        "detail": "Runtime inspection collected from docker ps.",
        "containers": containers,
    }


async def _collect_runtime_snapshot() -> dict[str, Any]:
    services = await asyncio.to_thread(_collect_runtime_services)
    docker_runtime = await asyncio.to_thread(_collect_docker_runtime_snapshot)
    healthy_services = sum(1 for item in services if item["status"] == "healthy")
    return {
        "services": services,
        "service_summary": {
            "healthy": healthy_services,
            "degraded": sum(1 for item in services if item["status"] == "degraded"),
            "unreachable": sum(1 for item in services if item["status"] == "unreachable"),
            "total": len(services),
        },
        "docker_runtime": docker_runtime,
    }


def list_connector_catalog() -> list[dict[str, Any]]:
    return [
        {"key": key, **value}
        for key, value in sorted(CONNECTOR_CATALOG.items(), key=lambda item: item[1]["label"])
    ]


def _dry_run_summary(account: IntegrationAccount) -> dict[str, Any]:
    connector = CONNECTOR_CATALOG.get(account.connector_type, {})
    label = connector.get("label", account.connector_type)
    category = connector.get("category", "integration")
    evidence_types = connector.get("evidence_types", [])
    return {
        "mode": "dry_run",
        "connector_type": account.connector_type,
        "connector_label": label,
        "category": category,
        "records_seen": max(4, len(evidence_types) * 3),
        "preview_assertions": [
            f"{label} integration scaffolding is configured for this project.",
            f"Expected evidence types: {', '.join(evidence_types) if evidence_types else 'generic telemetry'}.",
            "This was a dry-run sync. No live tenant or account data was pulled.",
        ],
        "next_step": "Switch the connector from dry_run to a real auth mode and provide credentials when ready.",
    }


async def _atobot_summary(db: AsyncSession, account: IntegrationAccount) -> dict[str, Any]:
    now = datetime.now(UTC)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    total_users = int((await db.execute(select(func.count()).select_from(User))).scalar() or 0)
    active_users = int((await db.execute(select(func.count()).select_from(User).where(User.is_active.is_(True)))).scalar() or 0)
    admin_users = int((await db.execute(select(func.count()).select_from(User).where(User.role.in_(["admin", "assessor"])))).scalar() or 0)
    privileged_without_mfa = int((
        await db.execute(
            select(func.count()).select_from(User).where(
                User.role.in_(["admin", "assessor"]),
                User.is_active.is_(True),
                User.mfa_enabled.is_(False),
            )
        )
    ).scalar() or 0)
    audit_events_24h = int((await db.execute(select(func.count()).select_from(AuditLog).where(AuditLog.timestamp >= day_ago))).scalar() or 0)
    config_changes_7d = int((await db.execute(select(func.count()).select_from(IngestionConfigAudit).where(IngestionConfigAudit.changed_at >= week_ago))).scalar() or 0)
    unresolved_security_events = int((await db.execute(select(func.count()).select_from(SecurityEvent).where(SecurityEvent.resolved.is_(False)))).scalar() or 0)
    unresolved_critical_events = int((
        await db.execute(
            select(func.count()).select_from(SecurityEvent).where(
                SecurityEvent.resolved.is_(False),
                SecurityEvent.severity.in_(["high", "critical"]),
            )
        )
    ).scalar() or 0)
    failed_ingestion_24h = int((
        await db.execute(
            select(func.count()).select_from(IngestionRun).where(
                IngestionRun.started_at >= day_ago,
                IngestionRun.status == "failed",
            )
        )
    ).scalar() or 0)
    failed_assessments_7d = int((
        await db.execute(
            select(func.count()).select_from(Assessment).where(
                Assessment.started_at >= week_ago,
                Assessment.status == "failed",
            )
        )
    ).scalar() or 0)
    documents_failed = int((
        await db.execute(
            select(func.count()).select_from(Document).where(
                Document.parse_status.in_(["failed", "index_failed"]),
            )
        )
    ).scalar() or 0)
    indexed_docs = int((await db.execute(select(func.count()).select_from(Document).where(Document.parse_status == "indexed"))).scalar() or 0)
    open_poam = int((
        await db.execute(
            select(func.count()).select_from(POAM).where(
                POAM.status.in_(["open", "in_progress"]),
            )
        )
    ).scalar() or 0)
    runtime_snapshot = await _collect_runtime_snapshot()
    runtime_services = runtime_snapshot["services"]
    runtime_summary = runtime_snapshot["service_summary"]
    docker_runtime = runtime_snapshot["docker_runtime"]

    identity_status = "supported" if admin_users > 0 and privileged_without_mfa == 0 else "partial"
    audit_status = "supported" if audit_events_24h > 0 else "partial"
    monitoring_status = "supported" if (
        failed_ingestion_24h == 0
        and failed_assessments_7d == 0
        and unresolved_critical_events == 0
        and runtime_summary["unreachable"] == 0
    ) else "partial"
    config_status = "supported" if config_changes_7d > 0 else "partial"
    continuous_monitoring_status = "supported" if audit_events_24h > 0 and monitoring_status == "supported" else "partial"
    service_status = "supported" if runtime_summary["unreachable"] == 0 else "partial"

    preview = [
        f"ATO Bot observed {active_users} active users and {admin_users} privileged accounts.",
        f"Privileged accounts without MFA: {privileged_without_mfa}. Audit events in the last 24h: {audit_events_24h}.",
        f"Ingestion failures (24h): {failed_ingestion_24h}; failed assessments (7d): {failed_assessments_7d}; unresolved critical security events: {unresolved_critical_events}.",
        f"Runtime services healthy: {runtime_summary['healthy']} of {runtime_summary['total']}; unreachable: {runtime_summary['unreachable']}.",
    ]

    assertions_payload = [
        {
            "category": "identity_posture",
            "key": "privileged_mfa_coverage",
            "value_json": {
                "admin_users": admin_users,
                "privileged_without_mfa": privileged_without_mfa,
                "mfa_coverage_pct": round(((admin_users - privileged_without_mfa) / admin_users) * 100, 1) if admin_users else 100.0,
            },
            "normalized_value": "ato_bot:privileged_mfa_coverage",
            "confidence": 0.95,
            "status": "proposed",
            "rationale": "Derived from active privileged user accounts and MFA settings.",
            "provenance_json": {"connector_type": "ato_bot", "metric_window": "current"},
        },
        {
            "category": "audit_posture",
            "key": "audit_activity_24h",
            "value_json": {"audit_events_24h": audit_events_24h, "indexed_documents": indexed_docs},
            "normalized_value": "ato_bot:audit_activity_24h",
            "confidence": 0.9,
            "status": "proposed",
            "rationale": "Derived from application audit logs and document indexing state.",
            "provenance_json": {"connector_type": "ato_bot", "metric_window": "24h"},
        },
        {
            "category": "configuration_posture",
            "key": "config_change_tracking",
            "value_json": {
                "config_changes_7d": config_changes_7d,
                "documents_failed": documents_failed,
            },
            "normalized_value": "ato_bot:config_change_tracking",
            "confidence": 0.84,
            "status": "proposed",
            "rationale": "Derived from ingestion configuration audit history and failed document tracking.",
            "provenance_json": {"connector_type": "ato_bot", "metric_window": "7d"},
        },
        {
            "category": "security_posture",
            "key": "security_event_backlog",
            "value_json": {
                "unresolved_security_events": unresolved_security_events,
                "unresolved_critical_events": unresolved_critical_events,
                "open_poam": open_poam,
            },
            "normalized_value": "ato_bot:security_event_backlog",
            "confidence": 0.87,
            "status": "proposed",
            "rationale": "Derived from unresolved security events and active remediation backlog.",
            "provenance_json": {"connector_type": "ato_bot", "metric_window": "current"},
        },
        {
            "category": "operations_posture",
            "key": "job_health",
            "value_json": {
                "failed_ingestion_24h": failed_ingestion_24h,
                "failed_assessments_7d": failed_assessments_7d,
                "documents_failed": documents_failed,
                "open_poam": open_poam,
            },
            "normalized_value": "ato_bot:job_health",
            "confidence": 0.88,
            "status": "proposed",
            "rationale": "Derived from ingestion, assessment, and POA&M records.",
            "provenance_json": {"connector_type": "ato_bot", "metric_window": "24h_7d"},
        },
        {
            "category": "continuous_monitoring",
            "key": "control_monitoring_health",
            "value_json": {
                "audit_events_24h": audit_events_24h,
                "failed_ingestion_24h": failed_ingestion_24h,
                "failed_assessments_7d": failed_assessments_7d,
                "unresolved_critical_events": unresolved_critical_events,
            },
            "normalized_value": "ato_bot:control_monitoring_health",
            "confidence": 0.9,
            "status": "proposed",
            "rationale": "Derived from application telemetry freshness, pipeline reliability, and unresolved critical events.",
            "provenance_json": {"connector_type": "ato_bot", "metric_window": "24h_7d"},
        },
        {
            "category": "runtime_posture",
            "key": "service_runtime_health",
            "value_json": {
                "services": runtime_services,
                "service_summary": runtime_summary,
                "docker_runtime": docker_runtime,
            },
            "normalized_value": "ato_bot:service_runtime_health",
            "confidence": 0.85 if runtime_summary["unreachable"] == 0 else 0.66,
            "status": "proposed",
            "rationale": "Derived from live reachability checks across the ATO Bot service stack and best-effort Docker runtime inspection.",
            "provenance_json": {"connector_type": "ato_bot", "metric_window": "current"},
        },
    ]

    control_postures_payload = [
        {
            "control_id": "IA-2",
            "support_status": identity_status,
            "freshness_status": "fresh",
            "confidence": 0.9,
            "evidence_json": {
                "connector_type": "ato_bot",
                "connector_label": "ATO Bot",
                "focus": "Privileged MFA coverage",
                "admin_users": admin_users,
                "privileged_without_mfa": privileged_without_mfa,
                "summary": f"{admin_users - privileged_without_mfa} of {admin_users} privileged users currently have MFA enabled.",
                "recommended_action": "Enable MFA for every admin and assessor account before relying on this app as a live evidence source.",
            },
        },
        {
            "control_id": "AC-2",
            "support_status": "supported" if active_users > 0 else "partial",
            "freshness_status": "fresh",
            "confidence": 0.78,
            "evidence_json": {
                "connector_type": "ato_bot",
                "connector_label": "ATO Bot",
                "focus": "Local user and role administration",
                "active_users": active_users,
                "total_users": total_users,
                "summary": f"{active_users} active application users are currently tracked out of {total_users} total accounts.",
            },
        },
        {
            "control_id": "AU-2",
            "support_status": audit_status,
            "freshness_status": "fresh",
            "confidence": 0.82,
            "evidence_json": {
                "connector_type": "ato_bot",
                "connector_label": "ATO Bot",
                "focus": "Audit event selection and generation",
                "audit_events_24h": audit_events_24h,
                "summary": f"{audit_events_24h} application audit events were recorded in the last 24 hours.",
                "recommended_action": "Review audit coverage if this stays at zero during normal system use.",
            },
        },
        {
            "control_id": "AU-12",
            "support_status": audit_status,
            "freshness_status": "fresh",
            "confidence": 0.84,
            "evidence_json": {
                "connector_type": "ato_bot",
                "connector_label": "ATO Bot",
                "focus": "Audit generation",
                "audit_events_24h": audit_events_24h,
                "summary": f"Application telemetry shows {audit_events_24h} audit records generated in the last 24 hours.",
            },
        },
        {
            "control_id": "AU-6",
            "support_status": "supported" if unresolved_critical_events == 0 else "partial",
            "freshness_status": "fresh",
            "confidence": 0.76,
            "evidence_json": {
                "connector_type": "ato_bot",
                "connector_label": "ATO Bot",
                "focus": "Security-event review backlog",
                "unresolved_security_events": unresolved_security_events,
                "unresolved_critical_events": unresolved_critical_events,
                "summary": f"{unresolved_security_events} unresolved security events remain, including {unresolved_critical_events} high or critical items.",
                "recommended_action": "Triage unresolved security events and document review/disposition activity.",
            },
        },
        {
            "control_id": "CA-7",
            "support_status": continuous_monitoring_status,
            "freshness_status": "fresh",
            "confidence": 0.88,
            "evidence_json": {
                "connector_type": "ato_bot",
                "connector_label": "ATO Bot",
                "focus": "Continuous monitoring health",
                "audit_events_24h": audit_events_24h,
                "failed_ingestion_24h": failed_ingestion_24h,
                "failed_assessments_7d": failed_assessments_7d,
                "unresolved_critical_events": unresolved_critical_events,
                "summary": f"Continuous monitoring is {'healthy' if continuous_monitoring_status == 'supported' else 'degraded'} based on audit freshness and pipeline health.",
                "recommended_action": "Keep ingestion and assessment failures at zero and maintain fresh telemetry for continuous monitoring evidence.",
            },
        },
        {
            "control_id": "CM-3",
            "support_status": config_status,
            "freshness_status": "fresh",
            "confidence": 0.72,
            "evidence_json": {
                "connector_type": "ato_bot",
                "connector_label": "ATO Bot",
                "focus": "Tracked configuration changes",
                "config_changes_7d": config_changes_7d,
                "summary": f"{config_changes_7d} ingestion/runtime configuration changes were recorded in the last 7 days.",
                "recommended_action": "Review and approve configuration changes regularly so they remain defensible as change-control evidence.",
            },
        },
        {
            "control_id": "SI-4",
            "support_status": monitoring_status,
            "freshness_status": "fresh",
            "confidence": 0.79,
            "evidence_json": {
                "connector_type": "ato_bot",
                "connector_label": "ATO Bot",
                "focus": "Ingestion, assessment, and security monitoring health",
                "failed_ingestion_24h": failed_ingestion_24h,
                "failed_assessments_7d": failed_assessments_7d,
                "unresolved_critical_events": unresolved_critical_events,
                "summary": f"Monitoring posture reflects {failed_ingestion_24h} ingestion failures, {failed_assessments_7d} failed assessments, and {unresolved_critical_events} unresolved critical events.",
                "recommended_action": "Investigate pipeline failures and clear critical events before treating the monitoring posture as fully supported.",
            },
        },
        {
            "control_id": "SC-5",
            "support_status": service_status,
            "freshness_status": "fresh",
            "confidence": 0.74,
            "evidence_json": {
                "connector_type": "ato_bot",
                "connector_label": "ATO Bot",
                "focus": "Runtime service availability and internal resilience",
                "service_summary": runtime_summary,
                "services": runtime_services,
                "docker_runtime": docker_runtime,
                "summary": f"{runtime_summary['healthy']} of {runtime_summary['total']} expected runtime services are currently reachable.",
                "recommended_action": "Keep backend, frontend, database, and Redis reachable and review any exposed container drift before relying on this stack for continuous authorization evidence.",
            },
        },
    ]

    drift_records_payload: list[dict[str, Any]] = []
    if privileged_without_mfa > 0:
        drift_records_payload.append(
            {
                "scope_type": "control",
                "scope_id": "IA-2",
                "severity": "high",
                "title": "Privileged users without MFA detected in ATO Bot",
                "details_json": {
                    "admin_users": admin_users,
                    "privileged_without_mfa": privileged_without_mfa,
                    "recommended_action": "Enable MFA for all admin and assessor accounts before relying on this application for cATO operations.",
                },
            }
        )
    if failed_ingestion_24h > 0 or failed_assessments_7d > 0:
        drift_records_payload.append(
            {
                "scope_type": "operations",
                "scope_id": "job_health",
                "severity": "medium",
                "title": "Recent ATO Bot pipeline failures detected",
                "details_json": {
                    "failed_ingestion_24h": failed_ingestion_24h,
                    "failed_assessments_7d": failed_assessments_7d,
                    "recommended_action": "Review failed ingestion and assessment jobs before treating posture as continuously reliable.",
                },
            }
        )
    if unresolved_critical_events > 0:
        drift_records_payload.append(
            {
                "scope_type": "security",
                "scope_id": "critical_events",
                "severity": "high",
                "title": "Unresolved high-severity ATO Bot security events exist",
                "details_json": {
                    "unresolved_security_events": unresolved_security_events,
                    "unresolved_critical_events": unresolved_critical_events,
                    "recommended_action": "Resolve or disposition critical security events before relying on this app as a cATO evidence source.",
                },
            }
        )
    unhealthy_runtime_services = [item for item in runtime_services if item["status"] != "healthy"]
    if unhealthy_runtime_services:
        drift_records_payload.append(
            {
                "scope_type": "runtime",
                "scope_id": "service_health",
                "severity": "high" if any(item["status"] == "unreachable" for item in unhealthy_runtime_services) else "medium",
                "title": "ATO Bot runtime services are degraded or unreachable",
                "details_json": {
                    "services": unhealthy_runtime_services,
                    "recommended_action": "Investigate unhealthy frontend, backend, PostgreSQL, or Redis services before treating ATO Bot as a reliable cATO evidence source.",
                },
            }
        )
    if docker_runtime.get("available") and any(not item.get("healthy") for item in docker_runtime.get("containers", [])):
        drift_records_payload.append(
            {
                "scope_type": "runtime",
                "scope_id": "docker_runtime",
                "severity": "medium",
                "title": "One or more ATO Bot Docker containers are not healthy",
                "details_json": {
                    "containers": docker_runtime.get("containers", []),
                    "recommended_action": "Review unhealthy or restarting containers before relying on this environment for continuous monitoring evidence.",
                },
            }
        )

    return {
        "mode": "internal",
        "connector_type": "ato_bot",
        "connector_label": "ATO Bot",
        "category": "application",
        "records_seen": total_users + audit_events_24h + unresolved_security_events + config_changes_7d,
        "preview_assertions": preview,
        "next_step": "Use these internal posture signals as the first real cATO evidence source while external connectors are still being added.",
        "runtime_services": runtime_services,
        "runtime_service_summary": runtime_summary,
        "docker_runtime": docker_runtime,
        "assertions_payload": assertions_payload,
        "control_postures_payload": control_postures_payload,
        "drift_records_payload": drift_records_payload,
    }


def _build_connector_assertions(account: IntegrationAccount, summary: dict[str, Any]) -> list[dict[str, Any]]:
    assertions = list(summary.get("assertions_payload") or [])
    connector = CONNECTOR_CATALOG.get(account.connector_type, {})
    label = connector.get("label", account.connector_type)
    category = connector.get("category", "integration")
    evidence_types = connector.get("evidence_types", [])
    mode = summary.get("mode") or account.auth_mode
    confidence = 0.45 if mode == "dry_run" else 0.72
    assertions.extend([
        {
            "category": "integration",
            "key": f"{account.connector_type}_connector",
            "value_json": {
                "connector_type": account.connector_type,
                "connector_label": label,
                "category": category,
                "auth_mode": mode,
                "account_name": account.name,
            },
            "normalized_value": f"{account.connector_type}:{account.name}".lower(),
            "confidence": confidence,
            "status": "proposed",
            "rationale": f"{label} connector is configured for this project.",
            "provenance_json": {"integration_account_id": account.id, "mode": mode},
        }
    ])
    for evidence_type in evidence_types:
        assertions.append(
            {
                "category": "live_telemetry",
                "key": evidence_type,
                "value_json": {
                    "connector_type": account.connector_type,
                    "connector_label": label,
                    "evidence_type": evidence_type,
                    "mode": mode,
                },
                "normalized_value": f"{account.connector_type}:{evidence_type}".lower(),
                "confidence": confidence,
                "status": "proposed",
                "rationale": f"{label} is expected to provide {evidence_type.replace('_', ' ')} evidence.",
                "provenance_json": {"integration_account_id": account.id, "mode": mode},
            }
        )
    return assertions


def _build_control_postures(account: IntegrationAccount, summary: dict[str, Any]) -> list[dict[str, Any]]:
    if summary.get("control_postures_payload"):
        return list(summary["control_postures_payload"])
    connector = CONNECTOR_CATALOG.get(account.connector_type, {})
    label = connector.get("label", account.connector_type)
    mode = summary.get("mode") or account.auth_mode
    base_status = "planned" if mode == "dry_run" else "partial"
    confidence = 0.35 if mode == "dry_run" else 0.68
    mappings = CONNECTOR_CONTROL_MAP.get(account.connector_type, [])
    return [
        {
            "control_id": item["control_id"],
            "support_status": item.get("support_status") if mode == "dry_run" else base_status,
            "freshness_status": "fresh",
            "confidence": confidence,
            "evidence_json": {
                "account_id": account.id,
                "account_name": account.name,
                "connector_type": account.connector_type,
                "connector_label": label,
                "auth_mode": mode,
                "focus": item["focus"],
            },
        }
        for item in mappings
    ]


def _build_drift_records(account: IntegrationAccount, summary: dict[str, Any]) -> list[dict[str, Any]]:
    drifts: list[dict[str, Any]] = list(summary.get("drift_records_payload") or [])
    mode = summary.get("mode") or account.auth_mode
    if mode == "dry_run":
        return drifts
    if mode != "internal" and (not account.config_json or not any(v for v in account.config_json.values())):
        drifts.append(
            {
                "scope_type": "connector",
                "scope_id": account.connector_type,
                "severity": "medium",
                "title": f"{account.name} is missing live connector configuration",
                "details_json": {
                    "account_id": account.id,
                    "account_name": account.name,
                    "connector_type": account.connector_type,
                    "recommended_action": "Provide live credentials or endpoint settings before relying on this connector for cATO evidence.",
                },
            }
        )
    if int(summary.get("records_seen") or 0) == 0:
        drifts.append(
            {
                "scope_type": "connector",
                "scope_id": account.connector_type,
                "severity": "low",
                "title": f"{account.name} produced no live telemetry records",
                "details_json": {
                    "account_id": account.id,
                    "account_name": account.name,
                    "connector_type": account.connector_type,
                    "recommended_action": "Verify permissions, connector scope, and source availability.",
                },
            }
        )
    return drifts


async def _persist_connector_knowledge(
    db: AsyncSession,
    *,
    project_id: int,
    run_id: int,
    account: IntegrationAccount,
    summary: dict[str, Any],
) -> int:
    assertions_payload = _build_connector_assertions(account, summary)
    knowledge_run = SystemKnowledgeRun(
        project_id=project_id,
        source_mode="integration_sync",
        source_run_id=run_id,
        status="complete",
        summary_json={
            "connector_type": account.connector_type,
            "account_name": account.name,
            "assertion_count": len(assertions_payload),
            "mode": summary.get("mode") or account.auth_mode,
        },
        completed_at=datetime.now(UTC),
    )
    db.add(knowledge_run)
    await db.flush()
    for item in assertions_payload:
        db.add(
            SystemKnowledgeAssertion(
                run_id=knowledge_run.id,
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
    return len(assertions_payload)


async def _persist_control_posture(
    db: AsyncSession,
    *,
    project_id: int,
    account: IntegrationAccount,
    summary: dict[str, Any],
) -> int:
    rows = _build_control_postures(account, summary)
    count = 0
    for item in rows:
        stmt = insert(ControlTelemetryPosture).values(
            project_id=project_id,
            control_id=item["control_id"],
            source_kind="integration",
            source_ref=f"account:{account.id}",
            support_status=item["support_status"],
            freshness_status=item["freshness_status"],
            confidence=item["confidence"],
            evidence_json=item["evidence_json"],
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["project_id", "control_id", "source_kind", "source_ref"],
            set_={
                "support_status": stmt.excluded.support_status,
                "freshness_status": stmt.excluded.freshness_status,
                "confidence": stmt.excluded.confidence,
                "evidence_json": stmt.excluded.evidence_json,
                "updated_at": datetime.now(UTC),
            },
        )
        await db.execute(stmt)
        count += 1
    return count


async def _persist_drift_records(
    db: AsyncSession,
    *,
    project_id: int,
    account: IntegrationAccount,
    run_id: int,
    summary: dict[str, Any],
) -> int:
    await db.execute(
        update(DriftRecord)
        .where(
            DriftRecord.project_id == project_id,
            DriftRecord.account_id == account.id,
            DriftRecord.status == "active",
        )
        .values(status="resolved", updated_at=datetime.now(UTC))
    )
    items = _build_drift_records(account, summary)
    for item in items:
        db.add(
            DriftRecord(
                project_id=project_id,
                account_id=account.id,
                run_id=run_id,
                source_kind="integration",
                scope_type=item["scope_type"],
                scope_id=item["scope_id"],
                severity=item["severity"],
                status="active",
                title=item["title"],
                details_json=item["details_json"],
            )
        )
    return len(items)


async def list_integration_accounts(project_id: int, db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(IntegrationAccount)
            .where(IntegrationAccount.project_id == project_id)
            .order_by(IntegrationAccount.connector_type, IntegrationAccount.name, IntegrationAccount.id.desc())
        )
    ).scalars().all()
    return [
        {
            "id": item.id,
            "project_id": item.project_id,
            "connector_type": item.connector_type,
            "connector_label": CONNECTOR_CATALOG.get(item.connector_type, {}).get("label", item.connector_type),
            "name": item.name,
            "auth_mode": item.auth_mode,
            "status": item.status,
            "config": item.config_json or {},
            "last_error": item.last_error,
            "last_tested_at": item.last_tested_at.isoformat() if item.last_tested_at else None,
            "last_run_at": item.last_run_at.isoformat() if item.last_run_at else None,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in rows
    ]


async def list_integration_runs(project_id: int, db: AsyncSession, *, limit: int = 25) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(IntegrationRun, IntegrationAccount)
            .join(IntegrationAccount, IntegrationRun.account_id == IntegrationAccount.id)
            .where(IntegrationRun.project_id == project_id)
            .order_by(IntegrationRun.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": run.id,
            "account_id": account.id,
            "account_name": account.name,
            "connector_type": account.connector_type,
            "connector_label": CONNECTOR_CATALOG.get(account.connector_type, {}).get("label", account.connector_type),
            "trigger_mode": run.trigger_mode,
            "status": run.status,
            "records_seen": run.records_seen,
            "assertions_created": run.assertions_created,
            "summary": run.summary_json or {},
            "error_message": run.error_message,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
        for run, account in rows
    ]


async def get_integration_posture(project_id: int, db: AsyncSession) -> dict[str, Any]:
    posture_rows = (
        await db.execute(
            select(ControlTelemetryPosture)
            .where(ControlTelemetryPosture.project_id == project_id)
            .order_by(ControlTelemetryPosture.control_id, ControlTelemetryPosture.updated_at.desc())
        )
    ).scalars().all()
    drift_rows = (
        await db.execute(
            select(DriftRecord)
            .where(DriftRecord.project_id == project_id)
            .order_by(DriftRecord.status.asc(), DriftRecord.updated_at.desc(), DriftRecord.id.desc())
            .limit(50)
        )
    ).scalars().all()

    best_order = {"supported": 5, "partial": 4, "planned": 3, "unknown": 2, "drift_detected": 1, "unsupported": 0}
    by_control: dict[str, dict[str, Any]] = {}
    for row in posture_rows:
        item = {
            "id": row.id,
            "control_id": row.control_id,
            "source_kind": row.source_kind,
            "source_ref": row.source_ref,
            "support_status": row.support_status,
            "freshness_status": row.freshness_status,
            "confidence": row.confidence,
            "evidence": row.evidence_json or {},
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        current = by_control.get(row.control_id)
        if not current or best_order.get(item["support_status"], -1) > best_order.get(current["support_status"], -1):
            by_control[row.control_id] = item

    support_counts: dict[str, int] = {}
    for item in by_control.values():
        support_counts[item["support_status"]] = support_counts.get(item["support_status"], 0) + 1

    return {
        "summary": {
            "control_count": len(by_control),
            "support_counts": support_counts,
            "active_drift_count": sum(1 for row in drift_rows if row.status == "active"),
            "resolved_drift_count": sum(1 for row in drift_rows if row.status == "resolved"),
        },
        "controls": sorted(by_control.values(), key=lambda item: item["control_id"]),
        "drifts": [
            {
                "id": row.id,
                "scope_type": row.scope_type,
                "scope_id": row.scope_id,
                "severity": row.severity,
                "status": row.status,
                "title": row.title,
                "details": row.details_json or {},
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in drift_rows
        ],
    }


async def create_integration_account(
    db: AsyncSession,
    *,
    project_id: int,
    connector_type: str,
    name: str,
    auth_mode: str,
    config_json: dict | None,
    created_by: int | None,
) -> dict[str, Any]:
    if connector_type not in CONNECTOR_CATALOG:
        raise ValueError("Unsupported connector type")
    account = IntegrationAccount(
        project_id=project_id,
        connector_type=connector_type,
        name=name,
        auth_mode=auth_mode,
        status="configured",
        config_json=config_json or {},
        created_by=created_by,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return {
        "id": account.id,
        "name": account.name,
        "connector_type": account.connector_type,
        "auth_mode": account.auth_mode,
        "status": account.status,
    }


async def delete_integration_account(db: AsyncSession, *, project_id: int, account_id: int) -> bool:
    account = await db.get(IntegrationAccount, account_id)
    if not account or account.project_id != project_id:
        return False
    await db.execute(delete(TelemetrySnapshot).where(TelemetrySnapshot.account_id == account_id))
    await db.execute(delete(IntegrationRun).where(IntegrationRun.account_id == account_id))
    await db.delete(account)
    await db.commit()
    return True


async def test_integration_account(db: AsyncSession, *, project_id: int, account_id: int) -> dict[str, Any] | None:
    account = await db.get(IntegrationAccount, account_id)
    if not account or account.project_id != project_id:
        return None

    now = datetime.now(UTC)
    if account.connector_type == "ato_bot":
        account.status = "healthy"
        account.last_error = None
        account.last_tested_at = now
        await db.commit()
        return {
            "status": "healthy",
            "mode": "internal",
            "message": "ATO Bot internal telemetry is available with no external credentials required.",
        }

    if account.auth_mode == "dry_run":
        account.status = "healthy"
        account.last_error = None
        account.last_tested_at = now
        await db.commit()
        return {
            "status": "healthy",
            "mode": "dry_run",
            "message": "Dry-run connector is ready. No external credentials are required yet.",
        }

    has_config = bool(account.config_json and any(v for v in account.config_json.values()))
    account.last_tested_at = now
    if has_config:
        account.status = "healthy"
        account.last_error = None
        await db.commit()
        return {
            "status": "healthy",
            "mode": account.auth_mode,
            "message": "Connector configuration is present. Live API pull is not implemented in this slice yet.",
        }

    account.status = "needs_configuration"
    account.last_error = "Missing connector configuration values."
    await db.commit()
    return {
        "status": "needs_configuration",
        "mode": account.auth_mode,
        "message": "Provide connector configuration details before running a live sync.",
    }


async def run_integration_sync(
    db: AsyncSession,
    *,
    project_id: int,
    account_id: int,
    trigger_mode: str = "manual",
) -> dict[str, Any] | None:
    account = await db.get(IntegrationAccount, account_id)
    if not account or account.project_id != project_id:
        return None

    run = IntegrationRun(
        project_id=project_id,
        account_id=account_id,
        trigger_mode=trigger_mode,
        status="running",
    )
    db.add(run)
    await db.flush()

    now = datetime.now(UTC)
    if account.connector_type == "ato_bot":
        summary = await _atobot_summary(db, account)
    elif account.auth_mode == "dry_run":
        summary = _dry_run_summary(account)
    else:
        summary = {
            "mode": account.auth_mode,
            "connector_type": account.connector_type,
            "connector_label": CONNECTOR_CATALOG.get(account.connector_type, {}).get("label", account.connector_type),
            "records_seen": 0,
            "preview_assertions": [],
            "next_step": "Live sync plumbing is scaffolded; implement connector-specific API pulls next.",
        }

    run.records_seen = int(summary.get("records_seen") or 0)
    assertions_created = await _persist_connector_knowledge(
        db,
        project_id=project_id,
        run_id=run.id,
        account=account,
        summary=summary,
    )
    posture_created = await _persist_control_posture(
        db,
        project_id=project_id,
        account=account,
        summary=summary,
    )
    drift_created = await _persist_drift_records(
        db,
        project_id=project_id,
        account=account,
        run_id=run.id,
        summary=summary,
    )
    run.assertions_created = assertions_created
    run.summary_json = {
        **summary,
        "posture_controls": posture_created,
        "drift_records": drift_created,
    }
    run.status = "completed"
    run.completed_at = now

    account.last_run_at = now
    account.status = "healthy" if account.auth_mode in {"dry_run", "internal"} or account.connector_type == "ato_bot" else "connected"
    account.last_error = None

    db.add(
        TelemetrySnapshot(
            project_id=project_id,
            account_id=account_id,
            run_id=run.id,
            snapshot_type="connector_summary",
            freshness_status="fresh",
            summary_json=summary,
        )
    )
    await db.commit()

    return {
        "run_id": run.id,
        "status": run.status,
        "summary": run.summary_json,
    }
