"""System-level assessment policy services."""
from __future__ import annotations

from datetime import UTC, datetime
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import AssessmentPolicy, AssessmentPolicyBucket
from app.services.controls.catalog import load_catalog

DEFAULT_POLICY_NAME = "ATO Bot Default Assessment Policy"
DEFAULT_POLICY_VERSION = 1

DEFAULT_THRESHOLDS = {
    "compliant_threshold": 0.85,
    "partial_threshold": 0.45,
    "minimum_evidence_quality_for_compliant": 0.65,
    "max_contradiction_for_compliant": 0.15,
    "critical_failure_blocks_compliant": True,
    "manual_review_contradiction_threshold": 0.20,
    "manual_review_weak_evidence_threshold": 0.35,
    "manual_review_inheritance_without_authority": False,
    "manual_review_compensating_without_authority": True,
}

DEFAULT_MAPPING_RULES = {
    "precedence": [
        "objective_override",
        "control_override",
        "control_family_rule",
        "objective_text_rule",
        "default_bucket",
    ],
    "default_bucket": "procedure_execution",
}

DEFAULT_BUCKETS = [
    {
        "bucket_key": "policy_governance",
        "label": "Policy Governance",
        "description": "Policy existence, responsibility, and review cadence objectives.",
        "sort_order": 10,
        "objective_weight": 0.80,
        "critical_by_default": False,
        "minimum_evidence_strength": 0.50,
        "negative_evidence_penalty": 0.20,
        "contradiction_penalty": 0.15,
        "future_state_cap": 0.40,
        "inheritance_allowed": True,
        "compensating_allowed": False,
        "confidence_cap_if_only_weak_evidence": 0.70,
        "confidence_cap_if_compensating_only": None,
    },
    {
        "bucket_key": "procedure_execution",
        "label": "Procedure Execution",
        "description": "Operational procedures, workflows, and approval sequence objectives.",
        "sort_order": 20,
        "objective_weight": 1.00,
        "critical_by_default": False,
        "minimum_evidence_strength": 0.55,
        "negative_evidence_penalty": 0.25,
        "contradiction_penalty": 0.20,
        "future_state_cap": 0.40,
        "inheritance_allowed": True,
        "compensating_allowed": True,
        "confidence_cap_if_only_weak_evidence": 0.72,
        "confidence_cap_if_compensating_only": None,
    },
    {
        "bucket_key": "technical_enforcement",
        "label": "Technical Enforcement",
        "description": "Runtime enforcement, configuration, and direct technical safeguard objectives.",
        "sort_order": 30,
        "objective_weight": 1.30,
        "critical_by_default": False,
        "minimum_evidence_strength": 0.70,
        "negative_evidence_penalty": 0.30,
        "contradiction_penalty": 0.25,
        "future_state_cap": 0.25,
        "inheritance_allowed": False,
        "compensating_allowed": True,
        "confidence_cap_if_only_weak_evidence": 0.68,
        "confidence_cap_if_compensating_only": None,
    },
    {
        "bucket_key": "monitoring_audit",
        "label": "Monitoring and Audit",
        "description": "Logging, alerting, monitoring, and review objectives.",
        "sort_order": 40,
        "objective_weight": 1.10,
        "critical_by_default": False,
        "minimum_evidence_strength": 0.65,
        "negative_evidence_penalty": 0.25,
        "contradiction_penalty": 0.25,
        "future_state_cap": 0.30,
        "inheritance_allowed": True,
        "compensating_allowed": True,
        "confidence_cap_if_only_weak_evidence": 0.70,
        "confidence_cap_if_compensating_only": None,
    },
    {
        "bucket_key": "crypto_and_key_management",
        "label": "Crypto and Key Management",
        "description": "Encryption, key management, and certificate-handling objectives.",
        "sort_order": 50,
        "objective_weight": 1.40,
        "critical_by_default": True,
        "minimum_evidence_strength": 0.75,
        "negative_evidence_penalty": 0.35,
        "contradiction_penalty": 0.30,
        "future_state_cap": 0.20,
        "inheritance_allowed": True,
        "compensating_allowed": False,
        "confidence_cap_if_only_weak_evidence": 0.65,
        "confidence_cap_if_compensating_only": None,
    },
    {
        "bucket_key": "identity_and_access_enforcement",
        "label": "Identity and Access Enforcement",
        "description": "MFA, privileged access, authentication, and session-protection objectives.",
        "sort_order": 60,
        "objective_weight": 1.40,
        "critical_by_default": True,
        "minimum_evidence_strength": 0.75,
        "negative_evidence_penalty": 0.35,
        "contradiction_penalty": 0.30,
        "future_state_cap": 0.20,
        "inheritance_allowed": True,
        "compensating_allowed": False,
        "confidence_cap_if_only_weak_evidence": 0.65,
        "confidence_cap_if_compensating_only": None,
    },
    {
        "bucket_key": "vulnerability_and_flaw_remediation",
        "label": "Vulnerability and Flaw Remediation",
        "description": "Patch, scanner, coverage, and flaw-remediation objectives.",
        "sort_order": 70,
        "objective_weight": 1.15,
        "critical_by_default": False,
        "minimum_evidence_strength": 0.65,
        "negative_evidence_penalty": 0.30,
        "contradiction_penalty": 0.25,
        "future_state_cap": 0.30,
        "inheritance_allowed": True,
        "compensating_allowed": True,
        "confidence_cap_if_only_weak_evidence": 0.70,
        "confidence_cap_if_compensating_only": None,
    },
    {
        "bucket_key": "inherited_control_support",
        "label": "Inherited Control Support",
        "description": "Inherited common-control evidence paths and provider-backed support objectives.",
        "sort_order": 80,
        "objective_weight": 0.95,
        "critical_by_default": False,
        "minimum_evidence_strength": 0.70,
        "negative_evidence_penalty": 0.25,
        "contradiction_penalty": 0.20,
        "future_state_cap": 0.20,
        "inheritance_allowed": True,
        "compensating_allowed": False,
        "confidence_cap_if_only_weak_evidence": 0.70,
        "confidence_cap_if_compensating_only": None,
    },
    {
        "bucket_key": "compensating_control_support",
        "label": "Compensating Control Support",
        "description": "Documented compensating-control objectives and alternative safeguards.",
        "sort_order": 90,
        "objective_weight": 0.90,
        "critical_by_default": False,
        "minimum_evidence_strength": 0.75,
        "negative_evidence_penalty": 0.20,
        "contradiction_penalty": 0.20,
        "future_state_cap": 0.20,
        "inheritance_allowed": False,
        "compensating_allowed": True,
        "confidence_cap_if_only_weak_evidence": 0.68,
        "confidence_cap_if_compensating_only": 0.72,
    },
    {
        "bucket_key": "negative_evidence",
        "label": "Negative Evidence",
        "description": "Explicit failed tests, audit findings, and unresolved gap evidence.",
        "sort_order": 100,
        "objective_weight": 1.20,
        "critical_by_default": False,
        "minimum_evidence_strength": 0.60,
        "negative_evidence_penalty": 0.40,
        "contradiction_penalty": 0.30,
        "future_state_cap": 0.10,
        "inheritance_allowed": False,
        "compensating_allowed": False,
        "confidence_cap_if_only_weak_evidence": 0.62,
        "confidence_cap_if_compensating_only": None,
    },
]

