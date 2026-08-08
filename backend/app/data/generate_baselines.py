"""
Generate baseline control ID lists from the NIST 800-53 Rev 5 OSCAL catalog.
Baselines are defined per NIST SP 800-53B.

Run from the data/ directory:
  python generate_baselines.py
"""
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "nist_800_53_r5_catalog.json"

# NIST SP 800-53B Rev 5 — Moderate baseline control IDs (base + enhancements)
# Source: https://csrc.nist.gov/publications/detail/sp/800-53b/final
# These are the control IDs included in the MODERATE baseline.
MODERATE_CONTROLS = {
    # AC — Access Control
    "ac-1","ac-2","ac-2.1","ac-2.2","ac-2.3","ac-2.4",
    "ac-3","ac-4","ac-4.4","ac-5","ac-6","ac-6.1","ac-6.2","ac-6.5","ac-6.9","ac-6.10",
    "ac-7","ac-8","ac-11","ac-11.1","ac-12","ac-14","ac-17","ac-17.1","ac-17.2",
    "ac-17.3","ac-17.4","ac-18","ac-18.1","ac-19","ac-19.5","ac-20","ac-20.1","ac-20.2",
    "ac-21","ac-22",
    # AT — Awareness & Training
    "at-1","at-2","at-2.2","at-2.3","at-3","at-4",
    # AU — Audit & Accountability
    "au-1","au-2","au-3","au-3.1","au-4","au-5","au-6","au-6.1","au-6.3","au-7","au-7.1",
    "au-8","au-9","au-9.4","au-11","au-12","au-12.1","au-12.3",
    # CA — Assessment, Authorization & Monitoring
    "ca-1","ca-2","ca-2.2","ca-3","ca-5","ca-6","ca-7","ca-7.1","ca-8","ca-9",
    # CM — Configuration Management
    "cm-1","cm-2","cm-2.2","cm-2.7","cm-3","cm-3.1","cm-4","cm-5","cm-5.1","cm-6",
    "cm-7","cm-7.1","cm-7.2","cm-7.4","cm-7.5","cm-8","cm-8.1","cm-8.3","cm-9",
    "cm-10","cm-11",
    # CP — Contingency Planning
    "cp-1","cp-2","cp-2.1","cp-2.3","cp-2.5","cp-3","cp-4","cp-4.1","cp-6","cp-6.1",
    "cp-6.3","cp-7","cp-7.1","cp-7.2","cp-7.3","cp-8","cp-8.1","cp-8.2","cp-9",
    "cp-9.1","cp-9.3","cp-9.5","cp-10","cp-10.2",
    # IA — Identification & Authentication
    "ia-1","ia-2","ia-2.1","ia-2.2","ia-2.8","ia-2.12","ia-3","ia-4","ia-4.4","ia-5",
    "ia-5.1","ia-5.2","ia-5.3","ia-5.4","ia-5.6","ia-5.7","ia-5.13","ia-6","ia-7",
    "ia-8","ia-8.1","ia-8.2","ia-8.4","ia-11","ia-12","ia-12.2","ia-12.3","ia-12.4","ia-12.5",
    # IR — Incident Response
    "ir-1","ir-2","ir-3","ir-3.2","ir-4","ir-4.1","ir-5","ir-6","ir-6.1","ir-7",
    "ir-7.1","ir-8",
    # MA — Maintenance
    "ma-1","ma-2","ma-3","ma-3.1","ma-3.2","ma-4","ma-4.2","ma-5","ma-6",
    # MP — Media Protection
    "mp-1","mp-2","mp-3","mp-4","mp-5","mp-6","mp-6.1","mp-6.2","mp-7",
    # PE — Physical & Environmental Protection
    "pe-1","pe-2","pe-3","pe-4","pe-5","pe-6","pe-6.1","pe-8","pe-9","pe-10","pe-11",
    "pe-12","pe-13","pe-13.2","pe-14","pe-14.1","pe-15","pe-16","pe-17",
    # PL — Planning
    "pl-1","pl-2","pl-4","pl-4.1","pl-8","pl-10","pl-11",
    # PM — Program Management
    "pm-1","pm-2","pm-3","pm-4","pm-5","pm-5.1","pm-6","pm-7","pm-8","pm-9","pm-10",
    "pm-11","pm-12","pm-13","pm-14","pm-15","pm-16",
    # PS — Personnel Security
    "ps-1","ps-2","ps-3","ps-4","ps-4.2","ps-5","ps-6","ps-7","ps-8","ps-9",
    # PT — PII Processing & Transparency
    "pt-1","pt-2","pt-3","pt-4","pt-5","pt-6","pt-7","pt-8",
    # RA — Risk Assessment
    "ra-1","ra-2","ra-3","ra-3.1","ra-5","ra-5.2","ra-5.4","ra-5.5","ra-5.11","ra-7","ra-9",
    # SA — System & Services Acquisition
    "sa-1","sa-2","sa-3","sa-4","sa-4.1","sa-4.2","sa-4.5","sa-4.8","sa-4.9","sa-4.10",
    "sa-5","sa-8","sa-9","sa-9.2","sa-10","sa-11","sa-15","sa-16","sa-17","sa-21",
    # SC — System & Communications Protection
    "sc-1","sc-2","sc-3","sc-4","sc-5","sc-7","sc-7.3","sc-7.4","sc-7.5","sc-7.7",
    "sc-7.8","sc-7.18","sc-7.21","sc-7.25","sc-8","sc-8.1","sc-10","sc-12","sc-12.1",
    "sc-13","sc-15","sc-17","sc-18","sc-20","sc-21","sc-22","sc-23","sc-24","sc-28",
    "sc-28.1","sc-39",
    # SI — System & Information Integrity
    "si-1","si-2","si-2.2","si-3","si-3.1","si-3.2","si-4","si-4.2","si-4.4","si-4.5",
    "si-5","si-6","si-7","si-7.1","si-7.7","si-8","si-8.1","si-8.2","si-10","si-11",
    "si-12","si-16",
    # SR — Supply Chain Risk Management
    "sr-1","sr-2","sr-3","sr-5","sr-6","sr-8","sr-10","sr-11","sr-11.1","sr-11.2","sr-12",
}

