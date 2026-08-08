"""NIST 800-53 Rev 5 OSCAL catalog loader and control model."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CATALOG_PATH = DATA_DIR / "nist_800_53_r5_catalog.json"
BASELINES_DIR = DATA_DIR / "baselines"


@dataclass
class Control:
    id: str                          # e.g. "ac-1"
    label: str                       # e.g. "AC-1"
    family_id: str                   # e.g. "ac"
    family_title: str                # e.g. "Access Control"
    title: str
    statement: str
    supplemental_guidance: str
    assessment_objectives: list[str] = field(default_factory=list)
    assessment_methods: list[dict[str, object]] = field(default_factory=list)
    organization_defined_parameters: list[str] = field(default_factory=list)
    # Each entry: "AC-01a.[01]: an access control policy is developed and documented"
    is_enhancement: bool = False
    parent_id: str | None = None
    status: str = "active"
    incorporated_into: list[str] = field(default_factory=list)

    @property
    def display_id(self) -> str:
        return self.label.upper()

    @property
    def is_assessable(self) -> bool:
        return self.status.lower() != "withdrawn"


def _extract_prose(part: dict) -> str:
    """Recursively extract prose text from an OSCAL part."""
    text = part.get("prose", "")
    for sub in part.get("parts", []):
        sub_text = _extract_prose(sub)
        if sub_text:
            text = f"{text}\n{sub_text}".strip()
    return text


def _get_label(control: dict) -> str:
    for prop in control.get("props", []):
        if prop.get("name") == "label" and not prop.get("class"):
            return prop.get("value", control["id"].upper())
    return control["id"].upper()


def _get_sp800_53a_label(part: dict) -> str:
    """Extract the sp800-53a label value from a part's props."""
    for prop in part.get("props", []):
        if prop.get("name") == "label" and prop.get("class") == "sp800-53a":
            return prop.get("value", "")
    return ""


def _get_status(control: dict) -> str:
    for prop in control.get("props", []):
        if prop.get("name") == "status":
            return prop.get("value", "active").strip().lower() or "active"
    return "active"


def _get_incorporated_into_ids(control: dict) -> list[str]:
    targets: list[str] = []
    for link in control.get("links", []) or []:
        if link.get("rel") != "incorporated-into":
            continue
        href = (link.get("href") or "").strip()
        if href.startswith("#"):
            href = href[1:]
        if href:
            targets.append(href.lower())
    return targets


def _extract_leaf_objectives(part: dict, results: list[str]) -> None:
    """Recursively walk assessment-objective parts; collect leaf nodes (prose + no children)."""
    label = _get_sp800_53a_label(part)
    prose = part.get("prose", "").strip()

    # Clean ODP placeholders: {{ insert: param, ac-01_odp.01 }} → [org-defined]
    prose = re.sub(r'\{\{[^}]+\}\}', '[org-defined]', prose).rstrip(";").strip()

    sub_obj_parts = [p for p in part.get("parts", []) if p.get("name") == "assessment-objective"]

    if prose and not sub_obj_parts and label:
        # Leaf objective: has prose, no nested objectives, has a label
        results.append(f"{label}: {prose}")

    for sub in sub_obj_parts:
        _extract_leaf_objectives(sub, results)


def _extract_assessment_method(part: dict) -> dict[str, object] | None:
    method = next(
        (str(prop.get("value") or "").upper() for prop in part.get("props", []) if prop.get("name") == "method"),
        "",
    )
    if method not in {"EXAMINE", "INTERVIEW", "TEST"}:
        return None
    label = _get_sp800_53a_label(part)
    objects: list[str] = []
    for child in part.get("parts", []):
        if child.get("name") != "assessment-objects":
            continue
        prose = _extract_prose(child)
        for value in re.split(r"\n\s*\n|\r?\n", prose):
            normalized = " ".join(value.split())
            if normalized and normalized not in objects:
                objects.append(normalized)
    return {"method": method, "label": label, "objects": objects}