_BUCKET_EDITABLE_FIELDS = {
    "label",
    "description",
    "sort_order",
    "objective_weight",
    "critical_by_default",
    "minimum_evidence_strength",
    "negative_evidence_penalty",
    "contradiction_penalty",
    "future_state_cap",
    "inheritance_allowed",
    "compensating_allowed",
    "confidence_cap_if_only_weak_evidence",
    "confidence_cap_if_compensating_only",
    "active",
}

_THRESHOLD_FIELDS = {
    "compliant_threshold",
    "partial_threshold",
    "minimum_evidence_quality_for_compliant",
    "max_contradiction_for_compliant",
    "critical_failure_blocks_compliant",
    "manual_review_contradiction_threshold",
    "manual_review_weak_evidence_threshold",
    "manual_review_inheritance_without_authority",
    "manual_review_compensating_without_authority",
}

_IDENTITY_PATTERN = re.compile(
    r"\b(mfa|multi-factor|authentication|authenticat|account|privileged|role-based|role based|session|access control|access enforcement|least privilege|remote access|token)\b",
    re.IGNORECASE,
)
_CRYPTO_PATTERN = re.compile(
    r"\b(cryptographic|cryptography|encryption|decrypt|key management|key material|certificate|tls|ssl|fips|cipher)\b",
    re.IGNORECASE,
)
_MONITORING_PATTERN = re.compile(
    r"\b(log|logging|audit|auditable|event|alert|monitor|monitoring|review records|incident response|analysis|correlat|detect)\b",
    re.IGNORECASE,
)
_VULN_PATTERN = re.compile(
    r"\b(vulnerability|flaw|patch|remediation|scanner|scan|update|malware|integrity checks|software update)\b",
    re.IGNORECASE,
)
_INHERITED_PATTERN = re.compile(
    r"\b(inherit|inherited|common control|shared service|provider|external service)\b",
    re.IGNORECASE,
)
_COMPENSATING_PATTERN = re.compile(
    r"\b(compensating|alternate control|alternative safeguard|manual safeguard)\b",
    re.IGNORECASE,
)
_POLICY_PATTERN = re.compile(
    r"\b(policy|policies|responsibility|assign|oversight|review frequency|governance|disseminat|approve)\b",
    re.IGNORECASE,
)
_PROCEDURE_PATTERN = re.compile(
    r"\b(procedure|process|workflow|steps|documented process|approval chain|operational)\b",
    re.IGNORECASE,
)
_TECHNICAL_PATTERN = re.compile(
    r"\b(configur(?:e|ed|es|ing|ation)?|enforc(?:e|ed|es|ing|ement)?|implement(?:ed|ation|s|ing)?|disabl(?:e|ed|es|ing)?|restrict(?:ed|s|ing)?|prevent(?:ed|s|ing)?|protect(?:ed|s|ing|ion)?|mechanism|hardening|baseline setting(?:s)?|system enforc(?:e|es|ed|ing|ement)?)\b",
    re.IGNORECASE,
)


