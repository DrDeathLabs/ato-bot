"""Authoritative runtime feature registry for supported and pre-release capabilities."""
from __future__ import annotations

from typing import Any, Literal

from app.core.config import Settings

FeatureStatus = Literal["supported", "beta", "experimental", "deprecated", "unreachable"]


_FEATURES: tuple[dict[str, Any], ...] = (
    {
        "key": "assessment_core",
        "name": "NIST 800-53 assessment workbench",
        "status": "supported",
        "description": "Evidence-backed control assessment, deterministic rollups, and human review workflows.",
        "default_enabled": True,
    },
    {
        "key": "evidence_ingestion",
        "name": "Evidence ingestion and normalization",
        "status": "supported",
        "description": "Document parsing, evidence units, classification, embeddings, and provenance.",
        "default_enabled": True,
    },
    {
        "key": "remediation_closure",
        "name": "Remediation and closure",
        "status": "supported",
        "description": "Per-control closure guidance, draft artifacts, reports, and review workflows.",
        "default_enabled": True,
    },
    {
        "key": "oscal_ssp_exports",
        "name": "SSP and OSCAL-oriented exports",
        "status": "supported",
        "description": "SSP workbench and structured assessment/report export surfaces.",
        "default_enabled": True,
    },
    {
        "key": "cyber_assistant",
        "name": "Cyber Assistant",
        "status": "beta",
        "description": "Purpose-bound assistant conversations and attachment interpretation.",
        "default_enabled": True,
    },
    {
        "key": "system_knowledge",
        "name": "System knowledge extraction",
        "status": "beta",
        "description": "Architecture and tool assertions inferred from approved project evidence.",
        "default_enabled": True,
    },
    {
        "key": "calibration_harness",
        "name": "Calibration and synthetic datasets",
        "status": "beta",
        "description": "Assessment calibration suites and controlled evidence-dataset generation.",
        "default_enabled": True,
    },
    {
        "key": "human_artifact_generation",
        "name": "Human-style remediation artifacts",
        "status": "beta",
        "description": "AI-drafted control-owner artifacts that require approval before evidence use.",
        "default_enabled": True,
    },
    {
        "key": "external_integrations",
        "name": "External integration connectors",
        "status": "experimental",
        "description": "Connector accounts, synchronization scaffolding, and imported posture data.",
        "default_enabled": False,
        "setting": "enable_experimental_cato",
    },
    {
        "key": "continuous_telemetry",
        "name": "Continuous telemetry and drift",
        "status": "experimental",
        "description": "App, collector, container, and connector-derived monitoring posture.",
        "default_enabled": False,
        "setting": "enable_experimental_cato",
    },
    {
        "key": "cato_dashboard",
        "name": "Continuous ATO dashboard",
        "status": "experimental",
        "description": "Continuous posture dashboard built on incomplete telemetry and connector surfaces.",
        "default_enabled": False,
        "setting": "enable_experimental_cato",
    },
    {
        "key": "legacy_dashboard_route",
        "name": "Legacy dashboard route",
        "status": "deprecated",
        "description": "Compatibility redirect from /dashboard to the supported projects workspace.",
        "default_enabled": True,
    },
    {
        "key": "orphan_frontend_pages",
        "name": "Unrouted legacy frontend pages",
        "status": "unreachable",
        "description": "Dashboard, POA&M, scorecard, and security-event components with no live route.",
        "default_enabled": False,
    },
)


def feature_registry(settings: Settings) -> list[dict[str, Any]]:
    """Return immutable feature metadata with deployment-specific enablement."""
    result: list[dict[str, Any]] = []
    for definition in _FEATURES:
        item = dict(definition)
        setting_name = item.pop("setting", None)
        enabled = bool(getattr(settings, setting_name)) if setting_name else bool(item["default_enabled"])
        item["enabled"] = enabled
        result.append(item)
    return result


def feature_enabled(settings: Settings, key: str) -> bool:
    return next((item["enabled"] for item in feature_registry(settings) if item["key"] == key), False)