def _parse_control(raw: dict, family_id: str, family_title: str,
                   is_enhancement: bool = False, parent_id: str | None = None) -> Control:
    statement = ""
    supplemental = ""
    objectives: list[str] = []
    methods: list[dict[str, object]] = []
    parameter_ids = sorted(set(re.findall(
        r"\{\{\s*insert:\s*param,\s*([^}\s]+)\s*\}\}",
        json.dumps(raw),
        flags=re.IGNORECASE,
    )))

    for part in raw.get("parts", []):
        name = part.get("name", "")
        if name == "statement":
            statement = _extract_prose(part)
        elif name == "guidance":
            supplemental = _extract_prose(part)
        elif name == "assessment-objective":
            _extract_leaf_objectives(part, objectives)
        elif name == "assessment-method":
            method = _extract_assessment_method(part)
            if method:
                methods.append(method)

    return Control(
        id=raw["id"],
        label=_get_label(raw),
        family_id=family_id,
        family_title=family_title,
        title=raw.get("title", ""),
        statement=statement,
        supplemental_guidance=supplemental,
        assessment_objectives=objectives,
        assessment_methods=methods,
        organization_defined_parameters=parameter_ids,
        is_enhancement=is_enhancement,
        parent_id=parent_id,
        status=_get_status(raw),
        incorporated_into=_get_incorporated_into_ids(raw),
    )


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Control]:
    """Return dict of control_id -> Control for all 1196 controls/enhancements."""
    with open(CATALOG_PATH, encoding="utf-8") as f:
        data = json.load(f)

    catalog_data = data.get("catalog", data)
    controls: dict[str, Control] = {}

    for group in catalog_data.get("groups", []):
        family_id = group["id"]
        family_title = group.get("title", "")

        for raw_ctrl in group.get("controls", []):
            ctrl = _parse_control(raw_ctrl, family_id, family_title)
            controls[ctrl.id] = ctrl

            # Control enhancements (nested controls)
            for raw_enh in raw_ctrl.get("controls", []):
                enh = _parse_control(raw_enh, family_id, family_title,
                                     is_enhancement=True, parent_id=ctrl.id)
                controls[enh.id] = enh

    for control in controls.values():
        if not control.incorporated_into:
            continue
        resolved_targets = [
            controls[target_id].display_id if target_id in controls else target_id.upper()
            for target_id in control.incorporated_into
        ]
        control.incorporated_into = resolved_targets
        if control.status == "withdrawn":
            target_text = ", ".join(resolved_targets) if resolved_targets else "another control"
            disposition = f"Withdrawn: Incorporated into {target_text}."
            if not control.statement:
                control.statement = disposition
            if not control.supplemental_guidance:
                control.supplemental_guidance = (
                    "NIST SP 800-53 Rev. 5 marks this control as withdrawn. "
                    f"It is not assessed independently; assessment coverage is handled under {target_text}."
                )

    return controls


@lru_cache(maxsize=6)
def load_baseline(baseline: str, include_non_assessable: bool = False) -> list[Control]:
    """Return ordered assessable Controls for a baseline (low|moderate|high).

    Withdrawn controls remain in the catalog for traceability, but they are not
    part of the active assessment/generation denominator unless explicitly
    requested for reference views.
    """
    baseline = baseline.lower()
    baseline_path = BASELINES_DIR / f"{baseline}.json"
    with open(baseline_path, encoding="utf-8") as f:
        baseline_data = json.load(f)

    all_controls = load_catalog()
    result: list[Control] = []

    control_ids = list(baseline_data["control_ids"])
    if include_non_assessable:
        control_ids.extend(baseline_data.get("excluded_non_assessable_control_ids", []))

    for ctrl_id in control_ids:
        ctrl = all_controls.get(ctrl_id)
        if ctrl and (include_non_assessable or ctrl.is_assessable):
            result.append(ctrl)

    return result


def get_families() -> list[tuple[str, str]]:
    """Return list of (family_id, family_title) tuples."""
    seen: dict[str, str] = {}
    for ctrl in load_catalog().values():
        if ctrl.family_id not in seen:
            seen[ctrl.family_id] = ctrl.family_title
    return sorted(seen.items())