def serialize_bucket(bucket: AssessmentPolicyBucket) -> dict:
    return {
        "id": bucket.id,
        "bucket_key": bucket.bucket_key,
        "label": bucket.label,
        "description": bucket.description,
        "sort_order": bucket.sort_order,
        "objective_weight": bucket.objective_weight,
        "critical_by_default": bucket.critical_by_default,
        "minimum_evidence_strength": bucket.minimum_evidence_strength,
        "negative_evidence_penalty": bucket.negative_evidence_penalty,
        "contradiction_penalty": bucket.contradiction_penalty,
        "future_state_cap": bucket.future_state_cap,
        "inheritance_allowed": bucket.inheritance_allowed,
        "compensating_allowed": bucket.compensating_allowed,
        "confidence_cap_if_only_weak_evidence": bucket.confidence_cap_if_only_weak_evidence,
        "confidence_cap_if_compensating_only": bucket.confidence_cap_if_compensating_only,
        "active": bucket.active,
        "created_at": bucket.created_at.isoformat() if bucket.created_at else None,
        "updated_at": bucket.updated_at.isoformat() if bucket.updated_at else None,
    }


def serialize_policy(policy: AssessmentPolicy, *, include_buckets: bool = True) -> dict:
    data = {
        "id": policy.id,
        "name": policy.name,
        "version": policy.version,
        "description": policy.description,
        "status": policy.status,
        "effective_at": policy.effective_at.isoformat() if policy.effective_at else None,
        "created_by": policy.created_by,
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
        "notes": policy.notes,
        "default_thresholds": policy.default_thresholds_json or {},
        "mapping_rules": policy.mapping_rules_json or {},
    }
    if include_buckets:
        data["buckets"] = [serialize_bucket(bucket) for bucket in sorted(policy.buckets, key=lambda b: (b.sort_order, b.id))]
    return data