# LOW baseline is a subset of moderate (base controls, fewer enhancements)
LOW_CONTROLS = {
    "ac-1","ac-2","ac-3","ac-7","ac-8","ac-14","ac-17","ac-18","ac-19","ac-20","ac-22",
    "at-1","at-2","at-3","at-4",
    "au-1","au-2","au-3","au-4","au-5","au-6","au-8","au-9","au-11","au-12",
    "ca-1","ca-2","ca-3","ca-5","ca-6","ca-7","ca-9",
    "cm-1","cm-2","cm-6","cm-7","cm-8","cm-10","cm-11",
    "cp-1","cp-2","cp-9","cp-10",
    "ia-1","ia-2","ia-2.1","ia-2.2","ia-2.12","ia-3","ia-4","ia-5","ia-6","ia-7","ia-8","ia-8.1","ia-8.2","ia-8.4","ia-11",
    "ir-1","ir-2","ir-4","ir-5","ir-6","ir-7","ir-8",
    "ma-1","ma-2","ma-4","ma-5",
    "mp-1","mp-2","mp-6","mp-7",
    "pe-1","pe-2","pe-3","pe-6","pe-8","pe-9","pe-10","pe-11","pe-12","pe-13","pe-14","pe-15","pe-16",
    "pl-1","pl-2","pl-4","pl-8","pl-10","pl-11",
    "pm-1","pm-2","pm-3","pm-4","pm-5","pm-6","pm-7","pm-8","pm-9","pm-10","pm-11","pm-12","pm-13","pm-14","pm-15","pm-16",
    "ps-1","ps-2","ps-3","ps-4","ps-5","ps-6","ps-7","ps-8","ps-9",
    "pt-1","pt-2","pt-3","pt-4","pt-5","pt-6","pt-7","pt-8",
    "ra-1","ra-2","ra-3","ra-5","ra-7","ra-9",
    "sa-1","sa-2","sa-3","sa-4","sa-5","sa-8","sa-9","sa-10","sa-11",
    "sc-1","sc-5","sc-7","sc-12","sc-13","sc-15","sc-17","sc-18","sc-20","sc-21","sc-22","sc-39",
    "si-1","si-2","si-3","si-4","si-5","si-10","si-11","si-12",
    "sr-1","sr-2","sr-3","sr-5","sr-8","sr-10","sr-11","sr-12",
}

