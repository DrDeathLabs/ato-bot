"""
Assessment Engine — orchestrates the full RMF assessment pipeline:
  parse → chunk → embed → rule-screen → LLM assess → store findings
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.orm import (
    Assessment, AssessmentActivity, AssessmentPlan, ControlFinding, ControlOverride,
    Document, IngestionRun, Project,
)
from app.services.assessment_pipeline import (
    assess_control_with_assessor_pipeline,
    preload_evidence_index,
)
from app.services.assessment_policy import build_policy_runtime, get_active_assessment_policy, get_policy_by_id
from app.services.assessment_rollup import build_assessment_rollup
from app.services.activity_log import log_carried_forward, log_llm_assessed, log_override_applied
from app.services.controls.catalog import load_baseline
from app.services.evidence_view import (
    build_system_context_from_evidence,
    get_all_evidence_text,
    has_new_evidence_for_control_since,
)
from app.services.rag.retriever import retrieve_chunks

settings = get_settings()


def _is_carry_forward_compatible(
    assessment: Assessment,
    plan: AssessmentPlan,
    previous_assessment: Assessment | None,
    previous_plan: AssessmentPlan | None,
) -> bool:
    """Permit carry-forward only when evidence, policy, model, and execution mode are unchanged."""
    if not previous_assessment or not previous_plan:
        return False
    current_fingerprint = (plan.scope_json or {}).get("fingerprint")
    previous_fingerprint = (previous_plan.scope_json or {}).get("fingerprint")
    return bool(
        current_fingerprint
        and previous_fingerprint == current_fingerprint
        and previous_assessment.policy_id == assessment.policy_id
        and previous_assessment.policy_version == assessment.policy_version
        and previous_assessment.llm_provider == assessment.llm_provider
        and previous_assessment.llm_model == assessment.llm_model
        and previous_assessment.context_strategy == assessment.context_strategy
        and previous_assessment.skip_stage3 == assessment.skip_stage3
    )


def _resolve_assessment_concurrency(assessment: Assessment) -> int:
    configured = max(1, int(settings.assessment_concurrency))
    provider = str(getattr(assessment, "llm_provider", "") or "").strip().lower()
    model = str(getattr(assessment, "llm_model", "") or "").strip().lower()

    if provider == "ollama":
        if "120b" in model or "405b" in model:
            return min(configured, 3)
        if "70b" in model or "72b" in model or "cloud" in model:
            return min(configured, 4)
        return min(configured, 6)

    if provider in {"claude", "bedrock"}:
        return min(configured, 6)

    return configured


async def run_assessment(assessment_id: int) -> None:
    """Main entry point — runs as a background asyncio task."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Assessment).where(Assessment.id == assessment_id))
        assessment: Assessment | None = result.scalar_one_or_none()
        if not assessment:
            return

        plan = await db.scalar(
            select(AssessmentPlan).where(
                AssessmentPlan.assessment_id == assessment_id,
                AssessmentPlan.status == "approved",
            )
        )
        if not plan:
            assessment.status = "failed"
            assessment.error_message = "Execution blocked: an approved assessment plan is required."
            await db.commit()
            return

        assessment.status = "running"
        assessment.error_message = None
        if not assessment.started_at:
            assessment.started_at = datetime.now(UTC)
        await db.commit()

        try:
            await _run(assessment, db)
        except Exception as e:
            # Roll back any failed transaction before attempting status update
            try:
                await db.rollback()
            except Exception:
                pass
            # Use a fresh session to write the failure — the original may be broken
            try:
                async with AsyncSessionLocal() as err_db:
                    err_result = await err_db.execute(
                        select(Assessment).where(Assessment.id == assessment_id)
                    )
                    err_assessment = err_result.scalar_one_or_none()
                    if err_assessment and err_assessment.status not in ("paused",):
                        err_assessment.status = "failed"
                        err_assessment.error_message = str(e)
                        await err_db.commit()
            except Exception:
                pass