def build_policy_runtime(policy: AssessmentPolicy | None) -> dict:
    thresholds = {
        **DEFAULT_THRESHOLDS,
        **((policy.default_thresholds_json or {}) if policy else {}),
    }
    mapping_rules = {
        **DEFAULT_MAPPING_RULES,
        **((policy.mapping_rules_json or {}) if policy else {}),
    }

    buckets: dict[str, dict] = {}
    if policy is not None:
        for bucket in sorted(policy.buckets, key=lambda item: (item.sort_order, item.id)):
            if bucket.active:
                buckets[bucket.bucket_key] = serialize_bucket(bucket)

    if not buckets:
        for bucket in DEFAULT_BUCKETS:
            buckets[bucket["bucket_key"]] = {
                **bucket,
                "active": True,
            }

    return {
        "policy_id": policy.id if policy else None,
        "policy_name": policy.name if policy else DEFAULT_POLICY_NAME,
        "policy_version": policy.version if policy else DEFAULT_POLICY_VERSION,
        "thresholds": thresholds,
        "mapping_rules": mapping_rules,
        "buckets": buckets,
    }


def _bucket_snapshot(policy: AssessmentPolicy) -> dict[str, dict]:
    return {
        bucket.bucket_key: serialize_bucket(bucket)
        for bucket in policy.buckets
    }


def _policy_summary(policy: AssessmentPolicy) -> dict:
    return {
        "id": policy.id,
        "name": policy.name,
        "version": policy.version,
        "status": policy.status,
        "effective_at": policy.effective_at.isoformat() if policy.effective_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }


def _resolve_primary_bucket_key(control_family: str, text: str) -> str | None:
    family = (control_family or "").upper().strip()

    if family in {"IA", "AC", "PS"} or _IDENTITY_PATTERN.search(text):
        return "identity_and_access_enforcement"
    if family in {"SC"} or _CRYPTO_PATTERN.search(text):
        return "crypto_and_key_management"
    if family in {"AU", "IR", "CA"} or _MONITORING_PATTERN.search(text):
        return "monitoring_audit"
    if family in {"SI", "RA", "SA"} or _VULN_PATTERN.search(text):
        return "vulnerability_and_flaw_remediation"
    if _POLICY_PATTERN.search(text):
        return "policy_governance"
    if _PROCEDURE_PATTERN.search(text):
        return "procedure_execution"
    if _TECHNICAL_PATTERN.search(text):
        return "technical_enforcement"
    return None


def resolve_bucket_context(control_family: str, objective_text: str | None, control_title: str | None = None) -> dict:
    family = (control_family or "").upper().strip()
    text = " ".join(part for part in [control_title or "", objective_text or ""] if part).strip()
    primary_bucket_key = _resolve_primary_bucket_key(family, text)
    inherited_context = bool(_INHERITED_PATTERN.search(text))
    compensating_context = bool(_COMPENSATING_PATTERN.search(text))

    if primary_bucket_key:
        bucket_key = primary_bucket_key
    elif compensating_context:
        bucket_key = "compensating_control_support"
    elif inherited_context:
        bucket_key = "inherited_control_support"
    else:
        bucket_key = "procedure_execution"

    return {
        "bucket_key": bucket_key,
        "primary_bucket_key": primary_bucket_key or bucket_key,
        "inherited_context": inherited_context,
        "compensating_context": compensating_context,
    }


def resolve_bucket_key(control_family: str, objective_text: str | None, control_title: str | None = None) -> str:
    return resolve_bucket_context(control_family, objective_text, control_title)["bucket_key"]


