from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.middleware.security_headers import csp_allows_inline_scripts, csp_allows_inline_styles
from app.models.orm import (
    Assessment,
    AuditLog,
    ControlOverride,
    Document,
    IngestionConfigAudit,
    IngestionRun,
    POAM,
    Project,
    RefreshToken,
    SecurityAsset,
    SecurityBuildSnapshot,
    SecurityEvent,
    SecurityChangeEvent,
    SecurityCollector,
    SecurityCollectorNonce,
    SecurityFinding,
    SecurityRecommendation,
    SecurityRuntimeSnapshot,
    SecurityScan,
    SecuritySettingHistory,
    SecurityTrackedSetting,
    User,
    VerificationCheck,
    VerificationResult,
)
from app.services.llm.runtime import build_provider_for_purpose

settings = get_settings()
_GUIDANCE_CACHE: dict[str, dict[str, Any]] = {}


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt_secret(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def _decrypt_secret(value: bytes) -> str:
    return _fernet().decrypt(value).decode("utf-8")


def _signature_message(timestamp: str, nonce: str, body: bytes) -> bytes:
    return timestamp.encode("utf-8") + b"\n" + nonce.encode("utf-8") + b"\n" + body


def _severity_rank(value: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get((value or "").lower(), 0)


def _parse_iso_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _health_status(open_count: int, severity: str) -> str:
    if open_count <= 0:
        return "completed"
    return "attention" if severity in {"high", "critical"} else "in_progress"


def _value_hash(value: Any) -> str:
    normalized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _change_impact(setting_key: str, old_value: Any, new_value: Any) -> tuple[str, str]:
    positive_bool = {
        "container.non_root",
        "container.read_only_rootfs",
        "container.cap_drop_enabled",
        "container.healthcheck_enabled",
        "scan.backend_dependency_scan_available",
        "scan.frontend_dependency_scan_available",
        "scan.image_scan_available",
        "scan.image_scan_authenticated",
    }
    negative_bool = {
        "container.privileged",
        "container.mutable_image_tag",
        "host.reboot_required",
    }
    numeric_lower_better = {
        "host.missing_security_updates",
        "scan.backend_dependency_vuln_count",
        "scan.frontend_dependency_vuln_count",
        "scan.image_vuln_count",
    }

    if setting_key in positive_bool and isinstance(old_value, bool) and isinstance(new_value, bool):
        if old_value == new_value:
            return "low", "neutral"
        return ("medium", "positive") if new_value else ("high", "negative")

    if setting_key in negative_bool and isinstance(old_value, bool) and isinstance(new_value, bool):
        if old_value == new_value:
            return "low", "neutral"
        return ("high", "negative") if new_value else ("medium", "positive")

    if setting_key in numeric_lower_better:
        try:
            old_num = float(old_value or 0)
            new_num = float(new_value or 0)
        except Exception:
            return "low", "unknown"
        if new_num == old_num:
            return "low", "neutral"
        if new_num < old_num:
            return "medium", "positive"
        severity = "high" if new_num - old_num >= 5 else "medium"
        return severity, "negative"

    if setting_key == "container.published_ports":
        old_set = set(old_value or [])
        new_set = set(new_value or [])
        if old_set == new_set:
            return "low", "neutral"
        if new_set.issubset(old_set):
            return "medium", "positive"
        return "high", "negative"

    if setting_key == "container.image_digest":
        return "low", "neutral"

    return "low", "unknown"


def _change_status(snapshot_type: str, impact_direction: str) -> str:
    if impact_direction == "negative":
        return "needs_review"
    if snapshot_type == "build" and impact_direction in {"positive", "neutral"}:
        return "expected"
    if impact_direction == "positive":
        return "observed"
    return "observed"


def _change_event_type(impact_direction: str) -> str:
    if impact_direction == "negative":
        return "setting_regressed"
    if impact_direction == "positive":
        return "setting_improved"
    return "setting_changed"


def _summarize_value(value: Any) -> str:
    if isinstance(value, bool):
        return "enabled" if value else "disabled"
    if value is None or value == "":
        return "none"
    if isinstance(value, list):
        if not value:
            return "none"
        preview = ", ".join(str(item) for item in value[:2])
        if len(value) > 2:
            preview += f" +{len(value) - 2}"
        return preview
    return str(value)


def _finding_identity_key(*, title: str, category: str, asset_id: int | None, metadata: dict[str, Any] | None) -> tuple[Any, ...]:
    metadata = metadata or {}
    finding_type = (
        (metadata.get("detail_contract") or {}).get("finding_type")
        or metadata.get("finding_type")
        or category
        or "security_finding"
    )
    asset_name = metadata.get("asset_name")
    return (finding_type, title or "", category or "", asset_id or 0, asset_name or "")


async def _close_absent_source_findings(
    db: AsyncSession,
    *,
    project_id: int,
    source: str,
    active_keys: set[tuple[Any, ...]],
    resolved_at: datetime,
) -> None:
    existing_rows = (
        await db.execute(
            select(SecurityFinding).where(
                SecurityFinding.project_id == project_id,
                SecurityFinding.source == source,
                SecurityFinding.status == "open",
            )
        )
    ).scalars().all()

    for row in existing_rows:
        row_key = _finding_identity_key(
            title=row.title,
            category=row.category,
            asset_id=row.asset_id,
            metadata=dict(row.metadata_json or {}),
        )
        if row_key in active_keys:
            continue
        row.status = "closed"
        row.resolved_at = resolved_at


async def _record_setting(
    db: AsyncSession,
    *,
    project_id: int,
    asset_id: int,
    setting_key: str,
    setting_label: str,
    category: str,
    value: Any,
    observed_at: datetime,
    snapshot_type: str,
    snapshot_id: int,
    source: str,
) -> None:
    value_hash = _value_hash(value)
    tracked = (
        await db.execute(
            select(SecurityTrackedSetting).where(
                SecurityTrackedSetting.project_id == project_id,
                SecurityTrackedSetting.asset_id == asset_id,
                SecurityTrackedSetting.setting_key == setting_key,
            )
        )
    ).scalar_one_or_none()

    if not tracked:
        tracked = SecurityTrackedSetting(
            project_id=project_id,
            asset_id=asset_id,
            setting_key=setting_key,
            setting_label=setting_label,
            category=category,
            current_value_json=value,
            current_value_hash=value_hash,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            last_changed_at=observed_at,
            source=source,
        )
        db.add(tracked)
        await db.flush()
    else:
        if tracked.current_value_hash != value_hash:
            impact_level, impact_direction = _change_impact(setting_key, tracked.current_value_json, value)
            summary = f"{setting_label}: {_summarize_value(tracked.current_value_json)} -> {_summarize_value(value)}"
            db.add(
                SecurityChangeEvent(
                    project_id=project_id,
                    asset_id=asset_id,
                    tracked_setting_id=tracked.id,
                    event_type=_change_event_type(impact_direction),
                    category=category,
                    old_value_json=tracked.current_value_json,
                    new_value_json=value,
                    detected_at=observed_at,
                    source_snapshot_type=snapshot_type,
                    source_snapshot_id=snapshot_id,
                    impact_level=impact_level,
                    impact_direction=impact_direction,
                    change_status=_change_status(snapshot_type, impact_direction),
                    summary=summary,
                    details_json={
                        "setting_key": setting_key,
                        "setting_label": setting_label,
                        "source": source,
                    },
                )
            )
            tracked.current_value_json = value
            tracked.current_value_hash = value_hash
            tracked.last_changed_at = observed_at
        tracked.last_seen_at = observed_at
        tracked.source = source

    db.add(
        SecuritySettingHistory(
            tracked_setting_id=tracked.id,
            snapshot_type=snapshot_type,
            snapshot_id=snapshot_id,
            value_json=value,
            value_hash=value_hash,
            observed_at=observed_at,
        )
    )


async def _record_runtime_settings(
    db: AsyncSession,
    *,
    project_id: int,
    snapshot_id: int,
    host_asset_id: int | None,
    host: dict[str, Any],
    container_asset_ids: dict[str, int],
    payload: dict[str, Any],
    source: str,
    observed_at: datetime,
) -> None:
    if host_asset_id:
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=host_asset_id,
            setting_key="host.missing_security_updates",
            setting_label="Missing security updates",
            category="Host Patching",
            value=int((payload.get("patch_posture") or {}).get("missing_security_updates") or 0),
            observed_at=observed_at,
            snapshot_type="runtime",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=host_asset_id,
            setting_key="host.reboot_required",
            setting_label="Reboot required",
            category="Host Patching",
            value=bool((payload.get("patch_posture") or {}).get("reboot_required")),
            observed_at=observed_at,
            snapshot_type="runtime",
            snapshot_id=snapshot_id,
            source=source,
        )

    for container in payload.get("containers") or []:
        name = container.get("name")
        asset_id = container_asset_ids.get(name)
        if not asset_id:
            continue
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=asset_id,
            setting_key="container.non_root",
            setting_label="Runs as non-root",
            category="Platform & Container Security",
            value=bool(container.get("non_root")),
            observed_at=observed_at,
            snapshot_type="runtime",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=asset_id,
            setting_key="container.read_only_rootfs",
            setting_label="Read-only root filesystem",
            category="Platform & Container Security",
            value=bool(container.get("read_only_rootfs")),
            observed_at=observed_at,
            snapshot_type="runtime",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=asset_id,
            setting_key="container.cap_drop_enabled",
            setting_label="Drops Linux capabilities",
            category="Platform & Container Security",
            value=bool(container.get("cap_drop")),
            observed_at=observed_at,
            snapshot_type="runtime",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=asset_id,
            setting_key="container.healthcheck_enabled",
            setting_label="Container healthcheck enabled",
            category="Monitoring & Audit",
            value=bool(container.get("healthcheck")),
            observed_at=observed_at,
            snapshot_type="runtime",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=asset_id,
            setting_key="container.privileged",
            setting_label="Privileged container mode",
            category="Platform & Container Security",
            value=bool(container.get("privileged")),
            observed_at=observed_at,
            snapshot_type="runtime",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=asset_id,
            setting_key="container.image_digest",
            setting_label="Image digest",
            category="Platform & Container Security",
            value=container.get("digest"),
            observed_at=observed_at,
            snapshot_type="runtime",
            snapshot_id=snapshot_id,
            source=source,
        )
        image_ref = str(container.get("image") or "")
        mutable_tag = image_ref.endswith(":latest") or (":" not in image_ref and bool(image_ref))
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=asset_id,
            setting_key="container.mutable_image_tag",
            setting_label="Mutable image tag in use",
            category="Software Supply Chain",
            value=mutable_tag,
            observed_at=observed_at,
            snapshot_type="runtime",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=asset_id,
            setting_key="container.published_ports",
            setting_label="Published ports",
            category="Boundary & Session Security",
            value=container.get("published_ports") or [],
            observed_at=observed_at,
            snapshot_type="runtime",
            snapshot_id=snapshot_id,
            source=source,
        )


async def _record_build_settings(
    db: AsyncSession,
    *,
    project_id: int,
    snapshot_id: int,
    component_assets: dict[str, int],
    payload: dict[str, Any],
    source: str,
    observed_at: datetime,
) -> None:
    supply_chain = payload.get("software_supply_chain") or {}
    npm_counts = ((supply_chain.get("npm_audit") or {}).get("counts") or {})
    pip_counts = ((supply_chain.get("pip_audit") or {}).get("counts") or {})
    docker_scout = supply_chain.get("docker_scout") or {}

    frontend_asset_id = component_assets.get("frontend")
    backend_asset_id = component_assets.get("backend")
    image_asset_id = component_assets.get("images")

    if frontend_asset_id:
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=frontend_asset_id,
            setting_key="scan.frontend_dependency_scan_available",
            setting_label="Frontend dependency scanning available",
            category="Software Supply Chain",
            value=bool((supply_chain.get("npm_audit") or {}).get("available")),
            observed_at=observed_at,
            snapshot_type="build",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=frontend_asset_id,
            setting_key="scan.frontend_dependency_vuln_count",
            setting_label="Frontend dependency vulnerability count",
            category="Software Supply Chain",
            value=int(npm_counts.get("total") or 0),
            observed_at=observed_at,
            snapshot_type="build",
            snapshot_id=snapshot_id,
            source=source,
        )
    if backend_asset_id:
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=backend_asset_id,
            setting_key="scan.backend_dependency_vuln_count",
            setting_label="Backend dependency vulnerability count",
            category="Software Supply Chain",
            value=int(pip_counts.get("total") or 0),
            observed_at=observed_at,
            snapshot_type="build",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=backend_asset_id,
            setting_key="scan.backend_dependency_scan_available",
            setting_label="Backend dependency scanning available",
            category="Software Supply Chain",
            value=bool((supply_chain.get("pip_audit") or {}).get("available")),
            observed_at=observed_at,
            snapshot_type="build",
            snapshot_id=snapshot_id,
            source=source,
        )
    if image_asset_id:
        total_image_findings = sum(int((item or {}).get("finding_count") or 0) for item in (docker_scout.get("images") or []))
        inventory_available = bool(((docker_scout.get("inventory") or {}).get("available")))
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=image_asset_id,
            setting_key="scan.image_scan_available",
            setting_label="Container image scanning available",
            category="Software Supply Chain",
            value=bool(docker_scout.get("available") or inventory_available),
            observed_at=observed_at,
            snapshot_type="build",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=image_asset_id,
            setting_key="scan.image_vuln_count",
            setting_label="Container image vulnerability count",
            category="Software Supply Chain",
            value=total_image_findings,
            observed_at=observed_at,
            snapshot_type="build",
            snapshot_id=snapshot_id,
            source=source,
        )
        await _record_setting(
            db,
            project_id=project_id,
            asset_id=image_asset_id,
            setting_key="scan.image_scan_authenticated",
            setting_label="Container image scanning authenticated",
            category="Software Supply Chain",
            value=bool(docker_scout.get("available") and docker_scout.get("authenticated")),
            observed_at=observed_at,
            snapshot_type="build",
            snapshot_id=snapshot_id,
            source=source,
        )


async def _compute_security_score(project_id: int, db: AsyncSession) -> dict[str, int]:
    recommendations = (
        await db.execute(
            select(SecurityRecommendation).where(SecurityRecommendation.project_id == project_id)
        )
    ).scalars().all()
    max_points = sum(max(rec.score_impact, 1) for rec in recommendations) or 1
    lost_points = sum(max(rec.score_impact, 1) for rec in recommendations if rec.status != "completed")
    earned_points = max(max_points - lost_points, 0)
    return {
        "percentage": round((earned_points / max_points) * 100),
        "earned_points": earned_points,
        "total_points": max_points,
    }


async def register_security_collector(
    db: AsyncSession,
    *,
    project_id: int,
    name: str,
    collector_type: str,
    created_by: int | None,
    metadata_json: dict | None = None,
) -> dict[str, Any]:
    secret = secrets.token_urlsafe(32)
    collector = SecurityCollector(
        project_id=project_id,
        name=name,
        collector_type=collector_type,
        status="active",
        secret_encrypted=_encrypt_secret(secret),
        metadata_json=metadata_json or {},
        created_by=created_by,
    )
    db.add(collector)
    await db.commit()
    await db.refresh(collector)
    return {
        "id": collector.id,
        "project_id": collector.project_id,
        "name": collector.name,
        "collector_type": collector.collector_type,
        "status": collector.status,
        "secret": secret,
        "created_at": collector.created_at.isoformat() if collector.created_at else None,
    }


async def rotate_security_collector_secret(
    db: AsyncSession,
    *,
    project_id: int,
    collector_id: int,
) -> dict[str, Any] | None:
    collector = await db.get(SecurityCollector, collector_id)
    if not collector or collector.project_id != project_id:
        return None
    secret = secrets.token_urlsafe(32)
    collector.secret_encrypted = _encrypt_secret(secret)
    collector.updated_at = datetime.now(UTC)
    await db.execute(
        update(SecurityCollectorNonce)
        .where(SecurityCollectorNonce.collector_id == collector_id)
        .values(seen_at=datetime.now(UTC))
    )
    await db.commit()
    return {
        "id": collector.id,
        "name": collector.name,
        "collector_type": collector.collector_type,
        "status": collector.status,
        "secret": secret,
    }


