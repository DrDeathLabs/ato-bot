"""
Retry engine — re-runs LLM assessment for not_reviewed (failed parse) findings.
After two automated attempts still fail, marks needs_manual_review=True.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.orm import Assessment, ControlFinding, Project
from app.services.controls.catalog import load_baseline
from app.services.evidence_view import build_system_context_from_evidence, get_all_evidence_text
from app.services.rag.retriever import retrieve_chunks


async def retry_failed_findings(assessment_id: int) -> None:
    """Background task — retries all not_reviewed findings for an assessment."""
    async with AsyncSessionLocal() as db:
        # Load assessment + project
        result = await db.execute(select(Assessment).where(Assessment.id == assessment_id))
        assessment: Assessment | None = result.scalar_one_or_none()
        if not assessment:
            return

        proj_result = await db.execute(select(Project).where(Project.id == assessment.project_id))
        project: Project = proj_result.scalar_one()

        # Get all not_reviewed findings
        findings_result = await db.execute(
            select(ControlFinding).where(
                ControlFinding.assessment_id == assessment_id,
                ControlFinding.status == "not_reviewed",
            )
        )
        failed_findings = findings_result.scalars().all()
        if not failed_findings:
            return

        # Build control lookup from baseline
        controls = load_baseline(project.impact_baseline)
        control_map = {c.display_id: c for c in controls}

        # Build system context
        system_context = await _build_system_context(project.id, db)

        from app.core.config import get_settings
        from app.services.llm.runtime import build_provider_for_purpose
        settings = get_settings()
        llm, _ = await build_provider_for_purpose(
            db,
            "assessment_reasoning",
            provider_name=assessment.llm_provider,
            model=assessment.llm_model,
        )
        num_ctx = assessment.ollama_num_ctx or settings.ollama_num_ctx

        semaphore = asyncio.Semaphore(3)

        async def retry_one(finding: ControlFinding) -> None:
            async with semaphore:
                await _retry_finding(
                    finding=finding,
                    control_map=control_map,
                    project_id=project.id,
                    system_context=system_context,
                    llm=llm,
                    context_strategy=assessment.context_strategy,
                    num_ctx=num_ctx,
                    assessment_id=assessment_id,
                )

        await asyncio.gather(*[retry_one(f) for f in failed_findings])


async def _retry_finding(
    finding: ControlFinding,
    control_map: dict,
    project_id: int,
    system_context: str,
    llm,
    context_strategy: str,
    num_ctx: int,
    assessment_id: int,
) -> None:
    control = control_map.get(finding.control_id)
    if not control:
        return

    async with AsyncSessionLocal() as db:
        from app.core.config import get_settings
        settings = get_settings()
        max_chunk_tokens = max(2048, num_ctx - 3000)
        rag_query = f"{control.display_id} {control.title}: {control.statement[:300]}"

        if context_strategy == "full":
            chunks = await get_all_evidence_text(project_id, db, max_chunk_tokens)
        else:
            chunks = await retrieve_chunks(
                query=rag_query, project_id=project_id, db=db,
                top_k=10, max_tokens=max_chunk_tokens,
            )

        new_finding = await llm.assess_control(
            control_id=control.display_id,
            control_title=control.title,
            control_statement=control.statement,
            supplemental_guidance=control.supplemental_guidance,
            chunks=chunks,
            system_context=system_context,
            assessment_objectives=control.assessment_objectives or None,
        )

        # Reload finding in this session
        result = await db.execute(
            select(ControlFinding).where(ControlFinding.id == finding.id)
        )
        db_finding = result.scalar_one_or_none()
        if not db_finding:
            return

        db_finding.retry_count = (db_finding.retry_count or 0) + 1

        db_finding.tested_at = datetime.now(UTC)

        if new_finding.parse_failed:
            # Still failing — mark for manual review, keep raw response
            db_finding.needs_manual_review = True
            if new_finding.raw_response:
                db_finding.raw_llm_response = new_finding.raw_response
        else:
            # Success — update all fields
            db_finding.status = new_finding.status
            db_finding.implementation_statement = new_finding.implementation_statement
            db_finding.gaps = new_finding.gaps
            db_finding.evidence_citations = new_finding.evidence_citations
            db_finding.remediation_plan = new_finding.remediation_plan
            db_finding.confidence_score = new_finding.confidence
            db_finding.raw_llm_response = None
            db_finding.needs_manual_review = False

            # Auto-create POAM if needed
            if new_finding.status in ("non_compliant", "partially_compliant") and new_finding.gaps:
                from app.services.assessment_engine import _create_poam_entry
                await _create_poam_entry(assessment_id, control.display_id, new_finding, db)

        await db.commit()


async def _build_system_context(project_id: int, db: AsyncSession) -> str:
    return await build_system_context_from_evidence(project_id, db)
