from __future__ import annotations

import os
import re
from pathlib import Path
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.orm import (
    Assessment,
    AuditLog,
    Document,
    IngestionConfigAudit,
    IngestionRun,
    POAM,
    SecurityEvent,
    User,
)
from app.services.integrations import _collect_runtime_snapshot

REPO_ROOT = Path(__file__).resolve().parents[3]


def _extract_secret_from_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return parsed.password or ""
    except Exception:
        return ""


def _is_weak_secret(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.strip().lower()
    weak_exact = {
        "changeme",
        "secret",
        "dev-secret",
        "development",
        "password",
        "atobot",
        "ato-bot-secret",
    }
    if lowered in weak_exact:
        return True
    if len(value.strip()) < 16:
        return True
    if lowered.isalpha() or lowered.isdigit():
        return True
    return False


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _contains_all(text: str, needles: list[str]) -> bool:
    return bool(text) and all(needle in text for needle in needles)


def _contains_any(text: str, needles: list[str]) -> bool:
    return bool(text) and any(needle in text for needle in needles)


def _service_block(compose_text: str, service_name: str) -> str:
    pattern = rf"(?ms)^  {re.escape(service_name)}:\n(.*?)(?=^\S|^  [A-Za-z0-9_-]+:\n|\Z)"
    match = re.search(pattern, compose_text)
    return match.group(1) if match else ""


def _dockerfile_runs_as_non_root(dockerfile_text: str) -> bool:
    for line in dockerfile_text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("USER "):
            return stripped.split(None, 1)[1].strip().lower() != "root"
    return False


def _service_has_runtime_hardening(service_text: str) -> bool:
    return _contains_any(
        service_text,
        [
            "read_only:",
            "cap_drop:",
            "security_opt:",
            "user:",
            "tmpfs:",
        ],
    )


def _container_security_summary(compose_text: str, backend_dockerfile: str, frontend_dockerfile: str) -> dict[str, Any]:
    services = {
        "backend": _service_block(compose_text, "backend"),
        "frontend": _service_block(compose_text, "frontend"),
        "postgres": _service_block(compose_text, "postgres"),
        "redis": _service_block(compose_text, "redis"),
    }
    default_secret_fallbacks = []
    if "${POSTGRES_PASSWORD:-changeme}" in compose_text:
        default_secret_fallbacks.append("postgres")
    if "${REDIS_PASSWORD:-changeme}" in compose_text:
        default_secret_fallbacks.append("redis")

    service_rows = [
        {
            "service": "backend",
            "runs_as_non_root": _dockerfile_runs_as_non_root(backend_dockerfile),
            "runtime_hardening": _service_has_runtime_hardening(services["backend"]),
            "healthcheck": "healthcheck:" in services["backend"],
        },
        {
            "service": "frontend",
            "runs_as_non_root": _dockerfile_runs_as_non_root(frontend_dockerfile),
            "runtime_hardening": _service_has_runtime_hardening(services["frontend"]),
            "healthcheck": "healthcheck:" in services["frontend"],
        },
        {
            "service": "postgres",
            "runs_as_non_root": False,
            "runtime_hardening": _service_has_runtime_hardening(services["postgres"]),
            "healthcheck": "healthcheck:" in services["postgres"],
        },
        {
            "service": "redis",
            "runs_as_non_root": False,
            "runtime_hardening": _service_has_runtime_hardening(services["redis"]),
            "healthcheck": "healthcheck:" in services["redis"],
        },
    ]
    return {
        "services": service_rows,
        "default_secret_fallbacks": default_secret_fallbacks,
        "non_root_healthy": sum(1 for item in service_rows[:2] if item["runs_as_non_root"]),
        "runtime_hardening_healthy": sum(1 for item in service_rows if item["runtime_hardening"]),
        "healthcheck_healthy": sum(1 for item in service_rows if item["healthcheck"]),
    }


def _static_security_attestations() -> list[dict[str, Any]]:
    dockerignore_text = _safe_read(REPO_ROOT / "backend" / ".dockerignore")
    compose_text = _safe_read(REPO_ROOT / "docker-compose.yml")
    backend_dockerfile_text = _safe_read(REPO_ROOT / "backend" / "Dockerfile")
    frontend_dockerfile_text = _safe_read(REPO_ROOT / "frontend" / "Dockerfile")
    token_storage_text = _safe_read(REPO_ROOT / "frontend" / "src" / "utils" / "tokenStorage.js")
    auth_text = _safe_read(REPO_ROOT / "backend" / "app" / "api" / "auth.py")
    headers_text = _safe_read(REPO_ROOT / "backend" / "app" / "middleware" / "security_headers.py")
    config_text = _safe_read(REPO_ROOT / "backend" / "app" / "core" / "config.py")
    container_security = _container_security_summary(compose_text, backend_dockerfile_text, frontend_dockerfile_text)

    return [
        {
            "id": "build_context_hardening",
            "label": "Harden Docker build context",
            "group": "Secure build and deployment footprint",
            "controls": ["CM-6", "SC-28"],
            "healthy": _contains_all(dockerignore_text, [".env", "uploads/", "outputs/", ".venv/"]),
            "evidence": "backend/.dockerignore excludes secrets, uploads, outputs, and virtualenv content from backend image builds.",
            "action": "Keep backend/.dockerignore aligned with sensitive runtime and evidence directories.",
        },
        {
            "id": "localhost_service_exposure",
            "label": "Limit local service exposure",
            "group": "Protect application boundaries",
            "controls": ["SC-7", "CM-6"],
            "healthy": _contains_all(
                compose_text,
                [
                    '127.0.0.1:5432:5432',
                    '127.0.0.1:6379:6379',
                    '127.0.0.1:8000:8000',
                    '127.0.0.1:3001:80',
                ],
            ),
            "evidence": "docker-compose binds PostgreSQL, Redis, backend, and frontend to localhost instead of all interfaces.",
            "action": "Keep non-public services bound to 127.0.0.1 unless an explicit exposure decision is documented.",
        },
        {
            "id": "session_scoped_tokens",
            "label": "Use session-scoped browser tokens",
            "group": "Manage access and permissions",
            "controls": ["IA-5", "AC-2"],
            "healthy": _contains_all(token_storage_text, ["sessionStorage.setItem", "sessionStorage.getItem"]),
            "evidence": "Frontend token storage uses sessionStorage and clears legacy localStorage tokens.",
            "action": "Keep browser tokens session-scoped and avoid persistent localStorage token handling.",
        },
        {
            "id": "auth_rate_limiting",
            "label": "Throttle authentication endpoints",
            "group": "Manage access and permissions",
            "controls": ["AC-7", "IA-5"],
            "healthy": _contains_all(auth_text, ['@limiter.limit("10/minute")', '@limiter.limit("30/minute")']),
            "evidence": "Login and refresh endpoints are rate-limited through the shared limiter.",
            "action": "Maintain auth rate limiting and expand it if new high-risk auth endpoints are added.",
        },
        {
            "id": "browser_security_headers",
            "label": "Apply browser and API security headers",
            "group": "Harden browser and API boundaries",
            "controls": ["SC-8", "SI-10"],
            "healthy": _contains_all(headers_text, ["Strict-Transport-Security", "Content-Security-Policy", "Cross-Origin-Opener-Policy"]),
            "evidence": "Security headers middleware sets HSTS, CSP, COOP, CORP, X-Frame-Options, and related browser protections.",
            "action": "Keep security headers enabled and review CSP when new frontend capabilities are introduced.",
        },
        {
            "id": "production_security_validation",
            "label": "Reject weak production security configuration",
            "group": "Protect secrets and application configuration",
            "controls": ["CM-6", "IA-5"],
            "healthy": _contains_all(config_text, ["def validate_security_posture", "Wildcard CORS origins cannot be used", "SECRET_KEY"]),
            "evidence": "Production startup validation blocks weak secrets and credentialed wildcard CORS.",
            "action": "Keep startup validation strict enough to stop insecure production configuration before boot.",
        },
        {
            "id": "container_default_fallbacks",
            "label": "Remove default container credential fallbacks",
            "group": "Container security hardening",
            "controls": ["IA-5", "SC-28"],
            "healthy": len(container_security["default_secret_fallbacks"]) == 0,
            "evidence": "docker-compose currently uses password fallbacks for PostgreSQL and Redis when environment variables are missing.",
            "action": "Remove default `changeme` fallbacks and require explicit secrets for containerized services.",
        },
        {
            "id": "non_root_app_containers",
            "label": "Run application containers as non-root",
            "group": "Container security hardening",
            "controls": ["CM-6", "SC-2"],
            "healthy": container_security["non_root_healthy"] == 2,
            "evidence": "Backend and frontend Dockerfiles should set an explicit non-root USER before runtime.",
            "action": "Add non-root users to the backend and frontend images and switch runtime execution away from root.",
        },
        {
            "id": "container_runtime_hardening",
            "label": "Apply runtime hardening to containers",
            "group": "Container security hardening",
            "controls": ["CM-6", "SC-7"],
            "healthy": container_security["runtime_hardening_healthy"] == 4,
            "evidence": "Compose services should use runtime hardening like read-only filesystems, dropped capabilities, or no-new-privileges where feasible.",
            "action": "Add service-level runtime hardening to backend, frontend, Redis, and PostgreSQL containers.",
        },
    ]


def _recommendation(
    *,
    key: str,
    title: str,
    group: str,
    controls: list[str],
    points: int,
    healthy_resources: int,
    unhealthy_resources: int,
    total_resources: int,
    rationale: str,
    action: str,
    severity: str = "medium",
) -> dict[str, Any]:
    total = max(total_resources, 1)
    healthy = max(0, min(healthy_resources, total))
    unhealthy = max(0, min(unhealthy_resources, total))
    if unhealthy == 0 and healthy == total:
        status = "completed"
    elif severity == "high" and unhealthy > 0:
        status = "attention"
    elif healthy == 0:
        status = "attention"
    else:
        status = "in_progress"
    earned_points = round(points * (healthy / total))
    return {
        "id": key,
        "title": title,
        "group": group,
        "controls": controls,
        "points": points,
        "earned_points": earned_points,
        "potential_points": points - earned_points,
        "healthy_resources": healthy,
        "unhealthy_resources": unhealthy,
        "not_applicable_resources": 0,
        "total_resources": total,
        "status": status,
        "severity": severity,
        "health_ratio": healthy / total,
        "rationale": rationale,
        "action": action,
    }


async def build_ato_bot_security_posture(db: AsyncSession) -> dict[str, Any]:
    settings = get_settings()
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
    latest_assessment = (
        await db.execute(select(Assessment).order_by(Assessment.id.desc()).limit(1))
    ).scalar_one_or_none()

    runtime_snapshot = await _collect_runtime_snapshot()
    runtime_services = runtime_snapshot["services"]
    runtime_summary = runtime_snapshot["service_summary"]
    docker_runtime = runtime_snapshot["docker_runtime"]
    static_attestations = _static_security_attestations()
    container_attestations = [item for item in static_attestations if item["group"] == "Container security hardening"]
    container_healthy = sum(1 for item in container_attestations if item["healthy"])
    container_unhealthy = len(container_attestations) - container_healthy
    static_healthy = sum(1 for item in static_attestations if item["healthy"])
    static_unhealthy = len(static_attestations) - static_healthy
    compose_text = _safe_read(REPO_ROOT / "docker-compose.yml")
    backend_dockerfile_text = _safe_read(REPO_ROOT / "backend" / "Dockerfile")
    frontend_dockerfile_text = _safe_read(REPO_ROOT / "frontend" / "Dockerfile")
    container_security = _container_security_summary(compose_text, backend_dockerfile_text, frontend_dockerfile_text)

    secret_checks = [
        {"name": "JWT signing key", "weak": _is_weak_secret(settings.secret_key)},
        {"name": "Database credential", "weak": _is_weak_secret(_extract_secret_from_url(os.getenv("DATABASE_URL") or settings.database_url))},
        {"name": "Redis credential", "weak": _is_weak_secret(_extract_secret_from_url(os.getenv("REDIS_URL") or settings.redis_url))},
    ]
    weak_secret_count = sum(1 for item in secret_checks if item["weak"])

    recommendations = [
        _recommendation(
            key="privileged_mfa",
            title="Enforce MFA for privileged users",
            group="Manage access and permissions",
            controls=["IA-2", "AC-2"],
            points=15,
            healthy_resources=max(admin_users - privileged_without_mfa, 0) if admin_users else 0,
            unhealthy_resources=privileged_without_mfa if admin_users else 1,
            total_resources=max(admin_users, 1),
            rationale=f"{privileged_without_mfa} privileged account(s) are missing MFA coverage.",
            action="Require MFA for every admin and assessor before relying on ATO Bot as a cATO evidence source.",
            severity="high",
        ),
        _recommendation(
            key="secrets",
            title="Strengthen infrastructure secrets",
            group="Protect secrets and application configuration",
            controls=["IA-5", "SC-28"],
            points=12,
            healthy_resources=3 - weak_secret_count,
            unhealthy_resources=weak_secret_count,
            total_resources=3,
            rationale="JWT, database, and Redis secrets must not rely on weak or default values.",
            action="Replace weak/default secrets and rotate any credentials that still use placeholder values such as 'changeme'.",
            severity="high",
        ),
        _recommendation(
            key="audit_generation",
            title="Maintain audit generation and retention evidence",
            group="Collect audit evidence",
            controls=["AU-2", "AU-12"],
            points=10,
            healthy_resources=1 if audit_events_24h > 0 else 0,
            unhealthy_resources=0 if audit_events_24h > 0 else 1,
            total_resources=1,
            rationale=f"{audit_events_24h} audit event(s) were recorded in the last 24 hours.",
            action="Keep audit logging active and verify the event stream remains non-zero during normal use.",
        ),
        _recommendation(
            key="critical_events",
            title="Resolve high-severity security alerts",
            group="Respond to security alerts",
            controls=["AU-6", "SI-4"],
            points=12,
            healthy_resources=1 if unresolved_critical_events == 0 else 0,
            unhealthy_resources=0 if unresolved_critical_events == 0 else 1,
            total_resources=1,
            rationale=f"{unresolved_critical_events} high or critical unresolved security event(s) remain.",
            action="Triage or disposition critical security events so alert backlog does not undermine monitoring trust.",
            severity="high",
        ),
        _recommendation(
            key="monitoring_pipeline",
            title="Keep continuous monitoring jobs healthy",
            group="Monitor security operations",
            controls=["CA-7", "SI-4"],
            points=12,
            healthy_resources=sum(1 for value in [failed_ingestion_24h == 0, failed_assessments_7d == 0, documents_failed == 0] if value),
            unhealthy_resources=sum(1 for value in [failed_ingestion_24h > 0, failed_assessments_7d > 0, documents_failed > 0] if value),
            total_resources=3,
            rationale=f"Recent failures: {failed_ingestion_24h} ingestion, {failed_assessments_7d} assessments, {documents_failed} failed document parses.",
            action="Reduce failed ingestion, assessment, and document processing runs to keep continuous-monitoring evidence trustworthy.",
            severity="high",
        ),
        _recommendation(
            key="config_governance",
            title="Track and review configuration changes",
            group="Manage security configurations",
            controls=["CM-3"],
            points=9,
            healthy_resources=1 if config_changes_7d > 0 else 0,
            unhealthy_resources=0 if config_changes_7d > 0 else 1,
            total_resources=1,
            rationale=f"{config_changes_7d} configuration change audit event(s) were recorded in the last 7 days.",
            action="Keep runtime and ingestion configuration changes recorded so they can support CM-3 evidence.",
        ),
        _recommendation(
            key="security_services",
            title="Keep the security monitoring stack available",
            group="Operational resilience supporting security",
            controls=["SC-5", "CA-7"],
            points=8,
            healthy_resources=runtime_summary["healthy"],
            unhealthy_resources=runtime_summary["degraded"] + runtime_summary["unreachable"],
            total_resources=max(runtime_summary["total"], 1),
            rationale=f"{runtime_summary['healthy']} of {runtime_summary['total']} expected ATO Bot services are reachable right now.",
            action="Keep backend, frontend, PostgreSQL, and Redis reachable so audit and continuous-monitoring evidence remains available.",
        ),
        _recommendation(
            key="poam_backlog",
            title="Reduce open remediation backlog",
            group="Track remediation and residual risk",
            controls=["CA-5"],
            points=7,
            healthy_resources=1 if open_poam == 0 else 0,
            unhealthy_resources=0 if open_poam == 0 else 1,
            total_resources=1,
            rationale=f"{open_poam} open or in-progress POA&M item(s) currently remain.",
            action="Review aging POA&M items and close or revalidate them so backlog does not become accepted hidden risk.",
        ),
        _recommendation(
            key="secure_build_context",
            title="Keep sensitive files out of Docker build context",
            group="Secure build and deployment footprint",
            controls=["CM-6", "SC-28"],
            points=10,
            healthy_resources=1 if next((item for item in static_attestations if item["id"] == "build_context_hardening"), {}).get("healthy") else 0,
            unhealthy_resources=0 if next((item for item in static_attestations if item["id"] == "build_context_hardening"), {}).get("healthy") else 1,
            total_resources=1,
            rationale="Backend builds should exclude secrets, evidence uploads, outputs, and local virtual environments from the image context.",
            action="Maintain backend/.dockerignore so image builds do not send .env, uploads, outputs, or virtualenv content into Docker layers.",
            severity="high",
        ),
        _recommendation(
            key="boundary_and_session_controls",
            title="Keep browser, auth, and network boundaries hardened",
            group="Harden browser and API boundaries",
            controls=["AC-7", "IA-5", "SC-7", "SC-8", "SI-10"],
            points=15,
            healthy_resources=sum(
                1
                for item in static_attestations
                if item["id"] in {
                    "localhost_service_exposure",
                    "session_scoped_tokens",
                    "auth_rate_limiting",
                    "browser_security_headers",
                }
                and item["healthy"]
            ),
            unhealthy_resources=sum(
                1
                for item in static_attestations
                if item["id"] in {
                    "localhost_service_exposure",
                    "session_scoped_tokens",
                    "auth_rate_limiting",
                    "browser_security_headers",
                }
                and not item["healthy"]
            ),
            total_resources=4,
            rationale="Network exposure, token handling, auth throttling, and browser protections should all be in place before using ATO Bot as a cATO evidence source.",
            action="Keep localhost-only exposure, session-scoped tokens, auth throttling, and security headers in place and visible as explicit security assertions.",
            severity="high",
        ),
        _recommendation(
            key="container_hardening",
            title="Harden the container runtime footprint",
            group="Container security hardening",
            controls=["CM-6", "SC-2", "SC-7", "SC-28"],
            points=14,
            healthy_resources=container_healthy,
            unhealthy_resources=container_unhealthy,
            total_resources=max(len(container_attestations), 1),
            rationale="Container security is not only build hygiene. Runtime least privilege, explicit secrets, and hardened service configuration are part of the deployment posture.",
            action="Remove default secret fallbacks, run app containers as non-root, and add compose-level runtime hardening to the stack.",
            severity="high",
        ),
        _recommendation(
            key="production_security_guardrails",
            title="Block insecure production startup conditions",
            group="Protect secrets and application configuration",
            controls=["CM-6", "IA-5"],
            points=9,
            healthy_resources=1 if next((item for item in static_attestations if item["id"] == "production_security_validation"), {}).get("healthy") else 0,
            unhealthy_resources=0 if next((item for item in static_attestations if item["id"] == "production_security_validation"), {}).get("healthy") else 1,
            total_resources=1,
            rationale="Production should fail fast when secrets are weak or CORS is unsafe instead of silently starting insecurely.",
            action="Keep strict startup validation for production secrets and credentialed CORS posture.",
            severity="high",
        ),
    ]

    severity_order = {"high": 0, "medium": 1, "low": 2}

    total_points = sum(item["points"] for item in recommendations)
    earned_points = sum(item["earned_points"] for item in recommendations)
    secure_score_pct = round((earned_points / total_points) * 100) if total_points else 0
    for item in recommendations:
        item["potential_score_increase_pct"] = round((item["potential_points"] / total_points) * 100) if total_points else 0
    recommendations.sort(
        key=lambda item: (
            severity_order.get(item["severity"], 3),
            -item["potential_points"],
            item["title"],
        )
    )

    resource_health = {
        "healthy": sum(item["healthy_resources"] for item in recommendations),
        "unhealthy": sum(item["unhealthy_resources"] for item in recommendations),
        "not_applicable": sum(item["not_applicable_resources"] for item in recommendations),
    }
    resource_health["total"] = resource_health["healthy"] + resource_health["unhealthy"] + resource_health["not_applicable"]

    latest_assessment_summary = None
    if latest_assessment:
        latest_assessment_summary = {
            "id": latest_assessment.id,
            "status": latest_assessment.status,
            "started_at": latest_assessment.started_at.isoformat() if latest_assessment.started_at else None,
            "completed_at": latest_assessment.completed_at.isoformat() if latest_assessment.completed_at else None,
        }

    security_assertions = [
        {
            "label": "Privileged MFA coverage",
            "value": f"{max(admin_users - privileged_without_mfa, 0)}/{admin_users or 1}",
            "status": "healthy" if privileged_without_mfa == 0 and admin_users > 0 else "attention",
            "hint": f"{privileged_without_mfa} privileged account(s) without MFA.",
        },
        {
            "label": "Audit events in 24h",
            "value": str(audit_events_24h),
            "status": "healthy" if audit_events_24h > 0 else "attention",
            "hint": "Application audit trail freshness.",
        },
        {
            "label": "Critical security alerts",
            "value": str(unresolved_critical_events),
            "status": "healthy" if unresolved_critical_events == 0 else "attention",
            "hint": f"{unresolved_security_events} unresolved total security event(s).",
        },
        {
            "label": "Weak infrastructure secrets",
            "value": str(weak_secret_count),
            "status": "healthy" if weak_secret_count == 0 else "attention",
            "hint": ", ".join(item["name"] for item in secret_checks if item["weak"]) or "No weak secrets detected.",
        },
        {
            "label": "Runtime services reachable",
            "value": f"{runtime_summary['healthy']}/{runtime_summary['total']}",
            "status": "healthy" if runtime_summary["unreachable"] == 0 else "attention",
            "hint": f"{runtime_summary['degraded']} degraded, {runtime_summary['unreachable']} unreachable.",
        },
        {
            "label": "Indexed documents",
            "value": str(indexed_docs),
            "status": "healthy" if indexed_docs > 0 else "attention",
            "hint": f"{documents_failed} failed document(s) still need review.",
        },
        {
            "label": "Static security attestations",
            "value": f"{static_healthy}/{len(static_attestations)}",
            "status": "healthy" if static_unhealthy == 0 else "attention",
            "hint": f"{static_unhealthy} implementation or deployment security control(s) still need attention.",
        },
        {
            "label": "Container hardening controls",
            "value": f"{container_healthy}/{len(container_attestations)}",
            "status": "healthy" if container_unhealthy == 0 else "attention",
            "hint": "Tracks default credential fallbacks, non-root runtime, and compose runtime hardening.",
        },
    ]

    return {
        "generated_at": now.isoformat(),
        "metrics": {
            "total_users": total_users,
            "active_users": active_users,
            "admin_users": admin_users,
            "privileged_without_mfa": privileged_without_mfa,
            "audit_events_24h": audit_events_24h,
            "config_changes_7d": config_changes_7d,
            "unresolved_security_events": unresolved_security_events,
            "unresolved_critical_events": unresolved_critical_events,
            "failed_ingestion_24h": failed_ingestion_24h,
            "failed_assessments_7d": failed_assessments_7d,
            "documents_failed": documents_failed,
            "indexed_docs": indexed_docs,
            "open_poam": open_poam,
            "static_attestations_total": len(static_attestations),
            "static_attestations_healthy": static_healthy,
        },
        "secure_score": {
            "percentage": secure_score_pct,
            "earned_points": earned_points,
            "total_points": total_points,
        },
        "recommendation_status": {
            "completed_controls": sum(1 for item in recommendations if item["status"] == "completed"),
            "total_controls": len(recommendations),
            "completed_recommendations": sum(1 for item in recommendations if item["potential_points"] == 0),
            "total_recommendations": len(recommendations),
        },
        "resource_health": resource_health,
        "recommendations": recommendations,
        "security_assertions": security_assertions,
        "implementation_attestations": static_attestations,
        "supporting_context": {
            "runtime_services": runtime_services,
            "runtime_service_summary": runtime_summary,
            "docker_runtime": docker_runtime,
            "container_security": {
                "healthy": container_healthy,
                "total": len(container_attestations),
                "services": container_security["services"],
                "default_secret_fallbacks": container_security["default_secret_fallbacks"],
                "attestations": container_attestations,
            },
            "latest_assessment": latest_assessment_summary,
            "secret_checks": secret_checks,
        },
    }