async def list_security_collectors(project_id: int, db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(SecurityCollector)
            .where(SecurityCollector.project_id == project_id)
            .order_by(SecurityCollector.created_at.desc(), SecurityCollector.id.desc())
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "collector_type": row.collector_type,
            "status": row.status,
            "metadata": row.metadata_json or {},
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


async def verify_security_ingest_signature(
    db: AsyncSession,
    *,
    project_id: int,
    collector_id: int,
    timestamp: str,
    nonce: str,
    signature: str,
    body: bytes,
) -> SecurityCollector | None:
    collector = await db.get(SecurityCollector, collector_id)
    if not collector or collector.project_id != project_id or collector.status != "active":
        return None

    parsed_ts = _parse_iso_timestamp(timestamp)
    now = datetime.now(UTC)
    if parsed_ts < now - timedelta(minutes=5) or parsed_ts > now + timedelta(minutes=5):
        return None

    existing_nonce = (
        await db.execute(
            select(SecurityCollectorNonce.id).where(
                SecurityCollectorNonce.collector_id == collector_id,
                SecurityCollectorNonce.nonce == nonce,
            )
        )
    ).scalar_one_or_none()
    if existing_nonce:
        return None

    expected = hmac.new(
        _decrypt_secret(collector.secret_encrypted).encode("utf-8"),
        _signature_message(timestamp, nonce, body),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None

    db.add(SecurityCollectorNonce(collector_id=collector_id, nonce=nonce))
    await db.execute(
        update(SecurityCollectorNonce)
        .where(SecurityCollectorNonce.seen_at < now - timedelta(days=2))
        .values(seen_at=SecurityCollectorNonce.seen_at)
    )
    collector.last_seen_at = now
    return collector


async def _upsert_asset(
    db: AsyncSession,
    *,
    project_id: int,
    asset_type: str,
    name: str,
    external_id: str | None,
    criticality: str,
    metadata_json: dict | None,
) -> int:
    stmt = insert(SecurityAsset).values(
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        external_id=external_id,
        criticality=criticality,
        metadata_json=metadata_json or {},
        last_seen_at=datetime.now(UTC),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["project_id", "asset_type", "name"],
        set_={
            "external_id": stmt.excluded.external_id,
            "criticality": stmt.excluded.criticality,
            "metadata_json": stmt.excluded.metadata_json,
            "last_seen_at": stmt.excluded.last_seen_at,
            "updated_at": datetime.now(UTC),
        },
    ).returning(SecurityAsset.id)
    return int((await db.execute(stmt)).scalar_one())


def _fact(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": _summarize_value(value)}


def _compact_json_loads(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1])
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def _fallback_guidance(title: str, contract: dict[str, Any]) -> dict[str, Any]:
    fix_steps = contract.get("fix_steps") or []
    verification_checks = contract.get("verification_checks") or []
    why_it_matters = contract.get("why_it_matters") or contract.get("operator_summary") or title
    return {
        "operator_summary_text": contract.get("operator_summary") or why_it_matters,
        "why_it_matters_text": why_it_matters,
        "fix_steps_text": " ".join(f"{idx + 1}. {step}" for idx, step in enumerate(fix_steps[:4])) if fix_steps else "Review the finding and remediate the underlying issue.",
        "verification_text": " ".join(f"{idx + 1}. {step}" for idx, step in enumerate(verification_checks[:4])) if verification_checks else "Re-run the relevant collector or scan and confirm the issue is no longer reported.",
        "source": "deterministic",
    }


def _detail_contract(
    *,
    finding_type: str,
    source_scope: str,
    operator_summary: str,
    why_it_matters: str,
    observed: list[dict[str, str]] | None = None,
    expected: list[dict[str, str]] | None = None,
    evidence: list[dict[str, str]] | None = None,
    fix_steps: list[str] | None = None,
    verification_checks: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "finding_type": finding_type,
        "source_scope": source_scope,
        "operator_summary": operator_summary,
        "why_it_matters": why_it_matters,
        # Keep explicit "none" values because they are often the whole point of a security finding
        # (for example: no dropped capabilities, no healthcheck, no MFA coverage).
        "observed": [item for item in (observed or []) if item.get("value") != ""],
        "expected": [item for item in (expected or []) if item.get("value") != ""],
        "evidence": [item for item in (evidence or []) if item.get("value") != ""],
        "fix_steps": [item for item in (fix_steps or []) if item],
        "verification_checks": [item for item in (verification_checks or []) if item],
        "history": [item for item in (history or []) if item.get("value") not in {"", "none"}],
    }


async def _generate_contract_guidance(
    db: AsyncSession,
    *,
    title: str,
    severity: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    cache_key = _value_hash({"title": title, "severity": severity, "contract": contract})
    cached = _GUIDANCE_CACHE.get(cache_key)
    if cached:
        return cached

    fallback = _fallback_guidance(title, contract)
    try:
        provider, runtime = await build_provider_for_purpose(db, purpose="chat_general")
        system_prompt = (
            "You are a cybersecurity remediation assistant. "
            "You will receive a structured security finding contract. "
            "Do not invent facts. Use only the provided structured evidence. "
            "Return strict JSON with keys: operator_summary_text, why_it_matters_text, fix_steps_text, verification_text."
        )
        user_prompt = json.dumps(
            {
                "title": title,
                "severity": severity,
                "contract": contract,
            },
            default=str,
        )
        raw = await provider.complete(system_prompt, user_prompt)
        parsed = _compact_json_loads(raw)
        if parsed:
            guidance = {
                "operator_summary_text": str(parsed.get("operator_summary_text") or fallback["operator_summary_text"]).strip(),
                "why_it_matters_text": str(parsed.get("why_it_matters_text") or fallback["why_it_matters_text"]).strip(),
                "fix_steps_text": str(parsed.get("fix_steps_text") or fallback["fix_steps_text"]).strip(),
                "verification_text": str(parsed.get("verification_text") or fallback["verification_text"]).strip(),
                "source": f"llm:{runtime.provider}:{runtime.model}",
            }
            _GUIDANCE_CACHE[cache_key] = guidance
            return guidance
    except Exception:
        pass

    _GUIDANCE_CACHE[cache_key] = fallback
    return fallback


async def _finalize_finding_metadata(
    db: AsyncSession,
    *,
    title: str,
    severity: str,
    metadata: dict[str, Any],
    snapshot_kind: str,
    observed_at: datetime,
    snapshot_label: str | None = None,
) -> dict[str, Any]:
    contract = dict(metadata.get("detail_contract") or {})
    history = list(contract.get("history") or [])
    history.extend(
        [
            _fact("Snapshot", snapshot_kind),
            _fact("Observed at", observed_at.isoformat()),
        ]
    )
    if snapshot_label:
        history.append(_fact("Snapshot label", snapshot_label))
    if metadata.get("asset_name"):
        history.append(_fact("Asset", metadata.get("asset_name")))
    contract["history"] = [item for item in history if item.get("value") not in {"", "none"}]
    contract["generated_guidance"] = await _generate_contract_guidance(
        db,
        title=title,
        severity=severity,
        contract=contract,
    )
    metadata["detail_contract"] = contract
    metadata["finding_type"] = contract.get("finding_type") or metadata.get("finding_type") or metadata.get("category")
    metadata["generated_guidance"] = contract["generated_guidance"]
    return metadata


def _finding(
    *,
    finding_type: str,
    category: str,
    severity: str,
    title: str,
    recommendation_key: str,
    recommendation_title: str,
    domain: str,
    score_impact: int,
    action: str,
    summary: str,
    asset_name: str | None = None,
    fix_available: bool = True,
    cvss: float | None = None,
    source_scope: str = "live",
    observed: list[dict[str, str]] | None = None,
    expected: list[dict[str, str]] | None = None,
    evidence: list[dict[str, str]] | None = None,
    fix_steps: list[str] | None = None,
    verification_checks: list[str] | None = None,
    why_it_matters: str | None = None,
    history: list[dict[str, str]] | None = None,
    metadata_json: dict | None = None,
) -> dict[str, Any]:
    detail_contract = _detail_contract(
        finding_type=finding_type,
        source_scope=source_scope,
        operator_summary=summary,
        why_it_matters=why_it_matters or summary,
        observed=observed,
        expected=expected,
        evidence=evidence,
        fix_steps=fix_steps,
        verification_checks=verification_checks,
        history=history,
    )
    return {
        "finding_type": finding_type,
        "category": category,
        "severity": severity,
        "title": title,
        "status": "open",
        "fix_available": fix_available,
        "cvss": cvss,
        "metadata_json": {
            "recommendation_key": recommendation_key,
            "recommendation_title": recommendation_title,
            "domain": domain,
            "score_impact": score_impact,
            "action": action,
            "summary": summary,
            "asset_name": asset_name,
            "detail_contract": detail_contract,
            "finding_type": finding_type,
            **(metadata_json or {}),
        },
    }


def _build_findings_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    host = payload.get("host") or {}

    def _container_record(container: dict[str, Any]) -> dict[str, str]:
        ports = container.get("published_ports") or []
        return {
            "title": container.get("name") or "container",
            "subtitle": " | ".join(
                [
                    container.get("image") or "unknown image",
                    f"user={container.get('config_user') or container.get('pid1_uid') or 'unknown'}",
                    f"ports={', '.join(ports) if ports else 'none'}",
                ]
            ),
        }

    for container in payload.get("containers") or []:
        name = container.get("name") or "container"
        container_record = _container_record(container)
        if not container.get("non_root", False):
            findings.append(_finding(
                finding_type="container_runs_as_root",
                category="container_hardening",
                severity="high",
                title=f"{name} runs as root",
                recommendation_key="containers_non_root",
                recommendation_title="Run application containers as non-root",
                domain="Platform & Container Security",
                score_impact=12,
                action="Set an explicit non-root USER in the image and verify the runtime uses it.",
                summary="Root containers increase blast radius if the service is compromised.",
                asset_name=name,
                source_scope="live",
                observed=[_fact("Runs as non-root", "no"), _fact("Image", container.get("image") or "unknown")],
                expected=[_fact("Runs as non-root", "yes")],
                evidence=[_fact("Asset", name), _fact("Collector signal", "non_root=false")],
                fix_steps=[
                    "Set an explicit non-root USER in the image or runtime configuration.",
                    "Redeploy the service after the image or compose update.",
                ],
                verification_checks=[
                    "Collector reports runs as non-root = yes for this container.",
                    "Service remains healthy after the runtime change.",
                ],
                why_it_matters="A root container increases the blast radius of application compromise and weakens host isolation.",
                metadata_json={"records": [container_record]},
            ))
        if not container.get("read_only_rootfs", False):
            findings.append(_finding(
                finding_type="container_writable_rootfs",
                category="container_hardening",
                severity="medium",
                title=f"{name} has a writable root filesystem",
                recommendation_key="containers_read_only",
                recommendation_title="Use read-only root filesystems for containers",
                domain="Platform & Container Security",
                score_impact=8,
                action="Enable read-only root filesystems and mount only explicit writable paths if needed.",
                summary="Writable container filesystems make persistence and tampering easier.",
                asset_name=name,
                source_scope="live",
                observed=[_fact("Read-only root filesystem", "no")],
                expected=[_fact("Read-only root filesystem", "yes")],
                evidence=[_fact("Asset", name), _fact("Collector signal", "read_only_rootfs=false")],
                fix_steps=[
                    "Enable a read-only root filesystem for the container.",
                    "Mount only the explicit writable paths the service actually needs.",
                ],
                verification_checks=[
                    "Collector reports read-only root filesystem = yes.",
                    "Container still starts and writes only to approved mounted paths.",
                ],
                why_it_matters="Writable root filesystems make persistence, tampering, and post-compromise tooling easier.",
                metadata_json={"records": [container_record]},
            ))
        if container.get("privileged", False):
            findings.append(_finding(
                finding_type="container_privileged_mode",
                category="container_hardening",
                severity="critical",
                title=f"{name} is running in privileged mode",
                recommendation_key="containers_privileged",
                recommendation_title="Remove privileged container mode",
                domain="Platform & Container Security",
                score_impact=20,
                action="Remove privileged mode and replace it with minimal explicit capabilities only if required.",
                summary="Privileged containers substantially weaken host isolation.",
                asset_name=name,
                cvss=9.0,
                source_scope="live",
                observed=[_fact("Privileged mode", "yes")],
                expected=[_fact("Privileged mode", "no")],
                evidence=[_fact("Asset", name), _fact("Collector signal", "privileged=true")],
                fix_steps=[
                    "Remove privileged mode from the container runtime definition.",
                    "Replace it with the minimum explicit capabilities and mounts required.",
                ],
                verification_checks=[
                    "Collector reports privileged mode = no.",
                    "Service still functions after least-privilege runtime hardening.",
                ],
                why_it_matters="Privileged containers substantially reduce isolation from the host and create high-impact escape paths.",
                metadata_json={"records": [container_record]},
            ))
        if container.get("published_ports"):
            non_local = [port for port in container.get("published_ports") or [] if not str(port).startswith("127.0.0.1:")]
            if non_local:
                findings.append(_finding(
                    finding_type="container_non_local_port_exposure",
                    category="network_exposure",
                    severity="high",
                    title=f"{name} exposes non-local published ports",
                    recommendation_key="containers_port_exposure",
                    recommendation_title="Restrict container port exposure",
                    domain="Boundary & Session Security",
                    score_impact=10,
                    action="Bind services to localhost or place them behind an explicitly approved ingress boundary.",
                    summary="Container ports exposed beyond localhost broaden attack surface.",
                    asset_name=name,
                    source_scope="live",
                    observed=[_fact("Exposed ports", ", ".join(non_local))],
                    expected=[_fact("Published ports", "localhost only or approved ingress")],
                    evidence=[_fact("Asset", name), _fact("Exposed port count", len(non_local))],
                    fix_steps=[
                        "Bind ports to localhost or place the service behind an approved ingress boundary.",
                        "Remove any published ports that are not required.",
                    ],
                    verification_checks=[
                        "Collector reports no non-local published ports for this service.",
                        "Service remains reachable only through the approved boundary.",
                    ],
                    why_it_matters="Non-local published ports broaden attack surface and can bypass expected ingress controls.",
                    metadata_json={"ports": non_local, "records": [container_record]},
                ))
        if not container.get("cap_drop"):
            findings.append(_finding(
                finding_type="container_missing_cap_drop",
                category="container_hardening",
                severity="medium",
                title=f"{name} does not drop Linux capabilities",
                recommendation_key="containers_drop_caps",
                recommendation_title="Drop unnecessary container capabilities",
                domain="Platform & Container Security",
                score_impact=6,
                action="Use cap_drop and no-new-privileges where possible to reduce runtime privileges.",
                summary="Default container capabilities leave more privilege than most services need.",
                asset_name=name,
                source_scope="live",
                observed=[_fact("Dropped Linux capabilities", "none")],
                expected=[_fact("Dropped Linux capabilities", "ALL or minimum required set")],
                evidence=[_fact("Asset", name), _fact("Collector signal", "cap_drop=[]")],
                fix_steps=[
                    "Set cap_drop to ALL, then add back only the minimal capabilities the service truly needs.",
                    "Use no-new-privileges where supported by the runtime.",
                ],
                verification_checks=[
                    "Collector reports a non-empty cap_drop configuration.",
                    "Service remains healthy with the reduced capability set.",
                ],
                why_it_matters="Default Linux capabilities leave more privilege than most services need and increase post-compromise blast radius.",
                metadata_json={"records": [container_record]},
            ))
        if not container.get("healthcheck"):
            findings.append(_finding(
                finding_type="container_missing_healthcheck",
                category="runtime_observability",
                severity="low",
                title=f"{name} has no container healthcheck",
                recommendation_key="container_healthchecks",
                recommendation_title="Add container healthchecks to runtime services",
                domain="Monitoring & Audit",
                score_impact=4,
                action="Define healthchecks for runtime services so failures and stuck containers are detected faster.",
                summary="Without container healthchecks, unhealthy services are harder to detect automatically.",
                asset_name=name,
                source_scope="live",
                observed=[_fact("Healthcheck configured", "no")],
                expected=[_fact("Healthcheck configured", "yes")],
                evidence=[_fact("Asset", name), _fact("Collector signal", "healthcheck=false")],
                fix_steps=[
                    "Add a runtime healthcheck that verifies the service is actually responsive.",
                    "Ensure the healthcheck is specific enough to detect stuck or degraded states.",
                ],
                verification_checks=[
                    "Collector reports healthcheck configured = yes.",
                    "Runtime marks the container healthy when the service is actually working.",
                ],
                why_it_matters="Missing healthchecks make runtime failures harder to detect and reduce confidence in service health evidence.",
                metadata_json={"records": [container_record]},
            ))
        image_ref = str(container.get("image") or "")
        if image_ref and (image_ref.endswith(":latest") or ":" not in image_ref):
            findings.append(_finding(
                finding_type="mutable_image_tag",
                category="image_traceability",
                severity="medium",
                title=f"{name} uses a mutable image tag",
                recommendation_key="immutable_image_tags",
                recommendation_title="Pin runtime containers to immutable image references",
                domain="Software Supply Chain",
                score_impact=7,
                action="Pin containers to digests or immutable version tags so runtime provenance and rollback are reliable.",
                summary="Mutable image tags make it harder to prove exactly what is running and when it changed.",
                asset_name=name,
                source_scope="live",
                observed=[_fact("Image reference", image_ref)],
                expected=[_fact("Image reference", "immutable digest or fixed version tag")],
                evidence=[_fact("Asset", name), _fact("Mutable image tag", "yes")],
                fix_steps=[
                    "Pin the service to an immutable image digest or fixed version tag.",
                    "Update the deployment workflow to preserve artifact provenance for each release.",
                ],
                verification_checks=[
                    "Collector reports a fixed tag or digest-backed image reference.",
                    "Build and runtime evidence point to the same immutable artifact.",
                ],
                why_it_matters="Mutable tags weaken provenance and make it harder to prove exactly which artifact is running.",
                metadata_json={"image": image_ref, "records": [container_record]},
            ))

    patch = payload.get("patch_posture") or {}
    missing_updates = int(patch.get("missing_security_updates") or 0)
    host_record = {
        "title": host.get("hostname") or "current host",
        "subtitle": " | ".join(
            [
                host.get("os_version") or host.get("platform") or "unknown platform",
                f"missing_updates={missing_updates}",
                f"reboot_required={'yes' if patch.get('reboot_required') else 'no'}",
            ]
        ),
    }
    if missing_updates > 0:
        findings.append(_finding(
            finding_type="host_missing_security_updates",
            category="patching",
            severity="high" if missing_updates >= 10 else "medium",
            title="Host has missing security updates",
            recommendation_key="host_patching",
            recommendation_title="Patch the host and reduce security update backlog",
            domain="Host Patching",
            score_impact=14,
            action="Coordinate host-level patching outside ATO Bot and verify the collector reports the reduced backlog afterward.",
            summary=f"{missing_updates} security update(s) are missing on the host.",
            asset_name=host.get("hostname"),
            source_scope="live",
            observed=[_fact("Missing security updates", missing_updates)],
            expected=[_fact("Missing security updates", 0)],
            evidence=[
                _fact("Host", host.get("hostname") or "current host"),
                _fact("Patch backlog", missing_updates),
                _fact("Remediation scope", "host administrator / external to ATO Bot app"),
            ],
            fix_steps=[
                "Apply the missing security updates on the host that runs ATO Bot by using the host OS patching process.",
                "Review host patch cadence so security updates are applied consistently outside the application deployment.",
            ],
            verification_checks=[
                "Collector reports missing security updates = 0 or reduced as expected.",
                "Any required reboot is completed after patching.",
            ],
            why_it_matters="Missing security updates leave the host exposed to known vulnerabilities and weaken confidence in runtime posture, even though the remediation happens outside the ATO Bot application itself.",
            metadata_json={
                "missing_security_updates": missing_updates,
                "records": [host_record],
                "external_remediation": True,
                "remediation_scope": "host",
            },
        ))
    if patch.get("reboot_required"):
        findings.append(_finding(
            finding_type="host_reboot_required",
            category="patching",
            severity="medium",
            title="Host requires a reboot to complete patching",
            recommendation_key="host_reboot",
            recommendation_title="Reboot the host after security updates",
            domain="Host Patching",
            score_impact=5,
            action="Schedule the required host reboot outside ATO Bot so security updates fully take effect.",
            summary="Pending reboots leave patch posture incomplete.",
            asset_name=host.get("hostname"),
            source_scope="live",
            observed=[_fact("Reboot required", "yes")],
            expected=[_fact("Reboot required", "no")],
            evidence=[
                _fact("Host", host.get("hostname") or "current host"),
                _fact("Remediation scope", "host administrator / external to ATO Bot app"),
            ],
            fix_steps=[
                "Schedule and complete the required reboot through the host administration process.",
                "Validate that patch installation completes successfully after the reboot.",
            ],
            verification_checks=[
                "Collector reports reboot required = no.",
                "Host services return to a healthy state after the reboot.",
            ],
            why_it_matters="Pending reboot state means some security updates are not fully in effect yet, and the remediation occurs at the host administration layer rather than inside ATO Bot.",
            metadata_json={"records": [host_record], "external_remediation": True, "remediation_scope": "host"},
        ))

    app_security = payload.get("app_security") or {}
    if int(app_security.get("privileged_accounts_without_mfa") or 0) > 0:
        findings.append(_finding(
            finding_type="privileged_accounts_missing_mfa",
            category="identity",
            severity="high",
            title="Privileged accounts without MFA remain",
            recommendation_key="privileged_mfa",
            recommendation_title="Enforce MFA for privileged users",
            domain="Identity & Access",
            score_impact=15,
            action="Require MFA for every privileged ATO Bot account before relying on the system for security evidence.",
            summary="Privileged access without MFA is one of the highest-value attack paths to close.",
            source_scope="live",
            observed=[_fact("Privileged accounts without MFA", int(app_security.get("privileged_accounts_without_mfa") or 0))],
            expected=[_fact("Privileged accounts without MFA", 0)],
            evidence=[_fact("Identity control", "privileged MFA enforcement")],
            fix_steps=[
                "Require MFA for every privileged and administrative account.",
                "Validate that emergency and assessor paths are covered by the same control.",
            ],
            verification_checks=[
                "Collector reports privileged accounts without MFA = 0.",
                "Administrative sign-in policy shows MFA is enforced.",
            ],
            why_it_matters="Privileged access without MFA remains one of the highest-value attack paths to close.",
            metadata_json={"privileged_accounts_without_mfa": int(app_security.get("privileged_accounts_without_mfa") or 0)},
        ))
    if int(app_security.get("failed_ingestion_24h") or 0) > 0 or int(app_security.get("failed_assessments_7d") or 0) > 0:
        findings.append(_finding(
            finding_type="monitoring_pipeline_failures",
            category="monitoring_pipeline",
            severity="medium",
            title="Security monitoring pipeline has recent failures",
            recommendation_key="monitoring_pipeline",
            recommendation_title="Stabilize the security monitoring pipeline",
            domain="Monitoring & Audit",
            score_impact=10,
            action="Investigate recent ingestion and assessment failures so monitoring evidence stays trustworthy.",
            summary="Repeated failures in evidence or assessment processing reduce confidence in continuous monitoring.",
            source_scope="live",
            observed=[
                _fact("Failed ingestion runs (24h)", int(app_security.get("failed_ingestion_24h") or 0)),
                _fact("Failed assessments (7d)", int(app_security.get("failed_assessments_7d") or 0)),
            ],
            expected=[
                _fact("Failed ingestion runs (24h)", 0),
                _fact("Failed assessments (7d)", 0),
            ],
            evidence=[_fact("Pipeline area", "ingestion and assessment processing")],
            fix_steps=[
                "Investigate and stabilize the failing pipeline stage.",
                "Re-run the failed jobs and confirm telemetry and assessments complete cleanly.",
            ],
            verification_checks=[
                "Collector reports failed ingestion and failed assessments at zero or expected levels.",
                "Recent security evidence processing completes without errors.",
            ],
            why_it_matters="When the monitoring pipeline is failing, the security dashboard becomes less trustworthy.",
            metadata_json={
                "failed_ingestion_24h": int(app_security.get("failed_ingestion_24h") or 0),
                "failed_assessments_7d": int(app_security.get("failed_assessments_7d") or 0),
            },
        ))
    if int(app_security.get("unresolved_critical_events") or 0) > 0:
        findings.append(_finding(
            finding_type="critical_security_events_unresolved",
            category="alerts",
            severity="high",
            title="Critical security events remain unresolved",
            recommendation_key="critical_security_events",
            recommendation_title="Resolve critical security events",
            domain="Monitoring & Audit",
            score_impact=12,
            action="Triage or disposition critical security events to restore confidence in the alert backlog.",
            summary="Unresolved critical events are direct indicators of active or recent security risk.",
            source_scope="live",
            observed=[_fact("Unresolved critical events", int(app_security.get("unresolved_critical_events") or 0))],
            expected=[_fact("Unresolved critical events", 0)],
            evidence=[_fact("Alert backlog", "critical")],
            fix_steps=[
                "Triage the unresolved critical events and assign disposition or remediation.",
                "Confirm the backlog no longer contains unreviewed critical items.",
            ],
            verification_checks=[
                "Collector reports unresolved critical events = 0 or the accepted target value.",
                "Critical alerts are either resolved or formally risk-accepted.",
            ],
            why_it_matters="Unresolved critical events indicate active or recent security risk that still needs operator action.",
            metadata_json={"unresolved_critical_events": int(app_security.get("unresolved_critical_events") or 0)},
        ))
    supply_chain = payload.get("software_supply_chain") or {}
    npm_audit = supply_chain.get("npm_audit") or {}
    npm_counts = npm_audit.get("counts") or {}
    if npm_audit.get("available") and int(npm_counts.get("total") or 0) > 0:
        npm_packages = npm_audit.get("packages") or []
        findings.append(_finding(
            finding_type="frontend_dependency_vulnerabilities",
            category="dependency_vulnerability",
            severity="critical" if int(npm_counts.get("critical") or 0) > 0 else "high" if int(npm_counts.get("high") or 0) > 0 else "medium",
            title="Frontend dependencies have known vulnerabilities",
            recommendation_key="frontend_dependency_vulns",
            recommendation_title="Remediate vulnerable frontend dependencies",
            domain="Software Supply Chain",
            score_impact=14,
            action="Review npm audit results, upgrade vulnerable packages, and rebuild the frontend dependency tree.",
            summary=f"{int(npm_counts.get('total') or 0)} frontend vulnerability finding(s) across {len(npm_packages)} package(s) were reported.",
            asset_name="atobot_frontend",
            source_scope="build",
            observed=[_fact("Vulnerabilities reported", int(npm_counts.get("total") or 0)), _fact("Affected packages", len(npm_packages))],
            expected=[_fact("Vulnerabilities reported", 0)],
            evidence=[_fact("Asset", "atobot_frontend"), _fact("Scanner", "npm audit")],
            fix_steps=[
                "Upgrade or replace the vulnerable frontend packages.",
                "Rebuild the frontend dependency tree and retest the build.",
            ],
            verification_checks=[
                "The next build snapshot reports zero or reduced frontend dependency vulnerabilities.",
                "Affected packages are upgraded to fixed versions where available.",
            ],
            why_it_matters="Known vulnerable frontend dependencies increase the chance of shipping exploitable client-side code.",
            metadata_json={
                "counts": npm_counts,
                "detail": npm_audit.get("detail"),
                "packages": npm_packages,
                "vulnerabilities": npm_audit.get("vulnerabilities") or [],
                "ecosystem": "npm",
            },
        ))
    elif not npm_audit.get("available"):
        findings.append(_finding(
            finding_type="frontend_dependency_scan_missing",
            category="scan_coverage",
            severity="medium",
            title="Frontend dependency vulnerability scanning is not configured",
            recommendation_key="frontend_dependency_scan_coverage",
            recommendation_title="Enable frontend dependency vulnerability scanning",
            domain="Software Supply Chain",
            score_impact=8,
            action="Run npm audit or an equivalent dependency scanner in the build snapshot workflow so frontend package risk is measured every build.",
            summary="Without frontend dependency scanning, the dashboard cannot assert whether shipped JavaScript packages are vulnerable.",
            asset_name="atobot_frontend",
            source_scope="build",
            observed=[_fact("Frontend dependency scanning", "not configured")],
            expected=[_fact("Frontend dependency scanning", "enabled on every build")],
            evidence=[_fact("Asset", "atobot_frontend")],
            fix_steps=[
                "Add npm audit or an equivalent dependency scanner to the build workflow.",
                "Store the scan output with each build snapshot.",
            ],
            verification_checks=[
                "The next build snapshot reports frontend dependency scanning available = yes.",
                "The dashboard includes package-level frontend vulnerability detail when issues exist.",
            ],
            why_it_matters="Without frontend dependency scanning, you cannot prove whether shipped JavaScript packages are vulnerable.",
            metadata_json={"detail": npm_audit.get("detail")},
        ))
    pip_audit = supply_chain.get("pip_audit") or {}
    pip_counts = pip_audit.get("counts") or {}
    if pip_audit.get("available") and int(pip_counts.get("total") or 0) > 0:
        pip_packages = pip_audit.get("packages") or []
        findings.append(_finding(
            finding_type="backend_dependency_vulnerabilities",
            category="dependency_vulnerability",
            severity="high",
            title="Backend Python dependencies have known vulnerabilities",
            recommendation_key="backend_dependency_vulns",
            recommendation_title="Remediate vulnerable backend dependencies",
            domain="Software Supply Chain",
            score_impact=14,
            action="Review pip-audit results, upgrade vulnerable Python packages, and retest the backend runtime.",
            summary=f"{int(pip_counts.get('total') or 0)} backend vulnerability finding(s) across {len(pip_packages)} package(s) were reported.",
            asset_name="atobot_backend",
            source_scope="build",
            observed=[_fact("Vulnerabilities reported", int(pip_counts.get("total") or 0)), _fact("Affected packages", len(pip_packages))],
            expected=[_fact("Vulnerabilities reported", 0)],
            evidence=[_fact("Asset", "atobot_backend"), _fact("Scanner", "pip-audit")],
            fix_steps=[
                "Upgrade or replace the vulnerable backend Python packages.",
                "Rebuild and retest the backend after dependency updates.",
            ],
            verification_checks=[
                "The next build snapshot reports zero or reduced backend dependency vulnerabilities.",
                "Affected packages are upgraded to fixed versions where available.",
            ],
            why_it_matters="Known vulnerable backend dependencies weaken the shipped software supply chain and runtime security posture.",
            metadata_json={
                "counts": pip_counts,
                "detail": pip_audit.get("detail"),
                "packages": pip_packages,
                "vulnerabilities": pip_audit.get("vulnerabilities") or [],
                "ecosystem": "pip",
            },
        ))
    elif not pip_audit.get("available"):
        findings.append(_finding(
            finding_type="backend_dependency_scan_missing",
            category="scan_coverage",
            severity="medium",
            title="Backend dependency vulnerability scanning is not configured",
            recommendation_key="backend_dependency_scan_coverage",
            recommendation_title="Enable backend dependency vulnerability scanning",
            domain="Software Supply Chain",
            score_impact=8,
            action="Install and run pip-audit or an equivalent backend dependency scanner in the local collector workflow.",
            summary="Without backend dependency scanning, the dashboard cannot assert whether Python packages are vulnerable.",
            asset_name="atobot_backend",
            source_scope="build",
            observed=[_fact("Backend dependency scanning", "not configured")],
            expected=[_fact("Backend dependency scanning", "enabled on every build")],
            evidence=[_fact("Asset", "atobot_backend")],
            fix_steps=[
                "Add pip-audit or an equivalent dependency scanner to the build workflow.",
                "Store the scan output with each build snapshot.",
            ],
            verification_checks=[
                "The next build snapshot reports backend dependency scanning available = yes.",
                "The dashboard includes package-level backend vulnerability detail when issues exist.",
            ],
            why_it_matters="Without backend dependency scanning, you cannot prove whether shipped Python packages are vulnerable.",
            metadata_json={"detail": pip_audit.get("detail")},
        ))
    docker_scout = supply_chain.get("docker_scout") or {}
    inventory = docker_scout.get("inventory") or {}
    inventory_available = bool(inventory.get("available"))
    inventory_images = inventory.get("images") or []
    if docker_scout.get("available") and docker_scout.get("authenticated"):
        for image_item in docker_scout.get("images") or []:
            finding_count = int(image_item.get("finding_count") or 0)
            if finding_count <= 0:
                continue
            severity_counts = image_item.get("severity_counts") or {}
            image_record = {
                "title": image_item.get("image") or "container image",
                "subtitle": " | ".join(
                    [
                        f"findings={finding_count}",
                        f"critical={int(severity_counts.get('critical') or 0)}",
                        f"high={int(severity_counts.get('high') or 0)}",
                        f"medium={int(severity_counts.get('medium') or 0)}",
                    ]
                ),
            }
            findings.append(_finding(
                finding_type="container_image_vulnerabilities",
                category="image_vulnerability",
                severity="critical" if int(severity_counts.get("critical") or 0) > 0 else "high" if int(severity_counts.get("high") or 0) > 0 else "medium",
                title=f"Container image {image_item.get('image')} has known vulnerabilities",
                recommendation_key="container_image_vulns",
                recommendation_title="Remediate vulnerable container images",
                domain="Software Supply Chain",
                score_impact=16,
                action="Review Docker Scout image findings, refresh base images, and rebuild vulnerable container images.",
                summary=f"{finding_count} image vulnerability finding(s) were detected by Docker Scout.",
                asset_name=image_item.get("image"),
                source_scope="build",
                observed=[_fact("Image vulnerability findings", finding_count)],
                expected=[_fact("Image vulnerability findings", 0)],
                evidence=[_fact("Image", image_item.get("image") or "container image"), _fact("Scanner", "Docker Scout")],
                fix_steps=[
                    "Update the base image or rebuild the image with patched dependencies.",
                    "Re-scan the image before promotion.",
                ],
                verification_checks=[
                    "The next authenticated image scan reports zero or reduced image vulnerabilities.",
                    "Updated image digest is reflected in the next build snapshot.",
                ],
                why_it_matters="Known vulnerable container images weaken the shipped artifact and runtime supply chain posture.",
                metadata_json={"severity_counts": severity_counts, "finding_count": finding_count, "records": [image_record]},
            ))
    elif inventory_available:
        image_records = [
            {
                "title": item.get("image") or "container image",
                "subtitle": " | ".join(
                    part
                    for part in [
                        f"container={item.get('container')}" if item.get("container") else "",
                        f"package_manager={item.get('package_manager')}" if item.get("package_manager") else "",
                        f"packages={int(item.get('package_count') or 0)}",
                    ]
                    if part
                ),
            }
            for item in inventory_images
        ][:10]
        findings.append(_finding(
            finding_type="image_scan_inventory_only",
            category="scan_coverage",
            severity="low",
            title="Container image coverage is limited to local package inventory",
            recommendation_key="container_image_inventory_coverage",
            recommendation_title="Add image vulnerability intelligence on top of local inventory",
            domain="Software Supply Chain",
            score_impact=4,
            action="Keep local image inventory collection enabled and add an authenticated or offline vulnerability advisory feed so image CVEs can be evaluated continuously.",
            summary=f"Local package inventory is available for {len(inventory_images)} image(s), but vulnerability intelligence is not available from the current scanner path.",
            source_scope="build",
            observed=[
                _fact("Coverage mode", "inventory only"),
                _fact("Inventoried images", len(inventory_images)),
            ],
            expected=[_fact("Coverage mode", "inventory plus vulnerability intelligence")],
            evidence=[
                _fact("Scanner", "Docker Scout"),
                _fact("Advisory feed", "unavailable"),
                _fact("Inventory fallback", "available"),
            ],
            fix_steps=[
                "Authenticate Docker Scout or integrate an offline image vulnerability feed that can run locally.",
                "Keep storing local image inventory so package-level evidence remains available even when CVE intelligence is unavailable.",
            ],
            verification_checks=[
                "The next build snapshot reports authenticated or offline-capable image vulnerability intelligence.",
                "Image findings include CVE-backed vulnerability records when issues exist.",
            ],
            why_it_matters="Local package inventory is better than no visibility, but it does not tell you which shipped image packages are currently vulnerable.",
            metadata_json={
                "detail": docker_scout.get("detail") or inventory.get("detail"),
                "records": image_records,
                "inventory_images": inventory_images[:10],
            },
        ))
    elif docker_scout.get("available") and not docker_scout.get("authenticated"):
        image_records = [
            {"title": item.get("image") or "container image", "subtitle": "Docker Scout requires authentication"}
            for item in payload.get("containers") or []
            if item.get("image")
        ][:10]
        findings.append(_finding(
            finding_type="image_scan_not_authenticated",
            category="scan_coverage",
            severity="medium",
            title="Container vulnerability scanning is not authenticated",
            recommendation_key="docker_scout_auth",
            recommendation_title="Enable authenticated container vulnerability scanning",
            domain="Software Supply Chain",
            score_impact=8,
            action="Authenticate Docker Scout or connect another image vulnerability scanner so container CVEs can be measured continuously.",
            summary="Container image scanning is installed locally but cannot return vulnerability data until it is authenticated.",
            source_scope="build",
            observed=[_fact("Image vulnerability scanning", "installed but unauthenticated")],
            expected=[_fact("Image vulnerability scanning", "authenticated and returning findings")],
            evidence=[_fact("Scanner", "Docker Scout")],
            fix_steps=[
                "Authenticate Docker Scout or configure another supported image scanner.",
                "Store image vulnerability results with each build snapshot.",
            ],
            verification_checks=[
                "The next build snapshot reports authenticated image scanning = yes.",
                "Image vulnerability findings appear when CVEs are present.",
            ],
            why_it_matters="Unauthenticated image scanning gives the appearance of coverage without returning the actual image CVE detail.",
            metadata_json={"detail": docker_scout.get("detail"), "records": image_records},
        ))
    elif not docker_scout.get("available"):
        image_records = [
            {"title": item.get("image") or "container image", "subtitle": "No image scan coverage configured"}
            for item in payload.get("containers") or []
            if item.get("image")
        ][:10]
        findings.append(_finding(
            finding_type="image_scan_missing",
            category="scan_coverage",
            severity="medium",
            title="Container image vulnerability scanning is not configured",
            recommendation_key="docker_image_scan_coverage",
            recommendation_title="Enable container image vulnerability scanning",
            domain="Software Supply Chain",
            score_impact=8,
            action="Add Docker Scout or another authenticated image scanner to the build snapshot workflow so image CVEs are measured every build.",
            summary="Without image vulnerability scanning, the dashboard cannot assert whether shipped container images have known CVEs.",
            source_scope="build",
            observed=[_fact("Image vulnerability scanning", "not configured")],
            expected=[_fact("Image vulnerability scanning", "enabled on every build")],
            evidence=[_fact("Artifact type", "container images")],
            fix_steps=[
                "Add an authenticated image scanner to the build workflow.",
                "Store image scan output with each build snapshot.",
            ],
            verification_checks=[
                "The next build snapshot reports image scanning available = yes.",
                "Container image findings appear with image, severity, and fix detail when issues exist.",
            ],
            why_it_matters="Without image vulnerability scanning, you cannot prove whether shipped container images have known CVEs.",
            metadata_json={"detail": docker_scout.get("detail"), "records": image_records},
        ))
    return findings


async def _rebuild_project_recommendations(project_id: int, db: AsyncSession) -> None:
    open_findings = (
        await db.execute(
            select(SecurityFinding).where(
                SecurityFinding.project_id == project_id,
                SecurityFinding.status == "open",
            )
        )
    ).scalars().all()

    grouped: dict[str, dict[str, Any]] = {}
    for item in open_findings:
        metadata = item.metadata_json or {}
        key = metadata.get("recommendation_key")
        if not key:
            continue
        current = grouped.setdefault(
            key,
            {
                "title": metadata.get("recommendation_title") or item.title,
                "domain": metadata.get("domain") or "Security",
                "severity": item.severity,
                "score_impact": int(metadata.get("score_impact") or 0),
                "summary": metadata.get("summary"),
                "action": metadata.get("action"),
                "count": 0,
                "assets": set(),
                "packages": [],
                "vulnerabilities": [],
                "findings": [],
                "fix_steps": [],
                "verification_checks": [],
                "source_scope": set(),
            },
        )
        current["count"] += 1
        current["severity"] = item.severity if _severity_rank(item.severity) > _severity_rank(current["severity"]) else current["severity"]
        asset_name = metadata.get("asset_name")
        if asset_name:
            current["assets"].add(asset_name)
        contract = (metadata.get("detail_contract") or {})
        if contract.get("source_scope"):
            current["source_scope"].add(contract.get("source_scope"))
        for step in contract.get("fix_steps") or []:
            if step not in current["fix_steps"]:
                current["fix_steps"].append(step)
        for step in contract.get("verification_checks") or []:
            if step not in current["verification_checks"]:
                current["verification_checks"].append(step)
        for package in metadata.get("packages") or []:
            if not any(existing.get("name") == package.get("name") for existing in current["packages"]):
                current["packages"].append(package)
        for vuln in metadata.get("vulnerabilities") or []:
            vuln_id = vuln.get("id") or vuln.get("title") or vuln.get("package")
            package_name = vuln.get("package") or vuln.get("name")
            if not any((existing.get("id") or existing.get("title")) == vuln_id and (existing.get("package") or existing.get("name")) == package_name for existing in current["vulnerabilities"]):
                current["vulnerabilities"].append(vuln)
        current["findings"].append(
            {
                "id": item.id,
                "title": item.title,
                "severity": item.severity,
                "asset_name": asset_name,
                "summary": metadata.get("summary"),
                "category": item.category,
            }
        )

    existing = (
        await db.execute(
            select(SecurityRecommendation).where(SecurityRecommendation.project_id == project_id)
        )
    ).scalars().all()
    existing_by_key = {row.key: row for row in existing}
    active_keys = set(grouped.keys())

    for key, item in grouped.items():
        detail_contract = _detail_contract(
            finding_type=f"recommendation::{key}",
            source_scope="both" if len(item["source_scope"]) > 1 else next(iter(item["source_scope"]), "evidence"),
            operator_summary=item["summary"] or item["title"],
            why_it_matters=item["summary"] or item["title"],
            observed=[
                _fact("Open findings", item["count"]),
                _fact("Affected assets", len(item["assets"])),
                _fact("Affected packages", len(item["packages"])),
            ],
            expected=[_fact("Open findings", 0)],
            evidence=[
                _fact("Domain", item["domain"]),
                _fact("Severity", item["severity"]),
            ],
            fix_steps=item["fix_steps"][:5] or ([item["action"]] if item["action"] else []),
            verification_checks=item["verification_checks"][:5],
        )
        generated_guidance = await _generate_contract_guidance(
            db,
            title=item["title"],
            severity=item["severity"],
            contract=detail_contract,
        )
        payload = {
            "count": item["count"],
            "affected_assets": sorted(item["assets"]),
            "packages": item["packages"][:25],
            "vulnerabilities": item["vulnerabilities"][:50],
            "findings": item["findings"][:10],
            "detail_contract": detail_contract,
            "generated_guidance": generated_guidance,
        }
        if key in existing_by_key:
            rec = existing_by_key[key]
            rec.title = item["title"]
            rec.domain = item["domain"]
            rec.severity = item["severity"]
            rec.score_impact = item["score_impact"]
            rec.status = _health_status(item["count"], item["severity"])
            rec.summary = item["summary"]
            rec.action = item["action"]
            rec.metadata_json = payload
            rec.updated_at = datetime.now(UTC)
        else:
            db.add(
                SecurityRecommendation(
                    project_id=project_id,
                    key=key,
                    title=item["title"],
                    domain=item["domain"],
                    severity=item["severity"],
                    score_impact=item["score_impact"],
                    status=_health_status(item["count"], item["severity"]),
                    summary=item["summary"],
                    action=item["action"],
                    metadata_json=payload,
                )
            )

    for key, rec in existing_by_key.items():
        if key not in active_keys:
            rec.status = "completed"
            rec.metadata_json = {"count": 0, "affected_assets": []}
            rec.updated_at = datetime.now(UTC)


async def ingest_security_payload(
    db: AsyncSession,
    *,
    project_id: int,
    collector: SecurityCollector,
    payload: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    source = f"collector:{collector.id}"
    scan = SecurityScan(
        project_id=project_id,
        collector_id=collector.id,
        source=source,
        scan_type=payload.get("scan_type") or "local_runtime",
        status="running",
        summary_json={"collected_at": payload.get("collected_at"), "collector_name": collector.name},
    )
    db.add(scan)
    await db.flush()
    runtime_snapshot = SecurityRuntimeSnapshot(
        project_id=project_id,
        collector_id=collector.id,
        source=source,
        collected_at=_parse_iso_timestamp(payload.get("collected_at") or now.isoformat()),
        summary_json={"collector_name": collector.name},
    )
    db.add(runtime_snapshot)
    await db.flush()

    host = payload.get("host") or {}
    host_asset_id = None
    if host.get("hostname"):
        host_asset_id = await _upsert_asset(
            db,
            project_id=project_id,
            asset_type="host",
            name=host["hostname"],
            external_id=host.get("hostname"),
            criticality="high",
            metadata_json=host,
        )

    container_asset_ids: dict[str, int] = {}
    for container in payload.get("containers") or []:
        name = container.get("name")
        if not name:
            continue
        container_asset_ids[name] = await _upsert_asset(
            db,
            project_id=project_id,
            asset_type="container",
            name=name,
            external_id=container.get("digest") or container.get("image"),
            criticality="high" if container.get("privileged") else "medium",
            metadata_json=container,
        )

    await _record_runtime_settings(
        db,
        project_id=project_id,
        snapshot_id=runtime_snapshot.id,
        host_asset_id=host_asset_id,
        host=host,
        container_asset_ids=container_asset_ids,
        payload=payload,
        source=source,
        observed_at=runtime_snapshot.collected_at,
    )

    await db.execute(
        update(SecurityFinding)
        .where(
            SecurityFinding.project_id == project_id,
            SecurityFinding.source == source,
            SecurityFinding.status == "open",
        )
        .values(status="resolved", resolved_at=now)
    )

    built_findings = _build_findings_from_payload(payload)
    finding_rows = 0
    for item in built_findings:
        metadata = await _finalize_finding_metadata(
            db,
            title=item["title"],
            severity=item["severity"],
            metadata=item["metadata_json"] or {},
            snapshot_kind="runtime",
            observed_at=runtime_snapshot.collected_at,
        )
        asset_name = metadata.get("asset_name")
        asset_id = container_asset_ids.get(asset_name) if asset_name in container_asset_ids else host_asset_id
        db.add(
            SecurityFinding(
                project_id=project_id,
                asset_id=asset_id,
                scan_id=scan.id,
                source=source,
                category=item["category"],
                severity=item["severity"],
                title=item["title"],
                status=item["status"],
                fix_available=item["fix_available"],
                cvss=item["cvss"],
                metadata_json=metadata,
            )
        )
        finding_rows += 1

    scan.status = "completed"
    scan.completed_at = now
    scan.summary_json = {
        **(scan.summary_json or {}),
        "asset_count": (1 if host_asset_id else 0) + len(container_asset_ids),
        "finding_count": finding_rows,
    }

    await _rebuild_project_recommendations(project_id, db)
    score = await _compute_security_score(project_id, db)
    runtime_snapshot.security_score = score["percentage"]
    runtime_snapshot.summary_json = {
        **(runtime_snapshot.summary_json or {}),
        "asset_count": (1 if host_asset_id else 0) + len(container_asset_ids),
        "finding_count": finding_rows,
        "score": score,
    }
    await db.commit()
    return {
        "scan_id": scan.id,
        "runtime_snapshot_id": runtime_snapshot.id,
        "finding_count": finding_rows,
        "asset_count": (1 if host_asset_id else 0) + len(container_asset_ids),
        "status": "completed",
    }


async def ingest_build_snapshot_payload(
    db: AsyncSession,
    *,
    project_id: int,
    collector: SecurityCollector,
    payload: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    source = f"build:{collector.id}"
    build_date = _parse_iso_timestamp(payload.get("collected_at") or payload.get("build_date") or now.isoformat())
    snapshot = SecurityBuildSnapshot(
        project_id=project_id,
        collector_id=collector.id,
        label=payload.get("label") or build_date.strftime("%Y.%m.%d.%H%M"),
        version=payload.get("version"),
        commit_ref=payload.get("commit_ref"),
        source=payload.get("source") or "local_build",
        status="running",
        build_date=build_date,
        summary_json={
            "collector_name": collector.name,
            "build_metadata": payload.get("build_metadata") or {},
        },
    )
    db.add(snapshot)
    await db.flush()

    component_assets = {
        "backend": await _upsert_asset(
            db,
            project_id=project_id,
            asset_type="component",
            name="atobot_backend",
            external_id=payload.get("version"),
            criticality="high",
            metadata_json={"component": "backend"},
        ),
        "frontend": await _upsert_asset(
            db,
            project_id=project_id,
            asset_type="component",
            name="atobot_frontend",
            external_id=payload.get("version"),
            criticality="medium",
            metadata_json={"component": "frontend"},
        ),
        "images": await _upsert_asset(
            db,
            project_id=project_id,
            asset_type="component",
            name="atobot_images",
            external_id=payload.get("label"),
            criticality="high",
            metadata_json={"component": "images"},
        ),
    }

    await _record_build_settings(
        db,
        project_id=project_id,
        snapshot_id=snapshot.id,
        component_assets=component_assets,
        payload=payload,
        source=source,
        observed_at=build_date,
    )

    await db.execute(
        update(SecurityFinding)
        .where(
            SecurityFinding.project_id == project_id,
            SecurityFinding.source == source,
            SecurityFinding.status == "open",
        )
        .values(status="resolved", resolved_at=now)
    )

    built_findings = _build_findings_from_payload(
        {
            "software_supply_chain": payload.get("software_supply_chain") or {},
            "containers": [],
            "host": {},
            "patch_posture": {},
            "app_security": {},
        }
    )

    finding_rows = 0
    for item in built_findings:
        metadata = await _finalize_finding_metadata(
            db,
            title=item["title"],
            severity=item["severity"],
            metadata=item["metadata_json"] or {},
            snapshot_kind="build",
            observed_at=build_date,
            snapshot_label=snapshot.label,
        )
        asset_name = metadata.get("asset_name")
        if asset_name == "atobot_backend":
            asset_id = component_assets["backend"]
        elif asset_name == "atobot_frontend":
            asset_id = component_assets["frontend"]
        else:
            asset_id = component_assets["images"]
        db.add(
            SecurityFinding(
                project_id=project_id,
                asset_id=asset_id,
                scan_id=None,
                source=source,
                category=item["category"],
                severity=item["severity"],
                title=item["title"],
                status=item["status"],
                fix_available=item["fix_available"],
                cvss=item["cvss"],
                metadata_json={**metadata, "snapshot_label": snapshot.label, "snapshot_id": snapshot.id},
            )
        )
        finding_rows += 1

    await _rebuild_project_recommendations(project_id, db)
    score = await _compute_security_score(project_id, db)
    snapshot.security_score = score["percentage"]
    snapshot.status = "completed"
    snapshot.summary_json = {
        **(snapshot.summary_json or {}),
        "finding_count": finding_rows,
        "score": score,
        "software_supply_chain": payload.get("software_supply_chain") or {},
    }
    await db.commit()
    return {
        "build_snapshot_id": snapshot.id,
        "finding_count": finding_rows,
        "status": "completed",
        "score": score,
    }


def _serialize_finding_row(row: SecurityFinding) -> dict[str, Any]:
    metadata = dict(row.metadata_json or {})
    contract = dict(metadata.get("detail_contract") or {})
    contract.setdefault("finding_type", metadata.get("finding_type") or row.category or "security_finding")
    contract.setdefault("source_scope", "build" if str(row.source or "").startswith("build:") else "live")
    contract.setdefault("operator_summary", metadata.get("summary") or row.title)
    contract.setdefault("why_it_matters", metadata.get("summary") or row.title)
    contract["observed"] = [item for item in (contract.get("observed") or []) if item.get("value") != ""]
    contract["expected"] = [item for item in (contract.get("expected") or []) if item.get("value") != ""]
    contract["evidence"] = [item for item in (contract.get("evidence") or []) if item.get("value") != ""]
    contract["fix_steps"] = [item for item in (contract.get("fix_steps") or []) if item]
    contract["verification_checks"] = [item for item in (contract.get("verification_checks") or []) if item]
    history = list(contract.get("history") or [])
    if row.detected_at:
        history.append(_fact("Detected at", row.detected_at.isoformat()))
    if metadata.get("asset_name"):
        history.append(_fact("Asset", metadata.get("asset_name")))
    contract["history"] = [item for item in history if item.get("value") not in {"", "none"}]
    guidance = dict(metadata.get("generated_guidance") or contract.get("generated_guidance") or _fallback_guidance(row.title, contract))
    contract["generated_guidance"] = guidance
    metadata["detail_contract"] = contract
    metadata["generated_guidance"] = guidance
    metadata["finding_type"] = contract.get("finding_type")
    return {
        "id": row.id,
        "asset_id": row.asset_id,
        "source": row.source,
        "category": row.category,
        "severity": row.severity,
        "title": row.title,
        "status": row.status,
        "fix_available": row.fix_available,
        "cvss": row.cvss,
        "detected_at": row.detected_at.isoformat() if row.detected_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "metadata": metadata,
        "finding_type": contract.get("finding_type"),
        "source_scope": contract.get("source_scope"),
        "observed": contract.get("observed") or [],
        "expected": contract.get("expected") or [],
        "evidence": contract.get("evidence") or [],
        "fix_steps": contract.get("fix_steps") or [],
        "verification_checks": contract.get("verification_checks") or [],
        "history": contract.get("history") or [],
        "generated_guidance": guidance,
    }


def _serialize_recommendation_row(row: SecurityRecommendation) -> dict[str, Any]:
    metadata = dict(row.metadata_json or {})
    affected_assets = metadata.get("affected_assets") or []
    count = int(metadata.get("count") or 0)
    contract = dict(metadata.get("detail_contract") or {})
    contract.setdefault("finding_type", f"recommendation::{row.key}")
    contract.setdefault("source_scope", "live")
    contract.setdefault("operator_summary", row.summary or row.title)
    contract.setdefault("why_it_matters", row.summary or row.title)
    contract["observed"] = [item for item in (contract.get("observed") or []) if item.get("value") != ""]
    contract["expected"] = [item for item in (contract.get("expected") or []) if item.get("value") != ""]
    contract["evidence"] = [item for item in (contract.get("evidence") or []) if item.get("value") != ""]
    contract["fix_steps"] = [item for item in (contract.get("fix_steps") or []) if item]
    contract["verification_checks"] = [item for item in (contract.get("verification_checks") or []) if item]
    history = list(contract.get("history") or [])
    if getattr(row, "updated_at", None):
        history.append(_fact("Updated at", row.updated_at.isoformat()))
    if affected_assets:
        history.append(_fact("Affected assets", len(affected_assets)))
    contract["history"] = [item for item in history if item.get("value") not in {"", "none"}]
    guidance = dict(metadata.get("generated_guidance") or contract.get("generated_guidance") or _fallback_guidance(row.title, contract))
    contract["generated_guidance"] = guidance
    metadata["detail_contract"] = contract
    metadata["generated_guidance"] = guidance
    metadata["finding_type"] = contract.get("finding_type")
    return {
        "id": row.id,
        "key": row.key,
        "title": row.title,
        "domain": row.domain,
        "severity": row.severity,
        "score_impact": row.score_impact,
        "status": row.status,
        "summary": row.summary,
        "action": row.action,
        "asset_count": len(affected_assets),
        "healthy_resources": 0 if row.status != "completed" else len(affected_assets),
        "unhealthy_resources": count if row.status != "completed" else 0,
        "not_applicable_resources": 0,
        "total_resources": max(count, len(affected_assets)),
        "metadata": metadata,
        "finding_type": contract.get("finding_type"),
        "source_scope": contract.get("source_scope"),
        "observed": contract.get("observed") or [],
        "expected": contract.get("expected") or [],
        "evidence": contract.get("evidence") or [],
        "fix_steps": contract.get("fix_steps") or [],
        "verification_checks": contract.get("verification_checks") or [],
        "history": contract.get("history") or [],
        "generated_guidance": guidance,
    }


async def _materialize_internal_findings(
    db: AsyncSession,
    *,
    built_findings: list[dict[str, Any]],
    source: str,
    observed_at: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(built_findings, start=1):
        metadata = await _finalize_finding_metadata(
            db,
            title=item["title"],
            severity=item["severity"],
            metadata=item["metadata_json"] or {},
            snapshot_kind="runtime",
            observed_at=observed_at,
        )
        rows.append(
            {
                "id": f"{source}:{index}",
                "asset_id": None,
                "source": source,
                "category": item["category"],
                "severity": item["severity"],
                "title": item["title"],
                "status": item["status"],
                "fix_available": item["fix_available"],
                "cvss": item["cvss"],
                "detected_at": observed_at.isoformat(),
                "resolved_at": None,
                "metadata": metadata,
                "finding_type": (metadata.get("detail_contract") or {}).get("finding_type") or metadata.get("finding_type"),
                "source_scope": (metadata.get("detail_contract") or {}).get("source_scope"),
                "observed": ((metadata.get("detail_contract") or {}).get("observed") or []),
                "expected": ((metadata.get("detail_contract") or {}).get("expected") or []),
                "evidence": ((metadata.get("detail_contract") or {}).get("evidence") or []),
                "fix_steps": ((metadata.get("detail_contract") or {}).get("fix_steps") or []),
                "verification_checks": ((metadata.get("detail_contract") or {}).get("verification_checks") or []),
                "history": ((metadata.get("detail_contract") or {}).get("history") or []),
                "generated_guidance": (metadata.get("detail_contract") or {}).get("generated_guidance") or metadata.get("generated_guidance") or {},
            }
        )
    return rows


def _synthesize_recommendations_from_findings(findings: list[dict[str, Any]], *, source_prefix: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in findings:
        if item.get("status") != "open":
            continue
        metadata = item.get("metadata") or {}
        key = metadata.get("recommendation_key")
        if not key:
            continue
        current = grouped.setdefault(
            key,
            {
                "title": metadata.get("recommendation_title") or item.get("title"),
                "domain": metadata.get("domain") or "Security",
                "severity": item.get("severity") or "medium",
                "score_impact": int(metadata.get("score_impact") or 0),
                "summary": metadata.get("summary"),
                "action": metadata.get("action"),
                "count": 0,
                "assets": set(),
                "packages": [],
                "vulnerabilities": [],
                "findings": [],
                "fix_steps": [],
                "verification_checks": [],
                "source_scope": set(),
            },
        )
        current["count"] += 1
        if _severity_rank(item.get("severity") or "") > _severity_rank(current["severity"]):
            current["severity"] = item.get("severity") or current["severity"]
        asset_name = metadata.get("asset_name")
        if asset_name:
            current["assets"].add(asset_name)
        contract = metadata.get("detail_contract") or {}
        if contract.get("source_scope"):
            current["source_scope"].add(contract.get("source_scope"))
        for step in contract.get("fix_steps") or []:
            if step not in current["fix_steps"]:
                current["fix_steps"].append(step)
        for step in contract.get("verification_checks") or []:
            if step not in current["verification_checks"]:
                current["verification_checks"].append(step)
        for package in metadata.get("packages") or []:
            if not any(existing.get("name") == package.get("name") for existing in current["packages"]):
                current["packages"].append(package)
        for vuln in metadata.get("vulnerabilities") or []:
            vuln_id = vuln.get("id") or vuln.get("title") or vuln.get("package")
            package_name = vuln.get("package") or vuln.get("name")
            if not any((existing.get("id") or existing.get("title")) == vuln_id and (existing.get("package") or existing.get("name")) == package_name for existing in current["vulnerabilities"]):
                current["vulnerabilities"].append(vuln)
        current["findings"].append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "severity": item.get("severity"),
                "asset_name": asset_name,
                "summary": metadata.get("summary"),
                "category": item.get("category"),
            }
        )

    recommendations: list[dict[str, Any]] = []
    for index, (key, item) in enumerate(grouped.items(), start=1):
        detail_contract = _detail_contract(
            finding_type=f"recommendation::{key}",
            source_scope="both" if len(item["source_scope"]) > 1 else next(iter(item["source_scope"]), "live"),
            operator_summary=item["summary"] or item["title"],
            why_it_matters=item["summary"] or item["title"],
            observed=[
                _fact("Open findings", item["count"]),
                _fact("Affected assets", len(item["assets"])),
                _fact("Affected packages", len(item["packages"])),
            ],
            expected=[_fact("Open findings", 0)],
            evidence=[_fact("Domain", item["domain"]), _fact("Severity", item["severity"])],
            fix_steps=item["fix_steps"][:5] or ([item["action"]] if item["action"] else []),
            verification_checks=item["verification_checks"][:5],
        )
        guidance = _fallback_guidance(item["title"], detail_contract)
        recommendations.append(
            {
                "id": f"{source_prefix}:{index}",
                "key": key,
                "title": item["title"],
                "domain": item["domain"],
                "severity": item["severity"],
                "score_impact": item["score_impact"],
                "status": _health_status(item["count"], item["severity"]),
                "summary": item["summary"],
                "action": item["action"],
                "asset_count": len(item["assets"]),
                "healthy_resources": 0,
                "unhealthy_resources": item["count"],
                "not_applicable_resources": 0,
                "total_resources": max(item["count"], len(item["assets"])),
                "finding_type": detail_contract.get("finding_type"),
                "source_scope": detail_contract.get("source_scope"),
                "observed": detail_contract.get("observed") or [],
                "expected": detail_contract.get("expected") or [],
                "evidence": detail_contract.get("evidence") or [],
                "fix_steps": detail_contract.get("fix_steps") or [],
                "verification_checks": detail_contract.get("verification_checks") or [],
                "history": detail_contract.get("history") or [],
                "generated_guidance": guidance,
                "metadata": {
                    "count": item["count"],
                    "affected_assets": sorted(item["assets"]),
                    "packages": item["packages"][:25],
                    "vulnerabilities": item["vulnerabilities"][:50],
                    "findings": item["findings"][:10],
                    "detail_contract": {**detail_contract, "generated_guidance": guidance},
                    "generated_guidance": guidance,
                },
            }
        )
    recommendations.sort(key=lambda item: (-int(item.get("score_impact") or 0), -_severity_rank(item.get("severity") or "")))
    return recommendations


def _compute_score_from_recommendations(recommendations: list[dict[str, Any]]) -> dict[str, int]:
    max_points = sum(max(int(item.get("score_impact") or 0), 1) for item in recommendations) or 1
    lost_points = sum(max(int(item.get("score_impact") or 0), 1) for item in recommendations if item.get("status") != "completed")
    earned_points = max(max_points - lost_points, 0)
    return {
        "percentage": round((earned_points / max_points) * 100),
        "earned_points": earned_points,
        "total_points": max_points,
    }


async def _build_identity_domain(project_id: int, db: AsyncSession) -> dict[str, Any]:
    del project_id
    now = datetime.now(UTC)
    users = (await db.execute(select(User))).scalars().all()
    users_by_id = {user.id: user for user in users}
    privileged_roles = {"admin", "assessor", "owner"}
    privileged_users = [user for user in users if (user.role or "").lower() in privileged_roles and user.is_active]
    privileged_without_mfa = [user for user in privileged_users if not user.mfa_enabled]
    dormant_cutoff = now - timedelta(days=30)
    dormant_privileged = [user for user in privileged_users if user.last_login is None or user.last_login < dormant_cutoff]
    locked_accounts = [user for user in users if user.locked_until and user.locked_until > now]
    refresh_tokens = (await db.execute(select(RefreshToken))).scalars().all()
    active_refresh_tokens = [token for token in refresh_tokens if not token.revoked and token.expires_at and token.expires_at >= now]
    expired_unrevoked_tokens = [token for token in refresh_tokens if not token.revoked and token.expires_at and token.expires_at < now]
    session_age_threshold_days = max(int(settings.stale_refresh_session_days or 1), 1)
    stale_session_cutoff = now - timedelta(days=session_age_threshold_days)
    stale_active_sessions = [
        token for token in active_refresh_tokens
        if token.created_at and token.created_at <= stale_session_cutoff
    ]
    active_sessions_by_user: dict[int, list[RefreshToken]] = {}
    for token in active_refresh_tokens:
        active_sessions_by_user.setdefault(token.user_id, []).append(token)
    privileged_multi_session_users = [
        user for user in privileged_users
        if len(active_sessions_by_user.get(user.id, [])) > 1
    ]
    recent_failed_events = (
        await db.execute(
            select(SecurityEvent).where(
                SecurityEvent.timestamp >= now - timedelta(hours=24),
                SecurityEvent.event_type.in_(["failed_login", "account_locked", "account_locked_attempt", "mfa_bypass_attempt"]),
            )
        )
    ).scalars().all()
    recent_role_changes = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.timestamp >= now - timedelta(days=7),
                func.lower(AuditLog.action).like("%role%"),
            )
        )
    ).scalars().all()
    recent_mfa_disable_logs = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.timestamp >= now - timedelta(days=7),
                AuditLog.endpoint.like("%/auth/mfa/disable%"),
                AuditLog.status_code < 400,
            )
        )
    ).scalars().all()
    recent_mfa_setup_logs = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.timestamp >= now - timedelta(days=7),
                AuditLog.endpoint.like("%/auth/mfa/setup%"),
                AuditLog.status_code < 400,
            )
        )
    ).scalars().all()
    privileged_without_mfa_rows = [
        {
            "title": user.username,
            "subtitle": " | ".join(
                part
                for part in [
                    user.role or "unknown role",
                    "MFA disabled",
                    f"last login {user.last_login.isoformat()}" if user.last_login else "never logged in",
                ]
                if part
            ),
        }
        for user in privileged_without_mfa[:10]
    ]
    dormant_privileged_rows = [
        {
            "title": user.username,
            "subtitle": " | ".join(
                part
                for part in [
                    user.role or "unknown role",
                    f"last login {user.last_login.isoformat()}" if user.last_login else "never logged in",
                ]
                if part
            ),
        }
        for user in dormant_privileged[:10]
    ]
    locked_account_rows = [
        {
            "title": user.username,
            "subtitle": " | ".join(
                part
                for part in [
                    f"locked until {user.locked_until.isoformat()}" if user.locked_until else None,
                    f"{user.failed_logins or 0} failed login(s)",
                ]
                if part
            ),
        }
        for user in locked_accounts[:10]
    ]
    failed_event_rows = [
        {
            "title": row.event_type,
            "subtitle": " | ".join(
                part
                for part in [
                    row.severity or "medium",
                    row.description or "",
                    row.timestamp.isoformat() if row.timestamp else None,
                ]
                if part
            ),
        }
        for row in recent_failed_events[:10]
    ]
    role_change_rows = [
        {
            "title": row.action or "Role change",
            "subtitle": " | ".join(
                part
                for part in [
                    row.endpoint or "",
                    f"status {row.status_code}" if row.status_code is not None else None,
                    row.timestamp.isoformat() if row.timestamp else None,
                ]
                if part
            ),
        }
        for row in recent_role_changes[:10]
    ]
    stale_session_rows = [
        {
            "title": users_by_id.get(token.user_id).username if users_by_id.get(token.user_id) else f"user {token.user_id}",
            "subtitle": " | ".join(
                part
                for part in [
                    f"token_id={token.id}",
                    f"created={token.created_at.isoformat()}" if token.created_at else None,
                    f"expires={token.expires_at.isoformat()}" if token.expires_at else None,
                    f"sessions={len(active_sessions_by_user.get(token.user_id, []))}",
                ]
                if part
            ),
        }
        for token in stale_active_sessions[:10]
    ]
    expired_token_rows = [
        {
            "title": users_by_id.get(token.user_id).username if users_by_id.get(token.user_id) else f"user {token.user_id}",
            "subtitle": " | ".join(
                part
                for part in [
                    f"token_id={token.id}",
                    f"expired={token.expires_at.isoformat()}" if token.expires_at else None,
                    "revoked=no",
                ]
                if part
            ),
        }
        for token in expired_unrevoked_tokens[:10]
    ]
    privileged_multi_session_rows = [
        {
            "title": user.username,
            "subtitle": " | ".join(
                part
                for part in [
                    user.role or "unknown role",
                    f"{len(active_sessions_by_user.get(user.id, []))} active session(s)",
                    f"last login {user.last_login.isoformat()}" if user.last_login else "never logged in",
                ]
                if part
            ),
        }
        for user in privileged_multi_session_users[:10]
    ]
    mfa_disable_rows = [
        {
            "title": row.action or "MFA disable",
            "subtitle": " | ".join(
                part
                for part in [
                    row.endpoint or None,
                    f"status {row.status_code}" if row.status_code is not None else None,
                    row.timestamp.isoformat() if row.timestamp else None,
                ]
                if part
            ),
        }
        for row in recent_mfa_disable_logs[:10]
    ]

    built_findings: list[dict[str, Any]] = []
    if privileged_without_mfa:
        usernames = [user.username for user in privileged_without_mfa[:10]]
        built_findings.append(_finding(
            finding_type="app_privileged_accounts_missing_mfa",
            category="identity",
            severity="high",
            title="Privileged ATO Bot accounts do not all require MFA",
            recommendation_key="app_privileged_mfa",
            recommendation_title="Enforce MFA for privileged ATO Bot users",
            domain="Identity & Access",
            score_impact=15,
            action="Require MFA for every privileged user and verify emergency or assessor paths are covered by the same control.",
            summary=f"{len(privileged_without_mfa)} privileged account(s) are active without MFA.",
            asset_name="ato_bot_identity",
            source_scope="live",
            observed=[_fact("Privileged accounts without MFA", len(privileged_without_mfa)), _fact("Accounts", usernames)],
            expected=[_fact("Privileged accounts without MFA", 0)],
            evidence=[_fact("User scope", "app-wide"), _fact("Role set", ", ".join(sorted(privileged_roles)))],
            fix_steps=[
                "Enable MFA for each privileged account that can administer, assess, or manage the system.",
                "Remove or downgrade privileged access that is no longer required.",
            ],
            verification_checks=[
                "The identity endpoint reports privileged accounts without MFA = 0.",
                "Privileged sign-in still succeeds only with MFA enforced.",
            ],
            why_it_matters="Privileged access without MFA remains one of the highest-value attack paths in the application itself.",
            metadata_json={"usernames": usernames, "count": len(privileged_without_mfa), "records": privileged_without_mfa_rows},
        ))
    if dormant_privileged:
        usernames = [user.username for user in dormant_privileged[:10]]
        built_findings.append(_finding(
            finding_type="app_dormant_privileged_accounts",
            category="identity",
            severity="medium",
            title="Dormant privileged ATO Bot accounts need review",
            recommendation_key="app_dormant_privileged_access",
            recommendation_title="Review or disable dormant privileged accounts",
            domain="Identity & Access",
            score_impact=8,
            action="Review dormant privileged accounts and disable, remove, or validate them as still required.",
            summary=f"{len(dormant_privileged)} privileged account(s) have not logged in within the last 30 days.",
            asset_name="ato_bot_identity",
            source_scope="live",
            observed=[_fact("Dormant privileged accounts", len(dormant_privileged)), _fact("Accounts", usernames)],
            expected=[_fact("Dormant privileged accounts", 0)],
            evidence=[_fact("Dormancy threshold", "30 days")],
            fix_steps=[
                "Disable or downgrade privileged accounts that no longer need elevated access.",
                "Document and justify any dormant privileged account that must remain active.",
            ],
            verification_checks=["The identity endpoint reports dormant privileged accounts = 0 or only approved exceptions remain."],
            why_it_matters="Dormant privileged accounts increase standing access risk and are often overlooked during normal administration.",
            metadata_json={"usernames": usernames, "count": len(dormant_privileged), "records": dormant_privileged_rows},
        ))
    if len(recent_failed_events) >= 5:
        built_findings.append(_finding(
            finding_type="app_failed_login_activity",
            category="identity",
            severity="medium" if len(recent_failed_events) < 15 else "high",
            title="ATO Bot is seeing elevated failed authentication activity",
            recommendation_key="app_failed_login_activity",
            recommendation_title="Investigate elevated failed login activity",
            domain="Identity & Access",
            score_impact=6,
            action="Review recent failed login, lockout, and MFA bypass events to determine whether they represent attack activity or user friction.",
            summary=f"{len(recent_failed_events)} authentication-related security event(s) were recorded in the last 24 hours.",
            asset_name="ato_bot_identity",
            source_scope="live",
            observed=[_fact("Authentication security events (24h)", len(recent_failed_events))],
            expected=[_fact("Authentication security events (24h)", "baseline only")],
            evidence=[_fact("Event types", "failed_login, account_locked, mfa_bypass_attempt")],
            fix_steps=[
                "Review the event trail and affected accounts.",
                "Confirm rate limiting, lockout, and MFA controls are working as intended.",
            ],
            verification_checks=["Authentication-related security event volume returns to the expected baseline."],
            why_it_matters="Elevated failed authentication activity can indicate password guessing, MFA abuse, or policy friction that needs operator attention.",
            metadata_json={"event_count": len(recent_failed_events), "records": failed_event_rows},
        ))
    if locked_accounts:
        built_findings.append(_finding(
            finding_type="app_locked_accounts_present",
            category="identity",
            severity="medium",
            title="ATO Bot currently has locked user accounts",
            recommendation_key="app_locked_accounts_review",
            recommendation_title="Review current account lockouts",
            domain="Identity & Access",
            score_impact=4,
            action="Review locked accounts to determine whether they reflect attack activity, stale accounts, or user support issues.",
            summary=f"{len(locked_accounts)} account(s) are currently locked.",
            asset_name="ato_bot_identity",
            source_scope="live",
            observed=[_fact("Locked accounts", len(locked_accounts)), _fact("Accounts", [user.username for user in locked_accounts[:10]])],
            expected=[_fact("Locked accounts", 0)],
            evidence=[_fact("Lockout policy", f"{settings.max_login_attempts} attempts / {settings.lockout_minutes} minutes")],
            fix_steps=[
                "Review the cause of each lockout and confirm it was handled appropriately.",
                "Reset or disable accounts that should no longer be active.",
            ],
            verification_checks=["The identity endpoint reports no unexpected locked accounts."],
            why_it_matters="Active lockouts can indicate attack activity or identity hygiene problems that deserve review.",
            metadata_json={"count": len(locked_accounts), "usernames": [user.username for user in locked_accounts[:10]], "records": locked_account_rows},
        ))
    if recent_role_changes:
        built_findings.append(_finding(
            finding_type="app_recent_role_changes",
            category="identity",
            severity="medium",
            title="ATO Bot has recent role or privilege changes",
            recommendation_key="app_role_change_review",
            recommendation_title="Review recent role and privilege changes",
            domain="Identity & Access",
            score_impact=5,
            action="Review recent role and privilege changes to confirm they were expected, approved, and still appropriate.",
            summary=f"{len(recent_role_changes)} role-related audit event(s) were recorded in the last 7 days.",
            asset_name="ato_bot_identity",
            source_scope="live",
            observed=[_fact("Role-related audit events (7d)", len(recent_role_changes))],
            expected=[_fact("Role-related audit events (7d)", "approved baseline")],
            evidence=[_fact("Audit source", "audit_logs"), _fact("Window", "7 days")],
            fix_steps=[
                "Review the recent role changes and confirm they match approved administrative actions.",
                "Reverse or investigate any unexpected privilege change.",
            ],
            verification_checks=["Recent role changes are approved, documented, or reduced to the expected baseline."],
            why_it_matters="Recent role or privilege changes can materially alter system risk and should remain visible to operators.",
            metadata_json={"records": role_change_rows, "count": len(recent_role_changes)},
        ))
    if privileged_multi_session_users:
        built_findings.append(_finding(
            finding_type="app_privileged_concurrent_sessions",
            category="identity",
            severity="high" if any(len(active_sessions_by_user.get(user.id, [])) >= 3 for user in privileged_multi_session_users) else "medium",
            title="Privileged ATO Bot accounts have multiple active sessions",
            recommendation_key="app_privileged_session_hygiene",
            recommendation_title="Review concurrent privileged sessions",
            domain="Boundary & Session Security",
            score_impact=7,
            action="Review concurrent privileged sessions and revoke unneeded refresh tokens so elevated access stays tightly scoped.",
            summary=f"{len(privileged_multi_session_users)} privileged account(s) currently hold multiple active refresh sessions.",
            asset_name="ato_bot_identity",
            source_scope="live",
            observed=[_fact("Privileged users with multiple active sessions", len(privileged_multi_session_users))],
            expected=[_fact("Privileged users with multiple active sessions", 0)],
            evidence=[_fact("Token source", "refresh_tokens"), _fact("Active refresh sessions", len(active_refresh_tokens))],
            fix_steps=[
                "Review active refresh sessions for privileged users and revoke unnecessary tokens.",
                "Limit concurrent privileged sessions to the minimum operationally required set.",
            ],
            verification_checks=[
                "The identity endpoint reports zero or approved privileged users with multiple active sessions.",
                "Privileged users can still complete required work after unused sessions are revoked.",
            ],
            why_it_matters="Multiple active privileged sessions increase the window for token misuse and make elevated access harder to reason about during an incident.",
            metadata_json={"records": privileged_multi_session_rows, "count": len(privileged_multi_session_users)},
        ))
    if stale_active_sessions:
        built_findings.append(_finding(
            finding_type="app_long_lived_refresh_sessions",
            category="identity",
            severity="medium",
            title="ATO Bot has long-lived active refresh sessions",
            recommendation_key="app_refresh_session_age",
            recommendation_title="Reduce long-lived active refresh sessions",
            domain="Boundary & Session Security",
            score_impact=6,
            action="Review older active refresh sessions and revoke or rotate sessions that are no longer needed.",
            summary=f"{len(stale_active_sessions)} active refresh session(s) are older than {session_age_threshold_days} day(s).",
            asset_name="ato_bot_identity",
            source_scope="live",
            observed=[_fact("Active sessions older than threshold", len(stale_active_sessions)), _fact("Age threshold", f"{session_age_threshold_days} day(s)")],
            expected=[_fact("Active sessions older than threshold", 0)],
            evidence=[_fact("Token source", "refresh_tokens"), _fact("Refresh token lifetime", f"{settings.refresh_token_expire_days} day(s)")],
            fix_steps=[
                "Review and revoke refresh sessions that are older than the accepted session age threshold.",
                "Shorten refresh token lifetime or tighten session rotation if older sessions are common.",
            ],
            verification_checks=[
                "The identity endpoint reports zero or reduced long-lived active refresh sessions.",
                "Users can still authenticate successfully after older sessions are rotated or revoked.",
            ],
            why_it_matters="Long-lived active refresh sessions extend the life of stolen or forgotten tokens and weaken session hygiene.",
            metadata_json={"records": stale_session_rows, "count": len(stale_active_sessions)},
        ))
    if expired_unrevoked_tokens:
        built_findings.append(_finding(
            finding_type="app_expired_refresh_tokens_not_revoked",
            category="identity",
            severity="medium",
            title="ATO Bot keeps expired refresh tokens that are not revoked",
            recommendation_key="app_refresh_token_cleanup",
            recommendation_title="Clean up expired refresh tokens",
            domain="Boundary & Session Security",
            score_impact=5,
            action="Revoke or purge expired refresh tokens so the token inventory reflects only current usable sessions.",
            summary=f"{len(expired_unrevoked_tokens)} expired refresh token(s) remain unreconciled in the token store.",
            asset_name="ato_bot_identity",
            source_scope="live",
            observed=[_fact("Expired unrevoked refresh tokens", len(expired_unrevoked_tokens))],
            expected=[_fact("Expired unrevoked refresh tokens", 0)],
            evidence=[_fact("Token source", "refresh_tokens"), _fact("Refresh token lifetime", f"{settings.refresh_token_expire_days} day(s)")],
            fix_steps=[
                "Purge or revoke expired refresh tokens on a regular schedule.",
                "Keep the token inventory limited to sessions that are still valid and intended.",
            ],
            verification_checks=[
                "The identity endpoint reports zero expired refresh tokens that remain unrevoked.",
                "Expired sessions no longer appear in token inventory after cleanup.",
            ],
            why_it_matters="Expired-but-unrevoked tokens make the session inventory harder to trust and complicate incident review and access hygiene.",
            metadata_json={"records": expired_token_rows, "count": len(expired_unrevoked_tokens)},
        ))
    if recent_mfa_disable_logs:
        built_findings.append(_finding(
            finding_type="app_recent_mfa_disable_activity",
            category="identity",
            severity="high",
            title="ATO Bot has recent MFA disable activity",
            recommendation_key="app_mfa_disable_review",
            recommendation_title="Review recent MFA disable activity",
            domain="Identity & Access",
            score_impact=8,
            action="Review recent MFA disable operations and confirm they were approved, temporary, and restored when appropriate.",
            summary=f"{len(recent_mfa_disable_logs)} MFA disable action(s) were recorded in the last 7 days.",
            asset_name="ato_bot_identity",
            source_scope="live",
            observed=[_fact("MFA disable actions (7d)", len(recent_mfa_disable_logs))],
            expected=[_fact("MFA disable actions (7d)", 0)],
            evidence=[_fact("Audit source", "audit_logs"), _fact("Window", "7 days")],
            fix_steps=[
                "Review each MFA disable action for approval, rationale, and duration.",
                "Re-enable MFA or remove access where the disable action is no longer justified.",
            ],
            verification_checks=[
                "The identity endpoint reports zero unexpected recent MFA disable actions.",
                "Affected accounts have MFA restored or formally approved exception records.",
            ],
            why_it_matters="Recent MFA disable activity can materially reduce account protection and should be reviewed as a security-relevant change.",
            metadata_json={"records": mfa_disable_rows, "count": len(recent_mfa_disable_logs)},
        ))

    findings = await _materialize_internal_findings(db, built_findings=built_findings, source="app_api:identity", observed_at=now)
    recommendations = _synthesize_recommendations_from_findings(findings, source_prefix="internal:identity")
    return {
        "summary": {
            "total_users": len(users),
            "privileged_users": len(privileged_users),
            "privileged_without_mfa": len(privileged_without_mfa),
            "dormant_privileged": len(dormant_privileged),
            "locked_accounts": len(locked_accounts),
            "failed_auth_events_24h": len(recent_failed_events),
            "role_changes_7d": len(recent_role_changes),
            "active_refresh_sessions": len(active_refresh_tokens),
            "expired_unrevoked_refresh_tokens": len(expired_unrevoked_tokens),
            "stale_refresh_sessions": len(stale_active_sessions),
            "privileged_multi_session_users": len(privileged_multi_session_users),
            "mfa_disable_actions_7d": len(recent_mfa_disable_logs),
            "mfa_setup_actions_7d": len(recent_mfa_setup_logs),
        },
        "findings": findings,
        "recommendations": recommendations,
    }