async def _run(assessment: Assessment, db: AsyncSession) -> None:
    # Load project & baseline controls
    proj_result = await db.execute(select(Project).where(Project.id == assessment.project_id))
    project: Project = proj_result.scalar_one()

    controls = load_baseline(project.impact_baseline)
    assessment.controls_total = len(controls)
    await db.commit()

    plan = await db.scalar(select(AssessmentPlan).where(AssessmentPlan.assessment_id == assessment.id))
    if not plan or plan.status != "approved":
        raise RuntimeError("Execution blocked: the approved assessment plan is missing.")

    frozen_documents = list((plan.scope_json or {}).get("documents") or [])
    if not frozen_documents:
        raise RuntimeError("Execution blocked: the approved plan has no frozen evidence scope.")
    scope_doc_ids = [int(item["document_id"]) for item in frozen_documents]
    scope_run_ids = [int(item["ingestion_run_id"]) for item in frozen_documents]
    current_docs = {
        row.id: row.file_hash
        for row in (
            await db.execute(select(Document).where(Document.id.in_(scope_doc_ids)))
        ).scalars().all()
    }
    current_runs = {
        row.id: row
        for row in (
            await db.execute(select(IngestionRun).where(IngestionRun.id.in_(scope_run_ids)))
        ).scalars().all()
    }
    invalid_scope: list[int] = []
    for item in frozen_documents:
        document_id = int(item["document_id"])
        run_id = int(item["ingestion_run_id"])
        run = current_runs.get(run_id)
        if (
            current_docs.get(document_id) != item.get("file_hash")
            or run is None
            or run.document_id != document_id
            or run.status != "complete"
            or run.quality_status != "passed"
            or not run.readiness_eligible
        ):
            invalid_scope.append(document_id)
    if invalid_scope:
        raise RuntimeError(
            "Execution blocked: approved evidence changed or is no longer assessment-ready "
            f"for document IDs {sorted(set(invalid_scope))}. Approve a new assessment plan."
        )
    project_doc_ids_result = await db.execute(
        select(Document.id).where(
            Document.project_id == project.id,
            Document.parse_status.in_(("complete", "indexed")),
        )
    )
    project_doc_ids = list(project_doc_ids_result.scalars().all())
    extra_doc_ids = [doc_id for doc_id in scope_doc_ids if doc_id not in set(project_doc_ids)]
    has_indexed_docs = bool(scope_doc_ids)

    # Build system context summary from the assessment scope, not just project uploads.
    system_context = await build_system_context_from_evidence(
        project.id, db, scope_doc_ids, scope_run_ids=scope_run_ids
    )

    # Get LLM provider through the shared runtime resolver so assessment and
    # helper flows read from the same model-routing layer.
    from app.services.ingestion.config_store import get_value as _get_pipeline_val
    from app.services.llm.runtime import build_provider_for_purpose

    _reasoning_effort = await _get_pipeline_val(db, "ollama_reasoning_effort") or settings.ollama_reasoning_effort
    llm, _ = await build_provider_for_purpose(
        db,
        "assessment_reasoning",
        provider_name=assessment.llm_provider,
        model=assessment.llm_model,
        reasoning_effort=_reasoning_effort,
    )

    evidence_index = await preload_evidence_index(
        project.id, scope_doc_ids, db, scope_run_ids=scope_run_ids
    )
    policy_record = None
    if assessment.policy_id:
        policy_record = await get_policy_by_id(db, assessment.policy_id)
    if policy_record is None:
        policy_record = await get_active_assessment_policy(db)
    policy_runtime = build_policy_runtime(policy_record)

    # Load per-control overrides for this project
    overrides_result = await db.execute(
        select(ControlOverride).where(ControlOverride.project_id == project.id)
    )
    override_map: dict[str, ControlOverride] = {o.control_id: o for o in overrides_result.scalars().all()}

    # Load previous assessment's findings for change detection + carry-forward.
    # Store as plain dicts immediately — ORM objects become expired after commits
    # in the same session, causing silent attribute failures in async context.
    prev_findings: dict[str, str] = {}
    prev_findings_full: dict[str, dict] = {}  # plain dicts, not ORM objects
    prev_assess_result = await db.execute(
        select(Assessment)
        .where(Assessment.project_id == project.id, Assessment.status == "complete", Assessment.id != assessment.id)
        .order_by(Assessment.completed_at.desc())
        .limit(1)
    )
    prev_assessment = prev_assess_result.scalar_one_or_none()
    if prev_assessment:
        pf_result = await db.execute(
            select(ControlFinding)
            .where(ControlFinding.assessment_id == prev_assessment.id)
        )
        for row in pf_result.scalars().all():
            prev_findings[row.control_id] = row.status
            # Extract all fields needed for carry-forward into a plain dict
            prev_findings_full[row.control_id] = {
                "status": row.status,
                "implementation_statement": row.implementation_statement,
                "gaps": row.gaps,
                "evidence_citations": row.evidence_citations,
                "remediation_plan": row.remediation_plan,
                "confidence_score": row.confidence_score,
                "notes": row.notes,
            }

    concurrency = _resolve_assessment_concurrency(assessment)
    semaphore = asyncio.Semaphore(concurrency)
    ollama_num_ctx = assessment.ollama_num_ctx or settings.ollama_num_ctx

    # Load system profile N/A map — controls to skip entirely
    from app.services.system_profile import get_na_map
    na_map = await get_na_map(project.id, db, controls)

    # Skip controls that already have findings (resume support)
    existing_result = await db.execute(
        select(ControlFinding.control_id).where(ControlFinding.assessment_id == assessment.id)
    )
    completed_ids = {row[0] for row in existing_result.fetchall()}

    # ── Carry-forward compliant findings ────────────────────────────────────
    # When explicitly enabled, reuse compliant findings only when the frozen
    # evidence scope and assessment execution configuration are unchanged.
    from datetime import UTC
    carry_forward_compliant = getattr(assessment, 'carry_forward_compliant', False)
    carry_forward_ids: set[str] = set()

    prev_plan = None
    if prev_assessment:
        prev_plan = await db.scalar(
            select(AssessmentPlan).where(AssessmentPlan.assessment_id == prev_assessment.id)
        )
    carry_forward_compatible = _is_carry_forward_compatible(
        assessment, plan, prev_assessment, prev_plan
    )

    if carry_forward_compliant and prev_assessment and carry_forward_compatible:
        cf_findings_to_insert: list[ControlFinding] = []
        for ctrl in controls:
            cid = ctrl.display_id
            if cid in completed_ids or cid in na_map:
                continue
            prev = prev_findings_full.get(cid)  # plain dict
            if prev and prev["status"] == "compliant":
                # Don't carry forward if there's a manual override forcing a re-run
                ov = override_map.get(cid)
                if ov and (ov.satisfied or ov.applicability in ("not_applicable", "inherited")):
                    continue

                # Obs 9 Option A — Staleness check: if any document tagged to this
                # control was uploaded after the previous assessment completed,
                # the old finding is potentially stale — re-test instead of copying.
                if prev_assessment.completed_at:
                    has_new = await has_new_evidence_for_control_since(
                        project.id,
                        cid,
                        prev_assessment.completed_at,
                        db,
                    )
                    if has_new:
                        # New evidence exists — fall through to full re-assessment
                        continue

                cf_finding = ControlFinding(
                    assessment_id=assessment.id,
                    control_id=cid,
                    control_family=ctrl.family_id.upper(),
                    control_title=ctrl.title,
                    status="compliant",
                    implementation_statement=prev["implementation_statement"],
                    gaps=prev["gaps"],
                    evidence_citations=prev["evidence_citations"],
                    remediation_plan=prev["remediation_plan"],
                    confidence_score=prev["confidence_score"],
                    notes=prev["notes"],
                    carried_forward=True,
                    applicability_changed=False,
                    prev_status="compliant",
                    override_applied="carry_forward_compliant",
                    tested_at=datetime.now(UTC),
                    # Obs 9 Option C — audit trail: record which assessment this was sourced from
                )
                cf_findings_to_insert.append(cf_finding)
                carry_forward_ids.add(cid)

        if cf_findings_to_insert:
            import sqlalchemy as sa_mod
            async with AsyncSessionLocal() as cf_db:
                for f in cf_findings_to_insert:
                    cf_db.add(f)
                await cf_db.execute(
                    sa_mod.update(Assessment)
                    .where(Assessment.id == assessment.id)
                    .values(controls_complete=Assessment.controls_complete + len(cf_findings_to_insert))
                )
                await cf_db.commit()
            completed_ids.update(carry_forward_ids)

            # Log each carry-forward
            async with AsyncSessionLocal() as log_db:
                for ctrl in controls:
                    if ctrl.display_id in carry_forward_ids:
                        await log_carried_forward(
                            log_db,
                            project_id=project.id,
                            assessment_id=assessment.id,
                            control_id=ctrl.display_id,
                            control_family=ctrl.family_id.upper(),
                            control_title=ctrl.title,
                            status="compliant",
                        )
                await log_db.commit()

    # Build the list of controls still needing LLM assessment
    controls_to_run = [c for c in controls if c.display_id not in completed_ids and c.display_id not in na_map]

    # Create instant N/A findings for system-profile-excluded controls
    for ctrl in controls:
        if ctrl.display_id in na_map and ctrl.display_id not in completed_ids:
            async with AsyncSessionLocal() as na_db:
                rationale = na_map[ctrl.display_id]
                na_finding = ControlFinding(
                    assessment_id=assessment.id,
                    control_id=ctrl.display_id,
                    control_family=ctrl.family_id.upper(),
                    control_title=ctrl.title,
                    status="not_applicable",
                    implementation_statement=f"[System Profile] {rationale}",
                    gaps=[],
                    evidence_citations=[],
                    carried_forward=False,
                    applicability_changed=prev_findings.get(ctrl.display_id) not in (None, "not_applicable"),
                    prev_status=prev_findings.get(ctrl.display_id),
                    override_applied="system_profile",
                    tested_at=datetime.now(UTC),
                )
                na_db.add(na_finding)
                await na_db.execute(
                    __import__("sqlalchemy").update(Assessment)
                    .where(Assessment.id == assessment.id)
                    .values(controls_complete=Assessment.controls_complete + 1)
                )
                await na_db.commit()

    # Sync progress counter with already-done controls (resume support)
    if completed_ids:
        async with AsyncSessionLocal() as sync_db:
            count_result = await sync_db.execute(
                select(__import__("sqlalchemy").func.count(ControlFinding.id))
                .where(ControlFinding.assessment_id == assessment.id)
            )
            actual_done = count_result.scalar() or 0
            await sync_db.execute(
                __import__("sqlalchemy").update(Assessment)
                .where(Assessment.id == assessment.id)
                .values(controls_complete=actual_done)
            )
            await sync_db.commit()
        await db.refresh(assessment)

    # Pre-compute RAG chunks in parallel batches (bounded by embedding semaphore).
    # Embedding is fast relative to LLM calls, so modest parallelism here is safe.
    chunks_map: dict[str, list[str]] = {}
    max_chunk_tokens = max(2048, ollama_num_ctx - 3000)
    if assessment.context_strategy == "rag":
        embed_sem = asyncio.Semaphore(min(concurrency, 8))

        async def fetch_chunks(ctrl):
            if evidence_index.get(ctrl.display_id):
                return
            async with embed_sem:
                try:
                    rag_query = f"{ctrl.display_id} {ctrl.title}: {ctrl.statement[:300]}"
                    # Use a dedicated session per call — shared sessions must not be
                    # used concurrently across coroutines (asyncpg transaction corruption).
                    async with AsyncSessionLocal() as rag_db:
                        chunks_map[ctrl.display_id] = await retrieve_chunks(
                            query=rag_query, project_id=project.id, db=rag_db,
                            top_k=10, max_tokens=max_chunk_tokens,
                            extra_doc_ids=extra_doc_ids or None,
                            allowed_doc_ids=scope_doc_ids,
                            allowed_run_ids=scope_run_ids,
                        )
                except Exception:
                    chunks_map[ctrl.display_id] = []

        await asyncio.gather(*[fetch_chunks(ctrl) for ctrl in controls_to_run])

    skip_stage3 = getattr(assessment, 'skip_stage3', False)

    async def assess_one(control) -> None:
        async with semaphore:
            await _set_progress(assessment.id, f"▶ Processing: {control.display_id} {control.title[:60]}…")
            await _assess_control(
                assessment=assessment,
                control=control,
                project_id=project.id,
                system_context=system_context,
                llm=llm,
                context_strategy=assessment.context_strategy,
                ollama_num_ctx=ollama_num_ctx,
                override=override_map.get(control.display_id),
                prev_status=prev_findings.get(control.display_id),
                pre_chunks=chunks_map.get(control.display_id),
                provider_doc_ids=extra_doc_ids or None,
                has_indexed_docs=has_indexed_docs,
                skip_stage3=skip_stage3,
                evidence_index=evidence_index,
                policy_runtime=policy_runtime,
                scope_doc_ids=scope_doc_ids,
                scope_run_ids=scope_run_ids,
                evidence_scope_fingerprint=(plan.scope_json or {}).get("fingerprint"),
            )

    # Process in batches so we can check for pause between each batch
    batch_size = concurrency * 2
    for i in range(0, len(controls_to_run), batch_size):
        # Check if paused or cancelled before each batch
        await db.refresh(assessment)
        if assessment.status == "paused":
            return

        batch = controls_to_run[i:i + batch_size]
        tasks = [assess_one(ctrl) for ctrl in batch]
        await asyncio.gather(*tasks)

    # Final status — only mark complete if not paused
    await db.refresh(assessment)
    if assessment.status not in ("paused", "failed"):
        await build_assessment_rollup(assessment.id, db)
        await _record_automated_examine_activities(assessment.id, db)
        assessment.status = "complete"
        assessment.error_message = None
        assessment.completed_at = datetime.now(UTC)
        assessment.progress_detail = None
        await db.commit()


