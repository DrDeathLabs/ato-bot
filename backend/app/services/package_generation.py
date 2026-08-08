"""Shared planning helpers for consolidated test-package and remediation generation."""
from __future__ import annotations

from collections import Counter, defaultdict
from math import floor


PROFILE_PRESETS: dict[str, dict[str, int]] = {
    "passing_ato": {"satisfied_pct": 100, "partial_pct": 0, "failed_pct": 0},
    "mostly_compliant": {"satisfied_pct": 92, "partial_pct": 6, "failed_pct": 2},
    "mixed_realistic": {"satisfied_pct": 72, "partial_pct": 20, "failed_pct": 8},
    "stress_test": {"satisfied_pct": 50, "partial_pct": 30, "failed_pct": 20},
}

STYLE_CHUNK_SIZE: dict[str, int] = {
    "lean": 10,
    "standard": 7,
    "robust": 5,
}

FAMILY_TITLES: dict[str, str] = {
    "AC": "Access Control",
    "AT": "Awareness and Training",
    "AU": "Audit and Accountability",
    "CA": "Assessment, Authorization, and Monitoring",
    "CM": "Configuration Management",
    "CP": "Contingency Planning",
    "IA": "Identification and Authentication",
    "IR": "Incident Response",
    "MA": "Maintenance",
    "MP": "Media Protection",
    "PE": "Physical and Environmental Protection",
    "PL": "Planning",
    "PM": "Program Management",
    "PS": "Personnel Security",
    "PT": "PII Processing and Transparency",
    "RA": "Risk Assessment",
    "SA": "System and Services Acquisition",
    "SC": "System and Communications Protection",
    "SI": "System and Information Integrity",
    "SR": "Supply Chain Risk Management",
}

TECHNICAL_FAMILIES = {"SC", "SI", "CM"}
HIGH_RISK_FAMILIES = {"SC", "SI", "RA", "CA", "AU", "CM", "CP", "IR", "IA"}
POLICY_FAMILIES = {"PL", "PM"}
TRAINING_FAMILIES = {"AT", "PS"}
FIRST_PASS_TECHNICAL_FAMILIES = {"SC", "SI", "CM", "IA", "AU", "AC", "CP"}
FIRST_PASS_GOVERNANCE_FAMILIES = {"PL", "PM", "CA", "RA"}
FIRST_PASS_TARGETS = {"passing_ato", "mostly_compliant"}


def _normalize_family_overrides(family_overrides: dict | None) -> dict[str, dict[str, int | str]]:
    normalized: dict[str, dict[str, int | str]] = {}
    if not isinstance(family_overrides, dict):
        return normalized
    for family, override in family_overrides.items():
        if not family or not isinstance(override, dict):
            continue
        normalized[str(family).upper()] = resolve_expected_profile(
            "custom",
            expected_satisfied_pct=override.get("satisfied_pct"),
            expected_partial_pct=override.get("partial_pct"),
            expected_failed_pct=override.get("failed_pct"),
        )
    return normalized


def _normalize_outcome_status(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "compliant": "compliant",
        "pass": "compliant",
        "passed": "compliant",
        "satisfied": "compliant",
        "met": "compliant",
        "partial": "partially_compliant",
        "partially_compliant": "partially_compliant",
        "partially_met": "partially_compliant",
        "needs_work": "partially_compliant",
        "fail": "non_compliant",
        "failed": "non_compliant",
        "non_compliant": "non_compliant",
        "not_met": "non_compliant",
        "missing": "non_compliant",
    }
    return mapping.get(raw)


def _normalize_control_overrides(
    control_overrides: dict | None,
    valid_control_ids: set[str],
) -> tuple[dict[str, str], dict[str, str]]:
    normalized: dict[str, str] = {}
    invalid: dict[str, str] = {}
    if not isinstance(control_overrides, dict):
        return normalized, invalid

    for control_id, status in control_overrides.items():
        cid = str(control_id).strip().upper()
        normalized_status = _normalize_outcome_status(status)
        if cid not in valid_control_ids:
            invalid[cid] = "unknown_control"
            continue
        if not normalized_status:
            invalid[cid] = "invalid_status"
            continue
        normalized[cid] = normalized_status
    return normalized, invalid


