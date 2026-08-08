"""Persistent calibration harness for synthetic package validation."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    Assessment,
    CalibrationCase,
    CalibrationCaseResult,
    CalibrationRun,
    CalibrationSuite,
    ControlFinding,
    ObjectiveDetermination,
    TestDatasetJob,
)
from app.services.package_generation import build_benchmark_result


def _seconds_between(started_at: datetime | None, completed_at: datetime | None) -> float | None:
    if not started_at or not completed_at:
        return None
    try:
        return round((completed_at - started_at).total_seconds(), 3)
    except Exception:
        return None


def _build_performance_snapshot(*, source_content: dict | None = None, assessment: Assessment | None = None) -> dict:
    source_content = source_content or {}
    timing = source_content.get("timing") or {}
    artifact_validation = source_content.get("artifact_validation") or {}
    package_viability = artifact_validation.get("package_viability") or {}

    snapshot = {
        "package_timing": timing,
        "package_viability_score": package_viability.get("viability_score"),
        "package_viability_status": package_viability.get("status"),
        "weak_documents_count": artifact_validation.get("weak_documents_count"),
    }
    if assessment is not None:
        snapshot["assessment"] = {
            "assessment_id": assessment.id,
            "llm_provider": assessment.llm_provider,
            "llm_model": assessment.llm_model,
            "duration_secs": _seconds_between(assessment.started_at, assessment.completed_at),
            "started_at": assessment.started_at.isoformat() if assessment.started_at else None,
            "completed_at": assessment.completed_at.isoformat() if assessment.completed_at else None,
        }
    return snapshot


def _normalize_expected_objectives(expected) -> dict[str, str]:
    if not expected:
        return {}
    if isinstance(expected, dict):
        return {
            str(key): str(value)
            for key, value in expected.items()
            if key and value
        }
    if isinstance(expected, list):
        normalized = {}
        for item in expected:
            if not isinstance(item, dict):
                continue
            objective_id = item.get("objective_id") or item.get("id")
            status = item.get("status") or item.get("expected_status")
            if objective_id and status:
                normalized[str(objective_id)] = str(status)
        return normalized
    return {}


def _normalize_expected_citations(expected) -> list[str]:
    if not expected:
        return []
    if isinstance(expected, list):
        values = []
        for item in expected:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                candidate = item.get("filename") or item.get("source") or item.get("quote") or item.get("match")
                if candidate:
                    values.append(str(candidate))
        return [value.strip() for value in values if str(value).strip()]
    if isinstance(expected, dict):
        values = []
        for key, value in expected.items():
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
            elif key and str(key).strip():
                values.append(str(key).strip())
        return values
    if isinstance(expected, str) and expected.strip():
        return [expected.strip()]
    return []


def _citation_texts(citations) -> list[str]:
    values: list[str] = []
    if not citations:
        return values
    for citation in citations:
        if isinstance(citation, str):
            if citation.strip():
                values.append(citation.strip())
            continue
        if not isinstance(citation, dict):
            continue
        parts = [
            citation.get("filename"),
            citation.get("source"),
            citation.get("download_url"),
            citation.get("quote"),
            citation.get("relevance"),
            citation.get("text"),
        ]
        merged = " ".join(str(part) for part in parts if part)
        if merged.strip():
            values.append(merged.strip())
    return values


async def run_test_dataset_calibration(
    db: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    created_by: int | None = None,
) -> dict:
    job = (
        await db.execute(
            select(TestDatasetJob).where(
                TestDatasetJob.id == job_id,
                TestDatasetJob.project_id == project_id,
            )
        )
    ).scalars().first()
    if not job:
        raise ValueError("Test dataset job not found")

    content = job.content_json or {}
    expected_outcomes = content.get("expected_outcomes")
    if not expected_outcomes:
        raise ValueError("Test dataset job does not contain expected outcomes")

    calibration_run = CalibrationRun(
        project_id=project_id,
        source_type="test_dataset_job",
        source_run_id=job_id,
        status="running",
        created_by=created_by,
        runtime_snapshot_json={
            "job_id": job.id,
            "job_created_at": job.created_at.isoformat() if job.created_at else None,
            "config": content.get("config", {}),
            "performance": _build_performance_snapshot(source_content=content),
        },
    )
    db.add(calibration_run)
    await db.flush()

    assessment = (
        await db.execute(
            select(Assessment)
            .where(
                Assessment.project_id == project_id,
                Assessment.status == "complete",
                Assessment.completed_at.is_not(None),
                Assessment.completed_at >= job.created_at,
            )
            .order_by(Assessment.completed_at.desc())
            .limit(1)
        )
    ).scalars().first()

    if not assessment:
        calibration_run.status = "waiting_for_assessment"
        calibration_run.summary_json = {
            "status": "waiting_for_assessment",
            "message": "No completed assessment was found after this synthetic package was generated.",
            "job_id": job_id,
        }
        await db.commit()
        return {
            "run_id": calibration_run.id,
            **(calibration_run.summary_json or {}),
            "results": [],
        }

    findings = (
        await db.execute(
            select(ControlFinding.control_id, ControlFinding.status)
            .where(ControlFinding.assessment_id == assessment.id)
        )
    ).all()
    actual = {control_id: status for control_id, status in findings}
    benchmark = build_benchmark_result(expected_outcomes, actual)

    expected_by_control = expected_outcomes.get("by_control", {})
    case_rows: list[CalibrationCaseResult] = []
    drift_counter = Counter()
    for control_id, expected_status in expected_by_control.items():
        actual_status = actual.get(control_id, "not_reviewed")
        if actual_status == expected_status:
            match_status = "matched"
        elif expected_status == "compliant" and actual_status in {"partially_compliant", "non_compliant"}:
            match_status = "false_strict"
        elif expected_status == "non_compliant" and actual_status in {"partially_compliant", "compliant"}:
            match_status = "false_pass"
        elif expected_status == "partially_compliant" and actual_status == "non_compliant":
            match_status = "too_strict_partial"
        elif expected_status == "partially_compliant" and actual_status == "compliant":
            match_status = "too_lenient_partial"
        else:
            match_status = "mismatch"
        drift_counter[match_status] += 1
        case_rows.append(
            CalibrationCaseResult(
                run_id=calibration_run.id,
                control_id=control_id,
                expected_status=expected_status,
                actual_status=actual_status,
                match_status=match_status,
                delta_json={
                    "control_id": control_id,
                    "expected_status": expected_status,
                    "actual_status": actual_status,
                },
            )
        )

    db.add_all(case_rows)
    calibration_run.status = "complete"
    calibration_run.completed_at = datetime.now(UTC)
    calibration_run.summary_json = {
        "status": "complete",
        "job_id": job_id,
        "assessment_id": assessment.id,
        "assessment_completed_at": assessment.completed_at.isoformat() if assessment.completed_at else None,
        "match_pct": benchmark["match_pct"],
        "matched": benchmark["matched"],
        "total_controls": benchmark["total_controls"],
        "mismatch_count": benchmark["mismatch_count"],
        "expected_counts": benchmark["expected_counts"],
        "actual_counts": benchmark["actual_counts"],
        "drift_counts": dict(drift_counter),
        "top_mismatches": benchmark["mismatches"][:25],
        "performance": _build_performance_snapshot(source_content=content, assessment=assessment),
    }
    await db.commit()

    return {
        "run_id": calibration_run.id,
        **(calibration_run.summary_json or {}),
        "results": [
            {
                "control_id": row.control_id,
                "expected_status": row.expected_status,
                "actual_status": row.actual_status,
                "match_status": row.match_status,
            }
            for row in case_rows[:100]
        ],
    }


async def get_latest_calibration_for_job(
    db: AsyncSession,
    *,
    project_id: int,
    job_id: int,
) -> dict | None:
    run = (
        await db.execute(
            select(CalibrationRun)
            .where(
                CalibrationRun.project_id == project_id,
                CalibrationRun.source_type == "test_dataset_job",
                CalibrationRun.source_run_id == job_id,
            )
            .order_by(CalibrationRun.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if not run:
        return None

    rows = (
        await db.execute(
            select(CalibrationCaseResult)
            .where(CalibrationCaseResult.run_id == run.id)
            .order_by(CalibrationCaseResult.control_id)
            .limit(100)
        )
    ).scalars().all()
    return {
        "id": run.id,
        "project_id": run.project_id,
        "source_type": run.source_type,
        "source_run_id": run.source_run_id,
        "status": run.status,
        "summary": run.summary_json or {},
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "results": [
            {
                "control_id": row.control_id,
                "expected_status": row.expected_status,
                "actual_status": row.actual_status,
                "match_status": row.match_status,
            }
            for row in rows
        ],
    }


async def list_calibration_suites(
    db: AsyncSession,
    *,
    project_id: int,
) -> list[dict]:
    suites = (
        await db.execute(
            select(CalibrationSuite)
            .where(CalibrationSuite.project_id == project_id)
            .order_by(CalibrationSuite.created_at.desc(), CalibrationSuite.id.desc())
        )
    ).scalars().all()

    results: list[dict] = []
    for suite in suites:
        cases = (
            await db.execute(
                select(CalibrationCase)
                .where(CalibrationCase.suite_id == suite.id)
                .order_by(CalibrationCase.control_id, CalibrationCase.id)
            )
        ).scalars().all()
        latest_run = (
            await db.execute(
                select(CalibrationRun)
                .where(
                    CalibrationRun.project_id == project_id,
                    CalibrationRun.source_type == "suite",
                    CalibrationRun.source_run_id == suite.id,
                )
                .order_by(CalibrationRun.id.desc())
                .limit(1)
            )
        ).scalars().first()
        results.append(
            {
                "id": suite.id,
                "name": suite.name,
                "description": suite.description,
                "created_at": suite.created_at.isoformat() if suite.created_at else None,
                "case_count": len(cases),
                "cases": [
                    {
                        "id": case.id,
                        "control_id": case.control_id,
                        "expected_status": case.expected_status,
                        "expected_objectives": case.expected_objectives_json,
                        "expected_citations": case.expected_citations_json,
                        "notes": case.notes,
                    }
                    for case in cases
                ],
                "latest_run": None
                if not latest_run
                else {
                    "id": latest_run.id,
                    "status": latest_run.status,
                    "summary": latest_run.summary_json or {},
                    "created_at": latest_run.created_at.isoformat() if latest_run.created_at else None,
                    "completed_at": latest_run.completed_at.isoformat() if latest_run.completed_at else None,
                },
            }
        )
    return results


async def run_suite_calibration(
    db: AsyncSession,
    *,
    project_id: int,
    suite_id: int,
    created_by: int | None = None,
    assessment_id: int | None = None,
) -> dict:
    suite = (
        await db.execute(
            select(CalibrationSuite).where(
                CalibrationSuite.id == suite_id,
                CalibrationSuite.project_id == project_id,
            )
        )
    ).scalars().first()
    if not suite:
        raise ValueError("Calibration suite not found")

    cases = (
        await db.execute(
            select(CalibrationCase)
            .where(CalibrationCase.suite_id == suite.id)
            .order_by(CalibrationCase.control_id, CalibrationCase.id)
        )
    ).scalars().all()
    if not cases:
        raise ValueError("Calibration suite has no cases")

    if assessment_id is not None:
        assessment = (
            await db.execute(
                select(Assessment).where(
                    Assessment.id == assessment_id,
                    Assessment.project_id == project_id,
                    Assessment.status == "complete",
                )
            )
        ).scalars().first()
    else:
        assessment = (
            await db.execute(
                select(Assessment)
                .where(
                    Assessment.project_id == project_id,
                    Assessment.status == "complete",
                )
                .order_by(Assessment.completed_at.desc().nullslast(), Assessment.id.desc())
                .limit(1)
            )
        ).scalars().first()

    if not assessment:
        raise ValueError("No completed assessment available for this suite")

    run = CalibrationRun(
        project_id=project_id,
        source_type="suite",
        source_run_id=suite.id,
        status="running",
        created_by=created_by,
        runtime_snapshot_json={
            "suite_id": suite.id,
            "suite_name": suite.name,
            "assessment_id": assessment.id,
            "assessment_completed_at": assessment.completed_at.isoformat() if assessment.completed_at else None,
            "case_count": len(cases),
            "assessment_performance": _build_performance_snapshot(assessment=assessment).get("assessment", {}),
        },
    )
    db.add(run)
    await db.flush()

    findings = (
        await db.execute(
            select(
                ControlFinding.control_id,
                ControlFinding.status,
                ControlFinding.evidence_citations,
            )
            .where(ControlFinding.assessment_id == assessment.id)
        )
    ).all()
    actual = {control_id: status for control_id, status, _ in findings}
    control_citations = {control_id: (citations or []) for control_id, _status, citations in findings}
    objective_rows = (
        await db.execute(
            select(
                ObjectiveDetermination.control_id,
                ObjectiveDetermination.objective_id,
                ObjectiveDetermination.status,
                ObjectiveDetermination.supporting_citations,
            )
            .where(ObjectiveDetermination.assessment_id == assessment.id)
        )
    ).all()
    objective_map: dict[str, dict[str, str]] = {}
    objective_citations: dict[str, list] = {}
    for control_id, objective_id, status, supporting_citations in objective_rows:
        objective_map.setdefault(control_id, {})[objective_id] = status
        if supporting_citations:
            objective_citations.setdefault(control_id, []).extend(supporting_citations or [])

    case_results: list[CalibrationCaseResult] = []
    drift_counter = Counter()
    expected_counts = Counter()
    actual_counts = Counter()
    mismatches: list[dict] = []
    for case in cases:
        expected_status = case.expected_status
        actual_status = actual.get(case.control_id, "not_reviewed")
        expected_objectives = _normalize_expected_objectives(case.expected_objectives_json)
        actual_objectives = objective_map.get(case.control_id, {})
        objective_mismatches = []
        for objective_id, expected_objective_status in expected_objectives.items():
            actual_objective_status = actual_objectives.get(objective_id, "not_reviewed")
            if actual_objective_status != expected_objective_status:
                objective_mismatches.append(
                    {
                        "objective_id": objective_id,
                        "expected_status": expected_objective_status,
                        "actual_status": actual_objective_status,
                    }
                )
        expected_citations = _normalize_expected_citations(case.expected_citations_json)
        actual_citation_text = " || ".join(
            _citation_texts(control_citations.get(case.control_id, []))
            + _citation_texts(objective_citations.get(case.control_id, []))
        ).lower()
        citation_checks = []
        missing_citations = []
        for expected_citation in expected_citations:
            matched = expected_citation.lower() in actual_citation_text if actual_citation_text else False
            citation_checks.append({"expected": expected_citation, "matched": matched})
            if not matched:
                missing_citations.append(expected_citation)
        expected_counts[expected_status] += 1
        actual_counts[actual_status] += 1
        if actual_status == expected_status:
            match_status = "matched"
        elif expected_status == "compliant" and actual_status in {"partially_compliant", "non_compliant"}:
            match_status = "false_strict"
        elif expected_status == "non_compliant" and actual_status in {"partially_compliant", "compliant"}:
            match_status = "false_pass"
        elif expected_status == "partially_compliant" and actual_status == "non_compliant":
            match_status = "too_strict_partial"
        elif expected_status == "partially_compliant" and actual_status == "compliant":
            match_status = "too_lenient_partial"
        else:
            match_status = "mismatch"
        drift_counter[match_status] += 1
        if match_status != "matched" or objective_mismatches or missing_citations:
            mismatches.append(
                {
                    "case_id": case.id,
                    "control_id": case.control_id,
                    "expected_status": expected_status,
                    "actual_status": actual_status,
                    "notes": case.notes,
                    "objective_mismatches": objective_mismatches[:10],
                    "missing_citations": missing_citations[:10],
                }
            )
        case_results.append(
            CalibrationCaseResult(
                run_id=run.id,
                control_id=case.control_id,
                expected_status=expected_status,
                actual_status=actual_status,
                match_status=match_status,
                delta_json={
                    "case_id": case.id,
                    "control_id": case.control_id,
                    "expected_status": expected_status,
                    "actual_status": actual_status,
                    "notes": case.notes,
                    "expected_objectives": expected_objectives,
                    "actual_objectives": actual_objectives,
                    "objective_mismatches": objective_mismatches,
                    "expected_citations": expected_citations,
                    "citation_checks": citation_checks,
                    "missing_citations": missing_citations,
                },
            )
        )

    db.add_all(case_results)
    total_controls = len(cases)
    matched = drift_counter.get("matched", 0)
    run.status = "complete"
    run.completed_at = datetime.now(UTC)
    run.summary_json = {
        "status": "complete",
        "suite_id": suite.id,
        "suite_name": suite.name,
        "assessment_id": assessment.id,
        "total_controls": total_controls,
        "matched": matched,
        "match_pct": round((matched / total_controls) * 100, 2) if total_controls else 0.0,
        "mismatch_count": total_controls - matched,
        "expected_counts": dict(expected_counts),
        "actual_counts": dict(actual_counts),
        "drift_counts": dict(drift_counter),
        "top_mismatches": mismatches[:25],
        "performance": _build_performance_snapshot(assessment=assessment),
    }
    await db.commit()
    return {
        "id": run.id,
        "status": run.status,
        "summary": run.summary_json,
    }


async def get_calibration_run(
    db: AsyncSession,
    *,
    project_id: int,
    run_id: int,
) -> dict | None:
    run = (
        await db.execute(
            select(CalibrationRun).where(
                CalibrationRun.id == run_id,
                CalibrationRun.project_id == project_id,
            )
        )
    ).scalars().first()
    if not run:
        return None
    rows = (
        await db.execute(
            select(CalibrationCaseResult)
            .where(CalibrationCaseResult.run_id == run.id)
            .order_by(CalibrationCaseResult.match_status, CalibrationCaseResult.control_id)
        )
    ).scalars().all()
    return {
        "id": run.id,
        "source_type": run.source_type,
        "source_run_id": run.source_run_id,
        "status": run.status,
        "summary": run.summary_json or {},
        "runtime_snapshot": run.runtime_snapshot_json or {},
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "results": [
            {
                "control_id": row.control_id,
                "expected_status": row.expected_status,
                "actual_status": row.actual_status,
                "match_status": row.match_status,
                "delta": row.delta_json or {},
            }
            for row in rows
        ],
    }
