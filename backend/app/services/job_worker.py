from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.orm import Assessment, Document, RemediationReport, TestDatasetJob
from app.services.ingestion.pipeline import cleanup_stale_ingestion_runs

logger = logging.getLogger(__name__)
settings = get_settings()

T = TypeVar("T")


async def _recover_interrupted_work() -> None:
    """Re-queue durable jobs so the worker can resume them after restarts."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Assessment)
            .where(Assessment.status == "running")
            .values(
                status="pending",
                error_message=None,
                progress_detail="Resuming after worker restart...",
            )
        )
        await db.execute(
            update(RemediationReport)
            .where(RemediationReport.status == "running")
            .values(
                status="pending",
                error_message=None,
                progress_detail="Resuming after worker restart...",
            )
        )
        await db.execute(
            update(TestDatasetJob)
            .where(TestDatasetJob.status == "running")
            .values(
                status="pending",
                error_message=None,
                progress_detail="Resuming after worker restart...",
            )
        )
        await db.execute(
            update(Document)
            .where(Document.parse_status.in_(("processing", "indexing", "parsing")))
            .values(parse_status="pending")
        )
        stale_runs = await cleanup_stale_ingestion_runs(
            db,
            max_age_hours=settings.stale_ingestion_run_hours,
        )
        await db.commit()
    if stale_runs:
        logger.warning("Recovered %d stale ingestion run(s) on worker startup", stale_runs)


async def _claim_pending_assessment() -> int | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Assessment)
            .where(Assessment.status == "pending")
            .order_by(Assessment.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        assessment = result.scalar_one_or_none()
        if assessment is None:
            return None
        assessment.status = "running"
        assessment.error_message = None
        if not assessment.started_at:
            assessment.started_at = datetime.now(UTC)
        await db.commit()
        return assessment.id


async def _claim_pending_report() -> int | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RemediationReport)
            .where(RemediationReport.status == "pending")
            .order_by(RemediationReport.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        report = result.scalar_one_or_none()
        if report is None:
            return None
        report.status = "running"
        report.error_message = None
        if not report.progress_detail:
            report.progress_detail = "Queued on background worker..."
        await db.commit()
        return report.id


async def _claim_pending_test_dataset() -> tuple[int, int] | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TestDatasetJob)
            .where(TestDatasetJob.status == "pending")
            .order_by(TestDatasetJob.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return None
        job.status = "running"
        job.error_message = None
        if not job.progress_detail:
            job.progress_detail = "Queued on background worker..."
        await db.commit()
        return (job.id, job.project_id)


async def _claim_pending_document() -> int | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document)
            .where(Document.parse_status == "pending")
            .order_by(Document.created_at.asc(), Document.id.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        document = result.scalar_one_or_none()
        if document is None:
            return None
        document.parse_status = "processing"
        document.parse_error = None
        await db.commit()
        return document.id


async def _run_assessment_job(assessment_id: int) -> None:
    from app.services.assessment_engine import run_assessment

    await run_assessment(assessment_id)


async def _run_report_job(report_id: int) -> None:
    from app.services.remediation_service import run_remediation_report

    await run_remediation_report(report_id)


async def _run_test_dataset_job(job_info: tuple[int, int]) -> None:
    from app.services.test_dataset_generator import generate_test_dataset

    job_id, project_id = job_info
    await generate_test_dataset(job_id, project_id)


async def _run_document_job(document_id: int) -> None:
    from app.services.parsers.dispatcher import dispatch_parse

    await dispatch_parse(document_id)


def _reap_tasks(name: str, tasks: set[asyncio.Task[None]]) -> set[asyncio.Task[None]]:
    active: set[asyncio.Task[None]] = set()
    for task in tasks:
        if not task.done():
            active.add(task)
            continue
        try:
            task.result()
        except asyncio.CancelledError:
            logger.info("%s worker task cancelled", name)
        except Exception:
            logger.exception("%s worker task failed", name)
    return active


async def _pool_loop(
    *,
    name: str,
    concurrency: int,
    claim_next: Callable[[], Awaitable[T | None]],
    runner: Callable[[T], Awaitable[None]],
) -> None:
    slots = max(1, concurrency)
    poll_interval = max(0.1, float(settings.worker_poll_interval_secs))
    tasks: set[asyncio.Task[None]] = set()
    while True:
        tasks = _reap_tasks(name, tasks)
        started_any = False
        while len(tasks) < slots:
            item = await claim_next()
            if item is None:
                break
            started_any = True
            tasks.add(asyncio.create_task(runner(item)))
        if not started_any:
            await asyncio.sleep(poll_interval)


async def run_worker() -> None:
    await _recover_interrupted_work()
    logger.info(
        "Background worker online (assessments=%d reports=%d test_dataset=%d ingestion=%d)",
        settings.worker_assessment_slots,
        settings.worker_report_slots,
        settings.worker_test_dataset_slots,
        settings.worker_ingestion_slots,
    )
    await asyncio.gather(
        _pool_loop(
            name="assessment",
            concurrency=settings.worker_assessment_slots,
            claim_next=_claim_pending_assessment,
            runner=_run_assessment_job,
        ),
        _pool_loop(
            name="remediation",
            concurrency=settings.worker_report_slots,
            claim_next=_claim_pending_report,
            runner=_run_report_job,
        ),
        _pool_loop(
            name="test-dataset",
            concurrency=settings.worker_test_dataset_slots,
            claim_next=_claim_pending_test_dataset,
            runner=_run_test_dataset_job,
        ),
        _pool_loop(
            name="ingestion",
            concurrency=settings.worker_ingestion_slots,
            claim_next=_claim_pending_document,
            runner=_run_document_job,
        ),
    )