async def _build_configuration_domain(project_id: int, db: AsyncSession) -> dict[str, Any]:
    del project_id
    now = datetime.now(UTC)
    allowed_origins = settings.allowed_origins_list
    weak_secrets = {"changeme", "secret", "dev-secret", "development", "ato-bot-secret"}
    secret_is_weak = len(settings.secret_key or "") < 32 or (settings.secret_key or "").lower() in weak_secrets
    wildcard_cors = "*" in allowed_origins
    nonlocal_http_origins = [
        origin
        for origin in allowed_origins
        if origin and "localhost" not in origin and "127.0.0.1" not in origin and origin.startswith("http://")
    ]
    csp_inline_scripts = csp_allows_inline_scripts()
    csp_inline_styles = csp_allows_inline_styles()
    csp_uses_unsafe_inline = csp_inline_scripts or csp_inline_styles
    weak_lockout = settings.max_login_attempts > 10 or settings.lockout_minutes < 10
    weak_access_token_lifetime = settings.access_token_expire_minutes > 60
    weak_refresh_token_lifetime = settings.refresh_token_expire_days > 14
    weak_session_policy = weak_access_token_lifetime or weak_refresh_token_lifetime
    configuration_records = [
        {"title": "Application environment", "subtitle": settings.app_env},
        {"title": "Allowed origins", "subtitle": ", ".join(allowed_origins) if allowed_origins else "none"},
        {"title": "Credentials with CORS", "subtitle": "enabled" if settings.cors_allow_credentials else "disabled"},
        {"title": "Secret key length", "subtitle": str(len(settings.secret_key or ""))},
        {"title": "Login protection", "subtitle": f"{settings.max_login_attempts} attempts | {settings.lockout_minutes} minute lockout"},
        {
            "title": "CSP posture",
            "subtitle": (
                "inline scripts and styles allowed"
                if csp_inline_scripts and csp_inline_styles
                else "inline scripts allowed"
                if csp_inline_scripts
                else "inline styles allowed"
                if csp_inline_styles
                else "tightened"
            ),
        },
        {"title": "Token lifetimes", "subtitle": f"access={settings.access_token_expire_minutes} minute(s) | refresh={settings.refresh_token_expire_days} day(s)"},
    ]

    built_findings: list[dict[str, Any]] = []
    if wildcard_cors and settings.cors_allow_credentials:
        built_findings.append(_finding(
            finding_type="app_credentialed_wildcard_cors",
            category="configuration",
            severity="high",
            title="ATO Bot allows credentialed wildcard CORS",
            recommendation_key="app_cors_posture",
            recommendation_title="Restrict credentialed CORS origins",
            domain="Boundary & Session Security",
            score_impact=12,
            action="Replace wildcard CORS with an explicit trusted origin allowlist before relying on the app in a broader deployment.",
            summary="Credentialed wildcard CORS weakens browser trust boundaries and can expose authenticated sessions to untrusted origins.",
            asset_name="ato_bot_configuration",
            source_scope="live",
            observed=[_fact("Allowed origins", allowed_origins), _fact("Credentials allowed", settings.cors_allow_credentials)],
            expected=[_fact("Allowed origins", "explicit trusted origins only"), _fact("Credentials allowed", "only with explicit origins")],
            evidence=[_fact("Config source", "application settings")],
            fix_steps=[
                "Replace wildcard origins with an explicit allowlist of trusted origins.",
                "Keep credentials enabled only when paired with explicit trusted origins.",
            ],
            verification_checks=["The configuration endpoint reports no wildcard origin when credentials are enabled."],
            why_it_matters="Credentialed wildcard CORS weakens browser trust boundaries and can expose authenticated sessions to untrusted origins.",
            metadata_json={"records": configuration_records},
        ))
    elif nonlocal_http_origins:
        built_findings.append(_finding(
            finding_type="app_non_tls_cors_origins",
            category="configuration",
            severity="medium",
            title="ATO Bot trusts non-local HTTP origins",
            recommendation_key="app_cors_posture",
            recommendation_title="Restrict browser origins to trusted HTTPS endpoints",
            domain="Boundary & Session Security",
            score_impact=7,
            action="Restrict browser origins to trusted HTTPS endpoints or localhost-only development origins.",
            summary=f"{len(nonlocal_http_origins)} non-local HTTP origin(s) are currently trusted by CORS.",
            asset_name="ato_bot_configuration",
            source_scope="live",
            observed=[_fact("Trusted non-local HTTP origins", nonlocal_http_origins)],
            expected=[_fact("Trusted origins", "localhost dev origins or explicit HTTPS origins only")],
            evidence=[_fact("Config source", "application settings")],
            fix_steps=[
                "Replace non-local HTTP origins with HTTPS origins where possible.",
                "Restrict development-only origins to localhost.",
            ],
            verification_checks=["The configuration endpoint reports no non-local HTTP origins in the allowlist."],
            why_it_matters="Trusting non-local HTTP origins weakens browser boundary controls and can expose authenticated sessions over insecure transport.",
            metadata_json={"records": configuration_records, "origins": nonlocal_http_origins},
        ))
    if secret_is_weak:
        built_findings.append(_finding(
            finding_type="app_secret_key_posture",
            category="configuration",
            severity="high" if settings.app_env == "production" else "medium",
            title="ATO Bot is using a weak or short secret key",
            recommendation_key="app_secret_key_strength",
            recommendation_title="Use a strong application secret key",
            domain="Configuration & Secrets",
            score_impact=10,
            action="Replace the application secret key with a long, unique value and keep it out of source and image context.",
            summary="The configured secret key is weak enough to reduce trust in token and signing protections.",
            asset_name="ato_bot_configuration",
            source_scope="live",
            observed=[_fact("Secret key length", len(settings.secret_key or "")), _fact("Environment", settings.app_env)],
            expected=[_fact("Secret key length", "32+ characters and unique")],
            evidence=[_fact("Secret posture", "weak or short secret detected")],
            fix_steps=[
                "Replace the secret key with a strong unique value of at least 32 characters.",
                "Store the secret in a managed secret source instead of default or development values.",
            ],
            verification_checks=[
                "The configuration endpoint reports a strong secret posture.",
                "Authentication and signing behavior still works after rotation.",
            ],
            why_it_matters="Weak application secrets reduce confidence in token signing, encryption, and other security-sensitive application operations.",
            metadata_json={"records": configuration_records},
        ))
    if csp_inline_scripts:
        built_findings.append(_finding(
            finding_type="app_csp_unsafe_inline",
            category="configuration",
            severity="medium",
            title="ATO Bot CSP still allows unsafe inline scripts",
            recommendation_key="app_csp_hardening",
            recommendation_title="Harden CSP and remove unsafe inline scripts",
            domain="Boundary & Session Security",
            score_impact=7,
            action="Replace unsafe inline script CSP allowances with nonce-, hash-, or external-script-based policies.",
            summary="The current CSP still allows unsafe inline scripts, which weakens browser-side exploit resistance.",
            asset_name="ato_bot_configuration",
            source_scope="live",
            observed=[_fact("script-src", "'unsafe-inline' enabled")],
            expected=[_fact("script-src", "no unsafe-inline")],
            evidence=[_fact("Config source", "security headers middleware")],
            fix_steps=[
                "Move inline scripts to safer patterns using nonces, hashes, or external resources.",
                "Retest the UI after tightening the CSP.",
            ],
            verification_checks=["The configuration endpoint reports no unsafe inline script allowance in the CSP."],
            why_it_matters="Unsafe inline scripts materially reduce browser-side protection against injected script content.",
            metadata_json={"records": configuration_records},
        ))
    elif csp_inline_styles:
        built_findings.append(_finding(
            finding_type="app_csp_inline_styles",
            category="configuration",
            severity="low",
            title="ATO Bot CSP still allows inline styles",
            recommendation_key="app_csp_style_hardening",
            recommendation_title="Reduce inline style CSP allowances",
            domain="Boundary & Session Security",
            score_impact=3,
            action="Reduce inline style usage where practical so the CSP can move toward a stricter style policy without breaking the UI.",
            summary="The current CSP still allows inline styles because parts of the frontend depend on them.",
            asset_name="ato_bot_configuration",
            source_scope="live",
            observed=[_fact("style-src", "'unsafe-inline' enabled")],
            expected=[_fact("style-src", "no unsafe-inline where practical")],
            evidence=[_fact("Config source", "security headers middleware")],
            fix_steps=[
                "Refactor inline style attributes to safer styling patterns where practical.",
                "Tighten the style CSP after the frontend no longer depends on inline styles.",
            ],
            verification_checks=["The configuration endpoint reports no unsafe inline style allowance or a documented exception baseline."],
            why_it_matters="Inline styles are lower risk than inline scripts, but they still prevent the CSP from reaching a fully hardened posture.",
            metadata_json={"records": configuration_records},
        ))
    if weak_lockout:
        built_findings.append(_finding(
            finding_type="app_login_protection_weak",
            category="configuration",
            severity="medium",
            title="ATO Bot login protection thresholds are weak",
            recommendation_key="app_login_protection",
            recommendation_title="Tighten login rate-limit and lockout settings",
            domain="Identity & Access",
            score_impact=5,
            action="Tighten login attempt and lockout thresholds so brute-force and credential stuffing are harder to sustain.",
            summary=f"Current login protection is set to {settings.max_login_attempts} attempts and {settings.lockout_minutes} lockout minute(s).",
            asset_name="ato_bot_configuration",
            source_scope="live",
            observed=[_fact("Max login attempts", settings.max_login_attempts), _fact("Lockout minutes", settings.lockout_minutes)],
            expected=[_fact("Max login attempts", "10 or fewer"), _fact("Lockout minutes", "10 or more")],
            evidence=[_fact("Config source", "application settings")],
            fix_steps=["Lower the maximum allowed login attempts and ensure lockout is long enough to slow repeated guessing."],
            verification_checks=["The configuration endpoint reports the stronger login protection thresholds."],
            why_it_matters="Weak lockout thresholds make repeated guessing or credential stuffing easier to sustain against the app.",
            metadata_json={"records": configuration_records},
        ))
    if weak_session_policy:
        built_findings.append(_finding(
            finding_type="app_session_policy_weak",
            category="configuration",
            severity="high" if settings.refresh_token_expire_days > 30 or settings.access_token_expire_minutes > 120 else "medium",
            title="ATO Bot session token policy is longer-lived than the hardened baseline",
            recommendation_key="app_session_policy",
            recommendation_title="Tighten token and session lifetime policy",
            domain="Boundary & Session Security",
            score_impact=6,
            action="Shorten access and/or refresh token lifetimes so session exposure is reduced when credentials or tokens are lost.",
            summary=f"Current token policy is {settings.access_token_expire_minutes} access minute(s) and {settings.refresh_token_expire_days} refresh day(s).",
            asset_name="ato_bot_configuration",
            source_scope="live",
            observed=[_fact("Access token lifetime", f"{settings.access_token_expire_minutes} minute(s)"), _fact("Refresh token lifetime", f"{settings.refresh_token_expire_days} day(s)")],
            expected=[_fact("Access token lifetime", "60 minute(s) or fewer"), _fact("Refresh token lifetime", "14 day(s) or fewer")],
            evidence=[_fact("Config source", "application settings")],
            fix_steps=[
                "Reduce access token lifetime to the hardened baseline or shorter.",
                "Reduce refresh token lifetime and require session renewal more frequently for sensitive roles if appropriate.",
            ],
            verification_checks=["The configuration endpoint reports token lifetimes at or below the hardened baseline."],
            why_it_matters="Long-lived tokens widen the usable window for stolen or abandoned sessions and weaken session containment during incidents.",
            metadata_json={"records": configuration_records},
        ))

    findings = await _materialize_internal_findings(db, built_findings=built_findings, source="app_api:configuration", observed_at=now)
    recommendations = _synthesize_recommendations_from_findings(findings, source_prefix="internal:configuration")
    return {
        "summary": {
            "app_env": settings.app_env,
            "allowed_origins": allowed_origins,
            "wildcard_cors": wildcard_cors,
            "cors_allow_credentials": settings.cors_allow_credentials,
            "weak_secret": secret_is_weak,
            "csp_unsafe_inline": csp_uses_unsafe_inline,
            "csp_inline_scripts": csp_inline_scripts,
            "csp_inline_styles": csp_inline_styles,
            "max_login_attempts": settings.max_login_attempts,
            "lockout_minutes": settings.lockout_minutes,
            "access_token_expire_minutes": settings.access_token_expire_minutes,
            "refresh_token_expire_days": settings.refresh_token_expire_days,
            "weak_session_policy": weak_session_policy,
        },
        "findings": findings,
        "recommendations": recommendations,
    }


