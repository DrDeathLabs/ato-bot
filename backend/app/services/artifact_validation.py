"""Validation helpers for generated remediation and synthetic packages."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    ArtifactValidationResult,
    ArtifactValidationRun,
    Document,
    EvidenceClassification,
    EvidenceEmbedding,
    EvidenceUnit,
    IngestionRun,
    PackageViabilityRun,
)

MIN_FILE_SIZE_BYTES = 1500
MIN_PARSED_LINES = 12
MIN_EVIDENCE_UNITS = 2
MIN_MAPPED_UNITS = 1


def _status_for_flag(flag: bool) -> str:
    return "pass" if flag else "fail"


def _score_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


async def validate_generated_artifacts(
    db: AsyncSession,
    *,
    project_id: int,
    document_ids: list[int],
    source_mode: str,
    source_run_id: int,
    expected_profile: str | None = None,
) -> dict:
    """Persist generated-artifact validation results and a package viability score."""
    validation_run = ArtifactValidationRun(
        project_id=project_id,
        source_mode=source_mode,
        source_run_id=source_run_id,
        status="running",
    )
    db.add(validation_run)
    await db.flush()

    if not document_ids:
        validation_run.status = "complete"
        validation_run.summary_json = {
            "document_count": 0,
            "status": "empty",
            "integrity_passed": 0,
            "ingestion_complete": 0,
            "retrieval_viable": 0,
            "mapped_documents": 0,
            "weak_documents": [],
        }
        viability_run = PackageViabilityRun(
            project_id=project_id,
            source_mode=source_mode,
            source_run_id=source_run_id,
            expected_profile=expected_profile,
            viability_score=0.0,
            status="empty",
            summary_json={"document_count": 0, "status": "empty"},
        )
        db.add(viability_run)
        await db.commit()
        return {
            "validation_run_id": validation_run.id,
            "package_viability_run_id": viability_run.id,
            "status": "empty",
            "document_count": 0,
        }

    docs = (
        await db.execute(
            select(Document).where(
                Document.project_id == project_id,
                Document.id.in_(document_ids),
            )
        )
    ).scalars().all()

    doc_ids = [doc.id for doc in docs]
    latest_runs_subquery = (
        select(
            IngestionRun.document_id.label("document_id"),
            func.max(IngestionRun.id).label("run_id"),
        )
        .where(IngestionRun.document_id.in_(doc_ids))
        .group_by(IngestionRun.document_id)
        .subquery()
    )
    latest_runs = {
        run.document_id: run
        for run in (
            await db.execute(
                select(IngestionRun)
                .join(latest_runs_subquery, latest_runs_subquery.c.run_id == IngestionRun.id)
            )
        ).scalars().all()
    }
    mapped_counts = {
        document_id: count
        for document_id, count in (
            await db.execute(
                select(
                    EvidenceUnit.document_id,
                    func.count(func.distinct(EvidenceClassification.unit_id)),
                )
                .join(EvidenceClassification, EvidenceClassification.unit_id == EvidenceUnit.id)
                .where(
                    EvidenceUnit.document_id.in_(doc_ids),
                    func.coalesce(func.jsonb_array_length(EvidenceClassification.control_ids), 0) > 0,
                )
                .group_by(EvidenceUnit.document_id)
            )
        ).all()
    }
    embedding_counts = {
        document_id: count
        for document_id, count in (
            await db.execute(
                select(
                    EvidenceUnit.document_id,
                    func.count(EvidenceEmbedding.id),
                )
                .join(EvidenceEmbedding, EvidenceEmbedding.unit_id == EvidenceUnit.id)
                .where(EvidenceUnit.document_id.in_(doc_ids))
                .group_by(EvidenceUnit.document_id)
            )
        ).all()
    }

    results: list[ArtifactValidationResult] = []
    weak_documents: list[dict] = []
    integrity_passed = 0
    ingestion_complete = 0
    retrieval_viable = 0
    mapped_documents = 0

    for doc in docs:
        latest_run = latest_runs.get(doc.id)

        file_path = Path(doc.file_path)
        file_exists = file_path.exists()
        file_size = 0
        if file_exists:
            try:
                file_size = file_path.stat().st_size
            except OSError:
                file_size = 0

        parsed_lines = latest_run.lines_parsed if latest_run else 0
        evidence_units = latest_run.evidence_units_created if latest_run else 0
        units_classified = latest_run.units_classified if latest_run else 0
        units_embedded = latest_run.units_embedded if latest_run else 0

        mapped_unit_count = mapped_counts.get(doc.id, 0)
        embedding_count = embedding_counts.get(doc.id, 0)

        integrity_ok = file_exists and file_size >= MIN_FILE_SIZE_BYTES and parsed_lines >= MIN_PARSED_LINES
        ingestion_ok = bool(latest_run and latest_run.status == "complete" and units_classified >= evidence_units and units_embedded >= evidence_units)
        mapping_ok = mapped_unit_count >= MIN_MAPPED_UNITS
        retrieval_ok = mapping_ok and embedding_count >= max(1, min(evidence_units, MIN_EVIDENCE_UNITS))

        if integrity_ok:
            integrity_passed += 1
        if ingestion_ok:
            ingestion_complete += 1
        if mapping_ok:
            mapped_documents += 1
        if retrieval_ok:
            retrieval_viable += 1

        details = {
            "filename": doc.filename,
            "file_exists": file_exists,
            "file_size_bytes": file_size,
            "parse_status": doc.parse_status,
            "ingestion_run_id": latest_run.id if latest_run else None,
            "ingestion_status": latest_run.status if latest_run else "missing",
            "lines_parsed": parsed_lines,
            "evidence_units_created": evidence_units,
            "units_classified": units_classified,
            "units_embedded": units_embedded,
            "mapped_units": mapped_unit_count,
            "embeddings": embedding_count,
            "document_type": doc.document_type,
            "document_intent": doc.document_intent,
        }

        if not (integrity_ok and ingestion_ok and retrieval_ok):
            weak_documents.append(
                {
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "integrity_status": _status_for_flag(integrity_ok),
                    "ingestion_status": _status_for_flag(ingestion_ok),
                    "control_mapping_status": _status_for_flag(mapping_ok),
                    "retrieval_status": _status_for_flag(retrieval_ok),
                    "details": details,
                }
            )

        result = ArtifactValidationResult(
            validation_run_id=validation_run.id,
            document_id=doc.id,
            integrity_status=_status_for_flag(integrity_ok),
            ingestion_status=_status_for_flag(ingestion_ok),
            control_mapping_status=_status_for_flag(mapping_ok),
            retrieval_status=_status_for_flag(retrieval_ok),
            details_json=details,
        )
        results.append(result)
        db.add(result)

    document_count = len(docs)
    ratios = {
        "integrity_ratio": _score_ratio(integrity_passed, document_count),
        "ingestion_ratio": _score_ratio(ingestion_complete, document_count),
        "mapping_ratio": _score_ratio(mapped_documents, document_count),
        "retrieval_ratio": _score_ratio(retrieval_viable, document_count),
    }
    viability_score = round(
        (
            ratios["integrity_ratio"] * 0.25
            + ratios["ingestion_ratio"] * 0.30
            + ratios["mapping_ratio"] * 0.20
            + ratios["retrieval_ratio"] * 0.25
        )
        * 100,
        1,
    )

    status_counter = Counter(
        "healthy"
        if r.integrity_status == "pass" and r.ingestion_status == "pass" and r.retrieval_status == "pass"
        else "weak"
        for r in results
    )
    validation_summary = {
        "document_count": document_count,
        "status": "complete",
        "integrity_passed": integrity_passed,
        "ingestion_complete": ingestion_complete,
        "mapped_documents": mapped_documents,
        "retrieval_viable": retrieval_viable,
        "healthy_documents": status_counter.get("healthy", 0),
        "weak_documents_count": status_counter.get("weak", 0),
        "weak_documents": weak_documents[:25],
        **ratios,
    }
    validation_run.status = "complete"
    validation_run.summary_json = validation_summary

    viability_status = (
        "ready"
        if viability_score >= 85
        else "workable"
        if viability_score >= 60
        else "unlikely"
    )
    viability_summary = {
        "document_count": document_count,
        "viability_score": viability_score,
        "status": viability_status,
        "expected_profile": expected_profile,
        "validation_run_id": validation_run.id,
        **ratios,
        "weak_documents_count": status_counter.get("weak", 0),
    }
    viability_run = PackageViabilityRun(
        project_id=project_id,
        source_mode=source_mode,
        source_run_id=source_run_id,
        expected_profile=expected_profile,
        viability_score=viability_score,
        status=viability_status,
        summary_json=viability_summary,
    )
    db.add(viability_run)
    await db.commit()

    return {
        "validation_run_id": validation_run.id,
        "package_viability_run_id": viability_run.id,
        **validation_summary,
        "package_viability": viability_summary,
    }
