from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


EXPECTED_FAMILY_COUNT = 20


class PackagingError(RuntimeError):
    """Raised when a family package cannot be assembled safely."""


@dataclass(slots=True)
class FamilySelection:
    family_id: str
    family_root: Path
    run_dir: Path
    manifest_path: Path
    manifest: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a portable ATO Bot usability package from the latest per-family harness outputs."
    )
    parser.add_argument("assessment_id", nargs="?", type=int, default=146)
    return parser.parse_args()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def outputs_root() -> Path:
    return repo_root() / "backend" / "outputs" / "test_harness"


def usability_root() -> Path:
    return outputs_root() / "usability_packages"


def discover_family_roots(root: Path) -> dict[str, Path]:
    family_dirs: dict[str, Path] = {}
    for path in sorted(root.glob("*_family_package")):
        if not path.is_dir():
            continue
        family_id = path.name.removesuffix("_family_package").upper()
        if not re.fullmatch(r"[A-Z]{2}", family_id):
            continue
        family_dirs[family_id] = path
    if len(family_dirs) != EXPECTED_FAMILY_COUNT:
        raise PackagingError(
            f"Expected {EXPECTED_FAMILY_COUNT} family package directories under {root}, found {len(family_dirs)}."
        )
    return dict(sorted(family_dirs.items()))


def choose_latest_run_dir(family_root: Path, assessment_id: int) -> Path:
    candidates = [path for path in family_root.glob(f"assessment_{assessment_id}_*") if path.is_dir()]
    if not candidates:
        raise PackagingError(f"No assessment_{assessment_id}_* run directories found under {family_root}.")
    return sorted(candidates, key=lambda path: path.name)[-1]


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive I/O guard
        raise PackagingError(f"Could not parse manifest {manifest_path}: {exc}") from exc
    generated = data.get("generated")
    if not isinstance(generated, list) or not generated:
        raise PackagingError(f"Manifest {manifest_path} is missing a non-empty generated list.")
    return data


def select_families(assessment_id: int) -> list[FamilySelection]:
    selected: list[FamilySelection] = []
    for family_id, family_root in discover_family_roots(outputs_root()).items():
        run_dir = choose_latest_run_dir(family_root, assessment_id)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise PackagingError(f"Missing manifest.json in {run_dir}.")
        manifest = load_manifest(manifest_path)
        selected.append(
            FamilySelection(
                family_id=family_id,
                family_root=family_root,
                run_dir=run_dir,
                manifest_path=manifest_path,
                manifest=manifest,
            )
        )
    return selected


def sanitize_filename_component(text: str, *, max_length: int = 72) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", normalized).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    if not cleaned:
        cleaned = "document"
    return cleaned[:max_length].rstrip("._-") or "document"


def preferred_readable_stem(item: dict[str, Any]) -> str:
    title = item.get("title")
    if isinstance(title, str) and title.strip():
        return sanitize_filename_component(title)
    filename = item.get("filename")
    if isinstance(filename, str) and filename.strip():
        return sanitize_filename_component(Path(filename).stem)
    key = item.get("key")
    if isinstance(key, str) and key.strip():
        return sanitize_filename_component(key)
    return "document"


def ensure_unique_docx_name(stem: str, key: str, used_names: set[str]) -> str:
    safe_key = sanitize_filename_component(key or "doc", max_length=48)
    candidate = f"{stem}.docx"
    if candidate not in used_names:
        used_names.add(candidate)
        return candidate
    candidate = f"{stem}__{safe_key}.docx"
    if candidate not in used_names:
        used_names.add(candidate)
        return candidate
    suffix = 2
    while True:
        candidate = f"{stem}__{safe_key}_{suffix}.docx"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        suffix += 1


def localize_storage_path(storage_area: str) -> Path:
    storage_area = storage_area.rstrip("/\\")
    prefix = "/app/"
    if storage_area.startswith(prefix):
        relative_parts = [part for part in storage_area[len(prefix) :].split("/") if part]
        return repo_root() / "backend" / Path(*relative_parts)
    return Path(storage_area)


def infer_storage_dir(selection: FamilySelection) -> Path:
    generated = selection.manifest["generated"]
    storage_areas = {
        str(item.get("storage_area")).strip()
        for item in generated
        if isinstance(item.get("storage_area"), str) and str(item.get("storage_area")).strip()
    }
    if storage_areas:
        if len(storage_areas) != 1:
            raise PackagingError(f"Manifest {selection.manifest_path} references multiple storage areas: {sorted(storage_areas)}")
        storage_dir = localize_storage_path(next(iter(storage_areas)))
    else:
        uploads_root = selection.run_dir / "uploads"
        candidates = [path for path in uploads_root.iterdir() if path.is_dir()] if uploads_root.exists() else []
        if len(candidates) != 1:
            raise PackagingError(f"Could not infer a unique uploads directory for {selection.run_dir}.")
        storage_dir = candidates[0]
    if not storage_dir.exists():
        raise PackagingError(f"Storage directory {storage_dir} referenced by {selection.manifest_path} does not exist.")
    return storage_dir