async def _build_jobs_domain(project_id: int, db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    stale_run_hours = max(int(settings.stale_ingestion_run_hours or 1), 1)
    failed_ingestions_24h = (
        await db.execute(
            select(IngestionRun).where(
                IngestionRun.started_at >= now - timedelta(hours=24),
                IngestionRun.status == "failed",
            )
        )
    ).scalars().all()
    stuck_ingestions = (
        await db.execute(
            select(IngestionRun).where(
                IngestionRun.status == "running",
                IngestionRun.started_at <= now - timedelta(hours=stale_run_hours),
            )
        )
    ).scalars().all()
    failed_assessments_7d = (
        await db.execute(
            select(Assessment).where(
                Assessment.started_at >= now - timedelta(days=7),
                Assessment.status == "failed",
            )
        )
    ).scalars().all()
    unresolved_high_events = (
        await db.execute(
            select(SecurityEvent).where(
                SecurityEvent.resolved == False,
                SecurityEvent.severity.in_(["critical", "high"]),
            )
        )
    ).scalars().all()
    config_changes_7d = (
        await db.execute(
            select(IngestionConfigAudit).where(
                IngestionConfigAudit.changed_at >= now - timedelta(days=7),
            )
        )
    ).scalars().all()
    parse_failures_24h = [run for run in failed_ingestions_24h if (run.error_stage or run.current_stage) == "parse"]
    failed_ingestion_rows = [
        {
            "title": f"Document {run.document_id}" if run.document_id else f"Ingestion run {run.id}",
            "subtitle": " | ".join(
                [
                    run.error_stage or run.current_stage or "unknown stage",
                    run.error_message[:120] if run.error_message else None,
                    f"run_id={run.id}",
                ]
            ),
        }
        for run in failed_ingestions_24h[:10]
    ]
    stuck_ingestion_rows = [
        {
            "title": f"Document {run.document_id}" if run.document_id else f"Ingestion run {run.id}",
            "subtitle": " | ".join(
                [
                    run.current_stage or "running",
                    f"started={run.started_at.isoformat()}" if run.started_at else None,
                    f"run_id={run.id}",
                ]
            ),
        }
        for run in stuck_ingestions[:10]
    ]
    failed_assessment_rows = [
        {
            "title": assessment.name or f"Assessment {assessment.id}",
            "subtitle": " | ".join(
                [
                    assessment.status or "failed",
                    assessment.llm_model or None,
                    f"assessment_id={assessment.id}",
                ]
            ),
        }
        for assessment in failed_assessments_7d[:10]
    ]
    unresolved_event_rows = [
        {
            "title": event.event_type or f"Security event {event.id}",
            "subtitle": " | ".join(
                [
                    event.severity or "unknown",
                    event.description[:120] if event.description else None,
                    event.timestamp.isoformat() if event.timestamp else None,
                ]
            ),
        }
        for event in unresolved_high_events[:10]
    ]
    parse_failure_rows = [
        {
            "title": f"Document {run.document_id}" if run.document_id else f"Ingestion run {run.id}",
            "subtitle": " | ".join(
                [
                    "parse",
                    run.error_message[:120] if run.error_message else None,
                    f"run_id={run.id}",
                ]
            ),
        }
        for run in parse_failures_24h[:10]
    ]

    built_findings: list[dict[str, Any]] = []
    if failed_ingestions_24h:
        built_findings.append(_finding(
            finding_type="app_ingestion_failures",
            category="jobs",
            severity="high" if len(failed_ingestions_24h) >= 5 else "medium",
            title="ATO Bot ingestion pipeline has recent failures",
            recommendation_key="app_ingestion_pipeline_health",
            recommendation_title="Stabilize ingestion pipeline failures",
            domain="Monitoring & Audit",
            score_impact=10,
            action="Review recent ingestion failures, error stages, and affected documents so evidence collection remains trustworthy.",
            summary=f"{len(failed_ingestions_24h)} ingestion run(s) failed in the last 24 hours.",
            asset_name="ato_bot_jobs",
            source_scope="live",
            observed=[_fact("Failed ingestion runs (24h)", len(failed_ingestions_24h))],
            expected=[_fact("Failed ingestion runs (24h)", 0)],
            evidence=[_fact("Pipeline", "document ingestion"), _fact("Project scope", project_id)],
            fix_steps=[
                "Review the failed ingestion runs and their error stages.",
                "Fix the failing parser or pipeline stages and re-run the affected documents.",
            ],
            verification_checks=[
                "The jobs endpoint reports failed ingestion runs (24h) = 0 or the accepted baseline.",
                "The affected documents complete ingestion successfully on retry.",
            ],
            why_it_matters="If ingestion is failing, the system loses confidence in evidence collection and downstream security analysis.",
            metadata_json={"records": failed_ingestion_rows},
        ))
    if stuck_ingestions:
        built_findings.append(_finding(
            finding_type="app_stuck_ingestion_jobs",
            category="jobs",
            severity="high",
            title="ATO Bot has ingestion jobs stuck in running state",
            recommendation_key="app_stuck_jobs",
            recommendation_title="Resolve stuck ingestion jobs",
            domain="Monitoring & Audit",
            score_impact=9,
            action="Investigate and clear stuck ingestion jobs so the monitoring pipeline does not silently stall.",
            summary=f"{len(stuck_ingestions)} ingestion run(s) have been running for more than one hour.",
            asset_name="ato_bot_jobs",
            source_scope="live",
            observed=[_fact("Stuck ingestion jobs", len(stuck_ingestions))],
            expected=[_fact("Stuck ingestion jobs", 0)],
            evidence=[_fact("Running threshold", f"{stale_run_hours} hour(s)")],
            fix_steps=[
                "Inspect the stuck runs and determine whether they need cancellation, retry, or parser fixes.",
                "Add or tune runtime detection for long-running stuck stages if needed.",
            ],
            verification_checks=["The jobs endpoint reports zero stuck ingestion jobs."],
            why_it_matters="Stuck jobs create monitoring blind spots and can hide evidence collection failures for long periods.",
            metadata_json={"records": stuck_ingestion_rows},
        ))
    if failed_assessments_7d:
        built_findings.append(_finding(
            finding_type="app_assessment_failures",
            category="jobs",
            severity="medium",
            title="ATO Bot assessments have failed recently",
            recommendation_key="app_assessment_pipeline_health",
            recommendation_title="Stabilize assessment pipeline failures",
            domain="Monitoring & Audit",
            score_impact=8,
            action="Review failed assessments and correct the pipeline or model/runtime causes before relying on those outputs.",
            summary=f"{len(failed_assessments_7d)} assessment run(s) failed in the last 7 days.",
            asset_name="ato_bot_jobs",
            source_scope="live",
            observed=[_fact("Failed assessments (7d)", len(failed_assessments_7d))],
            expected=[_fact("Failed assessments (7d)", 0)],
            evidence=[_fact("Pipeline", "assessment execution")],
            fix_steps=[
                "Review the failed assessment runs and resolve the underlying model, context, or runtime errors.",
                "Re-run failed assessments after the issue is corrected.",
            ],
            verification_checks=["The jobs endpoint reports failed assessments (7d) = 0 or the expected baseline."],
            why_it_matters="Assessment failures reduce confidence in the system’s ability to continuously generate and update security evidence.",
            metadata_json={"records": failed_assessment_rows},
        ))
    if unresolved_high_events:
        built_findings.append(_finding(
            finding_type="app_unresolved_security_events",
            category="jobs",
            severity="high",
            title="ATO Bot has unresolved high-severity security events",
            recommendation_key="app_security_event_backlog",
            recommendation_title="Resolve high-severity security events",
            domain="Monitoring & Audit",
            score_impact=12,
            action="Triage and disposition unresolved high-severity security events so the alert backlog reflects current risk.",
            summary=f"{len(unresolved_high_events)} unresolved high-severity security event(s) are present.",
            asset_name="ato_bot_jobs",
            source_scope="live",
            observed=[_fact("Unresolved high-severity events", len(unresolved_high_events))],
            expected=[_fact("Unresolved high-severity events", 0)],
            evidence=[_fact("Event source", "security_events table")],
            fix_steps=[
                "Review each unresolved event and either remediate, resolve, or formally accept the risk.",
                "Ensure the event backlog accurately reflects current system state.",
            ],
            verification_checks=["The jobs endpoint reports unresolved high-severity events = 0 or only approved exceptions remain."],
            why_it_matters="Unresolved high-severity security events are direct indicators that the app still has untriaged security risk.",
            metadata_json={"records": unresolved_event_rows},
        ))
    if len(parse_failures_24h) >= 3:
        built_findings.append(_finding(
            finding_type="app_parser_failure_cluster",
            category="jobs",
            severity="medium",
            title="ATO Bot parsing stage is failing repeatedly",
            recommendation_key="app_parser_failure_cluster",
            recommendation_title="Resolve repeated parser-stage failures",
            domain="Monitoring & Audit",
            score_impact=6,
            action="Review parse-stage errors and stabilize the parser or input handling path.",
            summary=f"{len(parse_failures_24h)} parse-stage ingestion failure(s) were recorded in the last 24 hours.",
            asset_name="ato_bot_jobs",
            source_scope="live",
            observed=[_fact("Parse-stage failures (24h)", len(parse_failures_24h))],
            expected=[_fact("Parse-stage failures (24h)", 0)],
            evidence=[_fact("Error stage", "parse")],
            fix_steps=[
                "Review the failing parser inputs and errors.",
                "Correct the parser or document handling path and retest the affected documents.",
            ],
            verification_checks=["The jobs endpoint reports parse-stage failures at zero or reduced to the expected baseline."],
            why_it_matters="Repeated parser failures create a specific blind spot in evidence ingestion and can silently suppress downstream analysis.",
            metadata_json={"records": parse_failure_rows},
        ))

    findings = await _materialize_internal_findings(db, built_findings=built_findings, source="app_api:jobs", observed_at=now)
    recommendations = _synthesize_recommendations_from_findings(findings, source_prefix="internal:jobs")
    return {
        "summary": {
            "failed_ingestions_24h": len(failed_ingestions_24h),
            "stuck_ingestions": len(stuck_ingestions),
            "failed_assessments_7d": len(failed_assessments_7d),
            "unresolved_high_security_events": len(unresolved_high_events),
            "parse_failures_24h": len(parse_failures_24h),
            "config_changes_7d": len(config_changes_7d),
        },
        "findings": findings,
        "recommendations": recommendations,
    }


async def _build_data_protection_domain(project_id: int, db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    documents = (
        await db.execute(
            select(Document).where(Document.project_id == project_id)
        )
    ).scalars().all()
    failed_documents = [doc for doc in documents if (doc.parse_status or "").lower() in {"failed", "index_failed"}]
    pending_documents = [doc for doc in documents if (doc.parse_status or "").lower() in {"pending", "processing", "indexing"}]
    stale_pending_documents = [
        doc for doc in pending_documents
        if doc.created_at and doc.created_at <= now - timedelta(hours=24)
    ]
    upload_path = Path(settings.upload_dir).resolve()
    output_path = Path(settings.output_dir).resolve()
    upload_exists = upload_path.exists()
    output_exists = output_path.exists()
    secret_fallback_in_database = "changeme" in (settings.database_url or "").lower()
    secret_fallback_in_redis = "changeme" in (settings.redis_url or "").lower()
    local_file_storage = True
    retention_policy_defined = False
    failed_document_rows = [
        {
            "title": doc.filename or f"Document {doc.id}",
            "subtitle": f"status={doc.parse_status or 'unknown'} | doc_id={doc.id}",
        }
        for doc in failed_documents[:10]
    ]
    stale_pending_document_rows = [
        {
            "title": doc.filename or f"Document {doc.id}",
            "subtitle": " | ".join(
                part
                for part in [
                    f"status={doc.parse_status or 'unknown'}",
                    f"created={doc.created_at.isoformat()}" if doc.created_at else None,
                    f"doc_id={doc.id}",
                ]
                if part
            ),
        }
        for doc in stale_pending_documents[:10]
    ]
    storage_locations = [
        {"title": "Upload directory", "subtitle": str(upload_path)},
        {"title": "Output directory", "subtitle": str(output_path)},
    ]

    built_findings: list[dict[str, Any]] = []
    if secret_fallback_in_database or secret_fallback_in_redis:
        weak_services = []
        if secret_fallback_in_database:
            weak_services.append("database")
        if secret_fallback_in_redis:
            weak_services.append("redis")
        built_findings.append(_finding(
            finding_type="app_data_store_default_secret_fallback",
            category="data_protection",
            severity="high",
            title="ATO Bot backing services still rely on default secret fallbacks",
            recommendation_key="app_data_store_secret_posture",
            recommendation_title="Replace default backing-service credentials",
            domain="Data Protection",
            score_impact=12,
            action="Replace default database or Redis credential fallbacks with strong managed secrets before treating the deployment as trustworthy.",
            summary=f"Default credential fallback was detected in {', '.join(weak_services)} connection configuration.",
            asset_name="ato_bot_data_protection",
            source_scope="live",
            observed=[_fact("Services with fallback credentials", weak_services)],
            expected=[_fact("Services with fallback credentials", 0)],
            evidence=[_fact("Database URL", "configured"), _fact("Redis URL", "configured"), _fact("Weak services", weak_services)],
            fix_steps=[
                "Replace fallback credentials with strong unique values sourced from managed secrets.",
                "Restart the affected services after rotating the credentials.",
            ],
            verification_checks=[
                "The data-protection endpoint reports no default or fallback backing-service credentials.",
                "Database and Redis connectivity still succeeds after rotation.",
            ],
            why_it_matters="Default backing-service credentials reduce confidence in evidence protection and make unauthorized access easier if the environment is exposed.",
            history=[_fact("Stored documents", len(documents)), _fact("Failed evidence records", len(failed_documents))],
            metadata_json={
                "services": weak_services,
                "storage_locations": storage_locations,
            },
        ))
    if local_file_storage and documents:
        built_findings.append(_finding(
            finding_type="app_local_evidence_storage",
            category="data_protection",
            severity="medium",
            title="ATO Bot stores security evidence on local filesystem paths",
            recommendation_key="app_evidence_storage_hardening",
            recommendation_title="Harden local evidence storage and handling",
            domain="Data Protection",
            score_impact=7,
            action="Verify local evidence directories are access-controlled, backed up appropriately, and not exposed beyond the intended host scope.",
            summary=f"{len(documents)} project document(s) rely on local upload or output storage paths.",
            asset_name="ato_bot_data_protection",
            source_scope="live",
            observed=[_fact("Upload directory", str(upload_path)), _fact("Output directory", str(output_path)), _fact("Stored project documents", len(documents))],
            expected=[_fact("Evidence storage", "access-controlled and explicitly governed")],
            evidence=[_fact("Upload dir exists", upload_exists), _fact("Output dir exists", output_exists)],
            fix_steps=[
                "Review filesystem permissions for upload and output directories.",
                "Confirm evidence backups and host-level protections match the sensitivity of stored materials.",
            ],
            verification_checks=[
                "The data-protection endpoint reports approved storage posture for evidence directories.",
                "Evidence storage paths remain restricted to the intended host and users.",
            ],
            why_it_matters="Security evidence stored on local filesystem paths needs clear protection and handling rules to preserve confidentiality and integrity.",
            history=[_fact("Stored documents", len(documents)), _fact("Failed evidence records", len(failed_documents))],
            metadata_json={
                "storage_locations": storage_locations,
                "stored_documents": len(documents),
            },
        ))
    if not retention_policy_defined and documents:
        built_findings.append(_finding(
            finding_type="app_evidence_retention_unknown",
            category="data_protection",
            severity="medium",
            title="ATO Bot does not expose an explicit evidence retention policy",
            recommendation_key="app_evidence_retention_policy",
            recommendation_title="Define and expose evidence retention posture",
            domain="Data Protection",
            score_impact=6,
            action="Define the retention period and handling expectations for uploaded evidence, outputs, and generated artifacts.",
            summary="The app currently stores evidence but does not expose a formal retention signal through its internal security API.",
            asset_name="ato_bot_data_protection",
            source_scope="live",
            observed=[_fact("Retention policy exposed", "no"), _fact("Stored project documents", len(documents))],
            expected=[_fact("Retention policy exposed", "yes")],
            evidence=[_fact("Upload path", str(upload_path)), _fact("Output path", str(output_path))],
            fix_steps=[
                "Define the retention period and purge expectations for uploaded evidence and generated outputs.",
                "Expose that retention posture as structured security telemetry.",
            ],
            verification_checks=["The data-protection endpoint reports an explicit evidence retention posture."],
            why_it_matters="If retention and deletion expectations are unclear, sensitive evidence can persist longer than intended and weaken data protection governance.",
            history=[_fact("Stored documents", len(documents)), _fact("Upload dir exists", upload_exists), _fact("Output dir exists", output_exists)],
            metadata_json={
                "storage_locations": storage_locations,
                "retention_policy_exposed": retention_policy_defined,
            },
        ))
    if failed_documents:
        built_findings.append(_finding(
            finding_type="app_protected_evidence_processing_failures",
            category="data_protection",
            severity="medium",
            title="ATO Bot has evidence records stuck in failed processing states",
            recommendation_key="app_evidence_processing_reliability",
            recommendation_title="Resolve failed evidence processing records",
            domain="Data Protection",
            score_impact=5,
            action="Review failed evidence-processing records and restore the affected files or pipelines so the protected evidence set is complete.",
            summary=f"{len(failed_documents)} document(s) are in failed or index-failed states.",
            asset_name="ato_bot_data_protection",
            source_scope="live",
            observed=[_fact("Failed evidence records", len(failed_documents))],
            expected=[_fact("Failed evidence records", 0)],
            evidence=[_fact("Failure states", "failed, index_failed")],
            fix_steps=[
                "Inspect the failed document records and their parser or indexing errors.",
                "Reprocess or replace the affected evidence once the underlying issue is fixed.",
            ],
            verification_checks=["The data-protection endpoint reports zero failed evidence-processing records or only approved exceptions."],
            why_it_matters="Failed evidence processing creates blind spots in the evidence corpus and weakens confidence in downstream assessment results.",
            history=[_fact("Stored documents", len(documents)), _fact("Failed evidence records", len(failed_documents))],
            metadata_json={
                "failed_documents": failed_document_rows,
                "storage_locations": storage_locations,
            },
        ))
    if stale_pending_documents:
        built_findings.append(_finding(
            finding_type="app_evidence_processing_stalled",
            category="data_protection",
            severity="medium",
            title="ATO Bot has evidence records stalled in pending processing states",
            recommendation_key="app_evidence_processing_stalled",
            recommendation_title="Clear stalled evidence processing backlog",
            domain="Data Protection",
            score_impact=5,
            action="Review older pending evidence records and restore the affected parser or indexing workflow so protected material is fully available.",
            summary=f"{len(stale_pending_documents)} document(s) have remained pending, processing, or indexing for more than 24 hours.",
            asset_name="ato_bot_data_protection",
            source_scope="live",
            observed=[_fact("Stale pending evidence records", len(stale_pending_documents)), _fact("Age threshold", "24 hours")],
            expected=[_fact("Stale pending evidence records", 0)],
            evidence=[_fact("Pending states", "pending, processing, indexing")],
            fix_steps=[
                "Review the stalled evidence records and identify which pipeline stage is blocking completion.",
                "Retry, reprocess, or repair the affected evidence ingestion workflow until those records complete.",
            ],
            verification_checks=["The data-protection endpoint reports zero stale pending evidence records or only approved exceptions."],
            why_it_matters="Stalled evidence processing leaves blind spots in the evidence corpus and delays or prevents downstream security assessment.",
            history=[_fact("Stored documents", len(documents)), _fact("Pending evidence records", len(pending_documents))],
            metadata_json={
                "stale_pending_documents": stale_pending_document_rows,
                "storage_locations": storage_locations,
            },
        ))

    findings = await _materialize_internal_findings(db, built_findings=built_findings, source="app_api:data_protection", observed_at=now)
    recommendations = _synthesize_recommendations_from_findings(findings, source_prefix="internal:data_protection")
    return {
        "summary": {
            "stored_documents": len(documents),
            "failed_documents": len(failed_documents),
            "pending_documents": len(pending_documents),
            "stale_pending_documents": len(stale_pending_documents),
            "upload_dir": str(upload_path),
            "output_dir": str(output_path),
            "upload_dir_exists": upload_exists,
            "output_dir_exists": output_exists,
            "database_secret_fallback": secret_fallback_in_database,
            "redis_secret_fallback": secret_fallback_in_redis,
            "retention_policy_exposed": retention_policy_defined,
        },
        "findings": findings,
        "recommendations": recommendations,
    }


async def _build_change_events_domain(project_id: int, db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    recent_changes = (
        await db.execute(
            select(SecurityChangeEvent)
            .where(
                SecurityChangeEvent.project_id == project_id,
                SecurityChangeEvent.detected_at >= now - timedelta(days=7),
            )
            .order_by(SecurityChangeEvent.detected_at.desc(), SecurityChangeEvent.id.desc())
        )
    ).scalars().all()
    recent_config_changes = (
        await db.execute(
            select(IngestionConfigAudit).where(
                IngestionConfigAudit.changed_at >= now - timedelta(days=7),
            )
        )
    ).scalars().all()
    regressions = [item for item in recent_changes if item.impact_direction == "negative"]
    unexpected = [item for item in recent_changes if item.change_status == "needs_review"]
    event_rows = [
        {
            "title": row.summary or row.category or f"Change {row.id}",
            "subtitle": " | ".join(
                [
                    row.change_status or "observed",
                    row.impact_direction or "unknown",
                    row.details_json.get("setting_label") if isinstance(row.details_json, dict) else None,
                    row.detected_at.isoformat() if row.detected_at else None,
                ]
            ),
        }
        for row in recent_changes[:10]
    ]

    built_findings: list[dict[str, Any]] = []
    if unexpected:
        built_findings.append(_finding(
            finding_type="app_unexpected_security_drift",
            category="change_events",
            severity="high" if len(unexpected) >= 3 else "medium",
            title="ATO Bot has unexpected security drift that needs review",
            recommendation_key="app_unexpected_security_drift",
            recommendation_title="Review unexpected security drift",
            domain="Monitoring & Audit",
            score_impact=9,
            action="Review recent unexpected security changes and decide whether they are approved changes, regressions, or incidents.",
            summary=f"{len(unexpected)} recent security change event(s) are marked needs review.",
            asset_name="ato_bot_changes",
            source_scope="live",
            observed=[_fact("Unexpected security changes (7d)", len(unexpected))],
            expected=[_fact("Unexpected security changes (7d)", 0)],
            evidence=[_fact("Recent tracked changes (7d)", len(recent_changes))],
            fix_steps=[
                "Review the recent security change events and validate whether each one was planned.",
                "Document or remediate any unexpected regression.",
            ],
            verification_checks=["The change-events endpoint reports zero unexpected security changes or only approved exceptions remain."],
            why_it_matters="Unexpected security drift means the runtime can diverge from the intended secure state without a corresponding decision or review.",
            history=[_fact("Recent changes (7d)", len(recent_changes)), _fact("Unexpected changes (7d)", len(unexpected))],
            metadata_json={
                "change_events": event_rows,
                "details": {"recent_changes_7d": len(recent_changes), "unexpected_changes_7d": len(unexpected)},
            },
        ))
    if regressions:
        built_findings.append(_finding(
            finding_type="app_security_regressions_recently_detected",
            category="change_events",
            severity="medium",
            title="ATO Bot has recent security regressions",
            recommendation_key="app_security_regression_review",
            recommendation_title="Review recent security regressions",
            domain="Monitoring & Audit",
            score_impact=7,
            action="Inspect the regressed settings and determine whether the runtime or build state needs to be rolled forward or remediated.",
            summary=f"{len(regressions)} recent security change event(s) regressed posture.",
            asset_name="ato_bot_changes",
            source_scope="live",
            observed=[_fact("Security regressions (7d)", len(regressions))],
            expected=[_fact("Security regressions (7d)", 0)],
            evidence=[_fact("Change tracking source", "tracked settings history")],
            fix_steps=[
                "Review each regressed setting to confirm the current runtime value is still intended.",
                "Remediate the regressed configuration or formally accept the risk.",
            ],
            verification_checks=["The change-events endpoint reports the regressed changes as remediated, expected, or accepted risk."],
            why_it_matters="Regressions signal that the system moved away from the previously observed secure state and may need immediate review.",
            history=[_fact("Security regressions (7d)", len(regressions)), _fact("Recent changes (7d)", len(recent_changes))],
            metadata_json={
                "change_events": event_rows,
                "details": {"regressions_7d": len(regressions)},
            },
        ))
    if len(recent_config_changes) >= 5:
        config_audit_rows = [
            {
                "title": row.config_key or "Configuration change",
                "subtitle": " | ".join(
                    [
                        str(row.changed_by) if row.changed_by is not None else "unknown actor",
                        row.changed_at.isoformat() if row.changed_at else None,
                        _summarize_value(row.old_value),
                        _summarize_value(row.new_value),
                    ]
                ),
            }
            for row in recent_config_changes[:10]
        ]
        built_findings.append(_finding(
            finding_type="app_security_config_churn",
            category="change_events",
            severity="medium",
            title="ATO Bot security-relevant configuration is changing frequently",
            recommendation_key="app_security_config_churn",
            recommendation_title="Review recent configuration churn",
            domain="Configuration & Secrets",
            score_impact=5,
            action="Review recent configuration changes to ensure the churn is planned, controlled, and documented.",
            summary=f"{len(recent_config_changes)} configuration audit entries were recorded in the last 7 days.",
            asset_name="ato_bot_changes",
            source_scope="live",
            observed=[_fact("Config changes (7d)", len(recent_config_changes))],
            expected=[_fact("Config changes (7d)", "controlled baseline")],
            evidence=[_fact("Change source", "ingestion_config_audit")],
            fix_steps=[
                "Review recent configuration changes for unexpected or repeated edits.",
                "Tie frequent configuration changes back to approved change records where possible.",
            ],
            verification_checks=["The change-events endpoint shows controlled, explained configuration change volume."],
            why_it_matters="Frequent configuration churn increases the chance of unnoticed regressions and makes the secure baseline harder to trust.",
            history=[_fact("Config changes (7d)", len(recent_config_changes))],
            metadata_json={
                "change_events": config_audit_rows,
                "details": {"config_changes_7d": len(recent_config_changes)},
            },
        ))

    findings = await _materialize_internal_findings(db, built_findings=built_findings, source="app_api:change_events", observed_at=now)
    recommendations = _synthesize_recommendations_from_findings(findings, source_prefix="internal:change_events")
    return {
        "summary": {
            "recent_changes_7d": len(recent_changes),
            "unexpected_changes_7d": len(unexpected),
            "regressions_7d": len(regressions),
            "config_changes_7d": len(recent_config_changes),
        },
        "findings": findings,
        "recommendations": recommendations,
        "events": [
            {
                "id": row.id,
                "summary": row.summary,
                "impact_direction": row.impact_direction,
                "change_status": row.change_status,
                "detected_at": row.detected_at.isoformat() if row.detected_at else None,
                "details": row.details_json or {},
            }
            for row in recent_changes[:25]
        ],
    }


async def _build_detections_domain(project_id: int, db: AsyncSession) -> dict[str, Any]:
    del project_id
    now = datetime.now(UTC)
    recent_events = (
        await db.execute(
            select(SecurityEvent)
            .where(SecurityEvent.timestamp >= now - timedelta(days=7))
            .order_by(SecurityEvent.timestamp.desc(), SecurityEvent.id.desc())
        )
    ).scalars().all()
    unresolved_events = [item for item in recent_events if not item.resolved]
    high_unresolved = [item for item in unresolved_events if item.severity in {"high", "critical"}]
    suspicious_types = {"privilege_escalation", "bulk_download", "off_hours_access", "mfa_bypass_attempt"}
    suspicious_events = [item for item in recent_events if item.event_type in suspicious_types]
    detection_rows = [
        {
            "title": row.event_type,
            "subtitle": " | ".join(
                [
                    row.severity or "medium",
                    "resolved" if row.resolved else "open",
                    row.description or "",
                ]
            ),
        }
        for row in recent_events[:10]
    ]

    built_findings: list[dict[str, Any]] = []
    if high_unresolved:
        built_findings.append(_finding(
            finding_type="app_open_high_severity_detections",
            category="detections",
            severity="high",
            title="ATO Bot has unresolved high-severity detections",
            recommendation_key="app_open_detections",
            recommendation_title="Review unresolved high-severity detections",
            domain="Monitoring & Audit",
            score_impact=10,
            action="Review and disposition the unresolved high-severity detections so the detection backlog reflects current risk.",
            summary=f"{len(high_unresolved)} unresolved high-severity detection(s) were recorded in the last 7 days.",
            asset_name="ato_bot_detections",
            source_scope="live",
            observed=[_fact("Open high-severity detections", len(high_unresolved))],
            expected=[_fact("Open high-severity detections", 0)],
            evidence=[_fact("Detection source", "security_events"), _fact("Window", "7 days")],
            fix_steps=[
                "Review each open high-severity detection and triage its cause.",
                "Resolve, mitigate, or formally track the risk for each detection.",
            ],
            verification_checks=["The detections endpoint reports no unresolved high-severity detections or only approved exceptions remain."],
            why_it_matters="Open high-severity detections are direct indicators that active cyber defense still has unresolved risk to process.",
            history=[_fact("Detections (7d)", len(recent_events)), _fact("Open detections (7d)", len(unresolved_events))],
            metadata_json={
                "detections": detection_rows,
                "severity_counts": {
                    "high": len([item for item in high_unresolved if item.severity == "high"]),
                    "critical": len([item for item in high_unresolved if item.severity == "critical"]),
                },
            },
        ))
    if len(suspicious_events) >= 3:
        built_findings.append(_finding(
            finding_type="app_suspicious_detection_cluster",
            category="detections",
            severity="medium",
            title="ATO Bot is seeing a cluster of suspicious security detections",
            recommendation_key="app_suspicious_detection_cluster",
            recommendation_title="Investigate clustered suspicious detections",
            domain="Monitoring & Audit",
            score_impact=7,
            action="Investigate the recent suspicious detections and determine whether they represent real attack activity or tuning noise.",
            summary=f"{len(suspicious_events)} suspicious detection event(s) were recorded in the last 7 days.",
            asset_name="ato_bot_detections",
            source_scope="live",
            observed=[_fact("Suspicious detections (7d)", len(suspicious_events)), _fact("Event types", sorted({item.event_type for item in suspicious_events}))],
            expected=[_fact("Suspicious detections (7d)", "expected baseline")],
            evidence=[_fact("Detection source", "security_events")],
            fix_steps=[
                "Review the detection cluster and validate whether the activity was malicious, expected, or a tuning problem.",
                "Adjust controls or detection tuning based on the result.",
            ],
            verification_checks=["The detections endpoint shows suspicious detection volume returning to the expected baseline."],
            why_it_matters="A cluster of suspicious detections can indicate active abuse, policy violations, or weak detection tuning that needs attention.",
            history=[_fact("Detections (7d)", len(recent_events)), _fact("Suspicious detections (7d)", len(suspicious_events))],
            metadata_json={
                "detections": detection_rows,
                "event_types": sorted({item.event_type for item in suspicious_events}),
            },
        ))

    findings = await _materialize_internal_findings(db, built_findings=built_findings, source="app_api:detections", observed_at=now)
    recommendations = _synthesize_recommendations_from_findings(findings, source_prefix="internal:detections")
    return {
        "summary": {
            "detections_7d": len(recent_events),
            "open_detections_7d": len(unresolved_events),
            "open_high_detections_7d": len(high_unresolved),
            "suspicious_detections_7d": len(suspicious_events),
        },
        "findings": findings,
        "recommendations": recommendations,
        "detections": [
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "event_type": row.event_type,
                "severity": row.severity,
                "description": row.description,
                "resolved": row.resolved,
            }
            for row in recent_events[:25]
        ],
    }


async def _build_incidents_domain(project_id: int, db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    poams = (
        await db.execute(
            select(POAM)
            .join(Assessment, POAM.assessment_id == Assessment.id)
            .where(Assessment.project_id == project_id)
            .order_by(POAM.updated_at.desc(), POAM.id.desc())
        )
    ).scalars().all()
    open_poams = [item for item in poams if (item.status or "open") not in {"closed", "completed"}]
    overdue_poams = [item for item in open_poams if item.due_date and item.due_date < now]
    accepted_risk_poams = [item for item in poams if item.status == "accepted_risk"]
    accepted_risk_overrides = (
        await db.execute(
            select(ControlOverride).where(
                ControlOverride.project_id == project_id,
                ControlOverride.risk_accepted == True,  # noqa: E712
            )
        )
    ).scalars().all()
    active_accepted_risk_overrides = [
        item
        for item in accepted_risk_overrides
        if not item.risk_acceptance_expiry or item.risk_acceptance_expiry >= now
    ]
    unresolved_critical_events = (
        await db.execute(
            select(SecurityEvent).where(
                SecurityEvent.resolved == False,
                SecurityEvent.severity == "critical",
            )
        )
    ).scalars().all()
    incident_rows = [
        {
            "title": item.poam_id or f"POAM {item.id}",
            "subtitle": " | ".join(
                [
                    item.status or "open",
                    item.risk_level or "unknown",
                    item.control_id or "no control",
                    item.due_date.isoformat() if item.due_date else "no due date",
                ]
            ),
        }
        for item in poams[:10]
    ]
    critical_event_rows = [
        {
            "title": row.event_type,
            "subtitle": " | ".join(
                [
                    row.severity or "critical",
                    "resolved" if row.resolved else "open",
                    row.description or "",
                ]
            ),
        }
        for row in unresolved_critical_events[:10]
    ]
    accepted_risk_rows = [
        {
            "title": f"Accepted risk: {item.control_id}",
            "subtitle": " | ".join(
                part
                for part in [
                    item.risk_acceptance_rationale or "No rationale provided",
                    item.risk_acceptance_expiry.isoformat() if item.risk_acceptance_expiry else "No expiry",
                ]
                if part
            ),
        }
        for item in active_accepted_risk_overrides[:10]
    ]
    accepted_risk_total = len(accepted_risk_poams) + len(active_accepted_risk_overrides)

    built_findings: list[dict[str, Any]] = []
    if overdue_poams:
        built_findings.append(_finding(
            finding_type="app_overdue_poam_actions",
            category="incidents",
            severity="high" if len(overdue_poams) >= 3 else "medium",
            title="ATO Bot has overdue remediation actions",
            recommendation_key="app_overdue_poam_actions",
            recommendation_title="Resolve overdue remediation actions",
            domain="Remediation & Risk",
            score_impact=9,
            action="Review overdue POA&M actions and either complete, extend with justification, or accept the risk formally.",
            summary=f"{len(overdue_poams)} open remediation item(s) are past due.",
            asset_name="ato_bot_incidents",
            source_scope="live",
            observed=[_fact("Overdue POA&M items", len(overdue_poams))],
            expected=[_fact("Overdue POA&M items", 0)],
            evidence=[_fact("Incident source", "POA&M backlog")],
            fix_steps=[
                "Review each overdue remediation item and update the plan of action.",
                "Close, re-baseline, or formally accept the risk with current dates and ownership.",
            ],
            verification_checks=["The incidents endpoint reports no overdue remediation actions or only approved exceptions remain."],
            why_it_matters="Overdue remediation actions indicate known security work is not being closed fast enough to match the current risk profile.",
            history=[_fact("Open POA&M", len(open_poams)), _fact("Overdue POA&M", len(overdue_poams))],
            metadata_json={
                "incidents": incident_rows,
                "details": {"open_poams": len(open_poams), "overdue_poams": len(overdue_poams)},
            },
        ))
    if unresolved_critical_events:
        built_findings.append(_finding(
            finding_type="app_open_critical_incidents",
            category="incidents",
            severity="high",
            title="ATO Bot has unresolved critical security incidents",
            recommendation_key="app_open_critical_incidents",
            recommendation_title="Resolve critical incident backlog",
            domain="Remediation & Risk",
            score_impact=12,
            action="Treat unresolved critical incidents as active priority work until they are mitigated, resolved, or formally accepted.",
            summary=f"{len(unresolved_critical_events)} unresolved critical security event(s) are still open.",
            asset_name="ato_bot_incidents",
            source_scope="live",
            observed=[_fact("Open critical incidents", len(unresolved_critical_events))],
            expected=[_fact("Open critical incidents", 0)],
            evidence=[_fact("Incident source", "critical security events")],
            fix_steps=[
                "Review each unresolved critical event and move it through the response workflow immediately.",
                "Document the disposition and any remaining risk.",
            ],
            verification_checks=["The incidents endpoint reports zero unresolved critical incidents."],
            why_it_matters="Critical incidents that remain unresolved are the clearest indicator that tactical risk is still active and not yet contained.",
            history=[_fact("Open critical incidents", len(unresolved_critical_events)), _fact("Open POA&M", len(open_poams))],
            metadata_json={
                "incidents": critical_event_rows,
                "details": {"open_critical_incidents": len(unresolved_critical_events)},
            },
        ))
    if accepted_risk_total:
        built_findings.append(_finding(
            finding_type="app_accepted_risk_inventory",
            category="incidents",
            severity="medium",
            title="ATO Bot currently carries accepted security risk",
            recommendation_key="app_accepted_risk_review",
            recommendation_title="Review accepted-risk inventory",
            domain="Remediation & Risk",
            score_impact=4,
            action="Review accepted-risk items to make sure they are still justified, time-bounded, and visible to decision makers.",
            summary=f"{accepted_risk_total} accepted-risk item(s) are currently active for this project.",
            asset_name="ato_bot_incidents",
            source_scope="live",
            observed=[_fact("Accepted-risk items", accepted_risk_total)],
            expected=[_fact("Accepted-risk items", "current approved baseline")],
            evidence=[_fact("Incident source", "project POA&M backlog and control overrides")],
            fix_steps=[
                "Review the accepted-risk entries and verify the rationale, owner, and expiry are still valid.",
                "Close accepted risk that is no longer needed or re-open items that should be remediated.",
            ],
            verification_checks=["The incidents endpoint reports only current, justified accepted-risk items."],
            why_it_matters="Accepted risk is not necessarily wrong, but it must stay explicit, current, and visible to remain trustworthy.",
            history=[_fact("Accepted risk items", accepted_risk_total), _fact("Open POA&M", len(open_poams))],
            metadata_json={
                "incidents": [
                    *[
                        {
                            "title": item.poam_id or f"POAM {item.id}",
                            "subtitle": " | ".join(
                                [
                                    item.status or "accepted_risk",
                                    item.risk_level or "unknown",
                                    item.control_id or "no control",
                                ]
                            ),
                        }
                        for item in accepted_risk_poams[:10]
                    ],
                    *accepted_risk_rows,
                ],
                "details": {"accepted_risk_items": accepted_risk_total},
            },
        ))

    findings = await _materialize_internal_findings(db, built_findings=built_findings, source="app_api:incidents", observed_at=now)
    recommendations = _synthesize_recommendations_from_findings(findings, source_prefix="internal:incidents")
    return {
        "summary": {
            "open_poams": len(open_poams),
            "overdue_poams": len(overdue_poams),
            "accepted_risk_items": accepted_risk_total,
            "open_critical_incidents": len(unresolved_critical_events),
        },
        "findings": findings,
        "recommendations": recommendations,
        "incidents": [
            {
                "id": item.id,
                "poam_id": item.poam_id,
                "control_id": item.control_id,
                "risk_level": item.risk_level,
                "status": item.status,
                "due_date": item.due_date.isoformat() if item.due_date else None,
            }
            for item in poams[:25]
        ],
    }


def _serialize_live_asset_row(row: SecurityAsset) -> dict[str, Any]:
    return {
        "id": row.external_id or f"asset-{row.id}",
        "asset_id": row.id,
        "type": row.asset_type,
        "name": row.name,
        "criticality": row.criticality,
        "owner": "ATO Bot",
        "runtime_scope": "live",
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "metadata": row.metadata_json or {},
    }


def _live_signal(
    signal_id: str,
    *,
    domain: str,
    signal_type: str,
    value: dict[str, Any],
    source_name: str,
    observed_at: datetime | None = None,
    asset_id: str | None = None,
    severity_hint: str | None = None,
) -> dict[str, Any]:
    return {
        "id": signal_id,
        "domain": domain,
        "type": signal_type,
        "asset_id": asset_id,
        "severity_hint": severity_hint,
        "observed_at": observed_at.isoformat() if observed_at else None,
        "value": value,
        "source": {
            "kind": "app_api" if source_name == "ATO Bot internal security API" else "collector",
            "name": source_name,
        },
    }


def _build_live_state_signals(
    *,
    identity_domain: dict[str, Any],
    configuration_domain: dict[str, Any],
    jobs_domain: dict[str, Any],
    data_protection_domain: dict[str, Any],
    change_events_domain: dict[str, Any],
    detections_domain: dict[str, Any],
    latest_runtime_snapshot: SecurityRuntimeSnapshot | None,
) -> list[dict[str, Any]]:
    runtime_summary = dict(latest_runtime_snapshot.summary_json or {}) if latest_runtime_snapshot and isinstance(latest_runtime_snapshot.summary_json, dict) else {}
    collected_at = latest_runtime_snapshot.collected_at if latest_runtime_snapshot else datetime.now(UTC)
    signals: list[dict[str, Any]] = [
        _live_signal(
            "signal-identity-session-hygiene",
            domain="identity",
            signal_type="session_hygiene",
            value=dict(identity_domain.get("summary") or {}),
            source_name="ATO Bot internal security API",
            observed_at=collected_at,
            asset_id="ato_bot_identity",
            severity_hint="medium",
        ),
        _live_signal(
            "signal-configuration-posture",
            domain="configuration",
            signal_type="configuration_posture",
            value=dict(configuration_domain.get("summary") or {}),
            source_name="ATO Bot internal security API",
            observed_at=collected_at,
            asset_id="ato_bot_configuration",
            severity_hint="medium",
        ),
        _live_signal(
            "signal-jobs-posture",
            domain="jobs",
            signal_type="pipeline_health",
            value=dict(jobs_domain.get("summary") or {}),
            source_name="ATO Bot internal security API",
            observed_at=collected_at,
            asset_id="ato_bot_jobs",
            severity_hint="medium",
        ),
        _live_signal(
            "signal-data-protection-posture",
            domain="data_protection",
            signal_type="data_protection_posture",
            value=dict(data_protection_domain.get("summary") or {}),
            source_name="ATO Bot internal security API",
            observed_at=collected_at,
            asset_id="ato_bot_data_protection",
            severity_hint="medium",
        ),
        _live_signal(
            "signal-change-events",
            domain="change_events",
            signal_type="security_change_tracking",
            value=dict(change_events_domain.get("summary") or {}),
            source_name="ATO Bot internal security API",
            observed_at=collected_at,
            asset_id="ato_bot_changes",
            severity_hint="medium",
        ),
        _live_signal(
            "signal-detections",
            domain="detections",
            signal_type="security_detections",
            value=dict(detections_domain.get("summary") or {}),
            source_name="ATO Bot internal security API",
            observed_at=collected_at,
            asset_id="ato_bot_detections",
            severity_hint="high" if int((detections_domain.get("summary") or {}).get("open_high_detections_7d") or 0) > 0 else "medium",
        ),
    ]
    if runtime_summary:
        signals.append(_live_signal(
            "signal-runtime-platform",
            domain="runtime_platform",
            signal_type="runtime_platform_posture",
            value=runtime_summary,
            source_name=latest_runtime_snapshot.source or "runtime collector",
            observed_at=collected_at,
            severity_hint="medium",
        ))
    return signals


async def get_live_state_payload(project_id: int, db: AsyncSession) -> dict[str, Any]:
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalars().one_or_none()
    if not project:
        return {}

    overview = await get_security_overview(project_id, db)
    if not overview:
        return {}

    latest_runtime_snapshot = (
        await db.execute(
            select(SecurityRuntimeSnapshot)
            .where(SecurityRuntimeSnapshot.project_id == project_id)
            .order_by(SecurityRuntimeSnapshot.collected_at.desc(), SecurityRuntimeSnapshot.id.desc())
        )
    ).scalars().first()
    assets = (
        await db.execute(
            select(SecurityAsset).where(SecurityAsset.project_id == project_id).order_by(SecurityAsset.asset_type, SecurityAsset.name)
        )
    ).scalars().all()

    incidents_domain = overview.get("incidents_domain") or {}
    incident_finding_ids = {item.get("id") for item in incidents_domain.get("findings") or []}

    live_findings = [
        item
        for item in (overview.get("findings") or [])
        if item.get("source_scope") == "live" and item.get("id") not in incident_finding_ids
    ]
    live_recommendations = _synthesize_recommendations_from_findings(
        live_findings,
        source_prefix="live_state",
    )

    open_live_findings = [item for item in live_findings if item.get("status") == "open"]
    critical_findings = sum(1 for item in open_live_findings if item.get("severity") == "critical")
    high_findings = sum(1 for item in open_live_findings if item.get("severity") == "high")
    live_score = _compute_score_from_recommendations(live_recommendations)

    if critical_findings or high_findings:
        trust = "low"
    elif open_live_findings:
        trust = "medium"
    else:
        trust = "high"

    return {
        "system": {
            "id": f"project-{project.id}",
            "name": project.name,
            "environment": (project.system_type or "application"),
            "collected_at": datetime.now(UTC).isoformat(),
            "version": (overview.get("latest_build_snapshot") or {}).get("version"),
            "build_label": (overview.get("latest_build_snapshot") or {}).get("label"),
            "commit_ref": (overview.get("latest_build_snapshot") or {}).get("commit_ref"),
        },
        "assets": [_serialize_live_asset_row(row) for row in assets],
        "signals": _build_live_state_signals(
            identity_domain=overview.get("identity_domain") or {},
            configuration_domain=overview.get("configuration_domain") or {},
            jobs_domain=overview.get("jobs_domain") or {},
            data_protection_domain=overview.get("data_protection_domain") or {},
            change_events_domain=overview.get("change_events_domain") or {},
            detections_domain=overview.get("detections_domain") or {},
            latest_runtime_snapshot=latest_runtime_snapshot,
        ),
        "findings": live_findings,
        "recommendations": live_recommendations,
        "risk_state": {
            "live_score": live_score.get("percentage"),
            "trust": trust,
            "critical_findings": critical_findings,
            "high_findings": high_findings,
            "gate_breaches": [],
            "drift_since_build": (overview.get("summary") or {}).get("changes_since_build", 0),
        },
        "change_events": overview.get("recent_changes") or [],
        "detections": (overview.get("detections_domain") or {}).get("detections") or [],
    }


async def _ensure_verification_check(
    db: AsyncSession,
    *,
    check_key: str,
    name: str,
    domain: str,
    control_id: str | None,
    source_scope: str,
    freshness_minutes: int,
    description: str,
) -> VerificationCheck:
    row = (
        await db.execute(
            select(VerificationCheck).where(VerificationCheck.check_key == check_key)
        )
    ).scalars().one_or_none()
    if row:
        row.name = name
        row.domain = domain
        row.control_id = control_id
        row.source_scope = source_scope
        row.freshness_minutes = freshness_minutes
        row.description = description
        return row

    row = VerificationCheck(
        check_key=check_key,
        name=name,
        domain=domain,
        control_id=control_id,
        source_scope=source_scope,
        verifier_type="deterministic",
        freshness_minutes=freshness_minutes,
        description=description,
    )
    db.add(row)
    await db.flush()
    return row


async def _record_verification_result(
    db: AsyncSession,
    *,
    check: VerificationCheck,
    project_id: int,
    asset_id: int | None,
    result: str,
    summary: str,
    confidence: str,
    evidence: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    verified_at: datetime | None = None,
) -> VerificationResult:
    verified_at = verified_at or datetime.now(UTC)
    expires_at = verified_at + timedelta(minutes=max(int(check.freshness_minutes or 60), 1))
    row = VerificationResult(
        check_id=check.id,
        project_id=project_id,
        asset_id=asset_id,
        result=result,
        summary=summary,
        confidence=confidence,
        verified_at=verified_at,
        expires_at=expires_at,
        evidence_json=evidence,
        metadata_json=metadata or {},
    )
    db.add(row)
    await db.flush()
    return row


def _latest_result_by_check(rows: list[VerificationResult]) -> dict[int, VerificationResult]:
    latest: dict[int, VerificationResult] = {}
    for row in rows:
        current = latest.get(row.check_id)
        if not current or (row.verified_at or datetime.min.replace(tzinfo=UTC)) > (current.verified_at or datetime.min.replace(tzinfo=UTC)):
            latest[row.check_id] = row
    return latest


async def _get_latest_verification_pairs(project_id: int, db: AsyncSession) -> list[tuple[VerificationCheck, VerificationResult]]:
    checks = (
        await db.execute(select(VerificationCheck).order_by(VerificationCheck.domain, VerificationCheck.name))
    ).scalars().all()
    if not checks:
        return []
    results = (
        await db.execute(
            select(VerificationResult)
            .where(VerificationResult.project_id == project_id)
            .order_by(VerificationResult.verified_at.desc(), VerificationResult.id.desc())
        )
    ).scalars().all()
    latest = _latest_result_by_check(results)
    pairs: list[tuple[VerificationCheck, VerificationResult]] = []
    for check in checks:
        result = latest.get(check.id)
        if result:
            pairs.append((check, result))
    return pairs


def _verification_output(check: VerificationCheck, result: VerificationResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "check_id": check.id,
        "check_key": check.check_key,
        "name": check.name,
        "domain": check.domain,
        "control_id": check.control_id,
        "source_scope": check.source_scope,
        "verifier_type": check.verifier_type,
        "freshness_minutes": check.freshness_minutes,
        "description": check.description,
        "result": result.result,
        "summary": result.summary,
        "confidence": result.confidence,
        "verified_at": result.verified_at.isoformat() if result.verified_at else None,
        "expires_at": result.expires_at.isoformat() if result.expires_at else None,
        "evidence": result.evidence_json or {},
        "metadata": result.metadata_json or {},
        "is_fresh": bool(result.expires_at and result.expires_at >= datetime.now(UTC)),
    }


async def run_security_verifications(project_id: int, db: AsyncSession) -> dict[str, Any]:
    project_exists = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
    if not project_exists:
        return {}

    now = datetime.now(UTC)
    identity_domain = await _build_identity_domain(project_id, db)
    configuration_domain = await _build_configuration_domain(project_id, db)
    jobs_domain = await _build_jobs_domain(project_id, db)
    data_protection_domain = await _build_data_protection_domain(project_id, db)
    detections_domain = await _build_detections_domain(project_id, db)

    assets = (
        await db.execute(select(SecurityAsset).where(SecurityAsset.project_id == project_id))
    ).scalars().all()
    asset_ids_by_name = {row.name: row.id for row in assets}

    latest_runtime_snapshot = (
        await db.execute(
            select(SecurityRuntimeSnapshot)
            .where(SecurityRuntimeSnapshot.project_id == project_id)
            .order_by(SecurityRuntimeSnapshot.collected_at.desc(), SecurityRuntimeSnapshot.id.desc())
        )
    ).scalars().first()
    runtime_source = latest_runtime_snapshot.source if latest_runtime_snapshot else None
    runtime_findings: list[SecurityFinding] = []
    if runtime_source:
        runtime_findings = (
            await db.execute(
                select(SecurityFinding).where(
                    SecurityFinding.project_id == project_id,
                    SecurityFinding.source == runtime_source,
                    SecurityFinding.status == "open",
                )
            )
        ).scalars().all()

    hardening_titles = (
        "does not run as non-root",
        "does not drop linux capabilities",
        "writable root filesystem",
        "runs in privileged mode",
        "uses a mutable image tag",
        "has no container healthcheck",
        "published port",
    )
    runtime_hardening_findings = [
        row for row in runtime_findings
        if any(fragment in (row.title or "").lower() for fragment in hardening_titles)
    ]
    host_patch_findings = [
        row for row in runtime_findings
        if "missing security updates" in (row.title or "").lower()
    ]

    checks_to_run: list[dict[str, Any]] = []

    identity_summary = identity_domain.get("summary") or {}
    privileged_without_mfa = int(identity_summary.get("privileged_without_mfa") or 0)
    identity_finding_ids = [item.get("id") for item in identity_domain.get("findings") or []]
    identity_recommendation_ids = [item.get("id") for item in identity_domain.get("recommendations") or []]
    checks_to_run.append({
        "check_key": "verify_privileged_mfa_coverage",
        "name": "Verify privileged MFA coverage",
        "domain": "identity",
        "control_id": "IA-2",
        "source_scope": "live",
        "freshness_minutes": 60,
        "description": "Confirm that all privileged application users require MFA.",
        "asset_id": asset_ids_by_name.get("ato_bot_identity"),
        "result": "pass" if privileged_without_mfa == 0 else "fail",
        "summary": "All privileged application users require MFA." if privileged_without_mfa == 0 else f"{privileged_without_mfa} privileged account(s) lack MFA.",
        "confidence": "high",
        "evidence": {
            "observed": {
                "privileged_users": int(identity_summary.get("privileged_users") or 0),
                "privileged_without_mfa": privileged_without_mfa,
            },
            "expected": {"privileged_without_mfa": 0},
            "records": [item.get("metadata", {}).get("records", []) for item in identity_domain.get("findings") or [] if item.get("finding_type") == "app_privileged_accounts_missing_mfa"][:1],
        },
        "related_finding_ids": identity_finding_ids,
        "related_recommendation_ids": identity_recommendation_ids,
    })

    expired_unrevoked = int(identity_summary.get("expired_unrevoked_refresh_tokens") or 0)
    stale_sessions = int(identity_summary.get("stale_refresh_sessions") or 0)
    token_result = "pass"
    if expired_unrevoked > 0:
        token_result = "fail"
    elif stale_sessions > 0:
        token_result = "degraded"
    checks_to_run.append({
        "check_key": "verify_refresh_token_hygiene",
        "name": "Verify refresh token hygiene",
        "domain": "identity",
        "control_id": "IA-2",
        "source_scope": "live",
        "freshness_minutes": 60,
        "description": "Confirm refresh tokens are revoked, rotated, and not retained beyond accepted age thresholds.",
        "asset_id": asset_ids_by_name.get("ato_bot_identity"),
        "result": token_result,
        "summary": (
            "Refresh token hygiene is within policy."
            if token_result == "pass"
            else f"Refresh token hygiene is degraded: {expired_unrevoked} expired unrevoked token(s), {stale_sessions} stale active session(s)."
        ),
        "confidence": "high",
        "evidence": {
            "observed": {
                "active_refresh_sessions": int(identity_summary.get("active_refresh_sessions") or 0),
                "expired_unrevoked_refresh_tokens": expired_unrevoked,
                "stale_refresh_sessions": stale_sessions,
            },
            "expected": {
                "expired_unrevoked_refresh_tokens": 0,
                "stale_refresh_sessions": 0,
            },
        },
        "related_finding_ids": identity_finding_ids,
        "related_recommendation_ids": identity_recommendation_ids,
    })

    config_summary = configuration_domain.get("summary") or {}
    configuration_finding_ids = [item.get("id") for item in configuration_domain.get("findings") or []]
    configuration_recommendation_ids = [item.get("id") for item in configuration_domain.get("recommendations") or []]
    wildcard_cors = bool(config_summary.get("wildcard_cors"))
    csp_inline_scripts = bool(config_summary.get("csp_inline_scripts"))
    csp_inline_styles = bool(config_summary.get("csp_inline_styles"))
    weak_secret = bool(config_summary.get("weak_secret"))
    weak_session_policy = bool(config_summary.get("weak_session_policy"))
    header_result = "pass"
    if wildcard_cors or csp_inline_scripts or weak_secret:
        header_result = "fail"
    elif csp_inline_styles or weak_session_policy:
        header_result = "degraded"
    checks_to_run.append({
        "check_key": "verify_security_headers_emitted",
        "name": "Verify security header and configuration posture",
        "domain": "configuration",
        "control_id": "CM-6",
        "source_scope": "live",
        "freshness_minutes": 60,
        "description": "Confirm the running application emits the expected secure header and session posture.",
        "asset_id": asset_ids_by_name.get("ato_bot_configuration"),
        "result": header_result,
        "summary": (
            "Security header and session posture is within policy."
            if header_result == "pass"
            else "Security header and session posture still has material deviations from the expected baseline."
        ),
        "confidence": "high",
        "evidence": {
            "observed": {
                "wildcard_cors": wildcard_cors,
                "csp_inline_scripts": csp_inline_scripts,
                "csp_inline_styles": csp_inline_styles,
                "weak_secret": weak_secret,
                "weak_session_policy": weak_session_policy,
            },
            "expected": {
                "wildcard_cors": False,
                "csp_inline_scripts": False,
                "weak_secret": False,
            },
        },
        "related_finding_ids": configuration_finding_ids,
        "related_recommendation_ids": configuration_recommendation_ids,
    })

    jobs_summary = jobs_domain.get("summary") or {}
    jobs_finding_ids = [item.get("id") for item in jobs_domain.get("findings") or []]
    jobs_recommendation_ids = [item.get("id") for item in jobs_domain.get("recommendations") or []]
    stuck_ingestions = int(jobs_summary.get("stuck_ingestions") or 0)
    failed_ingestions = int(jobs_summary.get("failed_ingestions_24h") or 0)
    failed_assessments = int(jobs_summary.get("failed_assessments_7d") or 0)
    unresolved_high_events = int(jobs_summary.get("unresolved_high_security_events") or 0)
    parse_failures = int(jobs_summary.get("parse_failures_24h") or 0)
    jobs_result = "pass"
    if stuck_ingestions > 0 or unresolved_high_events > 0:
        jobs_result = "fail"
    elif failed_ingestions > 0 or failed_assessments > 0 or parse_failures > 0:
        jobs_result = "degraded"
    checks_to_run.append({
        "check_key": "verify_ingestion_pipeline_health",
        "name": "Verify ingestion and assessment pipeline health",
        "domain": "jobs",
        "control_id": "AU-6",
        "source_scope": "live",
        "freshness_minutes": 30,
        "description": "Confirm ingestion and assessment jobs are not stuck and the monitoring pipeline is producing current evidence.",
        "asset_id": asset_ids_by_name.get("ato_bot_jobs"),
        "result": jobs_result,
        "summary": (
            "Ingestion and assessment pipelines are healthy."
            if jobs_result == "pass"
            else f"Pipeline health is degraded: {stuck_ingestions} stuck ingestion(s), {failed_ingestions} failed ingestion(s), {failed_assessments} failed assessment(s), {unresolved_high_events} unresolved high event(s)."
        ),
        "confidence": "high",
        "evidence": {
            "observed": {
                "stuck_ingestions": stuck_ingestions,
                "failed_ingestions_24h": failed_ingestions,
                "failed_assessments_7d": failed_assessments,
                "unresolved_high_security_events": unresolved_high_events,
                "parse_failures_24h": parse_failures,
            },
            "expected": {
                "stuck_ingestions": 0,
                "unresolved_high_security_events": 0,
            },
        },
        "related_finding_ids": jobs_finding_ids,
        "related_recommendation_ids": jobs_recommendation_ids,
    })

    runtime_result = "pass" if not runtime_hardening_findings else "fail"
    checks_to_run.append({
        "check_key": "verify_container_runtime_hardening",
        "name": "Verify container runtime hardening",
        "domain": "runtime_platform",
        "control_id": "CM-6",
        "source_scope": "live",
        "freshness_minutes": 60,
        "description": "Confirm the current runtime snapshot does not show unresolved container hardening regressions.",
        "asset_id": None,
        "result": runtime_result,
        "summary": (
            "Current runtime snapshot shows no unresolved container hardening findings."
            if runtime_result == "pass"
            else f"{len(runtime_hardening_findings)} unresolved runtime hardening finding(s) remain open."
        ),
        "confidence": "medium" if latest_runtime_snapshot else "low",
        "evidence": {
            "observed": {
                "runtime_source": runtime_source,
                "open_runtime_hardening_findings": len(runtime_hardening_findings),
                "titles": [row.title for row in runtime_hardening_findings[:10]],
            },
            "expected": {"open_runtime_hardening_findings": 0},
        },
        "related_finding_ids": [row.id for row in runtime_hardening_findings],
        "related_recommendation_ids": [],
    })

    data_summary = data_protection_domain.get("summary") or {}
    data_finding_ids = [item.get("id") for item in data_protection_domain.get("findings") or []]
    data_recommendation_ids = [item.get("id") for item in data_protection_domain.get("recommendations") or []]
    db_fallback = bool(data_summary.get("database_secret_fallback"))
    redis_fallback = bool(data_summary.get("redis_secret_fallback"))
    stale_pending_docs = int(data_summary.get("stale_pending_documents") or 0)
    failed_docs = int(data_summary.get("failed_documents") or 0)
    retention_exposed = bool(data_summary.get("retention_policy_exposed"))
    data_result = "pass"
    if db_fallback or redis_fallback or stale_pending_docs > 0 or failed_docs > 0:
        data_result = "fail"
    elif not retention_exposed:
        data_result = "degraded"
    checks_to_run.append({
        "check_key": "verify_evidence_storage_posture",
        "name": "Verify evidence storage and retention posture",
        "domain": "data_protection",
        "control_id": "SC-28",
        "source_scope": "live",
        "freshness_minutes": 60,
        "description": "Confirm protected evidence storage uses acceptable credential posture and exposes a defined retention state.",
        "asset_id": asset_ids_by_name.get("ato_bot_data_protection"),
        "result": data_result,
        "summary": (
            "Evidence storage posture is within policy."
            if data_result == "pass"
            else "Evidence storage posture still has unresolved protection or retention gaps."
        ),
        "confidence": "high",
        "evidence": {
            "observed": {
                "database_secret_fallback": db_fallback,
                "redis_secret_fallback": redis_fallback,
                "stale_pending_documents": stale_pending_docs,
                "failed_documents": failed_docs,
                "retention_policy_exposed": retention_exposed,
            },
            "expected": {
                "database_secret_fallback": False,
                "redis_secret_fallback": False,
                "stale_pending_documents": 0,
                "retention_policy_exposed": True,
            },
        },
        "related_finding_ids": data_finding_ids,
        "related_recommendation_ids": data_recommendation_ids,
    })

    detections_summary = detections_domain.get("summary") or {}
    detection_finding_ids = [item.get("id") for item in detections_domain.get("findings") or []]
    detection_recommendation_ids = [item.get("id") for item in detections_domain.get("recommendations") or []]
    detection_signal_ids = [f"detection-{item.get('id')}" for item in detections_domain.get("detections") or [] if not item.get("resolved")]
    open_detections = int(detections_summary.get("open_detections_7d") or 0)
    open_high_detections = int(detections_summary.get("open_high_detections_7d") or 0)
    suspicious_detections = int(detections_summary.get("suspicious_detections_7d") or 0)
    detections_result = "pass"
    if open_high_detections > 0:
        detections_result = "fail"
    elif open_detections > 0 or suspicious_detections > 0:
        detections_result = "degraded"
    checks_to_run.append({
        "check_key": "verify_detection_backlog",
        "name": "Verify security detection backlog",
        "domain": "detections",
        "control_id": "SI-4",
        "source_scope": "live",
        "freshness_minutes": 30,
        "description": "Confirm unresolved security detections remain within acceptable thresholds.",
        "asset_id": asset_ids_by_name.get("ato_bot_detections"),
        "result": detections_result,
        "summary": (
            "Security detection backlog is within threshold."
            if detections_result == "pass"
            else f"Detection backlog needs review: {open_detections} open detection(s), {open_high_detections} high severity."
        ),
        "confidence": "medium",
        "evidence": {
            "observed": {
                "open_detections_7d": open_detections,
                "open_high_detections_7d": open_high_detections,
                "suspicious_detections_7d": suspicious_detections,
            },
            "expected": {"open_high_detections_7d": 0},
        },
        "related_finding_ids": detection_finding_ids,
        "related_recommendation_ids": detection_recommendation_ids,
        "related_signal_ids": detection_signal_ids,
    })

    if host_patch_findings:
        checks_to_run.append({
            "check_key": "verify_host_patch_backlog",
            "name": "Verify host patch backlog",
            "domain": "runtime_platform",
            "control_id": "SI-2",
            "source_scope": "live",
            "freshness_minutes": 240,
            "description": "Confirm host patch backlog is within acceptable threshold.",
            "asset_id": None,
            "result": "fail",
            "summary": f"{len(host_patch_findings)} host patch finding(s) remain open and require host-admin remediation.",
            "confidence": "medium",
            "evidence": {
                "observed": {"open_host_patch_findings": len(host_patch_findings), "titles": [row.title for row in host_patch_findings[:10]]},
                "expected": {"open_host_patch_findings": 0},
            },
            "related_finding_ids": [row.id for row in host_patch_findings],
            "related_recommendation_ids": [],
        })

    outputs: list[dict[str, Any]] = []
    for item in checks_to_run:
        check = await _ensure_verification_check(
            db,
            check_key=item["check_key"],
            name=item["name"],
            domain=item["domain"],
            control_id=item["control_id"],
            source_scope=item["source_scope"],
            freshness_minutes=item["freshness_minutes"],
            description=item["description"],
        )
        result_row = await _record_verification_result(
            db,
            check=check,
            project_id=project_id,
            asset_id=item["asset_id"],
            result=item["result"],
            summary=item["summary"],
            confidence=item["confidence"],
            evidence=item["evidence"],
            metadata={
                "project_id": project_id,
                "generated_at": now.isoformat(),
                "check_key": item["check_key"],
                "related_finding_ids": [str(value) for value in (item.get("related_finding_ids") or [])],
                "related_recommendation_ids": [str(value) for value in (item.get("related_recommendation_ids") or [])],
                "related_signal_ids": [str(value) for value in (item.get("related_signal_ids") or [])],
            },
            verified_at=now,
        )
        outputs.append(_verification_output(check, result_row))

    await db.commit()
    return {
        "generated_at": now.isoformat(),
        "project_id": project_id,
        "results": outputs,
    }


async def get_security_verifications(project_id: int, db: AsyncSession) -> dict[str, Any]:
    pairs = await _get_latest_verification_pairs(project_id, db)
    if not pairs:
        return await run_security_verifications(project_id, db)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "project_id": project_id,
        "results": [_verification_output(check, result) for check, result in pairs],
    }


async def get_control_support(project_id: int, db: AsyncSession) -> dict[str, Any]:
    verification_payload = await get_security_verifications(project_id, db)
    results = verification_payload.get("results") or []

    capability_map = {
        "IA-2": "Identification and Authentication",
        "CM-6": "Configuration Baseline Enforcement",
        "AU-6": "Audit and Monitoring Review",
        "SI-2": "Flaw Remediation",
        "SI-4": "System Monitoring",
        "SC-28": "Protection of Information at Rest",
    }
    grouped: dict[str, dict[str, Any]] = {}
    for item in results:
        control_id = item.get("control_id")
        if not control_id:
            continue
        current = grouped.setdefault(
            control_id,
            {
                "control_id": control_id,
                "capability": capability_map.get(control_id, control_id),
                "status": "pass",
                "confidence": "high",
                "last_verified_at": item.get("verified_at"),
                "expires_at": item.get("expires_at"),
                "evidence_refs": [],
                "failed_checks": [],
                "checks": [],
                "related_finding_ids": [],
                "related_recommendation_ids": [],
                "related_signal_ids": [],
            },
        )
        current["checks"].append(item)
        current["evidence_refs"].append(item.get("check_key"))
        current["related_finding_ids"].extend(item.get("metadata", {}).get("related_finding_ids") or [])
        current["related_recommendation_ids"].extend(item.get("metadata", {}).get("related_recommendation_ids") or [])
        current["related_signal_ids"].extend(item.get("metadata", {}).get("related_signal_ids") or [])
        if item.get("result") == "fail":
            current["status"] = "fail"
            current["failed_checks"].append(item.get("check_key"))
        elif item.get("result") == "degraded" and current["status"] != "fail":
            current["status"] = "degraded"
            current["failed_checks"].append(item.get("check_key"))
        if item.get("confidence") == "low":
            current["confidence"] = "low"
        elif item.get("confidence") == "medium" and current["confidence"] == "high":
            current["confidence"] = "medium"
        if item.get("verified_at") and (not current["last_verified_at"] or item["verified_at"] > current["last_verified_at"]):
            current["last_verified_at"] = item["verified_at"]
        if item.get("expires_at") and (not current["expires_at"] or item["expires_at"] < current["expires_at"]):
            current["expires_at"] = item["expires_at"]

    controls = sorted(grouped.values(), key=lambda item: item["control_id"])
    for item in controls:
        item["related_finding_ids"] = sorted({str(value) for value in item.get("related_finding_ids") or []})
        item["related_recommendation_ids"] = sorted({str(value) for value in item.get("related_recommendation_ids") or []})
        item["related_signal_ids"] = sorted({str(value) for value in item.get("related_signal_ids") or []})
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "project_id": project_id,
        "controls": controls,
    }


async def get_security_overview(project_id: int, db: AsyncSession) -> dict[str, Any]:
    project_exists = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
    if not project_exists:
        return {}

    findings = (
        await db.execute(
            select(SecurityFinding).where(SecurityFinding.project_id == project_id).order_by(SecurityFinding.detected_at.desc(), SecurityFinding.id.desc())
        )
    ).scalars().all()
    recommendations = (
        await db.execute(
            select(SecurityRecommendation).where(SecurityRecommendation.project_id == project_id).order_by(SecurityRecommendation.score_impact.desc(), SecurityRecommendation.updated_at.desc())
        )
    ).scalars().all()
    assets = (
        await db.execute(
            select(SecurityAsset).where(SecurityAsset.project_id == project_id).order_by(SecurityAsset.asset_type, SecurityAsset.name)
        )
    ).scalars().all()
    collectors = (
        await db.execute(
            select(SecurityCollector).where(SecurityCollector.project_id == project_id).order_by(SecurityCollector.created_at.desc())
        )
    ).scalars().all()
    latest_build_snapshot = (
        await db.execute(
            select(SecurityBuildSnapshot)
            .where(SecurityBuildSnapshot.project_id == project_id)
            .order_by(SecurityBuildSnapshot.build_date.desc(), SecurityBuildSnapshot.id.desc())
        )
    ).scalars().first()
    latest_runtime_snapshot = (
        await db.execute(
            select(SecurityRuntimeSnapshot)
            .where(SecurityRuntimeSnapshot.project_id == project_id)
            .order_by(SecurityRuntimeSnapshot.collected_at.desc(), SecurityRuntimeSnapshot.id.desc())
        )
    ).scalars().first()
    change_events = (
        await db.execute(
            select(SecurityChangeEvent)
            .where(SecurityChangeEvent.project_id == project_id)
            .order_by(SecurityChangeEvent.detected_at.desc(), SecurityChangeEvent.id.desc())
        )
    ).scalars().all()

    identity_domain = await _build_identity_domain(project_id, db)
    configuration_domain = await _build_configuration_domain(project_id, db)
    jobs_domain = await _build_jobs_domain(project_id, db)
    data_protection_domain = await _build_data_protection_domain(project_id, db)
    change_events_domain = await _build_change_events_domain(project_id, db)
    detections_domain = await _build_detections_domain(project_id, db)
    incidents_domain = await _build_incidents_domain(project_id, db)

    latest_runtime_source = latest_runtime_snapshot.source if latest_runtime_snapshot else None
    latest_build_source = f"build:{latest_build_snapshot.collector_id}" if latest_build_snapshot and latest_build_snapshot.collector_id else None

    current_findings: list[SecurityFinding] = []
    for row in findings:
        source = row.source or ""
        if source.startswith("collector:"):
            if latest_runtime_source and source == latest_runtime_source and row.status == "open":
                current_findings.append(row)
            continue
        if source.startswith("build:"):
            if latest_build_source and source == latest_build_source and row.status == "open":
                current_findings.append(row)
            continue
        if row.status == "open":
            current_findings.append(row)

    serialized_findings = [_serialize_finding_row(row) for row in current_findings]
    internal_findings = (
        identity_domain["findings"]
        + configuration_domain["findings"]
        + jobs_domain["findings"]
        + data_protection_domain["findings"]
        + change_events_domain["findings"]
        + detections_domain["findings"]
        + incidents_domain["findings"]
    )
    all_findings = serialized_findings + internal_findings

    serialized_recommendations = [_serialize_recommendation_row(row) for row in recommendations]
    internal_recommendations = (
        identity_domain["recommendations"]
        + configuration_domain["recommendations"]
        + jobs_domain["recommendations"]
        + data_protection_domain["recommendations"]
        + change_events_domain["recommendations"]
        + detections_domain["recommendations"]
        + incidents_domain["recommendations"]
    )
    all_recommendations = sorted(
        serialized_recommendations + internal_recommendations,
        key=lambda item: (-int(item.get("score_impact") or 0), -_severity_rank(item.get("severity") or "")),
    )

    open_findings = [item for item in all_findings if item["status"] == "open"]
    critical = sum(1 for item in open_findings if item["severity"] == "critical")
    high = sum(1 for item in open_findings if item["severity"] == "high")
    medium = sum(1 for item in open_findings if item["severity"] == "medium")
    low = sum(1 for item in open_findings if item["severity"] == "low")

    score = _compute_score_from_recommendations(all_recommendations)
    changes_since_build = 0
    if latest_build_snapshot:
        changes_since_build = sum(1 for item in change_events if item.detected_at >= latest_build_snapshot.build_date)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "secure_score": score,
        "summary": {
            "critical_findings": critical,
            "high_findings": high,
            "medium_findings": medium,
            "low_findings": low,
            "open_findings": len(open_findings),
            "collector_count": len(collectors),
            "asset_count": len(assets),
            "recommendation_count": len(all_recommendations),
            "changes_since_build": changes_since_build,
        },
        "collectors": [
            {
                "id": row.id,
                "name": row.name,
                "collector_type": row.collector_type,
                "status": row.status,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            }
            for row in collectors
        ],
        "assets": [
            {
                "id": row.id,
                "asset_type": row.asset_type,
                "name": row.name,
                "criticality": row.criticality,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                "metadata": row.metadata_json or {},
            }
            for row in assets
        ],
        "findings": all_findings,
        "recommendations": all_recommendations,
        "latest_build_snapshot": (
            {
                "id": latest_build_snapshot.id,
                "label": latest_build_snapshot.label,
                "version": latest_build_snapshot.version,
                "commit_ref": latest_build_snapshot.commit_ref,
                "source": latest_build_snapshot.source,
                "status": latest_build_snapshot.status,
                "build_date": latest_build_snapshot.build_date.isoformat() if latest_build_snapshot.build_date else None,
                "security_score": latest_build_snapshot.security_score,
                "summary": latest_build_snapshot.summary_json or {},
            }
            if latest_build_snapshot else None
        ),
        "latest_runtime_snapshot": (
            {
                "id": latest_runtime_snapshot.id,
                "source": latest_runtime_snapshot.source,
                "collected_at": latest_runtime_snapshot.collected_at.isoformat() if latest_runtime_snapshot.collected_at else None,
                "security_score": latest_runtime_snapshot.security_score,
                "summary": latest_runtime_snapshot.summary_json or {},
            }
            if latest_runtime_snapshot else None
        ),
        "recent_changes": [
            {
                "id": row.id,
                "asset_id": row.asset_id,
                "tracked_setting_id": row.tracked_setting_id,
                "event_type": row.event_type,
                "category": row.category,
                "old_value": row.old_value_json,
                "new_value": row.new_value_json,
                "detected_at": row.detected_at.isoformat() if row.detected_at else None,
                "source_snapshot_type": row.source_snapshot_type,
                "source_snapshot_id": row.source_snapshot_id,
                "impact_level": row.impact_level,
                "impact_direction": row.impact_direction,
                "change_status": row.change_status,
                "summary": row.summary,
                "details": row.details_json or {},
            }
            for row in change_events[:25]
        ],
        "identity_domain": identity_domain,
        "configuration_domain": configuration_domain,
        "jobs_domain": jobs_domain,
        "data_protection_domain": data_protection_domain,
        "change_events_domain": change_events_domain,
        "detections_domain": detections_domain,
        "incidents_domain": incidents_domain,
    }