def build_bucket_preview(policy: AssessmentPolicy, compare_to: AssessmentPolicy | None = None) -> dict:
    catalog = list(load_catalog().values())
    bucket_stats: dict[str, dict] = {}
    changed_bucket_keys: set[str] = set()

    if compare_to is not None:
        current = _bucket_snapshot(policy)
        baseline = _bucket_snapshot(compare_to)
        for key in set(current) | set(baseline):
            if current.get(key) != baseline.get(key):
                changed_bucket_keys.add(key)

    for control in catalog:
        objectives = list(control.assessment_objectives or [])
        if not objectives:
            objectives = [control.statement] if control.statement else []
        seen_for_control: set[str] = set()
        for objective in objectives:
            bucket_key = resolve_bucket_key(control.family_id, objective, control.title)
            bucket = bucket_stats.setdefault(
                bucket_key,
                {
                    "bucket_key": bucket_key,
                    "mapped_objectives_count": 0,
                    "mapped_controls_count": 0,
                    "control_ids": set(),
                    "families": set(),
                },
            )
            bucket["mapped_objectives_count"] += 1
            bucket["families"].add(control.family_id.upper())
            if bucket_key not in seen_for_control:
                bucket["mapped_controls_count"] += 1
                seen_for_control.add(bucket_key)
            bucket["control_ids"].add(control.display_id)

    serialized_buckets: list[dict] = []
    for bucket in sorted(policy.buckets, key=lambda item: (item.sort_order, item.id)):
        stats = bucket_stats.get(
            bucket.bucket_key,
            {
                "mapped_objectives_count": 0,
                "mapped_controls_count": 0,
                "control_ids": set(),
                "families": set(),
            },
        )
        serialized_buckets.append(
            {
                **serialize_bucket(bucket),
                "mapped_objectives_count": stats["mapped_objectives_count"],
                "mapped_controls_count": stats["mapped_controls_count"],
                "sample_control_ids": sorted(stats["control_ids"])[:8],
                "families": sorted(stats["families"]),
                "changed_from_active": bucket.bucket_key in changed_bucket_keys,
            }
        )

    impacted_controls = set()
    impacted_objectives = 0
    for item in serialized_buckets:
        if item["changed_from_active"]:
            impacted_controls.update(item["sample_control_ids"])
            impacted_objectives += item["mapped_objectives_count"]

    return {
        "policy": _policy_summary(policy),
        "compare_to": _policy_summary(compare_to) if compare_to else None,
        "bucket_preview": serialized_buckets,
        "impact_summary": {
            "changed_bucket_count": len(changed_bucket_keys),
            "affected_bucket_count": len([b for b in serialized_buckets if b["mapped_objectives_count"] > 0]),
            "affected_objectives_count": impacted_objectives,
            "changed_buckets_with_mappings": len([b for b in serialized_buckets if b["changed_from_active"] and b["mapped_objectives_count"] > 0]),
            "catalog_control_count": len(catalog),
            "catalog_objective_count": sum(item["mapped_objectives_count"] for item in serialized_buckets),
            "impact_note": (
                "Preview shows which catalog controls and objectives are governed by each bucket. "
                "Assessment score deltas will become exact once the weighted adjudication engine consumes this policy."
            ),
        },
    }


async def get_active_assessment_policy(db: AsyncSession) -> AssessmentPolicy | None:
    return await db.scalar(
        select(AssessmentPolicy)
        .where(AssessmentPolicy.status == "active")
        .order_by(AssessmentPolicy.effective_at.desc().nullslast(), AssessmentPolicy.id.desc())
    )


async def seed_default_assessment_policy(db: AsyncSession) -> AssessmentPolicy:
    existing = await get_active_assessment_policy(db)
    if existing is not None:
        await db.refresh(existing, attribute_names=["buckets"])
        return existing

    any_policy = await db.scalar(select(AssessmentPolicy).limit(1))
    if any_policy is not None:
        if any_policy.status != "active":
            any_policy.status = "active"
            any_policy.effective_at = any_policy.effective_at or datetime.now(UTC)
            await db.commit()
            await db.refresh(any_policy, attribute_names=["buckets"])
        return any_policy

    policy = AssessmentPolicy(
        name=DEFAULT_POLICY_NAME,
        version=DEFAULT_POLICY_VERSION,
        description="Organization-wide default adjudication policy for control scoring and evidence weighting.",
        status="active",
        effective_at=datetime.now(UTC),
        notes="Seeded automatically by ATO Bot.",
        default_thresholds_json=DEFAULT_THRESHOLDS,
        mapping_rules_json=DEFAULT_MAPPING_RULES,
    )
    db.add(policy)
    await db.flush()

    for bucket in DEFAULT_BUCKETS:
        db.add(AssessmentPolicyBucket(policy_id=policy.id, active=True, **bucket))

    await db.commit()
    await db.refresh(policy, attribute_names=["buckets"])
    return policy


