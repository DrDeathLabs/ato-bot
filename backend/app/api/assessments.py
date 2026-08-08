"""Assessments API — start, status, SSE progress, findings, review."""
import asyncio
import json
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.rbac import (
    require_assessor,
    require_project_access,
    require_project_assessment_access,
    require_reviewer,
    require_viewer,
)
from app.models.orm import (
    Assessment,
    AssessmentChallenge,
    AssessmentCriteriaPackage,
    AssessmentEvidenceTriage,
    AssessmentActivity,
    AssessmentPlan,
    AssessmentRollup,
    AssessmentRetryJob,
    ControlDetermination,
    ControlFinding,
    Document,
    EvidenceUnit,
    ObjectiveDetermination,
    ObjectiveEvidenceReview,
    Project,
    ProjectCommonProvider,
)
from app.models.schemas import (
    AssessmentResponse,
    AssessmentStartRequest,
    AssessmentUpdateRequest,
    ControlFindingResponse,
    FindingManualResolveRequest,
    FindingNotesRequest,
    FindingReviewRequest,
)
from app.services.activity_log import log_action
from app.services.assessment_pipeline import get_scope_evidence_readiness
from app.services.assessment_policy import get_active_assessment_policy
from app.services.controls.catalog import load_baseline

router = APIRouter(
    prefix="/projects/{project_id}/assessments",
    tags=["assessments"],
    dependencies=[Depends(require_project_access)],
)
settings = get_settings()


async def _require_mutable_assessment(assessment_id: int, db: AsyncSession) -> Assessment:
    assessment = await db.scalar(select(Assessment).where(Assessment.id == assessment_id))
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.finalization_status == "finalized":
        raise HTTPException(
            status_code=409,
            detail="The finalized assessment record is immutable. Start a new assessment to record changes.",
        )
    return assessment


async def _effective_controls_complete(db: AsyncSession, assessment: Assessment) -> int:
    base = int(assessment.controls_complete or 0)
    total = int(assessment.controls_total or 0)
    if assessment.status not in {"pending", "running"}:
        return min(base, total) if total else base

    findings_count = await db.scalar(
        select(func.count()).select_from(ControlFinding).where(ControlFinding.assessment_id == assessment.id)
    ) or 0
    determination_count = await db.scalar(
        select(func.count()).select_from(ControlDetermination).where(ControlDetermination.assessment_id == assessment.id)
    ) or 0
    effective = max(base, int(findings_count), int(determination_count))
    if total:
        effective = min(effective, total)
    return effective


def _manual_review_reasons_from_notes(notes: str | None) -> list[str]:
    if not notes:
        return []
    match = re.search(r"Manual review reasons:\s*(.+)$", notes)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def _display_review_reasons(reasons: list[str]) -> list[str]:
    return [reason for reason in reasons if reason != "inherited_support_requires_review"]


def _normalize_rollup_summary_text(text: str | None) -> str | None:
    if not text:
        return text
    return (
        text.replace(
            "were challenged by the assessor-review pass and warrant human review.",
            "have AI dissents where the review model disagreed with the automated verdict and warrant human review.",
        ).replace(
            "have AI dissents from the assessor-review pass and warrant human review.",
            "have AI dissents where the review model disagreed with the automated verdict and warrant human review.",
        )
    )


def _normalize_review_attention_summary(text: str | None, count: int) -> str | None:
    if not text:
        return text
    pattern = r"\s*\d+\scontrol\(s\)\sneed assessor attention due to [^.]+\."
    if count > 0:
        replacement = (
            f" {count} control(s) need assessor attention due to weak, contradictory, or compensating evidence patterns."
        )
        if re.search(pattern, text):
            return re.sub(pattern, replacement, text, count=1).strip()
        return f"{text.strip()}{replacement}"
    return re.sub(pattern, "", text, count=1).strip()


