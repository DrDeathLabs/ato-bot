"""NIST SP 800-53 Rev. 5 control catalog reference API."""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.rbac import require_viewer
from app.services.controls.catalog import Control, get_families, load_baseline, load_catalog
from app.services.multistage_engine import _derive_objectives_from_statement

router = APIRouter(prefix="/control-catalog", tags=["control-catalog"])


def _catalog_index() -> tuple[dict[str, Control], dict[str, Control]]:
    catalog = load_catalog()
    by_display_id = {control.display_id.upper(): control for control in catalog.values()}
    return catalog, by_display_id


@lru_cache(maxsize=3)
def _baseline_id_set(baseline_name: str) -> set[str]:
    return {control.id for control in load_baseline(baseline_name)}


@lru_cache(maxsize=3)
def _raw_baseline_id_set(baseline_name: str) -> set[str]:
    return {control.id for control in load_baseline(baseline_name, include_non_assessable=True)}


def _baseline_membership(control: Control) -> list[str]:
    memberships: list[str] = []
    for baseline_name in ("low", "moderate", "high"):
        if control.id in _baseline_id_set(baseline_name):
            memberships.append(baseline_name)
    return memberships


def _raw_baseline_membership(control: Control) -> list[str]:
    memberships: list[str] = []
    for baseline_name in ("low", "moderate", "high"):
        if control.id in _raw_baseline_id_set(baseline_name):
            memberships.append(baseline_name)
    return memberships


def _assessment_criteria(control: Control) -> tuple[list[str], str]:
    if not control.is_assessable:
        return [], "not_assessable"
    if control.assessment_objectives:
        return control.assessment_objectives, "800-53A"
    derived = _derive_objectives_from_statement(control.display_id, control.statement or "")
    if derived:
        return derived, "derived_from_statement"
    return [], "unavailable"


def _control_summary(control: Control) -> dict:
    criteria, criteria_source = _assessment_criteria(control)
    return {
        "id": control.display_id,
        "catalog_id": control.id,
        "family_id": control.family_id.upper(),
        "family_title": control.family_title,
        "title": control.title,
        "is_enhancement": control.is_enhancement,
        "parent_id": control.parent_id,
        "assessable": control.is_assessable,
        "status": control.status,
        "incorporated_into": control.incorporated_into,
        "assessment_objective_count": len(criteria),
        "assessment_criteria_source": criteria_source,
        "baselines": _baseline_membership(control),
        "raw_baselines": _raw_baseline_membership(control),
    }


def _control_detail(control: Control) -> dict:
    criteria, criteria_source = _assessment_criteria(control)
    parent = None
    if control.parent_id:
        parent_control = load_catalog().get(control.parent_id)
        if parent_control:
            parent = {
                "id": parent_control.display_id,
                "catalog_id": parent_control.id,
                "title": parent_control.title,
            }

    return {
        **_control_summary(control),
        "statement": control.statement,
        "supplemental_guidance": control.supplemental_guidance,
        "assessment_criteria": criteria,
        "reference_source": "NIST SP 800-53 Rev. 5 / 800-53A",
        "parent": parent,
    }


def _resolve_control(control_id: str) -> Control | None:
    normalized = control_id.strip()
    if not normalized:
        return None
    catalog, by_display_id = _catalog_index()
    return (
        by_display_id.get(normalized.upper())
        or catalog.get(normalized.lower())
    )


@router.get("/families")
async def list_control_families(
    _: dict = Depends(require_viewer),
) -> dict:
    return {
        "families": [
            {"id": family_id.upper(), "title": family_title}
            for family_id, family_title in get_families()
        ]
    }


@router.get("/controls")
async def list_controls(
    q: str | None = Query(default=None, description="Search by control ID, title, statement, or objective text."),
    family: str | None = Query(default=None, description="Control family filter, e.g. AC."),
    baseline: str | None = Query(default=None, description="Baseline filter: low, moderate, or high."),
    include_enhancements: bool = Query(default=True, description="Include control enhancements."),
    include_non_assessable: bool = Query(default=False, description="Include withdrawn/non-assessable controls."),
    limit: int = Query(default=50, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_viewer),
) -> dict:
    catalog = list(load_catalog().values())

    q_norm = (q or "").strip().lower()
    family_norm = (family or "").strip().lower()
    baseline_norm = (baseline or "").strip().lower()

    baseline_ids: set[str] | None = None
    if baseline_norm:
        if baseline_norm not in {"low", "moderate", "high"}:
            raise HTTPException(status_code=400, detail="baseline must be low, moderate, or high")
        baseline_ids = _baseline_id_set(baseline_norm)

    filtered: list[Control] = []
    for control in catalog:
        if not include_non_assessable and not control.is_assessable:
            continue
        if not include_enhancements and control.is_enhancement:
            continue
        if family_norm and control.family_id.lower() != family_norm:
            continue
        if baseline_ids is not None and control.id not in baseline_ids:
            continue
        if q_norm:
            criteria, _ = _assessment_criteria(control)
            haystack = "\n".join([
                control.display_id,
                control.title,
                control.statement,
                control.supplemental_guidance,
                *criteria[:20],
            ]).lower()
            if q_norm not in haystack:
                continue
        filtered.append(control)

    filtered.sort(key=lambda control: (control.family_id, control.label))
    page = filtered[offset:offset + limit]

    return {
        "total": len(filtered),
        "items": [_control_summary(control) for control in page],
    }


@router.get("/controls/{control_id}")
async def get_control(
    control_id: str,
    _: dict = Depends(require_viewer),
) -> dict:
    control = _resolve_control(control_id)
    if control is None:
        raise HTTPException(status_code=404, detail=f"Control {control_id} not found")
    return _control_detail(control)