def map_generated_files(selection: FamilySelection) -> list[tuple[dict[str, Any], Path]]:
    generated = selection.manifest["generated"]
    storage_dir = infer_storage_dir(selection)
    physical_files = sorted(
        [path for path in storage_dir.glob("*.docx") if path.is_file()],
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    if len(physical_files) != len(generated):
        raise PackagingError(
            f"{selection.family_id} expected {len(generated)} generated .docx files in {storage_dir}, found {len(physical_files)}."
        )
    return list(zip(generated, physical_files, strict=True))


def summarize_proof(manifest: dict[str, Any]) -> dict[str, Any] | None:
    proof = manifest.get("proof")
    if not isinstance(proof, dict):
        return None
    results = proof.get("results")
    if not isinstance(results, list):
        return {
            "proof_assessment_id": proof.get("proof_assessment_id"),
            "compliant_count": 0,
            "noncompliant_count": 0,
            "failing_control_ids": [],
        }
    compliant_count = 0
    failing_control_ids: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        control_id = item.get("control_id")
        status = item.get("status")
        if status == "compliant":
            compliant_count += 1
        elif isinstance(control_id, str) and control_id:
            failing_control_ids.append(control_id)
    return {
        "proof_assessment_id": proof.get("proof_assessment_id"),
        "compliant_count": compliant_count,
        "noncompliant_count": len(failing_control_ids),
        "failing_control_ids": failing_control_ids,
    }


def build_readme(assessment_id: int, timestamp: str, families: list[dict[str, Any]]) -> str:
    residual_families = [item for item in families if item.get("proof_summary", {}).get("failing_control_ids")]
    residual_list = ", ".join(
        f"{item['family_id']} ({', '.join(item['proof_summary']['failing_control_ids'])})"
        for item in residual_families
    ) or "None"
    family_codes = ", ".join(item["family_id"] for item in families)
    return "\n".join(
        [
            f"# ATO Bot Usability Package for Assessment {assessment_id}",
            "",
            "This package is assembled from the latest realism-biased family-package outputs generated by the test harness.",
            "It is intended for ATO Bot ingestion and testing, not for proof validation.",
            "Residual proof gaps may still exist in some families; they are recorded in `package_manifest.json` and do not block package creation.",
            "",
            "## Package Layout",
            "",
            "- `artifacts/<FAMILY>/`: copied `.docx` payloads for that family using readable filenames",
            "- `artifacts/<FAMILY>/family_manifest.json`: original manifest copied from the selected family run",
            "- `package_manifest.json`: package-level provenance, copied document metadata, and proof summaries",
            "- `README.md`: this overview",
            "",
            "## Source Selection Rule",
            "",
            f"For each family under `backend/outputs/test_harness/*_family_package`, this package selects the newest `assessment_{assessment_id}_*` run directory by timestamp in the directory name.",
            "",
            "## Families Included",
            "",
            family_codes,
            "",
            "## Residual Proof Findings",
            "",
            "Look in `package_manifest.json` under each family entry's `proof_summary.failing_control_ids`.",
            f"Current residual families: {residual_list}",
            "",
            "## Build Metadata",
            "",
            f"- Assessment ID: {assessment_id}",
            "- Package policy: `latest_per_family_realism`",
            f"- Generated at (UTC): {timestamp}",
        ]
    ) + "\n"


def relative_file_set(root: Path) -> set[str]:
    return {
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file()
    }


def validate_package(staging_dir: Path, zip_path: Path, family_entries: list[dict[str, Any]]) -> None:
    artifact_root = staging_dir / "artifacts"
    actual_families = sorted(path.name for path in artifact_root.iterdir() if path.is_dir())
    expected_families = sorted(entry["family_id"] for entry in family_entries)
    if actual_families != expected_families:
        raise PackagingError(f"Artifact family directories do not match expected family list: {actual_families} != {expected_families}")

    package_manifest = json.loads((staging_dir / "package_manifest.json").read_text(encoding="utf-8"))
    package_families = package_manifest.get("families")
    if not isinstance(package_families, list) or len(package_families) != EXPECTED_FAMILY_COUNT:
        raise PackagingError("package_manifest.json does not include all 20 families.")

    for entry in family_entries:
        family_dir = artifact_root / entry["family_id"]
        manifest_copy = family_dir / "family_manifest.json"
        if not manifest_copy.exists():
            raise PackagingError(f"Missing family_manifest.json in {family_dir}")
        copied_names = [doc["copied_readable_filename"] for doc in entry["copied_documents"]]
        if len(copied_names) != len(set(copied_names)):
            raise PackagingError(f"Copied filenames are not unique in family {entry['family_id']}.")
        for doc in entry["copied_documents"]:
            copied_path = family_dir / doc["copied_readable_filename"]
            if not copied_path.exists():
                raise PackagingError(f"Missing copied document {copied_path}.")

    staging_files = relative_file_set(staging_dir)
    with zipfile.ZipFile(zip_path) as zip_file:
        zip_names = {
            name.split("/", 1)[1]
            for name in zip_file.namelist()
            if not name.endswith("/") and "/" in name
        }
        if zip_names != staging_files:
            raise PackagingError("Zip contents do not match the staging directory file set.")
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            zip_file.extractall(temp_dir)
            extracted_root = temp_dir / staging_dir.name
            if not extracted_root.exists():
                raise PackagingError("Zip extraction did not produce the expected root folder.")
            extracted_files = relative_file_set(extracted_root)
            if extracted_files != staging_files:
                raise PackagingError("Extracted zip contents do not match the staging directory file set.")


def create_package(assessment_id: int) -> tuple[Path, Path, list[dict[str, Any]]]:
    selected = select_families(assessment_id)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    package_name = f"assessment_{assessment_id}_latest_realism_{timestamp}"
    staging_dir = usability_root() / package_name
    zip_path = usability_root() / f"{package_name}.zip"

    if staging_dir.exists() or zip_path.exists():
        raise PackagingError(f"Refusing to overwrite existing package output for {package_name}.")

    staging_dir.mkdir(parents=True, exist_ok=False)
    artifacts_root = staging_dir / "artifacts"
    artifacts_root.mkdir(parents=True, exist_ok=False)

    family_entries: list[dict[str, Any]] = []

    for selection in selected:
        family_dir = artifacts_root / selection.family_id
        family_dir.mkdir(parents=True, exist_ok=False)

        used_names: set[str] = set()
        copied_documents: list[dict[str, Any]] = []
        for item, source_path in map_generated_files(selection):
            if not source_path.exists():
                raise PackagingError(f"Source file {source_path} for family {selection.family_id} does not exist.")
            key = str(item.get("key") or "doc")
            readable_name = ensure_unique_docx_name(preferred_readable_stem(item), key, used_names)
            destination = family_dir / readable_name
            shutil.copy2(source_path, destination)
            copied_documents.append(
                {
                    "key": key,
                    "document_id": item.get("document_id"),
                    "original_uuid_filename": source_path.name,
                    "copied_readable_filename": readable_name,
                    "title": item.get("title"),
                    "document_type": item.get("document_type"),
                    "document_intent": item.get("document_intent"),
                    "controls_addressed": item.get("controls_addressed") or [],
                }
            )

        shutil.copy2(selection.manifest_path, family_dir / "family_manifest.json")

        proof_summary = summarize_proof(selection.manifest)
        family_entries.append(
            {
                "family_id": selection.family_id,
                "selected_source_directory": str(selection.run_dir),
                "source_manifest_path": str(selection.manifest_path),
                "copied_documents": copied_documents,
                "proof_summary": proof_summary,
            }
        )

    package_manifest = {
        "assessment_id": assessment_id,
        "package_policy": "latest_per_family_realism",
        "generated_at": datetime.now(UTC).isoformat(),
        "selected_family_list": [entry["family_id"] for entry in family_entries],
        "families": family_entries,
    }
    (staging_dir / "package_manifest.json").write_text(json.dumps(package_manifest, indent=2), encoding="utf-8")
    (staging_dir / "README.md").write_text(
        build_readme(assessment_id, package_name.rsplit("_", 1)[-1], family_entries),
        encoding="utf-8",
    )

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path in sorted(staging_dir.rglob("*")):
            if path.is_file():
                arcname = Path(staging_dir.name) / path.relative_to(staging_dir)
                zip_file.write(path, arcname=str(arcname).replace("\\", "/"))

    validate_package(staging_dir, zip_path, family_entries)
    return staging_dir, zip_path, family_entries


def main() -> int:
    args = parse_args()
    try:
        staging_dir, zip_path, family_entries = create_package(args.assessment_id)
    except PackagingError as exc:
        print(f"packaging error: {exc}", file=sys.stderr)
        return 1

    residual = {
        entry["family_id"]: entry["proof_summary"]["failing_control_ids"]
        for entry in family_entries
        if entry.get("proof_summary") and entry["proof_summary"].get("failing_control_ids")
    }

    print(f"output_folder: {staging_dir}")
    print(f"zip_path: {zip_path}")
    print(f"families_included: {', '.join(entry['family_id'] for entry in family_entries)}")
    if residual:
        print("residual_proof_findings:")
        for family_id, controls in residual.items():
            print(f"  {family_id}: {', '.join(controls)}")
    else:
        print("residual_proof_findings: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