@router.post("", response_model=AssessmentResponse, status_code=status.HTTP_201_CREATED)
async def start_assessment(
    project_id: int,
    body: AssessmentStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_assessor),
) -> AssessmentResponse:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Determine model name
    model = body.llm_model
    if not model:
        if body.llm_provider == "ollama":
            model = settings.ollama_model
        elif body.llm_provider == "claude":
            model = settings.claude_model
        else:
            model = settings.bedrock_model_id

    # Calculate project-scoped run number
    run_count_result = await db.execute(
        select(func.count()).select_from(Assessment).where(Assessment.project_id == project_id)
    )
    run_number = (run_count_result.scalar() or 0) + 1
    active_policy = await get_active_assessment_policy(db)
    evidence_readiness = await get_scope_evidence_readiness(project_id, db)
    if not evidence_readiness["ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Assessment evidence is not ready. Reprocess degraded documents before execution.",
                **evidence_readiness,
            },
        )
    controls = load_baseline(project.impact_baseline)
    required_methods = {
        item["method"]
        for control in controls
        for item in control.assessment_methods
    }
    missing_methods = sorted(required_methods - set(body.planned_methods))
    if missing_methods:
        raise HTTPException(
            status_code=422,
            detail=f"The selected baseline requires assessment methods: {', '.join(missing_methods)}",
        )

    assessment = Assessment(
        project_id=project_id,
        project_run_number=run_number,
        status="pending",
        llm_provider=body.llm_provider,
        llm_model=model,
        context_strategy=body.context_strategy,
        ollama_num_ctx=body.ollama_num_ctx or settings.ollama_num_ctx,
        skip_stage3=getattr(body, 'skip_stage3', False),
        carry_forward_compliant=getattr(body, 'carry_forward_compliant', False),
        started_by=current_user["id"],
        policy_id=active_policy.id if active_policy else None,
        policy_version=active_policy.version if active_policy else None,
    )
    db.add(assessment)
    await db.flush()

    plan = AssessmentPlan(
        assessment_id=assessment.id,
        title=body.plan_title,
        status="approved",
        scope_json={
            "statement": body.scope_statement,
            "project_id": project_id,
            "impact_baseline": project.impact_baseline,
            "document_ids": evidence_readiness["eligible_document_ids"],
            "document_count": evidence_readiness["eligible_document_count"],
            "documents": evidence_readiness["eligible_documents"],
            "fingerprint": evidence_readiness["scope_fingerprint"],
        },
        control_selection_json={
            "baseline": project.impact_baseline,
            "control_count": len(controls),
            "control_ids": [control.display_id for control in controls],
        },
        methods_json=body.planned_methods,
        objects_json=body.assessment_objects,
        depth=body.depth,
        coverage=body.coverage,
        assessor_id=current_user["id"],
        approved_by=current_user["id"],
        approved_at=datetime.now(UTC),
        approval_note=body.plan_approval_note,
    )
    db.add(plan)
    await db.flush()

    for control in controls:
        for procedure in control.assessment_methods:
            method = str(procedure["method"])
            if method not in body.planned_methods:
                continue
            db.add(AssessmentActivity(
                assessment_id=assessment.id,
                plan_id=plan.id,
                control_id=control.display_id,
                method=method,
                assessment_objects=list(procedure.get("objects") or []),
                description=f"{method.title()} the NIST-defined assessment objects for {control.display_id}.",
                status="planned",
            ))
    await db.commit()
    await db.refresh(assessment)
    return assessment


@router.get("", response_model=list[AssessmentResponse])
async def list_assessments(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> list[AssessmentResponse]:
    result = await db.execute(
        select(Assessment).where(Assessment.project_id == project_id).order_by(Assessment.started_at.desc())
    )
    assessments = list(result.scalars().all())
    for assessment in assessments:
        assessment.controls_complete = await _effective_controls_complete(db, assessment)
    return assessments


@router.delete("/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assessment(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_assessor),
) -> None:
    result = await db.execute(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.project_id == project_id)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.finalization_status == "finalized":
        raise HTTPException(status_code=409, detail="A finalized assessment cannot be deleted")
    if assessment.status == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running assessment")
    await db.delete(assessment)
    await db.commit()


@router.post("/{assessment_id}/pause", response_model=AssessmentResponse)
async def pause_assessment(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_assessor),
) -> AssessmentResponse:
    result = await db.execute(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.project_id == project_id)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.status != "running":
        raise HTTPException(status_code=409, detail="Only running assessments can be paused")
    assessment.status = "paused"
    assessment.paused_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(assessment)
    return assessment


