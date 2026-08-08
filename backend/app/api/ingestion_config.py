"""Admin API for ingestion pipeline configuration.

Endpoints:
  GET  /ingestion-config           — list all settings (secrets masked)
  PUT  /ingestion-config/{key}     — update a single setting
  POST /ingestion-config/test/voyage  — test Voyage API connectivity
  POST /ingestion-config/test/ollama  — test Ollama connectivity
  GET  /ingestion-config/audit     — recent audit log
  GET  /ingestion-config/runs/{doc_id}  — ingestion runs for a document
  POST /ingestion-config/reprocess/{doc_id}  — trigger reprocess
  GET  /ingestion-config/run-status/{run_id}  — run status detail
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_admin, require_assessor

from app.models.orm import (
    IngestionRun, IngestionConfigAudit, Document,
    EvidenceUnit, EvidenceClassification, ScreeningResult,
)
from app.services.ingestion.config_store import (
    get_config, get_secret, get_value, set_value, get_runtime_embedding_config, get_runtime_ollama_config,
    DEFAULTS, DESCRIPTIONS, SECRET_KEYS,
)
from app.services.ingestion.corpus_store import (
    activate_corpus,
    get_active_corpus,
    list_corpora,
    upsert_corpus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingestion-config", tags=["ingestion-config"])


def _parse_headers(raw: str) -> dict[str, str] | None:
    if not raw:
        return None
    try:
        import json

        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(key): str(value) for key, value in parsed.items()}
    except json.JSONDecodeError:
        return None
    return None


class ConfigUpdateRequest(BaseModel):
    value: str


class ActivateCorpusRequest(BaseModel):
    corpus_key: str


class CorpusUpsertRequest(BaseModel):
    corpus_key: str
    display_name: str
    version: str
    description: str | None = None
    family_keywords: dict[str, list[str]]
    control_keywords: dict[str, list[str]]


# ── GET all settings ──────────────────────────────────────────────────────────

@router.get("")
async def list_config(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    """Return all ingestion config settings. Secret values are masked as '***'."""
    values = await get_config(db)
    return {
        "settings": [
            {
                "key": key,
                "value": values.get(key, DEFAULTS.get(key, "")),
                "is_secret": key in SECRET_KEYS,
                "description": DESCRIPTIONS.get(key, ""),
                "default": DEFAULTS.get(key, ""),
            }
            for key in DEFAULTS
        ]
    }


# ── PUT single setting ────────────────────────────────────────────────────────

@router.put("/{key}")
async def update_config(
    key: str,
    body: ConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Update a single ingestion config setting."""
    if key not in DEFAULTS:
        raise HTTPException(status_code=404, detail=f"Unknown config key: {key}")
    if key == "active_corpus_key":
        try:
            await activate_corpus(db, body.value, changed_by_id=user.get("id"))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await db.commit()
        return {"ok": True, "key": key}
    await set_value(db, key, body.value, changed_by_id=user.get("id"))
    await db.commit()
    return {"ok": True, "key": key}


# ── Test Voyage connection ────────────────────────────────────────────────────

@router.post("/test/voyage")
async def test_voyage(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    """Test Voyage AI API connectivity using the stored API key."""
    api_key = await get_secret(db, "voyage_api_key")
    if not api_key:
        return {"ok": False, "error": "No Voyage API key configured"}
    model = await get_value(db, "voyage_model")
    base_url = await get_value(db, "voyage_base_url")
    from app.services.ingestion.voyage_embedder import test_connection
    result = await test_connection(api_key=api_key, model=model, base_url=base_url)
    return result


# ── Test Ollama connection ─────────────────────────────────────────────────────

@router.post("/test/ollama")
async def test_ollama(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    """Test Ollama connectivity and verify the reasoning model is available."""
    import json
    import httpx
    ollama_cfg = await get_runtime_ollama_config(db)
    headers = {"Content-Type": "application/json"}
    if ollama_cfg["api_key"]:
        headers["Authorization"] = f"Bearer {ollama_cfg['api_key']}"
    if ollama_cfg["headers_json"]:
        try:
            parsed = json.loads(ollama_cfg["headers_json"])
            if isinstance(parsed, dict):
                headers.update({str(k): str(v) for k, v in parsed.items()})
        except json.JSONDecodeError:
            return {"ok": False, "error": "Invalid JSON in ollama_headers_json", "base_url": ollama_cfg["base_url"]}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ollama_cfg['base_url'].rstrip('/')}/api/tags", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            available = [m["name"] for m in data.get("models", [])]
            model = ollama_cfg["model"]
            model_found = any(m.startswith(model.split(":")[0]) for m in available)
            return {
                "ok": True,
                "base_url": ollama_cfg["base_url"],
                "connection_mode": ollama_cfg["connection_mode"],
                "model": model,
                "model_available": model_found,
                "available_models": available[:10],
            }
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "base_url": ollama_cfg["base_url"]}


