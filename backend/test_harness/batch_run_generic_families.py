from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_FAMILIES = [
    "AC",
    "AT",
    "AU",
    "CA",
    "CM",
    "CP",
    "IA",
    "IR",
    "MA",
    "MP",
    "PE",
    "PL",
    "PM",
    "PS",
    "PT",
    "RA",
    "SA",
    "SC",
    "SI",
    "SR",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run family artifact proof across one or more NIST families."
    )
    parser.add_argument("assessment_id", type=int)
    parser.add_argument("--families", default=",".join(DEFAULT_FAMILIES))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--run-dir",
        type=Path,
        help="Existing batch directory to resume, or explicit directory for a new run.",
    )
    return parser.parse_args()


def _proof_result(result: dict[str, object] | None) -> dict[str, object]:
    proof = (result or {}).get("proof") or {}
    rows = proof.get("results") or []
    failing = [
        str(row.get("control_id"))
        for row in rows
        if str(row.get("status", "")).lower() != "compliant"
    ]
    return {
        "controls": len(rows),
        "compliant": len(rows) - len(failing),
        "failing_control_ids": failing,
        "clean": bool(rows) and not failing,
    }


def _entry_is_clean(entry: dict[str, object] | None) -> bool:
    if not entry or entry.get("status") not in {"complete", "proof_clean"}:
        return False
    proof_summary = entry.get("proof_summary")
    if proof_summary:
        return bool(proof_summary.get("clean"))
    return bool(_proof_result(entry.get("result"))["clean"])


def _resolve_batch_dir(args: argparse.Namespace, batch_root: Path, families: list[str]) -> Path:
    if args.run_dir:
        path = args.run_dir
        if not path.is_absolute():
            path = batch_root / path
        return path.resolve()

    if args.resume:
        candidates = sorted(
            batch_root.glob(f"assessment_{args.assessment_id}_*"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            summary_path = candidate / "summary.json"
            if not summary_path.exists():
                continue
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if summary.get("families_requested") == families:
                return candidate.resolve()
        raise RuntimeError("No resumable batch run matches this assessment and family list.")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return (batch_root / f"assessment_{args.assessment_id}_{timestamp}").resolve()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    generic_script = repo_root / "backend" / "test_harness" / "generic_family_package_trial.py"
    batch_root = repo_root / "backend" / "outputs" / "test_harness" / "batch_runs"
    batch_root.mkdir(parents=True, exist_ok=True)

    families = [item.strip().upper() for item in args.families.split(",") if item.strip()]
    unknown = sorted(set(families) - set(DEFAULT_FAMILIES))
    if unknown:
        raise RuntimeError(f"Unknown NIST families: {', '.join(unknown)}")
    if len(families) != len(set(families)):
        raise RuntimeError("Family list contains duplicates.")

    batch_dir = _resolve_batch_dir(args, batch_root, families)
    batch_dir.mkdir(parents=True, exist_ok=True)
    summary_path = batch_dir / "summary.json"

    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("assessment_id") != args.assessment_id or summary.get("families_requested") != families:
            raise RuntimeError("Existing batch directory does not match the requested assessment and families.")
    else:
        summary = {
            "assessment_id": args.assessment_id,
            "started_at": datetime.now(UTC).isoformat(),
            "families_requested": families,
            "families": {},
        }

    script_text = generic_script.read_text(encoding="utf-8")

    for family in families:
        if args.resume and _entry_is_clean(summary["families"].get(family)):
            print(f"[skip] {family} already proof-clean")
            continue

        print(f"[run] {family}")
        proc = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "backend",
                "python",
                "-",
                str(args.assessment_id),
                family,
                "--proof",
            ],
            input=script_text,
            text=True,
            capture_output=True,
            cwd=repo_root,
        )

        family_entry: dict[str, object] = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "completed_at": datetime.now(UTC).isoformat(),
        }

        if proc.returncode == 0:
            try:
                payload = json.loads(proc.stdout)
                proof_summary = _proof_result(payload)
                family_entry["result"] = payload
                family_entry["proof_summary"] = proof_summary
                family_entry["status"] = "proof_clean" if proof_summary["clean"] else "proof_residual"
            except json.JSONDecodeError:
                family_entry["status"] = "error"
                family_entry["error"] = "Could not parse JSON output"
        else:
            family_entry["status"] = "error"

        summary["families"][family] = family_entry
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        family_log = batch_dir / f"{family}.log"
        family_log.write_text(proc.stdout + "\n\nSTDERR\n" + proc.stderr, encoding="utf-8")

        if family_entry["status"] == "proof_clean":
            print(f"[clean] {family}")
        elif proc.returncode != 0:
            print(f"[error] {family} failed with return code {proc.returncode}")
        else:
            failing = family_entry.get("proof_summary", {}).get("failing_control_ids", [])
            print(f"[residual] {family}: {', '.join(failing)}")

    clean_families = [family for family in families if _entry_is_clean(summary["families"].get(family))]
    summary["finished_at"] = datetime.now(UTC).isoformat()
    summary["run_scope"] = "full_20_family" if families == DEFAULT_FAMILIES else "focused"
    summary["status"] = (
        "full_run_green"
        if families == DEFAULT_FAMILIES and len(clean_families) == len(DEFAULT_FAMILIES)
        else "focused_run_green"
        if len(clean_families) == len(families)
        else "residual_findings"
    )
    summary["clean_families"] = clean_families
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"summary: {summary_path}")
    return 0 if len(clean_families) == len(families) else 1


if __name__ == "__main__":
    raise SystemExit(main())