# HIGH baseline adds everything from moderate plus additional enhancements
# Build HIGH as superset — include everything in moderate + additional HIGH-only controls
HIGH_ADDITIONS = {
    "ac-2.5","ac-2.9","ac-2.11","ac-2.12","ac-2.13","ac-3.2","ac-3.4","ac-4.2","ac-4.12",
    "ac-4.15","ac-4.17","ac-6.3","ac-6.4","ac-6.7","ac-6.8","ac-7.2","ac-17.6","ac-17.9",
    "ac-18.2","ac-18.3","ac-18.4","ac-19.4",
    "au-2.3","au-3.2","au-6.5","au-6.6","au-9.2","au-9.3","au-10","au-12.2",
    "ca-2.1","ca-7.3","ca-7.4","ca-8.1","ca-8.2",
    "cm-2.6","cm-3.2","cm-5.2","cm-7.6","cm-8.2","cm-8.4","cm-9.1",
    "cp-2.2","cp-2.4","cp-2.6","cp-2.7","cp-2.8","cp-4.2","cp-6.2","cp-7.4","cp-7.5","cp-7.6",
    "cp-9.2","cp-9.6","cp-9.7","cp-9.8","cp-10.4","cp-11","cp-12","cp-13",
    "ia-2.3","ia-2.4","ia-2.5","ia-2.9","ia-2.13","ia-3.1","ia-4.3","ia-5.8","ia-5.9",
    "ia-5.10","ia-5.12","ia-5.14","ia-5.15","ia-5.16","ia-5.17","ia-8.5","ia-9","ia-10","ia-13",
    "ir-3.1","ir-4.2","ir-4.3","ir-4.4","ir-4.5","ir-4.6","ir-4.8","ir-4.10","ir-4.11","ir-4.12",
    "ir-4.13","ir-4.14","ir-5.1","ir-6.2","ir-6.3","ir-9","ir-9.1","ir-9.2","ir-9.3","ir-9.4",
    "ma-3.3","ma-3.4","ma-4.1","ma-4.3","ma-4.4","ma-4.5","ma-4.6","ma-4.7","ma-6.1","ma-6.2","ma-6.3",
    "mp-4.2","mp-6.3","mp-6.6","mp-6.7","mp-6.8","mp-8",
    "pe-3.1","pe-3.2","pe-6.2","pe-6.3","pe-6.4","pe-11.1","pe-13.1","pe-13.3","pe-14.2","pe-18","pe-19","pe-20",
    "ra-2.1","ra-3.2","ra-5.1","ra-5.3","ra-5.6","ra-5.10","ra-6","ra-7.1","ra-7.2","ra-10",
    "sa-4.3","sa-4.4","sa-4.6","sa-4.7","sa-5.1","sa-9.1","sa-9.3","sa-9.4","sa-9.5","sa-10.1",
    "sa-10.2","sa-11.1","sa-11.2","sa-11.4","sa-11.5","sa-11.6","sa-11.8","sa-12","sa-15.1",
    "sa-15.3","sa-15.8","sa-15.9","sa-20","sa-22","sa-23",
    "sc-2.1","sc-4.2","sc-7.9","sc-7.10","sc-7.11","sc-7.13","sc-7.14","sc-7.15","sc-7.17",
    "sc-7.19","sc-7.20","sc-7.22","sc-7.23","sc-7.26","sc-7.29","sc-8.2","sc-8.3","sc-8.4","sc-8.5",
    "sc-11","sc-12.2","sc-12.3","sc-13.1","sc-16","sc-19","sc-23.1","sc-25","sc-26","sc-27",
    "sc-28.2","sc-29","sc-30","sc-31","sc-32","sc-34","sc-35","sc-36","sc-37","sc-43","sc-44",
    "si-2.1","si-2.3","si-3.8","si-4.1","si-4.7","si-4.9","si-4.10","si-4.11","si-4.12","si-4.13",
    "si-4.14","si-4.15","si-4.16","si-4.17","si-4.19","si-4.20","si-4.22","si-4.23","si-4.24","si-4.25",
    "si-6.1","si-6.2","si-7.2","si-7.5","si-7.6","si-7.8","si-7.9","si-7.10","si-7.14","si-7.15",
    "si-7.16","si-7.17","si-7.20","si-8.3","si-13","si-14","si-15","si-17","si-18","si-19","si-20",
    "sr-4","sr-6.1","sr-7","sr-9","sr-9.1","sr-11.3",
}
HIGH_CONTROLS = MODERATE_CONTROLS | HIGH_ADDITIONS


def _load_catalog_statuses() -> dict[str, str]:
    catalog_data = json.loads(CATALOG_PATH.read_text(encoding="utf-8")).get("catalog", {})
    statuses: dict[str, str] = {}
    for group in catalog_data.get("groups", []):
        for control in group.get("controls", []):
            for item in [control, *control.get("controls", [])]:
                status = "active"
                for prop in item.get("props", []):
                    if prop.get("name") == "status":
                        status = str(prop.get("value") or "active").strip().lower()
                        break
                statuses[item["id"]] = status
    return statuses


def write_baseline(name: str, control_ids: set, output_path: Path) -> None:
    statuses = _load_catalog_statuses()
    excluded = sorted(
        control_id
        for control_id in control_ids
        if statuses.get(control_id) == "withdrawn" or control_id not in statuses
    )
    active_ids = sorted(
        control_id
        for control_id in control_ids
        if statuses.get(control_id) != "withdrawn" and control_id in statuses
    )
    data = {
        "baseline": name,
        "description": f"NIST SP 800-53 Rev 5 {name.title()} Baseline",
        "control_ids": active_ids,
        "count": len(active_ids),
        "excluded_non_assessable_control_ids": excluded,
        "excluded_non_assessable_count": len(excluded),
    }
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {name}: {len(active_ids)} controls -> {output_path}")


if __name__ == "__main__":
    baselines_dir = Path(__file__).parent / "baselines"
    baselines_dir.mkdir(exist_ok=True)
    write_baseline("low", LOW_CONTROLS, baselines_dir / "low.json")
    write_baseline("moderate", MODERATE_CONTROLS, baselines_dir / "moderate.json")
    write_baseline("high", HIGH_CONTROLS, baselines_dir / "high.json")
    print("Done.")