@router.post("/{assessment_id}/resume", response_model=AssessmentResponse)
async def resume_assessment(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_assessor),
) -> AssessmentResponse:
    result = await db.execute(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.project_id == project_id)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.status != "paused":
        raise HTTPException(status_code=409, detail="Only paused assessments can be resumed")
    assessment.status = "pending"
    assessment.paused_at = None
    await db.commit()
    await db.refresh(assessment)
    return assessment


@router.patch("/{assessment_id}", response_model=AssessmentResponse)
async def update_assessment(
    project_id: int,
    assessment_id: int,
    body: AssessmentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_assessor),
) -> AssessmentResponse:
    """Update assessment name and/or notes."""
    result = await db.execute(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.project_id == project_id)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if body.name is not None:
        assessment.name = body.name
    if body.notes is not None:
        assessment.notes = body.notes
    await db.commit()
    await db.refresh(assessment)
    return assessment


@router.get("/{assessment_id}", response_model=AssessmentResponse)
async def get_assessment(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> AssessmentResponse:
    result = await db.execute(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.project_id == project_id)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    assessment.controls_complete = await _effective_controls_complete(db, assessment)
    return assessment


@router.get("/{assessment_id}/progress")
async def assessment_progress_sse(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> StreamingResponse:
    """Server-Sent Events stream for real-time assessment progress."""

    async def event_generator():
        while True:
            async with AsyncSessionLocal() as progress_db:
                result = await progress_db.execute(
                    select(Assessment).where(Assessment.id == assessment_id)
                )
                assessment = result.scalar_one_or_none()
                if not assessment:
                    yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                    break
                effective_controls_complete = await _effective_controls_complete(progress_db, assessment)

            if not assessment:
                yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                break
            payload = {
                "status": assessment.status,
                "controls_complete": effective_controls_complete,
                "controls_total": assessment.controls_total,
                "pct": round(effective_controls_complete / max(assessment.controls_total, 1) * 100, 1),
                "progress_detail": assessment.progress_detail,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if assessment.status in ("complete", "failed"):
                break
            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{assessment_id}/findings", response_model=list[ControlFindingResponse])
async def list_findings(
    project_id: int,
    assessment_id: int,
    family: str | None = None,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> list[ControlFindingResponse]:
    q = select(ControlFinding).where(ControlFinding.assessment_id == assessment_id)
    if family:
        q = q.where(ControlFinding.control_family == family.upper())
    if status_filter:
        q = q.where(ControlFinding.status == status_filter)
    result = await db.execute(q.order_by(ControlFinding.control_id))
    return result.scalars().all()


def _require_control_package(package, control_id: str):
    if not package:
        raise HTTPException(status_code=404, detail=f"No staged assessment data found for {control_id}")
    return package


@router.get("/{assessment_id}/controls/{control_id}/criteria")
async def get_control_criteria_package(
    project_id: int,
    assessment_id: int,
    control_id: str,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> dict:
    package = await db.scalar(
        select(AssessmentCriteriaPackage).where(
            AssessmentCriteriaPackage.assessment_id == assessment_id,
            AssessmentCriteriaPackage.control_id == control_id.upper(),
        )
    )
    package = _require_control_package(package, control_id.upper())
    return {
        "control_id": package.control_id,
        "control_family": package.control_family,
        "control_title": package.control_title,
        "control_statement": package.control_statement,
        "supplemental_guidance": package.supplemental_guidance,
        "assessment_objectives": package.assessment_objectives or [],
        "criteria_metadata": package.criteria_metadata or {},
    }


@router.get("/{assessment_id}/controls/{control_id}/triage")
async def get_control_evidence_triage(
    project_id: int,
    assessment_id: int,
    control_id: str,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    rows = (
        await db.execute(
            select(AssessmentEvidenceTriage, EvidenceUnit.content)
            .outerjoin(EvidenceUnit, AssessmentEvidenceTriage.unit_id == EvidenceUnit.id)
            .where(
                AssessmentEvidenceTriage.assessment_id == assessment_id,
                AssessmentEvidenceTriage.control_id == control_id.upper(),
            )
            .order_by(AssessmentEvidenceTriage.sort_order, AssessmentEvidenceTriage.id)
        )
    ).all()
    return [
        {
            "unit_id": row.unit_id,
            "document_id": row.document_id,
            "source_type": row.source_type,
            "artifact_type": row.artifact_type,
            "evidence_strength": row.evidence_strength,
            "evidence_language_type": row.evidence_language_type,
            "document_type": row.document_type,
            "document_intent": row.document_intent,
            "triage_role": row.triage_role,
            "relevance_score": row.relevance_score,
            "citation_label": row.citation_label,
            "excerpt": excerpt,
            "rationale": row.rationale,
            "sort_order": row.sort_order,
        }
        for row, excerpt in rows
    ]


@router.get("/{assessment_id}/controls/{control_id}/objectives")
async def get_control_objective_determinations(
    project_id: int,
    assessment_id: int,
    control_id: str,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    rows = (
        await db.execute(
            select(ObjectiveDetermination)
            .where(
                ObjectiveDetermination.assessment_id == assessment_id,
                ObjectiveDetermination.control_id == control_id.upper(),
            )
            .order_by(ObjectiveDetermination.objective_id)
        )
    ).scalars().all()
    return [
        {
            "objective_id": row.objective_id,
            "objective_text": row.objective_text,
            "status": row.status,
            "rationale": row.rationale,
            "supporting_citations": row.supporting_citations or [],
            "contradictory_citations": row.contradictory_citations or [],
            "missing_evidence": row.missing_evidence,
            "confidence_score": row.confidence_score,
        }
        for row in rows
    ]


@router.get("/{assessment_id}/controls/{control_id}/objective-evidence")
async def get_control_objective_evidence_reviews(
    project_id: int,
    assessment_id: int,
    control_id: str,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> dict:
    rows = (
        await db.execute(
            select(ObjectiveEvidenceReview)
            .where(
                ObjectiveEvidenceReview.assessment_id == assessment_id,
                ObjectiveEvidenceReview.control_id == control_id.upper(),
            )
            .order_by(
                ObjectiveEvidenceReview.objective_id,
                ObjectiveEvidenceReview.sort_order,
                ObjectiveEvidenceReview.id,
            )
        )
    ).scalars().all()
    grouped: dict[str, dict] = {}
    for row in rows:
        entry = grouped.setdefault(
            row.objective_id,
            {
                "objective_id": row.objective_id,
                "objective_text": row.objective_text,
                "reviews": [],
            },
        )
        entry["reviews"].append(
            {
                "unit_id": row.unit_id,
                "document_id": row.document_id,
                "source_type": row.source_type,
                "artifact_type": row.artifact_type,
                "evidence_strength": row.evidence_strength,
                "document_type": row.document_type,
                "document_intent": row.document_intent,
                "review_role": row.review_role,
                "used_in_prompt": row.used_in_prompt,
                "objective_relevance_score": row.objective_relevance_score,
                "keyword_hits": row.keyword_hits or [],
                "excerpt": row.excerpt,
                "rationale": row.rationale,
                "sort_order": row.sort_order,
            }
        )
    return {
        "control_id": control_id.upper(),
        "objective_reviews": list(grouped.values()),
    }


@router.get("/{assessment_id}/controls/{control_id}/determination")
async def get_control_determination(
    project_id: int,
    assessment_id: int,
    control_id: str,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> dict:
    determination = await db.scalar(
        select(ControlDetermination).where(
            ControlDetermination.assessment_id == assessment_id,
            ControlDetermination.control_id == control_id.upper(),
        )
    )
    if not determination:
        raise HTTPException(status_code=404, detail=f"No control determination found for {control_id.upper()}")
    return {
        "control_id": determination.control_id,
        "status": determination.status,
        "confidence_score": determination.confidence_score,
        "objective_summary": determination.objective_summary or {},
        "deficiency_summary": determination.deficiency_summary,
        "evidence_summary": determination.evidence_summary,
    }


@router.get("/{assessment_id}/controls/{control_id}/challenge")
async def get_control_challenge(
    project_id: int,
    assessment_id: int,
    control_id: str,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> dict:
    challenge = await db.scalar(
        select(AssessmentChallenge).where(
            AssessmentChallenge.assessment_id == assessment_id,
            AssessmentChallenge.control_id == control_id.upper(),
        )
    )
    if not challenge:
        raise HTTPException(status_code=404, detail=f"No challenge record found for {control_id.upper()}")
    return {
        "control_id": challenge.control_id,
        "concur": challenge.concur,
        "dissent_note": challenge.dissent_note,
        "challenged_objectives": challenge.challenged_objectives or [],
        "model_name": challenge.model_name,
    }


@router.get("/{assessment_id}/rollup")
async def get_assessment_rollup(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> dict:
    rollup = await db.scalar(
        select(AssessmentRollup).where(AssessmentRollup.assessment_id == assessment_id)
    )
    if not rollup:
        raise HTTPException(status_code=404, detail="Assessment rollup not found")
    findings = (
        await db.execute(
            select(ControlFinding).where(ControlFinding.assessment_id == assessment_id).order_by(ControlFinding.control_id)
        )
    ).scalars().all()
    summary = dict(rollup.summary_json or {})
    counts = dict(summary.get("counts") or {})
    counts.setdefault("total_controls", len(findings))
    counts.setdefault("compliant", sum(1 for finding in findings if finding.status == "compliant"))
    counts.setdefault(
        "partially_compliant",
        sum(1 for finding in findings if finding.status == "partially_compliant"),
    )
    counts.setdefault("non_compliant", sum(1 for finding in findings if finding.status == "non_compliant"))
    counts.setdefault("not_applicable", sum(1 for finding in findings if finding.status == "not_applicable"))
    counts.setdefault("not_reviewed", sum(1 for finding in findings if finding.status == "not_reviewed"))
    counts["needs_review"] = sum(1 for finding in findings if finding.needs_manual_review)
    summary["counts"] = counts

    if not summary.get("source_documents") or not summary.get("source_controls"):
        triage_rows = (
            await db.execute(
                select(AssessmentEvidenceTriage).where(AssessmentEvidenceTriage.assessment_id == assessment_id)
            )
        ).scalars().all()
        source_keys = ("project", "common_control", "policy", "procedure")
        source_documents = {key: set() for key in source_keys}
        source_controls = {key: set() for key in source_keys}
        for row in triage_rows:
            if row.source_type not in source_documents:
                continue
            if row.document_id:
                source_documents[row.source_type].add(row.document_id)
            if row.control_id:
                source_controls[row.source_type].add(row.control_id)
        summary["source_documents"] = {
            key: len(value) for key, value in source_documents.items()
        }
        summary["source_controls"] = {
            key: len(value) for key, value in source_controls.items()
        }

    review_attention = dict(summary.get("review_attention") or {})
    if not review_attention.get("controls"):
        controls = []
        reason_counts: dict[str, int] = {}
        for finding in findings:
            if not finding.needs_manual_review:
                continue
            reasons = _manual_review_reasons_from_notes(finding.notes)
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            controls.append({
                "control_id": finding.control_id,
                "title": finding.control_title,
                "status": finding.status,
                "confidence": finding.confidence_score,
                "reasons": reasons,
            })
        review_attention = {
            "count": len(controls),
            "controls": controls,
            "reason_counts": reason_counts,
        }
    else:
        review_attention["count"] = len(review_attention.get("controls") or [])

    display_controls = []
    display_reason_counts: dict[str, int] = {}
    for control in review_attention.get("controls") or []:
        reasons = _display_review_reasons(control.get("reasons") or [])
        if not reasons:
            continue
        display_control = dict(control)
        display_control["reasons"] = reasons
        display_controls.append(display_control)
        for reason in reasons:
            display_reason_counts[reason] = display_reason_counts.get(reason, 0) + 1

    review_attention["raw_count"] = review_attention.get("count", len(review_attention.get("controls") or []))
    review_attention["count"] = len(display_controls)
    review_attention["controls"] = display_controls
    review_attention["reason_counts"] = display_reason_counts
    summary["review_attention"] = review_attention

    return {
        "assessment_id": assessment_id,
        "readiness": rollup.readiness,
        "summary": summary,
        "residual_risk_summary": _normalize_review_attention_summary(
            _normalize_rollup_summary_text(rollup.residual_risk_summary),
            review_attention["count"],
        ),
        "updated_at": rollup.updated_at.isoformat() if rollup.updated_at else None,
    }


@router.get("/{assessment_id}/evidence-sources")
async def list_assessment_evidence_sources(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    _: dict = Depends(require_viewer),
) -> list[dict]:
    result = await db.execute(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.project_id == project_id)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    indexed_statuses = ("complete", "indexed")
    linked_providers = (
        select(ProjectCommonProvider.provider_id)
        .where(ProjectCommonProvider.project_id == project_id)
        .scalar_subquery()
    )

    docs_result = await db.execute(
        select(Document)
        .where(
            Document.parse_status.in_(indexed_statuses),
            or_(
                Document.project_id == project_id,
                Document.provider_id.in_(linked_providers),
                Document.policy_library_id.is_not(None),
                Document.procedure_library_id.is_not(None),
            ),
        )
        .order_by(Document.created_at.desc(), Document.id.desc())
    )
    docs = docs_result.scalars().all()

    out: list[dict] = []
    for doc in docs:
        if doc.project_id == project_id:
            scope = "project"
            download_url = f"/projects/{project_id}/documents/{doc.id}/download"
        elif doc.provider_id is not None:
            scope = "provider"
            download_url = f"/common-controls/providers/{doc.provider_id}/documents/{doc.id}/download"
        elif doc.policy_library_id is not None:
            scope = "policy_library"
            download_url = f"/enterprise-policies/libraries/{doc.policy_library_id}/documents/{doc.id}/download"
        elif doc.procedure_library_id is not None:
            scope = "procedure_library"
            download_url = f"/enterprise-procedures/libraries/{doc.procedure_library_id}/documents/{doc.id}/download"
        else:
            continue

        out.append({
            "id": doc.id,
            "filename": doc.filename,
            "scope": scope,
            "project_id": doc.project_id,
            "provider_id": doc.provider_id,
            "policy_library_id": doc.policy_library_id,
            "procedure_library_id": doc.procedure_library_id,
            "download_url": download_url,
        })
    return out


@router.post("/{assessment_id}/retry-failed", status_code=status.HTTP_202_ACCEPTED)
async def retry_failed_findings(
    project_id: int,
    assessment_id: int,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    current_user: dict = Depends(require_assessor),
) -> dict:
    """Re-queue all not_reviewed findings for automated retry."""
    result = await db.execute(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.project_id == project_id)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    await _require_mutable_assessment(assessment_id, db)
    if assessment.status == "running":
        raise HTTPException(status_code=409, detail="Assessment is already running")

    # Count pending retries
    count_result = await db.execute(
        select(ControlFinding).where(
            ControlFinding.assessment_id == assessment_id,
            ControlFinding.status == "not_reviewed",
        )
    )
    pending = count_result.scalars().all()
    if not pending:
        return {"queued": 0, "message": "No failed findings to retry"}
    active_job = await db.scalar(
        select(AssessmentRetryJob).where(
            AssessmentRetryJob.assessment_id == assessment_id,
            AssessmentRetryJob.status.in_(("pending", "running")),
        )
    )
    if active_job:
        raise HTTPException(status_code=409, detail="A failed-finding retry is already queued or running")

    job = AssessmentRetryJob(
        assessment_id=assessment_id,
        control_ids=[finding.control_id for finding in pending],
        created_by=current_user["id"],
    )
    db.add(job)
    for finding in pending:
        await log_action(
            db,
            project_id=project_id,
            assessment_id=assessment_id,
            control_id=finding.control_id,
            control_family=finding.control_family,
            control_title=finding.control_title,
            action_type="retry_queued",
            action_summary="Failed finding queued for durable worker retry",
            performed_by=current_user["username"],
        )
    await db.commit()
    await db.refresh(job)
    return {
        "queued": len(pending),
        "job_id": job.id,
        "message": f"Queued {len(pending)} failed findings for worker retry",
    }


@router.patch("/{assessment_id}/findings/{finding_id}/notes", response_model=ControlFindingResponse)
async def update_finding_notes(
    project_id: int,
    assessment_id: int,
    finding_id: int,
    body: FindingNotesRequest,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    current_user: dict = Depends(require_reviewer),
) -> ControlFindingResponse:
    """Update analyst notes on a specific control finding."""
    result = await db.execute(
        select(ControlFinding).where(
            ControlFinding.id == finding_id,
            ControlFinding.assessment_id == assessment_id,
        )
    )
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    finding.notes = body.notes
    await log_action(
        db, project_id=project_id, assessment_id=assessment_id,
        control_id=finding.control_id, control_family=finding.control_family,
        control_title=finding.control_title,
        action_type="notes_updated",
        action_summary="Analyst notes updated",
        performed_by=current_user.get("username", "unknown"),
        details={"notes_preview": (body.notes or "")[:120]},
    )
    await db.commit()
    await db.refresh(finding)
    return finding


@router.patch("/{assessment_id}/findings/{finding_id}/resolve", response_model=ControlFindingResponse)
async def manual_resolve_finding(
    project_id: int,
    assessment_id: int,
    finding_id: int,
    body: FindingManualResolveRequest,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    current_user: dict = Depends(require_reviewer),
) -> ControlFindingResponse:
    """Manually resolve a finding that could not be parsed automatically."""
    await _require_mutable_assessment(assessment_id, db)
    result = await db.execute(
        select(ControlFinding).where(
            ControlFinding.id == finding_id,
            ControlFinding.assessment_id == assessment_id,
        )
    )
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    finding.status = body.status
    finding.implementation_statement = body.implementation_statement
    finding.gaps = body.gaps
    finding.remediation_plan = body.remediation_plan
    finding.confidence_score = body.confidence_score
    finding.needs_manual_review = False
    finding.raw_llm_response = None
    finding.reviewed_by = current_user["id"]
    finding.reviewer_note = body.reviewer_note
    finding.reviewer_status = "override"
    finding.reviewed_at = datetime.now(UTC)
    await log_action(
        db, project_id=project_id, assessment_id=assessment_id,
        control_id=finding.control_id, control_family=finding.control_family,
        control_title=finding.control_title,
        action_type="manual_resolved",
        action_summary=f"Manually resolved by {current_user.get('username', 'unknown')}: status set to {body.status.replace('_', ' ').title()}",
        performed_by=current_user.get("username", "unknown"),
        details={"new_status": body.status, "confidence": body.confidence_score,
                 "reviewer_note": body.reviewer_note},
    )
    await db.commit()
    await db.refresh(finding)
    return finding


@router.patch("/{assessment_id}/findings/{finding_id}", response_model=ControlFindingResponse)
async def review_finding(
    project_id: int,
    assessment_id: int,
    finding_id: int,
    body: FindingReviewRequest,
    db: AsyncSession = Depends(get_db),
    _project_access: dict = Depends(require_project_assessment_access),
    current_user: dict = Depends(require_reviewer),
) -> ControlFindingResponse:
    await _require_mutable_assessment(assessment_id, db)
    result = await db.execute(
        select(ControlFinding).where(
            ControlFinding.id == finding_id,
            ControlFinding.assessment_id == assessment_id,
        )
    )
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    finding.reviewer_status = body.reviewer_status
    finding.reviewer_note = body.reviewer_note
    finding.reviewed_by = current_user["id"]
    finding.reviewed_at = datetime.now(UTC)

    action_map = {
        "accepted": ("reviewer_accepted", "Finding accepted by reviewer"),
        "override": ("reviewer_override", "Finding overridden by reviewer"),
        "revision_requested": ("reviewer_revision", "Reviewer requested revision"),
    }
    atype, base_summary = action_map.get(body.reviewer_status, ("reviewer_action", "Reviewer action"))
    summary = f"{base_summary} — {current_user.get('username', 'unknown')}"
    if body.reviewer_note:
        summary += f": {body.reviewer_note[:120]}"
    await log_action(
        db, project_id=project_id, assessment_id=assessment_id,
        control_id=finding.control_id, control_family=finding.control_family,
        control_title=finding.control_title,
        action_type=atype, action_summary=summary,
        performed_by=current_user.get("username", "unknown"),
        details={"reviewer_status": body.reviewer_status, "note": body.reviewer_note},
    )
    await db.commit()
    await db.refresh(finding)
    return finding
