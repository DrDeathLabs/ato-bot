from __future__ import annotations

import argparse
import json
import subprocess
import sys
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
        description="Run the generic family package trial across one or more NIST families in the separate test area."
    )
    parser.add_argument("assessment_id", type=int)
    parser.add_argument("--families", default=",".join(DEFAULT_FAMILIES))
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    generic_script = repo_root / "backend" / "test_harness" / "generic_family_package_trial.py"
    batch_root = repo_root / "backend" / "outputs" / "test_harness" / "batch_runs"
    batch_root.mkdir(parents=True, exist_ok=True)

    families = [item.strip().upper() for item in args.families.split(",") if item.strip()]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    batch_dir = batch_root / f"assessment_{args.assessment_id}_{timestamp}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    summary_path = batch_dir / "summary.json"

    if args.resume and summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = {
            "assessment_id": args.assessment_id,
            "started_at": datetime.now(UTC).isoformat(),
            "families_requested": families,
            "families": {},
        }

    script_text = generic_script.read_text(encoding="utf-8")

    for family in families:
        if args.resume and summary["families"].get(family, {}).get("status") == "complete":
            print(f"[skip] {family} already complete")
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
                family_entry["status"] = "complete"
                family_entry["result"] = payload
            except json.JSONDecodeError:
                family_entry["status"] = "error"
                family_entry["error"] = "Could not parse JSON output"
        else:
            family_entry["status"] = "error"

        summary["families"][family] = family_entry
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        family_log = batch_dir / f"{family}.log"
        family_log.write_text(proc.stdout + "\n\nSTDERR\n" + proc.stderr, encoding="utf-8")

        if proc.returncode != 0:
            print(f"[error] {family} failed with return code {proc.returncode}")
        else:
            print(f"[done] {family}")

    summary["finished_at"] = datetime.now(UTC).isoformat()
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
