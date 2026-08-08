from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.orm import Assessment, AssessmentPolicy, Project, SystemProfile
from app.services.assessment_pipeline import assess_control_with_assessor_pipeline, preload_evidence_index
from app.services.assessment_policy import build_policy_runtime
from app.services.closure_service import _build_project_context
from app.services.controls.catalog import load_catalog
from app.services.human_artifact_generator import generate_human_artifacts_for_assessment
from app.services.llm.runtime import build_provider_for_purpose


def _parse_args() -> tuple[int, list[str], bool, bool]:
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: python backend/human_artifact_trial.py <assessment_id> <control_ids_csv> [--proof] [--force-llm]"
        )
    assessment_id = int(sys.argv[1])
    control_ids = [item.strip() for item in sys.argv[2].split(",") if item.strip()]
    proof = "--proof" in sys.argv[3:]
    force_llm = "--force-llm" in sys.argv[3:]
    return assessment_id, control_ids, proof, force_llm


async def _load_context(db: AsyncSession, assessment_id: int) -> tuple[Assessment, str]:
    assessment = await db.get(
        Assessment,
        assessment_id,
        options=[selectinload(Assessment.policy)],
    )
    if assessment is None:
        raise RuntimeError(f"Assessment {assessment_id} was not found.")
    project = await db.get(Project, assessment.project_id)
    profile_result = await db.execute(select(SystemProfile).where(SystemProfile.project_id == assessment.project_id))
    profile_obj = profile_result.scalars().first()
    _system_name, system_context = _build_project_context(project, profile_obj)
    return assessment, system_context


async def _run_proof(
    *,
    source_assessment: Assessment,
    system_context: str,
    control_ids: list[str],
    evidence_doc_ids: list[int],
) -> dict:
    catalog = load_catalog()
    proof_assessment = Assessment(
        project_id=source_assessment.project_id,
        status="running",
        llm_provider=source_assessment.llm_provider,
        llm_model=source_assessment.llm_model,
        context_strategy=source_assessment.context_strategy,
        skip_stage3=source_assessment.skip_stage3,
        carry_forward_compliant=False,
        started_at=datetime.now(UTC),
        name=f"Human artifact trial for {', '.join(control_ids)}",
        started_by=source_assessment.started_by,
        policy_id=source_assessment.policy_id,
        policy_version=source_assessment.policy_version,
        controls_total=len(control_ids),
        controls_complete=0,
    )

    async with AsyncSessionLocal() as db:
        db.add(proof_assessment)
        await db.flush()
        policy_record = None
        if source_assessment.policy_id:
            policy_record = await db.get(
                AssessmentPolicy,
                source_assessment.policy_id,
                options=[selectinload(AssessmentPolicy.buckets)],
            )
        policy_runtime = build_policy_runtime(policy_record)
        provider, _runtime = await build_provider_for_purpose(
            db,
            "assessment_reasoning",
            provider_name=source_assessment.llm_provider,
            model=source_assessment.llm_model,
        )
        evidence_index = await preload_evidence_index(source_assessment.project_id, evidence_doc_ids, db)

        results: list[dict] = []
        for control_id in control_ids:
            control = catalog[control_id.lower()]
            finding = await assess_control_with_assessor_pipeline(
                assessment_id=proof_assessment.id,
                project_id=source_assessment.project_id,
                control=control,
                system_context=system_context,
                llm=provider,
                db=db,
                evidence_index=evidence_index,
                skip_stage3=source_assessment.skip_stage3,
                policy_runtime=policy_runtime,
            )
            proof_assessment.controls_complete += 1
            await db.flush()
            results.append(
                {
                    "control_id": control_id,
                    "status": finding.status if finding else "not_reviewed",
                    "confidence": getattr(finding, "confidence", 0.0) if finding else 0.0,
                    "gaps": getattr(finding, "gaps", []) if finding else ["No result returned."],
                }
            )

        proof_assessment.status = "complete"
        proof_assessment.completed_at = datetime.now(UTC)
        await db.commit()
        return {"proof_assessment_id": proof_assessment.id, "results": results}


async def main() -> None:
    assessment_id, control_ids, do_proof, force_llm = _parse_args()

    generated = await generate_human_artifacts_for_assessment(
        assessment_id=assessment_id,
        control_ids=control_ids,
        trigger_parse=True,
        force_llm=force_llm,
    )
    output: dict[str, object] = {
        "assessment_id": assessment_id,
        "control_ids": control_ids,
        "force_llm": force_llm,
        "generated": [
            {
                "control_id": item.get("control_id"),
                "document_id": item.get("document_id"),
                "title": item.get("title"),
                "filename": item.get("filename"),
                "document_type": item.get("document_type"),
                "generation_mode": item.get("generation_mode"),
                "lint_issues": item.get("lint_issues"),
                "parse_status": item.get("parse_status"),
                "parse_attempts": item.get("parse_attempts"),
            }
            for item in generated
        ],
    }

    if do_proof:
        async with AsyncSessionLocal() as db:
            assessment, system_context = await _load_context(db, assessment_id)
        output["proof"] = await _run_proof(
            source_assessment=assessment,
            system_context=system_context,
            control_ids=control_ids,
            evidence_doc_ids=[int(item["document_id"]) for item in generated if item.get("document_id")],
        )

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