def _family_rank(control_id: str) -> tuple[int, str]:
    family = control_id.split("-")[0].upper()
    risk_rank = 0 if family in HIGH_RISK_FAMILIES else 1
    return (risk_rank, control_id)


def _bundle_artifact_shape(family: str) -> tuple[str, str, str]:
    family = family.upper()
    if family in TECHNICAL_FAMILIES:
        return ("technical_artifact", "implements", "Technical Security Evidence Package")
    if family in {"CA", "RA"}:
        return ("ssp_narrative", "implements", "Assessment and Risk Narrative Package")
    if family in TRAINING_FAMILIES:
        return ("procedure", "implements", "Training and Personnel Security Packet")
    if family in POLICY_FAMILIES:
        return ("policy", "implements", "Governance and Planning Policy Suite")
    if family in {"AU", "IR", "CP", "MA", "MP", "PE", "SA", "SR"}:
        return ("procedure", "implements", "Operational Security Procedure Pack")
    return ("procedure", "implements", "Control Implementation Procedure Pack")


def _family_bundle_recipes(
    family: str,
    target_profile: str,
    evidence_mix: str,
) -> list[dict[str, str]]:
    family = family.upper()
    is_first_pass = target_profile in FIRST_PASS_TARGETS

    if is_first_pass and family in FIRST_PASS_TECHNICAL_FAMILIES:
        return [
            {
                "artifact_type": "policy",
                "document_type": "policy",
                "document_intent": "implements",
                "evidence_role": "governance",
                "component_label": "Control Definition and Governance Policy",
            },
            {
                "artifact_type": "ssp_narrative",
                "document_type": "ssp_narrative",
                "document_intent": "implements",
                "evidence_role": "architecture",
                "component_label": "System Documentation and Control Narrative",
            },
            {
                "artifact_type": "technical_artifact",
                "document_type": "technical_artifact",
                "document_intent": "implements",
                "evidence_role": "implementation",
                "component_label": "Technical Implementation Evidence Package",
            },
            {
                "artifact_type": "technical_artifact",
                "document_type": "technical_artifact",
                "document_intent": "implements",
                "evidence_role": "validation",
                "component_label": "Technical Validation and Verification Record",
            },
        ]

    if is_first_pass and family in FIRST_PASS_GOVERNANCE_FAMILIES:
        return [
            {
                "artifact_type": "ssp_narrative",
                "document_type": "ssp_narrative",
                "document_intent": "implements",
                "evidence_role": "architecture",
                "component_label": "Implementation and Architecture Narrative Package",
            },
            {
                "artifact_type": "policy",
                "document_type": "policy",
                "document_intent": "implements",
                "evidence_role": "governance",
                "component_label": "Governance and Planning Policy Suite",
            },
        ]

    if is_first_pass and family in TRAINING_FAMILIES:
        return [
            {
                "artifact_type": "procedure",
                "document_type": "procedure",
                "document_intent": "implements",
                "evidence_role": "operations",
                "component_label": "Training and Personnel Security Packet",
            },
            {
                "artifact_type": "procedure",
                "document_type": "procedure",
                "document_intent": "implements",
                "evidence_role": "validation",
                "component_label": "Training Completion and Verification Record",
            },
        ]

    artifact_type, document_intent, component_label = _bundle_artifact_shape(family)
    role = "implementation"
    if artifact_type == "policy":
        role = "governance"
    elif artifact_type == "ssp_narrative":
        role = "architecture"
    elif artifact_type == "procedure":
        role = "operations" if evidence_mix == "operational" else "implementation"

    return [
        {
            "artifact_type": artifact_type,
            "document_type": artifact_type,
            "document_intent": document_intent,
            "evidence_role": role,
            "component_label": component_label,
        }
    ]


def resolve_expected_profile(
    target_profile: str,
    expected_satisfied_pct: int | None = None,
    expected_partial_pct: int | None = None,
    expected_failed_pct: int | None = None,
) -> dict[str, int | str]:
    base = dict(PROFILE_PRESETS.get(target_profile, PROFILE_PRESETS["passing_ato"]))
    if expected_satisfied_pct is not None:
        base["satisfied_pct"] = int(expected_satisfied_pct)
    if expected_partial_pct is not None:
        base["partial_pct"] = int(expected_partial_pct)
    if expected_failed_pct is not None:
        base["failed_pct"] = int(expected_failed_pct)

    total = base["satisfied_pct"] + base["partial_pct"] + base["failed_pct"]
    if total <= 0:
        base = dict(PROFILE_PRESETS["passing_ato"])
        total = 100
    if total != 100:
        scale = 100 / total
        base["satisfied_pct"] = round(base["satisfied_pct"] * scale)
        base["partial_pct"] = round(base["partial_pct"] * scale)
        base["failed_pct"] = max(0, 100 - base["satisfied_pct"] - base["partial_pct"])

    return {"target_profile": target_profile, **base}