async def get_policy_by_id(db: AsyncSession, policy_id: int) -> AssessmentPolicy | None:
    policy = await db.scalar(select(AssessmentPolicy).where(AssessmentPolicy.id == policy_id))
    if policy is not None:
        await db.refresh(policy, attribute_names=["buckets"])
    return policy


async def update_policy_metadata(
    db: AsyncSession,
    policy: AssessmentPolicy,
    *,
    name: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    default_thresholds: dict | None = None,
) -> AssessmentPolicy:
    if policy.status != "draft":
        raise ValueError("Only draft policies can be edited")

    if name is not None:
        policy.name = name
    if description is not None:
        policy.description = description
    if notes is not None:
        policy.notes = notes
    if default_thresholds is not None:
        cleaned = {
            key: value
            for key, value in default_thresholds.items()
            if key in _THRESHOLD_FIELDS
        }
        policy.default_thresholds_json = {
            **(policy.default_thresholds_json or DEFAULT_THRESHOLDS),
            **cleaned,
        }
    await db.commit()
    await db.refresh(policy, attribute_names=["buckets"])
    return policy


async def update_policy_bucket(
    db: AsyncSession,
    policy: AssessmentPolicy,
    bucket_key: str,
    updates: dict,
) -> AssessmentPolicyBucket:
    if policy.status != "draft":
        raise ValueError("Only draft policies can be edited")

    bucket = next((item for item in policy.buckets if item.bucket_key == bucket_key), None)
    if bucket is None:
        raise ValueError("Bucket not found")

    for key, value in updates.items():
        if key in _BUCKET_EDITABLE_FIELDS:
            setattr(bucket, key, value)

    await db.commit()
    await db.refresh(policy, attribute_names=["buckets"])
    return next(item for item in policy.buckets if item.bucket_key == bucket_key)


async def clone_policy_to_draft(
    db: AsyncSession,
    source_policy: AssessmentPolicy,
    *,
    created_by: int | None = None,
) -> AssessmentPolicy:
    next_version = (await db.scalar(select(func.max(AssessmentPolicy.version)))) or 0
    draft = AssessmentPolicy(
        name=source_policy.name,
        version=int(next_version) + 1,
        description=source_policy.description,
        status="draft",
        effective_at=None,
        created_by=created_by,
        notes=source_policy.notes,
        default_thresholds_json=dict(source_policy.default_thresholds_json or {}),
        mapping_rules_json=dict(source_policy.mapping_rules_json or {}),
    )
    db.add(draft)
    await db.flush()

    for bucket in source_policy.buckets:
        db.add(
            AssessmentPolicyBucket(
                policy_id=draft.id,
                bucket_key=bucket.bucket_key,
                label=bucket.label,
                description=bucket.description,
                sort_order=bucket.sort_order,
                objective_weight=bucket.objective_weight,
                critical_by_default=bucket.critical_by_default,
                minimum_evidence_strength=bucket.minimum_evidence_strength,
                negative_evidence_penalty=bucket.negative_evidence_penalty,
                contradiction_penalty=bucket.contradiction_penalty,
                future_state_cap=bucket.future_state_cap,
                inheritance_allowed=bucket.inheritance_allowed,
                compensating_allowed=bucket.compensating_allowed,
                confidence_cap_if_only_weak_evidence=bucket.confidence_cap_if_only_weak_evidence,
                confidence_cap_if_compensating_only=bucket.confidence_cap_if_compensating_only,
                active=bucket.active,
            )
        )

    await db.commit()
    await db.refresh(draft, attribute_names=["buckets"])
    return draft


async def activate_policy(db: AsyncSession, policy: AssessmentPolicy) -> AssessmentPolicy:
    if policy.status != "draft":
        raise ValueError("Only draft policies can be activated")

    active = await get_active_assessment_policy(db)
    if active is not None and active.id != policy.id:
        active.status = "retired"

    policy.status = "active"
    policy.effective_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(policy, attribute_names=["buckets"])
    return policy


async def delete_policy_draft(db: AsyncSession, policy: AssessmentPolicy) -> None:
    if policy.status != "draft":
        raise ValueError("Only draft policies can be deleted")
    await db.delete(policy)
    await db.commit()