async def _record_automated_examine_activities(assessment_id: int, db: AsyncSession) -> None:
    """Record document examination performed by the engine without claiming interviews or tests."""
    assessment = await db.scalar(select(Assessment).where(Assessment.id == assessment_id))
    findings = (
        await db.execute(select(ControlFinding).where(ControlFinding.assessment_id == assessment_id))
    ).scalars().all()
    finding_map = {finding.control_id: finding for finding in findings}
    activities = (
        await db.execute(
            select(AssessmentActivity).where(
                AssessmentActivity.assessment_id == assessment_id,
                AssessmentActivity.method == "EXAMINE",
                AssessmentActivity.status == "planned",
            )
        )
    ).scalars().all()
    now = datetime.now(UTC)
    for activity in activities:
        finding = finding_map.get(activity.control_id)
        if not finding:
            continue
        activity.status = "performed"
        activity.result = (
            f"ATO Bot examined the indexed evidence scope and produced a {finding.status} draft finding. "
            "A qualified assessor must review the finding before finalization."
        )
        activity.evidence_refs = finding.evidence_citations or []
        activity.performed_by = assessment.started_by if assessment else None
        activity.performed_at = finding.tested_at or now


async def _set_progress(assessment_id: int, detail: str) -> None:
    """Atomically update progress_detail for live status display."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            __import__("sqlalchemy").update(Assessment)
            .where(Assessment.id == assessment_id)
            .values(progress_detail=detail)
        )
        await db.commit()


async def _assess_control(
    assessment: Assessment,
    control,
    project_id: int,
    system_context: str,
    llm,
    context_strategy: str,
    ollama_num_ctx: int,
    override=None,
    prev_status: str | None = None,
    pre_chunks: list[str] | None = None,
    provider_doc_ids: list[int] | None = None,
    has_indexed_docs: bool = False,
    skip_stage3: bool = False,
    evidence_index: dict[str, list[dict]] | None = None,
    policy_runtime: dict | None = None,
    scope_doc_ids: list[int] | None = None,
    scope_run_ids: list[int] | None = None,
    evidence_scope_fingerprint: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        override_applied = None
        carried_forward = False

        # ── Override: Satisfied ──────────────────────────────────────────────
        if (
            override
            and override.satisfied
            and override.satisfied_finding_snapshot
            and override.satisfied_finding_snapshot.get("evidence_scope_fingerprint")
            == evidence_scope_fingerprint
        ):
            snap = override.satisfied_finding_snapshot
            is_na = snap.get("status") == "not_applicable"
            prev_is_na = prev_status == "not_applicable" if prev_status else is_na
            applicability_changed = is_na != prev_is_na

            db_finding = ControlFinding(
                assessment_id=assessment.id,
                control_id=control.display_id,
                control_family=control.family_id.upper(),
                control_title=control.title,
                status=snap.get("status", "not_reviewed"),
                implementation_statement=snap.get("implementation_statement"),
                gaps=snap.get("gaps", []),
                evidence_citations=snap.get("evidence_citations", []),
                remediation_plan=snap.get("remediation_plan"),
                confidence_score=snap.get("confidence_score"),
                notes=snap.get("notes"),
                carried_forward=True,
                applicability_changed=applicability_changed,
                prev_status=prev_status,
                override_applied="satisfied",
                tested_at=datetime.now(UTC),
            )
            db.add(db_finding)
            await log_carried_forward(
                db, project_id=project_id, assessment_id=assessment.id,
                control_id=control.display_id, control_family=control.family_id.upper(),
                control_title=control.title, status=snap.get("status", "not_reviewed"),
            )
            await db.execute(
                __import__("sqlalchemy").update(Assessment)
                .where(Assessment.id == assessment.id)
                .values(
                    controls_complete=Assessment.controls_complete + 1,
                    progress_detail=f"Carried forward: {control.display_id} (satisfied)",
                )
            )
            await db.commit()
            return

        # ── Override: Force Not Applicable ───────────────────────────────────
        if override and override.applicability == "not_applicable":
            applicability_changed = prev_status not in (None, "not_applicable")
            stmt = "This control has been marked Not Applicable by the assessor."
            if override.applicability_rationale:
                stmt += f" Rationale: {override.applicability_rationale}"

            db_finding = ControlFinding(
                assessment_id=assessment.id,
                control_id=control.display_id,
                control_family=control.family_id.upper(),
                control_title=control.title,
                status="not_applicable",
                implementation_statement=stmt,
                gaps=[],
                evidence_citations=[],
                carried_forward=False,
                applicability_changed=applicability_changed,
                prev_status=prev_status,
                override_applied="not_applicable",
                tested_at=datetime.now(UTC),
            )
            db.add(db_finding)
            await log_override_applied(
                db, project_id=project_id, assessment_id=assessment.id,
                control_id=control.display_id, control_family=control.family_id.upper(),
                control_title=control.title, override_type="not_applicable",
                rationale=override.applicability_rationale,
            )
            await db.execute(
                __import__("sqlalchemy").update(Assessment)
                .where(Assessment.id == assessment.id)
                .values(controls_complete=Assessment.controls_complete + 1)
            )
            await db.commit()
            return

        # ── Override: Inherited ───────────────────────────────────────────────
        if override and override.applicability == "inherited":
            applicability_changed = prev_status not in (None, "not_applicable")
            stmt = f"Control inherited from underlying provider/platform. {override.applicability_rationale or ''}"
            db_finding = ControlFinding(
                assessment_id=assessment.id,
                control_id=control.display_id,
                control_family=control.family_id.upper(),
                control_title=control.title,
                status="not_applicable",
                implementation_statement=stmt,
                gaps=[],
                evidence_citations=[],
                carried_forward=False,
                applicability_changed=applicability_changed,
                prev_status=prev_status,
                override_applied="inherited",
                tested_at=datetime.now(UTC),
            )
            db.add(db_finding)
            await log_override_applied(
                db, project_id=project_id, assessment_id=assessment.id,
                control_id=control.display_id, control_family=control.family_id.upper(),
                control_title=control.title, override_type="inherited",
                rationale=override.applicability_rationale,
            )
            await db.execute(
                __import__("sqlalchemy").update(Assessment)
                .where(Assessment.id == assessment.id)
                .values(controls_complete=Assessment.controls_complete + 1)
            )
            await db.commit()
            return

        # ── Normal LLM assessment path ────────────────────────────────────────
        max_chunk_tokens = max(2048, ollama_num_ctx - 3000)

        finding = None
        if evidence_index is not None:
            finding = await assess_control_with_assessor_pipeline(
                assessment_id=assessment.id,
                project_id=project_id,
                control=control,
                system_context=system_context,
                llm=llm,
                db=db,
                evidence_index=evidence_index,
                skip_stage3=skip_stage3,
                policy_runtime=policy_runtime,
            )

        if finding is None and pre_chunks is not None:
            # Chunks pre-computed upfront to avoid concurrent embedding queue pileup
            chunks = pre_chunks
        elif finding is None:
            rag_query = f"{control.display_id} {control.title}: {control.statement[:300]}"
            if context_strategy == "full":
                chunks = await get_all_evidence_text(
                    project_id, db, max_chunk_tokens, scope_doc_ids, scope_run_ids
                )
            elif context_strategy == "rag":
                chunks = await retrieve_chunks(
                    query=rag_query, project_id=project_id, db=db,
                    top_k=10, max_tokens=max_chunk_tokens,
                    extra_doc_ids=provider_doc_ids,
                    allowed_doc_ids=scope_doc_ids,
                    allowed_run_ids=scope_run_ids,
                )
            else:  # hybrid
                rag_chunks = await retrieve_chunks(
                    query=rag_query, project_id=project_id, db=db,
                    top_k=6, max_tokens=max_chunk_tokens // 2,
                    extra_doc_ids=provider_doc_ids,
                    allowed_doc_ids=scope_doc_ids,
                    allowed_run_ids=scope_run_ids,
                )
                all_chunks = await get_all_evidence_text(
                    project_id, db, max_chunk_tokens // 2, scope_doc_ids, scope_run_ids
                )
                seen = set()
                chunks = []
                for c in rag_chunks + all_chunks:
                    if c not in seen:
                        seen.add(c)
                        chunks.append(c)

        # LLM assessment — staged legacy chunk path if evidence-unit pipeline had no result
        if finding is None and has_indexed_docs:
            # Obs 6 Option B: gate relaxed — multistage now handles no-objectives controls
            # internally by deriving synthetic objectives from the control statement.
            from app.services.multistage_engine import (
                assess_control_multistage,
                _derive_objectives_from_statement,
            )
            from app.services.rag.retriever import retrieve_chunks_multi_query as _retrieve_multi

            async def _rag_fallback():
                """Obs 7: objective-grouped multi-query RAG fallback.

                Groups assessment objectives into buckets of 8 and issues one semantic
                query per bucket so the retrieved evidence pool covers all objective areas
                rather than clustering around the control's general topic.
                """
                import re as _re

                # Use formal OSCAL objectives when available; fall back to synthetic ones
                objectives = control.assessment_objectives or []
                if not objectives and control.statement:
                    objectives = _derive_objectives_from_statement(
                        control.display_id, control.statement
                    )

                if objectives:
                    # Group into buckets of 8 → one targeted query per group
                    bucket_size = 8
                    queries: list[str] = []
                    for i in range(0, min(len(objectives), 40), bucket_size):
                        bucket = objectives[i:i + bucket_size]
                        # Strip leading objective IDs ("AC-01a.[01] ") — keep requirement text
                        obj_texts = " ".join(
                            _re.sub(r'^[A-Z]{2,3}-\d+[\w.()\[\]]*\s*', '', o).strip()
                            for o in bucket
                        )
                        queries.append(
                            f"{control.display_id} {control.title}: {obj_texts[:300]}"
                        )
                else:
                    # No objectives available — single broad query (last resort)
                    queries = [
                        f"{control.display_id} {control.title}: {control.statement[:300]}"
                    ]

                return await _retrieve_multi(
                    queries=queries,
                    project_id=project_id,
                    db=db,
                    top_k_per_query=4,
                    max_tokens=max_chunk_tokens,
                    extra_doc_ids=provider_doc_ids,
                    allowed_doc_ids=scope_doc_ids,
                    allowed_run_ids=scope_run_ids,
                )

            finding = await assess_control_multistage(
                control=control,
                project_id=project_id,
                system_context=system_context,
                llm=llm,
                db=db,
                max_chunk_tokens=max_chunk_tokens,
                rag_fallback_fn=_rag_fallback,
                skip_stage3=skip_stage3,
            )

        if finding is None:
            # Single-stage fallback (no indexed docs, or multistage stage-2 failed)
            # Obs 6 Option A: chunks are passed as enriched dicts when available so
            # the single-stage path gets document type/intent weighting via build_control_prompt().
            finding = await llm.assess_control(
                control_id=control.display_id,
                control_title=control.title,
                control_statement=control.statement,
                supplemental_guidance=control.supplemental_guidance,
                chunks=chunks,
                system_context=system_context,
                assessment_objectives=control.assessment_objectives or None,
            )

            # Obs 6 Option A post-processing: single-stage LLM sometimes marks a finding
            # compliant while also returning non-empty gaps — a contradiction that multistage
            # prevents via SHA anchoring but single-stage cannot.  Catch it here.
            if finding.status == "compliant" and finding.gaps:
                finding.status = "partially_compliant"
                finding.confidence = min(finding.confidence, 0.70)

        # If assessor marked as "applicable" but LLM says not_applicable — override
        if override and override.applicability == "applicable" and finding.status == "not_applicable":
            finding.status = "partially_compliant"  # override: assessor says it applies
            finding.implementation_statement = (
                f"[Assessor override: marked applicable] {finding.implementation_statement}"
            )
            override_applied = "applicable"

        # Manual status override — assessor-set status is protected; LLM cannot change it
        if override and override.manual_status:
            finding.status = override.manual_status
            finding.implementation_statement = (
                f"[Manual override by {override.manual_status_set_by or 'assessor'}] "
                + (override.manual_status_rationale or "")
                + "\n\n[LLM Assessment]\n" + finding.implementation_statement
            )
            override_applied = f"manual_status:{override.manual_status}"

        # Detect applicability change vs previous run
        curr_is_na = finding.status == "not_applicable"
        prev_is_na = prev_status == "not_applicable" if prev_status else curr_is_na
        applicability_changed = curr_is_na != prev_is_na
        adjudication_summary = getattr(finding, "adjudication_summary", {}) or {}
        manual_review_reasons = adjudication_summary.get("manual_review_reasons") or []
        notes = None
        if adjudication_summary:
            notes = (
                f"Policy-weighted adjudication v{adjudication_summary.get('policy_version') or '?'}: "
                f"support={adjudication_summary.get('weighted_support_score', 0):.2f}, "
                f"evidence={adjudication_summary.get('evidence_quality_index', 0):.2f}, "
                f"contradiction={adjudication_summary.get('contradiction_index', 0):.2f}"
            )
            if manual_review_reasons:
                notes += f". Manual review reasons: {', '.join(manual_review_reasons)}"

        # Store finding
        db_finding = ControlFinding(
            assessment_id=assessment.id,
            control_id=control.display_id,
            control_family=control.family_id.upper(),
            control_title=control.title,
            status=finding.status,
            implementation_statement=finding.implementation_statement,
            gaps=finding.gaps,
            evidence_citations=finding.evidence_citations,
            remediation_plan=finding.remediation_plan,
            confidence_score=finding.confidence,
            rule_signal="policy_weighted" if adjudication_summary else None,
            raw_llm_response=finding.raw_response if finding.parse_failed else None,
            needs_manual_review=getattr(finding, "needs_manual_review", False),
            carried_forward=False,
            applicability_changed=applicability_changed,
            prev_status=prev_status,
            override_applied=override_applied,
            notes=notes,
            llm_challenge_note=finding.llm_challenge_note or None,
            synthesized_narrative=finding.synthesized,  # Issue 5: flag skip_stage3 / LLM fallback
            tested_at=datetime.now(UTC),
        )
        db.add(db_finding)

        # Audit log — one entry per LLM assessment
        await log_llm_assessed(
            db,
            project_id=project_id,
            assessment_id=assessment.id,
            control_id=control.display_id,
            control_family=control.family_id.upper(),
            control_title=control.title,
            status=finding.status,
            confidence=finding.confidence if not finding.parse_failed else 0.0,
            override_applied=override_applied,
        )

        # Auto-create POAM entry for non/partial controls — ignore if already exists
        if finding.status in ("non_compliant", "partially_compliant") and finding.gaps:
            await _create_poam_entry(assessment.id, control.display_id, finding, db)

        # Status label for display
        status_label = {
            "compliant": "COMPLIANT",
            "partially_compliant": "PARTIAL",
            "non_compliant": "NON-COMPLIANT",
            "not_applicable": "N/A",
        }.get(finding.status, finding.status.upper())

        # Increment progress counter and update live status atomically
        await db.execute(
            __import__("sqlalchemy").update(Assessment)
            .where(Assessment.id == assessment.id)
            .values(
                controls_complete=Assessment.controls_complete + 1,
                progress_detail=f"Last completed: {control.display_id} {control.title[:60]} — {status_label}",
            )
        )
        await db.commit()

async def _create_poam_entry(assessment_id: int, control_id: str, finding, db: AsyncSession) -> None:

    risk = "high" if finding.status == "non_compliant" else "medium"
    poam_id = f"POAM-{assessment_id}-{control_id.replace('-', '').replace('(', '').replace(')', '')}"

    # Use INSERT ... ON CONFLICT DO NOTHING to avoid duplicate key errors on retries
    await db.execute(
        text("""
            INSERT INTO poam_entries (poam_id, control_id, finding, risk_level, weakness, remediation_plan, status, assessment_id)
            VALUES (:poam_id, :control_id, :finding, :risk_level, :weakness, :remediation_plan, 'open', :assessment_id)
            ON CONFLICT (poam_id) DO NOTHING
        """),
        {
            "poam_id": poam_id,
            "control_id": control_id,
            "finding": f"Control {control_id} assessed as {finding.status}",
            "risk_level": risk,
            "weakness": "; ".join(finding.gaps[:3]) if finding.gaps else None,
            "remediation_plan": finding.remediation_plan or None,
            "assessment_id": assessment_id,
        }
    )