def build_expected_outcomes(
    control_ids: list[str],
    target_profile: str,
    expected_satisfied_pct: int | None = None,
    expected_partial_pct: int | None = None,
    expected_failed_pct: int | None = None,
    family_overrides: dict | None = None,
    control_overrides: dict | None = None,
) -> dict:
    profile = resolve_expected_profile(
        target_profile,
        expected_satisfied_pct=expected_satisfied_pct,
        expected_partial_pct=expected_partial_pct,
        expected_failed_pct=expected_failed_pct,
    )
    normalized_family_overrides = _normalize_family_overrides(family_overrides)
    valid_control_ids = {str(control_id).strip().upper() for control_id in control_ids}
    normalized_control_overrides, invalid_control_overrides = _normalize_control_overrides(
        control_overrides,
        valid_control_ids=valid_control_ids,
    )
    total = len(control_ids)
    if total == 0:
        return {
            "profile": profile,
            "family_overrides": normalized_family_overrides,
            "control_overrides": normalized_control_overrides,
            "invalid_control_overrides": invalid_control_overrides,
            "by_control": {},
            "summary": {"total_controls": 0},
        }

    controls_by_family: dict[str, list[str]] = defaultdict(list)
    for control_id in control_ids:
        controls_by_family[control_id.split("-")[0].upper()].append(control_id)

    by_control: dict[str, str] = {}
    family_summary: dict[str, dict[str, int]] = {}
    for family, family_control_ids in controls_by_family.items():
        family_profile = normalized_family_overrides.get(family, profile)
        ranked = sorted(family_control_ids, key=_family_rank)
        family_total = len(ranked)
        failed_count = floor(family_total * int(family_profile["failed_pct"]) / 100)
        partial_count = floor(family_total * int(family_profile["partial_pct"]) / 100)
        family_statuses: dict[str, str] = {cid: "compliant" for cid in ranked}
        for cid in ranked[:failed_count]:
            family_statuses[cid] = "non_compliant"
        for cid in ranked[failed_count:failed_count + partial_count]:
            family_statuses[cid] = "partially_compliant"
        by_control.update(family_statuses)

    for control_id, status in normalized_control_overrides.items():
        by_control[control_id] = status

    for family, family_control_ids in controls_by_family.items():
        family_profile = normalized_family_overrides.get(family, profile)
        family_counts = Counter(by_control.get(cid, "compliant") for cid in family_control_ids)
        family_summary[family] = {
            "total_controls": len(family_control_ids),
            "compliant": family_counts.get("compliant", 0),
            "partially_compliant": family_counts.get("partially_compliant", 0),
            "non_compliant": family_counts.get("non_compliant", 0),
            "profile_satisfied_pct": int(family_profile["satisfied_pct"]),
            "profile_partial_pct": int(family_profile["partial_pct"]),
            "profile_failed_pct": int(family_profile["failed_pct"]),
        }

    counts = Counter(by_control.values())
    return {
        "profile": profile,
        "family_overrides": normalized_family_overrides,
        "control_overrides": normalized_control_overrides,
        "invalid_control_overrides": invalid_control_overrides,
        "by_control": by_control,
        "summary": {
            "total_controls": total,
            "compliant": counts.get("compliant", 0),
            "partially_compliant": counts.get("partially_compliant", 0),
            "non_compliant": counts.get("non_compliant", 0),
            "family_override_count": len(normalized_family_overrides),
            "control_override_count": len(normalized_control_overrides),
            "invalid_control_override_count": len(invalid_control_overrides),
        },
        "by_family": family_summary,
    }