@router.post("/test/embedding")
async def test_embedding_provider(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    """Test the active embedding provider using the configured model and endpoint."""
    embed_cfg = await get_runtime_embedding_config(db)
    provider = embed_cfg["provider"]
    if provider == "voyage":
        if not embed_cfg["api_key"]:
            return {"ok": False, "error": "No Voyage API key configured", "provider": provider}
        from app.services.ingestion.voyage_embedder import test_connection

        result = await test_connection(
            api_key=embed_cfg["api_key"],
            model=embed_cfg["model"],
            base_url=embed_cfg["base_url"],
        )
        result["provider"] = provider
        return result

    from app.services.ingestion.ollama_embedder import test_connection

    result = await test_connection(
        model=embed_cfg["model"],
        base_url=embed_cfg["base_url"],
        api_key=embed_cfg["api_key"],
        extra_headers=_parse_headers(embed_cfg["headers_json"]),
    )
    result["provider"] = provider
    return result



# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit_log(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    """Return recent config change audit entries."""
    result = await db.execute(
        select(IngestionConfigAudit)
        .order_by(IngestionConfigAudit.changed_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return {
        "entries": [
            {
                "id": r.id,
                "key": r.config_key,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "changed_by": r.changed_by,
                "changed_at": r.changed_at.isoformat() if r.changed_at else None,
            }
            for r in rows
        ]
    }


@router.get("/corpora")
async def get_corpora(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    corpora = await list_corpora(db)
    active = await get_active_corpus(db)
    await db.commit()
    return {
        "active_corpus_key": active.corpus_key,
        "corpora": [
            {
                "corpus_key": corpus.corpus_key,
                "display_name": corpus.display_name,
                "version": corpus.version,
                "description": corpus.description,
                "is_active": corpus.is_active,
                "created_at": corpus.created_at.isoformat() if corpus.created_at else None,
            }
            for corpus in corpora
        ],
    }


@router.post("/corpora/activate")
async def set_active_corpus(
    body: ActivateCorpusRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    try:
        corpus = await activate_corpus(db, body.corpus_key, changed_by_id=user.get("id"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return {"ok": True, "active_corpus_key": corpus.corpus_key, "version": corpus.version}


@router.post("/corpora")
async def import_corpus(
    body: CorpusUpsertRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    payload = body.model_dump()
    try:
        corpus = await upsert_corpus(db, payload, changed_by_id=user.get("id"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return {"ok": True, "corpus_key": corpus.corpus_key, "version": corpus.version}


# ── Ingestion runs for a document ─────────────────────────────────────────────

@router.get("/runs/{document_id}")
async def get_runs_for_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    """Return all ingestion runs for a document, newest first."""
    result = await db.execute(
        select(IngestionRun)
        .where(IngestionRun.document_id == document_id)
        .order_by(IngestionRun.started_at.desc())
    )
    runs = result.scalars().all()
    return {"runs": [_run_dict(r) for r in runs]}


@router.get("/run-status/{run_id}")
async def get_run_status(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    run = await db.get(IngestionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_dict(run)


# ── Reprocess a document ──────────────────────────────────────────────────────

@router.post("/reprocess/{document_id}")
async def reprocess_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Trigger a new ingestion run for a document (full reprocess)."""
    import asyncio
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    from app.services.ingestion.pipeline import run_ingestion_pipeline
    asyncio.create_task(run_ingestion_pipeline(
        document_id=document_id,
        triggered_by=user.get("id"),
    ))
    return {"ok": True, "message": f"Reprocessing started for document {document_id}"}


@router.post("/resume/{run_id}")
async def resume_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    run = await db.get(IngestionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"failed", "running"}:
        raise HTTPException(status_code=400, detail="Only failed or in-progress runs can be resumed")

    import asyncio
    from app.services.ingestion.pipeline import run_ingestion_pipeline

    asyncio.create_task(
        run_ingestion_pipeline(
            document_id=run.document_id,
            triggered_by=user.get("id"),
            resume_run_id=run_id,
        )
    )
    return {"ok": True, "message": f"Resume started for run {run_id}"}


# ── Document pipeline report ──────────────────────────────────────────────────

@router.get("/document-report/{document_id}")
async def get_document_report(
    document_id: int,
    limit: int = 30,
    offset: int = 0,
    control_filter: str | None = None,
    strength_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_assessor),
):
    """Return pipeline quality report for a document.

    Includes: latest run stats, control distribution across all evidence units,
    and a paginated list of evidence units with their Ollama classifications.
    """
    # Latest run for this document
    run_result = await db.execute(
        select(IngestionRun)
        .where(IngestionRun.document_id == document_id)
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )
    run = run_result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No ingestion run found for this document")

    # Document metadata
    doc = await db.get(Document, document_id)

    # Lines above threshold count
    threshold_result = await db.execute(
        select(ScreeningResult)
        .join(EvidenceUnit, ScreeningResult.line_id == EvidenceUnit.trigger_line_id)
        .where(EvidenceUnit.run_id == run.id)
        .where(ScreeningResult.above_threshold == True)  # noqa: E712
    )
    lines_above_threshold = len(threshold_result.scalars().all())

    # Full list of units+classifications for control distribution
    all_units_result = await db.execute(
        select(EvidenceUnit, EvidenceClassification)
        .outerjoin(EvidenceClassification, EvidenceClassification.unit_id == EvidenceUnit.id)
        .where(EvidenceUnit.run_id == run.id)
    )
    all_rows = all_units_result.all()

    # Build control distribution from ALL units
    control_dist: dict[str, dict] = {}
    artifact_counts: dict[str, int] = {}
    strength_counts: dict[str, int] = {"strong": 0, "moderate": 0, "weak": 0, "insufficient": 0}

    for unit, cls in all_rows:
        if cls:
            # Artifact type tally
            at = cls.artifact_type or "other"
            artifact_counts[at] = artifact_counts.get(at, 0) + 1
            # Strength tally
            st = cls.evidence_strength or "weak"
            if st in strength_counts:
                strength_counts[st] += 1
            # Control distribution
            for ctrl in (cls.control_ids or []):
                if ctrl not in control_dist:
                    control_dist[ctrl] = {"count": 0, "strong": 0, "moderate": 0, "weak": 0}
                control_dist[ctrl]["count"] += 1
                if st in control_dist[ctrl]:
                    control_dist[ctrl][st] += 1

    control_distribution = sorted(
        [{"control_id": k, **v} for k, v in control_dist.items()],
        key=lambda x: x["count"],
        reverse=True,
    )

    # Paginated units with optional filters
    units_query = (
        select(EvidenceUnit, EvidenceClassification)
        .outerjoin(EvidenceClassification, EvidenceClassification.unit_id == EvidenceUnit.id)
        .where(EvidenceUnit.run_id == run.id)
    )
    if control_filter:
        # Filter units where control_ids JSON array contains the given control
        from sqlalchemy import cast, String
        units_query = units_query.where(
            EvidenceClassification.control_ids.cast(String).contains(control_filter)
        )
    if strength_filter:
        units_query = units_query.where(
            EvidenceClassification.evidence_strength == strength_filter
        )

    total_filtered_result = await db.execute(units_query)
    total_filtered = len(total_filtered_result.all())

    paged_result = await db.execute(
        units_query.order_by(EvidenceUnit.id).offset(offset).limit(limit)
    )
    paged_rows = paged_result.all()

    units_data = []
    for unit, cls in paged_rows:
        u = {
            "id": unit.id,
            "content": unit.content[:600] if unit.content else "",
            "content_truncated": len(unit.content) > 600 if unit.content else False,
            "section_path": unit.section_path,
            "page_numbers": unit.page_numbers,
            "token_count": unit.token_count,
            "classification": None,
        }
        if cls:
            u["classification"] = {
                "control_ids": cls.control_ids or [],
                "enhancement_ids": cls.enhancement_ids or [],
                "artifact_type": cls.artifact_type,
                "evidence_strength": cls.evidence_strength,
                "evidence_language_type": cls.evidence_language_type,
                "explanation": cls.explanation,
                "model_confidence": cls.model_confidence,
                "model_name": cls.model_name,
            }
        units_data.append(u)

    return {
        "document": {
            "id": doc.id if doc else document_id,
            "filename": doc.filename if doc else None,
            "document_type": doc.document_type if doc else None,
            "parse_status": doc.parse_status if doc else None,
        },
        "run": _run_dict(run),
        "funnel": {
            "lines_parsed": run.lines_parsed or 0,
            "lines_screened": run.lines_screened or 0,
            "lines_above_threshold": lines_above_threshold,
            "evidence_units": run.evidence_units_created or 0,
            "units_classified": run.units_classified or 0,
            "units_embedded": run.units_embedded or 0,
        },
        "artifact_counts": artifact_counts,
        "strength_counts": strength_counts,
        "control_distribution": control_distribution,
        "evidence_units": units_data,
        "total_filtered": total_filtered,
        "total_units": run.evidence_units_created or 0,
    }


def _run_dict(r: IngestionRun) -> dict:
    return {
        "id": r.id,
        "document_id": r.document_id,
        "status": r.status,
        "corpus_version": r.corpus_version,
        "current_stage": r.current_stage,
        "stages": {
            "parse":    r.stage_parse,
            "screen":   r.stage_screen,
            "expand":   r.stage_expand,
            "classify": r.stage_classify,
            "embed":    r.stage_embed,
        },
        "counts": {
            "lines_parsed":          r.lines_parsed,
            "lines_screened":        r.lines_screened,
            "evidence_units":        r.evidence_units_created,
            "units_classified":      r.units_classified,
            "units_embedded":        r.units_embedded,
        },
        "error_message": r.error_message,
        "error_stage":   r.error_stage,
        "started_at":    r.started_at.isoformat() if r.started_at else None,
        "completed_at":  r.completed_at.isoformat() if r.completed_at else None,
    }
