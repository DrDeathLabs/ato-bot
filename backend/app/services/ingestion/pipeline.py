"""NIST 800-53 evidence ingestion pipeline — main orchestrator.

Replaces the legacy dispatch_parse + tag_document flow.

Stage order:
  1. parse    — extract line-level records from the document file
  2. screen   — keyword relevance screening of every line
  3. expand   — context expansion for lines above threshold
  4. classify — Ollama reasoning classification of evidence units
  5. embed    — Voyage AI embeddings for evidence units

Each stage persists its output before the next stage begins.
A failure in any stage updates the run record with the error and stage,
then stops. The run can be resumed from the failed stage.

The pipeline persists parsed lines, screening results, evidence units,
classifications, and embeddings as the canonical evidence system.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.orm import (
    Document,
    IngestionRun, ParsedLine, ScreeningResult,
    EvidenceUnit, EvidenceClassification, EvidenceEmbedding,
    ParsedDocumentRecord,
)

logger = logging.getLogger(__name__)

# Global semaphore — limit concurrent ingestion runs (heavy LLM calls)
_INGESTION_SEMAPHORE = asyncio.Semaphore(3)
_OLLAMA_CLASSIFY_SEMAPHORE = asyncio.Semaphore(3)
_SCREEN_SEMAPHORE_LOCK = asyncio.Lock()
_SCREEN_SEMAPHORES: dict[int, asyncio.Semaphore] = {}
_CLASSIFY_SEMAPHORE_LOCK = asyncio.Lock()
_CLASSIFY_SEMAPHORES: dict[int, asyncio.Semaphore] = {}
_EMBED_SEMAPHORE_LOCK = asyncio.Lock()
_EMBED_SEMAPHORES: dict[tuple[str, int], asyncio.Semaphore] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def cleanup_stale_ingestion_runs(
    db: AsyncSession,
    *,
    max_age_hours: int = 1,
) -> int:
    """Mark abandoned running ingestion runs as failed.

    This catches runs left in ``running`` after crashes, container restarts,
    or task interruption so they do not stay open forever and distort
    monitoring telemetry.
    """
    threshold = _utcnow() - timedelta(hours=max(1, int(max_age_hours)))
    result = await db.execute(
        select(IngestionRun).where(
            IngestionRun.status == "running",
            IngestionRun.started_at <= threshold,
        )
    )
    stale_runs = result.scalars().all()
    if not stale_runs:
        return 0

    document_ids = {run.document_id for run in stale_runs if run.document_id}
    docs_by_id: dict[int, Document] = {}
    if document_ids:
        docs_result = await db.execute(select(Document).where(Document.id.in_(document_ids)))
        docs_by_id = {doc.id: doc for doc in docs_result.scalars().all()}

    stage_order = ["parse", "screen", "expand", "classify", "embed"]
    now = _utcnow()
    for run in stale_runs:
        current_stage = run.current_stage or _first_incomplete_stage(run, stage_order)
        if current_stage:
            setattr(run, f"stage_{current_stage}", "failed")
        run.status = "failed"
        run.error_stage = current_stage
        run.error_message = (
            f"Ingestion run was marked failed after exceeding the {max_age_hours}-hour "
            "stale-run threshold."
        )
        run.completed_at = now
        doc = docs_by_id.get(run.document_id)
        if doc and doc.parse_status == "processing":
            doc.parse_status = "failed"
            doc.parse_error = run.error_message

    await db.commit()
    return len(stale_runs)


async def run_ingestion_pipeline(
    document_id: int,
    triggered_by: int | None = None,
    resume_run_id: int | None = None,
) -> int:
    """Entry point for the full ingestion pipeline.

    Creates (or resumes) an IngestionRun, then runs all 5 stages.
    Returns the run_id.
    """
    async with _INGESTION_SEMAPHORE:
        stage_order = ["parse", "screen", "expand", "classify", "embed"]
        async with AsyncSessionLocal() as db:
            from app.core.config import get_settings

            settings = get_settings()
            cleaned = await cleanup_stale_ingestion_runs(
                db,
                max_age_hours=settings.stale_ingestion_run_hours,
            )
            if cleaned:
                logger.warning("Marked %d stale ingestion run(s) failed before starting a new run", cleaned)
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one_or_none()
            if not doc:
                logger.error("Document %d not found for ingestion", document_id)
                return -1

            run = None
            if resume_run_id:
                run_result = await db.execute(
                    select(IngestionRun).where(IngestionRun.id == resume_run_id)
                )
                run = run_result.scalar_one_or_none()
                if not run:
                    resume_run_id = None

            if not resume_run_id:
                from app.services.ingestion.config_store import get_config
                from app.services.ingestion.corpus_store import get_active_corpus

                config_snap = await get_config(db)
                config_snap = {k: ("***" if v == "***" else v) for k, v in config_snap.items()}
                active_corpus = await get_active_corpus(db)

                run = IngestionRun(
                    document_id=document_id,
                    config_snapshot=config_snap,
                    corpus_version=active_corpus.version,
                    status="running",
                    current_stage="parse",
                    triggered_by=triggered_by,
                )
                db.add(run)
                await db.commit()
                await db.refresh(run)
            else:
                run.status = "running"
                run.error_message = None
                run.completed_at = None
                await db.commit()

        run_id = run.id

        # Update document parse_status
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one_or_none()
            if doc:
                doc.parse_status = "processing"
                doc.parse_error = None
                await db.commit()

        try:
            for stage_name, stage_func in [
                ("parse", _stage_parse),
                ("screen", _stage_screen),
                ("expand", _stage_expand),
                ("classify", _stage_classify),
                ("embed", _stage_embed),
            ]:
                async with AsyncSessionLocal() as db:
                    current_run = await db.get(IngestionRun, run_id)
                    if current_run is None:
                        raise RuntimeError(f"Ingestion run {run_id} disappeared")
                    if getattr(current_run, f"stage_{stage_name}") == "complete":
                        continue
                await stage_func(run_id, document_id)

            async with AsyncSessionLocal() as db:
                r = await db.get(IngestionRun, run_id)
                if r:
                    r.status = "complete"
                    r.current_stage = None
                    r.error_stage = None
                    r.error_message = None
                    r.completed_at = _utcnow()
                result2 = await db.execute(select(Document).where(Document.id == document_id))
                doc2 = result2.scalar_one_or_none()
                if doc2:
                    doc2.parse_status = "indexed"
                    doc2.parse_error = None
                await db.commit()

        except Exception as exc:
            logger.error("Ingestion pipeline failed for doc %d run %d: %s", document_id, run_id, exc)
            async with AsyncSessionLocal() as db:
                r = await db.get(IngestionRun, run_id)
                if r:
                    r.status = "failed"
                    if not r.error_stage:
                        current_stage = r.current_stage or _first_incomplete_stage(r, stage_order)
                        r.error_stage = current_stage
                        if current_stage:
                            setattr(r, f"stage_{current_stage}", "failed")
                    r.error_message = str(exc)[:500]
                    r.completed_at = _utcnow()
                result3 = await db.execute(select(Document).where(Document.id == document_id))
                doc3 = result3.scalar_one_or_none()
                if doc3:
                    doc3.parse_status = "failed"
                    doc3.parse_error = str(exc)[:500]
                await db.commit()

        return run_id


# -- Stage 1: Parse ------------------------------------------------------------

async def _stage_parse(run_id: int, document_id: int) -> None:
    """Extract line-level records and save as ParsedLine rows."""
    logger.info("Ingestion run %d: stage_parse starting for doc %d", run_id, document_id)

    async with AsyncSessionLocal() as db:
        await _set_stage(db, run_id, "stage_parse", "running", current="parse")

        result = await db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            raise RuntimeError(f"Document {document_id} not found")

        # Parse file
        from app.services.parsers.dispatcher import parse_document
        from app.services.ingestion.line_parser import extract_lines
        parsed = parse_document(doc.file_path)
        if not parsed.success:
            raise RuntimeError(f"Parse failed: {parsed.error}")

        doc.page_count = len(parsed.pages) or 1

        parsed_doc = ParsedDocumentRecord(
            run_id=run_id,
            document_id=document_id,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            parser_metadata=parsed.metadata,
            source_filename=parsed.filename,
            file_type=parsed.file_type,
            page_count=len(parsed.pages) or 1,
        )
        db.add(parsed_doc)

        line_records = extract_lines(parsed)

        db_lines = []
        for lr in line_records:
            pl = ParsedLine(
                run_id=run_id,
                document_id=document_id,
                line_number=lr.line_number,
                page_number=lr.page_number,
                section_path=lr.section_path,
                block_id=lr.block_id,
                block_type=lr.block_type,
                table_id=lr.table_id,
                row_index=lr.row_index,
                col_index=lr.col_index,
                cell_label=lr.cell_label,
                content_type=lr.content_type,
                content=lr.content,
            )
            db.add(pl)
            db_lines.append(pl)

        run = await db.get(IngestionRun, run_id)
        if run:
            run.lines_parsed = len(db_lines)

        await db.commit()
        await _set_stage(db, run_id, "stage_parse", "complete")

    logger.info("Ingestion run %d: stage_parse complete — %d lines", run_id, len(line_records))


# -- Stage 2: Screen -----------------------------------------------------------

async def _stage_screen(run_id: int, document_id: int) -> None:
    """Screen every ParsedLine for NIST control relevance."""
    logger.info("Ingestion run %d: stage_screen starting", run_id)

    async with AsyncSessionLocal() as db:
        await _set_stage(db, run_id, "stage_screen", "running", current="screen")

        from app.services.ingestion.config_store import (
            get_int_value,
            get_runtime_ollama_config,
            get_screening_threshold,
            get_value,
        )
        from app.services.ingestion.corpus_store import get_active_corpus
        threshold = await get_screening_threshold(db)
        screen_mode = (await get_value(db, "screening_mode")).strip().lower() or "llm"
        batch_size = max(1, await get_int_value(db, "screening_batch_size"))
        max_concurrency = max(1, await get_int_value(db, "screening_max_concurrency"))
        timeout_secs = max(15, await get_int_value(db, "screening_timeout_secs"))
        screening_model = (await get_value(db, "ollama_screening_model")).strip()
        screening_reasoning_effort = (await get_value(db, "screening_reasoning_effort")).strip().lower()
        max_retries = await get_int_value(db, "max_retries")
        retry_delay_secs = await get_int_value(db, "retry_delay_secs")
        ollama_config = await get_runtime_ollama_config(db)
        if screening_model:
            ollama_config["model"] = screening_model
        if screening_reasoning_effort:
            ollama_config["reasoning_effort"] = screening_reasoning_effort
        active_corpus = await get_active_corpus(db)
        corpus_payload = active_corpus.corpus_json or {}

        # Load all ParsedLines for this run
        result = await db.execute(
            select(ParsedLine).where(
                ParsedLine.run_id == run_id,
                ParsedLine.document_id == document_id,
            ).order_by(ParsedLine.line_number)
        )
        lines = result.scalars().all()

        if screen_mode == "llm":
            screen_results = await _screen_lines_with_llm(
                lines=lines,
                ollama_config=ollama_config,
                timeout_secs=timeout_secs,
                batch_size=batch_size,
                max_concurrency=max_concurrency,
                threshold=threshold,
                max_retries=max_retries,
                retry_delay_secs=retry_delay_secs,
            )
        else:
            from app.services.ingestion.corpus import screen_line

            screen_results = []
            for line in lines:
                result_dict = screen_line(
                    line.content,
                    threshold=threshold,
                    corpus_payload=corpus_payload,
                )
                screen_results.append((line.id, result_dict))

        screened = 0
        for line_id, result_dict in screen_results:
            sr = ScreeningResult(
                line_id=line_id,
                run_id=run_id,
                relevance_score=result_dict["relevance_score"],
                candidate_controls=result_dict["candidate_controls"],
                candidate_enhancements=result_dict["candidate_enhancements"],
                rationale=result_dict["rationale"],
                above_threshold=result_dict["above_threshold"],
            )
            db.add(sr)
            screened += 1

            # Flush in batches to avoid large transaction
            if screened % 500 == 0:
                await db.flush()

        run = await db.get(IngestionRun, run_id)
        if run:
            run.lines_screened = screened
            run.corpus_version = active_corpus.version

        await db.commit()
        await _set_stage(db, run_id, "stage_screen", "complete")

    logger.info("Ingestion run %d: stage_screen complete — %d lines screened", run_id, screened)


# -- Stage 3: Expand -----------------------------------------------------------

async def _stage_expand(run_id: int, document_id: int) -> None:
    """Build EvidenceUnits from lines that crossed the screening threshold."""
    logger.info("Ingestion run %d: stage_expand starting", run_id)

    async with AsyncSessionLocal() as db:
        await _set_stage(db, run_id, "stage_expand", "running", current="expand")

        from app.services.ingestion.config_store import get_int_value
        window = await get_int_value(db, "expand_window_lines")
        max_tokens = await get_int_value(db, "expand_max_tokens")

        # Load all lines for this run as dicts (for expander)
        lines_result = await db.execute(
            select(ParsedLine).where(ParsedLine.run_id == run_id).order_by(ParsedLine.line_number)
        )
        all_lines_orm = lines_result.scalars().all()
        all_lines_dicts = [
            {
                "id": ln.id,
                "line_number": ln.line_number,
                "page_number": ln.page_number,
                "section_path": ln.section_path,
                "block_id": ln.block_id,
                "block_type": ln.block_type,
                "table_id": ln.table_id,
                "row_index": ln.row_index,
                "col_index": ln.col_index,
                "cell_label": ln.cell_label,
                "content_type": ln.content_type,
                "content": ln.content,
            }
            for ln in all_lines_orm
        ]
        line_id_to_idx = {ln["id"]: i for i, ln in enumerate(all_lines_dicts)}

        # Load screening results that are above threshold
        sr_result = await db.execute(
            select(ScreeningResult).where(
                ScreeningResult.run_id == run_id,
                ScreeningResult.above_threshold == True,  # noqa: E712
            )
            .order_by(ScreeningResult.relevance_score.desc(), ScreeningResult.id)
        )
        threshold_lines = sr_result.scalars().all()

        from app.services.ingestion.expander import expand_line

        # Deduplicate: if two trigger lines expand to overlapping content,
        # keep only one unit per unique expanded context to avoid redundant
        # classify/embed work on identical table rows or logical blocks.
        units_created = 0
        seen_expansions: set[tuple] = set()
        for sr in threshold_lines:
            idx = line_id_to_idx.get(sr.line_id)
            if idx is None:
                continue

            expansion = expand_line(idx, all_lines_dicts, window=window, max_tokens=max_tokens)
            expansion_key = (
                tuple(expansion.source_line_ids),
                expansion.section_path,
                expansion.content,
            )
            if expansion_key in seen_expansions:
                continue
            seen_expansions.add(expansion_key)

            unit = EvidenceUnit(
                run_id=run_id,
                document_id=document_id,
                trigger_line_id=expansion.trigger_line_id,
                source_line_ids=expansion.source_line_ids,
                content=expansion.content,
                page_numbers=expansion.page_numbers,
                section_path=expansion.section_path,
                table_coordinates=expansion.table_coordinates,
                token_count=expansion.token_count,
            )
            db.add(unit)
            units_created += 1

            if units_created % 100 == 0:
                await db.flush()

        run = await db.get(IngestionRun, run_id)
        if run:
            run.evidence_units_created = units_created

        await db.commit()
        await _set_stage(db, run_id, "stage_expand", "complete")

    logger.info("Ingestion run %d: stage_expand complete — %d units", run_id, units_created)


# -- Stage 4: Classify ---------------------------------------------------------

async def _stage_classify(run_id: int, document_id: int) -> None:
    """Classify each EvidenceUnit using the Ollama reasoning model."""
    logger.info("Ingestion run %d: stage_classify starting", run_id)
    from app.services.evidence_profiles import normalize_autogenerated_profile

    async with AsyncSessionLocal() as db:
        await _set_stage(db, run_id, "stage_classify", "running", current="classify")

        from app.services.ingestion.config_store import get_int_value, get_runtime_ollama_config, get_value
        ollama_config = await get_runtime_ollama_config(db)
        classify_reasoning_effort = await get_value(db, "classify_reasoning_effort")
        classify_model = await get_value(db, "ollama_classify_model")
        classify_max_concurrency = max(1, await get_int_value(db, "classify_max_concurrency"))
        batch_size = await get_int_value(db, "classify_batch_size")
        timeout_secs = await get_int_value(db, "classify_timeout_secs")
        max_retries = await get_int_value(db, "max_retries")
        retry_delay_secs = await get_int_value(db, "retry_delay_secs")

        units_result = await db.execute(
            select(EvidenceUnit, EvidenceClassification, Document)
            .join(Document, Document.id == EvidenceUnit.document_id)
            .outerjoin(EvidenceClassification, EvidenceClassification.unit_id == EvidenceUnit.id)
            .where(EvidenceUnit.run_id == run_id)
            .order_by(EvidenceUnit.id)
        )
        units_to_classify = []
        unit_docs: dict[int, Document] = {}
        classified = 0
        for unit, existing_classification, doc in units_result.all():
            if existing_classification is not None:
                classified += 1
                continue
            units_to_classify.append(unit)
            unit_docs[unit.id] = doc

        sr_by_trigger: dict[int, list[str]] = {}
        sr_result = await db.execute(
            select(ScreeningResult).where(ScreeningResult.run_id == run_id)
        )
        for sr in sr_result.scalars().all():
            sr_by_trigger[sr.line_id] = sr.candidate_controls or []

    from app.services.ingestion.classifier import classify_units_batch
    ollama_headers = _parse_json_headers(ollama_config["headers_json"])
    classify_semaphore = await _get_classify_semaphore(classify_max_concurrency)
    classify_model = (classify_model or "gpt-oss:20b-cloud").strip()
    reasoning_effort = classify_reasoning_effort or ollama_config["reasoning_effort"]
    batches = [units_to_classify[i: i + batch_size] for i in range(0, len(units_to_classify), batch_size)]
    batch_results = await asyncio.gather(*[
        _classify_batch_with_limit(
            batch=batch,
            sr_by_trigger=sr_by_trigger,
            classify_units_batch=classify_units_batch,
            ollama_config=ollama_config,
            classify_model=classify_model,
            ollama_headers=ollama_headers,
            timeout_secs=timeout_secs,
            max_retries=max_retries,
            retry_delay_secs=retry_delay_secs,
            classify_semaphore=classify_semaphore,
            reasoning_effort=reasoning_effort,
        )
        for batch in batches
    ])

    async with AsyncSessionLocal() as db:
        for batch, cls_results in zip(batches, batch_results):
            for unit, cls_result in zip(batch, cls_results):
                doc = unit_docs.get(unit.id)
                if doc is not None:
                    cls_result = {
                        **cls_result,
                        **normalize_autogenerated_profile(
                            doc,
                            cls_result.get("artifact_type"),
                            cls_result.get("evidence_strength"),
                            cls_result.get("evidence_language_type"),
                        ),
                    }
                db.add(
                    EvidenceClassification(
                        unit_id=unit.id,
                        run_id=run_id,
                        control_ids=cls_result["control_ids"],
                        enhancement_ids=cls_result["enhancement_ids"],
                        artifact_type=cls_result["artifact_type"],
                        evidence_strength=cls_result["evidence_strength"],
                        evidence_language_type=cls_result["evidence_language_type"],
                        explanation=cls_result["explanation"],
                        model_name=cls_result["model_name"],
                        model_confidence=cls_result["confidence"],
                    )
                )
                classified += 1
        await db.commit()

    async with AsyncSessionLocal() as db:
        run = await db.get(IngestionRun, run_id)
        if run:
            run.units_classified = classified
        await db.commit()
        await _set_stage(db, run_id, "stage_classify", "complete")

    logger.info("Ingestion run %d: stage_classify complete — %d units classified", run_id, classified)


# -- Stage 5: Embed ------------------------------------------------------------

async def _stage_embed(run_id: int, document_id: int) -> None:
    """Generate embeddings for all EvidenceUnits using the active provider."""
    logger.info("Ingestion run %d: stage_embed starting", run_id)

    async with AsyncSessionLocal() as db:
        await _set_stage(db, run_id, "stage_embed", "running", current="embed")

        from app.services.ingestion.config_store import get_int_value, get_runtime_embedding_config
        embed_config = await get_runtime_embedding_config(db)
        provider = embed_config["provider"]
        api_key = embed_config["api_key"]
        model = embed_config["model"]
        base_url = embed_config["base_url"]
        embed_max_concurrency = max(1, int(embed_config["max_concurrency"]))
        provider_rate_limit_backoff_secs = max(0, await get_int_value(db, "voyage_rate_limit_backoff_secs"))
        batch_size = await get_int_value(db, "embed_batch_size")
        timeout_secs = await get_int_value(db, "embed_timeout_secs")
        max_retries = await get_int_value(db, "max_retries")
        retry_delay_secs = await get_int_value(db, "retry_delay_secs")

    if provider == "voyage" and not api_key:
        logger.info("Ingestion run %d: no Voyage API key configured — skipping embeddings", run_id)
        async with AsyncSessionLocal() as db:
            await _set_stage(db, run_id, "stage_embed", "complete", current="embed")
        return

    async with AsyncSessionLocal() as db:
        units_result = await db.execute(
            select(EvidenceUnit, EvidenceEmbedding)
            .outerjoin(EvidenceEmbedding, EvidenceEmbedding.unit_id == EvidenceUnit.id)
            .where(EvidenceUnit.run_id == run_id)
            .order_by(EvidenceUnit.id)
        )
        units = []
        embedded = 0
        active_model_name = _canonical_embedding_model_name(provider, model)
        for unit, existing_embedding in units_result.all():
            if (
                existing_embedding
                and existing_embedding.embedding is not None
                and existing_embedding.model_name == active_model_name
            ):
                embedded += 1
                continue
            units.append({
                "unit_id": unit.id,
                "content": unit.content,
                "existing_embedding_id": existing_embedding.id if existing_embedding else None,
            })

    embed_headers = _parse_json_headers(embed_config["headers_json"])
    embed_semaphore = await _get_embed_semaphore(provider, embed_max_concurrency)

    for i in range(0, len(units), batch_size):
        batch = units[i: i + batch_size]
        texts = [u["content"] for u in batch]
        async with embed_semaphore:
            vectors = await _run_with_retries(
                lambda: _embed_batch_or_raise(
                    provider=provider,
                    texts=texts,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    timeout_secs=timeout_secs,
                    rate_limit_backoff_secs=provider_rate_limit_backoff_secs,
                    extra_headers=embed_headers,
                ),
                attempts=max_retries,
                delay_secs=retry_delay_secs,
            )

        async with AsyncSessionLocal() as db:
            for unit_meta, vec in zip(batch, vectors):
                if unit_meta["existing_embedding_id"] is not None:
                    ee = await db.get(EvidenceEmbedding, unit_meta["existing_embedding_id"])
                    if ee is None:
                        raise RuntimeError(
                            f"Missing EvidenceEmbedding {unit_meta['existing_embedding_id']} during retry repair"
                        )
                    ee.model_name = active_model_name
                    ee.embedding = vec
                else:
                    db.add(
                        EvidenceEmbedding(
                            unit_id=unit_meta["unit_id"],
                            run_id=run_id,
                            model_name=active_model_name,
                            embedding=vec,
                        )
                    )
                embedded += 1
            await db.commit()

        await asyncio.sleep(0)

    async with AsyncSessionLocal() as db:
        run = await db.get(IngestionRun, run_id)
        if run:
            run.units_embedded = embedded
        await db.commit()
        await _set_stage(db, run_id, "stage_embed", "complete")

    logger.info("Ingestion run %d: stage_embed complete — %d embeddings", run_id, embedded)


# -- Helpers -------------------------------------------------------------------

async def _set_stage(
    db: AsyncSession,
    run_id: int,
    stage_field: str,
    status: str,
    current: str | None = None,
) -> None:
    run = await db.get(IngestionRun, run_id)
    if run:
        setattr(run, stage_field, status)
        if current:
            run.current_stage = current
        await db.commit()


def _first_incomplete_stage(run: IngestionRun, stage_order: list[str]) -> str | None:
    for stage in stage_order:
        if getattr(run, f"stage_{stage}") != "complete":
            return stage
    return None


def _normalize_screening_token(value: str | None) -> str:
    return (value or "").replace("_", " ").strip()


def _build_row_context_map(lines: list[ParsedLine]) -> dict[tuple[str, int], str]:
    rows: dict[tuple[str, int], list[str]] = {}
    for line in lines:
        if line.table_id is None or line.row_index is None:
            continue
        key = (line.table_id, line.row_index)
        value = (line.content or "").strip()
        if not value:
            continue
        label = _normalize_screening_token(line.cell_label)
        entry = f"{label}: {value}" if label else value
        rows.setdefault(key, []).append(entry)
    return {
        key: " | ".join(values[:8])
        for key, values in rows.items()
        if values
    }


def _build_screening_item(line: ParsedLine, row_context_map: dict[tuple[str, int], str]) -> dict:
    parts = []
    if line.page_number is not None:
        parts.append(f"Page or sheet: {line.page_number}")
    if line.section_path:
        parts.append(f"Section path: {line.section_path}")
    if line.content_type:
        parts.append(f"Content type: {line.content_type}")
    if line.block_type:
        parts.append(f"Block type: {line.block_type}")

    if line.content_type == "table_cell":
        header = _normalize_screening_token(line.cell_label)
        if header:
            parts.append(f"Field or header: {header}")
        parts.append(f"Value: {line.content}")
        if line.table_id is not None and line.row_index is not None:
            row_context = row_context_map.get((line.table_id, line.row_index))
            if row_context:
                parts.append(f"Row context: {row_context}")
    else:
        parts.append(f"Text: {line.content}")

    return {
        "item_id": line.id,
        "line_number": line.line_number,
        "excerpt": "\n".join(part for part in parts if part),
    }


async def _screen_batch_with_limit(
    batch_items: list[dict],
    ollama_config: dict[str, str],
    ollama_headers: dict | None,
    timeout_secs: int,
    max_retries: int,
    retry_delay_secs: int,
    screen_semaphore: asyncio.Semaphore,
) -> list[dict]:
    from app.services.ingestion.llm_screener import screen_batch

    async with screen_semaphore:
        return await _run_with_retries(
            lambda: screen_batch(
                items=batch_items,
                ollama_base_url=ollama_config["base_url"],
                model=ollama_config["model"],
                timeout_secs=timeout_secs,
                reasoning_effort=ollama_config["reasoning_effort"],
                api_key=ollama_config["api_key"],
                extra_headers=ollama_headers,
            ),
            attempts=max_retries,
            delay_secs=retry_delay_secs,
        )


async def _screen_lines_with_llm(
    lines: list[ParsedLine],
    ollama_config: dict[str, str],
    timeout_secs: int,
    batch_size: int,
    max_concurrency: int,
    threshold: float,
    max_retries: int,
    retry_delay_secs: int,
) -> list[tuple[int, dict]]:
    row_context_map = _build_row_context_map(lines)
    items = [_build_screening_item(line, row_context_map) for line in lines]
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    ollama_headers = _parse_json_headers(ollama_config["headers_json"])
    screen_semaphore = await _get_screen_semaphore(max_concurrency)

    results_by_batch = await asyncio.gather(*[
        _screen_batch_with_limit(
            batch_items=batch,
            ollama_config=ollama_config,
            ollama_headers=ollama_headers,
            timeout_secs=timeout_secs,
            max_retries=max_retries,
            retry_delay_secs=retry_delay_secs,
            screen_semaphore=screen_semaphore,
        )
        for batch in batches
    ]) if batches else []

    flattened: list[tuple[int, dict]] = []
    for batch_result in results_by_batch:
        for row in batch_result:
            score = float(row.get("relevance_score") or 0.0)
            flattened.append((
                row["item_id"],
                {
                    "relevance_score": round(score, 4),
                    "candidate_controls": row.get("candidate_controls") or [],
                    "candidate_enhancements": row.get("candidate_enhancements") or [],
                    "rationale": row.get("rationale") or "",
                    "above_threshold": score >= threshold,
                },
            ))
    return flattened


async def _classify_batch_with_limit(
    batch: list[EvidenceUnit],
    sr_by_trigger: dict[int, list[str]],
    classify_units_batch,
    ollama_config: dict[str, str],
    classify_model: str,
    ollama_headers: dict | None,
    timeout_secs: int,
    max_retries: int,
    retry_delay_secs: int,
    classify_semaphore: asyncio.Semaphore,
    reasoning_effort: str,
) -> list[dict]:
    items = [
        {
            "unit_id": unit.id,
            "content": unit.content,
            "candidate_controls": sr_by_trigger.get(unit.trigger_line_id, []),
            "section_path": unit.section_path,
        }
        for unit in batch
    ]
    async with classify_semaphore:
        try:
            return await _run_with_retries(
                lambda: classify_units_batch(
                    items=items,
                    ollama_base_url=ollama_config["base_url"],
                    model=classify_model or ollama_config["model"],
                    timeout_secs=timeout_secs,
                    reasoning_effort=reasoning_effort,
                    api_key=ollama_config["api_key"],
                    extra_headers=ollama_headers,
                ),
                attempts=max_retries,
                delay_secs=retry_delay_secs,
            )
        except Exception as exc:
            logger.warning("Classification failed for batch of %d units: %s", len(batch), type(exc).__name__)
            return [
                {
                    "control_ids": sr_by_trigger.get(unit.trigger_line_id, [])[:5],
                    "enhancement_ids": [],
                    "artifact_type": "other",
                    "evidence_strength": "weak",
                    "evidence_language_type": "mixed",
                    "explanation": f"Classification error: {type(exc).__name__}",
                    "confidence": None,
                    "model_name": classify_model or ollama_config["model"],
                }
                for unit in batch
            ]


async def _get_classify_semaphore(limit: int) -> asyncio.Semaphore:
    normalized_limit = max(1, int(limit))
    async with _CLASSIFY_SEMAPHORE_LOCK:
        semaphore = _CLASSIFY_SEMAPHORES.get(normalized_limit)
        if semaphore is None:
            semaphore = asyncio.Semaphore(normalized_limit)
            _CLASSIFY_SEMAPHORES[normalized_limit] = semaphore
        return semaphore


async def _get_screen_semaphore(limit: int) -> asyncio.Semaphore:
    normalized_limit = max(1, int(limit))
    async with _SCREEN_SEMAPHORE_LOCK:
        semaphore = _SCREEN_SEMAPHORES.get(normalized_limit)
        if semaphore is None:
            semaphore = asyncio.Semaphore(normalized_limit)
            _SCREEN_SEMAPHORES[normalized_limit] = semaphore
        return semaphore


async def _run_with_retries(factory, attempts: int, delay_secs: int):
    max_attempts = max(1, attempts)
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await factory()
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            retry_after_secs = getattr(exc, "retry_after_secs", None)
            base_delay = max(0, delay_secs) * (2 ** (attempt - 1))
            if retry_after_secs is not None:
                wait_secs = max(base_delay, max(0, retry_after_secs))
                logger.warning(
                    "Retrying after provider backoff (%ss requested, attempt %d/%d)",
                    wait_secs,
                    attempt,
                    max_attempts,
                )
            else:
                wait_secs = base_delay
            await asyncio.sleep(wait_secs)
    raise last_error


def _canonical_embedding_model_name(provider: str, model: str) -> str:
    return f"{provider.strip().lower()}:{model.strip()}"


async def _get_embed_semaphore(provider: str, limit: int) -> asyncio.Semaphore:
    normalized_provider = provider.strip().lower()
    normalized_limit = max(1, limit)
    key = (normalized_provider, normalized_limit)
    async with _EMBED_SEMAPHORE_LOCK:
        semaphore = _EMBED_SEMAPHORES.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(normalized_limit)
            _EMBED_SEMAPHORES[key] = semaphore
        return semaphore


async def _embed_batch_or_raise(
    provider: str,
    texts: list[str],
    api_key: str,
    model: str,
    base_url: str,
    timeout_secs: int,
    rate_limit_backoff_secs: int,
    extra_headers: dict | None,
):
    from app.services.ingestion.embedding_provider import embed_texts_for_provider

    vectors = await embed_texts_for_provider(
        provider=provider,
        texts=texts,
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_secs=timeout_secs,
        rate_limit_backoff_secs=rate_limit_backoff_secs,
        extra_headers=extra_headers,
    )
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"{provider} returned {len(vectors)} embeddings for {len(texts)} requested texts"
        )

    missing = [idx for idx, vec in enumerate(vectors) if vec is None]
    if missing:
        raise RuntimeError(
            f"{provider} returned null embeddings for {len(missing)} of {len(texts)} texts"
        )
    return vectors


def _parse_json_headers(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        import json

        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(key): str(value) for key, value in parsed.items()}
    except Exception:
        logger.warning("Invalid ollama_headers_json; ignoring custom headers")
    return None