def plan_test_dataset_bundles(
    controls: list,
    package_style: str,
    evidence_mix: str,
    expected_outcomes: dict,
) -> dict:
    chunk_size = STYLE_CHUNK_SIZE.get(package_style, STYLE_CHUNK_SIZE["standard"])
    control_status = expected_outcomes.get("by_control", {})
    target_profile = str(expected_outcomes.get("profile", {}).get("target_profile", "passing_ato")).lower()
    recipe_name = "first_pass_technical" if target_profile in FIRST_PASS_TARGETS else "standard"
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    poam_candidates: list[dict] = []

    for ctrl in controls:
        control_id = getattr(ctrl, "display_id", None) or getattr(ctrl, "label", None) or getattr(ctrl, "id", "")
        family = getattr(ctrl, "family_id", control_id.split("-")[0]).upper()
        status = control_status.get(control_id, "compliant")
        item = {
            "control_id": control_id,
            "family": family,
            "family_title": FAMILY_TITLES.get(family, family),
            "title": getattr(ctrl, "title", control_id),
            "statement": getattr(ctrl, "statement", "") or "",
            "objectives": getattr(ctrl, "assessment_objectives", []) or [],
            "target_status": status,
        }
        if status == "non_compliant":
            poam_candidates.append(item)
            continue
        for recipe in _family_bundle_recipes(family, target_profile=target_profile, evidence_mix=evidence_mix):
            grouped[(family, recipe["document_type"], recipe["evidence_role"])].append(
                {
                    **item,
                    "document_type": recipe["document_type"],
                    "document_intent": recipe["document_intent"],
                    "component_label": recipe["component_label"],
                    "evidence_role": recipe["evidence_role"],
                }
            )

    bundles: list[dict] = []
    for (family, document_type, evidence_role), items in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        for idx in range(0, len(items), chunk_size):
            chunk = items[idx: idx + chunk_size]
            part_no = idx // chunk_size + 1
            label = chunk[0]["component_label"]
            title = f"{FAMILY_TITLES.get(family, family)} {label}"
            if len(items) > chunk_size:
                title = f"{title} Part {part_no}"
            bundles.append(
                {
                    "bundle_id": f"{family.lower()}-{document_type}-{evidence_role}-{part_no}",
                    "family": family,
                    "family_title": FAMILY_TITLES.get(family, family),
                    "title": title,
                    "artifact_type": document_type,
                    "document_type": document_type,
                    "document_intent": chunk[0]["document_intent"],
                    "evidence_role": evidence_role,
                    "evidence_mix": evidence_mix,
                    "controls": chunk,
                    "control_ids": [item["control_id"] for item in chunk],
                }
            )

    if poam_candidates:
        bundles.append(
            {
                "bundle_id": "known-gaps-register",
                "family": "POAM",
                "family_title": "Known Gaps and Planned Improvements",
                "title": "Known Gaps and Planned Improvements Register",
                "artifact_type": "ssp_narrative",
                "document_type": "ssp_narrative",
                "document_intent": "plans",
                "evidence_mix": evidence_mix,
                "controls": poam_candidates,
                "control_ids": [item["control_id"] for item in poam_candidates],
            }
        )

    type_counts = Counter(bundle["artifact_type"] for bundle in bundles)
    role_counts = Counter(bundle.get("evidence_role", "implementation") for bundle in bundles)
    return {
        "bundles": bundles,
        "summary": {
            "package_style": package_style,
            "evidence_mix": evidence_mix,
            "recipe_name": recipe_name,
            "bundle_count": len(bundles),
            "artifact_type_counts": dict(type_counts),
            "evidence_role_counts": dict(role_counts),
            "controls_in_implemented_bundles": sum(
                len(bundle["control_ids"]) for bundle in bundles if bundle["document_intent"] == "implements"
            ),
            "controls_in_gap_register": len(poam_candidates),
            "technical_bundle_count": sum(1 for bundle in bundles if bundle["artifact_type"] == "technical_artifact"),
        },
    }


