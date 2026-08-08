"""Validation helpers for OSCAL exports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import regex
from jsonschema import Draft7Validator, ValidationError, validators

OSCAL_VERSION = "1.2.1"
ASSESSMENT_PLAN_SCHEMA_SOURCE = (
    "https://github.com/usnistgov/OSCAL/releases/download/v1.2.1/oscal_assessment-plan_schema.json"
)
ASSESSMENT_RESULTS_SCHEMA_SOURCE = (
    "https://github.com/usnistgov/OSCAL/releases/download/v1.2.1/oscal_assessment-results_schema.json"
)
POAM_SCHEMA_SOURCE = (
    "https://github.com/usnistgov/OSCAL/releases/download/v1.2.1/oscal_poam_schema.json"
)
SSP_SCHEMA_SOURCE = (
    "https://github.com/usnistgov/OSCAL/releases/download/v1.2.1/oscal_ssp_schema.json"
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "oscal"
ASSESSMENT_PLAN_SCHEMA_PATH = DATA_DIR / "oscal_assessment-plan_schema.json"
ASSESSMENT_RESULTS_SCHEMA_PATH = DATA_DIR / "oscal_assessment-results_schema.json"
POAM_SCHEMA_PATH = DATA_DIR / "oscal_poam_schema.json"
SSP_SCHEMA_PATH = DATA_DIR / "oscal_ssp_schema.json"


def _load_schema(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _pattern_with_unicode(validator, pattern, instance, schema):
    if not validator.is_type(instance, "string"):
        return
    if regex.search(pattern, instance) is None:
        yield ValidationError(f"{instance!r} does not match {pattern!r}")


OscalDraft7Validator = validators.extend(
    Draft7Validator,
    {"pattern": _pattern_with_unicode},
)


def validate_assessment_results_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _validate(payload, ASSESSMENT_RESULTS_SCHEMA_PATH)


def validate_poam_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _validate(payload, POAM_SCHEMA_PATH)


def validate_assessment_plan_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _validate(payload, ASSESSMENT_PLAN_SCHEMA_PATH)


def validate_ssp_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _validate(payload, SSP_SCHEMA_PATH)


def _validate(payload: dict[str, Any], schema_path: Path) -> list[dict[str, Any]]:
    schema = _load_schema(schema_path)
    validator = OscalDraft7Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.absolute_path))
    return [
        {
            "path": [str(part) for part in err.absolute_path],
            "message": err.message,
            "validator": err.validator,
        }
        for err in errors
    ]


def summarize_validation_errors(
    errors: list[dict[str, Any]],
    *,
    artifact_name: str = "assessment-results",
) -> str:
    if not errors:
        return f"Export passed NIST OSCAL {artifact_name} schema validation."
    first = errors[0]
    path = ".".join(first.get("path") or []) or "$"
    return f"Export failed OSCAL schema validation with {len(errors)} error(s). First error at {path}: {first.get('message')}"
