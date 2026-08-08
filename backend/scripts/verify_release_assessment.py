"""Read-only release gate for a governed Moderate-baseline assessment."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal, engine
from app.models.orm import (
    Assessment,
    AssessmentPlan,
    ControlFinding,
    IngestionRun,
    ObjectiveDetermination,
)
from app.services.assessment_governance import build_finalization_readiness
from app.services.controls.catalog import load_baseline


def _expected_moderate_scope() -> tuple[set[str], set[tuple[str, str]]]:
    controls = load_baseline("moderate")
    control_ids = {control.display_id for control in controls}
    objectives = {
        (control.display_id, objective.split(":", 1)[0].strip())
        for control in controls
        for objective in control.assessment_objectives
    }
    return control_ids, objectives


def evaluate_release_metrics(
    *,
    assessment_status: str,
    finalization_status: str,
    actual_control_ids: set[str],
    actual_objectives: set[tuple[str, str]],
    expected_control_ids: set[str],
    expected_objectives: set[tuple[str, str]],
    frozen_documents: list[dict[str, Any]],
    healthy_run_ids: set[int],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    missing_controls = sorted(expected_control_ids - actual_control_ids)
    unexpected_controls = sorted(actual_control_ids - expected_control_ids)
    add(
        "moderate_control_totality",
        not missing_controls and not unexpected_controls,
        (
            f"{len(actual_control_ids)}/{len(expected_control_ids)} exact controls; "
            f"missing={missing_controls[:20]}; unexpected={unexpected_controls[:20]}"
        ),
    )

    missing_objectives = sorted(expected_objectives - actual_objectives)
    unexpected_objectives = sorted(actual_objectives - expected_objectives)
    add(
        "moderate_objective_totality",
        not missing_objectives and not unexpected_objectives,
        (
            f"{len(actual_objectives)}/{len(expected_objectives)} exact objectives; "
            f"missing={missing_objectives[:20]}; unexpected={unexpected_objectives[:20]}"
        ),
    )

    families = {control_id.split("-", 1)[0] for control_id in actual_control_ids}
    expected_families = {control_id.split("-", 1)[0] for control_id in expected_control_ids}
    add(
        "family_totality",
        families == expected_families,
        f"{len(families)}/{len(expected_families)} families: {sorted(families)}",
    )

    malformed_scope = [
        item
        for item in frozen_documents
        if not item.get("document_id") or not item.get("ingestion_run_id") or not item.get("file_hash")
    ]
    frozen_run_ids = {int(item["ingestion_run_id"]) for item in frozen_documents if item.get("ingestion_run_id")}
    unhealthy_run_ids = sorted(frozen_run_ids - healthy_run_ids)
    add(
        "frozen_evidence_scope",
        bool(frozen_documents) and not malformed_scope and not unhealthy_run_ids,
        (
            f"{len(frozen_documents)} frozen documents; malformed={len(malformed_scope)}; "
            f"unhealthy_ingestion_runs={unhealthy_run_ids[:20]}"
        ),
    )

    add(
        "execution_complete",
        assessment_status == "complete",
        f"assessment status={assessment_status}",
    )
    add(
        "governance_ready",
        bool(readiness.get("ready")),
        f"blockers={[item.get('code') for item in readiness.get('blockers', [])]}",
    )
    add(
        "assessment_finalized",
        finalization_status == "finalized",
        f"finalization status={finalization_status}",
    )

    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "counts": {
            "families": len(families),
            "controls": len(actual_control_ids),
            "objectives": len(actual_objectives),
            "frozen_documents": len(frozen_documents),
        },
        "governance": readiness,
    }


async def verify_assessment(assessment_id: int) -> dict[str, Any]:
    expected_control_ids, expected_objectives = _expected_moderate_scope()
    async with AsyncSessionLocal() as db:
        assessment = await db.scalar(select(Assessment).where(Assessment.id == assessment_id))
        if not assessment:
            raise ValueError(f"Assessment {assessment_id} not found")
        plan = await db.scalar(select(AssessmentPlan).where(AssessmentPlan.assessment_id == assessment_id))
        findings = (
            await db.execute(select(ControlFinding).where(ControlFinding.assessment_id == assessment_id))
        ).scalars().all()
        determinations = (
            await db.execute(
                select(ObjectiveDetermination).where(ObjectiveDetermination.assessment_id == assessment_id)
            )
        ).scalars().all()
        readiness = await build_finalization_readiness(assessment_id, db)

        frozen_documents = list((plan.scope_json or {}).get("documents") or []) if plan else []
        frozen_run_ids = {
            int(item["ingestion_run_id"])
            for item in frozen_documents
            if item.get("ingestion_run_id")
        }
        healthy_run_ids: set[int] = set()
        if frozen_run_ids:
            runs = (
                await db.execute(select(IngestionRun).where(IngestionRun.id.in_(frozen_run_ids)))
            ).scalars().all()
            healthy_run_ids = {
                run.id
                for run in runs
                if run.status == "complete"
                and run.quality_status == "passed"
                and run.readiness_eligible
                and not (run.fallback_stages or [])
            }

    result = evaluate_release_metrics(
        assessment_status=assessment.status,
        finalization_status=assessment.finalization_status,
        actual_control_ids={finding.control_id for finding in findings},
        actual_objectives={(row.control_id, row.objective_id) for row in determinations},
        expected_control_ids=expected_control_ids,
        expected_objectives=expected_objectives,
        frozen_documents=frozen_documents,
        healthy_run_ids=healthy_run_ids,
        readiness=readiness,
    )
    return {"assessment_id": assessment_id, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assessment_id", type=int)
    args = parser.parse_args()

    async def run_and_dispose() -> dict[str, Any]:
        try:
            return await verify_assessment(args.assessment_id)
        finally:
            await engine.dispose()

    result = asyncio.run(run_and_dispose())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