def plan_remediation_bundles(findings: list, package_style: str) -> dict:
    chunk_size = STYLE_CHUNK_SIZE.get(package_style, STYLE_CHUNK_SIZE["standard"])
    grouped: dict[tuple[str, str, str], list] = defaultdict(list)

    for finding in findings:
        family = getattr(finding, "control_family", getattr(finding, "family", "OTHER")).upper()
        # Remediation artifacts should generate reassessment-ready implementation
        # evidence, not advisory templates. Reuse the stronger first-pass bundle
        # recipes so failing families get the same corroborating document mix that
        # the test dataset generator uses for high-confidence evidence.
        recipes = _family_bundle_recipes(
            family,
            target_profile="passing_ato",
            evidence_mix="balanced",
        )
        for recipe in recipes:
            grouped[
                (
                    family,
                    recipe["document_type"],
                    recipe["evidence_role"],
                )
            ].append(
                {
                    "finding": finding,
                    "document_type": recipe["document_type"],
                    "document_intent": recipe["document_intent"],
                    "evidence_role": recipe["evidence_role"],
                    "component_label": recipe["component_label"],
                }
            )

    bundles: list[dict] = []
    for (family, artifact_type, evidence_role), items in sorted(
        grouped.items(),
        key=lambda kv: (kv[0][0], kv[0][1], kv[0][2]),
    ):
        for idx in range(0, len(items), chunk_size):
            chunk = items[idx: idx + chunk_size]
            part_no = idx // chunk_size + 1
            family_title = FAMILY_TITLES.get(family, family)
            title = f"{family_title} {chunk[0]['component_label']}"
            if len(items) > chunk_size:
                title = f"{title} Part {part_no}"
            bundles.append(
                {
                    "bundle_id": f"{family.lower()}-{artifact_type}-{evidence_role}-{part_no}",
                    "family": family,
                    "family_title": family_title,
                    "title": title,
                    "artifact_type": artifact_type,
                    "document_type": chunk[0]["document_type"],
                    "document_intent": chunk[0]["document_intent"],
                    "evidence_role": evidence_role,
                    "control_ids": [getattr(item["finding"], "control_id", "") for item in chunk],
                    "findings": [item["finding"] for item in chunk],
                }
            )

    return {
        "bundles": bundles,
        "summary": {
            "package_style": package_style,
            "bundle_count": len(bundles),
            "controls_addressed": sum(len(bundle["control_ids"]) for bundle in bundles),
            "families_covered": sorted({bundle["family"] for bundle in bundles}),
            "artifact_type_counts": dict(Counter(bundle["artifact_type"] for bundle in bundles)),
            "evidence_role_counts": dict(Counter(bundle.get("evidence_role", "implementation") for bundle in bundles)),
            "recipe_name": "reassessment_pass",
        },
    }


def build_blueprint_validation(blueprint: dict, expected_outcomes: dict | None = None) -> dict:
    bundles = blueprint.get("bundles", [])
    controls_addressed = sum(len(bundle.get("control_ids", [])) for bundle in bundles)
    families = sorted({bundle.get("family", "OTHER") for bundle in bundles})
    type_counts = Counter(bundle.get("artifact_type", "other") for bundle in bundles)
    role_counts = Counter(bundle.get("evidence_role", "implementation") for bundle in bundles)
    validation = {
        "bundle_count": len(bundles),
        "controls_addressed": controls_addressed,
        "families_covered": families,
        "artifact_type_counts": dict(type_counts),
        "evidence_role_counts": dict(role_counts),
        "recipe_name": blueprint.get("summary", {}).get("recipe_name", "standard"),
        "status": "ready" if bundles else "empty",
    }
    if expected_outcomes:
        summary = expected_outcomes.get("summary", {})
        validation["expected_outcomes"] = {
            "compliant": summary.get("compliant", 0),
            "partially_compliant": summary.get("partially_compliant", 0),
            "non_compliant": summary.get("non_compliant", 0),
        }
    return validation


def build_benchmark_result(expected_outcomes: dict, actual_status_by_control: dict[str, str]) -> dict:
    expected = expected_outcomes.get("by_control", {})
    mismatches: list[dict] = []
    matched = 0
    expected_counts = Counter(expected.values())
    actual_counts = Counter()

    for control_id, expected_status in expected.items():
        actual = actual_status_by_control.get(control_id, "not_reviewed")
        actual_counts[actual] += 1
        if actual == expected_status:
            matched += 1
        else:
            mismatches.append(
                {
                    "control_id": control_id,
                    "expected_status": expected_status,
                    "actual_status": actual,
                }
            )

    total = len(expected)
    return {
        "total_controls": total,
        "matched": matched,
        "match_pct": round((matched / total) * 100, 2) if total else 0.0,
        "expected_counts": dict(expected_counts),
        "actual_counts": dict(actual_counts),
        "mismatches": mismatches[:50],
        "mismatch_count": max(0, len(mismatches)),
    }
